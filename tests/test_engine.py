"""Tests for MetadataEngine."""

import hashlib
import os
import shutil
import subprocess

import pytest

from codetta.core.engine import (
    MetadataEngine,
    MetadataError,
    TrackMetadata,
    UnsupportedFormatError,
)
from tests.conftest import EXPECTED_TAGS, SAMPLE_FILES, SAMPLE_RATES


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
    assert meta.sample_rate == SAMPLE_RATES.get(name, 44100)
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

    monkeypatch.setattr("codetta.core.engine.os.replace", failing_replace)

    with pytest.raises(MetadataError, match="disk on fire"):
        engine.update_tags(path, {"title": "Changed"})

    assert sha256(path) == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["sample.flac"]


# --- Shared tag vocabulary (see codetta/core/tagmap.py) ------------------------

# Tags Navidrome / OpenSubsonic clients use, with a sample value for each.
NAVIDROME_TAGS = {
    "artists": ["Artist A", "Artist B"],
    "albumartists": ["Artist A", "Artist B"],
    "originaldate": ["2019-03-01"],
    "discsubtitle": ["The B-Sides"],
    "compilation": ["1"],
    "releasetype": ["single"],
    "releasestatus": ["official"],
    "label": ["Indie Records"],
    "catalognumber": ["IR-001"],
    "barcode": ["0123456789012"],
    "isrc": ["USABC1234567"],
    "media": ["Digital Media"],
    "mood": ["Chill"],
    "bpm": ["120"],
    "composer": ["Comp Oser"],
    "lyricist": ["Lyric Writer"],
    "conductor": ["Con Ductor"],
    "arranger": ["Arr Anger"],
    "remixer": ["Re Mixer"],
    "releasecountry": ["GB"],
    "engineer": ["Engi Neer"],
    "mixer": ["Mix Er"],
    "producer": ["Pro Ducer", "Co Producer"],
    "djmixer": ["DJ Someone"],
    "comment": ["Ripped from SoundCloud"],
    "language": ["eng"],
    "copyright": ["2024 Indie Records"],
}


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_navidrome_tags_round_trip_on_every_format(engine, fixture_copy, name):
    path = fixture_copy(name)

    engine.update_tags(path, NAVIDROME_TAGS)
    tags = MetadataEngine().load_metadata(path).tags

    for key, value in NAVIDROME_TAGS.items():
        assert tags.get(key) == value, f"{name}: tag '{key}'"
    # The original tags are still there too.
    for key, value in EXPECTED_TAGS.items():
        assert tags.get(key) == value, f"{name}: tag '{key}'"


def test_mp3_credits_land_where_navidrome_and_picard_read_them(engine, fixture_copy):
    # mutagen's own "arranger" is TPE4, which Picard and Navidrome read as the remixer.
    from mutagen.id3 import ID3

    path = fixture_copy("sample.mp3")
    engine.update_tags(path, {"arranger": "Arr Anger", "remixer": "Re Mixer"})
    id3 = ID3(path)
    assert ["arranger", "Arr Anger"] in [list(p) for p in id3["TIPL"].people]
    assert id3["TPE4"].text == ["Re Mixer"]


def test_m4a_release_country_uses_picards_atom_and_reads_the_old_one(engine, fixture_copy):
    from mutagen.mp4 import MP4

    path = fixture_copy("sample.m4a")
    old = "----:com.apple.iTunes:MusicBrainz Release Country"  # what older Codetta versions wrote
    a = MP4(path)
    a[old] = [b"FR"]
    a.save()
    assert engine.load_metadata(path).tags["releasecountry"] == ["FR"]
    engine.update_tags(path, {"releasecountry": "GB"})
    a = MP4(path)
    assert a["----:com.apple.iTunes:MusicBrainz Album Release Country"] == [b"GB"] and old not in a
    assert engine.load_metadata(path).tags["releasecountry"] == ["GB"]


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_each_credit_role_is_independent(engine, fixture_copy, name):
    # On MP3 these all share one TIPL frame; changing one must not touch others.
    path = fixture_copy(name)
    engine.update_tags(path, {"engineer": "E", "mixer": "M", "producer": "P"})

    tags = engine.update_tags(path, {"mixer": None}).tags

    assert tags["engineer"] == ["E"]
    assert tags["producer"] == ["P"]
    assert "mixer" not in tags


@pytest.mark.parametrize("name", ["sample.mp3", "sample.m4a"])
def test_aliases_are_not_duplicated(engine, fixture_copy, name):
    # e.g. on MP3 "label" and mutagen's "organization" are the same field.
    tags = engine.update_tags(fixture_copy(name), {"label": "L", "releasetype": "album"}).tags
    assert "organization" not in tags
    assert "musicbrainz_albumtype" not in tags


