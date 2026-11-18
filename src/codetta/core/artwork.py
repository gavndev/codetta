"""Embedded album art: reading, validating and writing pictures per format.

Each format keeps pictures somewhere different:

    FLAC        METADATA_BLOCK_PICTURE blocks (``audio.pictures``)
    ID3 family  ``APIC`` frames (MP3, MP2, WAV, AIFF, DSF, TrueAudio)
    M4A         the ``covr`` atom (JPEG or PNG only)
    OGG family  a base64-encoded picture block in the ``metadata_block_picture``
                comment (Ogg Vorbis, Opus, Ogg FLAC, Speex)
    WavPack     the APEv2 ``Cover Art (Front)`` binary item ("name\\0" + image)
    WMA         ``WM/Picture`` attributes (a small binary header + image)

Codetta keeps it simple and predictable: *setting* art replaces every embedded
picture with one front cover, and *removing* art removes them all. Images must
be JPEG or PNG, which every player (and Navidrome) understands.

These functions work on already-opened mutagen objects; the engine handles
opening files and the safe temp-copy write.
"""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass

from mutagen.apev2 import BINARY as APE_BINARY
from mutagen.apev2 import APEValue
from mutagen.asf import ASFByteArrayAttribute
from mutagen.flac import Picture
from mutagen.id3 import APIC
from mutagen.mp4 import MP4Cover

from codetta.core.tagmap import APE_FORMATS, ASF_FORMATS, ID3_FORMATS

APE_COVER_KEYS = ("Cover Art (Front)", "Cover Art (Back)", "Cover Art (Other)")

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


def sniff_image_type(data: bytes) -> str | None:
    """The image type from the file's actual bytes (never what it claims to be).

    Only formats every browser displays safely as an <img>; SVG (which can
    carry scripts) is deliberately not included.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


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
    elif format_name in ID3_FORMATS:
        frames = audio.tags.getall("APIC") if audio.tags is not None else []
        candidates = [(f.type, f.data, f.mime) for f in frames]
    elif format_name in APE_FORMATS:
        for i, key in enumerate(APE_COVER_KEYS):
            item = (audio.tags or {}).get(key)
            if item is not None and item.kind == APE_BINARY:
                _, _, data = bytes(item.value).partition(b"\x00")
                candidates.append((FRONT_COVER if i == 0 else 0, data, ""))
    elif format_name in ASF_FORMATS:
        for attr in (audio.tags or {}).get("WM/Picture", []):
            pic = _asf_unpack(bytes(attr.value))
            if pic:
                candidates.append(pic)
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
            except Exception:  # noqa: BLE001  # nosec B112 - a damaged picture block is skipped, not fatal
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
    elif format_name in ID3_FORMATS:
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
    elif format_name in APE_FORMATS:
        if audio.tags is None:
            audio.add_tags()
        for key in APE_COVER_KEYS:
            if key in audio.tags:
                del audio.tags[key]
        if art:
            name = b"cover.png" if art.mime == "image/png" else b"cover.jpg"
            audio.tags["Cover Art (Front)"] = APEValue(name + b"\x00" + art.data, APE_BINARY)
    elif format_name in ASF_FORMATS:
        if "WM/Picture" in audio.tags:
            del audio.tags["WM/Picture"]
        if art:
            audio.tags["WM/Picture"] = [ASFByteArrayAttribute(_asf_pack(art))]
    else:  # ogg family
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


def _asf_pack(art: Artwork) -> bytes:
    """WM/Picture: type (1 byte), size (4, little-endian), MIME and description
    (UTF-16-LE, NUL-terminated), then the image."""
    mime = art.mime.encode("utf-16-le") + b"\x00\x00"
    desc = b"\x00\x00"
    return struct.pack("<bI", FRONT_COVER, len(art.data)) + mime + desc + art.data


def _asf_unpack(value: bytes) -> tuple[int, bytes, str] | None:
    try:
        pic_type, size = struct.unpack_from("<bI", value)
        pos = 5
        strings = []
        for _ in range(2):  # MIME, description
            end = pos
            while value[end:end + 2] != b"\x00\x00":
                end += 2
                if end >= len(value):  # damaged: no terminator
                    return None
            strings.append(value[pos:end].decode("utf-16-le"))
            pos = end + 2
        return pic_type, value[pos:pos + size], strings[0]
    except (struct.error, IndexError, UnicodeDecodeError):
        return None
