"""Failure-case and edge-case tests: files must never be damaged.

Every test that expects an error also checks the original file is
byte-for-byte unchanged and no temp files are left behind.
"""

import base64
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

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


# --- Batch tools: find & replace, folder rename ------------------------------------------------------

import shutil as _shutil  # noqa: E402

from fastapi.testclient import TestClient as _TestClient  # noqa: E402

from codetta.web.app import Settings as _Settings, create_app as _create_app  # noqa: E402


@pytest.fixture
def batch_client(tmp_path):
    from codetta.core.engine import MetadataEngine
    music = tmp_path / "music"
    album = music / "Artist" / "Album"
    album.mkdir(parents=True)
    e = MetadataEngine()
    for i, title in enumerate(["Intro (Official Audio)", "Night ft. Zayn (official audio)", "Plain"], 1):
        _shutil.copy2(FIXTURES_DIR / "sample.flac", album / f"0{i}.flac")
        e.update_tags(album / f"0{i}.flac", {"title": title, "artist": "Artist"})
    (album / "cover.jpg").write_bytes(b"jpg")
    with _TestClient(_create_app(_Settings(music_dir=music, config_dir=tmp_path / "cfg", auth=False))) as c:
        yield c, music


def title(c, path):
    return c.get("/api/track", params={"path": path}).json()["tags"].get("title")


def test_find_replace_previews_then_writes_once_and_undoes(batch_client):
    c, _ = batch_client
    body = {"folder": "Artist/Album", "find": " (official audio)"}
    prev = c.post("/api/tracks/replace", json=body).json()
    assert prev["changing"] == 2 and title(c, "Artist/Album/01.flac") == ["Intro (Official Audio)"]  # preview only
    assert prev["preview"][0]["changes"][0] == {"key": "title", "old": "Intro (Official Audio)", "new": "Intro"}
    done = c.post("/api/tracks/replace", json={**body, "dry_run": False}).json()
    assert done["changed"] == 2 and title(c, "Artist/Album/02.flac") == ["Night ft. Zayn"]
    entry = c.get("/api/activity").json()[0]
    assert entry["message"].startswith("Find & replace") and entry["can_undo"]
    assert c.post(f"/api/activity/{entry['id']}/undo").json()["undone"] == 2
    assert title(c, "Artist/Album/02.flac") == ["Night ft. Zayn (official audio)"]


def test_find_replace_regex_and_case(batch_client):
    c, _ = batch_client
    r = c.post("/api/tracks/replace", json={"folder": "Artist/Album", "find": r"\bft\.\s*(\w+)", "replace": r"feat. \1",
                                            "regex": True, "dry_run": False}).json()
    assert r["changed"] == 1 and title(c, "Artist/Album/02.flac") == ["Night feat. Zayn (official audio)"]
    assert c.post("/api/tracks/replace", json={"folder": "Artist/Album", "find": "OFFICIAL", "match_case": True}).json()["changing"] == 0
    assert c.post("/api/tracks/replace", json={"folder": "Artist/Album", "find": "(", "regex": True}).status_code == 422
    assert c.post("/api/tracks/replace", json={"folder": "Artist/Album", "find": "x", "replace": r"\9", "regex": True}).status_code == 422


def test_rename_folder_moves_everything_and_undoes(batch_client):
    c, music = batch_client
    r = c.post("/api/folders/rename", json={"path": "Artist/Album", "name": "Album (2024)"}).json()
    assert r["path"] == "Artist/Album (2024)" and r["moved"] == 4  # three tracks and the cover
    assert not (music / "Artist" / "Album").exists() and (music / "Artist" / "Album (2024)" / "cover.jpg").exists()
    entry = c.get("/api/activity").json()[0]
    assert c.post(f"/api/activity/{entry['id']}/undo").json()["failed"] == 0
    assert (music / "Artist" / "Album" / "01.flac").exists() and not (music / "Artist" / "Album (2024)").exists()


def test_rename_folder_never_overwrites_and_stays_inside(batch_client):
    c, music = batch_client
    (music / "Artist" / "Taken").mkdir()
    assert c.post("/api/folders/rename", json={"path": "Artist/Album", "name": "Taken"}).status_code == 409
    assert (music / "Artist" / "Album" / "01.flac").exists()
    r = c.post("/api/folders/rename", json={"path": "Artist/Album", "name": "../../escape"}).json()
    assert r["path"].startswith("Artist/") and "/" not in r["path"][len("Artist/"):]  # the name is made safe
    assert c.post("/api/folders/rename", json={"path": "@inbox", "name": "x"}).status_code == 422
    assert c.post("/api/folders/rename", json={"path": "", "name": "x"}).status_code == 422


