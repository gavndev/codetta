"""Browsing the library, streaming a track and its lyrics."""
from __future__ import annotations

import re

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse

from codetta.core.library import is_special
from codetta.core.engine import MetadataError
from codetta.core.library import LibraryPathError
from codetta.core.providers import ProviderError, TrackQuery
from codetta.web.common import (
    MAX_PATH_CHARS,
    STREAM_TYPES,
    BrowseOut,
    Crumb,
    FolderCoversIn,
    TrackOut,
)


def register(app, shared) -> None:
    engine = shared.engine
    folder_out = shared.folder_out
    lib_index = shared.lib_index
    library = shared.library
    lrclib = shared.lrclib
    require_connection = shared.require_connection
    require_library = shared.require_library
    to_out = shared.to_out
    tracks_out = shared.tracks_out

    @app.get("/api/browse", response_model=BrowseOut)
    def browse(path: str = Query("", max_length=MAX_PATH_CHARS, description="Folder, relative to the music folder")):
        """One folder: its subfolders and the tags of its audio files."""
        require_library()
        listing = library.list_folder(path)
        crumbs = [Crumb(name="Library", path="")]
        parts = listing.path.split("/") if listing.path else []
        for i, part in enumerate(parts):
            crumbs.append(Crumb(name=part, path="/".join(parts[: i + 1])))
        return BrowseOut(
            path=listing.path,
            name=crumbs[-1].name,
            breadcrumbs=crumbs,
            folders=[folder_out(f) for f in listing.folders],
            skipped=listing.skipped,
            tracks=tracks_out(listing.files),
        )

    @app.post("/api/folder-covers")
    def folder_covers(body: FolderCoversIn) -> dict:
        """A cover for each folder in the grid: a track inside it with embedded art (from the
        search index, so nothing is read from disk). The page shows it with /api/art."""
        require_library()
        folders = []
        for rel in body.paths:
            try:
                folders.append(library.relative(library.resolve(rel)))  # rejects anything outside the library
            except (LibraryPathError, ValueError):
                continue
        found = lib_index.cover_tracks(f for f in folders if not is_special(f))
        return {"covers": {f: {"path": p, "hash": h} for f, (p, h) in found.items()}}

    @app.get("/api/track", response_model=TrackOut)
    def get_track(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")):
        require_library()
        return to_out(path, engine.load_metadata(library.resolve(path)))

    @app.get("/api/stream", responses={200: {"content": {"audio/*": {}}}, 206: {"description": "Part of the file"}})
    def stream(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")):
        """The audio file itself, for the in-browser player. Supports seeking
        (HTTP range requests); nothing is converted or cached."""
        require_library()
        target = library.resolve(path)
        mime = STREAM_TYPES.get(target.suffix.lower())
        if mime is None or not target.is_file():
            raise HTTPException(404, "No such audio file")
        # The type comes from Codetta's own list (always audio/*), never from the file.
        return FileResponse(target, media_type=mime, content_disposition_type="inline",
                            headers={"Cache-Control": "private, max-age=3600"})

    LRC_LINE = re.compile(r"^\s*\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]")

    @app.get("/api/lyrics")
    def get_lyrics(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")) -> dict:
        """The track's lyrics for the player: the lyrics tag, else a ``.lrc`` file next to it
        (as Navidrome reads them). ``synced`` when it's timed LRC."""
        require_library()
        target = library.resolve(path)
        text, source = "", None
        try:
            text = "\n".join(engine.load_metadata(target).tags.get("lyrics", [])).strip()
            source = "tag" if text else None
        except (MetadataError, OSError):
            pass
        if not text:
            side = target.with_suffix(".lrc")
            try:
                if side.is_file() and side.stat().st_size <= 512 * 1024:
                    text, source = side.read_text("utf-8", errors="replace").strip(), "file"
            except OSError:
                pass
        synced = sum(1 for line in text.splitlines() if LRC_LINE.match(line)) >= 2
        return {"lyrics": text, "source": source, "synced": synced}

    @app.get("/api/lyrics/lookup")
    def lyrics_lookup(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")) -> dict:
        """Look up lyrics for a track on LRCLIB (sends artist, title, album and length only).
        Returns a suggestion; nothing is written."""
        require_connection("lyrics")
        require_library()
        meta = engine.load_metadata(library.resolve(path))
        first = lambda key: (meta.tags.get(key) or [""])[0].strip()
        artist = first("artist") or first("albumartist")
        title = first("title")
        if not artist or not title:
            raise HTTPException(422, "Add the artist and title first, so the right song can be found.")
        try:
            result = lrclib.lyrics(TrackQuery(artist=artist, title=title, album=first("album"), duration=meta.duration))
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"found": result is not None, "result": result.to_dict() if result else None}
