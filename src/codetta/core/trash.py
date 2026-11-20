"""Recently deleted: what Delete (and cleared downloads, undone imports) set aside, kept for 30 days in
the config folder as ``deleted/<YYYYmmdd-HHMMSS>/<original path>``.

From here things can be put back, or (carefully) deleted for good: the only place Codetta truly
erases files. Erasing only ever touches paths inside the deleted folder, checked on every file.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

KEEP_DAYS = 30


def _stamp_time(name: str) -> float | None:
    try:
        return datetime.strptime(name, "%Y%m%d-%H%M%S").timestamp()
    except ValueError:
        return None


def batches(root: Path) -> list[dict]:
    """Each deletion (newest first): when, what was there, how many files and how big."""
    out = []
    try:
        entries = sorted((e for e in root.iterdir() if e.is_dir() and _stamp_time(e.name)), key=lambda e: e.name, reverse=True)
    except OSError:
        return []
    for e in entries:
        files, size = [], 0
        for dirpath, _, names in os.walk(e):
            for n in names:
                p = Path(dirpath) / n
                try:
                    size += p.lstat().st_size
                except OSError:
                    continue
                files.append(p.relative_to(e).as_posix())
        if not files:
            continue
        files.sort()
        top = os.path.commonpath(files) if len(files) > 1 else files[0]
        when = _stamp_time(e.name) or 0
        out.append({"id": e.name, "deleted": int(when), "expires": int(when + KEEP_DAYS * 86400),
                    "what": top or files[0].split("/")[0], "files": len(files), "size": size, "sample": files[:50]})
    return out


def batch_dir(root: Path, batch_id: str) -> Path:
    """The folder of one deletion, refusing anything that isn't one (no "..", no other names)."""
    if not _stamp_time(batch_id) or "/" in batch_id or "\\" in batch_id:
        raise ValueError("That isn't one of the recently deleted items")
    d = root / batch_id
    if not d.is_dir() or d.resolve().parent != root.resolve():
        raise ValueError("That item isn't in Recently deleted any more")
    return d


def count_files(d: Path) -> int:
    return sum(len(names) for _, _, names in os.walk(d))


def erase(root: Path, batch_id: str) -> int:
    """Delete one deletion for good. Returns how many files went."""
    d = batch_dir(root, batch_id)
    n = count_files(d)
    if d.is_symlink() or not d.resolve().is_relative_to(root.resolve()):
        raise ValueError("Refusing to delete outside Recently deleted")
    shutil.rmtree(d)
    return n
