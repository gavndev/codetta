"""Tag Loadouts: saved sets of tags you can apply to many files at once.

A loadout is a JSON file in the loadouts folder (``config/loadouts/`` by
default), for example ``config/loadouts/album-folder.json``::

    {
      "name": "Album Folder",
      "description": "Turn a folder of loose files into a tagged album.",
      "tags": {
        "title": "{filename_title}",
        "album": "{folder}",
        "tracknumber": "{track}/{tracktotal}",
        "artist": "",
        "genre": ["Hip-Hop", "Lo-Fi"]
      }
    }

Values can be a single string or a list (for multi-value tags). Blank values
are ignored when applying, so a loadout can list fields to fill in later.

Placeholders are filled in per file:

    {filename}        the file name without its extension
    {filename_title}  the file name tidied into a title ("01_my_song" -> "my song")
    {folder}          the name of the folder the file is in
    {track}           the file's position in the batch (1, 2, 3, ...)
    {tracktotal}      how many files are in the batch

Applying a loadout:

* ``mode="fill"`` (the default) only sets tags the file doesn't already have,
  so it's safe to run over partly tagged files.
* ``mode="overwrite"`` replaces existing values.
* Tags a format can't store (rare after ``tagmap``) are skipped for that file
  and reported, rather than failing the whole batch.
* ``dry_run=True`` reports what *would* change without touching any files.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from coda.core.engine import (
    SUPPORTED_EXTENSIONS,
    MetadataEngine,
    MetadataError,
    TagValue,
    is_tag_supported,
)

PLACEHOLDERS = frozenset({"filename", "filename_title", "folder", "track", "tracktotal"})
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


class LoadoutError(Exception):
    """A loadout is invalid, missing, or could not be saved."""


class ApplyMode(StrEnum):
    FILL = "fill"  # only set tags the file doesn't already have
    OVERWRITE = "overwrite"  # replace existing values


@dataclass
class Loadout:
    name: str
    tags: dict[str, list[str]] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name or not slugify(self.name):
            raise LoadoutError("A loadout needs a name containing letters or numbers")
        self.tags = {key.strip().lower(): _as_list(value) for key, value in self.tags.items()}
        for key, values in self.tags.items():
            if not key:
                raise LoadoutError(f"Loadout '{self.name}' has a blank tag name")
            for value in values:
                unknown = set(_PLACEHOLDER_RE.findall(value)) - PLACEHOLDERS
                if unknown:
                    raise LoadoutError(
                        f"Loadout '{self.name}', tag '{key}': unknown placeholder "
                        f"{{{sorted(unknown)[0]}}}. Available: "
                        + ", ".join(f"{{{p}}}" for p in sorted(PLACEHOLDERS))
                    )

    @property
    def slug(self) -> str:
        return slugify(self.name)

    @classmethod
    def from_dict(cls, data: object) -> Loadout:
        if not isinstance(data, dict):
            raise LoadoutError("A loadout must be a JSON object")
        name, tags = data.get("name"), data.get("tags", {})
        description = data.get("description", "")
        if not isinstance(name, str):
            raise LoadoutError("A loadout needs a \"name\" string")
        if not isinstance(tags, dict):
            raise LoadoutError(f"Loadout '{name}': \"tags\" must be an object")
        if not isinstance(description, str):
            raise LoadoutError(f"Loadout '{name}': \"description\" must be a string")
        for key, value in tags.items():
            ok = isinstance(value, str) or (
                isinstance(value, list) and all(isinstance(v, str) for v in value)
            )
            if not ok:
                raise LoadoutError(
                    f"Loadout '{name}', tag '{key}': value must be a string or list of strings"
                )
        return cls(name=name, tags=tags, description=description)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            # Single values are saved as plain strings to keep the JSON readable.
            "tags": {k: v[0] if len(v) == 1 else v for k, v in self.tags.items()},
        }


class LoadoutStore:
    """Loads and saves loadouts as one JSON file each in ``directory``."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def list(self) -> list[Loadout]:
        """All valid loadouts, sorted by name. Broken files are skipped."""
        if not self.directory.is_dir():
            return []
        loadouts = []
        for path in self.directory.glob("*.json"):
            if path.name.startswith("."):
                continue  # e.g. a leftover temp file from an interrupted save
            try:
                loadouts.append(self._read(path))
            except LoadoutError:
                continue  # one bad hand-edited file shouldn't hide the rest
        return sorted(loadouts, key=lambda lo: lo.name.lower())

    def get(self, name: str) -> Loadout:
        path = self._path_for(name)
        if not path.is_file():
            raise LoadoutError(f"No loadout named '{name}'")
        return self._read(path)

    def save(self, loadout: Loadout) -> Path:
        """Save (or replace) a loadout. Returns the file it was written to."""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path_for(loadout.name)
        text = json.dumps(loadout.to_dict(), indent=2, ensure_ascii=False) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=".coda-", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return path

    def delete(self, name: str) -> None:
        path = self._path_for(name)
        if not path.is_file():
            raise LoadoutError(f"No loadout named '{name}'")
        path.unlink()

    def install_defaults(self) -> list[Loadout]:
        """Save the starter loadouts that don't exist yet. Returns those added."""
        added = []
        for loadout in default_loadouts():
            if not self._path_for(loadout.name).exists():
                self.save(loadout)
                added.append(loadout)
        return added

    def _path_for(self, name: str) -> Path:
        slug = slugify(name)
        if not slug:
            raise LoadoutError(f"Invalid loadout name: '{name}'")
        return self.directory / f"{slug}.json"

    def _read(self, path: Path) -> Loadout:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoadoutError(f"Could not read loadout {path.name}: {exc}") from exc
        return Loadout.from_dict(data)


