"""Lidarr: reading how it's set up, rescans after Codetta changes files, and leaving file names to it."""

import json
import shutil
import stat
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

import codetta.core.lidarr as lidarr_mod
from codetta.core.engine import MetadataEngine
from codetta.core.lidarr import find_folder
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

KEY = "0123456789abcdef0123456789abcdef"
ROOT = "/data/media/music"  # what Lidarr calls the music folder (Codetta calls it something else)


class FakeLidarr:
    def __init__(self, write_tags="no", renames=False, root=ROOT, artists=("Radiohead",)):
        self.write_tags, self.renames, self.root, self.artists = write_tags, renames, root, list(artists)
        self.calls, self.rescans, self.down = [], [], False

    def __call__(self, method, url, headers, body):
        if self.down:
            raise lidarr_mod.LidarrError("Couldn't reach Lidarr: connection refused")
        self.calls.append((method, url, dict(headers)))
        if headers.get("X-Api-Key") != KEY:
            return 401, b""
        path = urllib.parse.urlsplit(url).path.removeprefix("/api/v1")
        if path == "/system/status":
            return 200, json.dumps({"version": "3.1.6.5079"}).encode()
        if path == "/rootfolder":
            return 200, json.dumps([{"path": self.root}]).encode()
        if path == "/artist":
            return 200, json.dumps([{"path": f"{self.root}/{a}"} for a in self.artists]).encode()
        if path == "/config/metadataprovider":
            return 200, json.dumps({"writeAudioTags": self.write_tags}).encode()
        if path == "/config/naming":
            return 200, json.dumps({"renameTracks": self.renames}).encode()
        if path == "/command" and method == "POST":
            self.rescans.append(json.loads(body))
            return 201, b"{}"
        return 404, b""


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(lidarr_mod, "SYNC_QUIET_SECONDS", 0.05)


@pytest.fixture
def music(tmp_path):
    album = tmp_path / "music" / "Radiohead" / "In Rainbows (2007)"
    album.mkdir(parents=True)
    e = MetadataEngine()
    for n, title in ((1, "15 Step"), (2, "Bodysnatchers")):
        f = album / f"0{n} - {title}.flac"
        shutil.copy2(FIXTURES_DIR / "sample.flac", f)
        e.update_tags(f, {"title": title, "artist": "Radiohead", "albumartist": "Radiohead", "album": "In Rainbows",
                          "tracknumber": str(n), "date": "2007"})
    (tmp_path / "music" / "Not Lidarr").mkdir()
    return tmp_path / "music"


def make(music, tmp_path, fake, names="auto", connect=True):
    c = TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config", auth=False), lidarr_request=fake))
    c.__enter__()
    if connect:
        c.put("/api/connections", json={"enabled": {"lidarr": True}})
        r = c.put("/api/lidarr/settings", json={"url": "lidarr:8686", "api_key": KEY, "names": names})
        assert r.status_code == 200, r.text
    return c


