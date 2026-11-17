"""Tests for MetadataEngine."""

import hashlib

import pytest

from coda.core.engine import (
    MetadataEngine,
    MetadataError,
    TrackMetadata,
    UnsupportedFormatError,
)
from tests.conftest import EXPECTED_TAGS, SAMPLE_FILES


@pytest.fixture
def engine():
    return MetadataEngine()


# --- load_metadata: reading -------------------------------------------------


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_reads_known_tags_from_every_format(engine, fixture_copy, name):
    meta = engine.load_metadata(fixture_copy(name))

    assert isinstance(meta, TrackMetadata)
    for key, value in EXPECTED_TAGS.items():
        assert meta.tags.get(key) == value, f"{name}: tag '{key}'"


@pytest.mark.parametrize(
    ("name", "expected_format"),
    [
        ("sample.flac", "flac"),
        ("sample.mp3", "mp3"),
        ("sample.m4a", "m4a"),
        ("sample.ogg", "ogg"),
        ("sample.opus", "opus"),
    ],
)
def test_detects_format(engine, fixture_copy, name, expected_format):
    assert engine.load_metadata(fixture_copy(name)).format == expected_format


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_reads_audio_properties(engine, fixture_copy, name):
    meta = engine.load_metadata(fixture_copy(name))

    assert meta.duration == pytest.approx(1.0, abs=0.1)
    assert meta.sample_rate in (44100, 48000)  # Opus always reports 48 kHz
    assert meta.channels == 1


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_reading_never_modifies_the_file(engine, fixture_copy, name):
    path = fixture_copy(name)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    engine.load_metadata(path)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_tag_names_are_lowercase(engine, fixture_copy):
    meta = engine.load_metadata(fixture_copy("sample.flac"))
    assert all(key == key.lower() for key in meta.tags)


def test_untagged_file_returns_empty_tags(engine, fixture_copy):
    meta = engine.load_metadata(fixture_copy("untagged.flac"))
    assert meta.tags == {}
    assert meta.format == "flac"


def test_accepts_string_paths(engine, fixture_copy):
    meta = engine.load_metadata(str(fixture_copy("sample.mp3")))
    assert meta.tags["title"] == ["Test Track"]


def test_uppercase_extension_is_supported(engine, fixture_copy):
    path = fixture_copy("sample.flac")
    upper = path.rename(path.with_suffix(".FLAC"))
    assert engine.load_metadata(upper).format == "flac"


# --- load_metadata: errors --------------------------------------------------


def test_missing_file_raises(engine, tmp_path):
    with pytest.raises(FileNotFoundError):
        engine.load_metadata(tmp_path / "nope.flac")


def test_directory_raises(engine, tmp_path):
    with pytest.raises(FileNotFoundError):
        engine.load_metadata(tmp_path)


def test_unsupported_extension_raises(engine, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("not audio")
    with pytest.raises(UnsupportedFormatError):
        engine.load_metadata(path)


def test_garbage_with_audio_extension_raises_metadata_error(engine, tmp_path):
    path = tmp_path / "broken.flac"
    path.write_bytes(b"this is definitely not a flac file" * 10)
    with pytest.raises(MetadataError):
        engine.load_metadata(path)


def test_truncated_file_raises_metadata_error(engine, fixture_copy):
    path = fixture_copy("sample.flac")
    path.write_bytes(path.read_bytes()[:20])  # chop it off mid-header
    with pytest.raises(MetadataError):
        engine.load_metadata(path)
