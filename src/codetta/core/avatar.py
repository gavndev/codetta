"""Profile pictures.

The browser does the image work (crops to a square, scales to 256x256 and
converts to WebP or JPEG, including HEIC photos where the browser can read
them), so the server only has to check that what arrives really is a small
JPEG, PNG or WebP image and store it, one file per user, in the config folder.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

MAX_AVATAR_BYTES = 2 * 1024 * 1024  # the browser sends ~10-30 KB; this is a generous cap

_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class AvatarError(ValueError):
    """The upload isn't a usable profile picture."""


def detect_image_type(data: bytes) -> str | None:
    """MIME type from the file's first bytes (never trust the file name)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class AvatarStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _base(self, username: str) -> str:
        # File-name-safe and stable for any username (any script, any case).
        return hashlib.sha256(username.strip().lower().encode("utf-8")).hexdigest()[:24]

    def _find(self, username: str) -> Path | None:
        base = self._base(username)
        for ext in _TYPES.values():
            path = self.directory / f"{base}.{ext}"
            if path.is_file():
                return path
        return None

    def get(self, username: str) -> tuple[bytes, str] | None:
        """(image bytes, MIME type), or None if the user has no picture."""
        path = self._find(username)
        if path is None:
            return None
        data = path.read_bytes()
        return data, detect_image_type(data) or "application/octet-stream"

    def version(self, username: str) -> int | None:
        """Changes whenever the picture does (lets browsers cache it safely)."""
        path = self._find(username)
        return path.stat().st_mtime_ns if path else None

    def save(self, username: str, data: bytes) -> None:
        if not data:
            raise AvatarError("The image is empty")
        if len(data) > MAX_AVATAR_BYTES:
            raise AvatarError("That image is too large")
        mime = detect_image_type(data)
        if mime is None:
            raise AvatarError("Profile pictures must be JPEG, PNG or WebP")
        self.directory.mkdir(parents=True, exist_ok=True)
        old = self._find(username)
        target = self.directory / f"{self._base(username)}.{_TYPES[mime]}"
        fd, tmp = tempfile.mkstemp(prefix=".codetta-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        if old is not None and old != target:
            old.unlink(missing_ok=True)

    def delete(self, username: str) -> bool:
        path = self._find(username)
        if path is None:
            return False
        path.unlink()
        return True