def test_rename_folder_case_only(batch_client):
    c, music = batch_client
    r = c.post("/api/folders/rename", json={"path": "Artist/Album", "name": "ALBUM"}).json()
    assert r["path"] == "Artist/ALBUM" and (music / "Artist" / "ALBUM" / "01.flac").exists()


# --- Moving files (Organize, Rename folder, the inbox) ------------------------------------------


def test_a_move_never_replaces_a_file_that_appears_at_the_last_moment(tmp_path, monkeypatch):
    from pathlib import Path

    from codetta.core.organize import Move, apply_moves
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "song.flac").write_bytes(b"mine")
    target = tmp_path / "b" / "song.flac"
    real_mkdir = Path.mkdir

    def mkdir_then_race(self, *args, **kwargs):  # after Codetta checked the name was free...
        real_mkdir(self, *args, **kwargs)
        if self == target.parent and not target.exists():
            target.write_bytes(b"someone else's")  # ...a download finishes with the same name

    monkeypatch.setattr(Path, "mkdir", mkdir_then_race)
    (r,) = apply_moves(tmp_path, [Move("a/song.flac", "b/song.flac", "move")])
    assert not r.ok and "already has that name" in r.error
    assert target.read_bytes() == b"someone else's"  # a plain rename would have replaced it
    assert (tmp_path / "a" / "song.flac").read_bytes() == b"mine"


def test_moving_across_disks_works_with_names_at_the_length_limit(tmp_path):
    from codetta.core.organize import _copy_then_remove
    name = "x" * 245 + ".flac"  # 250 bytes: a longer temporary name would be refused by the filesystem
    a = tmp_path / "from" / name
    a.parent.mkdir()
    a.write_bytes(b"audio")
    b = tmp_path / "to" / name
    b.parent.mkdir()
    _copy_then_remove(a, b)
    assert b.read_bytes() == b"audio" and not a.exists()
    assert not [p for p in b.parent.iterdir() if p.name.startswith(".codetta-move-")]


def test_undo_of_a_move_whose_folder_is_gone_says_so(tmp_path):
    import json

    from fastapi.testclient import TestClient

    from codetta.web.app import Settings, create_app
    music, config = tmp_path / "music", tmp_path / "config"
    music.mkdir()
    config.mkdir()
    entry = {"id": 1, "time": "2026-11-19T00:00:00+00:00", "kind": "inbox", "ok": True, "message": "Filed an album",
             "files": ["A/01.flac"], "file_count": 1, "changes": [], "errors": [],
             "undo": {"type": "moves", "moves": [["@inbox/new/01.flac", "A/01.flac"]]}}
    (config / "activity.jsonl").write_text(json.dumps(entry) + "\n")
    with TestClient(create_app(Settings(music_dir=music, config_dir=config, auth=False))) as c:
        res = c.post("/api/activity/1/undo")
    assert res.status_code == 409 and "can't be undone" in res.json()["detail"]  # not a bare server error


def test_a_preset_carries_on_past_a_file_it_cannot_open(tmp_path, monkeypatch):
    """One unreadable file used to end the whole request part-way: the files before it were
    changed but never logged, so they couldn't be undone."""
    from codetta.core.presets import Preset, apply_preset_to_folder
    engine = MetadataEngine()
    for name in ("1.flac", "2.flac", "3.flac"):
        shutil.copy2(FIXTURES_DIR / "sample.flac", tmp_path / name)
    real = engine.load_metadata

    def flaky(path, *a, **k):
        if Path(path).name == "2.flac":  # exactly: a save's temp copy (".codetta-…2.flac") must not match
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, *a, **k)

    monkeypatch.setattr(engine, "load_metadata", flaky)
    results = apply_preset_to_folder(engine, Preset(name="T", tags={"genre": ["Ambient"]}), tmp_path, mode="overwrite")
    by_name = {r.path.name: r for r in results}
    assert by_name["2.flac"].error and "Permission" in by_name["2.flac"].error
    assert by_name["1.flac"].applied == {"genre": ["Ambient"]} and by_name["3.flac"].applied == {"genre": ["Ambient"]}


@pytest.mark.parametrize("name", ["sample.mp3", "sample.aiff", "sample.wav"])
@pytest.mark.parametrize("genre", ["0", "17", "(17)", "RX"])
def test_a_genre_that_is_only_a_number_is_refused_with_a_clear_reason(fixture_copy, name, genre):
    """ID3 reads a bare number as an old numbered genre (0 = Blues), so saving "0" would really save
    "Blues". The write is refused, the file is untouched, and the message says why."""
    path = fixture_copy(name)
    before = path.read_bytes()
    with pytest.raises(MetadataError, match="only a number"):
        MetadataEngine().update_tags(path, {"genre": genre})
    assert path.read_bytes() == before
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".codetta-")]
    # With a word added, it saves.
    assert MetadataEngine().update_tags(path, {"genre": f"Genre {genre}"}).tags["genre"] == [f"Genre {genre}"]
