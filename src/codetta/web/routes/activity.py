"""Writing per-file changes, undo and the activity log."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException, Query

from codetta.core.engine import MetadataError
from codetta.core.library import LibraryPathError
from codetta.core.undo import undo_change


def register(app, shared) -> None:
    activity = shared.activity
    art_cache = shared.art_cache
    art_store = shared.art_store
    engine = shared.engine
    lib_index = shared.lib_index
    library = shared.library
    require_library = shared.require_library

    def apply_per_file(per_file: dict[str, dict], message: str) -> tuple[list[str], list[dict]]:
        """Write different tag changes to each file (safe writes, a few at once) and log them as
        one undoable activity entry. Returns (files done, failures)."""
        undo_files: dict = {}

        def one(item):
            rel, changes = item
            try:
                target = library.resolve(rel)
                was: dict = {}
                after = engine.update_tags(target, changes, before=was).tags
                before = was["tags"]
                keys = {k.lower() for k in changes}
                diff = [k for k in keys if before.get(k, []) != after.get(k, [])]
                if diff:
                    undo_files[rel] = {"before": {k: before.get(k, []) for k in diff},
                                       "after": {k: after.get(k, []) for k in diff}}
                return rel, None
            except (MetadataError, LibraryPathError, OSError) as exc:
                return rel, str(exc)

        items = list(per_file.items())
        if len(items) > 8:
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="codetta-write") as pool:
                results = list(pool.map(one, items))
        else:
            results = [one(i) for i in items]
        done = [r for r, e in results if e is None]
        failed = [{"path": r, "error": e} for r, e in results if e is not None]
        keys = sorted({k for c in per_file.values() for k in c})
        news = {k: {str(c.get(k)) for c in per_file.values() if k in c} for k in keys}
        activity.add(
            "edit", message if not failed else f"{message.split(':')[0]}: changed {len(done)} of {len(items)} tracks",
            ok=not failed, files=done + [f["path"] for f in failed],
            changes=[{"key": k, "old": "", "new": news[k].pop() if len(news[k]) == 1 else "various"} for k in keys],
            errors=failed, undo={"type": "tags", "files": undo_files} if undo_files else None,
        )
        lib_index.mark_dirty(done)
        return done, failed

    undo_lock = threading.Lock()  # one undo at a time: a double tap can't run the same undo twice

    @app.post("/api/activity/{entry_id}/undo")
    def undo(entry_id: int) -> dict:
        """Reverse a logged change. Files edited again since are left alone."""
        require_library()
        with undo_lock:
            return undo_locked(entry_id)

    def undo_locked(entry_id: int) -> dict:
        entry = activity.get(entry_id)
        if entry is None:
            raise HTTPException(404, "That change is no longer in the activity log")
        if not entry.get("undo"):
            raise HTTPException(422, "This change can't be undone")
        if activity.is_undone(entry_id):
            raise HTTPException(409, "This change has already been undone")
        try:
            outcome = undo_change(engine, library.resolve, art_store, entry["undo"])
        except LibraryPathError as exc:  # e.g. it moved files in the inbox, and there's no inbox folder now
            raise HTTPException(409, f"This change can't be undone any more: {exc}") from exc
        lib_index.mark_dirty(r.path for r in outcome.results if r.ok)
        if entry["undo"].get("type") == "moves" and outcome.reverse:
            lib_index.mark_dirty(p for pair in outcome.reverse["moves"] for p in pair if not p.startswith("@"))
            art_cache.clear()
        done = [r for r in outcome.results if r.ok]
        skipped = [r for r in outcome.results if r.skipped]
        failed = [r for r in outcome.results if not r.ok and not r.skipped]
        n = len(outcome.results)
        # Name the original change, however many times it's been undone/redone.
        what = entry.get("root_message") or entry["message"]
        redo = entry.get("kind") == "undo" and not entry.get("redo")
        verb = "Redid" if redo else "Undid"
        if not done:
            message = f"Couldn't {'redo' if redo else 'undo'} “{what}”"
        elif len(done) == n:
            message = f"{verb} “{what}”"
        else:
            message = f"{verb} “{what}” on {len(done)} of {n} files"
        if done:
            activity.add(
                "undo", message, ok=not failed,
                files=[r.path for r in done],
                changes=[{"key": c["key"], "old": c["new"], "new": c["old"]} for c in entry.get("changes", [])
                         if c.get("old") != "various"],
                errors=[{"path": r.path, "error": r.error or ""} for r in skipped + failed],
                undo=outcome.reverse, undoes=entry_id,
                extra={"root_message": what, "redo": redo},
            )
        return {
            "message": message,
            "undone": len(done), "skipped": len(skipped), "failed": len(failed),
            "results": [{"path": r.path, "ok": r.ok, "skipped": r.skipped, "error": r.error} for r in outcome.results],
        }

    # --- Activity -------------------------------------------------------------------------

    @app.get("/api/activity")
    def get_activity(limit: int = Query(50, ge=1, le=500), after_id: int = Query(0, ge=0)) -> list[dict]:
        """Recent changes, newest first. Pass ``after_id`` to get only newer ones."""
        return activity.recent(limit=limit, after_id=after_id)

    shared.share(apply_per_file=apply_per_file, undo=undo)
