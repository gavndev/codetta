"""Tests for Tag Presets (codetta.core.presets)."""

import hashlib
import json
import shutil

import mutagen
import pytest

from codetta.core.engine import MetadataEngine
from codetta.core.presets import (
    ApplyMode,
    Preset,
    PresetError,
    PresetStore,
    apply_preset,
    apply_preset_to_folder,
    default_presets,
    filename_to_title,
    slugify,
)
from tests.conftest import FIXTURES_DIR


@pytest.fixture
def engine():
    return MetadataEngine()


@pytest.fixture
def blank_file(tmp_path):
    """Copy a sample into tmp_path under a new name, with ALL tags removed.

    Mimics a loose download that came with no metadata.
    """

    def _make(sample: str, dest_name: str, folder: str = "") -> object:
        dest_dir = tmp_path / folder if folder else tmp_path
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / dest_name
        shutil.copy2(FIXTURES_DIR / sample, dest)
        mutagen.File(dest).delete()
        return dest

    return _make


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Preset validation ----------------------------------------------------------


def test_preset_normalizes_values_and_keys():
    lo = Preset(name="  Test  ", tags={"Genre": "Rock", "ARTIST": ["A", "B"]})
    assert lo.name == "Test"
    assert lo.tags == {"genre": ["Rock"], "artist": ["A", "B"]}


@pytest.mark.parametrize("name", ["", "   "])
def test_preset_requires_a_name(name):
    with pytest.raises(PresetError):
        Preset(name=name)


@pytest.mark.parametrize("name", ["🔥🔥", "!!!", "★ Favourites ★", "हिंदी गाने", "夜のドライブ"])
def test_preset_names_in_any_script_or_emoji(tmp_path, name):
    store = PresetStore(tmp_path)
    store.save(Preset(name=name, tags={"genre": "Test"}))
    assert store.get(name).name == name
    assert [lo.name for lo in store.list()] == [name]
    assert slugify(name)  # always a usable file name


def test_unknown_placeholder_is_rejected():
    with pytest.raises(PresetError, match="unknown placeholder"):
        Preset(name="Bad", tags={"title": "{nope}"})


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"tags": {}},
        {"name": "X", "tags": []},
        {"name": "X", "tags": {"genre": 5}},
        {"name": "X", "tags": {"genre": ["ok", 5]}},
        {"name": "X", "description": 5},
    ],
)
def test_from_dict_rejects_bad_shapes(data):
    with pytest.raises(PresetError):
        Preset.from_dict(data)


def test_dict_round_trip_keeps_single_values_readable():
    lo = Preset(name="X", tags={"genre": "Rock", "artist": ["A", "B"]}, description="d")
    data = lo.to_dict()
    assert data["tags"] == {"genre": "Rock", "artist": ["A", "B"]}
    assert Preset.from_dict(data) == lo


def test_default_presets_are_valid():
    names = [lo.name for lo in default_presets()]
    assert names == ["Single", "Album Folder", "Explicit", "Clean", "Full Credits"]


# --- PresetStore --------------------------------------------------------------


def test_store_save_get_list_delete(tmp_path):
    store = PresetStore(tmp_path / "presets")
    assert store.list() == []

    path = store.save(Preset(name="My Vibes", tags={"mood": "Chill"}))

    assert path.name == "my-vibes.json"
    assert store.get("My Vibes").tags == {"mood": ["Chill"]}
    assert store.get("my vibes").name == "My Vibes"  # lookup ignores case/spacing
    assert [lo.name for lo in store.list()] == ["My Vibes"]

    store.delete("My Vibes")
    assert store.list() == []
    with pytest.raises(PresetError):
        store.get("My Vibes")


def test_store_save_replaces_existing(tmp_path):
    store = PresetStore(tmp_path)
    store.save(Preset(name="X", tags={"genre": "Rock"}))
    store.save(Preset(name="X", tags={"genre": "Jazz"}))
    assert store.get("X").tags == {"genre": ["Jazz"]}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_store_files_are_human_editable(tmp_path):
    store = PresetStore(tmp_path)
    (tmp_path / "hand-made.json").write_text(
        json.dumps({"name": "Hand Made", "tags": {"genre": "Lo-Fi"}})
    )
    assert store.get("Hand Made").tags == {"genre": ["Lo-Fi"]}


