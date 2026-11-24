"""Music apps: the library as the Subsonic / OpenSubsonic API presents it.

Players such as Symfonium, Narjo, Arpeggi, Feishin, DSub or Eclipse speak this API (it's
the one Navidrome serves). With it switched on, they can browse, search, stream and show
covers straight from Codetta. It's opt-in, read-only, and signs in with its own app
password, never the account's.

The library is presented the way those apps expect, built from the search index:

* **Songs**: every indexed audio file.
* **Albums**: songs grouped by album artist (or artist) and album tag; files without an
  album tag are grouped by their folder.
* **Artists**: albums grouped by album artist.

IDs are the paths and names themselves (base64url), so they stay the same across restarts
and never need a database of their own.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from codetta.core.index import sfold

API_VERSION = "1.16.1"
EXTENSIONS = [{"name": "apiKeyAuthentication", "versions": [1]}, {"name": "formPost", "versions": [1]},
              {"name": "songLyrics", "versions": [1]}]

# Error codes from the Subsonic API.
MISSING = 10  # required parameter is missing
WRONG_LOGIN = 40  # wrong username or password
TOKEN_NOT_SUPPORTED = 41
NOT_AUTHORIZED = 50
NOT_FOUND = 70
MULTIPLE_AUTH = 43  # OpenSubsonic: more than one way of signing in at once
BAD_API_KEY = 44


class SubsonicError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --- IDs ----------------------------------------------------------------------------------------


def make_id(kind: str, value: str) -> str:
    return kind + "-" + base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def read_id(raw: str) -> tuple[str, str]:
    """("s" | "a" | "r" | "d", value) for an ID this server gave out; SubsonicError otherwise."""
    kind, _, data = (raw or "").partition("-")
    if kind not in ("s", "a", "r", "d") or not data:
        raise SubsonicError(NOT_FOUND, "Not found")
    try:
        return kind, base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise SubsonicError(NOT_FOUND, "Not found") from None


# --- The catalogue ------------------------------------------------------------------------------


def _first(tags: dict, key: str) -> str:
    v = tags.get(key)
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "").strip()


def _int(text: str) -> int | None:
    head = (text or "").split("/")[0].strip()
    return int(head) if head.isdigit() else None


def _year(tags: dict) -> int | None:
    for key in ("originaldate", "date", "year"):
        y = (_first(tags, key) or "")[:4]
        if y.isdigit():
            return int(y)
    return None


@dataclass
class Album:
    id: str
    name: str
    artist: str
    artist_id: str
    songs: list[str] = field(default_factory=list)  # song IDs, in disc/track order
    year: int | None = None
    genre: str = ""
    cover: str | None = None  # a song path whose embedded cover stands for the album
    created: float = 0.0  # newest file's modification time
    duration: int = 0


@dataclass
class Artist:
    id: str
    name: str
    albums: list[str] = field(default_factory=list)


@dataclass
class Song:
    id: str
    path: str
    track: dict
    size: int
    mtime: float
    album_id: str = ""
    artist_id: str = ""


class Catalog:
    def __init__(self, rows: Iterable[tuple[str, int, float, dict]]) -> None:
        self.songs: dict[str, Song] = {}
        self.albums: dict[str, Album] = {}
        self.artists: dict[str, Artist] = {}
        for path, size, mtime, track in rows:
            if track.get("error"):
                continue
            tags = track.get("tags") or {}
            folder = path.rsplit("/", 1)[0] if "/" in path else ""
            album_name = _first(tags, "album")
            artist_name = _first(tags, "albumartist") or _first(tags, "artist") or "Unknown artist"
            artist_id = make_id("r", sfold(artist_name) or artist_name)
            album_key = (f"{sfold(artist_name)}\x1f{sfold(album_name)}" if album_name else f"\x1ffolder\x1f{folder}")
            album_id = make_id("a", album_key)
            song = Song(make_id("s", path), path, track, size or 0, (mtime or 0) / 1e9, album_id, artist_id)  # mtime in ns
            self.songs[song.id] = song
            album = self.albums.get(album_id)
            if album is None:
                album = self.albums[album_id] = Album(album_id, album_name or (folder.rsplit("/", 1)[-1] or "Unknown album"),
                                                      artist_name, artist_id)
                self.artists.setdefault(artist_id, Artist(artist_id, artist_name)).albums.append(album_id)
            album.songs.append(song.id)
            album.duration += int(track.get("duration") or 0)
            album.created = max(album.created, song.mtime)
            album.year = album.year or _year(tags)
            album.genre = album.genre or _first(tags, "genre")
            if album.cover is None and track.get("art"):
                album.cover = path

        def order(sid: str) -> tuple:
            t = self.songs[sid].track.get("tags") or {}
            return (_int(_first(t, "discnumber")) or 1, _int(_first(t, "tracknumber")) or 9999, self.songs[sid].path)

        for album in self.albums.values():
            album.songs.sort(key=order)
        for artist in self.artists.values():
            artist.albums.sort(key=lambda a: (self.albums[a].year or 0, sfold(self.albums[a].name)))

    # --- Shapes the API sends ----------------------------------------------------------------

    def song_out(self, s: Song) -> dict:
        t = s.track.get("tags") or {}
        suffix = s.path.rsplit(".", 1)[-1].lower() if "." in s.path else ""
        album = self.albums.get(s.album_id)
        out = {
            "id": s.id, "parent": s.album_id, "isDir": False, "type": "music", "mediaType": "song",
            "title": _first(t, "title") or s.path.rsplit("/", 1)[-1],
            "album": album.name if album else _first(t, "album"),
            "artist": _first(t, "artist") or (album.artist if album else ""),
            "albumId": s.album_id, "artistId": s.artist_id,
            "suffix": suffix, "contentType": CONTENT_TYPES.get(suffix, "application/octet-stream"),
            "path": s.path, "size": s.size,
            "duration": int(s.track.get("duration") or 0),
            "bitRate": int((s.track.get("bitrate") or 0) / 1000),
            "created": _iso(s.mtime),
        }
        for key, value in (("track", _int(_first(t, "tracknumber"))), ("discNumber", _int(_first(t, "discnumber"))),
                           ("year", _year(t)), ("genre", _first(t, "genre"))):
            if value:
                out[key] = value
        if album and album.cover:
            out["coverArt"] = album.id
        return out

    def album_out(self, a: Album, with_songs: bool = False) -> dict:
        out = {"id": a.id, "name": a.name, "title": a.name, "album": a.name, "artist": a.artist, "artistId": a.artist_id,
               "songCount": len(a.songs), "duration": a.duration, "created": _iso(a.created),
               "isDir": True, "parent": a.artist_id}
        if a.year:
            out["year"] = a.year
        if a.genre:
            out["genre"] = a.genre
        if a.cover:
            out["coverArt"] = a.id
        if with_songs:
            out["song"] = [self.song_out(self.songs[s]) for s in a.songs]
        return out

    def artist_out(self, r: Artist, with_albums: bool = False) -> dict:
        out = {"id": r.id, "name": r.name, "albumCount": len(r.albums)}
        cover = next((self.albums[a].id for a in r.albums if self.albums[a].cover), None)
        if cover:
            out["coverArt"] = cover
        if with_albums:
            out["album"] = [self.album_out(self.albums[a]) for a in r.albums]
        return out

    def indexes(self) -> list[dict]:
        """Artists under their first letter ("#" for the rest), as getArtists sends them."""
        groups: dict[str, list[Artist]] = {}
        for r in self.artists.values():
            letter = (sfold(r.name)[:1] or "#").upper()
            groups.setdefault(letter if letter.isalpha() else "#", []).append(r)
        return [{"name": k, "artist": [self.artist_out(r) for r in sorted(v, key=lambda x: sfold(x.name))]}
                for k, v in sorted(groups.items())]

    def search(self, query: str) -> tuple[list[Artist], list[Album], list[Song]]:
        words = sfold(query.replace('"', " ")).split()

        def hit(*texts: str) -> bool:
            blob = " ".join(sfold(t) for t in texts if t)
            return all(w in blob for w in words)

        artists = [r for r in self.artists.values() if hit(r.name)]
        albums = [a for a in self.albums.values() if hit(a.name, a.artist)]
        songs = [s for s in self.songs.values()
                 if hit(_first(s.track.get("tags") or {}, "title"), _first(s.track.get("tags") or {}, "artist"),
                        self.albums[s.album_id].name, s.path.rsplit("/", 1)[-1])]
        artists.sort(key=lambda r: sfold(r.name))
        albums.sort(key=lambda a: (sfold(a.artist), sfold(a.name)))
        songs.sort(key=lambda s: s.path)
        return artists, albums, songs


CONTENT_TYPES = {
    "mp3": "audio/mpeg", "mp2": "audio/mpeg", "flac": "audio/flac", "m4a": "audio/mp4", "m4b": "audio/mp4",
    "aac": "audio/aac", "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg", "spx": "audio/ogg",
    "wav": "audio/wav", "aiff": "audio/aiff", "aif": "audio/aiff", "wv": "audio/x-wavpack", "ape": "audio/x-ape",
    "mpc": "audio/x-musepack", "tta": "audio/x-tta", "wma": "audio/x-ms-wma", "dsf": "audio/dsf", "dff": "audio/dff",
}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts or 0, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --- Signing in ---------------------------------------------------------------------------------


@dataclass
class SubsonicSettings:
    enabled: bool = False
    password: str = ""


class SubsonicStore:
    """Settings in subsonic.json (owner-only: it holds the app password)."""

    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        self.settings = SubsonicSettings()
        try:
            data = json.loads(file.read_text("utf-8"))
            if isinstance(data, dict):
                self.settings = SubsonicSettings(enabled=bool(data.get("enabled")), password=str(data.get("password") or ""))
        except (OSError, ValueError):
            pass

    def new_password(self) -> str:
        self.settings.password = secrets.token_urlsafe(18)
        return self.settings.password

    def save(self) -> None:
        with self.lock:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".subsonic-", dir=self.file.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"enabled": self.settings.enabled, "password": self.settings.password}, f)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise


def check_login(params: dict, username: str, password: str) -> None:
    """Raise SubsonicError unless the request signs in with the app password.

    Accepts the OpenSubsonic ``apiKey``, the classic token (``t`` = md5(password + ``s``)),
    or the password itself (``p``, plain or ``enc:`` + hex)."""
    if not password:
        raise SubsonicError(WRONG_LOGIN, "Wrong username or password")
    api_key = params.get("apiKey")
    if api_key is not None:
        if params.get("u") or params.get("p") or params.get("t"):
            raise SubsonicError(MULTIPLE_AUTH, "Use either an API key or a username and password, not both")
        if not hmac.compare_digest(api_key.encode(), password.encode()):
            raise SubsonicError(BAD_API_KEY, "Invalid API key")
        return
    user = params.get("u")
    if not user:
        raise SubsonicError(MISSING, "Required parameter is missing: u")
    if username and user.casefold() != username.casefold():
        raise SubsonicError(WRONG_LOGIN, "Wrong username or password")
    token, salt, given = params.get("t"), params.get("s"), params.get("p")
    if token is not None and salt is not None:
        expected = hashlib.md5((password + salt).encode("utf-8")).hexdigest()  # noqa: S324 (the protocol's own scheme)
        if hmac.compare_digest(token.lower().encode(), expected.encode()):
            return
        raise SubsonicError(WRONG_LOGIN, "Wrong username or password")
    if given is not None:
        if given.startswith("enc:"):
            try:
                given = bytes.fromhex(given[4:]).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                raise SubsonicError(WRONG_LOGIN, "Wrong username or password") from None
        if hmac.compare_digest(given.encode(), password.encode()):
            return
        raise SubsonicError(WRONG_LOGIN, "Wrong username or password")
    raise SubsonicError(MISSING, "Required parameter is missing: t and s, or p")


# --- Answers ------------------------------------------------------------------------------------


def envelope(version: str, payload: dict | None = None, error: SubsonicError | None = None) -> dict:
    out = {"status": "failed" if error else "ok", "version": API_VERSION, "type": "codetta",
           "serverVersion": version, "openSubsonic": True}
    if error:
        out["error"] = {"code": error.code, "message": error.message}
    out.update(payload or {})
    return out


def to_json(body: dict) -> str:
    return json.dumps({"subsonic-response": body}, ensure_ascii=False, separators=(",", ":"))


def to_xml(body: dict) -> str:
    """Subsonic's XML: plain values become attributes, objects child elements, lists repeated ones."""
    def element(name: str, obj: dict) -> str:
        attrs, kids, text = [], [], None
        for k, v in obj.items():
            if k == "value" and not isinstance(v, (dict, list)):
                text = str(v)
            elif isinstance(v, dict):
                kids.append(element(k, v))
            elif isinstance(v, list):
                kids.extend(element(k, x) if isinstance(x, dict) else f"<{k}>{escape(str(x))}</{k}>" for x in v)
            elif v is not None:
                attrs.append(f"{k}={quoteattr(str(v).lower() if isinstance(v, bool) else str(v))}")
        head = f"<{name}{''.join(' ' + a for a in attrs)}"
        inner = "".join(kids) + (escape(text) if text is not None else "")
        return f"{head}>{inner}</{name}>" if inner else f"{head}/>"

    xml = element("subsonic-response", body)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml.replace(
        "<subsonic-response", '<subsonic-response xmlns="http://subsonic.org/restapi"', 1)


class CatalogCache:
    """The catalogue, rebuilt when the index changes (checked at most every few seconds)."""

    def __init__(self, rows, signature, every: float = 5.0) -> None:
        self.rows, self.signature, self.every = rows, signature, every
        self._catalog: Catalog | None = None
        self._sig = None
        self._checked = 0.0
        self._lock = threading.Lock()

    def get(self) -> Catalog:
        with self._lock:
            now = time.monotonic()
            if self._catalog is None or now - self._checked > self.every:
                self._checked = now
                sig = self.signature()
                if self._catalog is None or sig != self._sig:
                    self._catalog, self._sig = Catalog(self.rows()), sig
            return self._catalog
