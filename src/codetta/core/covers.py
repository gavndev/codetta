"""Covers at the size an app asks for, cached on disk.

Music apps ask for small thumbnails for their lists (``getCoverArt?size=150``) and bigger ones
for the player. Embedded covers are often 1000-3000 px and several MB, so they're scaled down
once and kept in ``cover-cache/`` in the config folder (a size-capped cache: the oldest
thumbnails go first). Asking for the original size, or more, returns the original bytes.

Covers come from files people download, so decoding is guarded: Pillow's decompression-bomb
limit is lowered, and anything Pillow can't read safely is sent as it is (the caller has
already checked it's a real image).
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
import threading
from pathlib import Path

from PIL import Image

MAX_SIZE = 1500  # px: bigger requests get the original
MAX_PIXELS = 40_000_000  # refuse to decode bigger images (a 6000x6000 cover is already absurd)
CACHE_BYTES = 200 * 1024 * 1024
QUALITY = 85

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def resize(data: bytes, size: int) -> bytes | None:
    """``data`` scaled to fit ``size`` x ``size`` as a JPEG, or None (keep the original)."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > MAX_PIXELS or max(im.width, im.height) <= size:
                return None
            im.draft("RGB", (size, size))  # JPEG: decode at a smaller scale straight away
            img = im.convert("RGB")
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
            return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError, SyntaxError):
        return None


class CoverCache:
    def __init__(self, folder: Path, max_bytes: int = CACHE_BYTES) -> None:
        self.folder = folder
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._writes = 0

    def get(self, data: bytes, key: str, size: int | None) -> tuple[bytes, bool]:
        """(bytes, resized). ``key`` identifies the source (path + modification time)."""
        if not size or size <= 0 or size >= MAX_SIZE:
            return data, False
        name = hashlib.sha1(f"{key}\x1f{size}".encode()).hexdigest() + ".jpg"
        path = self.folder / name
        try:
            cached = path.read_bytes()
            os.utime(path)  # recently used: kept longer
            return cached, True
        except OSError:
            pass
        small = resize(data, size)
        if small is None:
            return data, False
        self._store(path, small)
        return small, True

    def _store(self, path: Path, data: bytes) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=".cover-")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except OSError:
            return  # not cached this time; nothing breaks
        with self._lock:
            self._writes += 1
            if self._writes % 50:
                return
        self.prune()

    def prune(self) -> None:
        """Remove the least recently used thumbnails until the cache fits its budget."""
        try:
            files = [(p.stat().st_mtime, p.stat().st_size, p) for p in self.folder.glob("*.jpg")]
        except OSError:
            return
        total = sum(s for _, s, _ in files)
        for _, s, p in sorted(files):
            if total <= self.max_bytes:
                break
            p.unlink(missing_ok=True)
            total -= s
