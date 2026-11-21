"""Zip up a folder: a ZIP archive streamed straight to the browser, nothing written to disk.

Music is already compressed, so files are stored as they are (no deflating): the archive
is about the size of the folder and comes out as fast as the disk reads. ZIP64 kicks in
by itself for big folders and files (over 4 GB), which every modern unzipper reads.

Symbolic links inside the folder are left out, so a zip only ever holds what's really in
that folder. Hidden files (".DS_Store", "._cover.jpg") are left out too.
"""

from __future__ import annotations

import os
import stat
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

CHUNK = 1024 * 1024
ZIP64_LIMIT = (1 << 31) - 1  # past this size zipfile needs to know up front that it's ZIP64


class _Pipe:
    """A write-only, unseekable file for zipfile: whatever it writes is collected for the stream."""

    def __init__(self) -> None:
        self.parts: list[bytes] = []
        self.offset = 0

    def write(self, data) -> int:
        b = bytes(data)
        self.parts.append(b)
        self.offset += len(b)
        return len(b)

    def tell(self) -> int:  # zipfile asks where it is; it never seeks
        return self.offset

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        out = b"".join(self.parts)
        self.parts.clear()
        return out


def folder_files(folder: Path) -> list[tuple[Path, str]]:
    """(file, name inside the zip) for everything in the folder, sorted, links and hidden files left out.
    Names start with the folder's own name, so unzipping gives back one folder."""
    out = []
    base = folder.name or "Music"
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(root, d)))
        rel_root = os.path.relpath(root, folder)
        for name in sorted(files):
            if name.startswith("."):
                continue
            p = Path(root) / name
            try:
                st = p.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue  # links, sockets...
            arc = "/".join(x for x in (base, "" if rel_root == "." else rel_root.replace(os.sep, "/"), name) if x)
            out.append((p, arc))
    return out


def zip_size(files: list[tuple[Path, str]]) -> int:
    total = 0
    for p, _ in files:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def zip_stream(files: list[tuple[Path, str]], chunk: int = CHUNK) -> Iterator[bytes]:
    """The ZIP archive of these files, a piece at a time. A file that can't be read is skipped."""
    pipe = _Pipe()
    with zipfile.ZipFile(pipe, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for path, arc in files:
            try:
                f = path.open("rb")
            except OSError:
                continue
            with f:
                st = os.fstat(f.fileno())
                info = zipfile.ZipInfo(arc, date_time=time.localtime(max(st.st_mtime, 315532800))[:6])
                info.compress_type = zipfile.ZIP_STORED
                info.file_size = st.st_size
                info.external_attr = 0o644 << 16
                with zf.open(info, "w", force_zip64=st.st_size > ZIP64_LIMIT) as out:
                    while block := f.read(chunk):
                        out.write(block)
                        if pipe.parts:
                            yield pipe.take()
            data = pipe.take()
            if data:
                yield data
    data = pipe.take()  # the archive's table of contents
    if data:
        yield data
