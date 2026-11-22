"""Exploring from the search bar: MusicBrainz (the !mb bang), Deezer (!dz) and iTunes (!it)."""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, Query

from codetta.core.health import EDITION_RE
from codetta.core.health import _base_artist as base_artist
from codetta.core.health import fold as health_fold
from codetta.core.musicbrainz import (
    MBID_RE,
    artist_links,
    artist_summary,
    group_summary,
    pick_release,
    tracklist,
)
from codetta.core.providers import ProviderError


def register(app, shared) -> None:
    catalogs = shared.catalogs
    lib_index = shared.lib_index
    mb = shared.mb
    require_connection = shared.require_connection

    owned_cache: dict = {"key": None, "albums": {}}

    def owned_albums() -> dict[str, dict[str, str]]:
        """Albums in the library: artist (folded) -> album name (folded, also without
        "(Deluxe)"-style suffixes) -> folder. From the index, rebuilt when it changes."""
        key = lib_index.version
        if owned_cache["key"] != key:
            albums: dict[str, dict[str, str]] = {}
            for path, track in lib_index.iter_tracks():
                tags = track.get("tags") or {}
                album = next((v for v in tags.get("album", []) if v.strip()), "")
                who = next((v for v in tags.get("albumartist", []) + tags.get("artist", []) if v.strip()), "")
                if not album or not who:
                    continue
                folder = path.rsplit("/", 1)[0] if "/" in path else ""
                names = albums.setdefault(health_fold(base_artist(who)), {})
                for name in {health_fold(album), health_fold(EDITION_RE.sub("", album))}:
                    names.setdefault(name, folder)
            owned_cache.update(key=key, albums=albums)
        return owned_cache["albums"]

    def owned_folder(artist: str, title: str) -> str | None:
        names = owned_albums().get(health_fold(base_artist(artist)))
        if not names:
            return None
        return names.get(health_fold(title)) or names.get(health_fold(EDITION_RE.sub("", title)))

    def with_owned(g: dict) -> dict:
        return {**g, "in_library": owned_folder(g["artist"], g["title"]) if g["artist"] else None}

    @app.get("/api/catalog/search")
    def catalog_search(source: Literal["deezer", "itunes", "discogs"], q: str = Query(..., min_length=1, max_length=200)) -> dict:
        """The !dz and !it bangs: albums on Deezer or iTunes, marked when they're already in the library."""
        require_connection(source)
        if sum(ch.isalnum() for ch in q) < 2:
            raise HTTPException(422, "Type at least two letters or numbers.")
        try:
            found = catalogs.search_text(source, q)
        except LookupError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        albums = []
        for r in found:
            artist = r.get("_artist") or ""
            albums.append(with_owned({
                "id": r["id"], "title": r.get("title") or "", "artist": artist, "year": (r.get("date") or "")[:4],
                "type": (r.get("release-group") or {}).get("primary-type") or "", "tracks": r.get("track-count"),
                "url": r.get("_url") or "",
            }))
        return {"source": source, "query": q, "albums": albums}

    def explore(call, mbid: str | None = None):
        if mbid is not None and not MBID_RE.match(mbid):
            raise HTTPException(422, "That isn't a MusicBrainz ID.")
        require_connection("musicbrainz")
        try:
            return call()
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/api/mb/search")
    def mb_explore_search(q: str = Query(..., min_length=1, max_length=200)) -> dict:
        """Artists and releases on MusicBrainz matching ``q`` (two requests: about two seconds)."""
        q = " ".join(q.split())
        if sum(c.isalnum() for c in q) < 2:
            raise HTTPException(422, "Type at least two letters or numbers to search MusicBrainz.")
        def run():
            artists = [artist_summary(a) for a in mb.search_artists(q)]
            groups = [with_owned(group_summary(g)) for g in mb.search_release_groups(q)]
            return {"query": q, "artists": [a for a in artists if (a["score"] or 0) >= 60][:8],
                    "releases": [g for g in groups if (g["score"] or 0) >= 60][:15]}
        return explore(run)

    @app.get("/api/mb/artist/{mbid}")
    def mb_explore_artist(mbid: str) -> dict:
        """An artist: who they are, links, and their albums, EPs and singles."""
        def run():
            a = mb.artist(mbid)
            groups = [group_summary(g) for g in mb.artist_release_groups(mbid)]
            name = a.get("name") or ""
            for g in groups:
                g["artist"] = g["artist"] or name
                g["in_library"] = owned_folder(name, g["title"])
            genres = sorted((x for x in a.get("genres") or [] if isinstance(x, dict)), key=lambda x: -(x.get("count") or 0))
            return {**artist_summary(a), "links": artist_links(a), "genres": [x.get("name") for x in genres[:6]],
                    "groups": groups}
        return explore(run, mbid)

    @app.get("/api/mb/release-group/{mbid}")
    def mb_explore_group(mbid: str) -> dict:
        """A release: what it is, its first official edition's tracklist and label."""
        def run():
            g = mb.release_group(mbid)
            out = with_owned(group_summary(g))
            pick = pick_release(g)
            out["editions"] = len(g.get("releases") or [])
            genres = sorted((x for x in g.get("genres") or [] if isinstance(x, dict)), key=lambda x: -(x.get("count") or 0))
            out["genres"] = [x.get("name") for x in genres[:6]]
            out["release"] = None
            if pick:
                rel = mb.release_tracks_summary(pick["id"])
                labels = [li for li in rel.get("label-info") or [] if isinstance(li, dict)]
                media = [m for m in rel.get("media") or [] if isinstance(m, dict)]
                out["release"] = {
                    "id": rel.get("id"), "date": rel.get("date") or "", "country": rel.get("country") or "",
                    "label": next(((li.get("label") or {}).get("name") for li in labels if li.get("label")), ""),
                    "catno": next((li.get("catalog-number") for li in labels if li.get("catalog-number")), ""),
                    "format": " + ".join(dict.fromkeys(m.get("format") or "Digital" for m in media)),
                    "tracks": tracklist(rel),
                }
            return out
        return explore(run, mbid)
