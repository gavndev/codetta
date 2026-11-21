"""Music servers: Navidrome (Subsonic), Jellyfin, Emby and Plex hear about Codetta's changes."""

import hashlib
import json
import shutil
import stat
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

import codetta.core.mediaserver as ms
from codetta.core.engine import MetadataEngine
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

PASSWORD = "s3cret pass"
TOKEN = "0123456789abcdef0123456789abcdef"
TRACK = "Radiohead/In Rainbows (2007)/01 - 15 Step.flac"


class FakeSubsonic:
    """Navidrome's Subsonic API: token sign-in (md5(password + salt))."""

    def __init__(self, admin=True, token_auth=True, kind="navidrome"):
        self.admin, self.token_auth, self.kind = admin, token_auth, kind
        self.calls, self.scans, self.down = [], 0, False

    def __call__(self, method, url, headers, body):
        if self.down:
            raise ms.ServerError("Couldn't reach the server: connection refused")
        u = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.calls.append((u.path, q))
        if not u.path.startswith("/rest/"):
            return 404, b""

        def out(extra=None, error=None):
            r = {"status": "failed" if error else "ok", "version": "1.16.1", "type": self.kind,
                 "serverVersion": "0.64.2", "openSubsonic": True, **(extra or {})}
            if error:
                r["error"] = {"code": error[0], "message": error[1]}
            return 200, json.dumps({"subsonic-response": r}).encode()

        if "t" in q:
            if not self.token_auth:
                return out(error=(41, "Token authentication not supported"))
            ok = q.get("u") == "admin" and hashlib.md5((PASSWORD + q["s"]).encode()).hexdigest() == q["t"]
        else:
            ok = q.get("u") == "admin" and q.get("p") == "enc:" + PASSWORD.encode().hex()
        if not ok:
            return out(error=(40, "Wrong username or password"))
        what = u.path.removeprefix("/rest/")
        if what == "ping":
            return out()
        if what == "getMusicFolders":
            return out({"musicFolders": {"musicFolder": [{"id": 1, "name": "Music"}]}})
        if what == "getUser":
            return out({"user": {"username": "admin", "adminRole": self.admin}})
        if what == "startScan":
            if not self.admin:
                return out(error=(50, "User not authorized"))
            self.scans += 1
            return out({"scanStatus": {"scanning": True, "count": 0}})
        return out(error=(70, "Not found"))


class FakeJellyfin:
    def __init__(self, product="Jellyfin Server"):
        self.product, self.calls, self.refreshed = product, [], []

    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlsplit(url)
        self.calls.append((method, u.path, dict(headers)))
        if headers.get("Authorization") != f'MediaBrowser Client="Codetta", Token="{TOKEN}"' and headers.get("X-Emby-Token") != TOKEN:
            return 401, b""
        if u.path == "/System/Info":
            return 200, json.dumps({"ProductName": self.product, "Version": "10.11.2"}).encode()
        if u.path == "/Library/VirtualFolders":
            return 200, json.dumps([{"Name": "Movies", "CollectionType": "movies", "ItemId": "m1"},
                                    {"Name": "Music", "CollectionType": "music", "ItemId": "a1"}]).encode()
        if method == "POST" and u.path.endswith("/Refresh"):
            self.refreshed.append(u.path)
            return 204, b""
        return 404, b""


class FakePlex:
    def __init__(self):
        self.refreshed = []

    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlsplit(url)
        if headers.get("X-Plex-Token") != TOKEN:
            return 401, b""
        if u.path == "/":
            return 200, json.dumps({"MediaContainer": {"version": "1.41.3"}}).encode()
        if u.path == "/library/sections":
            return 200, json.dumps({"MediaContainer": {"Directory": [
                {"key": "1", "type": "movie", "title": "Films"}, {"key": "4", "type": "artist", "title": "Music"}]}}).encode()
        if u.path.endswith("/refresh"):
            self.refreshed.append(u.path)
            return 200, b""
        return 404, b""


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(ms, "SCAN_QUIET_SECONDS", 0.05)
    monkeypatch.setattr(ms, "SCAN_GAP_SECONDS", 0.0)


