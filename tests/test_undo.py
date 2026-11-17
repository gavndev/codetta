"""Tests for undo from the activity log."""

import shutil

import mutagen
import pytest
from fastapi.testclient import TestClient

from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

JPEG = (FIXTURES_DIR / "cover.jpg").read_bytes()
PNG = (FIXTURES_DIR / "cover.png").read_bytes()


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "music"
    album = root / "Album"
    album.mkdir(parents=True)
    for i, (src, title) in enumerate([("sample.flac", "One"), ("sample.mp3", "Two"), ("sample.m4a", "Three")], 1):
        dest = album / f"0{i}.{src.split('.')[1]}"
        shutil.copy2(FIXTURES_DIR / src, dest)
        f = mutagen.File(dest, easy=True)
        f["title"] = [title]
        f["genre"] = [f"Genre {i}"]  # every file starts with a different genre
        f.save()
    return root


@pytest.fixture
def settings(music, tmp_path):
    return Settings(music_dir=music, config_dir=tmp_path / "config")


def signed_in(c):
    if c.get("/api/auth/status").json()["setup_required"]:
        c.post("/api/auth/setup", json={"username": "gavin", "password": "correct horse 1"})
    else:
        c.post("/api/auth/login", json={"username": "gavin", "password": "correct horse 1"})
    return c


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield signed_in(c)


PATHS = ["Album/01.flac", "Album/02.mp3", "Album/03.m4a"]


def tags(c, path):
    return c.get("/api/track", params={"path": path}).json()["tags"]


def latest(c):
    return c.get("/api/activity").json()[0]


def test_undo_batch_edit_restores_each_files_own_value(client):
    client.patch("/api/tracks", json={"paths": PATHS, "changes": {"genre": "Jazz", "mood": "Calm"}})
    assert [tags(client, p)["genre"] for p in PATHS] == [["Jazz"]] * 3
    entry = latest(client)
    assert entry["can_undo"] is True and "undo" not in entry  # big undo data never sent to the browser

    res = client.post(f"/api/activity/{entry['id']}/undo").json()

    assert res["undone"] == 3 and res["skipped"] == 0
    assert [tags(client, p)["genre"] for p in PATHS] == [["Genre 1"], ["Genre 2"], ["Genre 3"]]
    assert all("mood" not in tags(client, p) for p in PATHS)  # an added tag is removed again
    log = client.get("/api/activity").json()
    assert log[0]["kind"] == "undo" and log[0]["undoes"] == entry["id"]
    assert log[1]["undone"] is True and log[1]["can_undo"] is False


def test_undo_leaves_files_edited_since_alone(client):
    client.patch("/api/tracks", json={"paths": PATHS, "changes": {"genre": "Jazz"}})
    entry = latest(client)
    client.patch("/api/tracks", json={"paths": ["Album/02.mp3"], "changes": {"genre": "Blues"}})  # newer edit

    res = client.post(f"/api/activity/{entry['id']}/undo").json()

    assert (res["undone"], res["skipped"]) == (2, 1)
    assert tags(client, "Album/01.flac")["genre"] == ["Genre 1"]
    assert tags(client, "Album/02.mp3")["genre"] == ["Blues"]  # the newer edit is kept
    assert tags(client, "Album/03.m4a")["genre"] == ["Genre 3"]


def test_undo_twice_is_refused_and_redo_works(client):
    client.patch("/api/tracks", json={"paths": ["Album/01.flac"], "changes": {"title": "Changed"}})
    original = latest(client)
    client.post(f"/api/activity/{original['id']}/undo")
    assert client.post(f"/api/activity/{original['id']}/undo").status_code == 409
    assert tags(client, "Album/01.flac")["title"] == ["One"]

    undo_entry = latest(client)
    assert undo_entry["can_undo"] is True
    client.post(f"/api/activity/{undo_entry['id']}/undo")  # redo
    assert tags(client, "Album/01.flac")["title"] == ["Changed"]
    log = {e["id"]: e for e in client.get("/api/activity").json()}
    assert log[original["id"]]["undone"] is False  # the original change is back in effect
    assert log[undo_entry["id"]]["undone"] is True


