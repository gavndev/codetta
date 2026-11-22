"""The built-in tag tools: change case, fix garbled text, split / join / de-duplicate, keep only."""

import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.plugins import PluginAPI, PluginError
from codetta.plugins.builtin.tagtools import change_case, dedupe, fix_garbled, join_values, keep_only, split_values
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


def garble(text, codec):
    """What a program shows when it reads ``codec`` bytes as Windows-1252."""
    raw = text.encode(codec)
    return "".join(chr(b) if b in (0x81, 0x8D, 0x8F, 0x90, 0x9D) else bytes([b]).decode("cp1252") for b in raw)


@pytest.mark.parametrize(("text", "source", "codec"), [
    ("Beyoncé", "utf8", "utf-8"), ("Sigur Rós – Ágætis byrjun", "utf8", "utf-8"),
    ("Mötley Crüe’s “Dr. Feelgood”", "utf8", "utf-8"), ("Кино", "cp1251", "cp1251"),
    ("Земфира — Хочешь?", "cp1251", "cp1251"), ("宇多田ヒカル", "shift_jis", "shift_jis"),
    ("周杰伦", "gbk", "gbk"), ("방탄소년단", "cp949", "cp949"),
])
def test_garbled_text_is_repaired(text, source, codec):
    assert fix_garbled(garble(text, codec), source) == text


@pytest.mark.parametrize("good", ["Beyoncé", "Björk", "Motörhead", "Café del Mar", "Ñu", "Sigur Rós", "Zoë", "naïve",
                                  "Æon", "Kino", "Кино", "周杰伦", "AC/DC", ""])
@pytest.mark.parametrize("source", ["utf8", "cp1251", "shift_jis", "gbk", "cp949"])
def test_correct_names_are_never_changed(good, source):
    assert fix_garbled(good, source) == good


def test_case_styles():
    assert change_case("night drive in the CITY", "upper") == "NIGHT DRIVE IN THE CITY"
    assert change_case("Night Drive", "lower") == "night drive"
    assert change_case("NIGHT DRIVE IN THE CITY", "title") == "Night Drive in the City"
    assert change_case("NIGHT DRIVE in the city", "sentence") == "Night drive in the city"
    assert change_case("(intro) new day", "sentence") == "(Intro) new day"


def test_split_join_dedupe_and_keep_only():
    assert split_values({"genre": ["Rock; Pop;  Indie"]}, {"field": "genre", "separator": ";"}) == {"genre": ["Rock", "Pop", "Indie"]}
    assert split_values({"artist": ["A & B"], "genre": ["X/Y"]}, {"field": "all", "separator": "&"}) == {"artist": ["A", "B"]}
    assert join_values({"genre": ["Rock", "Pop"]}, {"field": "genre", "separator": "/"}) == {"genre": ["Rock / Pop"]}
    assert join_values({"genre": ["Rock"]}, {"field": "genre", "separator": ";"}) is None
    assert dedupe({"genre": ["Rock", " rock", "Pop"], "title": ["X"]}) == {"genre": ["Rock", "Pop"]}
    tags = {"title": ["a"], "encoder": ["LAME"], "musicbrainz_albumid": ["x"], "replaygain_track_gain": ["-1 dB"],
            "lyrics": ["la"], "comment": ["c"], "label": ["L"]}
    assert keep_only(tags, {"set": "basics"}) == {"encoder": None, "musicbrainz_albumid": None, "comment": None, "label": None}
    assert keep_only(tags, {"set": "ids"}) == {"encoder": None, "comment": None}  # IDs and release details stay


def test_options_must_have_choices():
    api = PluginAPI("x", lambda a: None)
    with pytest.raises(PluginError):
        api.add_action(id="bad", label="Bad", run=lambda t, o: None, options=[{"id": "o", "choices": []}])


