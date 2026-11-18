"""Organize: rename and move files from a pattern. Every test works on a temp copy."""

import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.organize import (
    DEFAULT_PATTERN,
    PatternError,
    Source,
    apply_moves,
    check_pattern,
    plan_moves,
    render,
    safe_name,
    undo_moves,
)
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

PASSWORD = "correct horse 1"


def src(rel="In/x.flac", **tags):
    return Source(rel, {k: [v] for k, v in tags.items()}, "flac")


ALBUM = dict(albumartist="Coda Collective", artist="Coda Tester", album="Fixture Album", title="Test Track",
             tracknumber="3/12", discnumber="1/1", date="2024-05-01")


# --- Patterns ----------------------------------------------------------------------------------


def test_default_pattern():
    assert render(DEFAULT_PATTERN, src(**ALBUM)) == "Coda Collective/Fixture Album (2024)/03 Test Track.flac"


def test_optional_parts_and_alternatives():
    no_year = {**ALBUM, "date": ""}
    assert render(DEFAULT_PATTERN, src(**no_year)) == "Coda Collective/Fixture Album/03 Test Track.flac"
    no_aa = {**ALBUM, "albumartist": ""}
    assert render(DEFAULT_PATTERN, src(**no_aa)).startswith("Coda Tester/")
    assert render("{album}/[{year} - ]{title}", src(**ALBUM)) == "Fixture Album/2024 - Test Track.flac"


def test_multi_disc_numbers():
    assert render(DEFAULT_PATTERN, src(**{**ALBUM, "discnumber": "2/2"}), multi_disc=True).endswith("/2-03 Test Track.flac")


def test_missing_tags_never_leave_an_empty_name():
    assert render(DEFAULT_PATTERN, src("In/My Song.mp3")) == "Unknown Artist/Unknown Album/My Song.mp3"


@pytest.mark.parametrize("value,expected", [
    ("AC/DC", "AC_DC"), ('What? "Yes": *No*', "What_ _Yes__ _No_"), ("Trailing dots...", "Trailing dots"),
    (".hidden", "_hidden"), ("   spaced\tout  ", "spaced out"), ("..", "_"), ("", "_"),
])
def test_safe_names(value, expected):
    assert safe_name(value) == expected


def test_long_names_are_cut_by_bytes_not_characters():
    name = safe_name("日本語" * 200)
    assert len(name.encode()) <= 200 and name.startswith("日本語")


def test_hostile_tags_stay_inside_the_folder():
    path = render(DEFAULT_PATTERN, src(**{**ALBUM, "albumartist": "../../etc", "album": "..", "title": "/passwd"}))
    assert not path.startswith("/") and ".." not in path.split("/")


@pytest.mark.parametrize("pattern", ["", "   ", "{album", "{album}/[x", "{album}/static", "{a}\\{b}"])
def test_bad_patterns(pattern):
    with pytest.raises(PatternError):
        check_pattern(pattern)


# --- Planning and moving ------------------------------------------------------------------------


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "music"
    (root / "Downloads" / "rip").mkdir(parents=True)
    return root


