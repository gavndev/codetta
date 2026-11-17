"""The music library on disk: safe path handling and folder listing.

Everything the web UI asks for is a path *relative to the music folder*
(e.g. ``"Artist/Album/01 - Song.flac"``). ``Library.resolve`` turns that into
a real path and refuses anything that would escape the music folder, such as
``"../../etc/passwd"`` or an absolute path.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from coda.core.engine import SUPPORTED_EXTENSIONS


class LibraryPathError(ValueError):
    """A requested path is invalid or outside the music folder."""


@dataclass
class FolderListing:
    path: str  # relative to the library root, "" for the root itself
    folders: list[str] = field(default_factory=list)  # relative paths
    files: list[str] = field(default_factory=list)  # relative paths of audio files


class Library:
    def __init__(self, root: str | Path) -> None:
        # Normalise without resolving symlinks: a library that links to music
        # on other disks is normal, and the engine follows links when writing.
        self.root = Path(os.path.abspath(root))

    def exists(self) -> bool:
        return self.root.is_dir()

    def resolve(self, relative: str) -> Path:
        """Turn a library-relative path into a real path, safely."""
        if "\x00" in relative or "\\" in relative:
            raise LibraryPathError("Invalid characters in path")
        rel = PurePosixPath(relative.strip("/")) if relative.strip("/") else PurePosixPath()
        if rel.is_absolute() or any(part in ("..", ".") for part in rel.parts):
            raise LibraryPathError(f"Path must stay inside the music folder: {relative!r}")
        return self.root.joinpath(*rel.parts)

    def relative(self, path: Path) -> str:
        """The library-relative form of ``path`` (always with forward slashes)."""
        rel = PurePosixPath(Path(os.path.abspath(path)).relative_to(self.root)).as_posix()
        return "" if rel == "." else rel

    def list_folder(self, relative: str = "") -> FolderListing:
        """Subfolders and audio files directly inside one folder.

        Hidden entries (names starting with ".") are skipped, which includes
        Coda's own ``.coda-*`` temp files. Both lists are in natural order
        ("Disc 2" before "Disc 10").
        """
        folder = self.resolve(relative)
        if not folder.is_dir():
            raise FileNotFoundError(f"No such folder: {relative or '/'}")
        folders, files = [], []
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        folders.append(entry.name)
                    elif entry.is_file() and Path(entry.name).suffix.lower() in SUPPORTED_EXTENSIONS:
                        files.append(entry.name)
                except OSError:
                    continue  # e.g. a broken symlink
        prefix = self.relative(folder)
        join = (lambda name: f"{prefix}/{name}") if prefix else (lambda name: name)
        return FolderListing(
            path=prefix,
            folders=[join(n) for n in sorted(folders, key=natural_key)],
            files=[join(n) for n in sorted(files, key=natural_key)],
        )


def natural_key(text: str) -> list:
    """Sort key that orders numbers numerically: "2 song" < "10 song"."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]
