"""Autoplay: when the queue runs out, keep playing songs like the last ones, from the library.

Sources are asked in order, and the first that finds enough songs in the library wins:

1. **AudioMuse-AI** (the user's own server): songs that *sound* alike.
2. **ListenBrainz** (free, no account): artists that people listen to together, found by
   the playing artist's MusicBrainz ID, and the recordings they're known for.
3. **Deezer** (no account): Deezer's related artists, found by name.
4. **The library itself**, always and offline: the same artist's other albums, then the same
   genre, then anything.

Every answer is mapped back to files already in the library (by MusicBrainz IDs where the
tags have them, otherwise by title and artist): Autoplay never downloads anything. The
online sources only run while their connection is switched on.
"""

from __future__ import annotations

import logging
import random
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable

from codetta.core.catalogs import deezer_artist

log = logging.getLogger("codetta")

LISTENBRAINZ_API = "https://api.listenbrainz.org/1"
DEEZER_API = "https://api.deezer.com"
PER_ARTIST = 2  # songs by one artist in a batch
SEEDS = 2  # recent songs a source starts from
MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SOURCE_NAMES = {"audiomuse": "AudioMuse-AI", "listenbrainz": "ListenBrainz", "deezer": "Deezer", "library": "your library"}

Fetch = Callable[[str], object]  # url -> parsed JSON (None for 404)


def _first(tags: dict, key: str) -> str:
    v = tags.get(key)
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "").strip()


def _mbid(tags: dict, key: str) -> str:
    v = _first(tags, key).split(";")[0].split("/")[0].strip().lower()
    return v if MBID.match(v) else ""


