"""Core metadata engine: reads and writes tags on audio files.

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
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen.easymp4 import EasyMP4
from mutagen.flac import FLAC
from mutagen.mp3 import MP3, EasyMP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

# Importing tagmap registers the extra tag names (mood, label, engineer, ...)
# so every format shares one vocabulary.
from codetta.core.artwork import Artwork, ArtworkError, parse_image, read_picture, write_picture
from codetta.core.tagmap import HIDDEN_ALIASES, is_tag_supported

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "Artwork",
    "MetadataEngine",
    "MetadataError",
    "TagValue",
    "TrackMetadata",
    "UnsupportedFormatError",
    "is_tag_supported",
]

# File extensions Codetta will open. Anything else is rejected up front.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".flac", ".mp3", ".m4a", ".ogg", ".opus"})

# The mutagen class detected from the file's contents -> Codetta's format name.
# Detection is by content (see _sniff_format), so a mislabelled file is still
# identified correctly.
_FORMAT_NAMES: dict[type, str] = {
    FLAC: "flac",
    EasyMP3: "mp3",
    EasyMP4: "m4a",
    OggVorbis: "ogg",
    OggOpus: "opus",
}

# OGG/Opus (and some old files) store cover art inside a text field as a big
# base64 blob. It isn't a text tag, so it's hidden from ``tags`` and can't be
# overwritten as text. (Other formats keep pictures outside the tag list.)
COVER_ART_KEYS = frozenset({"metadata_block_picture", "coverart", "coverartmime"})


# A tag value as callers may pass it: one string, several strings, or None.
# None, "" and [] all mean "remove this tag".
TagValue = str | Iterable[str] | None


# One lock per file (by real path): two saves to the same file at the same
# moment (two devices, a double-tap) take turns, and the second one starts from
# the first one's result instead of overwriting it.
_file_locks: dict[str, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = os.path.realpath(path)
    with _file_locks_guard:
        lock = _file_locks.get(key)
        if lock is None:
            if len(_file_locks) > 5000:  # forget idle locks so this can't grow forever
                for k in [k for k, v in _file_locks.items() if not v.locked()]:
                    del _file_locks[k]
            lock = _file_locks[key] = threading.Lock()
        return lock


class MetadataError(Exception):
    """A file could not be read or written (e.g. it is corrupt or truncated)."""


class UnsupportedFormatError(MetadataError):
    """The file is not one of the audio formats Codetta handles."""


@dataclass(frozen=True)
class TrackMetadata:
    """Everything Codetta knows about one audio file."""

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

        audio = _open_audio(path)
        format_name = _FORMAT_NAMES[type(audio)]

        tags = {
            key.lower(): [str(value) for value in values]
            for key, values in (audio.tags or {}).items()
            if key.lower() not in COVER_ART_KEYS
        }
        for old_name in HIDDEN_ALIASES.get(format_name, {}):
            tags.pop(old_name, None)
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
        _check_changes(normalized)
        if not normalized:
            return original

        def write_and_verify(temp: Path) -> None:
            self._write_tags(temp, original.format, normalized)
            self._verify_tags(temp, normalized)

        self._safe_write(path, write_and_verify)
        return self.load_metadata(path)

    # --- Album art --------------------------------------------------------------

    def read_artwork(self, path: str | Path) -> Artwork | None:
        """The file's front cover (or first picture), or None if it has none."""
        path = Path(path)
        self.load_metadata(path)  # validates path and format
        audio, format_name = _open_raw(path)
        return read_picture(audio, format_name)

    def update_artwork(self, path: str | Path, image: bytes | None) -> Artwork | None:
        """Embed ``image`` (JPEG or PNG bytes) as the album art, or remove all
        embedded pictures when ``image`` is None. Tags are left untouched.

        Uses the same temp-copy -> verify -> atomic swap as ``update_tags``.
        """
        path = Path(path)
        try:
            art = parse_image(image) if image is not None else None
        except ArtworkError as exc:
            raise MetadataError(str(exc)) from exc
        original = self.load_metadata(path)

        def write_and_verify(temp: Path) -> None:
            try:
                audio, format_name = _open_raw(temp)
                write_picture(audio, format_name, art)
                audio.save()
                check, _ = _open_raw(temp)
                after = read_picture(check, format_name)
            except (mutagen.MutagenError, ValueError, KeyError) as exc:
                raise MetadataError(f"Could not save album art to {path}: {exc}") from exc
            saved_ok = after is None if art is None else (after is not None and after.data == art.data)
            if not saved_ok:
                raise MetadataError("Album art did not save correctly")
            if self.load_metadata(temp).tags != original.tags:
                raise MetadataError("Saving album art unexpectedly changed the tags")

        self._safe_write(path, write_and_verify)
        return art

    # --- Safe writing -------------------------------------------------------------

    def _safe_write(self, path: Path, write_and_verify: Callable[[Path], None]) -> None:
        """Run ``write_and_verify`` on a temp copy of ``path``, then swap it in.

        The original is never edited in place. If anything fails, it is left
        untouched and the copy is deleted.
        """
        with _lock_for(path):
            self._safe_write_locked(path, write_and_verify)

    def _safe_write_locked(self, path: Path, write_and_verify: Callable[[Path], None]) -> None:
        # If ``path`` is a symlink, edit the file it points to. Otherwise the
        # swap below would replace the link itself with a regular file.
        target = Path(os.path.realpath(path))
        if not os.access(target, os.W_OK):
            raise MetadataError(f"File is read-only: {path}")

        temp_path = None
        try:
            try:
                fd, temp_name = tempfile.mkstemp(
                    prefix=".codetta-", suffix=target.suffix, dir=target.parent
                )
            except OSError as exc:
                raise MetadataError(f"Cannot write to folder {target.parent}: {exc}") from exc
            os.close(fd)
            temp_path = Path(temp_name)
            shutil.copy2(target, temp_path)  # also copies permissions
            _copy_ownership(target, temp_path)

            write_and_verify(temp_path)

            with open(temp_path, "rb") as f:
                os.fsync(f.fileno())  # make sure it's on disk before the swap
            # Atomic: the original is never half-written. This also gives the
            # file a new identity, so any hard-linked copy (e.g. a torrent
            # client still seeding it) keeps the original bytes.
            os.replace(temp_path, target)
            temp_path = None
        except OSError as exc:
            raise MetadataError(f"Could not write to {path}: {exc}") from exc
        finally:
            if temp_path is not None:
                with contextlib.suppress(OSError):
                    temp_path.unlink()

    def _write_tags(self, path: Path, format_name: str, changes: dict[str, list[str]]) -> None:
        try:
            audio = _open_audio(path)
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


