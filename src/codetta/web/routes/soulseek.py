"""The optional Soulseek integration through slskd."""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException

from codetta.core.inbox import FILED, MATCHING, WAITING
from codetta.core.inbox import signature as inbox_signature
from codetta.core.library import DELETED, LibraryPathError
from codetta.core.musicbrainz import parse_release_id
from codetta.core.organize import Move
from codetta.core.slskd import (
    ARRIVED as SK_ARRIVED,
)
from codetta.core.slskd import (
    CANCELLED as SK_CANCELLED,
)
from codetta.core.slskd import (
    DOWNLOADING as SK_DOWNLOADING,
)
from codetta.core.slskd import (
    FAILED as SK_FAILED,
)
from codetta.core.slskd import (
    IMPORTED as SK_IMPORTED,
)
from codetta.core.slskd import (
    NOTHING as SK_NOTHING,
)
from codetta.core.slskd import (
    SlskdError,
)
from codetta.core.slskd import (
    basenames as sk_basenames,
)
from codetta.core.slskd import (
    check as slskd_check,
)
from codetta.core.slskd import (
    clean_url as slskd_clean_url,
)
from codetta.web.common import (
    SlskdImportIn,
    SlskdNextIn,
    SlskdPickIn,
    SlskdSearchIn,
    SlskdSettingsIn,
    log,
)


