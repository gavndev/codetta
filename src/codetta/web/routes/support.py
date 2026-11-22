"""Search ideas, the server log and Report a problem, tag names and subfolders."""
from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import HTTPException, Query

from codetta.core.logbuffer import shared_buffer
from codetta.core.musicbrainz import clean_title
from codetta.core.tagmap import FIELDS, native_names
from codetta.web.common import MAX_PATH_CHARS, VERSION


def register(app, shared) -> None:
    care = shared.care
    connections = shared.connections
    lib_index = shared.lib_index
    library = shared.library
    require_library = shared.require_library

    ideas_cache: dict = {"at": -1e9, "data": None}

    @app.get("/api/search/ideas")
    def search_ideas() -> dict:
        """Real artists, albums, genres and moods from your library, for the search bar's rolling
        examples. A fresh random handful every 10 minutes; read from the index only."""
        require_library()
        if ideas_cache["data"] is None or time.monotonic() - ideas_cache["at"] > 600:
            v = lib_index.sample_values(("albumartist", "artist", "album", "genre", "mood"))
            artists = list(dict.fromkeys(v["albumartist"] + v["artist"]))[:12]
            albums = list(dict.fromkeys(a for a in (clean_title(x) for x in v["album"]) if a))  # "Rumours (2004 Remaster)" -> "Rumours"
            ideas_cache["data"] = {"artist": artists, "album": albums, "genre": v["genre"], "mood": v["mood"]}
            ideas_cache["at"] = time.monotonic()
        return ideas_cache["data"]

    log_buffer = shared_buffer()

    @app.get("/api/logs")
    def server_log(after: int = Query(0, ge=0, description="Only lines after this id")) -> dict:
        """Advanced mode: Codetta's own recent log lines (memory only, the last 500), for the live view.
        No visitor records, and anything shaped like a secret is masked."""
        lines = log_buffer.since(after)
        return {"lines": lines, "last": lines[-1]["id"] if lines else after}

    def install_kind() -> str:
        """How this Codetta was installed, in the words a bug report needs."""
        import sys
        if os.environ.get("SNAP"):
            return "snap"
        if Path("/.dockerenv").exists() or os.environ.get("CODETTA_IN_DOCKER"):
            return "Docker"
        if "pipx" in Path(sys.prefix).parts:
            return "pipx"
        if "site-packages" not in Path(__file__).parts:
            return "source checkout"
        return "pip"

    @app.get("/api/report")
    def problem_report() -> dict:
        """For "Report a problem": the version, how Codetta is installed, which connections are on,
        and recent warnings. No usernames; anything shaped like a secret is already masked."""
        import platform
        install = install_kind()
        lines = [ln for ln in log_buffer.since(0) if ln.get("level") in ("warning", "error", "critical")][-30:]
        return {"version": VERSION, "install": install, "python": platform.python_version(), "system": platform.system(),
                "connections": sorted(k for k in ("musicbrainz", "acoustid", "deezer", "itunes", "discogs", "lyrics", "slskd", "updates")
                                      if connections.enabled(k)),
                "tracks": lib_index.status().files, "tidy_up": care.mode,
                "log": [{"time": ln["time"], "level": ln["level"], "message": ln["message"]} for ln in lines]}

    @app.get("/api/tagnames")
    def tag_names(format: str = Query(..., max_length=20, description="A file format, e.g. flac, mp3, m4a")) -> dict:
        """Advanced mode: how this format stores each of Codetta's fields (None: it can't)."""
        return {"format": format, "names": native_names(format.lower(), [f.key for f in FIELDS])}

    @app.get("/api/folders")
    def list_subfolders(path: str = Query("", max_length=MAX_PATH_CHARS, description="Folder, relative to the music folder")) -> dict:
        """Just the subfolders of one folder (for the "Move to" picker): no tags are read."""
        require_library()
        if path.strip("/").startswith("@"):
            raise HTTPException(422, "Choose a folder inside your music folder.")
        listing = library.list_folder(path)
        return {"path": listing.path, "folders": [{"name": f.rsplit("/", 1)[-1], "path": f} for f in listing.folders]}
