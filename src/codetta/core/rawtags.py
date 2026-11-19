"""Raw tag view for Advanced mode: every stored field, exactly as the file has it.

The editor shows friendly names ("Album artist"); this lists what's really in
the file (``TPE2``, ``aART``, ``ALBUMARTIST``, ``Album Artist``, ``WM/AlbumArtist``),
including fields Codetta doesn't otherwise show and embedded pictures. Read-only.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from pathlib import Path

from mutagen.apev2 import BINARY as APE_BINARY
from mutagen.apev2 import TEXT as APE_TEXT
from mutagen.asf import ASFByteArrayAttribute
from mutagen.flac import Picture
from mutagen.mp4 import MP4FreeForm

from codetta.core.artwork import _asf_unpack, sniff_image_type
from codetta.core.tagmap import APE_FORMATS, ASF_FORMATS, ID3_FORMATS, MP4_FORMATS

MAX_VALUE_CHARS = 2000  # long values (lyrics, fingerprints) are cut for display

PICTURE_TYPES = {0: "Other", 3: "Front cover", 4: "Back cover", 6: "Media", 8: "Artist"}


@dataclass
class RawEntry:
    name: str
    value: str
    kind: str = "text"  # "text", "picture" or "binary"
    length: int | None = None  # full length when ``value`` was shortened


def _text(name: str, value: str) -> RawEntry:
    if len(value) > MAX_VALUE_CHARS:
        return RawEntry(name, value[:MAX_VALUE_CHARS] + "…", length=len(value))
    return RawEntry(name, value)


def _size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n >= 1024 else f"{n} bytes"


def _picture(name: str, mime: str, data: bytes, ptype: int | None = None) -> RawEntry:
    mime = mime or sniff_image_type(data) or ""
    parts = [p for p in (PICTURE_TYPES.get(ptype, "") if ptype is not None else "", mime, _size(len(data))) if p]
    return RawEntry(name, " · ".join(parts), kind="picture")


def raw_tags(audio, format_name: str) -> tuple[str, list[dict]]:
    """(tag system, entries) for a file opened with ``engine._open_raw``."""
    tags = audio.tags
    entries: list[RawEntry] = []

    if format_name in ID3_FORMATS:
        system = f"ID3v2.{tags.version[1]}" if tags is not None else "ID3 (no tags)"
        for key, frame in (tags or {}).items():
            if frame.FrameID == "APIC":
                entries.append(_picture(key, frame.mime, frame.data, frame.type))
            elif hasattr(frame, "people"):  # TIPL / TMCL: "producer: Name; mixer: Name"
                entries.append(_text(key, "; ".join(f"{role}: {name}" for role, name in frame.people)))
            elif hasattr(frame, "text") or hasattr(frame, "url"):
                entries.append(_text(key, str(frame)))
            else:
                data = getattr(frame, "data", b"")
                entries.append(RawEntry(key, _size(len(data)), kind="binary"))
    elif format_name in MP4_FORMATS:
        system = "MP4 atoms"
        for key, values in (tags or {}).items():
            if key == "covr":
                for c in values:
                    entries.append(_picture(key, "image/png" if c.imageformat == 14 else "image/jpeg", bytes(c)))
                continue
            if not isinstance(values, list):  # single-value atoms: cpil (compilation), pgap, hdvd... are a plain bool/int
                values = [values]
            shown = []
            for v in values:
                if isinstance(v, MP4FreeForm):
                    try:
                        shown.append(bytes(v).decode("utf-8"))
                    except UnicodeDecodeError:
                        shown.append(f"<{_size(len(v))} binary>")
                elif isinstance(v, tuple):
                    shown.append("/".join(str(x) for x in v))
                else:
                    shown.append(str(v))
            entries.append(_text(key, " / ".join(shown)))
    elif format_name in APE_FORMATS:
        system = "APEv2"
        for key in (tags or {}).keys():
            item = tags[key]
            if item.kind == APE_TEXT:
                entries.append(_text(key, " / ".join(item)))
            elif item.kind == APE_BINARY and key.lower().startswith("cover art"):
                _, _, data = bytes(item.value).partition(b"\x00")
                entries.append(_picture(key, "", data))
            else:
                entries.append(RawEntry(key, _size(len(bytes(item.value))), kind="binary"))
    elif format_name in ASF_FORMATS:
        system = "ASF attributes"
        for key in tags.keys():
            for attr in tags[key]:
                if isinstance(attr, ASFByteArrayAttribute):
                    pic = _asf_unpack(bytes(attr.value)) if key == "WM/Picture" else None
                    if pic:
                        entries.append(_picture(key, pic[2], pic[1], pic[0]))
                    else:
                        entries.append(RawEntry(key, _size(len(attr.value)), kind="binary"))
                else:
                    entries.append(_text(key, str(attr.value)))
    else:  # Vorbis comments: FLAC and the Ogg family
        system = "Vorbis comments"
        if tags is not None:
            if getattr(tags, "vendor", ""):
                entries.append(_text("(vendor)", tags.vendor))
            for key, value in tags:  # in file order, original spelling
                if key.lower() == "metadata_block_picture":
                    try:
                        pic = Picture(base64.b64decode(value))
                        entries.append(_picture(key, pic.mime, pic.data, pic.type))
                    except Exception:  # noqa: BLE001 - damaged block
                        entries.append(RawEntry(key, f"{len(value)} characters (unreadable picture)", kind="binary"))
                else:
                    entries.append(_text(key, value))
        for pic in getattr(audio, "pictures", []):  # FLAC picture blocks
            entries.append(_picture("PICTURE", pic.mime, pic.data, pic.type))

    return system, [asdict(e) for e in entries]


def read_raw(engine, path: Path) -> dict:
    from codetta.core.engine import _open_raw  # same opening (and format sniffing) as the editor

    engine.load_metadata(path)  # validates the path and format
    audio, format_name = _open_raw(path)
    system, entries = raw_tags(audio, format_name)
    return {"format": format_name, "system": system, "entries": entries}
