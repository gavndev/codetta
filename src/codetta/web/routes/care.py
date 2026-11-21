"""Tidy up: tagging and organizing the existing library, one album at a time."""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Query

from codetta.core import librarycare as care_mod
from codetta.core.library import LibraryPathError, audio_files
from codetta.core.organize import load_pattern
from codetta.web.common import (
    LibraryCareFolderIn,
    LibraryCareIgnoreIn,
    LibraryCareIn,
    MBProposalIn,
    MBSearchIn,
    OrganizeIn,
    log,
)


def register(app, shared) -> None:
    catalogs = shared.catalogs
    confident_match = shared.confident_match
    connections = shared.connections
    inbox = shared.inbox
    lib_index = shared.lib_index
    library = shared.library
    mb_apply = shared.mb_apply
    mb_preview = shared.mb_preview
    mb_read = shared.mb_read
    mb_search = shared.mb_search
    organize_apply = shared.organize_apply
    organize_preview = shared.organize_preview
    pattern_file = shared.pattern_file
    require_library = shared.require_library
    settings = shared.settings

    care = care_mod.LibraryCareStore(settings.config_dir / "library-care.json")
    care_wake = threading.Event()
    care_worker: dict = {"thread": None, "albums": [], "at": 0.0, "current": None, "gen": 0}

    def care_album_folders() -> list[str]:
        """Folders that hold audio, from the search index (no disk walk); never the inbox."""
        base = inbox.settings.folder
        folders = set()
        for path, _ in lib_index.iter_tracks():
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            if parent.startswith("@") or (base and (parent == base or parent.startswith(base + "/"))):
                continue
            folders.add(parent)
        return sorted(folders)

    def care_match(paths: list[str]) -> tuple[str, str, str, bool]:
        """Match one album (or one loose song) and tag it if Codetta is sure.
        Returns (status, note for people, title, tagged)."""
        found = mb_search(MBSearchIn(paths=paths))
        cands = found["candidates"]
        if not cands:
            return care_mod.REVIEW, "Couldn't find it online", "", False
        best = cands[0]
        title = f"{best['title']} · {best['artist']}"
        recs = found.get("recordings") or {}
        proposal = mb_preview(MBProposalIn(paths=paths, release=best["id"], recordings=recs))
        files = [f for f in proposal["files"] if not f["error"]]
        if not confident_match(best, files):
            return care_mod.REVIEW, f"Not sure it's the right album ({best['score']}% match)", title, False
        res = mb_apply(MBProposalIn(paths=paths, release=best["id"], recordings=recs))
        if res["failed"]:
            return care_mod.ERROR, f"{res['failed']} song(s) couldn't be changed", title, False
        return care_mod.TAGGED, "", title, True

    def care_one(folder: str) -> None:
        try:
            paths = audio_files(library, folder, False, 500)
        except (LibraryPathError, OSError):
            care.forget(folder)
            return
        if not paths:
            care.forget(folder)
            return
        care_worker["current"] = folder
        known = {p: (v[2].get("tags") or {}) for p, v in lib_index.stored(paths).items()}
        first = lambda p, k: ((known.get(p) or {}).get(k) or [""])[0]
        matched = all(first(p, "musicbrainz_albumid") for p in paths)
        online = connections.enabled("musicbrainz") or catalogs.available()
        albums = {first(p, "album").casefold() for p in paths}
        loose = len(paths) > 1 and (len(albums) > 1 or albums == {""})  # songs from different albums
        ids = {first(p, "musicbrainz_albumid") for p in paths}
        status, note, title, tagged = care_mod.SKIPPED, "", "", paths if matched else []
        if not matched and not online:
            status, note = care_mod.REVIEW, "Turn on MusicBrainz (Account → Connections) to match it"
        elif not matched and loose:
            # A folder of loose songs: each one is matched as a song, on its own.
            tagged = []
            for p in paths:
                if first(p, "musicbrainz_albumid"):
                    tagged.append(p)
                    continue
                *_, ok = care_match([p])
                if ok:
                    tagged.append(p)
            status = care_mod.TAGGED if len(tagged) == len(paths) else care_mod.REVIEW
            note = "" if status == care_mod.TAGGED else f"Loose songs: {len(tagged)} of {len(paths)} matched"
        elif not matched:
            status, note, title, ok = care_match(paths)
            tagged = paths if ok else []
        elif len(albums) > 1 and online and len({first(p, "musicbrainz_albumid") for p in paths}) == 1:
            # Matched before, but the songs disagree on the album's name ("Rumours" and "Rumours
            # (2004 Remaster)"): write them again from that same release so they agree.
            rid = first(paths[0], "musicbrainz_albumid")
            proposal = mb_preview(MBProposalIn(paths=paths, release=rid))
            files = [f for f in proposal["files"] if not f["error"]]
            if files and all(f["track"] and f["confidence"] == "high" for f in files):
                # Only the album's name (and its artist): the year and the rest stay as they are.
                res = mb_apply(MBProposalIn(paths=paths, release=rid, fields=["album", "albumartist"], cover="none"))
                status = care_mod.TAGGED if not res["failed"] else care_mod.ERROR
                title = f"{proposal['release']['title']} · {proposal['release']['artist']}" if proposal.get("release") else ""
            else:
                status, note, tagged = care_mod.REVIEW, "Its songs have different album names", []
        if care.mode == "full" and tagged and loose and (not matched or len(ids) > 1):
            # Loose songs go to their own albums, so different folders are expected. Songs that
            # share an album still never split: if they would, those stay where they are.
            dest = {m["src"]: m["dst"].rsplit("/", 1)[0] for m in organize_preview(OrganizeIn(paths=tagged))["moves"]
                    if m["status"] in ("move", "same")}
            infos, _, _ = mb_read(tagged)
            album_of = {f.path: (f.album.casefold(), (f.albumartist or f.artist).casefold()) for f in infos}
            folders_of: dict[tuple, set] = {}
            for p in tagged:
                folders_of.setdefault(album_of.get(p), set()).add(dest.get(p))
            held = {a for a, ds in folders_of.items() if len(ds) > 1}
            if held:
                tagged = [p for p in tagged if album_of.get(p) not in held]
                status, note = care_mod.REVIEW, f"Loose songs: {len(paths) - len(tagged)} would split an album, so they stayed"
        elif care.mode == "full" and tagged:
            # Never split an album: if its songs would land in different folders, leave them be.
            dests = {m["dst"].rsplit("/", 1)[0] for m in organize_preview(OrganizeIn(paths=tagged))["moves"]
                     if m["status"] in ("move", "same")}
            if len(dests) > 1:
                names = sorted({d.rsplit("/", 1)[-1] for d in dests})
                shown = " and ".join(f"“{n}”" for n in names[:2]) + (f" and {len(names) - 2} more" if len(names) > 2 else "")
                care.record(folder, care_mod.REVIEW,
                            f"Its songs would end up in different folders ({shown}), so it wasn't moved. "
                            "Make their album tags match and it'll be tidied next time.", title)
                return
        if care.mode == "full" and tagged:  # names and folders only ever come from a confident match
            org = organize_apply(OrganizeIn(paths=tagged))
            taken = sum(1 for h in org["held"] if h["status"] == "conflict")
            if taken:
                also = f"{taken} {'is' if taken == 1 else 'are'} already in your library, so {'it' if taken == 1 else 'they'} stayed"
                note = f"{note}; {also[0].lower()}{also[1:]}" if note else also
            if org["moved"]:
                if status in (care_mod.SKIPPED, care_mod.TAGGED):
                    status = care_mod.ORGANIZED
                for r in org["results"]:
                    if r["ok"]:
                        new = r["dst"].rsplit("/", 1)[0]
                        if new != folder:
                            care.record(new, care_mod.ORGANIZED, title=title)  # its new home is done
                remaining = [p for p in paths if p not in {r["src"] for r in org["results"] if r["ok"]}]
                if not remaining:
                    care.forget(folder)  # everything moved out: the old folder is gone
                    return
        care.record(folder, status, note, title)

    def care_run() -> None:
        try:
            while care.mode != "off" and not care.paused:
                if not lib_index.status().ready:  # the first scan comes first
                    if care_wake.wait(5):
                        care_wake.clear()
                    continue
                gen = care_worker["gen"]  # a new choice (or "try again") restarts the pass
                albums = care_album_folders()
                care_worker["albums"], care_worker["at"] = albums, time.monotonic()
                todo = [f for f in albums if f not in care.albums]
                if not todo:
                    if care.started is None:  # nothing left (say, every album dismissed): a run that's already done
                        care.begin()
                    care.end()
                    return
                care.begin()
                for folder in todo:
                    if care.mode == "off" or care.paused:
                        return
                    if care_worker["gen"] != gen:
                        break
                    try:
                        care_one(folder)
                    except HTTPException as exc:
                        care.record(folder, care_mod.ERROR, str(exc.detail))
                    except Exception as exc:  # noqa: BLE001 - one album never stops the rest
                        log.warning("Tidy up: %s: %s", folder, exc)
                        care.record(folder, care_mod.ERROR, "Something went wrong with this album")
                    if care_wake.wait(settings.care_pause_seconds):  # a gentle pace (online lookups are rate limited)
                        care_wake.clear()
                        if care.mode == "off" or care.paused:
                            return
                if care_wake.wait(2):  # let the index catch up with the moves before looking again
                    care_wake.clear()
        finally:
            care_worker["current"] = None

    def care_start() -> None:
        t = care_worker["thread"]
        if care.mode != "off" and not care.paused and (t is None or not t.is_alive()):
            care_wake.clear()
            care_worker["thread"] = threading.Thread(target=care_run, name="codetta-library-care", daemon=True)
            care_worker["thread"].start()

    app.state.care_start = care_start
    app.state.care_stop = care_wake.set

    def care_out() -> dict:
        if not care_worker.get("albums") or time.monotonic() - care_worker.get("at", 0) > 10:
            care_worker["albums"], care_worker["at"] = care_album_folders(), time.monotonic()
        t = care_worker["thread"]
        return care.summary(care_worker["albums"]) | {"running": bool(t and t.is_alive()), "current": care_worker.get("current")}

    @app.get("/api/library-care")
    def library_care() -> dict:
        """Library care's choice and progress: albums done, and the ones that need a look."""
        require_library()
        return care_out()

    @app.put("/api/library-care")
    def set_library_care(body: LibraryCareIn) -> dict:
        """Choose how Codetta looks after the library (off / tags / full), or pause and resume."""
        require_library()
        care.set(body.mode, body.paused)
        care_worker["gen"] += 1
        care_wake.set()  # a running pass notices right away
        if care.mode != "off" and not care.paused:
            care_start()
        return care_out()

    @app.get("/api/library-care/preview")
    def library_care_preview(albums: int = Query(3, ge=1, le=10)) -> dict:
        """Before the first full run: how a few albums would be renamed and moved, with their tags as
        they are now (online matching can still change them). Nothing is moved."""
        require_library()
        out = []
        for folder in care_album_folders():
            try:
                paths = audio_files(library, folder, False, 500)
            except (LibraryPathError, OSError):
                continue
            if not paths:
                continue
            tags = {p: (v[2].get("tags") or {}) for p, v in lib_index.stored(paths).items()}
            names = {((tags.get(p) or {}).get("album") or [""])[0].casefold() for p in paths}
            if len(names) > 1 or names == {""}:
                continue  # loose songs: matched one by one first, so where they go isn't known yet
            plan = organize_preview(OrganizeIn(paths=paths))
            moving = [m for m in plan["moves"] if m["status"] == "move"]
            if not moving:
                continue
            out.append({"folder": folder, "files": len(paths), "moving": len(moving),
                        "examples": [{"from": m["src"], "to": m["dst"]} for m in moving[:3]]})
            if len(out) >= albums:
                break
        return {"pattern": plan["pattern"] if out else load_pattern(pattern_file), "albums": out}

    @app.post("/api/library-care/again")
    def library_care_again(body: LibraryCareFolderIn) -> dict:
        """Look at one album again (after you've fixed it, or to retry)."""
        require_library()
        care.forget(body.folder.strip().strip("/"))
        care_worker["gen"] += 1
        care_start()
        return care_out()

    @app.post("/api/library-care/rerun")
    def library_care_rerun() -> dict:
        """Run Tidy up over the whole library again (after fixing things, or new settings)."""
        require_library()
        if care.mode == "off":
            raise HTTPException(409, "Tidy up is off. Choose what it should do first.")
        care.restart()
        care_worker["gen"] += 1
        care_start()
        return care_out()

    @app.post("/api/library-care/ignore")
    def library_care_ignore(body: LibraryCareIgnoreIn) -> dict:
        """Leave an album alone for good (it stops needing you), or look at it again."""
        require_library()
        if body.all and body.ignore:
            care.ignore_all_review()
            return care_out()
        folder = body.folder.strip().strip("/")
        if not folder or folder.startswith("@"):
            raise HTTPException(422, "Choose an album in your library.")
        care.ignore(folder, body.ignore)
        if not body.ignore:
            care_worker["gen"] += 1
            care_start()
        return care_out()

    shared.share(care=care)