class Autoplay:
    def __init__(self, index, tags_of: Callable[[list[str]], dict[str, dict]], enabled: Callable[[str], bool],
                 fetch: Fetch, audiomuse=None, rnd: random.Random | None = None) -> None:
        self.index = index  # LibraryIndex: paths_where(), random_paths()
        self.tags_of = tags_of  # paths -> {path: tags}
        self.enabled = enabled  # connection id -> on?
        self.fetch = fetch
        self.audiomuse = audiomuse
        self.rnd = rnd or random.Random()
        self._cache: OrderedDict[str, object] = OrderedDict()  # recent ListenBrainz/Deezer answers
        self._lock = threading.Lock()

    # --- The answer ---------------------------------------------------------------------------

    def next_tracks(self, seeds: list[str], avoid: Iterable[str] = (), n: int = 10) -> dict:
        """Up to ``n`` library paths to play after ``seeds`` (most recent last), none of them in ``avoid``.

        ``{"paths": [...], "source": "audiomuse" | ..., "because": "<artist>"}``."""
        seeds = [s for s in seeds if s][-SEEDS * 3:]
        avoid = set(avoid) | set(seeds)
        tags = self.tags_of(seeds) if seeds else {}
        seed_tags = [tags[s] for s in reversed(seeds) if s in tags][:SEEDS]  # most recent first
        because = (_first(seed_tags[0], "artist") or _first(seed_tags[0], "albumartist")) if seed_tags else ""
        sources = (("audiomuse", self._audiomuse), ("listenbrainz", self._listenbrainz),
                   ("deezer", self._deezer), ("library", self._library))
        picked: list[str] = []
        state = {"artists": {}, "album": None}  # variety carries across sources
        source = ""
        for name, ask in sources:
            if name != "library" and not self.enabled(name):
                continue
            if not seed_tags and name != "library":
                continue
            try:
                found = ask(seed_tags)
            except Exception as exc:  # noqa: BLE001 - one source failing must not stop the music
                log.info("Autoplay: %s didn't answer (%s)", SOURCE_NAMES[name], exc)
                continue
            more = self._pick(found, avoid | set(picked), n - len(picked), state)
            if more and not source:
                source = name  # the first source that found anything is the one named
            picked += more
            if len(picked) >= n:
                break
        return {"paths": picked, "source": source or "library", "because": because}

    def _pick(self, candidates: list[str], avoid: set[str], n: int, state: dict | None = None) -> list[str]:
        """Variety: no repeats, at most PER_ARTIST per artist, never the same album twice in a row.
        The best few times ``n`` are shuffled so the same seed doesn't always play the same songs.
        ``state`` carries the artist counts and the last album from one source to the next."""
        if n <= 0:
            return []
        state = state if state is not None else {"artists": {}, "album": None}
        seen, pool = set(), []
        for p in candidates:
            if p not in avoid and p not in seen:
                seen.add(p)
                pool.append(p)
        pool = pool[: n * 4]
        self.rnd.shuffle(pool)
        tags = self.tags_of(pool) if pool else {}
        per_artist: dict[str, int] = state["artists"]
        out = []
        for p in pool:
            t = tags.get(p, {})
            artist = (_first(t, "albumartist") or _first(t, "artist")).lower()
            album = (artist, _first(t, "album").lower())
            if per_artist.get(artist, 0) >= PER_ARTIST or album == state["album"]:
                continue
            per_artist[artist] = per_artist.get(artist, 0) + 1
            out.append(p)
            state["album"] = album
            if len(out) >= n:
                break
        return out

    # --- Finding files ------------------------------------------------------------------------

    def _by_title(self, title: str, artist: str) -> list[str]:
        hits = self.index.paths_where("title", title, limit=50)
        if not hits:
            return []
        for key in ("artist", "albumartist"):
            both = hits & self.index.paths_where(key, artist, limit=5000)
            if both:
                return sorted(both)[:1]
        return []

    def _by_artist(self, name: str = "", mbid: str = "", limit: int = 30) -> list[str]:
        found: set[str] = set()
        if mbid:
            found |= self.index.paths_where("musicbrainz_artistid", mbid, limit=limit * 4)
        if not found and name:
            for key in ("albumartist", "artist"):
                found |= self.index.paths_where(key, name, limit=limit * 4)
        out = sorted(found)
        self.rnd.shuffle(out)
        return out[:limit]

    def _remember(self, key: str, make: Callable[[], object]) -> object:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        value = make()
        with self._lock:
            self._cache[key] = value
            while len(self._cache) > 200:
                self._cache.popitem(last=False)
        return value

    # --- Sources ------------------------------------------------------------------------------

    def _audiomuse(self, seeds: list[dict]) -> list[str]:
        if self.audiomuse is None or not self.audiomuse.store.configured:
            return []
        out: list[str] = []
        for t in seeds:
            title, artist = _first(t, "title"), _first(t, "artist") or _first(t, "albumartist")
            if not (title and artist):
                continue
            for s in self.audiomuse.similar(title, artist, 40):
                out += self._by_title(s["title"], s["artist"])
        return out

    def _listenbrainz(self, seeds: list[dict]) -> list[str]:
        out: list[str] = []
        for t in seeds:
            seed_artist = _mbid(t, "musicbrainz_artistid") or _mbid(t, "musicbrainz_albumartistid")
            if not seed_artist:
                continue
            url = (f"{LISTENBRAINZ_API}/lb-radio/artist/{seed_artist}?mode=easy&max_similar_artists=10"
                   "&max_recordings_per_artist=8&pop_begin=0&pop_end=100")
            data = self._remember(url, lambda u=url: self.fetch(u))
            if not isinstance(data, dict):
                continue
            for artist_mbid, recordings in data.items():
                if artist_mbid == seed_artist or not isinstance(recordings, list):
                    continue
                name = next((str(r.get("similar_artist_name") or "") for r in recordings if isinstance(r, dict)), "")
                hits: list[str] = []
                for r in recordings:
                    rec = str(r.get("recording_mbid") or "").lower() if isinstance(r, dict) else ""
                    if MBID.match(rec):
                        hits += sorted(self.index.paths_where("musicbrainz_trackid", rec, limit=5))
                out += hits or self._by_artist(name, artist_mbid if MBID.match(artist_mbid) else "", limit=4)
        return out

    def _deezer(self, seeds: list[dict]) -> list[str]:
        out: list[str] = []
        for t in seeds:
            name = _first(t, "albumartist") or _first(t, "artist")
            if not name:
                continue
            best = self._remember("dz-artist:" + name.lower(), lambda n=name: deezer_artist(self.fetch, n))
            if not best:
                continue
            aid = int(best["id"])
            related = self._remember(f"dz-related:{aid}", lambda a=aid: self.fetch(f"{DEEZER_API}/artist/{a}/related?limit=25"))
            for a in (related.get("data") or []) if isinstance(related, dict) else []:
                if isinstance(a, dict) and a.get("name"):
                    out += self._by_artist(str(a["name"]), limit=4)
        return out

    def _library(self, seeds: list[dict]) -> list[str]:
        out: list[str] = []
        for t in seeds[:1]:
            artist = _first(t, "albumartist") or _first(t, "artist")
            album = _first(t, "album").lower()
            same = self._by_artist(artist, _mbid(t, "musicbrainz_artistid"), limit=60)
            if album:
                tags = self.tags_of(same)
                same = [p for p in same if _first(tags.get(p, {}), "album").lower() != album] or same
            out += same[:8]
            genre = _first(t, "genre")
            if genre:
                hits = sorted(self.index.paths_where("genre", genre, limit=400))
                self.rnd.shuffle(hits)
                out += hits[:40]
        out += self.index.random_paths(40)
        return out
