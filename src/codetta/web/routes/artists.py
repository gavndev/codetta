"""Artists named in a credit (tapping an artist name), and artist pictures."""

from __future__ import annotations

from fastapi import HTTPException, Query, Response

from codetta.core.artistart import ArtistArt
from codetta.core.artists import resolve, top_folders


def register(app, shared) -> None:
    settings = shared.settings
    lib_index = shared.lib_index
    connections = shared.connections
    art = ArtistArt(settings.music_dir, settings.config_dir / "artist-art", lambda: connections.enabled("deezer"),
                    shared.fetch_catalog or shared.catalog_fetch, shared.download_art)
    shared.share(artist_art=art)

    def known(name: str) -> int:
        """In how many folders ``name`` is a whole artist or album-artist value."""
        paths = lib_index.paths_where("artist", name, limit=400) | lib_index.paths_where("albumartist", name, limit=400)
        return len({p.rsplit("/", 1)[0] if "/" in p else "" for p in paths})

    @app.get("/api/artists")
    def artists_in(credit: list[str] = Query(default=[], max_length=10)) -> dict:
        """Every artist these credits name, and which of them the library has under their own name."""
        return {"artists": resolve([c[:500] for c in credit], known, top_folders(settings.music_dir))}

    @app.get("/api/artists/picture")
    def artist_picture(name: str = Query(..., max_length=300), folder: str = Query("", max_length=300)) -> Response:
        """The artist's picture: artist.jpg in their folder, else Deezer's (when connected). 404: draw initials."""
        if folder and folder not in top_folders(settings.music_dir).values():
            folder = ""  # only a real top-level folder of the library
        try:
            found = art.picture(name, folder or None)
        except Exception:  # noqa: BLE001 - no picture is fine; the page draws initials
            found = None
        if not found:
            raise HTTPException(404, "No picture for this artist")
        data, kind = found
        return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=86400"})