def test_store_list_skips_broken_files(tmp_path):
    store = PresetStore(tmp_path)
    store.save(Preset(name="Good"))
    (tmp_path / "broken.json").write_text("{ not json")
    (tmp_path / "wrong.json").write_text('{"name": "W", "tags": {"genre": 5}}')
    (tmp_path / ".codetta-leftover.json").write_text('{"name": "Ghost"}')
    assert [lo.name for lo in store.list()] == ["Good"]


def test_store_get_broken_file_raises(tmp_path):
    (tmp_path / "broken.json").write_text("{ not json")
    with pytest.raises(PresetError):
        PresetStore(tmp_path).get("broken")


def test_install_defaults_does_not_overwrite_user_edits(tmp_path):
    store = PresetStore(tmp_path)
    store.save(Preset(name="Single", tags={"genre": "Mine"}))

    added = store.install_defaults()

    assert [lo.name for lo in added] == ["Album Folder", "Explicit", "Clean", "Full Credits"]
    assert store.get("Single").tags == {"genre": ["Mine"]}
    assert store.install_defaults() == []


def test_unicode_preset_names(tmp_path):
    store = PresetStore(tmp_path)
    store.save(Preset(name="ローファイ", tags={"genre": "Lo-Fi"}))
    assert store.get("ローファイ").tags == {"genre": ["Lo-Fi"]}


# --- Helpers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("01 - My Song", "My Song"),
        ("3. Late Night", "Late Night"),
        ("07 Outro", "Outro"),
        ("12) Thing", "Thing"),
        ("03_late_night_drive", "late night drive"),
        ("Plain Title", "Plain Title"),
        ("1979", "1979"),
        ("2Pac Tribute", "2Pac Tribute"),
        ("99 Problems", "Problems"),  # ambiguous; a leading "NN " is usually a track number
        ("01", "01"),
    ],
)
def test_filename_to_title(stem, expected):
    assert filename_to_title(stem) == expected


def test_slugify():
    assert slugify("Album Folder!") == "album-folder"
    assert slugify("  --Lo-Fi  Beats-- ") == "lo-fi-beats"


# --- Applying: single files ------------------------------------------------------


@pytest.mark.parametrize("sample", ["sample.flac", "sample.mp3", "sample.m4a", "sample.ogg", "sample.opus"])
def test_single_preset_fleshes_out_a_bare_file(engine, blank_file, sample):
    ext = sample.split(".")[1]
    path = blank_file(sample, f"01 - Night Drive.{ext}")
    lo = Preset(
        name="Single+",
        tags={**default_presets()[0].tags, "artist": "DJ Test", "genre": "Lo-Fi"},
    )

    [result] = apply_preset(engine, lo, [path])

    assert result.ok, result.error
    tags = engine.load_metadata(path).tags
    assert tags["title"] == ["Night Drive"]
    assert tags["album"] == ["Night Drive"]
    assert tags["artist"] == ["DJ Test"]
    assert tags["genre"] == ["Lo-Fi"]
    assert tags["tracknumber"] == ["1/1"]
    assert tags["releasetype"] == ["single"]
    assert tags["media"] == ["Digital Media"]
    # Blank fields in the preset (date, albumartist, comment) are not written.
    assert "date" not in tags and "comment" not in tags


@pytest.mark.parametrize("sample", ["sample.mp3", "sample.m4a", "sample.flac"])
def test_full_credits_apply_to_every_format(engine, blank_file, sample):
    ext = sample.split(".")[1]
    path = blank_file(sample, f"song.{ext}")
    lo = Preset(
        name="Credits",
        tags={
            "composer": "C", "producer": ["P1", "P2"], "engineer": "E", "mixer": "M",
            "mood": "Chill", "label": "L", "releasetype": "ep", "artists": ["A", "B"],
        },
    )

    [result] = apply_preset(engine, lo, [path])

    assert result.ok and result.unsupported == []
    tags = engine.load_metadata(path).tags
    for key, values in lo.tags.items():
        assert tags[key] == values, key


