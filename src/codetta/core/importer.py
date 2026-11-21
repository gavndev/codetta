"""Import: music you add from your computer or phone (a few files, or whole folders).

Files arrive one request each, streamed to disk (never held in memory), into one folder per import:
the inbox when there is one (so they're matched and filed like any new music), otherwise "Imported"
in the library (where Organize places them). Names and folders from the upload are cleaned into safe
names; nothing is ever overwritten; nothing can land outside the import's folder.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
from pathlib import Path

from codetta.core.engine import SUPPORTED_EXTENSIONS
from codetta.core.organize import MAX_COMPONENT_BYTES, safe_name

MAX_IMPORT_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB per file (hi-res albums are big; this isn't a backup tool)
WRITE_CHUNK = 4 * 1024 * 1024  # bytes handed to the disk at a time
MAX_DEPTH = 6  # folders inside an imported folder
BATCH_RE = re.compile(r"^[0-9A-Za-z-]{6,40}$")


class ImportError_(ValueError):
    """A request that can't be imported (bad name, too big...); the message is for people."""


def clean_parts(path: str) -> list[str]:
    """An uploaded file's relative path ("Album/CD1/01 Song.flac") as safe names, one per part.
    "..", ".", empty parts and leading separators are dropped, so the result always stays inside."""
    parts = [p for p in re.split(r"[\\/]+", path or "") if p not in ("", ".", "..")]
    if not parts:
        raise ImportError_("That file has no name")
    *folders, name = parts
    stem, ext = os.path.splitext(name)
    if not stem or len(ext) > 12 or not ext[1:].isalnum():  # ".flac" yes; ".hidden" or "x.tar gz" no
        stem, ext = name, ""
    # Long names are shortened before the extension, so "….flac" stays a music file.
    parts = [safe_name(p) for p in folders] + [safe_name(stem, MAX_COMPONENT_BYTES - len(ext.encode())) + ext]
    if len(parts) > MAX_DEPTH + 1:
        parts = parts[:MAX_DEPTH] + [parts[-1]]  # very deep folders are flattened, never refused
    return parts


def free_name(folder: Path, name: str) -> Path:
    """``folder/name``, or "name (2).ext", "name (3).ext"... if that's taken: never overwrites."""
    stem, ext = os.path.splitext(name)
    target = folder / name
    n = 2
    while os.path.lexists(target):
        target = folder / f"{stem} ({n}){ext}"
        n += 1
    return target


def _place(tmp: Path, target_dir: Path, name: str) -> Path:
    """Give a finished temporary file its real name, never replacing anything."""
    target = free_name(target_dir, name)
    try:
        os.link(tmp, target)  # fails rather than replacing a file that appeared meanwhile
        tmp.unlink()
    except FileExistsError:
        target = free_name(target_dir, name)
        os.rename(tmp, target)
    except OSError:  # no hard links on this filesystem (exFAT, some network shares)
        os.rename(tmp, target)
    return target


def _too_big(limit: int) -> ImportError_:
    return ImportError_(f"That file is bigger than {limit // (1024 * 1024 * 1024)} GB")


def receive(folder: Path, parts: list[str], chunks, limit: int = MAX_IMPORT_BYTES) -> Path:
    """Write one uploaded file (``chunks``: its bytes, a piece at a time) under ``folder``.
    Written to a hidden temporary name first and only given its real name when complete."""
    target_dir = folder.joinpath(*parts[:-1])
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = target_dir / f".codetta-import-{secrets.token_hex(6)}"
    size = 0
    try:
        with open(tmp, "xb") as out:
            for chunk in chunks:
                size += len(chunk)
                if size > limit:
                    raise _too_big(limit)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        return _place(tmp, target_dir, parts[-1])
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def receive_stream(folder: Path, parts: list[str], stream, limit: int = MAX_IMPORT_BYTES) -> Path:
    """Like ``receive``, reading an async stream (a web request's body)."""
    target_dir = folder.joinpath(*parts[:-1])
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = target_dir / f".codetta-import-{secrets.token_hex(6)}"
    size = 0
    # The disk work runs in a worker thread, a megabyte at a time: writing (and above all the
    # final fsync, which can take a second on a hard drive) must never hold up other requests.
    out = await asyncio.to_thread(open, tmp, "xb")
    try:
        try:
            pending: list[bytes] = []
            held = 0
            async for chunk in stream:
                size += len(chunk)
                if size > limit:
                    raise _too_big(limit)
                pending.append(chunk)
                held += len(chunk)
                if held >= WRITE_CHUNK:
                    await asyncio.to_thread(out.writelines, pending)
                    pending, held = [], 0
            if pending:
                await asyncio.to_thread(out.writelines, pending)
            await asyncio.to_thread(_flush_and_sync, out)
        finally:
            out.close()
        return await asyncio.to_thread(_place, tmp, target_dir, parts[-1])
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _flush_and_sync(f) -> None:
    f.flush()
    os.fsync(f.fileno())


def is_audio(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_EXTENSIONS