@pytest.mark.parametrize("path", PATHS)
def test_undo_adding_art_removes_it(client, path):
    client.put("/api/art", params={"path": path}, content=JPEG, headers={"Content-Type": "image/jpeg"})
    client.post(f"/api/activity/{latest(client)['id']}/undo")
    assert client.get("/api/art", params={"path": path}).status_code == 404


def test_undo_replacing_and_removing_art_restores_the_old_image(client):
    p = "Album/01.flac"
    client.put("/api/art", params={"path": p}, content=JPEG, headers={"Content-Type": "image/jpeg"})
    client.put("/api/art", params={"path": p}, content=PNG, headers={"Content-Type": "image/png"})
    client.post(f"/api/activity/{latest(client)['id']}/undo")
    assert client.get("/api/art", params={"path": p}).content == JPEG

    client.delete("/api/art", params={"path": p})
    client.post(f"/api/activity/{latest(client)['id']}/undo")
    assert client.get("/api/art", params={"path": p}).content == JPEG


def test_undo_art_skips_if_art_changed_since(client):
    p = "Album/01.flac"
    client.put("/api/art", params={"path": p}, content=JPEG, headers={"Content-Type": "image/jpeg"})
    entry = latest(client)
    client.put("/api/art", params={"path": p}, content=PNG, headers={"Content-Type": "image/png"})
    res = client.post(f"/api/activity/{entry['id']}/undo").json()
    assert res["skipped"] == 1
    assert client.get("/api/art", params={"path": p}).content == PNG


def test_undo_loadout(client):
    client.post("/api/loadouts/apply", json={"name": "Album Folder", "folder": "Album", "mode": "overwrite", "dry_run": False})
    assert tags(client, "Album/02.mp3")["tracknumber"] == ["2/3"]
    client.post(f"/api/activity/{latest(client)['id']}/undo")
    t = tags(client, "Album/02.mp3")
    assert t["title"] == ["Two"] and t["genre"] == ["Genre 2"]
    assert t["tracknumber"] == ["3/12"]  # the fixture's original value


def test_undo_survives_restart(settings):
    with TestClient(create_app(settings)) as c:
        signed_in(c)
        c.patch("/api/tracks", json={"paths": ["Album/01.flac"], "changes": {"title": "Changed"}})
        c.put("/api/art", params={"path": "Album/01.flac"}, content=JPEG, headers={"Content-Type": "image/jpeg"})
        art_id, edit_id = [e["id"] for e in c.get("/api/activity").json()][:2]
    with TestClient(create_app(settings)) as c:
        signed_in(c)
        assert c.post(f"/api/activity/{art_id}/undo").json()["undone"] == 1
        assert c.post(f"/api/activity/{edit_id}/undo").json()["undone"] == 1
        assert tags(c, "Album/01.flac")["title"] == ["One"]


def test_unused_art_is_pruned_on_startup(settings):
    store = settings.config_dir / "undo-art"
    store.mkdir(parents=True)
    (store / ("0" * 64)).write_bytes(b"orphan")
    with TestClient(create_app(settings)) as c:
        signed_in(c)
        c.put("/api/art", params={"path": "Album/01.flac"}, content=JPEG, headers={"Content-Type": "image/jpeg"})
    with TestClient(create_app(settings)):
        names = {p.name for p in store.iterdir()}
    assert "0" * 64 not in names and len(names) == 1  # the JPEG stays, the orphan goes


def test_undo_errors(client):
    assert client.post("/api/activity/999/undo").status_code == 404
    client.patch("/api/tracks", json={"paths": ["Album/01.flac"], "changes": {"made_up_tag_on_mp3": "x"}})
    # FLAC accepts any tag, so that succeeded; an entry with nothing to undo:
    client.patch("/api/tracks", json={"paths": ["Album/02.mp3"], "changes": {"made_up": "x"}})  # fails on MP3
    failed = latest(client)
    assert failed["can_undo"] is False
    assert client.post(f"/api/activity/{failed['id']}/undo").status_code == 422


def test_undo_requires_sign_in(settings):
    with TestClient(create_app(settings)) as c:
        signed_in(c)
        c.patch("/api/tracks", json={"paths": ["Album/01.flac"], "changes": {"title": "X"}})
        entry_id = c.get("/api/activity").json()[0]["id"]
        c.cookies.clear()
        assert c.post(f"/api/activity/{entry_id}/undo").status_code == 401
