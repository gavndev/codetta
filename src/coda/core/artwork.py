"""Embedded album art: reading, validating and writing pictures per format.

Each format keeps pictures somewhere different:

    FLAC        METADATA_BLOCK_PICTURE blocks (``audio.pictures``)
    MP3         ID3 ``APIC`` frames
    M4A         the ``covr`` atom (JPEG or PNG only)
    OGG / Opus  a base64-encoded picture block in the ``metadata_block_picture``
                comment

Coda keeps it simple and predictable: *setting* art replaces every embedded
picture with one front cover, and *removing* art removes them all. Images must
be JPEG or PNG, which every player (and Navidrome) understands.

These functions work on already-opened mutagen objects; the engine handles
opening files and the safe temp-copy write.
"""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass

from mutagen.flac import Picture
from mutagen.id3 import APIC
from mutagen.mp4 import MP4Cover

MAX_ART_BYTES = 20 * 1024 * 1024  # 20 MB; real covers are usually < 2 MB
FRONT_COVER = 3  # picture type for "Cover (front)" in FLAC/ID3


class ArtworkError(ValueError):
    """The image is not usable as album art."""


@dataclass(frozen=True)
class Artwork:
    data: bytes
    mime: str  # "image/jpeg" or "image/png"
    width: int | None = None
    height: int | None = None


def parse_image(data: bytes) -> Artwork:
    """Check that ``data`` is a JPEG or PNG and read its size."""
    if not data:
        raise ArtworkError("The image is empty")
    if len(data) > MAX_ART_BYTES:
        raise ArtworkError(f"The image is too large (max {MAX_ART_BYTES // (1024 * 1024)} MB)")
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return Artwork(data, "image/png", width or None, height or None)
    if data.startswith(b"\xff\xd8\xff"):
        width, height = _jpeg_size(data)
        return Artwork(data, "image/jpeg", width, height)
    raise ArtworkError("Album art must be a JPEG or PNG image")


def _jpeg_size(data: bytes) -> tuple[int | None, int | None]:
    """Find a JPEG's dimensions in its start-of-frame (SOFn) marker."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:  # padding
            i += 1
            continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:  # markers without a length
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width or None, height or None
        i += 2 + length
    return None, None


# --- Reading ---------------------------------------------------------------------


def read_picture(audio, format_name: str) -> Artwork | None:
    """The front cover if there is one, otherwise the first picture."""
    candidates: list[tuple[int, bytes, str]] = []  # (type, data, mime)
    if format_name == "flac":
        candidates = [(p.type, p.data, p.mime) for p in audio.pictures]
    elif format_name == "mp3":
        frames = audio.tags.getall("APIC") if audio.tags is not None else []
        candidates = [(f.type, f.data, f.mime) for f in frames]
    elif format_name == "m4a":
        covers = (audio.tags or {}).get("covr", [])
        candidates = [
            (FRONT_COVER, bytes(c), "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg")
            for c in covers
        ]
    else:  # ogg / opus
        for encoded in (audio.tags or {}).get("metadata_block_picture", []):
            try:
                pic = Picture(base64.b64decode(encoded))
            except Exception:  # noqa: BLE001 - a damaged picture block is skipped, not fatal
                continue
            candidates.append((pic.type, pic.data, pic.mime))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0] != FRONT_COVER)  # front cover first, else original order
    _, data, mime = candidates[0]
    try:
        return parse_image(data)  # also fills in width/height
    except ArtworkError:
        return Artwork(data, mime or "application/octet-stream")  # unusual image type


# --- Writing -----------------------------------------------------------------------


def write_picture(audio, format_name: str, art: Artwork | None) -> None:
    """Replace all embedded pictures with ``art`` (or remove them if None).

    The caller is responsible for ``audio.save()``.
    """
    if format_name == "flac":
        audio.clear_pictures()
        if art:
            audio.add_picture(_flac_picture(art))
    elif format_name == "mp3":
        if audio.tags is None:
            audio.add_tags()
        audio.tags.delall("APIC")
        if art:
            audio.tags.add(APIC(encoding=3, mime=art.mime, type=FRONT_COVER, desc="", data=art.data))
    elif format_name == "m4a":
        if audio.tags is None:
            audio.add_tags()
        if art:
            fmt = MP4Cover.FORMAT_PNG if art.mime == "image/png" else MP4Cover.FORMAT_JPEG
            audio.tags["covr"] = [MP4Cover(art.data, imageformat=fmt)]
        else:
            audio.tags.pop("covr", None)
    else:  # ogg / opus
        for key in ("metadata_block_picture", "coverart", "coverartmime"):
            if key in audio.tags:
                del audio.tags[key]
        if art:
            block = base64.b64encode(_flac_picture(art).write()).decode("ascii")
            audio.tags["metadata_block_picture"] = [block]


def _flac_picture(art: Artwork) -> Picture:
    pic = Picture()
    pic.type = FRONT_COVER
    pic.mime = art.mime
    pic.desc = ""
    pic.width = art.width or 0
    pic.height = art.height or 0
    pic.depth = 24
    pic.data = art.data
    return pic
