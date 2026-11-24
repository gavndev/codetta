"""Music apps: the Subsonic / OpenSubsonic API at /rest/, and its settings.

/rest/ is outside Codetta's own sign-in (apps can't hold a session cookie); every request
signs in with the app password instead (see core/subsonic.py), failed attempts are
rate-limited like the sign-in page, and it all answers "off" until switched on.
"""

from __future__ import annotations

import random
import re
import time

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response

from codetta.core.artwork import sniff_image_type
from codetta.core.auth import LoginRateLimiter
from codetta.core.index import sfold
from codetta.core.library import LibraryPathError, is_special
from codetta.core.subsonic import (
    CONTENT_TYPES,
    EXTENSIONS,
    MISSING,
    NOT_AUTHORIZED,
    NOT_FOUND,
    WRONG_LOGIN,
    CatalogCache,
    SubsonicError,
    SubsonicStore,
    check_login,
    envelope,
    make_id,
    read_id,
    to_json,
    to_xml,
)
from codetta.web.common import VERSION, SubsonicSettingsIn

IGNORED_ARTICLES = "The El La Los Las Le Les"
MAX_LIST = 500
LRC = re.compile(r"^\s*((?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\])+)(.*)$")
STAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def register(app, shared) -> None:
    settings = shared.settings
    library = shared.library
    lib_index = shared.lib_index
    engine = shared.engine
    store = SubsonicStore(settings.config_dir / "subsonic.json")
    limiter = LoginRateLimiter()
    cache = CatalogCache(lib_index.catalog_rows, lib_index.fingerprint)

    def username() -> str:
        account = shared.accounts.get() if settings.auth else None
        return account.username if account else ""

    # --- Settings (Codetta's own page, signed in as usual) --------------------------------------

    def settings_out() -> dict:
        return {"enabled": store.settings.enabled, "password": store.settings.password if store.settings.enabled else "",
                "username": username(), "path": "/rest"}

    @app.get("/api/subsonic")
    def get_subsonic() -> dict:
        """Music app access: on or off, and how to connect (the app password, while it's on)."""
        return settings_out()

    @app.put("/api/subsonic")
    def put_subsonic(body: SubsonicSettingsIn) -> dict:
        store.settings.enabled = body.enabled
        if body.enabled and not store.settings.password:
            store.new_password()
        store.save()
        return settings_out()

    @app.post("/api/subsonic/password")
    def new_subsonic_password() -> dict:
        """A new app password: every app signed in with the old one has to sign in again."""
        store.new_password()
        store.save()
        return settings_out()

    # --- The API --------------------------------------------------------------------------------

    def ok(params: dict, payload: dict | None = None, error: SubsonicError | None = None) -> Response:
        body = envelope(VERSION, payload, error)
        fmt = params.get("f", "xml")
        if fmt == "json":
            return Response(to_json(body), media_type="application/json", headers=CORS)
        if fmt == "jsonp" and re.fullmatch(r"[A-Za-z_$][\w$.]{0,60}", params.get("callback", "")):
            return Response(f"{params['callback']}({to_json(body)});", media_type="application/javascript", headers=CORS)
        return Response(to_xml(body), media_type="application/xml", headers=CORS)

    def need(params: dict, key: str) -> str:
        value = params.get(key)
        if value is None or value == "":
            raise SubsonicError(MISSING, f"Required parameter is missing: {key}")
        return value

    def number(params: dict, key: str, default: int, top: int = MAX_LIST) -> int:
        try:
            return max(0, min(top, int(params.get(key, default))))
        except ValueError:
            return default

    def song_path(cat, raw: str) -> str:
        kind, value = read_id(raw)
        if kind != "s" or raw not in cat.songs:
            raise SubsonicError(NOT_FOUND, "Song not found")
        return value

    def songs_of(cat, raw: str) -> list:
        """The songs behind any ID: a song, an album, an artist or a folder."""
        kind, value = read_id(raw)
        if kind == "s" and raw in cat.songs:
            return [cat.songs[raw]]
        if kind == "a" and raw in cat.albums:
            return [cat.songs[s] for s in cat.albums[raw].songs]
        if kind == "r" and raw in cat.artists:
            return [cat.songs[s] for a in cat.artists[raw].albums for s in cat.albums[a].songs]
        if kind == "d":
            prefix = value.rstrip("/") + "/" if value else ""
            return [s for s in cat.songs.values() if s.path.startswith(prefix)]
        raise SubsonicError(NOT_FOUND, "Not found")

    def directory(cat, raw: str) -> dict:
        kind, value = read_id(raw)
        if kind == "a" and raw in cat.albums:
            a = cat.albums[raw]
            return {"id": a.id, "name": a.name, "parent": a.artist_id,
                    "child": [cat.song_out(cat.songs[s]) for s in a.songs]}
        if kind == "r" and raw in cat.artists:
            r = cat.artists[raw]
            return {"id": r.id, "name": r.name, "child": [cat.album_out(cat.albums[a]) for a in r.albums]}
        if kind == "d":
            if is_special(value):
                raise SubsonicError(NOT_FOUND, "Folder not found")
            try:
                listing = library.list_folder(value)
            except (LibraryPathError, OSError, ValueError):
                raise SubsonicError(NOT_FOUND, "Folder not found") from None
            parent = value.rsplit("/", 1)[0] if "/" in value else ""
            kids = [{"id": make_id("d", f), "parent": raw, "isDir": True, "title": f.rsplit("/", 1)[-1]}
                    for f in listing.folders if not is_special(f)]
            for path in listing.files:
                song = cat.songs.get(make_id("s", path))
                if song is not None:
                    kids.append({**cat.song_out(song), "parent": raw})
            return {"id": raw, "name": value.rsplit("/", 1)[-1] or "Music", "parent": make_id("d", parent), "child": kids}
        raise SubsonicError(NOT_FOUND, "Folder not found")

    def albums_list(cat, params: dict) -> list:
        kind = params.get("type", "alphabeticalByName")
        albums = list(cat.albums.values())
        if kind == "random":
            random.shuffle(albums)
        elif kind in ("newest", "recent", "frequent"):
            albums.sort(key=lambda a: -a.created)
        elif kind == "alphabeticalByArtist":
            albums.sort(key=lambda a: (sfold(a.artist), a.year or 0, sfold(a.name)))
        elif kind == "byYear":
            lo, hi = number(params, "fromYear", 0, 9999), number(params, "toYear", 9999, 9999)
            albums = [a for a in albums if a.year and min(lo, hi) <= a.year <= max(lo, hi)]
            albums.sort(key=lambda a: a.year or 0, reverse=lo > hi)
        elif kind == "byGenre":
            want = sfold(need(params, "genre"))
            albums = sorted((a for a in albums if sfold(a.genre) == want), key=lambda a: sfold(a.name))
        elif kind in ("starred", "highest"):
            albums = []  # Codetta keeps no stars or ratings
        else:
            albums.sort(key=lambda a: sfold(a.name))
        off, size = number(params, "offset", 0, 10**9), number(params, "size", 10)
        return [cat.album_out(a) for a in albums[off:off + size]]

    def random_songs(cat, params: dict) -> list:
        songs = list(cat.songs.values())
        genre = sfold(params.get("genre", ""))
        lo, hi = number(params, "fromYear", 0, 9999), number(params, "toYear", 9999, 9999)
        out = []
        for s in songs:
            out_song = cat.song_out(s)
            if genre and sfold(out_song.get("genre", "")) != genre:
                continue
            if ("fromYear" in params or "toYear" in params) and not (out_song.get("year") and lo <= out_song["year"] <= hi):
                continue
            out.append(out_song)
        random.shuffle(out)
        return out[:number(params, "size", 10)]

    def genres(cat) -> list:
        counts: dict[str, list] = {}
        for s in cat.songs.values():
            g = (cat.song_out(s).get("genre") or "").strip()
            if g:
                c = counts.setdefault(g, [0, set()])
                c[0] += 1
                c[1].add(s.album_id)
        return [{"value": g, "songCount": n, "albumCount": len(albums)} for g, (n, albums) in sorted(counts.items())]

    def lyrics_of(path: str) -> str:
        try:
            tags = engine.load_metadata(library.resolve(path)).tags
        except Exception:  # noqa: BLE001 - no lyrics is an answer too
            return ""
        for key in ("lyrics", "unsyncedlyrics"):
            if tags.get(key):
                return str(tags[key][0])
        return ""

    def structured(text: str) -> dict | None:
        lines, synced = [], False
        for raw in text.splitlines():
            m = LRC.match(raw)
            if m:
                synced = True
                for mm, ss, frac in STAMP.findall(m.group(1)):
                    ms = (int(mm) * 60 + int(ss)) * 1000 + (int((frac + "00")[:3]) if frac else 0)
                    lines.append({"start": ms, "value": m.group(2).strip()})
            elif raw.strip() and not re.match(r"^\s*\[[a-z]+:", raw, re.I):
                lines.append({"value": raw.strip()})
        if not lines:
            return None
        if synced:
            lines = sorted((x for x in lines if "start" in x), key=lambda x: x["start"])
        return {"lang": "xxx", "synced": synced, "line": lines}

    def cover(cat, raw: str) -> Response:
        try:
            paths = [s.path for s in songs_of(cat, raw) if s.track.get("art")]
        except SubsonicError:
            paths = []
        kind, _ = read_id(raw) if raw else ("", "")
        if kind == "a" and raw in cat.albums and cat.albums[raw].cover:
            paths.insert(0, cat.albums[raw].cover)
        for path in paths[:3]:
            try:
                art = engine.read_artwork(library.resolve(path))
            except Exception:  # noqa: BLE001 - try the next file
                continue
            if art is not None and sniff_image_type(art.data):
                return Response(art.data, media_type=sniff_image_type(art.data),
                                headers={**CORS, "Cache-Control": "private, max-age=86400"})
        raise SubsonicError(NOT_FOUND, "No cover art")

    def similar(cat, raw: str, count: int) -> list:
        seeds = [s.path for s in songs_of(cat, raw)][:3]
        autoplay = getattr(shared, "autoplay", None)
        if not seeds or autoplay is None:
            return []
        found = autoplay.next_tracks(seeds, set(seeds), min(count, 30))
        return [cat.song_out(cat.songs[make_id("s", p)]) for p in found["paths"] if make_id("s", p) in cat.songs]

    def handle(method: str, params: dict) -> Response | dict:
        cat = cache.get()
        m = method
        if m == "ping":
            return {}
        if m == "getLicense":
            return {"license": {"valid": True}}
        if m == "getOpenSubsonicExtensions":
            return {"openSubsonicExtensions": EXTENSIONS}
        if m == "getMusicFolders":
            return {"musicFolders": {"musicFolder": [{"id": 1, "name": "Music"}]}}
        if m == "getIndexes":
            groups: dict[str, list] = {}
            for f in library.list_folder("").folders:
                if is_special(f):
                    continue
                letter = (sfold(f)[:1] or "#").upper()
                groups.setdefault(letter if letter.isalpha() else "#", []).append({"id": make_id("d", f), "name": f})
            return {"indexes": {"lastModified": int(time.time() * 1000), "ignoredArticles": IGNORED_ARTICLES,
                                "index": [{"name": k, "artist": v} for k, v in sorted(groups.items())]}}
        if m == "getMusicDirectory":
            return {"directory": directory(cat, need(params, "id"))}
        if m == "getArtists":
            return {"artists": {"ignoredArticles": IGNORED_ARTICLES, "index": cat.indexes()}}
        if m == "getArtist":
            raw = need(params, "id")
            if raw not in cat.artists:
                raise SubsonicError(NOT_FOUND, "Artist not found")
            return {"artist": cat.artist_out(cat.artists[raw], with_albums=True)}
        if m == "getAlbum":
            raw = need(params, "id")
            if raw not in cat.albums:
                raise SubsonicError(NOT_FOUND, "Album not found")
            return {"album": cat.album_out(cat.albums[raw], with_songs=True)}
        if m == "getSong":
            raw = need(params, "id")
            song_path(cat, raw)
            return {"song": cat.song_out(cat.songs[raw])}
        if m in ("getAlbumList2", "getAlbumList"):
            return {"albumList2" if m.endswith("2") else "albumList": {"album": albums_list(cat, params)}}
        if m == "getRandomSongs":
            return {"randomSongs": {"song": random_songs(cat, params)}}
        if m == "getSongsByGenre":
            want = sfold(need(params, "genre"))
            songs = [cat.song_out(s) for s in cat.songs.values() if sfold(cat.song_out(s).get("genre", "")) == want]
            off = number(params, "offset", 0, 10**9)
            return {"songsByGenre": {"song": songs[off:off + number(params, "count", 10)]}}
        if m == "getGenres":
            return {"genres": {"genre": genres(cat)}}
        if m in ("search3", "search2"):
            artists, albums, songs = cat.search(params.get("query", ""))
            def page(items, key, default):
                off = number(params, key + "Offset", 0, 10**9)
                return items[off:off + number(params, key + "Count", default)]
            return {"searchResult3" if m == "search3" else "searchResult2": {
                "artist": [cat.artist_out(r) for r in page(artists, "artist", 20)],
                "album": [cat.album_out(a) for a in page(albums, "album", 20)],
                "song": [cat.song_out(s) for s in page(songs, "song", 20)]}}
        if m in ("getStarred2", "getStarred"):
            return {"starred2" if m.endswith("2") else "starred": {}}
        if m in ("star", "unstar", "setRating", "scrobble"):
            return {}  # accepted; Codetta keeps no stars, ratings or play counts
        if m == "getPlaylists":
            return {"playlists": {}}
        if m == "getPlaylist":
            raise SubsonicError(NOT_FOUND, "Playlist not found")
        if m == "getNowPlaying":
            return {"nowPlaying": {}}
        if m in ("getInternetRadioStations", "getPodcasts", "getNewestPodcasts", "getBookmarks", "getPlayQueue", "getShares"):
            key = {"getInternetRadioStations": "internetRadioStations", "getPodcasts": "podcasts",
                   "getNewestPodcasts": "newestPodcasts", "getBookmarks": "bookmarks", "getPlayQueue": "playQueue",
                   "getShares": "shares"}[m]
            return {key: {}}
        if m == "getUser":
            return {"user": {"username": params.get("u") or username() or "codetta", "scrobblingEnabled": False,
                             "adminRole": False, "settingsRole": False, "downloadRole": True, "uploadRole": False,
                             "playlistRole": False, "coverArtRole": True, "commentRole": False, "podcastRole": False,
                             "streamRole": True, "jukeboxRole": False, "shareRole": False, "videoConversionRole": False,
                             "folder": [1]}}
        if m in ("getScanStatus", "startScan"):
            if m == "startScan":
                lib_index.request_rescan()
            status = lib_index.status()
            return {"scanStatus": {"scanning": bool(status.scanning), "count": status.files}}
        if m in ("getArtistInfo2", "getArtistInfo"):
            return {"artistInfo2" if m.endswith("2") else "artistInfo": {}}
        if m in ("getAlbumInfo2", "getAlbumInfo"):
            return {"albumInfo": {}}
        if m in ("getSimilarSongs2", "getSimilarSongs"):
            songs = similar(cat, need(params, "id"), number(params, "count", 50))
            return {"similarSongs2" if m.endswith("2") else "similarSongs": {"song": songs}}
        if m == "getTopSongs":
            return {"topSongs": {}}
        if m == "getLyrics":
            title, artist = sfold(params.get("title", "")), sfold(params.get("artist", ""))
            for s in cat.songs.values():
                o = cat.song_out(s)
                if title and sfold(o["title"]) == title and (not artist or sfold(o["artist"]) == artist):
                    return {"lyrics": {"artist": o["artist"], "title": o["title"], "value": lyrics_of(s.path)}}
            return {"lyrics": {}}
        if m == "getLyricsBySongId":
            path = song_path(cat, need(params, "id"))
            found = structured(lyrics_of(path))
            return {"lyricsList": {"structuredLyrics": [found] if found else []}}
        if m in ("stream", "download"):
            path = song_path(cat, need(params, "id"))
            target = library.resolve(path)
            if not target.is_file():
                raise SubsonicError(NOT_FOUND, "Song not found")
            suffix = target.suffix.lower().lstrip(".")
            return FileResponse(target, media_type=CONTENT_TYPES.get(suffix, "application/octet-stream"),
                                content_disposition_type="attachment" if m == "download" else "inline",
                                filename=target.name if m == "download" else None, headers=CORS)
        if m == "getCoverArt":
            return cover(cat, need(params, "id"))
        if m == "getAvatar":
            raise SubsonicError(NOT_FOUND, "No avatar")
        raise SubsonicError(NOT_FOUND, f"Unknown method: {m}")

    @app.api_route("/rest/{method}", methods=["GET", "POST"], include_in_schema=False)
    async def rest(method: str, request: Request):
        params = {k: v for k, v in request.query_params.items()}
        if request.method == "POST" and "form" in request.headers.get("content-type", ""):
            form = await request.form()
            params.update({k: v for k, v in form.items() if isinstance(v, str)})
        method = method.removesuffix(".view")
        key = request.client.host if request.client else "unknown"
        try:
            if limiter.retry_after(key):
                raise SubsonicError(WRONG_LOGIN, "Too many failed sign-ins. Try again in a few minutes.")
            if not store.settings.enabled:
                raise SubsonicError(NOT_AUTHORIZED, "Music app access is off. Turn it on in Codetta: Account → Connections.")
            try:
                check_login(params, username(), store.settings.password)
            except SubsonicError as exc:
                if exc.code != MISSING:
                    limiter.failed(key)
                raise
            limiter.succeeded(key)
            result = await run_in_threadpool(handle, method, params)
        except SubsonicError as exc:
            return ok(params, error=exc)
        return result if isinstance(result, Response) else ok(params, result)


CORS = {"Access-Control-Allow-Origin": "*"}  # web players on other sites (sign-in is in the URL, never a cookie)
