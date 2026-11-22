"""Save covers as files: cover.jpg next to the music, never clobbering, fully undoable."""

import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

JPG = (FIXTURES_DIR / "cover.jpg").read_bytes()
PNG = (FIXTURES_DIR / "cover.png").read_bytes()


@pytest.fixture
def lib(tmp_path):
    e = MetadataEngine()
    music = tmp_path / "music"
    for folder, art in (("A/Jpeg Album", JPG), ("A/Png Album", PNG), ("A/Bare Album", None), ("A/Disc Album/CD1", JPG)):
        d = music / folder
        d.mkdir(parents=True)
        shutil.copy2(FIXTURES_DIR / "sample.flac", d / "01.flac")
        e.update_artwork(d / "01.flac", art)
    return music


@pytest.fixture
def client(lib, tmp_path):
    with TestClient(create_app(Settings(music_dir=lib, config_dir=tmp_path / "config", auth=False))) as c:
        yield c


def statuses(d):
    return {p["folder"]: p["status"] for p in d["preview"]}


def test_preview_shows_each_album_and_writes_nothing(client, lib):
    d = client.post("/api/covers/export", json={"folder": "A"}).json()
    assert statuses(d) == {"A/Jpeg Album": "write", "A/Png Album": "write", "A/Bare Album": "no_cover", "A/Disc Album": "write"}
    assert {p["folder"]: p.get("file") for p in d["preview"]}["A/Png Album"] == "cover.png"  # a PNG stays PNG
    assert not (lib / "A/Jpeg Album/cover.jpg").exists()


def test_covers_are_written_next_to_the_music_and_undo_removes_them(client, lib):
    r = client.post("/api/covers/export", json={"folder": "A", "dry_run": False}).json()
    assert r["written"] == 3
    assert (lib / "A/Jpeg Album/cover.jpg").read_bytes() == JPG
    assert (lib / "A/Png Album/cover.png").read_bytes() == PNG
    assert (lib / "A/Disc Album/cover.jpg").exists() and not (lib / "A/Disc Album/CD1/cover.jpg").exists()  # the album folder
    entry = client.get("/api/activity").json()[0]
    assert entry["message"] == "Exported covers: 3 albums"
    client.post(f"/api/activity/{entry['id']}/undo")
    assert not (lib / "A/Jpeg Album/cover.jpg").exists() and not (lib / "A/Png Album/cover.png").exists()
    redo = client.get("/api/activity").json()[0]
    client.post(f"/api/activity/{redo['id']}/undo")  # and redo brings them back
    assert (lib / "A/Jpeg Album/cover.jpg").read_bytes() == JPG


def test_an_existing_image_is_kept_unless_replace_and_undo_restores_it(client, lib):
    old = b"\xff\xd8\xff old cover"
    (lib / "A/Jpeg Album/cover.jpg").write_bytes(old)
    (lib / "A/Png Album/Cover.JPG").write_bytes(old)  # another name in the same family counts too
    d = client.post("/api/covers/export", json={"folder": "A"}).json()
    assert statuses(d)["A/Jpeg Album"] == "exists" and statuses(d)["A/Png Album"] == "exists"
    client.post("/api/covers/export", json={"paths": ["A/Jpeg Album/01.flac"], "replace": True, "dry_run": False})
    assert (lib / "A/Jpeg Album/cover.jpg").read_bytes() == JPG
    entry = client.get("/api/activity").json()[0]
    client.post(f"/api/activity/{entry['id']}/undo")
    assert (lib / "A/Jpeg Album/cover.jpg").read_bytes() == old  # the old one is back, byte for byte


def test_folder_and_front_names_and_already_done(client, lib):
    client.post("/api/covers/export", json={"folder": "A/Jpeg Album", "name": "folder", "dry_run": False})
    assert (lib / "A/Jpeg Album/folder.jpg").read_bytes() == JPG
    d = client.post("/api/covers/export", json={"folder": "A/Jpeg Album", "name": "folder", "replace": True}).json()
    assert statuses(d)["A/Jpeg Album"] == "same" and d["writing"] == 0


def test_undo_leaves_a_cover_file_changed_since(client, lib):
    client.post("/api/covers/export", json={"folder": "A/Jpeg Album", "dry_run": False})
    (lib / "A/Jpeg Album/cover.jpg").write_bytes(b"edited by hand")
    entry = client.get("/api/activity").json()[0]
    client.post(f"/api/activity/{entry['id']}/undo")
    assert (lib / "A/Jpeg Album/cover.jpg").read_bytes() == b"edited by hand"


def test_paths_stay_in_the_library(client):
    assert client.post("/api/covers/export", json={"paths": ["../x.flac"]}).status_code in (400, 422)
    assert client.post("/api/covers/export", json={"paths": ["@inbox/x.flac"]}).status_code == 422
