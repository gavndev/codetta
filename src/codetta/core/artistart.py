"""Artist pictures, shown next to artist names and in the artist menu.

Where a picture comes from, in order:

1. **The artist's own folder**: ``artist.jpg`` (or .png/.webp), the name Navidrome,
   Jellyfin, Emby and Kodi use, then ``folder.jpg``/``poster.jpg``. Always, offline too.
2. **Deezer**, only while the Deezer connection is on: the artist's picture from Deezer's
   catalogue, found by name (the same name with the most fans, so a tiny namesake
   doesn't win). Downloaded once and kept in ``artist-art/`` in the config folder; an
   artist Deezer has no picture for is remembered for a week, so it isn't asked again
   every time the page shows them.

With neither, the page draws the artist's initials instead.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from codetta.core.catalogs import DeezerBusy, deezer_artist
from codetta.core.index import sfold

LOCAL_NAMES = ("artist", "folder", "poster")
LOCAL_EXTS = (".jpg", ".jpeg", ".png", ".webp")
MISS_SECONDS = 7 * 24 * 3600  # how long "Deezer has no picture" is believed
BUSY_SECONDS = 300  # after Deezer says it's busy (over quota), leave it alone this long
MAX_CACHE_FILES = 5000


def _sniff(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ArtistArt:
    def __init__(self, music_dir: Path, cache_dir: Path, deezer_on: Callable[[], bool],
                 fetch_json: Callable[[str], object], fetch_image: Callable[[str], bytes | None]) -> None:
        self.music_dir = music_dir
        self.cache_dir = cache_dir
        self.deezer_on = deezer_on
        self.fetch_json = fetch_json
        self.fetch_image = fetch_image
        self._locks: dict[str, threading.Lock] = {}
        self._busy_until = 0.0  # Deezer said it's busy: don't ask again before this
        self._guard = threading.Lock()

    def local(self, folder: str | None) -> tuple[bytes, str] | None:
        """``artist.jpg`` and friends in a top-level folder of the library."""
        if not folder or "/" in folder or folder.startswith("."):
            return None
        base = self.music_dir / folder
        try:
            names = {e.name.lower(): e.name for e in os.scandir(base) if e.is_file(follow_symlinks=False)}
        except OSError:
            return None
        for stem in LOCAL_NAMES:
            for ext in LOCAL_EXTS:
                real = names.get(stem + ext)
                if real:
                    try:
                        data = (base / real).read_bytes()[:10_000_000]
                    except OSError:
                        continue
                    kind = _sniff(data)
                    if kind:
                        return data, kind
        return None

    def _key(self, name: str) -> str:
        return hashlib.sha1(sfold(name).encode()).hexdigest()[:20]

    def picture(self, name: str, folder: str | None = None) -> tuple[bytes, str] | None:
        """The artist's picture as (bytes, media type), or None (the page draws initials)."""
        found = self.local(folder)
        if found or not sfold(name):
            return found
        key = self._key(name)
        hit, miss = self.cache_dir / f"{key}.img", self.cache_dir / f"{key}.none"
        cached = self._cached(hit)
        if cached:
            return cached
        try:
            if time.time() - miss.stat().st_mtime < MISS_SECONDS:
                return None
        except OSError:
            pass
        if not self.deezer_on() or time.time() < self._busy_until:
            return None
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:  # two rows asking for the same artist download it once
            cached = self._cached(hit)  # another request may have fetched it meanwhile
            if cached:
                return cached
            try:
                data = self._deezer(name)
            except DeezerBusy:
                self._busy_until = time.time() + BUSY_SECONDS  # a music app syncing 800 artists won't keep the quota spent
                return None  # Deezer is busy or over quota: no answer is not "no picture"
            self._store(hit if data else miss, data or b"")
            kind = _sniff(data) if data else None
            return (data, kind) if data and kind else None

    def _cached(self, hit: Path) -> tuple[bytes, str] | None:
        try:
            data = hit.read_bytes()
        except OSError:
            return None
        kind = _sniff(data)
        if kind:
            return data, kind
        hit.unlink(missing_ok=True)  # broken (cut short, edited): fetch it again
        return None

    def _deezer(self, name: str) -> bytes | None:
        best = deezer_artist(self.fetch_json, name)
        if best is None:
            return None  # a different artist's face is worse than initials
        url = str(best.get("picture_medium") or best.get("picture_big") or "")
        # Deezer's stand-in for "no picture" has an empty image id: ".../images/artist//250x250..."
        if not url.startswith("https://") or "/artist//" in url:
            return None
        data = self.fetch_image(url)
        return data if data and _sniff(data) else None

    def _store(self, path: Path, data: bytes) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.cache_dir, prefix=".art-")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            files = sorted(self.cache_dir.iterdir(), key=lambda p: p.stat().st_mtime)
            for old in files[:-MAX_CACHE_FILES]:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # a picture not kept is fetched again next time; nothing breaks