def register(app, shared) -> None:
    connections = shared.connections
    inbox = shared.inbox
    inbox_file = shared.inbox_file
    inbox_start = shared.inbox_start
    library = shared.library
    notices = shared.notices
    require_library = shared.require_library
    settings = shared.settings
    soulseek = shared.soulseek
    soulseek_store = shared.soulseek_store
    run_moves = shared.later("run_moves")  # defined in routes/files.py

    sk_worker: dict = {"thread": None, "check": None}
    sk_wake = threading.Event()

    def sk_ready() -> None:
        if not connections.enabled("slskd"):
            raise HTTPException(403, "Soulseek is off. Turn it on in Account → Connections.")
        if not soulseek_store.configured:
            raise HTTPException(409, "Connect your slskd first: Account → Connections → Soulseek.")

    def sk_job(job_id: str):
        if not re.fullmatch(r"[0-9a-f-]{32,36}", job_id or ""):
            raise HTTPException(404, "That Soulseek request is gone")
        job = soulseek_store.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "That Soulseek request is gone")
        return job

    def sk_locate(job) -> str | None:
        """Find a finished download in the inbox (by its file names) and hand it over."""
        names = set(sk_basenames(job))
        if not names or not inbox.settings.folder:
            return None
        best = None
        for g in inbox.sync(library):
            if g.status == FILED or (g.source and g.source != job.id):
                continue  # filed already, or another request's download
            hit = len(names & {p.rsplit("/", 1)[-1] for p in g.paths})
            # Most of what was asked for, and most of what's there (an older album that happens
            # to share names like "01.flac" must never be taken for it: blocklisting deletes it).
            if hit < max(1, int(len(names) * 0.8)) or hit < int(len(g.paths) * 0.8):
                continue
            if inbox_signature(library, g.paths)[1] < job.created - 60:
                continue  # these files were there before the request
            if best is None or hit > best[0]:
                best = (hit, g.key)
        if best is None:
            return None
        # slskd says it's complete, so no need to wait for the files to settle.
        inbox.update(best[1], source=job.id, upgrade=job.upgrade, status=WAITING, note="", release=None, score=None)
        inbox_start()
        return best[1]

    def soulseek_matched(key: str) -> None:
        """A Soulseek download has been matched: ask for a review (unless it filed itself)."""
        g = inbox.groups.get(key)
        job = soulseek_store.jobs.get(g.source) if g and g.source else None
        if job is None or g.status in (FILED, MATCHING, WAITING):
            return
        name = g.title or job.query
        soulseek_store.update(job, note="Downloaded: have a look")
        notices.add("soulseek", f"Soulseek: “{name}” is here",
                    f"{(job.current or {}).get('quality', '')} from {(job.current or {}).get('username', '')}. "
                    "Import it, or blocklist it and try the next one.",
                    {"open": "soulseek", "job": job.id}, key=f"sk-review:{job.id}:{job.pick}")

    def sk_run() -> None:
        while soulseek_store.active():
            try:
                soulseek.tick(sk_locate)
                for job in list(soulseek_store.jobs.values()):
                    if job.leftovers:
                        sk_clear_leftovers(job)
            except Exception as exc:  # keep going whatever one job does
                log.warning("Soulseek: %s", exc)
            if sk_wake.wait(settings.slskd_poll_seconds):
                return

    def sk_start() -> None:
        t = sk_worker["thread"]
        if soulseek_store.active() and (t is None or not t.is_alive()):
            sk_wake.clear()
            sk_worker["thread"] = threading.Thread(target=sk_run, name="codetta-soulseek", daemon=True)
            sk_worker["thread"].start()

    app.state.soulseek_start = sk_start
    app.state.soulseek_stop = sk_wake.set

    def sk_drop_download(job) -> None:
        """Set aside what a job brought into the inbox (when it's blocklisted or swapped): the files go
        to Recently deleted (30 days, undoable), never straight off the disk."""
        g = inbox.groups.get(job.inbox_key) if job.inbox_key else None
        if g is None or g.status == FILED:
            return
        base = inbox.settings.folder
        if g.key != base and g.key.startswith(base + "/"):
            rels = []  # the folder slskd made, with its extras (cover.jpg, .nfo...)
            try:
                for dirpath, _, names in os.walk(library.resolve(g.key)):
                    rels += [library.relative(Path(dirpath) / n) for n in names]
            except (OSError, LibraryPathError):
                rels = []
        else:
            rels = [p for p in g.paths if p.startswith(base + "/")]  # only ever inside the inbox
        sk_set_aside(rels, f"Set aside the download “{g.title or g.key.rsplit('/', 1)[-1]}”")
        with inbox.lock:
            inbox.groups.pop(g.key, None)
            inbox.save()

    def sk_set_aside(rels: list[str], message: str) -> None:
        if not rels:
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        moves = [Move(r, f"{DELETED}/{stamp}/{r.lstrip('@')}", "move") for r in rels]
        run_moves(moves, "delete", message, [{"key": "location", "old": rels[0].rsplit("/", 1)[0], "new": "(recently deleted)"}])

    def sk_clear_leftovers(job) -> None:
        """Files that arrived from a source the job then gave up on: set aside, so they never
        appear in the inbox as a second, partial album."""
        if not job.leftovers or not inbox.settings.folder:
            return
        rels = []
        for left in job.leftovers:
            folder = f"{inbox.settings.folder}/{safe_component(left.get('folder', ''))}"
            for name in left.get("files", []):
                rel = f"{folder}/{safe_component(name)}"
                try:
                    if library.resolve(rel).is_file():
                        rels.append(rel)
                except LibraryPathError:
                    continue
        sk_set_aside(rels, f"Cleared what arrived from an abandoned source for “{job.query}”")
        soulseek_store.update(job, leftovers=[])

    def safe_component(name: str) -> str:
        """A folder or file name from slskd, as one path part (never "..", never a separator)."""
        name = str(name).replace("/", "_").replace("\\", "_").strip()
        return "_" if name in ("", ".", "..") else name

    def sk_job_out(job) -> dict:
        g = inbox.groups.get(job.inbox_key) if job.inbox_key else None
        def cand(i, c):
            return {k: c[k] for k in ("username", "folder", "name", "tracks", "size", "quality", "lossless",
                                      "free_slot", "speed", "queue", "score")} | {"index": i, "tried": i in job.tried}
        cur = job.current
        return {
            "id": job.id, "query": job.query, "status": job.status, "note": job.note, "progress": job.progress,
            "eta": job.eta,
            "created": job.created, "updated": job.updated, "upgrade": job.upgrade,
            "current": cand(job.pick, cur) | {"files": [split_name(f["filename"]) for f in cur.get("files", [])]} if cur else None,
            "candidates": [cand(i, c) | ({"files": [split_name(f["filename"]) for f in c.get("files", [])],
                                          "match": c.get("match")} if job.status == "choosing" else {})
                           for i, c in enumerate(job.candidates)],
            "inbox": {"key": g.key, "status": g.status, "title": g.title, "artist": g.artist, "release": g.release,
                      "score": g.score, "note": g.note, "paths": g.paths[:200], "recordings": g.recordings,
                      "dest": g.dest}
                     if g else None,
        }

    def split_name(remote: str) -> str:
        return remote.replace("\\", "/").rsplit("/", 1)[-1]

    def soulseek_out(check_result: dict | None = None) -> dict:
        with soulseek_store.lock:
            jobs = sorted(soulseek_store.jobs.values(), key=lambda j: -j.created)
            st = soulseek_store.settings
            return {
                "enabled": connections.enabled("slskd"),
                "configured": soulseek_store.configured,
                "url": soulseek_store.url, "has_key": bool(soulseek_store.api_key),
                "locked": {"url": soulseek_store.env_url is not None, "api_key": soulseek_store.env_key is not None},
                "settings": {"review": st.review, "lossless_only": st.lossless_only, "min_bitrate": st.min_bitrate,
                             "search_seconds": st.search_seconds},
                "inbox": {"folder": inbox.settings.folder, "external": library.inbox_available()},
                "blocked": len(soulseek_store.blocked),
                "check": check_result if check_result is not None else sk_worker["check"],
                "jobs": [sk_job_out(j) for j in jobs[:50]],
            }

    def sk_check() -> dict:
        if not soulseek_store.configured:
            return {"ok": False, "error": "Add your slskd's address and an API key."}
        result = slskd_check(soulseek.client())
        sk_worker["check"] = result
        return result

    @app.get("/api/slskd")
    def get_soulseek() -> dict:
        """Soulseek: connection details (never the API key), settings and requests."""
        return soulseek_out()

    @app.put("/api/slskd/settings")
    def put_soulseek_settings(body: SlskdSettingsIn) -> dict:
        url = slskd_clean_url(body.url)
        if url:
            parts = urlsplit(url)
            if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
                    or any(c.isspace() for c in url) or parts.query or parts.fragment):
                raise HTTPException(422, "slskd's address should look like http://slskd:5030 or http://192.168.1.50:5030")
            try:
                parts.port  # a port that isn't a number raises
            except ValueError:
                raise HTTPException(422, "The port in slskd's address should be a number, like :5030") from None
        if body.api_key is not None and body.api_key.strip():
            key = body.api_key.strip()
            if any(c.isspace() for c in key) or not key.isprintable() or len(key) < 8:
                raise HTTPException(422, "That doesn't look like an slskd API key (at least 8 characters, no spaces).")
        with soulseek_store.lock:
            st = soulseek_store.settings
            if soulseek_store.env_url is None:
                st.url = url
            if body.api_key is not None and soulseek_store.env_key is None:
                st.api_key = body.api_key.strip()
            st.review, st.lossless_only, st.choose = body.review, body.lossless_only, body.choose
            st.min_bitrate, st.search_seconds = body.min_bitrate, body.search_seconds
            try:
                soulseek_store.save()
            except OSError as exc:
                raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return soulseek_out(sk_check() if soulseek_store.configured else None)

    @app.post("/api/slskd/test")
    def test_soulseek() -> dict:
        return soulseek_out(sk_check())

    @app.post("/api/slskd/search")
    def soulseek_search(body: SlskdSearchIn) -> dict:
        """Ask slskd to search; the best match is downloaded into the inbox."""
        sk_ready()
        if not inbox.settings.folder:
            raise HTTPException(409, "Set up the inbox first: Soulseek downloads arrive there.")
        upgrade = body.upgrade.strip().strip("/")
        if upgrade:
            try:
                if upgrade.startswith("@") or not library.resolve(upgrade).is_dir():
                    raise HTTPException(422, "That album folder isn't in your library.")
            except LibraryPathError as exc:
                raise HTTPException(422, str(exc)) from exc
        try:
            job = soulseek.search(body.query, upgrade)
        except SlskdError as exc:
            raise HTTPException(502, str(exc)) from exc
        sk_start()
        return {"job": sk_job_out(job), **soulseek_out()}

    @app.post("/api/slskd/jobs/{job_id}/next")
    def soulseek_next(job_id: str, body: SlskdNextIn) -> dict:
        """Not this one: (blocklist it and) download the next best candidate."""
        sk_ready()
        job = sk_job(job_id)
        cur = job.current
        if cur is None:
            raise HTTPException(409, "Nothing has been downloaded for this request yet.")
        if body.block:
            soulseek.blocklist(cur["username"], cur["folder"])
        try:
            if job.status == SK_DOWNLOADING:
                soulseek.cancel_transfers(job)
            sk_drop_download(job)
            soulseek.next_candidate(job, f"Blocklisted {cur['name']} from {cur['username']}." if body.block else "")
        except SlskdError as exc:
            raise HTTPException(502, str(exc)) from exc
        sk_start()
        return soulseek_out()

    @app.post("/api/slskd/jobs/{job_id}/pick")
    def soulseek_pick(job_id: str, body: SlskdPickIn) -> dict:
        """Download a candidate of your choosing instead."""
        sk_ready()
        job = sk_job(job_id)
        if body.index >= len(job.candidates):
            raise HTTPException(404, "That result is gone")
        try:
            if job.status == SK_DOWNLOADING:
                soulseek.cancel_transfers(job)
            if job.status == SK_ARRIVED:
                sk_drop_download(job)
            soulseek.start(job, body.index)
        except SlskdError as exc:
            raise HTTPException(502, str(exc)) from exc
        sk_clear_leftovers(job)
        sk_start()
        return soulseek_out()

    @app.post("/api/slskd/jobs/{job_id}/import")
    def soulseek_import(job_id: str, body: SlskdImportIn | None = None) -> dict:
        """Keep it: file the download into the library (replacing the album it upgrades)."""
        require_library()
        job = sk_job(job_id)
        if job.status != SK_ARRIVED or job.inbox_key not in inbox.groups:
            raise HTTPException(409, "This download isn't in the inbox (yet).")
        release = None
        if body and body.release:
            release = parse_release_id(body.release)
            if not release:
                raise HTTPException(422, "That isn't a MusicBrainz release.")
        result = inbox_file(job.inbox_key, release, (body.recordings if body else None) or None)
        return {**result, **soulseek_out()}

    @app.post("/api/slskd/jobs/{job_id}/cancel")
    def soulseek_cancel(job_id: str) -> dict:
        job = sk_job(job_id)
        if job.status == SK_DOWNLOADING and soulseek_store.configured:
            try:
                soulseek.cancel_transfers(job)
            except SlskdError:
                pass
        if job.status in (SK_DOWNLOADING, "searching", "choosing", "fetched"):
            soulseek_store.update(job, status=SK_CANCELLED, note="Cancelled")
        sk_clear_leftovers(job)
        return soulseek_out()

    @app.delete("/api/slskd/jobs/{job_id}")
    def soulseek_forget(job_id: str) -> dict:
        """Take a finished request off the list (the files stay wherever they are)."""
        job = sk_job(job_id)
        if job.status not in (SK_IMPORTED, SK_NOTHING, SK_FAILED, SK_CANCELLED, SK_ARRIVED):
            raise HTTPException(409, "Cancel it first.")
        with soulseek_store.lock:
            soulseek_store.jobs.pop(job.id, None)
            soulseek_store.save()
        return soulseek_out()

    @app.delete("/api/slskd/blocklist")
    def soulseek_clear_blocklist() -> dict:
        with soulseek_store.lock:
            soulseek_store.blocked.clear()
            soulseek_store.save()
        return soulseek_out()

    shared.share(sk_set_aside=sk_set_aside, soulseek_matched=soulseek_matched)
