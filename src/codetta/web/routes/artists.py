"""Artists named in a credit (tapping an artist name), artist pictures and pages, and albums like
the one open (in the library, then ones it doesn't have)."""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from fastapi import HTTPException, Query, Response

from codetta.core.artistart import ArtistArt
from codetta.core.artistinfo import ArtistInfo
from codetta.core.artists import pieces, resolve, top_folders
from codetta.core.engine import MetadataError
from codetta.core.health import EDITION_RE
from codetta.core.index import sfold
from codetta.core.library import LibraryPathError

# Best-ofs and the like aren't albums to look for (Deezer lists them as albums).
COMPILATION_RE = re.compile(r"\b(?:best of|greatest hits|the essential|anthology|collection|hits|live (?:at|in|from)|remixe[sd])\b",
                            re.IGNORECASE)
DISC_RE = re.compile(r"^(?:cd|dis[ck]|side)\s*[\dA-Z]{1,2}\b", re.IGNORECASE)


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
    require_library = shared.require_library

    def known(name: str) -> int:
        """In how many folders ``name`` is a whole artist or album-artist value."""
        paths = lib_index.paths_where("artist", name, limit=400) | lib_index.paths_where("albumartist", name, limit=400)
        return len({p.rsplit("/", 1)[0] if "/" in p else "" for p in paths})

    def several(name: str, folder: str, folders: dict[str, str], credits: list[tuple[list[str], int]]) -> list[dict]:
        """The artists a folder named after several of them holds ("Ali Sethi & Nicolas Jaar"), or []
        for one artist. The tags say it best: an "album artists (all)" tag naming each of them, or
        several MusicBrainz album-artist IDs; one value or one ID there is one artist, a duo
        ("Simon & Garfunkel"). Without either, the name is split at the usual separators the way
        an artist credit is, except this folder doesn't count as an artist of its own. ``credits``
        come only from files whose album artist is the folder's name (not a stray album)."""
        if not pieces(name)[1:]:
            return []
        listed = next((names for names, _ in credits if names), None)
        if listed is not None:
            return resolve(listed, known, folders) if len(listed) > 1 else []
        if any(n > 1 for _, n in credits):
            pass  # several IDs: split the name
        elif any(n == 1 for _, n in credits):
            return []
        others = {k: v for k, v in folders.items() if v != folder}
        found = resolve([name], known, others)
        return found if len(found) > 1 else []

    # ---- Albums like this one: from the library first, then ones it doesn't have --------------------

    def album_tags(folder: str) -> tuple[str, dict]:
        """The album folder (checked) and the tags of its first file the index knows."""
        require_library()
        try:
            rel = library.relative(library.resolve(folder))
            files = library.list_folder(rel).files[:3]
        except (LibraryPathError, OSError, ValueError) as exc:
            raise HTTPException(404, "Not an album folder") from exc
        known_files = lib_index.stored(files)
        for f in files:
            if f in known_files:
                return rel, known_files[f][2].get("tags") or {}
        raise HTTPException(404, "Not an album folder")

    def first(tags: dict, *keys: str) -> str:
        return next((v for k in keys for v in tags.get(k) or [] if v.strip()), "")

    def year_of(tags: dict) -> int | None:
        y = first(tags, "originaldate", "date", "year")[:4]
        return int(y) if y.isdigit() else None

    def album_of(folder: str) -> str:
        """The album a folder is: its parent when it's one of the album's discs ("Album/CD1")."""
        parent, _, name = folder.rpartition("/")
        return parent if parent and DISC_RE.match(name) else folder

    def folders_where(key: str, value: str, limit: int = 3000) -> dict[str, str]:
        """Album folders with a file whose ``key`` is ``value``: folder -> one of its files."""
        out: dict[str, str] = {}
        for p in sorted(lib_index.paths_where(key, value, limit=limit)):
            out.setdefault(album_of(p.rsplit("/", 1)[0] if "/" in p else ""), p)
        out.pop("", None)
        return out

    @app.get("/api/albums/like")
    def albums_like(folder: str = Query(..., max_length=1000)) -> dict:
        """Albums in the library like this one: more by the same artist, then albums by similar
        artists (Deezer connection), then the same genre from about the same time."""
        rel, tags = album_tags(folder)
        rel = album_of(rel)
        artist = first(tags, "albumartist", "artist")
        genres = [g for g in tags.get("genre") or [] if g.strip()][:3]
        year = year_of(tags)
        picked: dict[str, str] = {rel: ""}  # folder -> why

        def take(found: dict[str, str], why: str, cap: int) -> list[tuple[str, str]]:
            out = []
            for f, p in found.items():
                if f not in picked and len(out) < cap:
                    picked[f] = why
                    out.append((f, p))
            return out

        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        same = {}
        if artist:
            same.update(folders_where("albumartist", artist))
        if parent:
            try:
                for sub in library.list_folder(parent).folders:
                    if not DISC_RE.match(sub.rsplit("/", 1)[-1]):  # CD1/CD2 are this album, not another
                        same.setdefault(sub, "")
            except (LibraryPathError, OSError):
                pass
        more = take(same, "artist", 24)
        similar = []
        for name in info.similar(artist, limit=25) if artist else []:
            similar += take(folders_where("albumartist", name) or folders_where("artist", name, limit=400), "similar", 3)
            if len(similar) >= 12:
                break
        by_genre: dict[str, str] = {}
        for g in genres:
            for f, p in folders_where("genre", g).items():
                by_genre.setdefault(f, p)
        rows = lib_index.stored([p for p in by_genre.values() if p])
        def distance(f: str) -> int:
            y = year_of((rows.get(by_genre[f]) or (0, 0, {}))[2].get("tags") or {})
            return abs(y - year) if y and year else 50
        genre = take({f: by_genre[f] for f in sorted(by_genre, key=distance)}, "genre", max(0, 18 - len(similar)))

        def describe(items: list[tuple[str, str]]) -> list[dict]:
            files = {f: p for f, p in items if p}
            stored = lib_index.stored(list(files.values()))
            covers = lib_index.cover_tracks([f for f, _ in items])
            out = []
            for f, _ in items:
                t = (stored.get(files.get(f, "")) or (0, 0, {}))[2].get("tags") or {}
                c = covers.get(f)
                out.append({"folder": f, "title": first(t, "album") or f.rsplit("/", 1)[-1],
                            "artist": first(t, "albumartist", "artist"), "year": str(year_of(t) or ""),
                            "cover": {"path": c[0], "hash": c[1]} if c else None})
            return out

        return {"artist": artist, "more": describe(more), "like": describe(similar + genre),
                "can": {"similar": connections.enabled("deezer")}}

    @app.get("/api/albums/elsewhere")
    def albums_elsewhere(folder: str = Query(..., max_length=1000)) -> dict:
        """Albums the library doesn't have: this artist's best-known ones, then similar artists'
        (from Deezer, so only with that connection on). Each can be looked for on Soulseek."""
        if not connections.enabled("deezer"):
            return {"albums": [], "can": False}
        rel, tags = album_tags(folder)
        artist = first(tags, "albumartist", "artist")
        if not artist:
            return {"albums": [], "can": True}
        owned = shared.owned_like
        out, seen = [], set()

        def add(albums: list[dict], why: str, cap: int) -> None:
            n = 0
            for a in albums:
                who, title = sfold(a["artist"]), sfold(EDITION_RE.sub("", a["title"]))
                if n >= cap or not title or COMPILATION_RE.search(a["title"]) or owned(a["artist"], a["title"]):
                    continue
                # One edition of each album: "Grace (Legacy Edition)", "OK Computer OKNOTOK 1997 2017"
                if any(w == who and (t.startswith(title) or title.startswith(t)
                                     or SequenceMatcher(None, t, title).ratio() >= 0.88) for w, t in seen):
                    continue
                seen.add((who, title))
                out.append({**a, "why": why})
                n += 1

        add(info.albums(artist, limit=12), "artist", 6)
        for name in info.similar(artist, limit=8):
            add(info.albums(name, limit=6), "similar", 2)
            if len(out) >= 18:
                break
        return {"albums": out, "can": True}

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
        credits = []  # per file: (album artists named one by one, how many MusicBrainz album-artist IDs)
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
                    if sfold((tags.get("albumartist") or tags.get("artist") or [""])[0]) == sfold(folder):
                        credits.append(([v for v in tags.get("albumartists") or [] if v.strip()],
                                        len(tags.get("musicbrainz_albumartistid") or [])))
        except (LibraryPathError, OSError):
            pass
        top = names.most_common(1)[0][0] if names else ""
        same = bool(top) and sfold(top) == sfold(folder)
        name = top if same else folder  # the tags' spelling ("Beyoncé") when it's this artist
        mbid = ids.most_common(1)[0][0] if ids and same else ""
        mbid = mbid if len(mbid) == 36 else ""
        together = several(name, folder, folders, credits)
        if together:  # "Ali Sethi & Nicolas Jaar": their pictures together, no bio or similar artists of one
            return {"name": name, "albums": len(albums), "bio": None, "similar": [], "artists": together,
                    "can": {"bio": info.bio_ready(), "similar": connections.enabled("deezer")}}
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
