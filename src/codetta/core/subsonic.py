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
import logging
import os
import re
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

log = logging.getLogger("codetta")

API_VERSION = "1.16.1"
EXTENSIONS = [{"name": "apiKeyAuthentication", "versions": [1]}, {"name": "formPost", "versions": [1]},
              {"name": "songLyrics", "versions": [1]}, {"name": "transcodeOffset", "versions": [1]},
              {"name": "indexBasedQueue", "versions": [1]}]

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
    """("s" | "a" | "r" | "d", value) for an ID this server gave out; SubsonicError otherwise.

    "d-" alone is the music folder itself (its folder path is empty)."""
    kind, sep, data = (raw or "").partition("-")
    if kind == "d" and sep and not data:
        return "d", ""
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


def _all(tags: dict, key: str) -> list[str]:
    v = tags.get(key)
    vals = v if isinstance(v, list) else ([v] if v else [])
    return [str(x).strip() for x in vals if str(x or "").strip()]


def _split(values: list[str]) -> list[str]:
    """Genres and similar: separate values, or one value with ";", "," or "|" between them."""
    out, seen = [], set()
    for v in values:
        for part in re.split(r"[;,|]", v):
            part = part.strip()
            if part and part.casefold() not in seen:
                seen.add(part.casefold())
                out.append(part)
    return out


def _int(text: str) -> int | None:
    head = (text or "").split("/")[0].strip()
    return int(head) if head.isascii() and head.isdecimal() else None  # "①" or "²" are digits, not numbers