@pytest.fixture
def music(tmp_path):
    album = tmp_path / "music" / "Radiohead" / "In Rainbows (2007)"
    album.mkdir(parents=True)
    f = album / "01 - 15 Step.flac"
    shutil.copy2(FIXTURES_DIR / "sample.flac", f)
    MetadataEngine().update_tags(f, {"title": "15 Step", "artist": "Radiohead", "album": "In Rainbows"})
    return tmp_path / "music"


def make(music, tmp_path, fake, settings=None, connect=True, env=None):
    c = TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config", auth=False,
                                       media_server_env=env), server_request=fake))
    c.__enter__()
    if connect:
        c.put("/api/connections", json={"enabled": {"mediaserver": True}})
        r = c.put("/api/mediaserver/settings", json=settings or {"kind": "subsonic", "url": "navidrome:4533",
                                                                  "username": "admin", "password": PASSWORD})
        assert r.status_code == 200, r.text
    return c


def wait_for(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def edit(c):
    r = c.patch("/api/tracks", json={"paths": [TRACK], "changes": {"genre": "Art Rock"}})
    assert r.json()[0]["ok"]


def test_navidrome_is_found_and_scans_after_an_edit(music, tmp_path):
    fake = FakeSubsonic()
    c = make(music, tmp_path, fake)
    d = c.get("/api/mediaserver").json()
    assert d["check"]["ok"] and d["check"]["name"] == "Navidrome" and d["check"]["version"] == "0.64.2"
    assert PASSWORD not in json.dumps(d) and d["has_password"] is True
    assert all("p" not in q for _, q in fake.calls)  # token sign-in: the password itself never travels
    edit(c)
    assert wait_for(lambda: fake.scans == 1)
    assert c.get("/api/mediaserver").json()["last_scan"]["error"] == ""
    c.__exit__(None, None, None)


def test_a_batch_of_changes_means_one_scan(music, tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "SCAN_QUIET_SECONDS", 0.3)
    fake = FakeSubsonic()
    c = make(music, tmp_path, fake)
    for genre in ("A", "B", "C"):
        c.patch("/api/tracks", json={"paths": [TRACK], "changes": {"genre": genre}})
    assert wait_for(lambda: fake.scans >= 1)
    time.sleep(0.5)
    assert fake.scans == 1
    c.__exit__(None, None, None)


def test_a_navidrome_user_who_isnt_admin_is_told(music, tmp_path):
    fake = FakeSubsonic(admin=False)
    c = make(music, tmp_path, fake)
    d = c.get("/api/mediaserver").json()
    assert d["check"]["ok"] and d["check"]["can_scan"] is False and "admin" in d["check"]["note"]
    r = c.post("/api/mediaserver/scan").json()
    assert "admin" in r["last_scan"]["error"]
    c.__exit__(None, None, None)


def test_servers_without_token_sign_in_get_the_encoded_password(music, tmp_path):
    fake = FakeSubsonic(token_auth=False, kind="ampache")
    c = make(music, tmp_path, fake)
    d = c.get("/api/mediaserver").json()
    assert d["check"]["ok"] and d["check"]["name"] == "Ampache"
    c.__exit__(None, None, None)


def test_a_wrong_password_is_explained(music, tmp_path):
    c = make(music, tmp_path, FakeSubsonic(), settings={"kind": "subsonic", "url": "navidrome:4533",
                                                        "username": "admin", "password": "nope"})
    d = c.get("/api/mediaserver").json()
    assert d["check"]["ok"] is False and "username or password" in d["check"]["error"]
    c.__exit__(None, None, None)


def test_jellyfin_refreshes_only_its_music_library(music, tmp_path):
    fake = FakeJellyfin()
    c = make(music, tmp_path, fake, settings={"kind": "jellyfin", "url": "http://jellyfin:8096", "token": TOKEN})
    d = c.get("/api/mediaserver").json()
    assert d["check"]["ok"] and d["check"]["libraries"] == [{"id": "a1", "name": "Music"}]
    assert TOKEN not in json.dumps(d)
    edit(c)
    assert wait_for(lambda: fake.refreshed)
    assert fake.refreshed == ["/Items/a1/Refresh"]  # never the films
    c.__exit__(None, None, None)


def test_emby_signs_in_its_own_way(music, tmp_path):
    fake = FakeJellyfin(product="Emby Server")
    c = make(music, tmp_path, fake, settings={"kind": "emby", "url": "emby:8096", "token": TOKEN})
    assert c.get("/api/mediaserver").json()["check"]["name"] == "Emby"
    assert fake.calls[-1][2].get("X-Emby-Token") == TOKEN
    c.__exit__(None, None, None)


def test_plex_scans_its_music_sections(music, tmp_path):
    fake = FakePlex()
    c = make(music, tmp_path, fake, settings={"kind": "plex", "url": "plex:32400", "token": TOKEN})
    d = c.get("/api/mediaserver").json()
    assert d["check"]["ok"] and d["check"]["version"] == "1.41.3"
    assert c.post("/api/mediaserver/scan").json()["last_scan"]["error"] == ""
    assert fake.refreshed == ["/library/sections/4/refresh"]
    c.__exit__(None, None, None)


def test_with_the_connection_off_the_server_hears_nothing(music, tmp_path):
    fake = FakeSubsonic()
    c = make(music, tmp_path, fake, connect=False)
    edit(c)
    time.sleep(0.2)
    assert fake.calls == []
    assert c.post("/api/mediaserver/scan").status_code == 409
    c.__exit__(None, None, None)


def test_an_unreachable_server_never_gets_in_the_way(music, tmp_path):
    fake = FakeSubsonic()
    c = make(music, tmp_path, fake)
    fake.down = True
    edit(c)
    assert wait_for(lambda: c.get("/api/mediaserver").json()["last_scan"]["error"])
    assert "Couldn't reach" in c.post("/api/mediaserver/test").json()["check"]["error"]
    c.__exit__(None, None, None)


def test_switching_kind_forgets_the_old_sign_in(music, tmp_path):
    c = make(music, tmp_path, FakeSubsonic())
    d = c.put("/api/mediaserver/settings", json={"kind": "plex", "url": "plex:32400"}).json()
    assert d["has_password"] is False and d["configured"] is False
    c.__exit__(None, None, None)


@pytest.mark.parametrize("url", ["ftp://navidrome", "http://user:pw@nd:4533", "http://nd:port", "http://n d", "http://nd/?x=1"])
def test_odd_addresses_are_refused(music, tmp_path, url):
    c = make(music, tmp_path, FakeSubsonic(), connect=False)
    assert c.put("/api/mediaserver/settings", json={"url": url}).status_code == 422
    c.__exit__(None, None, None)


def test_settings_file_is_owner_only_and_env_locks_details(music, tmp_path):
    c = make(music, tmp_path, FakeSubsonic())
    assert stat.S_IMODE((tmp_path / "config" / "mediaserver.json").stat().st_mode) == 0o600
    c.__exit__(None, None, None)
    env = {"kind": "plex", "url": "plex:32400", "username": None, "password": None, "token": TOKEN}
    c = make(music, tmp_path / "b", FakePlex(), connect=False, env=env)
    c.put("/api/connections", json={"enabled": {"mediaserver": True}})
    d = c.post("/api/mediaserver/test").json()
    assert d["check"]["ok"] and d["locked"]["token"] and d["kind"] == "plex" and TOKEN not in json.dumps(d)
    c.__exit__(None, None, None)
