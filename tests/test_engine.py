"""Tests for MetadataEngine."""

import hashlib
import os
import shutil
import subprocess

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


# --- update_tags: writing ---------------------------------------------------


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_updates_tags_on_every_format(engine, fixture_copy, name):
    path = fixture_copy(name)

    result = engine.update_tags(path, {"title": "New Title", "album": "New Album"})

    assert result.tags["title"] == ["New Title"]
    assert result.tags["album"] == ["New Album"]
    # Re-read from disk with a fresh engine to be sure it really saved.
    reread = MetadataEngine().load_metadata(path)
    assert reread.tags["title"] == ["New Title"]
    assert reread.tags["album"] == ["New Album"]


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_untouched_tags_are_preserved(engine, fixture_copy, name):
    path = fixture_copy(name)

    result = engine.update_tags(path, {"title": "New Title"})

    for key, value in EXPECTED_TAGS.items():
        if key != "title":
            assert result.tags[key] == value, f"{name}: tag '{key}' changed"


@pytest.mark.parametrize("name", SAMPLE_FILES)
@pytest.mark.parametrize("empty", [None, "", []])
def test_empty_value_removes_tag(engine, fixture_copy, name, empty):
    path = fixture_copy(name)

    result = engine.update_tags(path, {"genre": empty})

    assert "genre" not in result.tags
    assert result.tags["title"] == ["Test Track"]


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_removing_missing_tag_is_harmless(engine, fixture_copy, name):
    result = engine.update_tags(fixture_copy(name), {"composer": None})
    assert "composer" not in result.tags


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_multiple_values(engine, fixture_copy, name):
    result = engine.update_tags(fixture_copy(name), {"artist": ["Artist A", "Artist B"]})
    assert result.tags["artist"] == ["Artist A", "Artist B"]


@pytest.mark.parametrize("name", SAMPLE_FILES)
@pytest.mark.parametrize("key", ["composer", "comment"])
def test_composer_and_comment_work_everywhere(engine, fixture_copy, name, key):
    # mutagen lacks these for some formats out of the box; the engine adds them.
    path = fixture_copy(name)

    engine.update_tags(path, {key: "Some Value"})
    assert engine.load_metadata(path).tags[key] == ["Some Value"]

    engine.update_tags(path, {key: None})
    assert key not in engine.load_metadata(path).tags


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_track_and_disc_numbers(engine, fixture_copy, name):
    result = engine.update_tags(
        fixture_copy(name), {"tracknumber": "7/10", "discnumber": "2"}
    )
    assert result.tags["tracknumber"] == ["7/10"]
    assert result.tags["discnumber"] == ["2"]


def test_mixed_case_keys_are_normalized(engine, fixture_copy):
    result = engine.update_tags(fixture_copy("sample.flac"), {"TITLE": "Shouty"})
    assert result.tags["title"] == ["Shouty"]


def test_tags_can_be_added_to_untagged_file(engine, fixture_copy):
    result = engine.update_tags(
        fixture_copy("untagged.flac"), {"title": "Fresh", "artist": "Someone"}
    )
    assert result.tags == {"artist": ["Someone"], "title": ["Fresh"]}


def test_empty_changes_leave_file_alone(engine, fixture_copy):
    path = fixture_copy("sample.mp3")
    before = sha256(path)

    engine.update_tags(path, {})

    assert sha256(path) == before


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_no_temp_files_left_behind(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_tags(path, {"title": "New Title"})
    assert sorted(p.name for p in path.parent.iterdir()) == [name]


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_audio_properties_survive_a_write(engine, fixture_copy, name):
    path = fixture_copy(name)
    before = engine.load_metadata(path)

    after = engine.update_tags(path, {"title": "New Title"})

    assert after.format == before.format
    assert after.duration == pytest.approx(before.duration, abs=0.01)
    assert after.sample_rate == before.sample_rate
    assert after.channels == before.channels


def test_file_permissions_are_preserved(engine, fixture_copy):
    path = fixture_copy("sample.flac")
    path.chmod(0o640)

    engine.update_tags(path, {"title": "New Title"})

    assert path.stat().st_mode & 0o777 == 0o640


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_file_still_decodes_after_write(engine, fixture_copy, name):
    """The strongest 'not corrupted' check: a real decoder plays the whole file."""
    path = fixture_copy(name)
    engine.update_tags(path, {"title": "New Title", "comment": "Hello", "artist": ["A", "B"]})

    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""


# --- update_tags: failures must leave the original untouched ----------------


@pytest.mark.parametrize("name", ["sample.mp3", "sample.m4a"])
def test_invalid_tag_name_raises_and_leaves_file_untouched(engine, fixture_copy, name):
    # MP3 and M4A only allow a fixed list of tag names.
    path = fixture_copy(name)
    before = sha256(path)

    with pytest.raises(MetadataError, match="Invalid tag"):
        engine.update_tags(path, {"title": "Changed", "not_a_real_tag": "x"})

    assert sha256(path) == before
    assert sorted(p.name for p in path.parent.iterdir()) == [name]


def test_invalid_vorbis_key_raises_and_leaves_file_untouched(engine, fixture_copy):
    path = fixture_copy("sample.flac")
    before = sha256(path)

    with pytest.raises(MetadataError):
        engine.update_tags(path, {"bad=key": "x"})  # '=' is illegal in Vorbis keys

    assert sha256(path) == before


def test_freeform_tags_allowed_on_vorbis_formats(engine, fixture_copy):
    # FLAC/OGG/Opus accept any tag name, which is handy for custom fields.
    result = engine.update_tags(fixture_copy("sample.flac"), {"mood": "Chill"})
    assert result.tags["mood"] == ["Chill"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_read_only_file_is_refused(engine, fixture_copy):
    path = fixture_copy("sample.flac")
    path.chmod(0o444)
    before = sha256(path)

    with pytest.raises(MetadataError, match="read-only"):
        engine.update_tags(path, {"title": "Changed"})

    assert sha256(path) == before


def test_write_to_missing_file_raises(engine, tmp_path):
    with pytest.raises(FileNotFoundError):
        engine.update_tags(tmp_path / "gone.flac", {"title": "x"})


def test_failed_verification_leaves_file_untouched(engine, fixture_copy, monkeypatch):
    """If the re-read after writing doesn't match, nothing is swapped in."""
    path = fixture_copy("sample.flac")
    before = sha256(path)
    real_write = MetadataEngine._write_tags

    def sabotaged_write(self, temp, fmt, changes):
        real_write(self, temp, fmt, {"title": ["Something Else"]})

    monkeypatch.setattr(MetadataEngine, "_write_tags", sabotaged_write)

    with pytest.raises(MetadataError, match="did not save correctly"):
        engine.update_tags(path, {"title": "Wanted"})

    assert sha256(path) == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["sample.flac"]


def test_failure_during_swap_leaves_file_untouched(engine, fixture_copy, monkeypatch):
    """Simulate the disk failing at the very last step."""
    path = fixture_copy("sample.flac")
    before = sha256(path)

    def failing_replace(src, dst):
        raise OSError("disk on fire")

    monkeypatch.setattr("coda.core.engine.os.replace", failing_replace)

    with pytest.raises(MetadataError, match="disk on fire"):
        engine.update_tags(path, {"title": "Changed"})

    assert sha256(path) == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["sample.flac"]