def _float(text: str) -> float | None:
    m = re.match(r"\s*([+-]?\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else None


def _year(tags: dict) -> int | None:
    for key in ("originaldate", "date", "year"):
        y = (_first(tags, key) or "")[:4]
        if y.isascii() and y.isdecimal():
            return int(y)
    return None


def _date(text: str) -> dict | None:
    """"2016-08-20" -> {"year": 2016, "month": 8, "day": 20} (OpenSubsonic ItemDate)."""
    parts = re.findall(r"[0-9]+", text or "")
    if not parts or len(parts[0]) != 4:
        return None
    out = {"year": int(parts[0])}
    if len(parts) > 1 and 1 <= int(parts[1]) <= 12:
        out["month"] = int(parts[1])
        if len(parts) > 2 and 1 <= int(parts[2]) <= 31:
            out["day"] = int(parts[2])
    return out


def _mbid(tags: dict, key: str, i: int = 0) -> str:
    vals = _all(tags, key)
    v = vals[i] if i < len(vals) else ""
    return v.lower() if re.fullmatch(r"[0-9a-fA-F-]{36}", v) else ""


def artist_id(name: str) -> str:
    return make_id("r", sfold(name) or name)


def fingerprint(tags: dict, duration: float) -> str:
    """Finds a song again after it moved outside Codetta: title, artist, album and length."""
    return "\x1f".join([sfold(_first(tags, "title")), sfold(_first(tags, "artist")), sfold(_first(tags, "album")),
                        str(round(duration or 0))])


CONTRIBUTOR_ROLES = ("composer", "lyricist", "producer", "engineer", "mixer", "arranger", "remixer", "conductor", "djmixer")
VARIOUS = {"various artists", "various", "va"}


@dataclass
class Album:
    id: str
    name: str
    artist: str  # how the album artist reads
    artist_ids: list[str] = field(default_factory=list)
    songs: list[str] = field(default_factory=list)  # song IDs, in disc/track order
    year: int | None = None
    genres: list[str] = field(default_factory=list)
    cover: str | None = None  # a song path whose embedded cover stands for the album
    created: float = 0.0  # newest file's modification time
    duration: int = 0
    tags: dict = field(default_factory=dict)  # the first song's tags (album-wide details)
    base: dict = field(default_factory=dict)
    text: str = ""


@dataclass
class Artist:
    id: str
    name: str
    albums: list[str] = field(default_factory=list)  # as album artist
    appears: list[str] = field(default_factory=list)  # only as a track artist
    mbid: str = ""
    sort: str = ""
    text: str = ""


@dataclass
class Song:
    id: str
    path: str
    track: dict
    size: int
    mtime: float
    album_id: str = ""
    artist_id: str = ""
    base: dict = field(default_factory=dict)
    text: str = ""
    fp: str = ""


class Catalog:
    def __init__(self, rows: Iterable[tuple[str, int, float, dict]]) -> None:
        self.songs: dict[str, Song] = {}
        self.albums: dict[str, Album] = {}
        self.artists: dict[str, Artist] = {}
        self.built = time.time()
        for path, size, mtime, track in rows:
            if track.get("error"):
                continue
            self._add(path, size, mtime, track)
        self._finish()

    def _artist(self, name: str, mbid: str = "", sort: str = "") -> Artist:
        aid = artist_id(name)
        a = self.artists.get(aid)
        if a is None:
            a = self.artists[aid] = Artist(aid, name, mbid=mbid, sort=sort, text=sfold(name))
        if mbid and not a.mbid:
            a.mbid = mbid
        if sort and not a.sort:
            a.sort = sort
        return a

    def _add(self, path: str, size: int, mtime: float, track: dict) -> None:
        tags = track.get("tags") or {}
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        album_name = _first(tags, "album")
        album_artists = _all(tags, "albumartist") or _all(tags, "artist")[:1] or ["Unknown artist"]
        lead = album_artists[0]
        mb_album = _mbid(tags, "musicbrainz_albumid")
        if mb_album:
            key = f"mb\x1f{mb_album}"
        elif album_name:
            key = f"{sfold(lead)}\x1f{sfold(album_name)}"
        else:
            key = f"\x1ffolder\x1f{folder}"
        album_id = make_id("a", key)
        song = Song(make_id("s", path), path, track, size or 0, (mtime or 0) / 1e9, album_id, artist_id(lead))
        song.fp = fingerprint(tags, track.get("duration") or 0)
        self.songs[song.id] = song
        album = self.albums.get(album_id)
        if album is None:
            album = self.albums[album_id] = Album(album_id, album_name or (folder.rsplit("/", 1)[-1] or "Unknown album"),
                                                  " & ".join(album_artists) if len(album_artists) > 1 else lead, tags=tags)
            for i, name in enumerate(album_artists):
                a = self._artist(name, _mbid(tags, "musicbrainz_albumartistid", i), _first(tags, "albumartistsort") if i == 0 else "")
                album.artist_ids.append(a.id)
                a.albums.append(album_id)
        album.songs.append(song.id)
        album.duration += int(track.get("duration") or 0)
        album.created = max(album.created, song.mtime)
        album.year = album.year or _year(tags)
        for g in _split(_all(tags, "genre")):
            if g not in album.genres:
                album.genres.append(g)
        if album.cover is None and track.get("art"):
            album.cover = path
        for i, name in enumerate(_all(tags, "artist")):
            a = self._artist(name, _mbid(tags, "musicbrainz_artistid", i), _first(tags, "artistsort") if i == 0 else "")
            if album_id not in a.albums and album_id not in a.appears:
                a.appears.append(album_id)

    def _finish(self) -> None:
        def order(sid: str) -> tuple:
            t = self.songs[sid].track.get("tags") or {}
            return (_int(_first(t, "discnumber")) or 1, _int(_first(t, "tracknumber")) or 9999, self.songs[sid].path)

        for album in self.albums.values():
            album.songs.sort(key=order)
            album.base = self._album_base(album)
            album.text = f"{sfold(album.name)} {sfold(album.artist)}"
        for artist in self.artists.values():
            for ids in (artist.albums, artist.appears):
                ids.sort(key=lambda a: (self.albums[a].year or 0, sfold(self.albums[a].name)))
        for song in self.songs.values():
            song.base = self._song_base(song)
            t = song.track.get("tags") or {}
            song.text = " ".join(sfold(x) for x in (_first(t, "title"), _first(t, "artist"),
                                                     self.albums[song.album_id].name, song.path.rsplit("/", 1)[-1]) if x)

    # --- Shapes the API sends (built once per catalogue; user details added per request) ------

    def _song_base(self, s: Song) -> dict:
        t = s.track.get("tags") or {}
        suffix = s.path.rsplit(".", 1)[-1].lower() if "." in s.path else ""
        album = self.albums[s.album_id]
        artists = _all(t, "artist") or [album.artist]
        out = {
            "id": s.id, "parent": s.album_id, "isDir": False, "type": "music", "mediaType": "song",
            "title": _first(t, "title") or s.path.rsplit("/", 1)[-1],
            "album": album.name, "artist": ", ".join(artists) if len(artists) > 1 else artists[0],
            "albumId": s.album_id, "artistId": artist_id(artists[0]),
            "suffix": suffix, "contentType": CONTENT_TYPES.get(suffix, "application/octet-stream"),
            "path": s.path, "size": s.size,
            "duration": int(s.track.get("duration") or 0),
            "bitRate": int((s.track.get("bitrate") or 0) / 1000),
            "created": _iso(s.mtime),
            "displayArtist": ", ".join(artists),
            "artists": [{"id": artist_id(a), "name": a} for a in artists],
            "displayAlbumArtist": album.artist,
            "albumArtists": [{"id": aid, "name": self.artists[aid].name} for aid in album.artist_ids],
            "genres": [{"name": g} for g in _split(_all(t, "genre"))],
        }
        for key, value in (("track", _int(_first(t, "tracknumber"))), ("discNumber", _int(_first(t, "discnumber"))),
                           ("year", _year(t)), ("genre", (_split(_all(t, "genre")) or [""])[0]),
                           ("bpm", _int(_first(t, "bpm"))), ("comment", _first(t, "comment")[:500]),
                           ("sortName", _first(t, "titlesort")), ("musicBrainzId", _mbid(t, "musicbrainz_trackid")),
                           ("samplingRate", s.track.get("sample_rate")), ("channelCount", s.track.get("channels"))):
            if value:
                out[key] = value
        rg = {k: v for k, v in (("trackGain", _float(_first(t, "replaygain_track_gain"))),
                                ("albumGain", _float(_first(t, "replaygain_album_gain"))),
                                ("trackPeak", _float(_first(t, "replaygain_track_peak"))),
                                ("albumPeak", _float(_first(t, "replaygain_album_peak")))) if v is not None}
        if rg:
            out["replayGain"] = rg
        advisory = _first(t, "itunesadvisory")
        if advisory in ("1", "4"):
            out["explicitStatus"] = "explicit"
        elif advisory == "2":
            out["explicitStatus"] = "clean"
        contributors = [{"role": role, "artist": {"id": artist_id(name), "name": name}}
                        for role in CONTRIBUTOR_ROLES for name in _all(t, role)]
        if contributors:
            out["contributors"] = contributors
        if album.cover:
            out["coverArt"] = album.id
        return out

    def _album_base(self, a: Album) -> dict:
        t = a.tags
        out = {"id": a.id, "name": a.name, "title": a.name, "album": a.name, "artist": a.artist,
               "artistId": a.artist_ids[0] if a.artist_ids else "", "songCount": len(a.songs), "duration": a.duration,
               "created": _iso(a.created), "isDir": True, "parent": a.artist_ids[0] if a.artist_ids else "",
               "displayArtist": a.artist, "artists": [{"id": i, "name": self.artists[i].name} for i in a.artist_ids],
               "genres": [{"name": g} for g in a.genres], "isCompilation": _first(t, "compilation") == "1"
               or sfold(a.artist) in VARIOUS}
        types = _split(_all(t, "releasetype"))
        labels = _split(_all(t, "label"))
        discs: dict[int, str] = {}
        for sid in a.songs:
            st = self.songs[sid].track.get("tags") or {}
            title = _first(st, "discsubtitle")
            if title:
                discs.setdefault(_int(_first(st, "discnumber")) or 1, title)
        for key, value in (("year", a.year), ("genre", a.genres[0] if a.genres else None),
                           ("coverArt", a.id if a.cover else None), ("musicBrainzId", _mbid(t, "musicbrainz_albumid")),
                           ("sortName", _first(t, "albumsort")), ("releaseTypes", types or None),
                           ("recordLabels", [{"name": x} for x in labels] or None),
                           ("originalReleaseDate", _date(_first(t, "originaldate"))), ("releaseDate", _date(_first(t, "date"))),
                           ("discTitles", [{"disc": d, "title": x} for d, x in sorted(discs.items())] or None)):
            if value:
                out[key] = value
        return out

    def song_out(self, s: Song, marks: dict | None = None) -> dict:
        return _with_marks(dict(s.base), (marks or {}).get("s", {}).get(s.path))

    def album_out(self, a: Album, with_songs: bool = False, marks: dict | None = None) -> dict:
        out = _with_marks(dict(a.base), (marks or {}).get("a", {}).get(a.id))
        if with_songs:
            out["song"] = [self.song_out(self.songs[s], marks) for s in a.songs]
        return out

    def artist_out(self, r: Artist, with_albums: bool = False, marks: dict | None = None) -> dict:
        own = r.albums or r.appears
        out = {"id": r.id, "name": r.name, "albumCount": len(own)}
        cover = next((self.albums[a].id for a in own if self.albums[a].cover), None)
        if cover:
            out["coverArt"] = r.id  # the artist's picture, falling back to an album cover
            out["artistImageUrl"] = ""  # filled in by the route (needs the request's address)
        if r.mbid:
            out["musicBrainzId"] = r.mbid
        if r.sort:
            out["sortName"] = r.sort
        out = _with_marks(out, (marks or {}).get("r", {}).get(r.id))
        if with_albums:
            out["album"] = [self.album_out(self.albums[a], marks=marks) for a in own]
        return out

    def indexes(self, marks: dict | None = None) -> list[dict]:
        """Album artists under their first letter ("#" for the rest), as getArtists sends them."""
        groups: dict[str, list[Artist]] = {}
        for r in self.artists.values():
            if not r.albums:
                continue  # track-only artists aren't listed (as in Navidrome); their IDs still work
            letter = (sfold(r.sort or r.name)[:1] or "#").upper()
            groups.setdefault(letter if letter.isalpha() else "#", []).append(r)
        return [{"name": k, "artist": [self.artist_out(r, marks=marks) for r in sorted(v, key=lambda x: sfold(x.sort or x.name))]}
                for k, v in sorted(groups.items())]

    def search(self, query: str) -> tuple[list[Artist], list[Album], list[Song]]:
        words = sfold(query.replace('"', " ")).split()
        hit = (lambda text: all(w in text for w in words)) if words else (lambda text: True)
        artists = sorted((r for r in self.artists.values() if (r.albums or not words) and hit(r.text) and (r.albums or r.appears)),
                         key=lambda r: sfold(r.name))
        albums = sorted((a for a in self.albums.values() if hit(a.text)), key=lambda a: (sfold(a.artist), sfold(a.name)))
        songs = sorted((s for s in self.songs.values() if hit(s.text)), key=lambda s: s.path)
        return artists, albums, songs

    def by_fp(self) -> dict[str, str]:
        """fingerprint -> path, only for fingerprints that belong to exactly one song."""
        seen: dict[str, str | None] = {}
        for s in self.songs.values():
            seen[s.fp] = None if s.fp in seen else s.path
        return {k: v for k, v in seen.items() if v and k.strip("\x1f0")}


def _with_marks(out: dict, mark) -> dict:
    if mark is not None:
        if mark.starred:
            out["starred"] = _iso(mark.starred)
        if mark.rating:
            out["userRating"] = mark.rating
        if mark.plays:
            out["playCount"] = mark.plays
        if mark.last_played:
            out["played"] = _iso(mark.last_played)
    return out


CONTENT_TYPES = {
    "mp3": "audio/mpeg", "mp2": "audio/mpeg", "flac": "audio/flac", "m4a": "audio/mp4", "m4b": "audio/mp4",
    "aac": "audio/aac", "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg", "spx": "audio/ogg",
    "wav": "audio/wav", "aiff": "audio/aiff", "aif": "audio/aiff", "wv": "audio/x-wavpack", "ape": "audio/x-ape",
    "mpc": "audio/x-musepack", "tta": "audio/x-tta", "wma": "audio/x-ms-wma", "dsf": "audio/dsf", "dff": "audio/dff",
}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts or 0, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --- Signing in ---------------------------------------------------------------------------------


FORMATS = ("mp3", "opus", "aac")


@dataclass
class SubsonicSettings:
    enabled: bool = False
    password: str = ""
    transcode: bool = True  # convert when an app asks (format=… / maxBitRate=…)
    format: str = "mp3"  # what to convert to when an app only gives a bitrate


class SubsonicStore:
    """Settings in subsonic.json (owner-only: it holds the app password)."""

    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        self.settings = SubsonicSettings()
        try:
            data = json.loads(file.read_text("utf-8"))
            if isinstance(data, dict):
                fmt = str(data.get("format") or "mp3")
                self.settings = SubsonicSettings(enabled=bool(data.get("enabled")), password=str(data.get("password") or ""),
                                                 transcode=bool(data.get("transcode", True)),
                                                 format=fmt if fmt in FORMATS else "mp3")
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
                s = self.settings
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"enabled": s.enabled, "password": s.password, "transcode": s.transcode, "format": s.format}, f)
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
    """The catalogue, rebuilt when the index changes (checked at most every few seconds).

    Only the very first build makes a request wait; later rebuilds run on a background thread
    while requests keep getting the previous catalogue."""

    def __init__(self, rows, signature, every: float = 5.0, on_build=None) -> None:
        self.rows, self.signature, self.every, self.on_build = rows, signature, every, on_build
        self._catalog: Catalog | None = None
        self._sig = None
        self._checked = 0.0
        self._building = False
        self._lock = threading.Lock()

    def _build(self, sig) -> Catalog | None:
        try:
            cat = Catalog(self.rows())
        except Exception:  # noqa: BLE001 - keep serving the last good catalogue, and try again later
            log.exception("Music apps: couldn't rebuild the library view")
            with self._lock:
                self._building = False
            return None
        if self.on_build is not None:
            try:
                self.on_build(cat)
            except Exception:  # noqa: BLE001 - never lose the catalogue over a follow-up
                log.exception("Music apps: follow-up after a rebuild failed")
        with self._lock:
            self._catalog, self._sig, self._building = cat, sig, False
        return cat

    def get(self) -> Catalog:
        with self._lock:
            cat, now = self._catalog, time.monotonic()
            due = cat is not None and not self._building and now - self._checked > self.every
            if due:
                self._checked = now
        if cat is None:
            built = self._build(self.signature())
            if built is None:
                raise SubsonicError(0, "Codetta couldn't read the library for music apps. The server log has the details.")
            return built
        if due:
            sig = self.signature()
            if sig != self._sig:
                with self._lock:
                    self._building = True
                threading.Thread(target=self._build, args=(sig,), name="music-apps-catalog", daemon=True).start()
        return cat
