"""Tests for album art (coda.core.artwork + MetadataEngine artwork methods)."""

import hashlib
import shutil
import subprocess

import pytest

from coda.core.activity import ActivityLog
from coda.core.artwork import ArtworkError, parse_image
from coda.core.engine import MetadataEngine, MetadataError
from tests.conftest import EXPECTED_TAGS, FIXTURES_DIR, SAMPLE_FILES

JPEG = (FIXTURES_DIR / "cover.jpg").read_bytes()
PNG = (FIXTURES_DIR / "cover.png").read_bytes()


@pytest.fixture
def engine():
    return MetadataEngine()


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- parse_image ----------------------------------------------------------------------


def test_parse_jpeg_size():
    art = parse_image(JPEG)
    assert (art.mime, art.width, art.height) == ("image/jpeg", 64, 48)


def test_parse_png_size():
    art = parse_image(PNG)
    assert (art.mime, art.width, art.height) == ("image/png", 32, 32)


@pytest.mark.parametrize("data", [b"", b"GIF89a....", b"<svg></svg>", b"\x00" * 100])
def test_parse_rejects_non_images(data):
    with pytest.raises(ArtworkError):
        parse_image(data)


def test_parse_rejects_huge_images():
    with pytest.raises(ArtworkError, match="too large"):
        parse_image(b"\xff\xd8\xff" + b"\x00" * (21 * 1024 * 1024))


# --- Engine: read / add / replace / remove ---------------------------------------------


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_no_art_by_default(engine, fixture_copy, name):
    assert engine.read_artwork(fixture_copy(name)) is None


@pytest.mark.parametrize("name", SAMPLE_FILES)
@pytest.mark.parametrize("image", [JPEG, PNG], ids=["jpeg", "png"])
def test_add_art_to_every_format(engine, fixture_copy, name, image):
    path = fixture_copy(name)

    engine.update_artwork(path, image)

    art = MetadataEngine().read_artwork(path)
    assert art is not None
    assert art.data == image
    assert art.mime == parse_image(image).mime


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_replace_art_leaves_a_single_picture(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_artwork(path, JPEG)
    engine.update_artwork(path, PNG)
    assert engine.read_artwork(path).data == PNG


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_remove_art(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_artwork(path, JPEG)
    engine.update_artwork(path, None)
    assert engine.read_artwork(path) is None


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_art_changes_do_not_touch_tags(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_artwork(path, JPEG)
    tags = engine.load_metadata(path).tags
    for key, value in EXPECTED_TAGS.items():
        assert tags[key] == value
    # And the picture never leaks into the text tags (OGG/Opus store it as one).
    assert "metadata_block_picture" not in tags


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_tag_edits_keep_art(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_artwork(path, JPEG)
    engine.update_tags(path, {"title": "New", "genre": None})
    assert engine.read_artwork(path).data == JPEG


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_file_still_decodes_with_art(engine, fixture_copy, name):
    path = fixture_copy(name)
    engine.update_artwork(path, JPEG)
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0 and result.stderr == ""


def test_invalid_image_leaves_file_untouched(engine, fixture_copy):
    path = fixture_copy("sample.flac")
    before = sha256(path)
    with pytest.raises(MetadataError, match="JPEG or PNG"):
        engine.update_artwork(path, b"GIF89a not allowed")
    assert sha256(path) == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["sample.flac"]


def test_art_write_failure_leaves_file_untouched(engine, fixture_copy, monkeypatch):
    path = fixture_copy("sample.mp3")
    before = sha256(path)
    monkeypatch.setattr("coda.core.engine.os.replace", lambda *a: (_ for _ in ()).throw(OSError("disk gone")))
    with pytest.raises(MetadataError, match="disk gone"):
        engine.update_artwork(path, JPEG)
    assert sha256(path) == before


def test_art_through_symlink_edits_real_file(engine, tmp_path):
    real = tmp_path / "real.flac"
    shutil.copy2(FIXTURES_DIR / "sample.flac", real)
    link = tmp_path / "link.flac"
    link.symlink_to(real)
    engine.update_artwork(link, JPEG)
    assert link.is_symlink()
    assert engine.read_artwork(real).data == JPEG


# --- Activity log ------------------------------------------------------------------------


def test_activity_log_newest_first_and_after_id(tmp_path):
    log = ActivityLog(tmp_path / "activity.jsonl")
    a = log.add("edit", "first")
    b = log.add("art", "second", ok=False, errors=[{"path": "x", "error": "nope"}])
    assert [e["message"] for e in log.recent()] == ["second", "first"]
    assert [e["id"] for e in log.recent(after_id=a["id"])] == [b["id"]]


def test_activity_log_survives_restart(tmp_path):
    file = tmp_path / "activity.jsonl"
    log = ActivityLog(file)
    log.add("edit", "one")
    log.add("edit", "two")
    reloaded = ActivityLog(file)
    assert [e["message"] for e in reloaded.recent()] == ["two", "one"]
    assert reloaded.add("edit", "three")["id"] == 3  # ids keep counting


def test_activity_log_skips_corrupt_lines_and_trims(tmp_path):
    file = tmp_path / "activity.jsonl"
    log = ActivityLog(file, keep=3)
    for i in range(10):
        log.add("edit", f"e{i}")
    with open(file, "a") as f:
        f.write("{half a line")
    reloaded = ActivityLog(file, keep=3)
    assert [e["message"] for e in reloaded.recent()] == ["e9", "e8", "e7"]
    assert len(file.read_text().splitlines()) == 3  # rewritten smaller


def test_activity_log_without_file():
    log = ActivityLog(None)
    log.add("edit", "in memory only")
    assert log.recent()[0]["message"] == "in memory only"
