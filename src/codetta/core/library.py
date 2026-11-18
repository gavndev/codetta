"""The music library on disk: safe path handling and folder listing.

Everything the web UI asks for is a path *relative to the music folder*
(e.g. ``"Artist/Album/01 - Song.flac"``). ``Library.resolve`` turns that into
a real path and refuses anything that would escape the music folder, such as
``"../../etc/passwd"`` or an absolute path.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from codetta.core.engine import SUPPORTED_EXTENSIONS


class LibraryPathError(ValueError):
    """A requested path is invalid or outside the music folder."""


@dataclass
class FolderListing:
    path: str  # relative to the library root, "" for the root itself
    folders: list[str] = field(default_factory=list)  # relative paths
    files: list[str] = field(default_factory=list)  # relative paths of audio files
    # Entries whose names aren't valid UTF-8 (e.g. from an old Windows zip).
    # They can't be shown or sent to the browser, so they're counted instead.
    skipped: int = 0


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
        Codetta's own ``.codetta-*`` temp files. Both lists are in natural order
        ("Disc 2" before "Disc 10").
        """
        folder = self.resolve(relative)
        if not folder.is_dir():
            raise FileNotFoundError(f"No such folder: {relative or '/'}")
        folders, files, skipped = [], [], 0
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if not _is_valid_text(entry.name):
                    skipped += 1
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
            skipped=skipped,
        )


class TooManyFilesError(LibraryPathError):
    """More audio files than one request may handle."""


def audio_files(library: Library, relative: str, recursive: bool, limit: int) -> list[str]:
    """Audio files in a folder (and its subfolders if ``recursive``), in natural
    order, hidden entries skipped. Raises TooManyFilesError past ``limit``."""
    out: list[str] = []
    pending = [library.list_folder(relative)]
    while pending:
        listing = pending.pop(0)
        out.extend(listing.files)
        if len(out) > limit:
            raise TooManyFilesError(f"That's more than {limit} files at once. Choose a smaller folder.")
        if recursive:
            pending.extend(library.list_folder(f) for f in listing.folders)
    return out


def count_contents(folder: Path) -> tuple[int, int] | None:
    """(subfolders, audio files) directly inside ``folder``, without reading
    any tags. None if the folder can't be read."""
    folders = files = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        folders += 1
                    elif entry.is_file() and Path(entry.name).suffix.lower() in SUPPORTED_EXTENSIONS:
                        files += 1
                except OSError:
                    continue
    except OSError:
        return None
    return folders, files


def _is_valid_text(name: str) -> bool:
    """False for file names that aren't valid UTF-8 (Python keeps those as
    "surrogate" characters, which can't be sent as JSON)."""
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _sort_text(text: str) -> str:
    """Case- and accent-insensitive form for sorting: "Éclair" sorts with "eclair"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def natural_key(text: str) -> list:
    """Sort key that orders numbers numerically ("2 song" < "10 song") and
    ignores case and accents. Works for any script."""
    # isdecimal (not isdigit): "²" counts as a digit but int() can't read it.
    return [(0, int(p), "") if p.isdecimal() else (1, 0, _sort_text(p)) for p in re.split(r"(\d+)", text)]
