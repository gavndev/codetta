"""Raw tags, library search, saving tags and album art."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from codetta.core.artwork import sniff_image_type
from codetta.core.engine import MetadataError
from codetta.core.index import parse_query
from codetta.core.library import LibraryPathError
from codetta.core.rawtags import read_raw
from codetta.web.common import (
    MAX_PATH_CHARS,
    MAX_PATHS_PER_REQUEST,
    ArtInfo,
    ClauseOut,
    Crumb,
    SearchInfo,
    SearchOut,
    UpdateIn,
    UpdateResult,
    _log_art,
    _log_edit,
    _to_track_out,
    _unique,
)


def register(app, shared) -> None:
    activity = shared.activity
    art_store = shared.art_store
    engine = shared.engine
    lib_index = shared.lib_index
    library = shared.library
    require_library = shared.require_library
    to_out = shared.to_out

    @app.get("/api/track/raw")
    def get_track_raw(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")) -> dict:
        """Advanced mode: every stored field exactly as the file has it (read-only)."""
        require_library()
        return read_raw(engine, library.resolve(path))

    @app.get("/api/search", response_model=SearchOut)
    def search(
        q: str = Query(..., max_length=500, description='e.g. "genre: rap, hip-hop artist: drake" or plain words'),
        limit: int = Query(500, ge=1, le=MAX_PATHS_PER_REQUEST),
    ):
        """Search the whole library by tag. Commas mean "or"; clauses and words must all match."""
        require_library()
        query = parse_query(q, lib_index.has_key)
        tracks, total = lib_index.search(query, limit)
        lib_index.request_rescan()  # pick up music added outside Codetta (in the background)
        status = lib_index.status()
        return SearchOut(
            path="", name="Search", breadcrumbs=[Crumb(name="Library", path="")], folders=[], tracks=tracks,
            search=SearchInfo(
                query=q, words=query.words, total=total, indexing=not status.ready, indexed=status.files,
                clauses=[ClauseOut(key=c.key, label=c.label, values=c.values) for c in query.clauses if c.values],
            ),
        )

    @app.patch("/api/tracks", response_model=list[UpdateResult])
    def update_tracks(body: UpdateIn):
        """Apply the same tag changes to one or more files.

        Each file succeeds or fails on its own; check ``ok`` per result.
        """
        require_library()
        before: dict[str, dict[str, list[str]]] = {}  # for the activity log

        paths = _unique(body.paths)
        # A tag edit never touches the embedded cover: reuse what the index knows about it
        # instead of opening every file once more just to hash its picture again.
        known_art = {p: (t.get("art"),) for p, (_, _, t) in lib_index.stored(paths).items()} if len(paths) > 8 else {}

        def write(rel: str) -> UpdateResult:
            try:
                target = library.resolve(rel)
                was: dict = {}
                meta = engine.update_tags(target, body.changes, before=was, batch=wb)  # safe write: copy, check, swap
                before[rel] = was["tags"]
                if rel in known_art:
                    try:
                        mtime = target.stat().st_mtime_ns
                    except OSError:
                        mtime = None
                    out = _to_track_out(rel, meta, mtime)
                    art = known_art[rel][0]
                    out.art = ArtInfo(**art) if art else None
                    return UpdateResult(path=rel, ok=True, track=out)
                return UpdateResult(path=rel, ok=True, track=to_out(rel, meta))
            except (MetadataError, LibraryPathError, OSError) as exc:
                return UpdateResult(path=rel, ok=False, error=library.message(exc))

        with engine.batch() as wb:  # each album folder is flushed once, at the end
            if len(paths) > 8:
                # Most of a safe write is waiting for the disk, so a few at once is ~1.6x faster
                # (more on hard drives). Each file still has its own lock and its own safe write.
                with ThreadPoolExecutor(max_workers=4, thread_name_prefix="codetta-write") as pool:
                    results = list(pool.map(write, paths))
            else:
                results = [write(rel) for rel in paths]
        keys = {k.lower() for k in body.changes}
        undo_files = {}
        for r in results:
            if r.ok and r.path in before:
                b = {k: before[r.path].get(k, []) for k in keys}
                a = {k: r.track.tags.get(k, []) for k in keys}
                changed = [k for k in keys if b[k] != a[k]]
                if changed:
                    undo_files[r.path] = {"before": {k: b[k] for k in changed}, "after": {k: a[k] for k in changed}}
        _log_edit(activity, body.changes, results, before,
                  undo={"type": "tags", "files": undo_files} if undo_files else None)
        lib_index.mark_dirty(r.path for r in results if r.ok)
        return results

    # --- Album art ---------------------------------------------------------------------

    @app.get("/api/art", responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}})
    def get_art(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")):
        """The track's embedded cover image (404 if it has none)."""
        require_library()
        art = engine.read_artwork(library.resolve(path))
        if art is None:
            raise HTTPException(404, "This track has no album art")
        # The type is decided from the image's actual bytes, never from what the
        # file claims ("image/jpeg" holding HTML, "text/html", SVG...). Anything
        # that isn't a real JPEG/PNG/WebP/GIF is sent as a download, so a
        # booby-trapped file can never run a script inside Codetta.
        mime = sniff_image_type(art.data)
        if mime:
            return Response(art.data, media_type=mime, headers={"Cache-Control": "private, max-age=31536000, immutable"})
        return Response(art.data, media_type="application/octet-stream", headers={
            "Content-Disposition": 'attachment; filename="cover.bin"', "Cache-Control": "no-store"})

    @app.put("/api/art", response_model=list[UpdateResult])
    async def set_art(request: Request, path: list[str] = Query(..., description="One or more files")):
        """Embed the request body (a JPEG or PNG image) as album art in each file."""
        require_library()
        if len(path) > MAX_PATHS_PER_REQUEST:
            raise HTTPException(422, f"Too many files in one request (max {MAX_PATHS_PER_REQUEST})")
        image = await request.body()  # size already capped by GuardMiddleware
        return await run_in_threadpool(_change_art, _unique(path), image)

    @app.delete("/api/art", response_model=list[UpdateResult])
    def delete_art(path: list[str] = Query(..., description="One or more files")):
        """Remove all embedded pictures from each file."""
        require_library()
        if len(path) > MAX_PATHS_PER_REQUEST:
            raise HTTPException(422, f"Too many files in one request (max {MAX_PATHS_PER_REQUEST})")
        return _change_art(_unique(path), None)

    def _change_art(paths: list[str], image: bytes | None) -> list[UpdateResult]:
        results, had_art = [], 0
        art = None
        undo_files = {}
        wb = engine.batch()
        for rel in paths:
            try:
                target = library.resolve(rel)
                old = engine.read_artwork(target)
                had_art += old is not None
                art = engine.update_artwork(target, image, batch=wb)
                # Keep both images so the change can be undone (and redone).
                try:
                    before = art_store.save(old.data if old else None)
                    after = art_store.save(art.data if art else None)
                    if before != after:
                        undo_files[rel] = {"before": before, "after": after}
                except OSError:
                    pass  # couldn't keep a copy: this change just won't be undoable
                results.append(UpdateResult(path=rel, ok=True, track=to_out(rel, engine.load_metadata(target))))
            except (MetadataError, LibraryPathError, OSError) as exc:
                results.append(UpdateResult(path=rel, ok=False, error=library.message(exc)))
        wb.flush()  # the folders' renames, once, before the change is logged
        _log_art(activity, image is not None, art, had_art, results,
                 undo={"type": "art", "files": undo_files} if undo_files else None)
        lib_index.mark_dirty(r.path for r in results if r.ok)
        return results

    shared.share(set_art=set_art)
