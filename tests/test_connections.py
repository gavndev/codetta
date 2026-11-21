"""Connections: Codetta is offline until the user (or the admin's env) opts in."""

import json

import pytest
from fastapi.testclient import TestClient

from codetta.core.connections import CONNECTIONS, ConnectionStore, parse_switch
from codetta.web.app import Settings, create_app

PASSWORD = "correct horse 1"


def test_everything_is_off_until_chosen(tmp_path):
    store = ConnectionStore(tmp_path / "connections.json")
    assert store.needs_choice
    assert not any(store.enabled(c.id) for c in CONNECTIONS)
    assert store.status()["offline"] is True


def test_choices_are_saved_and_reloaded(tmp_path):
    file = tmp_path / "connections.json"
    ConnectionStore(file).save({"musicbrainz": True, "lyrics": False})
    again = ConnectionStore(file)
    assert again.enabled("musicbrainz") and not again.enabled("lyrics") and not again.enabled("updates")
    assert not again.needs_choice
    assert json.loads(file.read_text())["chosen"] is True


def test_staying_offline_is_a_choice_too(tmp_path):
    store = ConnectionStore(tmp_path / "connections.json")
    store.save({})
    assert not store.needs_choice and store.status()["offline"]


def test_env_wins_and_locks_the_switch(tmp_path):
    store = ConnectionStore(tmp_path / "c.json", forced={"musicbrainz": False, "lyrics": True})
    store.save({"musicbrainz": True, "lyrics": False, "updates": True})
    assert not store.enabled("musicbrainz") and store.enabled("lyrics") and store.enabled("updates")
    assert store.locked_by("musicbrainz") == "CODETTA_MUSICBRAINZ"
    assert store.locked_by("lyrics") == "CODETTA_LYRICS_LOOKUP"
    assert store.locked_by("updates") is None


def test_offline_master_switch_beats_everything(tmp_path):
    store = ConnectionStore(tmp_path / "c.json", offline=True, forced={"musicbrainz": True})
    store.save({"lyrics": True})
    assert not any(store.enabled(c.id) for c in CONNECTIONS)
    assert store.locked_by("lyrics") == "CODETTA_OFFLINE"
    assert not store.needs_choice  # nothing to ask


def test_no_question_when_env_decided_everything(tmp_path):
    store = ConnectionStore(tmp_path / "c.json", forced={c.id: False for c in CONNECTIONS})
    assert not store.needs_choice


def test_broken_file_means_not_chosen(tmp_path):
    file = tmp_path / "c.json"
    file.write_text("{not json")
    assert ConnectionStore(file).needs_choice
    file.write_text('{"chosen": true, "enabled": {"musicbrainz": "yes", "evil": true}}')
    store = ConnectionStore(file)
    assert not store.enabled("musicbrainz")  # only real booleans count


@pytest.mark.parametrize("value,expected", [("on", True), ("TRUE", True), ("1", True), ("off", False),
                                            ("no", False), (None, None), ("maybe", None)])
def test_parse_switch(value, expected):
    assert parse_switch(value) is expected


def test_settings_from_env(monkeypatch):
    for name in ("OFFLINE", "MUSICBRAINZ", "LYRICS_LOOKUP", "MUSICBRAINZ_URL"):
        monkeypatch.delenv(f"CODETTA_{name}", raising=False)
    s = Settings.from_env()
    assert s.offline is False and s.musicbrainz is None and s.lyrics_lookup is None and s.musicbrainz_url is None
    monkeypatch.setenv("CODETTA_OFFLINE", "on")
    monkeypatch.setenv("CODETTA_MUSICBRAINZ", "on")
    monkeypatch.setenv("CODETTA_MUSICBRAINZ_URL", "http://mb.lan:5000")
    s = Settings.from_env()
    assert s.offline is True and s.musicbrainz is True and s.musicbrainz_url == "http://mb.lan:5000"


# --- API -----------------------------------------------------------------------------------


@pytest.fixture
def make_client(tmp_path):
    opened = []

    def make(**settings):
        (tmp_path / "music").mkdir(exist_ok=True)
        app = create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config", **settings))
        c = TestClient(app)
        c.__enter__()
        opened.append(c)
        return c
    yield make
    for c in opened:
        c.__exit__(None, None, None)


def test_api_is_private(make_client):
    c = make_client()
    assert c.get("/api/connections").status_code == 401
    assert c.put("/api/connections", json={"enabled": {"musicbrainz": True}}).status_code == 401


def test_api_first_run_flow(make_client, tmp_path):
    c = make_client()
    c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
    data = c.get("/api/connections").json()
    assert data["needs_choice"] and data["offline"]
    ids = [x["id"] for x in data["connections"]]
    assert ids == ["musicbrainz", "deezer", "itunes", "acoustid", "lyrics", "slskd", "lidarr", "mediaserver", "updates"]
    assert all(x["hosts"] and x["sends"] for x in data["connections"])

    data = c.put("/api/connections", json={"enabled": {"musicbrainz": True}}).json()
    assert not data["needs_choice"] and not data["offline"]
    assert c.get("/api/status").json()["musicbrainz"] is True
    assert c.put("/api/connections", json={"enabled": {"nope": True}}).status_code == 422


def test_api_shows_locks(make_client):
    c = make_client(offline=True)
    c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
    data = c.put("/api/connections", json={"enabled": {"musicbrainz": True}}).json()
    assert data["offline_locked"] and data["offline"] and not data["needs_choice"]
    assert {x["locked_by"] for x in data["connections"]} == {"CODETTA_OFFLINE"}
    res = c.post("/api/musicbrainz/search", json={"folder": "", "album": "x"})
    assert res.status_code == 403 and "CODETTA_OFFLINE" in res.json()["detail"]


def test_api_mirror_is_shown(make_client):
    c = make_client(musicbrainz_url="http://mb.lan:5000")
    c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
    mb = next(x for x in c.get("/api/connections").json()["connections"] if x["id"] == "musicbrainz")
    assert mb["hosts"][0] == "mb.lan:5000" and mb["mirror"]


def test_works_with_sign_in_off(make_client):
    c = make_client(auth=False)
    assert c.get("/api/connections").status_code == 200
