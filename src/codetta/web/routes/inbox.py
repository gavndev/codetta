"""The import inbox: grouping, matching and filing new music."""
from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from codetta.core.library import is_special
from codetta.core.catalogs import is_catalog_id
from codetta.core.inbox import (
    DOWNLOADING,
    FILED,
    LOCAL,
    MATCHING,
    NO_MATCH,
    READY,
    REVIEW,
    SKIPPED,
    WAITING,
    InboxStore,
)
from codetta.core.inbox import (
    ERROR as INBOX_ERROR,
)
from codetta.core.library import INBOX as INBOX_ALIAS
from codetta.core.library import LibraryPathError
from codetta.core.matching import LEVELS, MatchingStore, confident
from codetta.core.musicbrainz import parse_release_id
from codetta.core.organize import Move, apply_moves, prune_replaced
from codetta.core.slskd import IMPORTED as SK_IMPORTED
from codetta.core.slskd import SlskdError, folder_progress
from codetta.web.common import (
    _name,
    InboxActionIn,
    InboxSettingsIn,
    log,
    MatchingIn,
    MAX_IDENTIFY,
    MBProposalIn,
    MBSearchIn,
    MBTarget,
    OrganizeIn,
)


def register(app, shared) -> None:
    activity = shared.activity
    art_cache = shared.art_cache
    catalogs = shared.catalogs
    connections = shared.connections
    fingerprinter = shared.fingerprinter
    lib_index = shared.lib_index
    library = shared.library
    mb_apply = shared.mb_apply
    mb_identify = shared.mb_identify
    mb_preview = shared.mb_preview
    mb_read = shared.mb_read
    mb_search = shared.mb_search
    most_common = shared.most_common
    notices = shared.notices
    organize_apply = shared.organize_apply
    require_library = shared.require_library
    settings = shared.settings
    soulseek = shared.soulseek
    soulseek_store = shared.soulseek_store
    sk_set_aside = shared.later("sk_set_aside")  # defined in routes/soulseek.py
    soulseek_matched = shared.later("soulseek_matched")  # defined in routes/soulseek.py

    inbox = InboxStore(settings.config_dir / "inbox.json", settings.inbox_settle_seconds)

    def downloads_complete(paths: list[str]) -> bool:
        """slskd says the download these files belong to is over (so they've all arrived)."""
        t = folder_progress(inbox_transfers(), {p.rsplit("/", 1)[-1] for p in paths})
        return bool(t and t.get("complete"))

    inbox.arrived = downloads_complete
    inbox_worker: dict = {"thread": None}
    inbox_wake = threading.Event()

    def inbox_tags(paths: list[str]) -> tuple[str, str]:
        infos, _, _ = mb_read(paths[:50])
        return (most_common(f.album for f in infos),
                most_common(f.albumartist or f.artist for f in infos))

    matching = MatchingStore(settings.config_dir / "matching.json")

    def confident_match(best: dict, files: list[dict]) -> bool:
        """Sure enough to write without asking, at the level chosen (Strict / Balanced / Relaxed):
        the Inbox's automatic filing and Tidy up both use this."""
        return confident(best, files, matching.level)

    def matching_out() -> dict:
        return {"confidence": matching.level,
                "levels": [{"id": k, "album": a, "single": s} for k, (a, s) in LEVELS.items()]}

    @app.get("/api/matching")
    def get_matching() -> dict:
        """How sure Codetta must be before it files (Inbox) or tags (Tidy up) an album on its own."""
        return matching_out()

    @app.put("/api/matching")
    def put_matching(body: MatchingIn) -> dict:
        try:
            matching.set(body.confidence)
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return matching_out()

    def inbox_match(key: str) -> None:
        g = inbox.update(key, status=MATCHING, note="")
        if g is None:
            return
        title, artist = inbox_tags(g.paths)
        if not connections.enabled("musicbrainz") and not catalogs.available():
            inbox.update(key, status=LOCAL, title=title, artist=artist,
                         note="Online lookups are off, so this files by its own tags.")
            return
        try:
            found = mb_search(MBSearchIn(paths=g.paths)) if (title or artist) else {"candidates": []}
            cands, recordings = found["candidates"], found.get("recordings") or {}
            sound = (connections.enabled("acoustid") and connections.enabled("musicbrainz")
                     and fingerprinter.available and len(g.paths) <= MAX_IDENTIFY)
            if sound and (not cands or cands[0]["score"] < 85):
                heard = mb_identify(MBTarget(paths=g.paths))
                if heard["candidates"] and (not cands or heard["candidates"][0]["score"] >= cands[0]["score"]):
                    cands, recordings = heard["candidates"], heard["recordings"]
            if not cands:
                inbox.update(key, status=NO_MATCH, title=title, artist=artist,
                             note="Couldn't find this online. Tap Search to look for it yourself, or keep its own tags.")
                return
            best = cands[0]
            proposal = mb_preview(MBProposalIn(paths=g.paths, release=best["id"], recordings=recordings))
            files = [f for f in proposal["files"] if not f["error"]]
            exact = confident_match(best, files)
            inbox.update(key, status=READY if exact else REVIEW, title=best["title"], artist=best["artist"],
                         release=best, score=best["score"], recordings=recordings,
                         note="" if exact else "Codetta isn't sure this is the right album. Tap Review to check.")
            if exact and inbox_auto(key):
                inbox_file(key, automatic=True)
        except HTTPException as exc:
            if exc.status_code == 409 and key in inbox_filing:
                return  # someone tapped "File" a moment earlier: that filing carries on
            inbox.update(key, status=INBOX_ERROR, title=title, artist=artist, note=str(exc.detail))

    def inbox_auto(key: str) -> bool:
        """File a confident match without asking? Soulseek downloads follow the
        Soulseek setting (review by default), everything else the inbox's."""
        g = inbox.groups.get(key)
        if g is not None and g.source:
            return not soulseek_store.settings.review
        return inbox.settings.auto

    inbox_filing: set[str] = set()
    inbox_filing_lock = threading.Lock()

    def inbox_file(key: str, release: str | None = None, recordings: dict | None = None, automatic: bool = False) -> dict:
        """File one album. A second request for the same album while it's being filed (a double
        tap, or "File all" while it's filing itself) is turned away instead of running twice."""
        with inbox_filing_lock:
            if key in inbox_filing:
                raise HTTPException(409, "This album is already being filed.")
            inbox_filing.add(key)
        try:
            return inbox_file_locked(key, release, recordings, automatic)
        finally:
            with inbox_filing_lock:
                inbox_filing.discard(key)

    def inbox_file_locked(key: str, release: str | None, recordings: dict | None, automatic: bool) -> dict:
        g = inbox.groups.get(key)
        if g is None:
            raise HTTPException(404, "That album is no longer in the inbox")
        release = release or (g.release or {}).get("id")
        notes, moved_to, applied = [], None, None
        if release:
            res = mb_apply(MBProposalIn(paths=g.paths, release=release, recordings=recordings or g.recordings))
            applied = res.get("release")  # the full summary of what was written
            if res["failed"]:
                notes.append(f"{res['failed']} track(s) couldn't be tagged")
        if g.upgrade and not notes:
            notes.extend(set_aside(g.upgrade))
        if inbox.settings.organize or g.upgrade:
            org = organize_apply(OrganizeIn(paths=g.paths))
            ok = [r for r in org["results"] if r["ok"]]
            if ok:
                moved_to = ok[0]["dst"].rsplit("/", 1)[0]
            untagged = sum("Not enough tags" in h["reason"] for h in org["held"])
            stuck = org["failed"] + len(org["held"]) - untagged
            if stuck:
                notes.append(f"{stuck} file(s) couldn't move: a file with that name is already in your library (a duplicate?)")
            if untagged:
                notes.append(f"{untagged} file(s) have no artist or album tags yet, so they stayed in the inbox")
        status = FILED if not notes else INBOX_ERROR
        if automatic:
            name = " by ".join(x for x in (f"“{g.title}”" if g.title else g.key.rsplit("/", 1)[-1], g.artist) if x)
            if status == FILED:
                notices.add("inbox", f"Filed {name}", f"Matched on MusicBrainz and moved to {moved_to or 'your library'}.",
                            {"open": "folder", "path": moved_to} if moved_to else {"open": "inbox"})
            else:
                notices.add("inbox", f"Couldn't file {name}", "; ".join(notes), {"open": "inbox"})
        inbox.update(key, status=status, dest=moved_to or "",
                     note="; ".join(notes) or (f"Filed in {moved_to}" if moved_to else "Tagged"),
                     # Another edition than the suggestion: keep its full summary (title, labels…), not
                     # just its ID, so the Inbox can describe it (#4).
                     release=g.release if not release or (g.release or {}).get("id") == release else (applied or {"id": release}))
        job = soulseek_store.jobs.get(g.source) if g.source else None
        if job is not None and status == FILED:
            soulseek_store.update(job, status=SK_IMPORTED, note=f"Filed in {moved_to}" if moved_to else "Filed")
        return {"status": status, "moved_to": moved_to, "note": "; ".join(notes)}

    def set_aside(folder: str) -> list[str]:
        """An upgrade: move the album it replaces out of the library, into the
        config folder ("@replaced"), as one undoable activity entry. Returns problems."""
        try:
            top = library.resolve(folder)
        except LibraryPathError as exc:
            return [str(exc)]
        if is_special(folder) or not folder or not top.is_dir():
            return []  # nothing there (any more): the download is simply new
        stamp = time.strftime("%Y%m%d-%H%M%S")
        moves = []
        for dirpath, _, names in os.walk(top):
            for name in names:
                rel = library.relative(Path(dirpath) / name)
                moves.append(Move(rel, f"@replaced/{stamp}/{rel}", "move"))
        results = apply_moves(library.resolve, moves)
        moved = [pair for r in results if r.ok for pair in r.moved]
        failed = [r for r in results if not r.ok]
        if moved:
            activity.add("organize", f"Set aside {_name(folder)} for its upgrade", ok=not failed,
                         files=[a for a, _ in moved], changes=[{"key": "location", "old": folder, "new": "(replaced)"}],
                         errors=[{"path": r.src, "error": r.error or ""} for r in failed],
                         undo={"type": "moves", "moves": [list(p) for p in moved]})
            lib_index.mark_dirty([a for a, _ in moved])
            art_cache.clear()
        return [f"{len(failed)} file(s) of the old album couldn't be moved aside"] if failed else []

    def inbox_run() -> None:
        done: list[str] = []
        while True:
            with inbox.lock:
                nxt = next((g.key for g in inbox.groups.values() if g.status == WAITING), None)
            if nxt is None:
                inbox_summary(done)
                return
            done.append(nxt)
            try:
                inbox_match(nxt)
                soulseek_matched(nxt)
            except Exception as exc:  # never let one album stop the queue
                log.warning("Inbox: couldn't look up %s: %s", nxt, exc)
                inbox.update(nxt, status=INBOX_ERROR, note="Something went wrong looking this up")

    def inbox_summary(keys: list[str]) -> None:
        """One notification when a round of lookups ends (auto-filed albums have their own)."""
        groups = [g for k in keys if (g := inbox.groups.get(k))]
        ready = [g for g in groups if g.status in (READY, LOCAL)]
        look = [g for g in groups if g.status in (REVIEW, NO_MATCH, INBOX_ERROR)]
        if not ready and not look:
            return
        parts = []
        if ready:
            parts.append(f"{len(ready)} ready to file")
        if look:
            parts.append(f"{len(look)} need{'s' if len(look) == 1 else ''} a look")
        names = ", ".join(g.title or g.key.rsplit("/", 1)[-1] for g in (ready + look)[:3])
        more = len(ready) + len(look) - 3
        notices.add("inbox", f"Inbox: {' · '.join(parts)}", names + (f" and {more} more" if more > 0 else ""),
                    {"open": "inbox"})

    def inbox_start() -> None:
        t = inbox_worker["thread"]
        if t is None or not t.is_alive():
            inbox_worker["thread"] = threading.Thread(target=inbox_run, name="codetta-inbox", daemon=True)
            inbox_worker["thread"].start()

    def inbox_watch() -> None:
        last_prune = time.time()
        while not inbox_wake.wait(15 * 60):
            if time.time() - last_prune > 86400:
                last_prune = time.time()
                prune_replaced(settings.config_dir / "replaced")
                prune_replaced(settings.config_dir / "deleted")
            if inbox.settings.watch and inbox.settings.folder and library.exists():
                try:
                    inbox.sync(library)
                    inbox_start()
                except (OSError, LibraryPathError) as exc:
                    log.warning("Inbox check failed: %s", exc)

    app.state.inbox_watch = inbox_watch  # started in lifespan
    app.state.inbox_stop = inbox_wake.set

    sk_transfers: dict = {"at": 0.0, "list": []}

    def inbox_transfers() -> list[dict]:
        """slskd's downloads, while something in the inbox is still arriving (for its progress bar)."""
        if not any(g.status == DOWNLOADING for g in list(inbox.groups.values())):
            return []
        if not (connections.enabled("slskd") and soulseek_store.configured):
            return []
        if time.time() - sk_transfers["at"] > 3:
            try:
                sk_transfers["list"] = soulseek.client().all_downloads()
            except SlskdError:
                sk_transfers["list"] = []
            sk_transfers["at"] = time.time()
        return sk_transfers["list"]

    inbox_owned_cache: dict[tuple, tuple[float, dict | None]] = {}

    def inbox_owned(g) -> dict | None:
        """Is this album already in the library (same release, or same album and artist)? Reads the
        search index only; remembered for a minute so the Inbox can refresh often."""
        rid = (g.release or {}).get("id") or ""
        ck = (g.key, rid, g.title, g.artist)
        hit = inbox_owned_cache.get(ck)
        if hit and time.monotonic() - hit[0] < 60:
            return hit[1]
        found: set[str] = set()
        if rid and not is_catalog_id(rid):
            found = lib_index.paths_where("musicbrainz_albumid", rid)
        if not found and g.title and g.artist:
            found = lib_index.paths_where("album", g.title) & (
                lib_index.paths_where("albumartist", g.artist) | lib_index.paths_where("artist", g.artist))
        base = inbox.settings.folder
        mine = set(g.paths)
        found = {p for p in found if not is_special(p) and p not in mine and not (base and p.startswith(base + "/"))}
        out = None
        if found:
            folders: dict[str, int] = {}
            for p in found:
                folders[p.rsplit("/", 1)[0] if "/" in p else ""] = folders.get(p.rsplit("/", 1)[0] if "/" in p else "", 0) + 1
            folder, n = max(folders.items(), key=lambda kv: kv[1])
            out = {"folder": folder, "tracks": n}
        inbox_owned_cache[ck] = (time.monotonic(), out)
        if len(inbox_owned_cache) > 500:
            inbox_owned_cache.clear()
        return out

    def inbox_out() -> dict:
        transfers = inbox_transfers()
        with inbox.lock:
            groups = sorted(inbox.groups.values(), key=lambda g: (g.status == FILED, -g.updated if g.status == FILED else 0, g.key))
            counts = {}
            for g in groups:
                counts[g.status] = counts.get(g.status, 0) + 1
            folder = inbox.settings.folder
            running = bool(inbox_worker["thread"] and inbox_worker["thread"].is_alive())
            try:
                exists = bool(folder) and library.resolve(folder).is_dir()
            except LibraryPathError:
                exists = False
            return {
                # A downloads folder mounted outside the music folder (e.g. slskd's), offered first.
                "external": {"available": library.inbox_available(),
                             "path": str(settings.inbox_dir) if settings.inbox_dir else None},
                "downloading": sum(g.status == DOWNLOADING for g in groups),
                "settings": {"folder": folder, "auto": inbox.settings.auto, "organize": inbox.settings.organize,
                             "watch": inbox.settings.watch},
                "folder_exists": exists,
                "online": connections.enabled("musicbrainz"),
                "running": running, "counts": counts,
                "groups": [{"key": g.key, "files": len(g.paths), "paths": g.paths[:1000], "status": g.status,
                            "title": g.title, "artist": g.artist, "release": g.release, "score": g.score,
                            "recordings": g.recordings, "note": g.note, "dest": g.dest,
                            "owned": inbox_owned(g) if g.status not in (FILED, DOWNLOADING) else None,
                            "transfer": folder_progress(transfers, {p.rsplit("/", 1)[-1] for p in g.paths})
                                        if transfers and g.status == DOWNLOADING else None} for g in groups],
            }

    @app.get("/api/inbox")
    def get_inbox() -> dict:
        """The inbox: re-read its folder and look up anything new (in the background)."""
        require_library()
        if inbox.settings.folder:
            try:
                inbox.sync(library)
            except (OSError, LibraryPathError) as exc:
                raise HTTPException(500, f"Couldn't read the inbox folder: {exc}") from exc
            inbox_start()
        return inbox_out()

    @app.put("/api/inbox/settings")
    def put_inbox_settings(body: InboxSettingsIn) -> dict:
        require_library()
        folder = body.folder.strip().strip("/")
        if is_special(folder) and folder != INBOX_ALIAS and not folder.startswith(INBOX_ALIAS + "/"):
            raise HTTPException(422, "The inbox can be your downloads folder or a folder in your music folder.")
        if not folder:
            raise HTTPException(422, "Choose your downloads folder, or a folder inside your music folder (not the whole library).")
        if not library.resolve(folder).is_dir():
            raise HTTPException(422, "The downloads folder isn't mounted (see CODETTA_INBOX_DIR)." if folder.startswith("@")
                                else f"There's no folder called “{folder}” in your music folder.")
        with inbox.lock:
            if folder != inbox.settings.folder:
                inbox.groups.clear()
            inbox.settings.folder, inbox.settings.auto = folder, body.auto
            inbox.settings.organize, inbox.settings.watch = body.organize, body.watch
            try:
                inbox.save()
            except OSError as exc:
                raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return get_inbox()

    @app.post("/api/inbox/accept")
    def inbox_file_route(body: InboxActionIn) -> dict:
        """File one album: write its MusicBrainz tags (if matched) and organize it into the library."""
        require_library()
        release = None
        if body.release:
            release = parse_release_id(body.release)
            if not release:
                raise HTTPException(422, "That isn't a MusicBrainz release.")
        result = inbox_file(body.key, release, body.recordings or None)
        return {**result, "inbox": inbox_out()}

    @app.post("/api/inbox/accept-ready")
    def inbox_file_ready() -> dict:
        """File every confident match in one go."""
        require_library()
        keys = [g.key for g in list(inbox.groups.values()) if g.status == READY]
        filed = 0
        for k in keys:
            try:
                filed += inbox_file(k)["status"] == FILED
            except HTTPException as exc:
                if exc.status_code != 409:  # 409: already being filed, by itself or another tap
                    raise
        return {"filed": filed, "total": len(keys), "inbox": inbox_out()}

    @app.post("/api/inbox/remove")
    def inbox_remove(body: InboxActionIn) -> dict:
        """Take an album out of the inbox: its files go to Recently deleted (30 days, undoable)."""
        require_library()
        g = inbox.groups.get(body.key)
        if g is None:
            raise HTTPException(404, "That album is no longer in the inbox")
        if g.status in (FILED, MATCHING) or body.key in inbox_filing:
            raise HTTPException(409, "It's being matched or filed right now. Try again in a moment.")
        base = inbox.settings.folder
        if g.key != base and g.key.startswith(base + "/"):
            rels = []
            for dirpath, _, names in os.walk(library.resolve(g.key)):
                rels += [library.relative(Path(dirpath) / n) for n in names]
        else:
            rels = [p for p in g.paths if p.startswith(base + "/")]
        sk_set_aside(rels, f"Removed “{g.title or g.key.rsplit('/', 1)[-1]}” from the inbox")
        with contextlib.suppress(OSError, LibraryPathError):
            if g.key != base and g.key.startswith(base + "/"):
                for dirpath, _, _ in sorted(os.walk(library.resolve(g.key)), key=lambda x: -len(x[0])):
                    with contextlib.suppress(OSError):
                        os.rmdir(dirpath)
        with inbox.lock:
            inbox.groups.pop(g.key, None)
            inbox.save()
        return inbox_out()

    @app.post("/api/inbox/dismiss")
    def inbox_dismiss(body: InboxActionIn) -> dict:
        """Take one filed album off the list."""
        if not inbox.dismiss(body.key):
            raise HTTPException(404, "Only albums that were filed can be dismissed")
        return inbox_out()

    @app.post("/api/inbox/dismiss-all")
    def inbox_dismiss_all() -> dict:
        """Take every filed album off the list."""
        inbox.dismiss()
        return inbox_out()

    @app.post("/api/inbox/skip")
    def inbox_skip(body: InboxActionIn) -> dict:
        if inbox.update(body.key, status=SKIPPED, note="Skipped: left where it is") is None:
            raise HTTPException(404, "That album is no longer in the inbox")
        return inbox_out()

    @app.post("/api/inbox/rematch")
    def inbox_rematch(body: InboxActionIn) -> dict:
        if inbox.update(body.key, status=WAITING, note="", release=None, score=None) is None:
            raise HTTPException(404, "That album is no longer in the inbox")
        inbox_start()
        return inbox_out()

    shared.share(confident_match=confident_match, inbox=inbox, inbox_file=inbox_file, inbox_start=inbox_start)