def touch(root, rel, data=b"x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_plan_and_apply_with_extras(lib):
    for n in (1, 2):
        touch(lib, f"Downloads/rip/0{n}.flac")
    touch(lib, "Downloads/rip/01.lrc")
    touch(lib, "Downloads/rip/cover.jpg")
    touch(lib, "Downloads/rip/scans/booklet.pdf")
    touch(lib, "Downloads/rip/.DS_Store")
    sources = [src(f"Downloads/rip/0{n}.flac", **{**ALBUM, "tracknumber": str(n), "title": f"Song {n}"}) for n in (1, 2)]
    moves = plan_moves(lib, sources, DEFAULT_PATTERN)
    assert [m.status for m in moves] == ["move", "move"]
    extras = {a: b for m in moves for a, b in m.companions}
    folder = "Coda Collective/Fixture Album (2024)"
    assert extras == {"Downloads/rip/01.lrc": f"{folder}/01 Song 1.lrc", "Downloads/rip/cover.jpg": f"{folder}/cover.jpg",
                      "Downloads/rip/scans": f"{folder}/scans"}
    results = apply_moves(lib, moves)
    assert all(r.ok for r in results)
    assert (lib / folder / "01 Song 1.flac").exists() and (lib / folder / "01 Song 1.lrc").exists()
    assert (lib / folder / "scans" / "booklet.pdf").exists()
    assert (lib / "Downloads" / "rip" / ".DS_Store").exists()  # hidden files stay (so the folder stays too)

    report, reverse = undo_moves(lib, [list(p) for r in results for p in r.moved])
    assert all(ok for *_, ok, _ in report)
    assert (lib / "Downloads/rip/01.flac").exists() and (lib / "Downloads/rip/01.lrc").exists()
    assert not (lib / "Coda Collective").exists()  # emptied folders are removed
    assert reverse and reverse[0][0].startswith(folder)


def test_extras_stay_when_only_part_of_a_folder_moves(lib):
    touch(lib, "Downloads/rip/a.flac")
    touch(lib, "Downloads/rip/b.flac")
    touch(lib, "Downloads/rip/cover.jpg")
    moves = plan_moves(lib, [src("Downloads/rip/a.flac", **ALBUM)], DEFAULT_PATTERN)
    assert moves[0].status == "move" and moves[0].companions == []


def test_conflicts_are_never_overwritten(lib):
    touch(lib, "Downloads/rip/a.flac", b"new")
    touch(lib, "Downloads/rip/b.flac", b"other")
    existing = touch(lib, "Coda Collective/Fixture Album (2024)/03 Test Track.flac", b"keep me")
    moves = plan_moves(lib, [src("Downloads/rip/a.flac", **ALBUM)], DEFAULT_PATTERN)
    assert moves[0].status == "conflict"
    existing.unlink()
    moves = plan_moves(lib, [src("Downloads/rip/a.flac", **ALBUM), src("Downloads/rip/b.flac", **ALBUM)], DEFAULT_PATTERN)
    assert [m.status for m in moves] == ["move", "conflict"]  # two files, one name
    touch(lib, "Coda Collective/Fixture Album (2024)/03 Test Track.flac", b"appeared meanwhile")
    res = apply_moves(lib, moves)
    assert not res[0].ok and (lib / "Downloads/rip/a.flac").read_bytes() == b"new"
    assert (lib / "Coda Collective/Fixture Album (2024)/03 Test Track.flac").read_bytes() == b"appeared meanwhile"


def test_already_in_place(lib):
    touch(lib, "Coda Collective/Fixture Album (2024)/03 Test Track.flac")
    moves = plan_moves(lib, [src("Coda Collective/Fixture Album (2024)/03 Test Track.flac", **ALBUM)], DEFAULT_PATTERN)
    assert moves[0].status == "same" and apply_moves(lib, moves) == []


def test_one_failure_doesnt_stop_the_rest(lib):
    touch(lib, "Downloads/rip/a.flac")
    moves = plan_moves(lib, [src("Downloads/rip/a.flac", **ALBUM), src("Downloads/rip/gone.flac", **{**ALBUM, "title": "B"})],
                       DEFAULT_PATTERN)
    res = apply_moves(lib, moves)
    assert res[0].ok and not res[1].ok and "no longer there" in res[1].error


def test_undo_leaves_changed_files_alone(lib):
    touch(lib, "Downloads/rip/a.flac")
    res = apply_moves(lib, plan_moves(lib, [src("Downloads/rip/a.flac", **ALBUM)], DEFAULT_PATTERN))
    touch(lib, "Downloads/rip/a.flac", b"someone put a new file here")
    report, reverse = undo_moves(lib, [list(p) for r in res for p in r.moved])
    assert not report[0][2] and "left alone" in report[0][3] and reverse == []


# --- API ----------------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    music = tmp_path / "music"
    (music / "Downloads").mkdir(parents=True)
    engine = MetadataEngine()
    for n, ext in ((1, "flac"), (2, "mp3")):
        dest = music / "Downloads" / f"track{n}.{ext}"
        shutil.copy2(FIXTURES_DIR / f"sample.{ext}", dest)
        engine.update_tags(dest, {"title": f"Song {n}", "tracknumber": f"{n}/2", "discnumber": None})
    (music / "Downloads" / "cover.jpg").write_bytes((FIXTURES_DIR / "cover.jpg").read_bytes())
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config"))) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.music = music
        yield c


def test_preview_moves_nothing(client):
    data = client.post("/api/organize/preview", json={"folder": "Downloads"}).json()
    assert data["counts"]["move"] == 2 and data["extras"] == 1
    assert [m["dst"] for m in data["moves"]] == ["Coda Collective/Fixture Album (2024)/01 Song 1.flac",
                                                  "Coda Collective/Fixture Album (2024)/02 Song 2.mp3"]
    assert (client.music / "Downloads" / "track1.flac").exists()


def test_apply_logs_and_undoes(client):
    res = client.post("/api/organize/apply", json={"folder": "Downloads"}).json()
    assert res["moved"] == 2 and res["failed"] == 0 and res["extras"] == 1
    new = "Coda Collective/Fixture Album (2024)/01 Song 1.flac"
    assert client.get("/api/track", params={"path": new}).json()["tags"]["title"] == ["Song 1"]
    assert (client.music / "Coda Collective/Fixture Album (2024)/cover.jpg").exists()
    assert not (client.music / "Downloads").exists()  # emptied, so removed

    entry = client.get("/api/activity").json()[0]
    assert entry["kind"] == "organize" and entry["can_undo"] and new in entry["files"]
    undo = client.post(f"/api/activity/{entry['id']}/undo").json()
    assert undo["undone"] == 2
    assert (client.music / "Downloads" / "track1.flac").exists() and (client.music / "Downloads" / "cover.jpg").exists()
    assert not (client.music / "Coda Collective").exists()
    redo = client.get("/api/activity").json()[0]
    assert client.post(f"/api/activity/{redo['id']}/undo").json()["undone"] == 2  # redo
    assert (client.music / new).exists()


def test_custom_pattern_and_saved_setting(client):
    data = client.post("/api/organize/preview", json={"folder": "Downloads", "pattern": "{album}/{track} - {title}"}).json()
    assert data["moves"][0]["dst"] == "Fixture Album/01 - Song 1.flac"
    assert client.put("/api/organize/settings", json={"pattern": "{album}/{title}"}).json()["pattern"] == "{album}/{title}"
    assert client.post("/api/organize/preview", json={"folder": "Downloads"}).json()["pattern"] == "{album}/{title}"
    assert client.put("/api/organize/settings", json={"pattern": "{album"}).status_code == 422
    assert client.post("/api/organize/preview", json={"folder": "Downloads", "pattern": "nope"}).status_code == 422


def test_example(client):
    ex = client.post("/api/organize/example", json={"pattern": DEFAULT_PATTERN}).json()
    assert ex["single"] == "Kōsei Mori/Northern Signal (2021)/03 Harbour Lights.flac"
    assert ex["multi"].endswith("/2-03 Harbour Lights.flac")
    assert client.post("/api/organize/example", json={"pattern": "{x"}).json()["ok"] is False


def test_paths_outside_the_library_are_refused(client):
    res = client.post("/api/organize/preview", json={"paths": ["../../etc/passwd"]})
    assert res.status_code == 200 and res.json()["moves"][0]["status"] == "error"
    assert client.post("/api/organize/preview", json={"folder": "../.."}).status_code == 400
