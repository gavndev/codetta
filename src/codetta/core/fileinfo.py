"""Get info: details about a file or folder beyond its tags (format, quality, size, dates)."""

from __future__ import annotations

import os
from pathlib import Path

from codetta.core.engine import SUPPORTED_EXTENSIONS, MetadataEngine, _open_raw
from codetta.core.artwork import read_picture
from codetta.core.tagmap import FIELDS, is_tag_supported

MAX_FOLDER_FILES = 20_000  # counting stops here, so a huge folder answers quickly


def _tag_kind(audio) -> str | None:
    """The kind of tag block the file carries, e.g. "ID3v2.4", "Vorbis comments", "MP4 atoms"."""
    tags = getattr(audio, "tags", None)
    if tags is None:
        return None
    name = type(tags).__name__
    if name.startswith("ID3"):
        version = getattr(tags, "version", None)
        return f"ID3v{version[0]}.{version[1]}" if version else "ID3"
    return {"VCFLACDict": "Vorbis comments", "VComment": "Vorbis comments", "OggVCommentDict": "Vorbis comments",
            "OggOpusVComment": "Vorbis comments", "OggFLACVComment": "Vorbis comments", "OggSpeexVComment": "Vorbis comments",
            "MP4Tags": "MP4 atoms", "APEv2": "APEv2", "ASFTags": "ASF attributes"}.get(name, name)


def _encoder(audio) -> str | None:
    """What made the file ("LAME 3.100", "Lavf62.3.100"...), when it says."""
    tags = getattr(audio, "tags", None)
    if not tags:
        return None
    for key in ("TSSE", "TENC", "©too", "encoder", "ENCODER", "Encoder", "WM/EncodingSettings", "WM/ToolName"):
        try:
            value = tags.get(key) if hasattr(tags, "get") else None
        except (KeyError, ValueError, TypeError):
            value = None
        if value:
            text = str(value[0] if isinstance(value, list) else value)
            if text.strip():
                return text.strip()[:120]
    return None


def file_info(engine: MetadataEngine, path: Path) -> dict:
    """What Get info shows for one audio file."""
    st = path.stat()
    meta = engine.load_metadata(path)
    audio, format_name = _open_raw(path)
    info = audio.info
    art = read_picture(audio, format_name)
    codec = getattr(info, "codec_description", None) or getattr(info, "codec", None)
    return {
        "kind": "file",
        "name": path.name,
        "format": meta.format,
        "codec": str(codec) if codec else None,
        "duration": meta.duration,
        "bitrate": meta.bitrate,
        "sample_rate": meta.sample_rate,
        "bits_per_sample": getattr(info, "bits_per_sample", None) or None,
        "channels": meta.channels,
        "size": st.st_size,
        "modified": int(st.st_mtime),
        "tag_kind": _tag_kind(audio),
        "tag_count": sum(len(v) for v in meta.tags.values()),
        "art": {"mime": art.mime, "width": art.width, "height": art.height, "size": len(art.data)} if art else None,
        "encoder": _encoder(audio),
        "fields_supported": sum(is_tag_supported(meta.format or "", f.key) for f in FIELDS),
        "fields_total": len(FIELDS),
        "fields_unsupported": [f.label for f in FIELDS if not is_tag_supported(meta.format or "", f.key)],
        "on_disk": str(path),
    }


def folder_info(path: Path) -> dict:
    """What Get info shows for a folder (counted up to MAX_FOLDER_FILES files)."""
    files = audio = folders = size = 0
    capped = False
    for dirpath, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        folders += len(dirs)
        for n in names:
            if n.startswith("."):
                continue
            files += 1
            audio += Path(n).suffix.lower() in SUPPORTED_EXTENSIONS
            try:
                size += (Path(dirpath) / n).stat().st_size
            except OSError:
                pass
            if files >= MAX_FOLDER_FILES:
                capped = True
                break
        if capped:
            break
    return {"kind": "folder", "name": path.name, "files": files, "audio": audio, "folders": folders,
            "size": size, "capped": capped, "modified": int(path.stat().st_mtime), "on_disk": str(path)}
