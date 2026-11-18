"""Failure-case and edge-case tests: files must never be damaged.

Every test that expects an error also checks the original file is
byte-for-byte unchanged and no temp files are left behind.
"""

import base64
import hashlib
import os
import shutil
import subprocess

import mutagen
import struct
from mutagen.apev2 import BINARY as APE_BINARY, APEValue
from mutagen.asf import ASFByteArrayAttribute
import pytest
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3
from mutagen.mp4 import MP4, MP4Cover

from codetta.core.engine import MetadataEngine, MetadataError, UnsupportedFormatError
from tests.conftest import EXPECTED_TAGS, FIXTURES_DIR, SAMPLE_FILES

IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
HAS_FFMPEG = shutil.which("ffmpeg") is not None

# A tiny but valid 1x1 PNG, used as cover art.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def engine():
    return MetadataEngine()


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_untouched(path, before):
    assert sha256(path) == before, "original file was modified"
    leftovers = [p.name for p in path.parent.iterdir() if p.name.startswith(".codetta-")]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def decodes_cleanly(path) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stderr == ""


# --- Unicode and unusual values ------------------------------------------------

UNICODE_TAGS = {
    "title": ["Ünïcödé Sóng – “quoted” ✨🎧"],
    "artist": ["坂本龍一", "Björk", "Сергей"],
    "album": ["مرحبا (Arabic, right-to-left)"],
    "comment": ["Line one\nLine two\n\tTabbed"],
    "genre": ["J-Pop/シティポップ"],
}


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_unicode_values_round_trip(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_tags(path, UNICODE_TAGS)
    tags = MetadataEngine().load_metadata(path).tags
    for key, value in UNICODE_TAGS.items():
        assert tags[key] == value, f"{name}: {key}"


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_very_long_value_round_trips(engine, fixture_copy, name):
    long_text = "lyrics " * 5000  # ~35 KB
    path = fixture_copy(name)
    engine.update_tags(path, {"comment": long_text})
    assert engine.load_metadata(path).tags["comment"] == [long_text]


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_null_character_is_rejected(engine, fixture_copy, name):
    # Some formats use \0 to separate values, so it would silently split one
    # value into two. Refuse it instead.
    path = fixture_copy(name)
    before = sha256(path)
    with pytest.raises(MetadataError, match="null"):
        engine.update_tags(path, {"title": "bad\x00value"})
    assert_untouched(path, before)


@pytest.mark.parametrize(
    "filename",
    ["Café del Mar – 01.flac", "坂本龍一 - Merry Christmas.mp3", "emoji 🎵 track.m4a",
     "spaces   and 'quotes'.ogg", "#hash & ampersand.opus"],
)
def test_unicode_and_odd_filenames(engine, tmp_path, filename):
    sample = "sample" + os.path.splitext(filename)[1]
    path = tmp_path / filename
    shutil.copy2(FIXTURES_DIR / sample, path)

    engine.update_tags(path, {"title": "Works"})

    assert engine.load_metadata(path).tags["title"] == ["Works"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [filename]


# --- Cover art must survive tag edits ----------------------------------------------


ID3_EXTS = {".mp3", ".mp2", ".wav", ".aiff", ".dsf", ".tta"}


def _wm_picture(data):
    mime = "image/png".encode("utf-16-le") + b"\x00\x00"
    return struct.pack("<bI", 3, len(data)) + mime + b"\x00\x00" + data


def _add_cover(path):
    """Add a cover with each format's own API (not Codetta's)."""
    fmt = path.suffix.lower()
    if fmt == ".flac":
        audio = FLAC(path)
        pic = Picture()
        pic.type, pic.mime, pic.data = 3, "image/png", PNG_1X1
        audio.add_picture(pic)
        audio.save()
    elif fmt in ID3_EXTS:
        audio = mutagen.File(path)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Cover", data=PNG_1X1))
        audio.save()
    elif fmt in (".m4a", ".m4b"):
        audio = MP4(path)
        audio["covr"] = [MP4Cover(PNG_1X1, imageformat=MP4Cover.FORMAT_PNG)]
        audio.save()
    elif fmt == ".wv":
        audio = mutagen.File(path)
        audio.tags["Cover Art (Front)"] = APEValue(b"cover.png\x00" + PNG_1X1, APE_BINARY)
        audio.save()
    elif fmt == ".wma":
        audio = mutagen.File(path)
        audio.tags["WM/Picture"] = [ASFByteArrayAttribute(_wm_picture(PNG_1X1))]
        audio.save()
    else:  # Ogg family: a base64 picture block in a Vorbis comment
        audio = mutagen.File(path)
        pic = Picture()
        pic.type, pic.mime, pic.data = 3, "image/png", PNG_1X1
        audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
        audio.save()


def _cover_bytes(path):
    fmt = path.suffix.lower()
    if fmt == ".flac":
        return [p.data for p in FLAC(path).pictures]
    if fmt in ID3_EXTS:
        tags = mutagen.File(path).tags
        return [f.data for f in tags.getall("APIC")] if tags is not None else []
    if fmt in (".m4a", ".m4b"):
        return [bytes(c) for c in MP4(path).tags.get("covr", [])]
    if fmt == ".wv":
        item = (mutagen.File(path).tags or {}).get("Cover Art (Front)")
        return [bytes(item.value).partition(b"\x00")[2]] if item else []
    if fmt == ".wma":
        return [bytes(a.value)[len(_wm_picture(b"")):] for a in mutagen.File(path).tags.get("WM/Picture", [])]
    audio = mutagen.File(path)
    return [
        Picture(base64.b64decode(v)).data for v in audio.get("metadata_block_picture", [])
    ]


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_cover_art_survives_tag_edits(engine, fixture_copy, name):
    path = fixture_copy(name)
    _add_cover(path)
    assert _cover_bytes(path) == [PNG_1X1]

    engine.update_tags(path, {"title": "New", "comment": "c", "genre": None})

    assert _cover_bytes(path) == [PNG_1X1]


@pytest.mark.parametrize("name", ["sample.ogg", "sample.opus"])
def test_embedded_cover_is_not_shown_as_a_text_tag(engine, fixture_copy, name):
    # OGG/Opus store cover art as a huge base64 "tag"; it isn't a text tag
    # and must not show up (or be editable) as one.
    path = fixture_copy(name)
    _add_cover(path)
    tags = engine.load_metadata(path).tags
    assert "metadata_block_picture" not in tags
    assert tags["title"] == ["Test Track"]


@pytest.mark.parametrize("key", ["metadata_block_picture", "coverart", "METADATA_BLOCK_PICTURE"])
def test_cover_art_fields_cannot_be_written_as_text(engine, fixture_copy, key):
    path = fixture_copy("sample.ogg")
    before = sha256(path)
    with pytest.raises(MetadataError, match="cover art"):
        engine.update_tags(path, {key: "not an image"})
    assert_untouched(path, before)


# --- Links (common in homelab libraries) ---------------------------------------------


def test_editing_through_a_symlink_edits_the_real_file(engine, tmp_path):
    real_dir = tmp_path / "storage"
    real_dir.mkdir()
    real = real_dir / "song.flac"
    shutil.copy2(FIXTURES_DIR / "sample.flac", real)
    link = tmp_path / "library-link.flac"
    link.symlink_to(real)

    engine.update_tags(link, {"title": "Via Link"})

    assert link.is_symlink(), "the symlink was replaced by a regular file"
    assert engine.load_metadata(real).tags["title"] == ["Via Link"]
    assert engine.load_metadata(link).tags["title"] == ["Via Link"]
    assert sorted(p.name for p in real_dir.iterdir()) == ["song.flac"]


def test_hard_linked_copy_is_left_untouched(engine, tmp_path):
    """e.g. a torrent client seeding the same file the library hard-links to.

    Writing tags in place would change the seeding copy too (breaking the
    torrent). Codetta writes a new file instead, so the other link keeps the
    original bytes.
    """
    seeding = tmp_path / "downloads" / "song.flac"
    seeding.parent.mkdir()
    shutil.copy2(FIXTURES_DIR / "sample.flac", seeding)
    library = tmp_path / "song.flac"
    os.link(seeding, library)
    before = sha256(seeding)

    engine.update_tags(library, {"title": "Library Copy"})

    assert engine.load_metadata(library).tags["title"] == ["Library Copy"]
    assert sha256(seeding) == before


# --- Permissions ------------------------------------------------------------------------


@pytest.mark.skipif(IS_ROOT, reason="root ignores file permissions")
def test_read_only_folder_is_refused_cleanly(engine, tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    path = folder / "song.flac"
    shutil.copy2(FIXTURES_DIR / "sample.flac", path)
    before = sha256(path)
    folder.chmod(0o555)  # file is writable, but no new files can be created here
    try:
        with pytest.raises(MetadataError, match="folder"):
            engine.update_tags(path, {"title": "Changed"})
        assert_untouched(path, before)
    finally:
        folder.chmod(0o755)


@pytest.mark.skipif(IS_ROOT, reason="root ignores file permissions")
def test_unreadable_file_raises_metadata_error(engine, fixture_copy):
    path = fixture_copy("sample.flac")
    path.chmod(0o000)
    try:
        with pytest.raises(MetadataError):
            engine.load_metadata(path)
    finally:
        path.chmod(0o644)


# --- Damaged and disguised files ---------------------------------------------------------


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_empty_file_is_rejected(engine, tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"")
    with pytest.raises(MetadataError):
        engine.load_metadata(path)
    with pytest.raises(MetadataError):
        engine.update_tags(path, {"title": "x"})
    assert path.read_bytes() == b""


@pytest.mark.parametrize("name", SAMPLE_FILES)
@pytest.mark.parametrize("keep", [0.1, 0.5, 0.9])
def test_truncated_audio_is_never_made_worse(engine, fixture_copy, name, keep):
    """A partially downloaded file: either the edit works, or nothing changes."""
    path = fixture_copy(name)
    data = path.read_bytes()
    path.write_bytes(data[: int(len(data) * keep)])
    before = sha256(path)

    try:
        engine.update_tags(path, {"title": "Changed"})
    except MetadataError:
        assert_untouched(path, before)
    else:
        assert engine.load_metadata(path).tags["title"] == ["Changed"]


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_random_garbage_with_audio_extension(engine, tmp_path, name):
    path = tmp_path / name
    path.write_bytes(os.urandom(4096))
    before = sha256(path)
    with pytest.raises(MetadataError):
        engine.update_tags(path, {"title": "x"})
    assert_untouched(path, before)


def test_mislabelled_file_is_detected_by_content(engine, tmp_path):
    # An MP3 that was renamed to .flac.
    path = tmp_path / "actually-an-mp3.flac"
    shutil.copy2(FIXTURES_DIR / "sample.mp3", path)

    meta = engine.load_metadata(path)
    assert meta.format == "mp3"
    engine.update_tags(path, {"title": "Still Works"})
    assert engine.load_metadata(path).tags["title"] == ["Still Works"]


@pytest.mark.parametrize("ext", [".aac", ".ape", ".mpc", ".txt", ".jpg", ""])
def test_unsupported_extensions(engine, tmp_path, ext):
    path = tmp_path / f"file{ext}"
    shutil.copy2(FIXTURES_DIR / "sample.flac", path)  # real audio inside, wrong type
    with pytest.raises(UnsupportedFormatError):
        engine.load_metadata(path)


# --- Interrupted writes ---------------------------------------------------------------------


def test_disk_full_while_copying(engine, fixture_copy, monkeypatch):
    path = fixture_copy("sample.flac")
    before = sha256(path)

    def disk_full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("codetta.core.engine.shutil.copy2", disk_full)

    with pytest.raises(MetadataError, match="No space left"):
        engine.update_tags(path, {"title": "Changed"})
    assert_untouched(path, before)


def test_ctrl_c_mid_write_leaves_original_and_cleans_up(engine, fixture_copy, monkeypatch):
    path = fixture_copy("sample.flac")
    before = sha256(path)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(MetadataEngine, "_verify_tags", interrupted)

    with pytest.raises(KeyboardInterrupt):
        engine.update_tags(path, {"title": "Changed"})
    assert_untouched(path, before)


# --- Repeated edits ----------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_many_edits_in_a_row_stay_healthy(engine, fixture_copy, name):
    """Simulate heavy use: 25 edits, growing and shrinking the tags."""
    path = fixture_copy(name)
    for i in range(25):
        engine.update_tags(path, {"title": f"Edit {i}", "comment": "x" * (i * 200) or None})

    meta = engine.load_metadata(path)
    assert meta.tags["title"] == ["Edit 24"]
    assert meta.duration == pytest.approx(1.0, abs=0.1)
    for key in ("artist", "album", "tracknumber"):
        assert meta.tags[key] == EXPECTED_TAGS[key]
    assert decodes_cleanly(path)


# --- Worldwide text ---------------------------------------------------------------------

WORLD_TAGS = {
    "title": ["夜に駆ける"],                                    # Japanese
    "artist": ["ए. आर. रहमान", "Ben&Ben", "아이유"],            # Hindi (Devanagari), Tagalog/Filipino band, Korean
    "album": ["Tyler, The Creator — CALL ME IF YOU GET LOST"],  # commas are fine
    "albumartist": ["Tyler, The Creator"],
    "genre": ["Pinoy Pop", "เพลงไทย", "粤语流行"],               # Thai, Cantonese
    "comment": ["Salamat po! Maraming salamat. 🙏🏽 👨‍👩‍👧 🇵🇭"],  # Tagalog + emoji incl. skin tone, ZWJ family, flag
    "composer": ["فيروز"],                                      # Arabic (right-to-left)
    "mood": ["😌 Chill"],
    "label": ["Café Records"],                            # decomposed accent (NFD) kept exactly
}


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_worldwide_text_round_trips_exactly(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_tags(path, WORLD_TAGS)
    tags = MetadataEngine().load_metadata(path).tags
    for key, value in WORLD_TAGS.items():
        assert tags[key] == value, f"{name}: {key}"


def test_non_utf8_file_names_are_skipped_not_fatal(tmp_path):
    from codetta.core.library import Library

    root = tmp_path / "music"
    root.mkdir()
    shutil.copy2(FIXTURES_DIR / "sample.flac", root / "good.flac")
    bad = os.fsdecode(b"caf\xe9 (latin-1).flac")  # an old Windows-style name
    shutil.copy2(FIXTURES_DIR / "sample.flac", root / bad)
    (root / os.fsdecode(b"Disc \xe9")).mkdir()

    listing = Library(root).list_folder("")
    assert listing.files == ["good.flac"]
    assert listing.folders == []
    assert listing.skipped == 2


def test_sorting_ignores_case_and_accents_and_odd_digits():
    from codetta.core.library import natural_key

    names = ["Zeta", "éclair", "Eagle", "10 b", "2 b", "²", "Ångström", "apple", "١٠ arabic digits", "٢ arabic digits"]
    assert sorted(names, key=natural_key) == [
        # Arabic-Indic digits are real numbers (٢ = 2, ١٠ = 10); ties sort by the rest of the name.
        "٢ arabic digits", "2 b", "١٠ arabic digits", "10 b", "²", "Ångström", "apple", "Eagle", "éclair", "Zeta",
    ]


def test_simultaneous_saves_to_one_file_both_land(engine, fixture_copy):
    """Two devices saving different fields at the same moment: neither edit is lost."""
    import threading

    path = fixture_copy("sample.flac")
    barrier = threading.Barrier(8)
    errors = []

    def save(i):
        barrier.wait()
        try:
            engine.update_tags(path, {f"custom{i}": f"value {i}"})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    tags = engine.load_metadata(path).tags
    assert all(tags.get(f"custom{i}") == [f"value {i}"] for i in range(8)), tags


def test_organize_never_overwrites_a_file_that_appears_after_the_preview(tmp_path):
    """Between previewing and applying, another program saves a file at the
    destination: the move is refused and both files survive untouched."""
    from codetta.core.organize import DEFAULT_PATTERN, Source, apply_moves, plan_moves

    root = tmp_path / "music"
    (root / "in").mkdir(parents=True)
    (root / "in" / "a.flac").write_bytes(b"mine")
    tags = {"albumartist": ["A"], "album": ["B"], "title": ["C"], "tracknumber": ["1"]}
    moves = plan_moves(root, [Source("in/a.flac", tags)], DEFAULT_PATTERN)
    (root / "A" / "B").mkdir(parents=True)
    (root / "A" / "B" / "01 C.flac").write_bytes(b"theirs")
    result = apply_moves(root, moves)[0]
    assert not result.ok
    assert (root / "in" / "a.flac").read_bytes() == b"mine" and (root / "A" / "B" / "01 C.flac").read_bytes() == b"theirs"