def test_fill_mode_keeps_existing_values(engine, tmp_path):
    path = tmp_path / "sample.flac"
    shutil.copy2(FIXTURES_DIR / "sample.flac", path)  # already titled "Test Track"
    lo = Preset(name="X", tags={"title": "{filename_title}", "mood": "Chill"})

    [result] = apply_preset(engine, lo, [path])

    assert result.kept_existing == ["title"]
    assert result.applied == {"mood": ["Chill"]}
    tags = engine.load_metadata(path).tags
    assert tags["title"] == ["Test Track"]
    assert tags["mood"] == ["Chill"]


def test_overwrite_mode_replaces_values(engine, tmp_path):
    path = tmp_path / "sample.flac"
    shutil.copy2(FIXTURES_DIR / "sample.flac", path)
    lo = Preset(name="X", tags={"title": "{filename_title}"})

    [result] = apply_preset(engine, lo, [path], mode="overwrite")

    assert result.applied == {"title": ["sample"]}
    assert engine.load_metadata(path).tags["title"] == ["sample"]


def test_overwrite_does_not_touch_tags_outside_the_preset(engine, tmp_path):
    path = tmp_path / "sample.mp3"
    shutil.copy2(FIXTURES_DIR / "sample.mp3", path)
    lo = Preset(name="X", tags={"genre": "Jazz"})

    apply_preset(engine, lo, [path], mode=ApplyMode.OVERWRITE)

    tags = engine.load_metadata(path).tags
    assert tags["genre"] == ["Jazz"]
    assert tags["artist"] == ["Coda Tester"]


def test_dry_run_reports_but_does_not_write(engine, blank_file):
    path = blank_file("sample.flac", "track.flac")
    before = sha256(path)
    lo = Preset(name="X", tags={"title": "{filename_title}", "genre": "Rock"})

    [result] = apply_preset(engine, lo, [path], dry_run=True)

    assert result.applied == {"title": ["track"], "genre": ["Rock"]}
    assert sha256(path) == before


def test_unchanged_file_is_not_rewritten(engine, tmp_path):
    path = tmp_path / "sample.flac"
    shutil.copy2(FIXTURES_DIR / "sample.flac", path)
    before = sha256(path)
    lo = Preset(name="X", tags={"genre": "Test"})  # already the value

    [result] = apply_preset(engine, lo, [path], mode="overwrite")

    assert result.applied == {}
    assert sha256(path) == before


def test_unsupported_tags_are_skipped_not_fatal(engine, blank_file):
    path = blank_file("sample.mp3", "song.mp3")
    lo = Preset(name="X", tags={"genre": "Rock", "my_custom_field": "x"})

    [result] = apply_preset(engine, lo, [path])

    assert result.ok
    assert result.unsupported == ["my_custom_field"]
    assert engine.load_metadata(path).tags["genre"] == ["Rock"]


def test_one_bad_file_does_not_stop_the_batch(engine, blank_file, tmp_path):
    good = blank_file("sample.flac", "good.flac")
    bad = tmp_path / "bad.flac"
    bad.write_bytes(b"not audio at all" * 20)
    missing = tmp_path / "missing.mp3"
    lo = Preset(name="X", tags={"genre": "Rock"})

    results = apply_preset(engine, lo, [bad, missing, good])

    assert [r.ok for r in results] == [False, False, True]
    assert results[0].applied == {}
    assert engine.load_metadata(good).tags["genre"] == ["Rock"]


def test_apply_by_name_from_store(engine, blank_file, tmp_path):
    store = PresetStore(tmp_path / "presets")
    store.install_defaults()
    path = blank_file("sample.opus", "02_sunrise.opus")

    apply_preset(engine, store.get("Single"), [path])

    tags = engine.load_metadata(path).tags
    assert tags["title"] == ["sunrise"]
    assert tags["releasetype"] == ["single"]


# --- Applying: folders (albums) --------------------------------------------------


