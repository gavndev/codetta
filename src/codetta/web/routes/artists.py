"""Artists named in a credit, for tapping an artist name in the page."""

from __future__ import annotations

from fastapi import Query

from codetta.core.artists import resolve, top_folders


def register(app, shared) -> None:
    settings = shared.settings
    lib_index = shared.lib_index

    def known(name: str) -> int:
        """In how many folders ``name`` is a whole artist or album-artist value."""
        paths = lib_index.paths_where("artist", name, limit=400) | lib_index.paths_where("albumartist", name, limit=400)
        return len({p.rsplit("/", 1)[0] if "/" in p else "" for p in paths})

    @app.get("/api/artists")
    def artists_in(credit: list[str] = Query(default=[], max_length=10)) -> dict:
        """Which of the artists in these credits the library has, and their folders."""
        return {"artists": resolve([c[:500] for c in credit], known, top_folders(settings.music_dir))}