def wait_for(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_reads_how_lidarr_is_set_up_and_finds_its_folder(music, tmp_path):
    fake = FakeLidarr(write_tags="allFiles", renames=True)
    c = make(music, tmp_path, fake)
    d = c.get("/api/lidarr").json()
    assert d["check"]["ok"] and d["check"]["version"] == "3.1.6.5079"
    assert d["check"]["roots"] == [{"lidarr": ROOT, "folder": ""}]  # /data/media/music is Codetta's music folder
    assert d["names_by_lidarr"] is True
    assert [w["id"] for w in d["warnings"]] == ["write_tags"]  # Lidarr would undo tag fixes
    assert KEY not in json.dumps(d) and d["has_key"] is True  # the key never goes back to the page
    c.__exit__(None, None, None)


def test_a_lidarr_root_inside_a_library_subfolder_is_found(tmp_path):
    (tmp_path / "lib" / "Lidarr" / "Radiohead").mkdir(parents=True)
    (tmp_path / "lib" / "Other" / "Someone").mkdir(parents=True)
    assert find_folder("/music", ["/music/Radiohead"], tmp_path / "lib") == "Lidarr"
    assert find_folder("/music", ["/music/Nobody Here"], tmp_path / "lib") is None  # not this library: no guessing


def test_folders_lidarr_cant_see_get_a_warning(music, tmp_path):
    c = make(music, tmp_path, FakeLidarr(artists=["Someone Else"]))
    d = c.get("/api/lidarr").json()
    assert d["check"]["roots"][0]["folder"] is None and "no_folders" in [w["id"] for w in d["warnings"]]
    c.__exit__(None, None, None)


def test_a_tag_edit_asks_lidarr_to_rescan_that_album(music, tmp_path):
    fake = FakeLidarr()
    c = make(music, tmp_path, fake)
    r = c.patch("/api/tracks", json={"paths": ["Radiohead/In Rainbows (2007)/01 - 15 Step.flac"], "changes": {"genre": "Art Rock"}})
    assert r.json()[0]["ok"]
    assert wait_for(lambda: fake.rescans)
    assert fake.rescans == [{"name": "RescanFolders", "folders": [f"{ROOT}/Radiohead/In Rainbows (2007)"]}]  # in Lidarr's words
    c.__exit__(None, None, None)


def test_moved_files_rescan_both_the_old_and_new_place(music, tmp_path):
    fake = FakeLidarr()  # Lidarr doesn't rename, so Codetta's pattern names files
    c = make(music, tmp_path, fake)
    r = c.post("/api/organize/apply", json={"folder": "Radiohead/In Rainbows (2007)", "pattern": "{albumartist}/{album}/{title}"})
    assert r.json()["moved"] == 2
    assert wait_for(lambda: fake.rescans)
    folders = set(fake.rescans[-1]["folders"])
    # The old album folder is gone: Lidarr is asked about its nearest folder (the artist's).
    assert folders == {f"{ROOT}/Radiohead", f"{ROOT}/Radiohead/In Rainbows"}
    c.__exit__(None, None, None)


def test_files_in_lidarrs_folders_keep_their_names_while_lidarr_renames(music, tmp_path):
    c = make(music, tmp_path, FakeLidarr(renames=True))
    p = c.post("/api/organize/preview", json={"folder": "Radiohead/In Rainbows (2007)", "pattern": "{albumartist}/{album}/{title}"}).json()
    assert p["counts"]["lidarr"] == 2 and p["counts"]["move"] == 0
    assert "Lidarr names the files" in p["moves"][0]["reason"]
    r = c.post("/api/organize/apply", json={"folder": "Radiohead/In Rainbows (2007)", "pattern": "{albumartist}/{album}/{title}"}).json()
    assert r["moved"] == 0 and {h["status"] for h in r["held"]} == {"lidarr"}
    assert (music / "Radiohead" / "In Rainbows (2007)" / "01 - 15 Step.flac").exists()
    c.__exit__(None, None, None)


def test_choosing_codetta_for_names_lets_organize_move_them(music, tmp_path):
    c = make(music, tmp_path, FakeLidarr(renames=True), names="codetta")
    d = c.get("/api/lidarr").json()
    assert d["names_by_lidarr"] is False and "both_rename" in [w["id"] for w in d["warnings"]]
    r = c.post("/api/organize/apply", json={"folder": "Radiohead/In Rainbows (2007)", "pattern": "{albumartist}/{album}/{title}"}).json()
    assert r["moved"] == 2
    c.__exit__(None, None, None)


def test_with_the_connection_off_lidarr_hears_nothing(music, tmp_path):
    fake = FakeLidarr(renames=True)
    c = make(music, tmp_path, fake, connect=False)
    c.patch("/api/tracks", json={"paths": ["Radiohead/In Rainbows (2007)/01 - 15 Step.flac"], "changes": {"genre": "Art Rock"}})
    r = c.post("/api/organize/apply", json={"folder": "Radiohead/In Rainbows (2007)", "pattern": "{albumartist}/{album}/{title}"}).json()
    assert r["moved"] == 2  # no Lidarr connection: Organize works as always
    time.sleep(0.2)
    assert fake.calls == []
    c.__exit__(None, None, None)


def test_an_unreachable_lidarr_never_gets_in_the_way(music, tmp_path):
    fake = FakeLidarr()
    c = make(music, tmp_path, fake)
    fake.down = True
    r = c.post("/api/lidarr/test").json()
    assert r["check"]["ok"] is False and "Couldn't reach Lidarr" in r["check"]["error"]
    assert c.patch("/api/tracks", json={"paths": ["Radiohead/In Rainbows (2007)/01 - 15 Step.flac"],
                                        "changes": {"genre": "Art Rock"}}).json()[0]["ok"]
    c.__exit__(None, None, None)


def test_a_wrong_key_is_explained(music, tmp_path):
    c = make(music, tmp_path, FakeLidarr(), connect=False)
    c.put("/api/connections", json={"enabled": {"lidarr": True}})
    d = c.put("/api/lidarr/settings", json={"url": "lidarr:8686", "api_key": "f" * 32}).json()
    assert d["check"]["ok"] is False and "API key" in d["check"]["error"]
    c.__exit__(None, None, None)


@pytest.mark.parametrize("url", ["ftp://lidarr", "http://user:pw@lidarr:8686", "http://lidarr:port", "http://lid arr", "http://lidarr/?x=1"])
def test_odd_addresses_are_refused(music, tmp_path, url):
    c = make(music, tmp_path, FakeLidarr(), connect=False)
    assert c.put("/api/lidarr/settings", json={"url": url, "api_key": KEY}).status_code == 422
    c.__exit__(None, None, None)


def test_the_settings_file_is_owner_only(music, tmp_path):
    c = make(music, tmp_path, FakeLidarr())
    mode = stat.S_IMODE((tmp_path / "config" / "lidarr.json").stat().st_mode)
    assert mode == 0o600
    assert c.put("/api/lidarr/settings", json={"url": "lidarr:8686", "api_key": "short"}).status_code == 422
    c.__exit__(None, None, None)
