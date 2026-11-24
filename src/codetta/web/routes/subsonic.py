"""Music apps: the Subsonic / OpenSubsonic API at /rest/, and its settings.

/rest/ is outside Codetta's own sign-in (apps can't hold a session cookie); every request
signs in with the app password instead (see core/subsonic.py), failed attempts are
rate-limited like the sign-in page, and it all answers "off" until switched on.
"""

from __future__ import annotations

import hashlib
import hmac
import random
import re
import time
from urllib.parse import urlencode

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from codetta.core.artists import top_folders
from codetta.core.artwork import sniff_image_type
from codetta.core.auth import LoginRateLimiter
from codetta.core.covers import CoverCache
from codetta.core.index import sfold
from codetta.core.library import LibraryPathError, is_special
from codetta.core.loudness import find_ffmpeg
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
    artist_id,
    check_login,
    envelope,
    make_id,
    read_id,
    to_json,
    to_xml,
)
from codetta.core.transcode import Transcoder
from codetta.web.common import VERSION, SubsonicSettingsIn

IGNORED_ARTICLES = "The El La Los Las Le Les"
MAX_LIST = 500
LRC = re.compile(r"^\s*((?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\])+)(.*)$")
STAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
CORS = {"Access-Control-Allow-Origin": "*"}  # web players on other sites (sign-in is in the URL, never a cookie)
PREFLIGHT = {**CORS, "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
             "Access-Control-Allow-Headers": "Content-Type, Range", "Access-Control-Max-Age": "86400"}


