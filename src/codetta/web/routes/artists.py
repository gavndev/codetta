"""Artists named in a credit (tapping an artist name), and artist pictures."""

from __future__ import annotations

from fastapi import HTTPException, Query, Response

from collections import Counter

from codetta.core.artistart import ArtistArt
from codetta.core.artistinfo import ArtistInfo
from codetta.core.artists import resolve, top_folders
from codetta.core.engine import MetadataError
from codetta.core.index import sfold
from codetta.core.library import LibraryPathError


def register(app, shared) -> None:
    settings = shared.settings
    lib_index = shared.lib_index
    connections = shared.connections
    art = ArtistArt(settings.music_dir, settings.config_dir / "artist-art", lambda: connections.enabled("deezer"),
                    shared.fetch_catalog or shared.catalog_fetch, shared.download_art)
    shared.share(artist_art=art)
    info = ArtistInfo(settings.config_dir / "artist-info.json", shared.mb, shared.wiki_fetch,
                      shared.fetch_catalog or shared.catalog_fetch, connections.enabled)
    library, engine = shared.library, shared.engine

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

    @app.get("/api/artists/info")
    def artist_info(folder: str = Query(..., max_length=300), lang: str = Query("en", max_length=5)) -> dict:
        """The top of an artist's folder: their name (from the tags), a bio and similar artists (each
        only with its connections on), and which similar artists have a folder here."""
        folders = top_folders(settings.music_dir)
        if folder not in folders.values():
            raise HTTPException(404, "Not an artist folder")
        # A look at the albums: one file from each of the first few subfolders.
        names, ids, albums = Counter(), Counter(), []
        try:
            for sub in library.list_folder(folder).folders[:12]:
                listing = library.list_folder(sub)
                files = listing.files[:1] or (library.list_folder(listing.folders[0]).files[:1] if listing.folders else [])  # CD1/
                for rel in files:
                    try:
                        tags = engine.load_metadata(library.resolve(rel)).tags
                    except (MetadataError, LibraryPathError, OSError):
                        continue
                    for n in (tags.get("albumartist") or tags.get("artist") or [])[:1]:
                        names[n] += 1
                    for i in (tags.get("musicbrainz_albumartistid") or [])[:1]:
                        ids[i] += 1
                    albums += (tags.get("album") or [])[:1]
        except (LibraryPathError, OSError):
            pass
        top = names.most_common(1)[0][0] if names else ""
        same = bool(top) and sfold(top) == sfold(folder)
        name = top if same else folder  # the tags' spelling ("Beyoncé") when it's this artist
        mbid = ids.most_common(1)[0][0] if ids and same else ""
        mbid = mbid if len(mbid) == 36 else ""
        seen = {sfold(name), sfold(folder)}
        similar = []
        for n in info.similar(name):
            if sfold(n) not in seen:  # never the artist themselves, nor the same name twice ("che" / "Che")
                seen.add(sfold(n))
                similar.append({"name": n, "folder": folders.get(sfold(n))})
        similar.sort(key=lambda a: a["folder"] is None)  # the ones you have first
        return {"name": name, "albums": len(albums), "bio": info.bio(name, mbid, albums, lang.split("-")[0].lower()),
                "similar": similar,
                "can": {"bio": info.bio_ready(), "similar": connections.enabled("deezer")}}