# --- Applying loadouts -------------------------------------------------------


@dataclass
class FileResult:
    """What applying a loadout did (or would do) to one file."""

    path: Path
    applied: dict[str, list[str]] = field(default_factory=dict)
    kept_existing: list[str] = field(default_factory=list)  # fill mode: already had a value
    unsupported: list[str] = field(default_factory=list)  # this format can't store it
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def apply_loadout(
    engine: MetadataEngine,
    loadout: Loadout,
    paths: list[str | Path],
    mode: ApplyMode | str = ApplyMode.FILL,
    dry_run: bool = False,
) -> list[FileResult]:
    """Apply ``loadout`` to ``paths``, in the order given.

    ``{track}`` and ``{tracktotal}`` come from that order. One file failing
    doesn't stop the others; check each result's ``error``.
    """
    mode = ApplyMode(mode)
    paths = [Path(p) for p in paths]
    return [
        _apply_one(engine, loadout, path, mode, dry_run, track=i, tracktotal=len(paths))
        for i, path in enumerate(paths, start=1)
    ]


def apply_loadout_to_folder(
    engine: MetadataEngine,
    loadout: Loadout,
    folder: str | Path,
    mode: ApplyMode | str = ApplyMode.FILL,
    recursive: bool = False,
    dry_run: bool = False,
) -> list[FileResult]:
    """Apply ``loadout`` to every audio file in ``folder`` (e.g. one album).

    Files are numbered in natural name order ("2 song" before "10 song").
    With ``recursive=True``, each subfolder is numbered separately, so a
    folder per disc or per album gets its own track numbers.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"No such folder: {folder}")
    groups = _audio_files_by_folder(folder, recursive)
    results = []
    for files in groups:
        results.extend(apply_loadout(engine, loadout, files, mode, dry_run))
    return results


def _apply_one(
    engine: MetadataEngine,
    loadout: Loadout,
    path: Path,
    mode: ApplyMode,
    dry_run: bool,
    track: int,
    tracktotal: int,
) -> FileResult:
    result = FileResult(path=path)
    try:
        current = engine.load_metadata(path)
        context = {
            "filename": path.stem,
            "filename_title": filename_to_title(path.stem),
            "folder": path.parent.name,
            "track": str(track),
            "tracktotal": str(tracktotal),
        }
        changes: dict[str, TagValue] = {}
        for key, values in loadout.tags.items():
            filled = [_fill_placeholders(v, context) for v in values]
            filled = [v for v in filled if v.strip()]
            if not filled:
                continue  # blank in the loadout: nothing to apply
            if not is_tag_supported(current.format, key):
                result.unsupported.append(key)
            elif mode is ApplyMode.FILL and current.tags.get(key):
                result.kept_existing.append(key)
            elif current.tags.get(key) != filled:
                changes[key] = filled
        result.applied = {k: list(v) for k, v in changes.items()}
        if changes and not dry_run:
            engine.update_tags(path, changes)
    except (MetadataError, FileNotFoundError) as exc:
        result.applied = {}
        result.error = str(exc)
    return result


def _audio_files_by_folder(folder: Path, recursive: bool) -> list[list[Path]]:
    folders = [folder]
    if recursive:
        folders += sorted(
            (d for d in folder.rglob("*") if d.is_dir() and not _is_hidden(d, folder)),
            key=lambda d: _natural_key(str(d.relative_to(folder))),
        )
    groups = []
    for d in folders:
        files = sorted(
            (
                f
                for f in d.iterdir()
                if f.is_file()
                and not f.name.startswith(".")  # includes .coda-* temp files
                and f.suffix.lower() in SUPPORTED_EXTENSIONS
            ),
            key=lambda f: _natural_key(f.name),
        )
        if files:
            groups.append(files)
    return groups


# --- Helpers -------------------------------------------------------------------


def slugify(name: str) -> str:
    """"Album Folder!" -> "album-folder" (used as the file name)."""
    return re.sub(r"\W+", "-", name.lower()).strip("-_")


def filename_to_title(stem: str) -> str:
    """Tidy a file name into a usable title.

    Strips a leading track number and turns underscores into spaces:
    "01 - My Song" -> "My Song", "03_late_night" -> "late night".
    """
    title = stem.replace("_", " ")
    # A 1-3 digit number followed by a separator or space: "01 - ", "3. ", "07 ".
    # "2Pac" and "1979" are left alone.
    stripped = re.sub(r"^\s*\d{1,3}(?:\s*[-.)\]]\s*|\s+)(?=\S)", "", title, count=1)
    title = stripped if stripped.strip() else title  # "1979" stays "1979"
    return re.sub(r"\s+", " ", title).strip()


def _fill_placeholders(value: str, context: dict[str, str]) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: context.get(m.group(1), m.group(0)), value)


def _as_list(value: TagValue) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _natural_key(text: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def _is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


# --- Starter loadouts ----------------------------------------------------------


def default_loadouts() -> list[Loadout]:
    """Starter loadouts. Blank fields are reminders of what to fill in."""
    return [
        Loadout(
            name="Single",
            description=(
                "For a loose track (e.g. a SoundCloud download): makes it show up as "
                "its own single in Navidrome instead of under 'Unknown Album'."
            ),
            tags={
                "title": "{filename_title}",
                "album": "{filename_title}",
                "artist": "",
                "albumartist": "",
                "genre": "",
                "date": "",
                "tracknumber": "1/1",
                "discnumber": "1/1",
                "releasetype": "single",
                "media": "Digital Media",
                "comment": "",
            },
        ),
        Loadout(
            name="Album Folder",
            description=(
                "For a folder of untagged tracks: names the album after the folder "
                "and numbers the tracks in file-name order."
            ),
            tags={
                "title": "{filename_title}",
                "album": "{folder}",
                "artist": "",
                "albumartist": "",
                "genre": "",
                "date": "",
                "tracknumber": "{track}/{tracktotal}",
                "discnumber": "1/1",
                "releasetype": "album",
                "media": "Digital Media",
            },
        ),
        Loadout(
            name="Full Credits",
            description=(
                "The extra detail Navidrome / OpenSubsonic clients can show: credits, "
                "mood, label and release info. Apply on top of Single or Album Folder."
            ),
            tags={
                "artists": "",
                "albumartists": "",
                "composer": "",
                "lyricist": "",
                "producer": "",
                "engineer": "",
                "mixer": "",
                "mood": "",
                "bpm": "",
                "label": "",
                "catalognumber": "",
                "releasestatus": "official",
                "originaldate": "",
                "copyright": "",
                "language": "",
            },
        ),
    ]