def register(app, shared) -> None:
    settings = shared.settings
    library = shared.library
    lib_index = shared.lib_index
    engine = shared.engine
    listening = shared.listening
    scrobbler = shared.scrobbler
    store = SubsonicStore(settings.config_dir / "subsonic.json")
    limiter = LoginRateLimiter()
    covers = CoverCache(settings.config_dir / "cover-cache")
    transcoder = Transcoder(find_ffmpeg(settings.ffmpeg))
    last_seen: dict[str, float] = {}

    def relink(cat) -> None:
        if lib_index.status().scanning:
            return  # songs not read yet would look "gone": wait for the next build

        def gone(path: str) -> bool:
            if is_special(path):
                return False  # the inbox and Recently deleted aren't the library: leave them be
            try:
                return not library.resolve(path).exists()
            except (LibraryPathError, ValueError):
                return False

        listening.relink({s.path for s in cat.songs.values()}, cat.by_fp(), gone)

    cache = CatalogCache(lib_index.catalog_rows, lib_index.fingerprint, on_build=relink)

    def username() -> str:
        account = shared.accounts.get() if settings.auth else None
        return account.username if account else ""

    # --- Settings (Codetta's own page, signed in as usual) --------------------------------------

    def settings_out() -> dict:
        s = store.settings
        return {"enabled": s.enabled, "password": s.password if s.enabled else "", "username": username(), "path": "/rest",
                "transcode": s.transcode, "format": s.format, "formats": transcoder.formats(),
                "clients": [{"name": n, "last_seen": t} for n, t in listening.clients()]}

    @app.get("/api/subsonic")
    def get_subsonic() -> dict:
        """Music app access: on or off, how to connect (the app password, while it's on), conversion."""
        return settings_out()

    @app.put("/api/subsonic")
    def put_subsonic(body: SubsonicSettingsIn) -> dict:
        s = store.settings
        s.enabled = body.enabled
        if body.transcode is not None:
            s.transcode = body.transcode
        if body.format is not None:
            s.format = body.format
        if body.enabled and not s.password:
            store.new_password()
        store.save()
        return settings_out()

    @app.post("/api/subsonic/password")
    def new_subsonic_password() -> dict:
        """A new app password: every app signed in with the old one has to sign in again."""
        store.new_password()
        store.save()
        return settings_out()

    # --- Answers --------------------------------------------------------------------------------

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
            return max(0, min(top, int(float(params.get(key, default)))))
        except (ValueError, TypeError):
            return default

    def flag(params: dict, key: str, default: bool) -> bool:
        value = str(params.get(key, "")).lower()
        return default if value == "" else value in ("true", "1", "yes")

    def song_of(cat, raw: str):
        kind, _ = read_id(raw)
        if kind != "s" or raw not in cat.songs:
            raise SubsonicError(NOT_FOUND, "Song not found")
        return cat.songs[raw]

    def songs_of(cat, raw: str) -> list:
        """The songs behind any ID: a song, an album, an artist or a folder."""
        kind, value = read_id(raw)
        if kind == "s" and raw in cat.songs:
            return [cat.songs[raw]]
        if kind == "a" and raw in cat.albums:
            return [cat.songs[s] for s in cat.albums[raw].songs]
        if kind == "r" and raw in cat.artists:
            r = cat.artists[raw]
            return [cat.songs[s] for a in (r.albums or r.appears) for s in cat.albums[a].songs]
        if kind == "d" and not is_special(value):
            prefix = value.rstrip("/") + "/" if value else ""
            return [s for s in cat.songs.values() if s.path.startswith(prefix)]
        raise SubsonicError(NOT_FOUND, "Not found")

    def image_urls(request: Request, params: dict, raw: str) -> dict:
        """Picture links an app can open as they are. They carry a signature that only opens that one
        picture at that size (never the app's password or token), and follow the address the app used,
        HTTPS behind a reverse proxy included."""
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        base = str(request.base_url).rstrip("/")
        if proto in ("http", "https"):
            base = proto + base[base.index(":"):]
        out = {}
        for name, size in (("smallImageUrl", 150), ("mediumImageUrl", 300), ("largeImageUrl", 600)):
            out[name] = f"{base}/rest/getCoverArt?" + urlencode({"id": raw, "size": size, "sig": image_sig(raw, str(size))})
        return out

    def image_sig(raw: str, size: str) -> str:
        key = store.settings.password.encode()
        return hmac.new(key, f"cover\x1f{raw}\x1f{size}".encode(), hashlib.sha256).hexdigest()[:32]

    def artist_out(cat, r, request, params, marks, with_albums=False) -> dict:
        out = cat.artist_out(r, with_albums=with_albums, marks=marks)
        if "artistImageUrl" in out:
            out["artistImageUrl"] = image_urls(request, params, r.id)["largeImageUrl"]
        return out

    def directory(cat, raw: str, marks) -> dict:
        kind, value = read_id(raw)
        if kind == "a" and raw in cat.albums:
            a = cat.albums[raw]
            return {"id": a.id, "name": a.name, "parent": a.artist_ids[0] if a.artist_ids else "",
                    "child": [cat.song_out(cat.songs[s], marks) for s in a.songs]}
        if kind == "r" and raw in cat.artists:
            r = cat.artists[raw]
            return {"id": r.id, "name": r.name, "child": [cat.album_out(cat.albums[a], marks=marks) for a in (r.albums or r.appears)]}
        if kind == "d":
            if is_special(value):
                raise SubsonicError(NOT_FOUND, "Folder not found")
            try:
                listing = library.list_folder(value)
            except (LibraryPathError, OSError, ValueError):
                raise SubsonicError(NOT_FOUND, "Folder not found") from None
            kids = [{"id": make_id("d", f), "parent": raw, "isDir": True, "title": f.rsplit("/", 1)[-1]}
                    for f in listing.folders if not is_special(f)]
            for path in listing.files:
                song = cat.songs.get(make_id("s", path))
                if song is not None:
                    kids.append({**cat.song_out(song, marks), "parent": raw})
            out = {"id": raw, "name": value.rsplit("/", 1)[-1] or "Music", "child": kids}
            if value:  # the music folder itself has no parent
                out["parent"] = make_id("d", value.rsplit("/", 1)[0] if "/" in value else "")
            return out
        raise SubsonicError(NOT_FOUND, "Folder not found")

    def albums_list(cat, params: dict, marks) -> list:
        kind = params.get("type", "alphabeticalByName")
        albums = list(cat.albums.values())
        amarks = marks.get("a", {})
        if kind == "random":
            random.shuffle(albums)
        elif kind == "newest":
            albums.sort(key=lambda a: -a.created)
        elif kind == "frequent":
            albums = sorted((a for a in albums if amarks.get(a.id) and amarks[a.id].plays), key=lambda a: -amarks[a.id].plays)
        elif kind == "recent":
            albums = sorted((a for a in albums if amarks.get(a.id) and amarks[a.id].last_played),
                            key=lambda a: -amarks[a.id].last_played)
        elif kind == "starred":
            albums = sorted((a for a in albums if amarks.get(a.id) and amarks[a.id].starred), key=lambda a: -amarks[a.id].starred)
        elif kind == "highest":
            albums = sorted((a for a in albums if amarks.get(a.id) and amarks[a.id].rating), key=lambda a: -amarks[a.id].rating)
        elif kind == "alphabeticalByArtist":
            albums.sort(key=lambda a: (sfold(a.artist), a.year or 0, sfold(a.name)))
        elif kind == "byYear":
            lo, hi = number(params, "fromYear", 0, 9999), number(params, "toYear", 9999, 9999)
            albums = [a for a in albums if a.year and min(lo, hi) <= a.year <= max(lo, hi)]
            albums.sort(key=lambda a: a.year or 0, reverse=lo > hi)
        elif kind == "byGenre":
            want = sfold(need(params, "genre"))
            albums = sorted((a for a in albums if any(sfold(g) == want for g in a.genres)), key=lambda a: sfold(a.name))
        else:
            albums.sort(key=lambda a: sfold(a.name))
        off, size = number(params, "offset", 0, 10**9), number(params, "size", 10)
        return [cat.album_out(a, marks=marks) for a in albums[off:off + size]]

    def song_genres(s) -> list[str]:
        return [g["name"] for g in s.base.get("genres", [])]

    def random_songs(cat, params: dict, marks) -> list:
        genre = sfold(params.get("genre", ""))
        years = "fromYear" in params or "toYear" in params
        lo, hi = number(params, "fromYear", 0, 9999), number(params, "toYear", 9999, 9999)
        pool = [s for s in cat.songs.values()
                if (not genre or any(sfold(g) == genre for g in song_genres(s)))
                and (not years or (s.base.get("year") and lo <= s.base["year"] <= hi))]
        size = number(params, "size", 10)
        return [cat.song_out(s, marks) for s in random.sample(pool, min(size, len(pool)))]

    def genres(cat) -> list:
        counts: dict[str, list] = {}
        for s in cat.songs.values():
            for g in song_genres(s):
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
        try:  # a .lrc file next to the song, as Navidrome reads
            lrc = library.resolve(path).with_suffix(".lrc")
            if lrc.is_file() and lrc.stat().st_size < 500_000:
                return lrc.read_text("utf-8", errors="replace")
        except (OSError, LibraryPathError, ValueError):
            pass
        return ""

    def structured(text: str, song) -> dict | None:
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
        return {"lang": "xxx", "synced": synced, "displayArtist": song.base.get("displayArtist", ""),
                "displayTitle": song.base.get("title", ""), "line": lines}

    def image(data: bytes, key: str, size: int | None) -> Response:
        out, resized = covers.get(data, key, size)
        mime = "image/jpeg" if resized else sniff_image_type(out)
        return Response(out, media_type=mime, headers={**CORS, "Cache-Control": "private, max-age=86400"})

    def cover(cat, raw: str, size: int | None) -> Response:
        kind, value = read_id(raw) if raw else ("", "")
        if kind == "r" and raw in cat.artists:
            name = cat.artists[raw].name
            folder = top_folders(settings.music_dir).get(sfold(name))
            art = getattr(shared, "artist_art", None)
            try:
                found = art.picture(name, folder) if art else None
            except Exception:  # noqa: BLE001 - fall back to an album cover
                found = None
            if found:
                return image(found[0], f"artist\x1f{sfold(name)}\x1f{len(found[0])}", size)
        if kind == "pl":
            pl = listening.playlist(int(value)) if value.isdigit() else None
            raw = make_id("s", pl.paths[0]) if pl and pl.paths else raw
        try:
            songs = songs_of(cat, raw)
        except SubsonicError:
            songs = []
        paths = [s.path for s in songs if s.track.get("art")]
        if kind == "a" and raw in cat.albums and cat.albums[raw].cover:
            paths.insert(0, cat.albums[raw].cover)
        for path in paths[:3]:
            try:
                target = library.resolve(path)
                art = engine.read_artwork(target)
                stamp = target.stat().st_mtime_ns
            except Exception:  # noqa: BLE001 - try the next file
                continue
            if art is not None and sniff_image_type(art.data):
                return image(art.data, f"{path}\x1f{stamp}", size)
        raise SubsonicError(NOT_FOUND, "No cover art")

    def similar(cat, raw: str, count: int, marks) -> list:
        seeds = [s.path for s in songs_of(cat, raw)][:3]
        autoplay = getattr(shared, "autoplay", None)
        if not seeds or autoplay is None:
            return []
        found = autoplay.next_tracks(seeds, set(seeds), min(count, 30))
        return [cat.song_out(cat.songs[make_id("s", p)], marks) for p in found["paths"] if make_id("s", p) in cat.songs]

    def similar_artists(cat, r, count: int, marks, request, params) -> list:
        autoplay = getattr(shared, "autoplay", None)
        seeds = [cat.songs[s].path for a in (r.albums or r.appears)[:2] for s in cat.albums[a].songs[:2]]
        if not seeds or autoplay is None:
            return []
        found = autoplay.next_tracks(seeds, set(seeds), 30)
        ids: list[str] = []
        for p in found["paths"]:
            song = cat.songs.get(make_id("s", p))
            if song and song.artist_id != r.id and song.artist_id not in ids and song.artist_id in cat.artists:
                ids.append(song.artist_id)
        return [artist_out(cat, cat.artists[i], request, params, marks) for i in ids[:count]]

    def playlist_out(cat, pl, marks, with_songs=False) -> dict:
        songs = [cat.songs[make_id("s", p)] for p in pl.paths if make_id("s", p) in cat.songs]
        out = {"id": str(pl.id), "name": pl.name, "comment": pl.comment, "owner": username() or "codetta",
               "public": pl.public, "songCount": len(songs), "duration": sum(int(s.track.get("duration") or 0) for s in songs),
               "created": _iso(pl.created), "changed": _iso(pl.changed)}
        if songs and cat.albums[songs[0].album_id].cover:
            out["coverArt"] = songs[0].album_id
        if with_songs:
            out["entry"] = [cat.song_out(s, marks) for s in songs]
        return out

    def queue_out(cat, marks, by_index: bool) -> dict:
        q = listening.queue()
        if q is None:
            return {}
        paths, current, position, changed, client = q
        songs = [cat.songs[make_id("s", p)] for p in paths if make_id("s", p) in cat.songs]
        out = {"entry": [cat.song_out(s, marks) for s in songs], "position": position, "username": username() or "codetta",
               "changed": _iso(changed), "changedBy": client or "codetta"}
        if current is not None and 0 <= current < len(paths) and make_id("s", paths[current]) in cat.songs:
            if by_index:
                out["currentIndex"] = [s.path for s in songs].index(paths[current])
            else:
                out["current"] = make_id("s", paths[current])
        return out

    def scrobble(cat, params: dict, multi: dict) -> None:
        submission = flag(params, "submission", True)
        times = multi.get("time", [])
        client = params.get("c", "")
        for i, raw in enumerate(multi.get("id", [])):
            try:
                song = song_of(cat, raw)
            except SubsonicError:
                continue
            tags = song.track.get("tags") or {}
            meta = shared.song_meta(tags, song.track.get("duration"))
            if submission:
                try:
                    when = int(times[i]) / 1000 if i < len(times) else time.time()
                except ValueError:
                    when = time.time()
                album = cat.albums[song.album_id]
                listening.played(song.path, when, song.fp, also=[("a", song.album_id), *[("r", a) for a in album.artist_ids]])
                scrobbler.listened(meta, when, player=client)
            else:
                listening.now_playing[client or "app"] = (song.path, time.time())
                scrobbler.now_playing(meta, player=client)

    def star(cat, multi: dict, on: bool) -> None:
        songs, albums, artists = [], [], []
        for raw in multi.get("id", []):
            kind = raw.partition("-")[0]
            (songs if kind == "s" else albums if kind == "a" else artists if kind == "r" else []).append(raw)
        albums += multi.get("albumId", [])
        artists += multi.get("artistId", [])
        found = [cat.songs[s] for s in songs if s in cat.songs]
        if found:
            listening.star("s", [s.path for s in found], on, {s.path: s.fp for s in found})
        if albums:
            listening.star("a", [a for a in albums if a in cat.albums], on)
        if artists:
            listening.star("r", [a for a in artists if a in cat.artists], on)

    def handle(method: str, params: dict, multi: dict, request: Request) -> Response | dict:
        cat = cache.get()
        marks = listening.marks()
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
            modified = int(cat.built * 1000)
            out = {"lastModified": modified, "ignoredArticles": IGNORED_ARTICLES}
            if number(params, "ifModifiedSince", 0, 2**63) < modified:
                groups: dict[str, list] = {}
                for f in library.list_folder("").folders:
                    if is_special(f):
                        continue
                    letter = (sfold(f)[:1] or "#").upper()
                    groups.setdefault(letter if letter.isalpha() else "#", []).append({"id": make_id("d", f), "name": f})
                out["index"] = [{"name": k, "artist": v} for k, v in sorted(groups.items())]
            return {"indexes": out}
        if m == "getMusicDirectory":
            return {"directory": directory(cat, need(params, "id"), marks)}
        if m == "getArtists":
            index = cat.indexes(marks)
            for group in index:
                for a in group["artist"]:
                    if "artistImageUrl" in a:
                        a["artistImageUrl"] = image_urls(request, params, a["id"])["largeImageUrl"]
            return {"artists": {"ignoredArticles": IGNORED_ARTICLES, "lastModified": int(cat.built * 1000), "index": index}}
        if m == "getArtist":
            raw = need(params, "id")
            if raw not in cat.artists:
                raise SubsonicError(NOT_FOUND, "Artist not found")
            return {"artist": artist_out(cat, cat.artists[raw], request, params, marks, with_albums=True)}
        if m == "getAlbum":
            raw = need(params, "id")
            if raw not in cat.albums:
                raise SubsonicError(NOT_FOUND, "Album not found")
            return {"album": cat.album_out(cat.albums[raw], with_songs=True, marks=marks)}
        if m == "getSong":
            return {"song": cat.song_out(song_of(cat, need(params, "id")), marks)}
        if m in ("getAlbumList2", "getAlbumList"):
            return {"albumList2" if m.endswith("2") else "albumList": {"album": albums_list(cat, params, marks)}}
        if m == "getRandomSongs":
            return {"randomSongs": {"song": random_songs(cat, params, marks)}}
        if m == "getSongsByGenre":
            want = sfold(need(params, "genre"))
            songs = [s for s in cat.songs.values() if any(sfold(g) == want for g in song_genres(s))]
            off = number(params, "offset", 0, 10**9)
            return {"songsByGenre": {"song": [cat.song_out(s, marks) for s in songs[off:off + number(params, "count", 10)]]}}
        if m == "getGenres":
            return {"genres": {"genre": genres(cat)}}
        if m in ("search3", "search2"):
            artists, albums, songs = cat.search(params.get("query", ""))

            def page(items, key, default):
                off = number(params, key + "Offset", 0, 10**9)
                return items[off:off + number(params, key + "Count", default, 100_000)]
            return {"searchResult3" if m == "search3" else "searchResult2": {
                "artist": [artist_out(cat, r, request, params, marks) for r in page(artists, "artist", 20)],
                "album": [cat.album_out(a, marks=marks) for a in page(albums, "album", 20)],
                "song": [cat.song_out(s, marks) for s in page(songs, "song", 20)]}}
        if m in ("getStarred2", "getStarred"):
            def starred(kind, items, out):
                got = [(marks.get(kind, {}).get(k), v) for k, v in items]
                return [out(v) for mk, v in sorted((x for x in got if x[0] and x[0].starred), key=lambda x: -x[0].starred)]
            return {"starred2" if m.endswith("2") else "starred": {
                "artist": starred("r", ((r.id, r) for r in cat.artists.values()), lambda r: artist_out(cat, r, request, params, marks)),
                "album": starred("a", ((a.id, a) for a in cat.albums.values()), lambda a: cat.album_out(a, marks=marks)),
                "song": starred("s", ((s.path, s) for s in cat.songs.values()), lambda s: cat.song_out(s, marks))}}
        if m in ("star", "unstar"):
            star(cat, multi, m == "star")
            return {}
        if m == "setRating":
            raw = need(params, "id")
            rating = number(params, "rating", 0, 5)
            kind = raw.partition("-")[0]
            if kind == "s":
                song = song_of(cat, raw)
                listening.rate("s", song.path, rating, song.fp)
            elif kind in ("a", "r") and (raw in cat.albums or raw in cat.artists):
                listening.rate(kind, raw, rating)
            else:
                raise SubsonicError(NOT_FOUND, "Not found")
            return {}
        if m == "scrobble":
            need(params, "id")
            scrobble(cat, params, multi)
            return {}
        if m == "getNowPlaying":
            now = time.time()
            entries = []
            for client, (path, since) in list(listening.now_playing.items()):
                song = cat.songs.get(make_id("s", path))
                if song is None or now - since > 20 * 60:
                    continue
                entries.append({**cat.song_out(song, marks), "username": username() or "codetta",
                                "minutesAgo": int((now - since) / 60), "playerId": 1, "playerName": client})
            return {"nowPlaying": {"entry": entries}}
        if m == "getPlaylists":
            return {"playlists": {"playlist": [playlist_out(cat, pl, marks) for pl in listening.playlists()]}}
        if m == "getPlaylist":
            raw = need(params, "id")
            pl = listening.playlist(int(raw)) if raw.isdigit() else None
            if pl is None:
                raise SubsonicError(NOT_FOUND, "Playlist not found")
            return {"playlist": playlist_out(cat, pl, marks, with_songs=True)}
        if m == "createPlaylist":
            paths = [song_of(cat, s).path for s in multi.get("songId", []) if s in cat.songs]
            pid_raw = params.get("playlistId", "")
            if pid_raw:
                if not pid_raw.isdigit() or not listening.replace_playlist(int(pid_raw), paths, params.get("name")):
                    raise SubsonicError(NOT_FOUND, "Playlist not found")
                pid = int(pid_raw)
            else:
                pid = listening.create_playlist(need(params, "name"), paths)
            return {"playlist": playlist_out(cat, listening.playlist(pid), marks, with_songs=True)}
        if m == "updatePlaylist":
            raw = need(params, "playlistId")
            add = [song_of(cat, s).path for s in multi.get("songIdToAdd", []) if s in cat.songs]
            pl_now = listening.playlist(int(raw)) if raw.isdigit() else None
            # The app's indexes count the songs it was shown, which leave out entries not in the
            # library right now: map them back to the stored positions.
            shown = [i for i, p in enumerate(pl_now.paths if pl_now else []) if make_id("s", p) in cat.songs]
            remove = [shown[int(i)] for i in multi.get("songIndexToRemove", []) if i.isdigit() and int(i) < len(shown)]
            public = params.get("public")
            if not raw.isdigit() or not listening.update_playlist(
                    int(raw), name=params.get("name"), comment=params.get("comment"),
                    public=None if public is None else public.lower() == "true", add=add, remove=remove):
                raise SubsonicError(NOT_FOUND, "Playlist not found")
            return {}
        if m == "deletePlaylist":
            raw = need(params, "id")
            if not raw.isdigit() or not listening.delete_playlist(int(raw)):
                raise SubsonicError(NOT_FOUND, "Playlist not found")
            return {}
        if m in ("getPlayQueue", "getPlayQueueByIndex"):
            key = "playQueue" if m == "getPlayQueue" else "playQueueByIndex"
            return {key: queue_out(cat, marks, by_index=m.endswith("ByIndex"))}
        if m in ("savePlayQueue", "savePlayQueueByIndex"):
            songs = [song_of(cat, s) for s in multi.get("id", []) if s in cat.songs]
            paths = [s.path for s in songs]
            if m == "savePlayQueue":
                cur = params.get("current", "")
                current = paths.index(cat.songs[cur].path) if cur in cat.songs and cat.songs[cur].path in paths else None
            else:
                idx = number(params, "currentIndex", -1, 10**6) if params.get("currentIndex") else None
                current = idx if idx is not None and 0 <= idx < len(paths) else None
            listening.save_queue(paths, current, number(params, "position", 0, 2**62), params.get("c", ""))
            return {}
        if m == "getBookmarks":
            out = []
            for path, position, comment, created, changed in listening.bookmarks():
                song = cat.songs.get(make_id("s", path))
                if song is not None:
                    out.append({"position": position, "username": username() or "codetta", "comment": comment,
                                "created": _iso(created), "changed": _iso(changed), "entry": cat.song_out(song, marks)})
            return {"bookmarks": {"bookmark": out}}
        if m == "createBookmark":
            song = song_of(cat, need(params, "id"))
            listening.set_bookmark(song.path, number(params, "position", 0, 2**62), params.get("comment", ""))
            return {}
        if m == "deleteBookmark":
            listening.delete_bookmark(song_of(cat, need(params, "id")).path)
            return {}
        if m in ("getInternetRadioStations", "getPodcasts", "getNewestPodcasts", "getShares"):
            key = {"getInternetRadioStations": "internetRadioStations", "getPodcasts": "podcasts",
                   "getNewestPodcasts": "newestPodcasts", "getShares": "shares"}[m]
            return {key: {}}
        if m == "getUser":
            return {"user": {"username": params.get("u") or username() or "codetta", "scrobblingEnabled": scrobbler.ready,
                             "adminRole": False, "settingsRole": False, "downloadRole": True, "uploadRole": False,
                             "playlistRole": True, "coverArtRole": True, "commentRole": False, "podcastRole": False,
                             "streamRole": True, "jukeboxRole": False, "shareRole": False, "videoConversionRole": False,
                             "folder": [1]}}
        if m in ("getScanStatus", "startScan"):
            if m == "startScan":
                lib_index.request_rescan(force=True)
            status = lib_index.status()
            return {"scanStatus": {"scanning": bool(status.scanning), "count": status.files}}
        if m in ("getArtistInfo2", "getArtistInfo"):
            raw = need(params, "id")
            kind = raw.partition("-")[0]
            if kind in ("s", "a") and (raw in cat.songs or raw in cat.albums):
                raw = cat.songs[raw].artist_id if kind == "s" else (cat.albums[raw].artist_ids or [""])[0]
            if raw not in cat.artists:
                raise SubsonicError(NOT_FOUND, "Artist not found")
            r = cat.artists[raw]
            info = {"biography": "", **image_urls(request, params, r.id)}
            if r.mbid:
                info["musicBrainzId"] = r.mbid
            info["similarArtist"] = similar_artists(cat, r, number(params, "count", 20, 50), marks, request, params)
            return {"artistInfo2" if m.endswith("2") else "artistInfo": info}
        if m in ("getAlbumInfo2", "getAlbumInfo"):
            raw = need(params, "id")
            if raw in cat.songs:
                raw = cat.songs[raw].album_id
            if raw not in cat.albums:
                raise SubsonicError(NOT_FOUND, "Album not found")
            a = cat.albums[raw]
            info = {"notes": "", **image_urls(request, params, a.id)}
            mbid = a.base.get("musicBrainzId")
            if mbid:
                info["musicBrainzId"] = mbid
            return {"albumInfo": info}
        if m in ("getSimilarSongs2", "getSimilarSongs"):
            songs = similar(cat, need(params, "id"), number(params, "count", 50), marks)
            return {"similarSongs2" if m.endswith("2") else "similarSongs": {"song": songs}}
        if m == "getTopSongs":
            want = sfold(need(params, "artist"))
            smarks = marks.get("s", {})
            songs = [s for s in cat.songs.values() if any(sfold(a["name"]) == want for a in s.base.get("artists", []))]
            songs.sort(key=lambda s: (-(smarks[s.path].plays if s.path in smarks else 0), s.base.get("year") or 0, s.path))
            return {"topSongs": {"song": [cat.song_out(s, marks) for s in songs[:number(params, "count", 50)]]}}
        if m == "getLyrics":
            title, artist = sfold(params.get("title", "")), sfold(params.get("artist", ""))
            for s in cat.songs.values():
                o = s.base
                if title and sfold(o["title"]) == title and (not artist or sfold(o["artist"]) == artist):
                    return {"lyrics": {"artist": o["artist"], "title": o["title"], "value": lyrics_of(s.path)}}
            return {"lyrics": {}}
        if m == "getLyricsBySongId":
            song = song_of(cat, need(params, "id"))
            found = structured(lyrics_of(song.path), song)
            return {"lyricsList": {"structuredLyrics": [found] if found else []}}
        if m in ("stream", "download"):
            song = song_of(cat, need(params, "id"))
            target = library.resolve(song.path)
            if not target.is_file():
                raise SubsonicError(NOT_FOUND, "Song not found")
            suffix = target.suffix.lower().lstrip(".")
            if m == "stream" and store.settings.transcode:
                plan = transcoder.plan(params.get("format"), number(params, "maxBitRate", 0, 10_000), suffix,
                                       song.base.get("bitRate", 0), store.settings.format)
                if plan is not None:
                    offset = number(params, "timeOffset", 0, 10**6)
                    chunks = transcoder.stream(target, plan, offset)
                    if chunks is not None:
                        # No Content-Length, even when asked to estimate one: the real size isn't known
                        # until ffmpeg is done, and a guess too small cuts the end of the song off.
                        return StreamingResponse(chunks, media_type=plan.content_type, headers=dict(CORS),
                                                 background=BackgroundTask(chunks.close))
            return FileResponse(target, media_type=CONTENT_TYPES.get(suffix, "application/octet-stream"),
                                content_disposition_type="attachment" if m == "download" else "inline",
                                filename=target.name if m == "download" else None, headers=CORS)
        if m == "getCoverArt":
            size = number(params, "size", 0, 10_000) or None
            return cover(cat, need(params, "id"), size)
        if m == "getAvatar":
            raise SubsonicError(NOT_FOUND, "No avatar")
        raise SubsonicError(NOT_FOUND, f"Unknown method: {m}")

    async def gather(request: Request) -> tuple[dict, dict]:
        multi: dict[str, list[str]] = {}
        for k, v in request.query_params.multi_items():
            multi.setdefault(k, []).append(v)
        if request.method == "POST" and "form" in request.headers.get("content-type", ""):
            form = await request.form()
            for k, v in form.multi_items():
                if isinstance(v, str):
                    multi.setdefault(k, []).append(v)
        return {k: vals[0] for k, vals in multi.items()}, multi

    @app.options("/rest/{method}", include_in_schema=False)
    async def rest_preflight(method: str) -> Response:
        return Response(status_code=204, headers=PREFLIGHT)

    @app.api_route("/rest/{method}", methods=["GET", "POST"], include_in_schema=False)
    async def rest(method: str, request: Request):
        params, multi = await gather(request)
        method = method.removesuffix(".view")
        key = request.client.host if request.client else "unknown"
        try:
            if limiter.retry_after(key):
                raise SubsonicError(WRONG_LOGIN, "Too many failed sign-ins. Try again in a few minutes.")
            if not store.settings.enabled:
                raise SubsonicError(NOT_AUTHORIZED, "Music app access is off. Turn it on in Codetta: Settings → Connections.")
            signed = (method == "getCoverArt" and params.get("sig") and store.settings.password
                      and hmac.compare_digest(params["sig"], image_sig(params.get("id", ""), params.get("size", ""))))
            try:
                if not signed:  # a signed picture link opens that picture only, without signing in
                    check_login(params, username(), store.settings.password)
            except SubsonicError as exc:
                if exc.code != MISSING:
                    limiter.failed(key)
                raise
            limiter.succeeded(key)
            client = params.get("c", "")
            if client and time.time() - last_seen.get(client, 0) > 60:
                last_seen[client] = time.time()
                listening.seen(client)
            result = await run_in_threadpool(handle, method, params, multi, request)
        except SubsonicError as exc:
            return ok(params, error=exc)
        return result if isinstance(result, Response) else ok(params, result)


def _iso(ts: float) -> str:
    from codetta.core.subsonic import _iso as iso
    return iso(ts)
