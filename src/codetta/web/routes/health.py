"""Library health: what's worth fixing across the library."""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Query

from codetta.core.health import (
    CATEGORIES as HEALTH_CATEGORIES,
)
from codetta.core.health import (
    CHECKS as HEALTH_CHECKS,
)
from codetta.core.health import (
    MB_RELEASE_KEYS,
    HealthStore,
    folder_has_image,
)
from codetta.core.health import (
    run as health_run,
)
from codetta.web.common import HealthIgnoreAllIn, HealthIssueIn, HealthSettingsIn


def register(app, shared) -> None:
    connections = shared.connections
    inbox = shared.inbox
    lib_index = shared.lib_index
    library = shared.library
    require_library = shared.require_library
    settings = shared.settings
    apply_per_file = shared.later("apply_per_file")  # defined in routes/activity.py

    health_store = HealthStore(settings.config_dir / "health.json")
    health_cache: dict = {"key": None, "data": None, "at": 0.0, "fixed": {}, "complete": False}
    health_lock = threading.Lock()

    health_compute_lock = threading.Lock()
    health_worker: dict = {"thread": None}

    def health_compute() -> None:
        with health_compute_lock:
            key = lib_index.version
            complete = lib_index.status().ready  # made from the whole library, not mid-way through the first scan
            inbox_folder = inbox.settings.folder
            skip = [inbox_folder] if inbox_folder and not inbox_folder.startswith("@") else []
            data = health_run(lib_index.iter_tracks(), folder_has_image(library.resolve),
                              lib_index.paths_with_any(MB_RELEASE_KEYS), skip)
            with health_lock:
                health_cache.update(data=data, key=key, at=time.time(), complete=complete)

    def health_data() -> dict:
        """Every issue. The first check waits for the answer; after that, a change to the library
        (or 10 minutes, for cover files) re-checks in the background while the last answer is
        shown, so a big library never makes anyone wait twice."""
        with health_lock:
            data = health_cache["data"]
            stale = health_cache["key"] != lib_index.version or time.time() - health_cache["at"] > 600
            partial = not health_cache["complete"] and lib_index.status().ready
        if data is None or partial:  # never show an answer from half a library once the whole one is read
            health_compute()
        elif stale and not (health_worker["thread"] and health_worker["thread"].is_alive()):
            health_worker["thread"] = threading.Thread(target=health_compute, name="codetta-health", daemon=True)
            health_worker["thread"].start()
        return health_cache["data"]

    def health_public(issue: dict) -> dict:
        """What the page needs: never the file lists or the planned changes themselves."""
        fix = issue.get("fix")
        return {k: v for k, v in issue.items() if k not in ("paths", "fix")} | {
            "fix": {"label": fix["label"], "summary": fix["summary"]} if fix else None}

    def health_visible() -> tuple[dict, list[dict], list[dict]]:
        data = health_data()
        # A fixed issue stays hidden until a check made after the fix confirms it's gone.
        fixed = {i for i, v in health_cache["fixed"].items() if (health_cache["key"] or 0) <= v}
        shown, ignored = [], []
        for issue in data["issues"]:
            if issue["check"] in health_store.disabled or issue["id"] in fixed:
                continue
            (ignored if issue["id"] in health_store.ignored else shown).append(issue)
        return data, shown, ignored

    HEALTH_PAGE = 200  # issues per answer; "Show more" asks for the next ones

    @app.get("/api/library-health")
    def get_health_route(category: str = Query("all", max_length=20), offset: int = Query(0, ge=0, le=1_000_000),
                         limit: int = Query(HEALTH_PAGE, ge=1, le=1000)) -> dict:
        """Library health: things worth fixing, found from the search index. Issues come a page
        at a time (a big library can have thousands); ``count`` and the category counts are totals."""
        return get_health(category, offset, limit)

    def get_health(category: str = "all", offset: int = 0, limit: int = HEALTH_PAGE) -> dict:
        require_library()
        if not health_store.enabled:  # switched off: nothing is checked at all
            return {"enabled": False, "indexing": False, "albums": 0, "tracks": 0, "unmatched": None, "count": 0,
                    "categories": [], "checks": [], "issues": [], "ignored": []}
        data, shown, ignored = health_visible()
        return {
            "enabled": True,
            "indexing": not lib_index.status().ready,
            "albums": data["albums"], "tracks": data["tracks"],
            "unmatched": data["unmatched"] if connections.enabled("musicbrainz") else None,
            "count": len(shown),
            "categories": [{"id": c, "label": label, "count": sum(i["category"] == c for i in shown)}
                           for c, label in HEALTH_CATEGORIES.items()],
            "checks": [{"id": c.id, "category": c.category, "label": c.label, "about": c.about,
                        "enabled": c.id not in health_store.disabled} for c in HEALTH_CHECKS],
            "category": category, "offset": offset,
            "issues": [health_public(i) for i in (shown if category == "all" else [x for x in shown if x["category"] == category])[offset:offset + limit]],
            "shown_total": len(shown) if category == "all" else sum(x["category"] == category for x in shown),
            "ignored": [health_public(i) for i in ignored[:limit]],
            "ignored_total": len(ignored),
        }

    @app.get("/api/library-health/summary")
    def get_health_summary() -> dict:
        """Just the count (for the card on the Library page)."""
        require_library()
        if not health_store.enabled:
            return {"enabled": False, "count": 0, "indexing": False}
        _, shown, _ = health_visible()
        return {"enabled": True, "count": len(shown), "indexing": not lib_index.status().ready}

    @app.put("/api/library-health/settings")
    def put_health_settings(body: HealthSettingsIn) -> dict:
        known = {c.id for c in HEALTH_CHECKS}
        with health_store.lock:
            if body.enabled is not None:
                health_store.enabled = body.enabled
            if body.disabled is not None:
                health_store.disabled = {c for c in body.disabled if c in known}
        try:
            health_store.save()
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return get_health()

    @app.post("/api/library-health/ignore")
    def health_ignore(body: HealthIssueIn) -> dict:
        with health_store.lock:
            (health_store.ignored.add if body.ignore else health_store.ignored.discard)(body.id)
        try:
            health_store.save()
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return get_health()

    @app.post("/api/library-health/ignore-all")
    def health_ignore_all(body: HealthIgnoreAllIn) -> dict:
        """Ignore every issue on the list you're looking at (all of them, or one kind)."""
        require_library()
        _, shown, _ = health_visible()
        ids = [i["id"] for i in shown if body.category == "all" or i["category"] == body.category]
        with health_store.lock:
            health_store.ignored.update(ids)
        try:
            health_store.save()
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return get_health(body.category)

    @app.post("/api/library-health/fix")
    def health_fix(body: HealthIssueIn) -> dict:
        """Apply an issue's one-tap fix: ordinary safe tag writes, one undoable activity entry."""
        require_library()
        if not health_store.enabled:
            raise HTTPException(409, "Library health is switched off.")
        with health_lock:
            stale = health_cache["key"] != lib_index.version
        if stale:  # the library changed since this list was made: check again before writing anything
            health_compute()
        issue = next((i for i in health_data()["issues"] if i["id"] == body.id), None)
        if issue is None:
            raise HTTPException(404, "That issue is gone (fixed already?)")
        fix = issue.get("fix")
        if not fix:
            raise HTTPException(409, "This one needs a look by hand.")
        version = lib_index.version
        done, failed = apply_per_file(fix["per_file"], f"Library health: {fix['summary']}")
        if not failed:
            health_cache["fixed"][issue["id"]] = version  # hidden until the index has the new tags
        return {"fixed": len(done), "failed": len(failed), "errors": failed[:20], "health": get_health()}