def _open_audio(path: Path):
    """Open ``path`` with mutagen, choosing the format from the file's bytes.

    mutagen on its own trusts the extension over the contents, so an MP3
    renamed to ``.flac`` would fail to open. Sniffing the header first avoids
    that, and also guarantees only Codetta's five formats are ever tried.
    """
    try:
        kind = _sniff_format(path)
        options = [kind] if kind else list(_FORMAT_NAMES)
        audio = mutagen.File(path, options=options)
    except (mutagen.MutagenError, OSError) as exc:
        raise MetadataError(f"Could not read {path}: {exc}") from exc
    if audio is None or type(audio) not in _FORMAT_NAMES:
        raise UnsupportedFormatError(f"Not a recognised audio file: {path}")
    return audio


def _open_raw(path: Path):
    """Open ``path`` with mutagen's full (non-"easy") classes, for pictures.

    Returns (audio, format_name).
    """
    audio = _open_audio(path)
    format_name = _FORMAT_NAMES[type(audio)]
    raw_class = {"mp3": MP3, "m4a": MP4}.get(format_name)
    if raw_class is not None:
        try:
            audio = raw_class(path)
        except (mutagen.MutagenError, OSError) as exc:
            raise MetadataError(f"Could not read {path}: {exc}") from exc
    return audio, format_name


def _sniff_format(path: Path) -> type | None:
    """Identify the audio format from the first bytes of the file, or None."""
    with open(path, "rb") as f:
        head = f.read(64)
        if head.startswith(b"ID3") and len(head) >= 10:
            # Skip an ID3 tag (normally MP3, occasionally stuck on a FLAC).
            size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
            f.seek(10 + size)
            after = f.read(4)
            return FLAC if after == b"fLaC" else EasyMP3
    if head.startswith(b"fLaC"):
        return FLAC
    if head.startswith(b"OggS"):
        if b"OpusHead" in head:
            return OggOpus
        if b"\x01vorbis" in head:
            return OggVorbis
        return None
    if head[4:8] == b"ftyp":
        return EasyMP4
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        return EasyMP3  # MPEG audio frame with no ID3 tag
    return None


def _check_changes(changes: dict[str, list[str]]) -> None:
    """Reject changes that can't be stored safely, before touching the file."""
    for key, values in changes.items():
        if key in COVER_ART_KEYS:
            raise MetadataError(f"'{key}' holds cover art and can't be edited as text")
        if any("\x00" in v for v in values):
            raise MetadataError(f"Tag '{key}' contains a null character, which can't be stored")


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

    Matters when Codetta runs as root in Docker: without this, edited files would
    end up owned by root instead of the user who owns the music library.
    """
    st = source.stat()
    with contextlib.suppress(PermissionError, AttributeError):
        os.chown(dest, st.st_uid, st.st_gid)
