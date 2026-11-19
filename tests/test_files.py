"""The right-click / long-press menu: Rename, Move to, Delete (to Recently deleted), Get info."""

import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


@pytest.fixture
def setup(tmp_path):
    music, config = tmp_path / "music", tmp_path / "config"
    album = music / "Artist" / "Album"
    album.mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.flac", album / "01 Song.flac")
    (album / "01 Song.lrc").write_text("[00:01.00] la")
    shutil.copy2(FIXTURES_DIR / "sample.mp3", album / "02 Other.mp3")
    (music / "Elsewhere").mkdir()
    with TestClient(create_app(Settings(music_dir=music, config_dir=config, auth=False))) as c:
        yield c, music, config


def undo_latest(c):
    entry = c.get("/api/activity").json()[0]
    assert entry["can_undo"]
    return c.post(f"/api/activity/{entry['id']}/undo").json()


def test_move_a_file_with_its_lyrics_then_undo(setup):
    c, music, _ = setup
    res = c.post("/api/files/move", json={"paths": ["Artist/Album/01 Song.flac"], "to": "Elsewhere"}).json()
    assert res["moved"] == 1 and res["failed"] == 0
    assert (music / "Elsewhere" / "01 Song.flac").exists() and (music / "Elsewhere" / "01 Song.lrc").exists()
    assert not (music / "Artist" / "Album" / "01 Song.flac").exists()
    undo_latest(c)
    assert (music / "Artist" / "Album" / "01 Song.flac").exists() and (music / "Artist" / "Album" / "01 Song.lrc").exists()


def test_move_a_folder_and_never_into_itself(setup):
    c, music, _ = setup
    assert c.post("/api/files/move", json={"paths": ["Artist"], "to": "Artist/Album"}).status_code == 422
    res = c.post("/api/files/move", json={"paths": ["Artist/Album"], "to": "Elsewhere"}).json()
    assert res["moved"] == 3  # both songs and the lyrics file
    assert (music / "Elsewhere" / "Album" / "02 Other.mp3").exists() and not (music / "Artist" / "Album").exists()


def test_move_never_overwrites(setup):
    c, music, _ = setup
    (music / "Elsewhere" / "02 Other.mp3").write_bytes(b"different")
    res = c.post("/api/files/move", json={"paths": ["Artist/Album/02 Other.mp3"], "to": "Elsewhere"}).json()
    assert res["failed"] == 1 and (music / "Elsewhere" / "02 Other.mp3").read_bytes() == b"different"


def test_rename_keeps_the_extension_and_the_lyrics_follow(setup):
    c, music, _ = setup
    res = c.post("/api/files/rename", json={"path": "Artist/Album/01 Song.flac", "name": "01 Better Name"}).json()
    assert res["path"] == "Artist/Album/01 Better Name.flac"
    assert (music / "Artist" / "Album" / "01 Better Name.lrc").exists()
    shutil.copy2(FIXTURES_DIR / "sample.flac", music / "Artist" / "Album" / "03 Taken.flac")
    assert c.post("/api/files/rename", json={"path": "Artist/Album/01 Better Name.flac", "name": "03 Taken"}).status_code == 409
    undo_latest(c)
    assert (music / "Artist" / "Album" / "01 Song.flac").exists()


def test_delete_goes_to_recently_deleted_and_can_be_undone(setup):
    c, music, config = setup
    res = c.post("/api/files/delete", json={"paths": ["Artist/Album"]}).json()
    assert res["moved"] == 3 and not (music / "Artist" / "Album").exists()
    kept = list((config / "deleted").rglob("*.flac"))
    assert len(kept) == 1 and kept[0].name == "01 Song.flac"  # nothing is erased, just set aside
    entry = c.get("/api/activity").json()[0]
    assert entry["kind"] == "delete" and "Recently deleted" in entry["message"]
    undo_latest(c)
    assert (music / "Artist" / "Album" / "01 Song.flac").exists() and (music / "Artist" / "Album" / "01 Song.lrc").exists()


def test_paths_outside_the_library_are_refused(setup):
    c, _, _ = setup
    for body in ({"paths": ["../x"]}, {"paths": ["@deleted/x"]}, {"paths": [""]}):
        assert c.post("/api/files/delete", json=body).status_code in (400, 422)
    assert c.post("/api/files/move", json={"paths": ["Artist"], "to": "@deleted"}).status_code == 404


def test_get_info_for_a_file_and_a_folder(setup):
    c, _, _ = setup
    f = c.get("/api/files/info", params={"path": "Artist/Album/01 Song.flac"}).json()
    assert f["kind"] == "file" and f["format"] == "flac" and f["size"] > 0 and f["sample_rate"] == 44100
    assert f["tag_kind"] == "Vorbis comments" and f["bits_per_sample"]
    m = c.get("/api/files/info", params={"path": "Artist/Album/02 Other.mp3"}).json()
    assert m["tag_kind"].startswith("ID3v2")
    d = c.get("/api/files/info", params={"path": "Artist"}).json()
    assert d["kind"] == "folder" and d["audio"] == 2 and d["files"] == 3 and d["folders"] == 1


def test_folder_picker_lists_only_folders(setup):
    c, _, _ = setup
    assert c.get("/api/folders").json()["folders"] == [{"name": "Artist", "path": "Artist"}, {"name": "Elsewhere", "path": "Elsewhere"}]
    assert c.get("/api/folders", params={"path": "Artist"}).json()["folders"] == [{"name": "Album", "path": "Artist/Album"}]


def test_the_menu_routes_need_sign_in(tmp_path):
    with TestClient(create_app(Settings(music_dir=tmp_path, config_dir=tmp_path / "c"))) as c:
        for method, url in [("post", "/api/files/move"), ("post", "/api/files/rename"), ("post", "/api/files/delete"),
                            ("get", "/api/files/info?path=x"), ("get", "/api/folders")]:
            assert getattr(c, method)(url, json={}).status_code == 401 if method == "post" else c.get(url).status_code == 401
