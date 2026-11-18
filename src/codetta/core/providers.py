"""Online metadata providers: the first step toward Codetta plugins.

A provider looks something up for one track and returns suggestions; it never
writes files. The user always sees a preview and decides. LRCLIB (lyrics) lives
here; MusicBrainz is in ``musicbrainz.py``. Each belongs to a *connection*
(see ``connections.py``) that is off until the user opts in.

Privacy: providers are only called when the user asks (a button press), and
only send what the lookup needs (artist, title, album, duration).
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_LYRICS_CHARS = 100_000  # same cap as any tag value
TIMEOUT = 8


class ProviderError(Exception):
    """The provider couldn't be reached or answered with something unusable."""


@dataclass
class TrackQuery:
    artist: str
    title: str
    album: str = ""
    duration: float | None = None  # seconds


@dataclass
class LyricsResult:
    provider: str
    artist: str
    title: str
    album: str
    duration: float | None
    synced: str  # LRC text, or "" if the provider only has plain lyrics
    plain: str
    instrumental: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# (url) -> parsed JSON or None for "not found". Replaceable in tests.
Fetcher = Callable[[str], object]


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects (the Cover Art Archive sends you to archive.org), but
    never from https down to plain http."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.full_url.startswith("https://") and not newurl.startswith("https://"):
            raise ProviderError("The service tried to redirect to an insecure address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_HttpsOnlyRedirects)


def http_get(url: str, user_agent: str, *, accept: str = "application/json", max_bytes: int = MAX_RESPONSE_BYTES,
             service: str = "the lyrics service", allow_http: bool = False) -> bytes | None:
    """GET a provider URL, size- and time-limited. None means 404 (not found).

    Only https, unless ``allow_http`` (a self-hosted mirror the admin set up)."""
    if not (url.startswith("https://") or (allow_http and url.startswith("http://"))):
        raise ProviderError("Providers must use https")
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": accept})
    try:
        with _opener.open(req, timeout=TIMEOUT) as res:  # nosec B310: http(s) only, fixed provider hosts
            data = res.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code in (429, 503):
            raise ProviderError(f"{service.capitalize()} is busy right now. Try again in a moment.") from exc
        raise ProviderError(f"{service.capitalize()} answered with an error ({exc.code})") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Couldn't reach {service}. Is the server online?") from exc
    if len(data) > max_bytes:
        raise ProviderError(f"{service.capitalize()} sent an unexpectedly large answer")
    return data


def http_get_json(url: str, user_agent: str, *, max_bytes: int = MAX_RESPONSE_BYTES,
                  service: str = "the lyrics service", allow_http: bool = False) -> object:
    """GET a JSON document (None for 404)."""
    data = http_get(url, user_agent, max_bytes=max_bytes, service=service, allow_http=allow_http)
    if data is None:
        return None
    try:
        return json.loads(data)
    except ValueError as exc:
        raise ProviderError(f"{service.capitalize()} sent something that isn't JSON") from exc


class LRCLib:
    """https://lrclib.net: free, open, no account, plain and synced lyrics."""

    name = "LRCLIB"
    base = "https://lrclib.net/api"

    def __init__(self, fetch: Fetcher):
        self.fetch = fetch
        self._cache: OrderedDict[tuple, LyricsResult | None] = OrderedDict()
        self._lock = threading.Lock()

    def lyrics(self, q: TrackQuery) -> LyricsResult | None:
        key = (q.artist.casefold(), q.title.casefold(), q.album.casefold(), round(q.duration or 0))
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        result = self._lookup(q)
        with self._lock:
            self._cache[key] = result
            while len(self._cache) > 500:
                self._cache.popitem(last=False)
        return result

    def _lookup(self, q: TrackQuery) -> LyricsResult | None:
        params = {"artist_name": q.artist, "track_name": q.title}
        if q.album:
            params["album_name"] = q.album
        if q.duration:
            params["duration"] = str(round(q.duration))
        exact = self.fetch(f"{self.base}/get?{urllib.parse.urlencode(params)}")
        if isinstance(exact, dict) and (exact.get("syncedLyrics") or exact.get("plainLyrics") or exact.get("instrumental")):
            return self._result(exact)
        # No exact match (e.g. album or duration differ slightly): search, and
        # take the closest by duration among same-title results.
        found = self.fetch(f"{self.base}/search?{urllib.parse.urlencode({'artist_name': q.artist, 'track_name': q.title})}")
        candidates = [r for r in found if isinstance(r, dict)] if isinstance(found, list) else []
        candidates = [r for r in candidates if r.get("syncedLyrics") or r.get("plainLyrics")]
        if not candidates:
            return None
        if q.duration:
            # Only versions within a few seconds of this file: synced lyrics from a
            # different edit (radio, extended) would be out of time.
            candidates = [r for r in candidates if abs((r.get("duration") or 0) - q.duration) <= 5]
            candidates.sort(key=lambda r: abs((r.get("duration") or 0) - q.duration))
            if not candidates:
                return None
        candidates.sort(key=lambda r: not r.get("syncedLyrics"))  # stable: closest synced, else closest
        return self._result(candidates[0])

    def _result(self, r: dict) -> LyricsResult:
        def text(key: str) -> str:
            value = r.get(key) or ""
            return value[:MAX_LYRICS_CHARS] if isinstance(value, str) else ""

        duration = r.get("duration")
        return LyricsResult(
            provider=self.name,
            artist=text("artistName"), title=text("trackName"), album=text("albumName"),
            duration=float(duration) if isinstance(duration, (int, float)) else None,
            synced=text("syncedLyrics").strip(), plain=text("plainLyrics").strip(),
            instrumental=bool(r.get("instrumental")),
        )