def test_m4a_compilation_rejects_non_boolean(engine, fixture_copy):
    path = fixture_copy("sample.m4a")
    before = sha256(path)
    with pytest.raises(MetadataError):
        engine.update_tags(path, {"compilation": "yes"})
    assert sha256(path) == before


@pytest.mark.parametrize(
    ("fmt", "key", "expected"),
    [
        ("flac", "anything_goes", True),
        ("ogg", "mood", True),
        ("opus", "bad=key", False),
        ("mp3", "mood", True),
        ("mp3", "engineer", True),
        ("mp3", "made_up_tag", False),
        ("m4a", "releasetype", True),
        ("m4a", "made_up_tag", False),
        ("wav", "title", True),
        ("aiff", "mood", True),
        ("wav", "made_up_tag", False),  # ID3 family: fixed vocabulary
        ("wavpack", "anything_goes", True),  # APEv2: free-form
        ("wavpack", "ID3", False),  # reserved APEv2 name
        ("wma", "anything_goes", True),  # ASF: free-form
        ("wma", "WM/Picture", False),  # technical attribute
        ("speex", "mood", True),
        ("aac", "title", False),
    ],
)
def test_is_tag_supported(fmt, key, expected):
    from codetta.core.engine import is_tag_supported

    assert is_tag_supported(fmt, key) is expected


# --- Sort and classical fields (0.2) -------------------------------------------------------------

CLASSICAL = {
    "work": "Symphony No. 5", "movementname": "Allegro con brio", "movement": "1", "movementtotal": "4",
    "showmovement": "1", "subtitle": "Live", "titlesort": "Sort Title", "artistsort": "Tester, Coda",
    "albumsort": "Album Sort", "albumartistsort": "Collective, Coda", "composersort": "Beethoven, Ludwig van",
}


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_sort_and_classical_fields_round_trip(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_tags(path, CLASSICAL)
    tags = engine.load_metadata(path).tags
    assert {k: tags.get(k) for k in CLASSICAL} == {k: [v] for k, v in CLASSICAL.items()}
    for key, value in EXPECTED_TAGS.items():  # nothing else disturbed
        assert tags[key] == value


def test_classical_fields_use_standard_storage(engine, fixture_copy):
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3
    from mutagen.mp4 import MP4

    paths = {name: fixture_copy(name) for name in ("sample.mp3", "sample.m4a", "sample.flac")}
    for path in paths.values():
        engine.update_tags(path, CLASSICAL)
    mp3 = ID3(paths["sample.mp3"])
    assert mp3["MVIN"].text == ["1/4"] and mp3["MVNM"].text == ["Allegro con brio"]
    assert mp3["TXXX:WORK"].text == ["Symphony No. 5"] and mp3["TIT3"].text == ["Live"]
    m4a = MP4(paths["sample.m4a"])
    assert m4a["\xa9mvi"] == [1] and m4a["\xa9mvc"] == [4] and m4a["\xa9wrk"] == ["Symphony No. 5"]
    flac = FLAC(paths["sample.flac"])
    assert flac["MOVEMENTNAME"] == ["Allegro con brio"] and flac["MOVEMENT"] == ["1"] and flac["WORK"] == ["Symphony No. 5"]


def test_movement_number_and_total_are_independent_in_id3(engine, fixture_copy):
    path = fixture_copy("sample.mp3")
    engine.update_tags(path, {"movement": "2", "movementtotal": "5"})
    engine.update_tags(path, {"movement": "3"})
    assert engine.load_metadata(path).tags["movementtotal"] == ["5"]
    engine.update_tags(path, {"movementtotal": None})
    tags = engine.load_metadata(path).tags
    assert tags["movement"] == ["3"] and "movementtotal" not in tags


# --- Lyrics (0.2) ----------------------------------------------------------------------------------

LRC = "[00:12.00] First line; with a semicolon\n[00:15.50] Second line, ünïcödé 夜\n[00:19.20] Third line"


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_lyrics_round_trip_exactly(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_tags(path, {"lyrics": LRC})
    assert engine.load_metadata(path).tags["lyrics"] == [LRC]
    engine.update_tags(path, {"lyrics": None})
    assert "lyrics" not in engine.load_metadata(path).tags


def test_lyrics_use_standard_storage(engine, fixture_copy):
    import mutagen
    from mutagen.id3 import ID3
    from mutagen.mp4 import MP4

    paths = {n: fixture_copy(n) for n in ("sample.mp3", "sample.m4a", "sample.wma", "sample.flac")}
    for p in paths.values():
        engine.update_tags(p, {"lyrics": LRC})
    assert ID3(paths["sample.mp3"]).getall("USLT")[0].text == LRC
    assert MP4(paths["sample.m4a"])["\xa9lyr"] == [LRC]
    assert str(mutagen.File(paths["sample.wma"]).tags["WM/Lyrics"][0]) == LRC
    assert mutagen.File(paths["sample.flac"])["LYRICS"] == [LRC]
