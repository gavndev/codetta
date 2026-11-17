"""Core metadata engine: reads (and later writes) tags on audio files.

Every supported format is opened through mutagen's "easy" interface, so tags
come back with the same friendly names regardless of format (``title``,
``artist``, ``albumartist``, ``tracknumber``, ...) instead of raw ID3 frame
IDs like ``TIT2`` or MP4 atoms like ``\\xa9nam``.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.easymp4 import EasyMP4, EasyMP4Tags
from mutagen.flac import FLAC
from mutagen.id3 import COMM
from mutagen.mp3 import EasyMP3
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

# File extensions Coda will open. Anything else is rejected up front.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".flac", ".mp3", ".m4a", ".ogg", ".opus"})

# The mutagen class detected from the file's contents -> Coda's format name.
# Detection is by content, so a mislabelled file is still identified correctly.
_FORMAT_NAMES: dict[type, str] = {
    FLAC: "flac",
    EasyMP3: "mp3",
    EasyMP4: "m4a",
    OggVorbis: "ogg",
    OggOpus: "opus",
}


# A tag value as callers may pass it: one string, several strings, or None.
# None, "" and [] all mean "remove this tag".
TagValue = str | Iterable[str] | None


# --- Fill gaps in mutagen's "easy" tag names -------------------------------
# Out of the box, easy MP4 has no ``composer`` and easy ID3 (MP3) has no
# ``comment``. Both formats can store them, so register the names here so
# every format accepts the same common tags.

EasyMP4Tags.RegisterTextKey("composer", "\xa9wrt")


def _id3_comment_keys(id3) -> list[str]:
    # Plain user comments have an empty description; others (e.g. iTunes'
    # "iTunNORM" volume data) are left alone.
    return [k for k in id3.keys() if k.startswith("COMM:") and id3[k].desc == ""]


def _id3_comment_get(id3, key):
    values = [text for k in _id3_comment_keys(id3) for text in id3[k].text]
    if not values:
        raise KeyError(key)
    return values


def _id3_comment_set(id3, key, value):
    _id3_comment_delete(id3, key)
    id3.add(COMM(encoding=3, lang="eng", desc="", text=list(value)))


def _id3_comment_delete(id3, key):
    for k in _id3_comment_keys(id3):
        del id3[k]


EasyID3.RegisterKey("comment", _id3_comment_get, _id3_comment_set, _id3_comment_delete)


class MetadataError(Exception):
    """A file could not be read or written (e.g. it is corrupt or truncated)."""


class UnsupportedFormatError(MetadataError):
    """The file is not one of the audio formats Coda handles."""


@dataclass(frozen=True)
class TrackMetadata:
    """Everything Coda knows about one audio file."""

    path: Path
    format: str
    # Tag name -> list of values. Lists because most formats allow a tag to
    # appear more than once (e.g. two ``artist`` entries).
    tags: dict[str, list[str]] = field(default_factory=dict)
    duration: float | None = None  # seconds
    bitrate: int | None = None  # bits per second
    sample_rate: int | None = None  # Hz
    channels: int | None = None


class MetadataEngine:
    """Reads and writes tags on audio files."""

    def load_metadata(self, path: str | Path) -> TrackMetadata:
        """Read the tags and audio properties of ``path``.

        This only reads; the file is never modified.

        Raises:
            FileNotFoundError: ``path`` does not exist or is not a file.
            UnsupportedFormatError: the file is not a supported audio format.
            MetadataError: the file looks supported but could not be parsed.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"No such audio file: {path}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise UnsupportedFormatError(f"Unsupported file type '{path.suffix}': {path}")

        try:
            audio = mutagen.File(path, easy=True)
        except mutagen.MutagenError as exc:
            raise MetadataError(f"Could not read {path}: {exc}") from exc

        format_name = _FORMAT_NAMES.get(type(audio)) if audio is not None else None
        if format_name is None:
            raise UnsupportedFormatError(f"Not a recognised audio file: {path}")

        tags = {
            key.lower(): [str(value) for value in values]
            for key, values in (audio.tags or {}).items()
        }
        info = audio.info
        sample_rate = getattr(info, "sample_rate", None)
        if format_name == "opus":
            # Opus always decodes at 48 kHz; mutagen doesn't expose a rate for it.
            sample_rate = 48000
        return TrackMetadata(
            path=path,
            format=format_name,
            tags=dict(sorted(tags.items())),
            duration=getattr(info, "length", None) or None,
            bitrate=getattr(info, "bitrate", None) or None,
            sample_rate=sample_rate or None,
            channels=getattr(info, "channels", None) or None,
        )

    def update_tags(self, path: str | Path, changes: Mapping[str, TagValue]) -> TrackMetadata:
        """Apply ``changes`` to the tags of ``path`` and return the new metadata.

        ``changes`` maps tag names to new values. Tags not mentioned are left
        as they are. A value of ``None``, ``""`` or ``[]`` removes that tag::

            engine.update_tags("song.flac", {"title": "New Title",
                                             "artist": ["A", "B"],
                                             "comment": None})

        Safety: the original file is never edited in place. The changes are
        written to a temporary copy in the same folder, the copy is re-read to
        confirm the tags stuck, and only then does it replace the original in a
        single atomic step. If anything fails, the original is left untouched
        and the copy is deleted.

        Raises:
            FileNotFoundError: ``path`` does not exist or is not a file.
            UnsupportedFormatError: the file is not a supported audio format.
            MetadataError: the file is read-only, a tag name isn't valid for
                this format, or the write could not be completed or verified.
        """
        path = Path(path)
        original = self.load_metadata(path)  # validates path and format
        normalized = {key.lower(): _normalize_value(value) for key, value in changes.items()}
        if not normalized:
            return original
        if not os.access(path, os.W_OK):
            raise MetadataError(f"File is read-only: {path}")

        temp_path = None
        try:
            try:
                fd, temp_name = tempfile.mkstemp(
                    prefix=".coda-", suffix=path.suffix, dir=path.parent
                )
            except OSError as exc:
                raise MetadataError(f"Cannot write to folder {path.parent}: {exc}") from exc
            os.close(fd)
            temp_path = Path(temp_name)
            shutil.copy2(path, temp_path)  # also copies permissions
            _copy_ownership(path, temp_path)

            self._write_tags(temp_path, original.format, normalized)
            self._verify_tags(temp_path, normalized)

            with open(temp_path, "rb") as f:
                os.fsync(f.fileno())  # make sure it's on disk before the swap
            os.replace(temp_path, path)  # atomic: original is never half-written
            temp_path = None
        except OSError as exc:
            raise MetadataError(f"Could not write tags to {path}: {exc}") from exc
        finally:
            if temp_path is not None:
                with contextlib.suppress(OSError):
                    temp_path.unlink()

        return self.load_metadata(path)

    def _write_tags(self, path: Path, format_name: str, changes: dict[str, list[str]]) -> None:
        try:
            audio = mutagen.File(path, easy=True)
            if audio.tags is None:
                audio.add_tags()
            for key, values in changes.items():
                if values:
                    audio[key] = values
                elif key in audio:
                    del audio[key]
            audio.save()
        except (KeyError, ValueError) as exc:
            raise MetadataError(
                f"Invalid tag for a {format_name} file: {exc}"
            ) from exc
        except mutagen.MutagenError as exc:
            raise MetadataError(f"Could not save tags to {path}: {exc}") from exc

    def _verify_tags(self, path: Path, changes: dict[str, list[str]]) -> None:
        written = self.load_metadata(path).tags
        for key, values in changes.items():
            if written.get(key, []) != values:
                raise MetadataError(
                    f"Tag '{key}' did not save correctly "
                    f"(wanted {values!r}, file has {written.get(key, [])!r})"
                )


def _normalize_value(value: TagValue) -> list[str]:
    """Turn a caller's tag value into a list of strings ([] means remove)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    values = [str(v) for v in value]
    return [] if all(v == "" for v in values) else values


def _copy_ownership(source: Path, dest: Path) -> None:
    """Give ``dest`` the same owner/group as ``source`` where permitted.

    Matters when Coda runs as root in Docker: without this, edited files would
    end up owned by root instead of the user who owns the music library.
    """
    st = source.stat()
    with contextlib.suppress(PermissionError, AttributeError):
        os.chown(dest, st.st_uid, st.st_gid)
