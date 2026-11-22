"""The desktop app: where it keeps things, how its window signs in, and quitting."""

import json

import pytest
from fastapi.testclient import TestClient

from codetta.cli import desktop
from codetta.web.app import Settings, create_app

TOKEN = "launch-secret-0123456789abcdef"


def test_portable_keeps_everything_next_to_the_app(tmp_path):
    (tmp_path / "Codetta Data").mkdir()
    (tmp_path / "Music").mkdir()
    music, config, portable = desktop.choose_folders(None, base=tmp_path)
    assert portable and config == tmp_path / "Codetta Data" / "config" and music == (tmp_path / "Music").resolve()


def test_a_fresh_stick_gets_a_music_folder_inside_codetta_data(tmp_path):
    (tmp_path / "Codetta Data").mkdir()
    music, _, _ = desktop.choose_folders(None, base=tmp_path)
    assert music == (tmp_path / "Codetta Data" / "Music").resolve()


def test_installed_uses_the_app_data_folder_and_remembers_the_music_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CODETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    (tmp_path / "Tunes").mkdir()
    desktop.save_prefs(tmp_path / "cfg", music=str(tmp_path / "Tunes"))
    music, config, portable = desktop.choose_folders(None, base=tmp_path / "app")
    assert not portable and config == tmp_path / "cfg" and music == (tmp_path / "Tunes").resolve()


@pytest.fixture
def client(tmp_path):
    (tmp_path / "music").mkdir()
    app = create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config", desktop_token=TOKEN))
    with TestClient(app) as c:
        c.app_ref = app
        yield c


def test_the_window_signs_in_with_the_launch_secret(client):
    assert client.get("/api/library-health/summary").status_code == 401
    r = client.get("/api/auth/desktop", params={"token": TOKEN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    status = client.get("/api/auth/status").json()
    assert status["signed_in"] and status["desktop"] and not status["setup_required"]
    assert client.get("/api/library-health/summary").status_code == 200


@pytest.mark.parametrize("token", ["", "wrong", TOKEN[:-1], TOKEN + "x"])
def test_anyone_without_the_secret_gets_nothing(client, token):
    assert client.get("/api/auth/desktop", params={"token": token}, follow_redirects=False).status_code == 404
    assert client.get("/api/auth/status").json()["signed_in"] is False


def test_without_a_desktop_secret_the_route_doesnt_exist(tmp_path):
    (tmp_path / "music").mkdir()
    with TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config"))) as c:
        assert c.get("/api/auth/desktop", params={"token": ""}, follow_redirects=False).status_code == 404
        assert c.get("/api/auth/status").json()["desktop"] is False


def test_signing_in_again_keeps_the_same_account(client, tmp_path):
    client.get("/api/auth/desktop", params={"token": TOKEN})
    first = json.loads((tmp_path / "config" / "auth.json").read_text())
    client.cookies.clear()
    client.get("/api/auth/desktop", params={"token": TOKEN})
    assert json.loads((tmp_path / "config" / "auth.json").read_text()) == first


def test_quit_stops_the_app(client):
    quit_calls = []
    client.app_ref.state.desktop_quit = lambda: quit_calls.append(1)
    assert client.post("/api/desktop/quit").status_code == 401  # signed in only
    client.get("/api/auth/desktop", params={"token": TOKEN})
    assert client.post("/api/desktop/quit").json() == {"ok": True}
    import time
    time.sleep(0.5)
    assert quit_calls == [1]


def test_a_running_codetta_is_found_again(tmp_path, monkeypatch):
    desktop._write_running(tmp_path, 1, "tok")
    assert json.loads((tmp_path / "running.json").read_text())["token"] == "tok"
    assert desktop._running(tmp_path) is None  # nothing answers on port 1: start a new one
