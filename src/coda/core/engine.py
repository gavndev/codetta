"""Core metadata engine: reads (and later writes) tags on audio files.

Every supported format is opened through mutagen's "easy" interface, so tags
come back with the same friendly names regardless of format (``title``,
``artist``, ``albumartist``, ``tracknumber``, ...) instead of raw ID3 frame
IDs like ``TIT2`` or MP4 atoms like ``\\xa9nam``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen.easyid3 import EasyID3  # noqa: F401  (registers EasyMP3's key map)
from mutagen.easymp4 import EasyMP4
from mutagen.flac import FLAC
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