@pytest.fixture
def client(tmp_path):
    album = tmp_path / "music" / "Album"
    album.mkdir(parents=True)
    e = MetadataEngine()
    for n, f in enumerate(["sample.flac", "sample.mp3"], 1):
        shutil.copy2(FIXTURES_DIR / f, album / f"0{n}{f[-5:] if f.endswith('flac') else '.mp3'}")
        e.update_tags(album / f"0{n}{'.flac' if f.endswith('flac') else '.mp3'}",
                      {"title": f"night drive {n}", "artist": garble("Beyoncé", "utf-8"), "genre": ["Rock; Pop"]})
    with TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config", auth=False))) as c:
        c.root = tmp_path / "music"
        yield c


def test_actions_list_their_choices(client):
    acts = {a["id"]: a for a in client.get("/api/plugins").json()["actions"]}
    assert {"tagtools.case", "tagtools.fix-garbled", "tagtools.split", "tagtools.join", "tagtools.dedupe",
            "tagtools.keep-only"} <= set(acts)
    assert [o["id"] for o in acts["tagtools.case"]["options"]] == ["field", "style"]
    assert acts["tidy.title-case"]["options"] == []  # the old actions still have none


def test_choices_go_through_the_api_and_can_be_undone(client):
    run = lambda opts, dry=True: client.post("/api/actions/tagtools.case/run",  # noqa: E731
                                             json={"folder": "Album", "options": opts, "dry_run": dry}).json()
    d = run({"field": "title", "style": "upper"})
    assert d["changing"] == 2 and d["preview"][0]["changes"][0]["new"] == "NIGHT DRIVE 1"
    assert run({"field": "title", "style": "nonsense"})["preview"][0]["changes"][0]["new"] == "NIGHT DRIVE 1"  # default
    assert run({"field": "title", "style": "upper"}, dry=False)["changed"] == 2
    assert client.get("/api/track", params={"path": "Album/02.mp3"}).json()["tags"]["title"] == ["NIGHT DRIVE 2"]
    entry = client.get("/api/activity").json()[0]
    assert client.post(f"/api/activity/{entry['id']}/undo").status_code == 200
    assert client.get("/api/track", params={"path": "Album/02.mp3"}).json()["tags"]["title"] == ["night drive 2"]


def test_garbled_names_are_fixed_in_real_files(client):
    client.post("/api/actions/tagtools.fix-garbled/run", json={"folder": "Album", "options": {"source": "utf8"}, "dry_run": False})
    for f in ("01.flac", "02.mp3"):
        assert client.get("/api/track", params={"path": f"Album/{f}"}).json()["tags"]["artist"] == ["Beyoncé"]


def test_split_writes_separate_values(client):
    client.post("/api/actions/tagtools.split/run",
                json={"folder": "Album", "options": {"field": "genre", "separator": ";"}, "dry_run": False})
    assert client.get("/api/track", params={"path": "Album/01.flac"}).json()["tags"]["genre"] == ["Rock", "Pop"]


def test_activity_says_what_changed_in_plain_words(client):
    """Not Python's "['Rock', 'Pop']" or "None": the values, before and after, as people read them."""
    client.post("/api/actions/tagtools.split/run",
                json={"folder": "Album", "options": {"field": "genre", "separator": ";"}, "dry_run": False})
    entry = client.get("/api/activity").json()[0]
    assert entry["changes"] == [{"key": "genre", "old": "Rock; Pop", "new": "Rock; Pop"}]  # one value -> two
    client.post("/api/actions/tagtools.case/run",
                json={"folder": "Album", "options": {"field": "title", "style": "upper"}, "dry_run": False})
    entry = client.get("/api/activity").json()[0]
    assert entry["changes"] == [{"key": "title", "old": "various", "new": "various"}]
    client.post("/api/actions/tagtools.keep-only/run", json={"folder": "Album", "dry_run": False})
    for ch in client.get("/api/activity").json()[0]["changes"]:
        assert "None" not in ch["new"] and "[" not in ch["new"] and "[" not in ch["old"]
