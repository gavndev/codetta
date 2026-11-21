"""One file or folder at a time (move, rename, delete), importing and Recently deleted."""
from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from urllib.parse import quote

from fastapi import HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from codetta.core import importer, trash
from codetta.core.archive import folder_files, zip_size, zip_stream
from codetta.core.fileinfo import file_info, folder_info
from codetta.core.library import DELETED, LibraryPathError
from codetta.core.organize import SIDECAR_SUFFIXES, Move, apply_moves, safe_name
from codetta.web.common import (
    MAX_PATH_CHARS,
    FileRenameIn,
    FilesIn,
    FilesMoveIn,
    FolderRenameIn,
    ImportDoneIn,
    OrganizeIn,
    TrashIn,
    _unique,
)


def register(app, shared) -> None:
    activity = shared.activity
    art_cache = shared.art_cache
    engine = shared.engine
    inbox = shared.inbox
    inbox_start = shared.inbox_start
    lib_index = shared.lib_index
    library = shared.library
    organize_apply = shared.organize_apply
    rename_folder = shared.rename_folder
    require_library = shared.require_library
    settings = shared.settings

    def _join(folder: str, name: str) -> str:
        return f"{folder}/{name}" if folder else name

    def _parent(rel: str) -> str:
        return rel.rsplit("/", 1)[0] if "/" in rel else ""

    def entry_moves(rel: str, new_rel: str) -> list[Move]:
        """Moves that put a file (with its .lrc) or a whole folder at ``new_rel``."""
        src = library.resolve(rel)
        if src.is_dir():
            moves = []
            for dirpath, _, names in os.walk(src):
                for n in sorted(names):
                    r = library.relative(Path(dirpath) / n)
                    moves.append(Move(r, new_rel + r[len(rel):], "move"))
            return moves
        if not src.is_file():
            raise HTTPException(404, f"“{rel.rsplit('/', 1)[-1]}” isn't there any more.")
        m = Move(rel, new_rel, "move")
        src_stem, dst_stem = os.path.splitext(rel)[0], os.path.splitext(new_rel)[0]
        for suffix in SIDECAR_SUFFIXES:  # lyrics files follow their song
            if library.resolve(src_stem + suffix).is_file() and not os.path.lexists(library.resolve(dst_stem + suffix)):
                m.companions.append((src_stem + suffix, dst_stem + suffix))
        return [m]

    def run_moves(moves: list[Move], kind: str, message: str, changes: list[dict]) -> dict:
        """Do the moves (nothing is ever overwritten), log them as one undoable entry, refresh."""
        results = apply_moves(library.resolve, moves)
        pairs = [p for r in results if r.ok for p in r.moved]
        failed = [r for r in results if not r.ok]
        if pairs:
            activity.add(kind, message, ok=not failed, files=[b for _, b in pairs], changes=changes,
                         errors=[{"path": r.src, "error": r.error or ""} for r in failed],
                         undo={"type": "moves", "moves": [list(p) for p in pairs]})
        lib_index.mark_dirty([p for pair in pairs for p in pair if not p.startswith("@")])
        art_cache.clear()
        return {"moved": len([r for r in results if r.ok]), "failed": len(failed),
                "errors": [{"path": r.src, "error": r.error or ""} for r in failed][:20]}

    def library_entries(paths: list[str]) -> list[str]:
        rels = [p.strip().strip("/") for p in _unique(paths)]
        for rel in rels:
            if not rel or rel.startswith("@"):
                raise HTTPException(422, "Choose files or folders inside your music folder.")
            library.resolve(rel)  # rejects anything outside the library
        return rels

    @app.post("/api/files/move")
    def move_entries(body: FilesMoveIn) -> dict:
        """Move files and folders into another folder (like Organize: nothing is overwritten, one undo)."""
        require_library()
        to = body.to.strip().strip("/")
        if to.startswith("@") or not library.resolve(to).is_dir():
            raise HTTPException(404, "That folder isn't there any more.")
        moves = []
        rels = library_entries(body.paths)
        for rel in rels:
            if to == rel or to.startswith(rel + "/"):
                raise HTTPException(422, "A folder can't go inside itself.")
            if _parent(rel) != to:
                moves += entry_moves(rel, _join(to, rel.rsplit("/", 1)[-1]))
        where = f"“{to.rsplit('/', 1)[-1]}”" if to else "the top of your library"
        what = f"“{rels[0].rsplit('/', 1)[-1]}”" if len(rels) == 1 else f"{len(rels)} items"
        if not moves:
            return {"moved": 0, "failed": 0, "errors": []}
        return run_moves(moves, "organize", f"Moved {what} to {where}", [{"key": "folder", "old": _parent(rels[0]), "new": to}])

    @app.post("/api/files/rename")
    def rename_entry(body: FileRenameIn) -> dict:
        """Rename one file (its extension stays; its .lrc follows). Folders use /api/folders/rename."""
        require_library()
        (rel,) = library_entries([body.path])
        src = library.resolve(rel)
        if src.is_dir():
            return rename_folder(FolderRenameIn(path=rel, name=body.name))
        ext = src.suffix
        stem = body.name.strip()
        if ext and stem.lower().endswith(ext.lower()):
            stem = stem[: -len(ext)]
        if not stem.strip().strip("."):
            raise HTTPException(422, "Give the file a name.")
        new_name = safe_name(stem) + ext
        new_rel = _join(_parent(rel), new_name)
        if new_rel == rel:
            return {"path": rel, "moved": 0, "failed": 0, "errors": []}
        target = library.resolve(new_rel)
        if os.path.lexists(target) and not (new_rel.casefold() == rel.casefold() and target.samefile(src)):
            raise HTTPException(409, f"There's already a file called “{new_name}” here.")
        out = run_moves(entry_moves(rel, new_rel), "organize", f"Renamed “{src.name}” to “{new_name}”",
                        [{"key": "name", "old": src.name, "new": new_name}])
        return {"path": new_rel if out["moved"] else rel, **out}

    @app.post("/api/files/delete")
    def delete_entries(body: FilesIn) -> dict:
        """Move files and folders to "Recently deleted" (kept 30 days in the config folder).
        Nothing is erased: Activity can put them back."""
        require_library()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        rels = library_entries(body.paths)
        moves = [m for rel in rels for m in entry_moves(rel, f"{DELETED}/{stamp}/{rel}")]
        what = f"“{rels[0].rsplit('/', 1)[-1]}”" if len(rels) == 1 else f"{len(rels)} items"
        out = run_moves(moves, "delete", f"Deleted {what} (in Recently deleted for 30 days)",
                        [{"key": "location", "old": _parent(rels[0]), "new": "(recently deleted)"}])
        for rel in rels:  # a deleted folder's empty subfolders go too
            src = library.resolve(rel)
            if src.is_dir():
                for dirpath, _, _ in sorted(os.walk(src), key=lambda x: -len(x[0])):
                    with contextlib.suppress(OSError):
                        os.rmdir(dirpath)
        return out

    @app.get("/api/files/info")
    def entry_info(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File or folder, relative to the music folder")) -> dict:
        """Get info: format, quality, size and dates of a file, or what a folder holds."""
        require_library()
        target = library.resolve(path)
        info = folder_info(target) if target.is_dir() else file_info(engine, target)
        return {"path": path.strip("/"), **info}

    @app.get("/api/folders/zip")
    def zip_folder(path: str = Query(..., max_length=MAX_PATH_CHARS, description="Folder, relative to the music folder")):
        """Download a folder as a .zip (streamed: nothing is written to disk, files stored as they are)."""
        require_library()
        rel = path.strip().strip("/")
        if not rel:
            raise HTTPException(422, "Pick a folder to zip up (not the whole library).")
        try:
            target = library.resolve(rel)
        except LibraryPathError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not target.is_dir():
            raise HTTPException(404, "That folder isn't there any more.")
        files = folder_files(target)
        if not files:
            raise HTTPException(422, "That folder is empty, so there's nothing to zip up.")
        name = (target.name or "Music") + ".zip"
        ascii_name = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)
        headers = {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}",
                   "X-Codetta-Zip-Files": str(len(files)), "X-Codetta-Zip-Bytes": str(zip_size(files)),
                   "Cache-Control": "no-store"}
        return StreamingResponse(zip_stream(files), media_type="application/zip", headers=headers)

    # --- Import: music added from your computer or phone ----------------------------------------

    def import_root(batch: str) -> str:
        """Where an import lands: the inbox (matched and filed like new music) or "Imported"."""
        if not importer.BATCH_RE.match(batch):
            raise HTTPException(422, "That import isn't valid.")
        base = inbox.settings.folder
        try:
            usable = bool(base) and library.resolve(base).is_dir()
        except LibraryPathError:
            usable = False
        return f"{base if usable else 'Imported'}/Import {batch}"

    @app.put("/api/import")
    async def import_file(request: Request, batch: str = Query(..., max_length=40),
                          path: str = Query(..., max_length=MAX_PATH_CHARS, description="The file's name, or its path inside the folder you picked")) -> dict:
        """Add one file (the request body), streamed to disk. Names are cleaned and nothing is overwritten."""
        require_library()
        root = import_root(batch)
        try:
            parts = importer.clean_parts(path)
            target = await importer.receive_stream(library.resolve(root), parts, request.stream())
        except importer.ImportError_ as exc:
            raise HTTPException(413 if "bigger" in str(exc) else 422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(507 if getattr(exc, "errno", None) == 28 else 500, f"Couldn't save it: {exc.strerror or exc}") from exc
        return {"path": library.relative(target), "audio": importer.is_audio(target.name)}

    @app.post("/api/import/done")
    def import_done(body: ImportDoneIn) -> dict:
        """The import is complete: log it (undo sends it to Recently deleted), then hand the music to
        the inbox, or organize it in the library."""
        require_library()
        root = import_root(body.batch)
        rels = []
        for p in _unique(body.paths):
            try:
                if p.startswith(root + "/") and library.resolve(p).is_file():
                    rels.append(p)
            except LibraryPathError:
                continue
        if not rels:
            raise HTTPException(422, "Nothing from this import arrived.")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        audio = [r for r in rels if importer.is_audio(r)]
        activity.add("import", f"Imported {len(rels)} file{'s' if len(rels) != 1 else ''}", files=rels,
                     changes=[{"key": "location", "old": "", "new": root}],
                     undo={"type": "moves", "moves": [[f"{DELETED}/{stamp}/{r.lstrip('@')}", r] for r in rels]})
        if root.startswith(inbox.settings.folder + "/") and inbox.settings.folder:
            inbox.sync(library)
            inbox_start()
            return {"files": len(rels), "audio": len(audio), "where": "inbox", "folder": root}
        lib_index.mark_dirty(rels)
        org = organize_apply(OrganizeIn(paths=audio)) if audio else {"moved": 0, "held": []}
        taken = sum(1 for h in org["held"] if h["status"] == "conflict")
        return {"files": len(rels), "audio": len(audio), "where": "library", "folder": root,
                "organized": org["moved"], "stayed": len(org["held"]),
                "stayed_taken": taken, "stayed_untagged": len(org["held"]) - taken}  # untagged or unreadable

    # --- Recently deleted -------------------------------------------------------------------------

    deleted_root = settings.config_dir / "deleted"

    @app.get("/api/deleted")
    def recently_deleted() -> dict:
        """What's in Recently deleted, newest first, with how long each is kept."""
        require_library()
        items = trash.batches(deleted_root)
        return {"items": items, "files": sum(i["files"] for i in items), "size": sum(i["size"] for i in items),
                "keep_days": trash.KEEP_DAYS}

    def deleted_original(rel_in_batch: str) -> str:
        """Where a set-aside file came from ("inbox/..." was the inbox folder)."""
        if rel_in_batch.startswith("inbox/") and library.inbox is not None:
            return "@" + rel_in_batch
        return rel_in_batch

    @app.post("/api/deleted/restore")
    def restore_deleted(body: TrashIn) -> dict:
        """Put items back where they were (never over a file that has taken their place)."""
        require_library()
        moves = []
        for bid in _unique(body.ids):
            try:
                d = trash.batch_dir(deleted_root, bid)
            except ValueError as exc:
                raise HTTPException(404, str(exc)) from exc
            for dirpath, _, names in os.walk(d):
                for n in names:
                    inside = (Path(dirpath) / n).relative_to(d).as_posix()
                    moves.append(Move(f"{DELETED}/{bid}/{inside}", deleted_original(inside), "move"))
        if not moves:
            return {"moved": 0, "failed": 0, "errors": [], **recently_deleted()}
        out = run_moves(moves, "organize", f"Put back {len(moves)} file{'s' if len(moves) != 1 else ''} from Recently deleted",
                        [{"key": "location", "old": "(recently deleted)", "new": moves[0].dst.rsplit("/", 1)[0]}])
        for bid in body.ids:  # tidy the emptied folders
            with contextlib.suppress(OSError, ValueError):
                d = trash.batch_dir(deleted_root, bid)
                for dirpath, _, _ in sorted(os.walk(d), key=lambda x: -len(x[0])):
                    with contextlib.suppress(OSError):
                        os.rmdir(dirpath)
        return {**out, **recently_deleted()}

    @app.post("/api/deleted/erase")
    def erase_deleted(body: TrashIn) -> dict:
        """Delete items for good: the one change that can't be undone. ``confirm`` must be the
        number of files, typed by you."""
        require_library()
        dirs = []
        for bid in _unique(body.ids):
            try:
                dirs.append((bid, trash.batch_dir(deleted_root, bid)))
            except ValueError as exc:
                raise HTTPException(404, str(exc)) from exc
        total = sum(trash.count_files(d) for _, d in dirs)
        if body.confirm != total:
            raise HTTPException(409, f"To delete for good, confirm the number of files ({total}).")
        gone = 0
        for bid, _ in dirs:
            try:
                gone += trash.erase(deleted_root, bid)
            except (ValueError, OSError) as exc:
                raise HTTPException(500, f"Couldn't delete it: {exc}") from exc
        activity.add("erase", f"Permanently deleted {gone} file{'s' if gone != 1 else ''} from Recently deleted",
                     changes=[{"key": "location", "old": "(recently deleted)", "new": "(gone)"}])
        return {"erased": gone, **recently_deleted()}

    shared.share(run_moves=run_moves)