def test_album_folder_numbers_tracks_in_natural_order(engine, blank_file, tmp_path):
    album = "Midnight Tapes"
    blank_file("sample.flac", "10 - Outro.flac", album)
    blank_file("sample.mp3", "1 - Intro.mp3", album)
    blank_file("sample.m4a", "2 - Groove.m4a", album)
    blank_file("sample.ogg", "3 - Haze.ogg", album)
    (tmp_path / album / "cover.jpg").write_bytes(b"jpeg")  # non-audio: ignored
    (tmp_path / album / ".codetta-temp.flac").write_bytes(b"x")  # temp: ignored

    results = apply_preset_to_folder(engine, default_presets()[1], tmp_path / album)

    assert all(r.ok for r in results), [r.error for r in results]
    got = {
        r.path.name: engine.load_metadata(r.path).tags for r in results
    }
    assert list(got) == ["1 - Intro.mp3", "2 - Groove.m4a", "3 - Haze.ogg", "10 - Outro.flac"]
    assert [t["tracknumber"] for t in got.values()] == [["1/4"], ["2/4"], ["3/4"], ["4/4"]]
    assert [t["title"] for t in got.values()] == [["Intro"], ["Groove"], ["Haze"], ["Outro"]]
    assert all(t["album"] == ["Midnight Tapes"] for t in got.values())
    assert all(t["releasetype"] == ["album"] for t in got.values())


def test_recursive_folder_numbers_each_subfolder_separately(engine, blank_file, tmp_path):
    blank_file("sample.flac", "a.flac", "Artist/Album One")
    blank_file("sample.flac", "b.flac", "Artist/Album One")
    blank_file("sample.mp3", "a.mp3", "Artist/Album Two")
    blank_file("sample.mp3", "skip.mp3", "Artist/.hidden")

    results = apply_preset_to_folder(
        engine, default_presets()[1], tmp_path / "Artist", recursive=True
    )

    tags = {f"{r.path.parent.name}/{r.path.name}": engine.load_metadata(r.path).tags for r in results}
    assert tags["Album One/a.flac"]["tracknumber"] == ["1/2"]
    assert tags["Album One/b.flac"]["tracknumber"] == ["2/2"]
    assert tags["Album Two/a.mp3"]["tracknumber"] == ["1/1"]
    assert tags["Album Two/a.mp3"]["album"] == ["Album Two"]
    assert len(results) == 3


def test_non_recursive_ignores_subfolders(engine, blank_file, tmp_path):
    blank_file("sample.flac", "top.flac", "Album")
    blank_file("sample.flac", "nested.flac", "Album/Extras")

    results = apply_preset_to_folder(engine, default_presets()[1], tmp_path / "Album")

    assert [r.path.name for r in results] == ["top.flac"]


def test_missing_folder_raises(engine, tmp_path):
    with pytest.raises(FileNotFoundError):
        apply_preset_to_folder(engine, default_presets()[1], tmp_path / "nope")


def test_old_loadouts_folder_moves_to_presets(tmp_path):
    """Tag Presets used to be "Tag Loadouts" in config/loadouts/: existing installs keep theirs."""
    from codetta.web.app import Settings, create_app
    old = tmp_path / "config" / "loadouts"
    old.mkdir(parents=True)
    (old / "my-preset.json").write_text('{"name": "My preset", "description": "", "tags": {"genre": "Jazz"}}')
    (tmp_path / "music").mkdir()
    create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config", auth=False))
    assert not old.exists() and (tmp_path / "config" / "presets" / "my-preset.json").is_file()


@pytest.mark.parametrize("name, value", [("Explicit", "1"), ("Clean", "2")])
def test_explicit_and_clean_presets_mark_a_whole_folder(tmp_path, name, value):
    """1 = explicit, 2 = clean: the advisory tag Navidrome (OpenSubsonic explicitStatus) and Apple Music read."""
    import shutil

    import mutagen

    from codetta.core.engine import MetadataEngine
    from codetta.core.presets import apply_preset_to_folder, default_presets
    from tests.conftest import FIXTURES_DIR, SAMPLE_FILES
    for f in SAMPLE_FILES:
        shutil.copy2(FIXTURES_DIR / f, tmp_path / f)
    preset = next(p for p in default_presets() if p.name == name)
    engine = MetadataEngine()
    results = apply_preset_to_folder(engine, preset, tmp_path, mode="overwrite")
    assert not [r.error for r in results if r.error]
    for f in SAMPLE_FILES:
        assert engine.load_metadata(tmp_path / f).tags["itunesadvisory"] == [value], f
    assert mutagen.File(tmp_path / "sample.m4a")["rtng"] == [int(value)]  # Apple's own atom in M4A
    assert mutagen.File(tmp_path / "sample.mp3")["TXXX:ITUNESADVISORY"].text == [value]
