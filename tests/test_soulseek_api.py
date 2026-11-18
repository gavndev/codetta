"""Soulseek through slskd, end to end through the API: a fake slskd that
'downloads' by copying fixture files into the inbox; a fake MusicBrainz."""

import json
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from codetta.web.app import Settings, create_app
from tests.test_inbox import ALBUM_DIR, music  # noqa: F401 (fixture)
from tests.test_musicbrainz import PASSWORD, FakeMB
from tests.test_slskd import FakeSlskd

NEW = "Coda Tester/Fixture Album (2024)"


class DownloadingSlskd(FakeSlskd):
    """Every download 'arrives' at once: the files appear in the downloads folder."""

    def __init__(self, source, downloads, sellers=("seller",), fail=()):
        names = sorted(p.name for p in source.iterdir() if p.suffix != ".jpg")
        super().__init__([{"username": u, "hasFreeUploadSlot": True, "uploadSpeed": 1_000_000, "queueLength": i,
                           "files": [{"filename": f"Music\\Coda Tester\\Fixture Album {u}\\{n}",
                                      "size": (source / n).stat().st_size, "bitDepth": 16, "sampleRate": 44100}
                                     for n in names]} for i, u in enumerate(sellers)])
        self.source, self.dl, self.fail = source, downloads, set(fail)

    def __call__(self, method, url, headers, body):
        out = super().__call__(method, url, headers, body)
        path = url.split("/api/v0", 1)[1]
        if method == "POST" and path == "/searches":
            self.searches[json.loads(body)["id"]]["done"] = True
        if method == "POST" and path.startswith("/transfers/downloads/"):
            user = path.rsplit("/", 1)[1]
            if user in self.fail:
                self.finish(user, "Completed, Rejected")
            else:
                for t in json.loads(body):
                    folder, name = t["filename"].rsplit("\\", 2)[-2:]
                    (self.dl / folder).mkdir(parents=True, exist_ok=True)
                    shutil.copy2(self.source / name, self.dl / folder / name)
                self.finish(user)
        return out


@pytest.fixture
def client(music, tmp_path):  # noqa: F811
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    opened = []

    def make(**kw):
        fake = DownloadingSlskd(music / ALBUM_DIR, downloads, **kw)
        app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config", inbox_settle_seconds=0,
                                  inbox_dir=downloads, slskd_poll_seconds=0.02),
                         fetch_mb=FakeMB(), fetch_art=lambda url: None, slskd_request=fake)
        c = TestClient(app)
        c.__enter__()
        opened.append(c)
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.put("/api/connections", json={"enabled": {"musicbrainz": True, "slskd": True}})
        c.put("/api/inbox/settings", json={"folder": "@inbox"})
        return c, fake
    yield make
    for c in opened:
        c.__exit__(None, None, None)


def connect(c):
    return c.put("/api/slskd/settings", json={"url": "slskd:5030", "api_key": "secret"}).json()


def wait_for(c, job_id, done, timeout=10):
    end = time.time() + timeout
    while True:
        data = c.get("/api/slskd").json()
        job = next(j for j in data["jobs"] if j["id"] == job_id)
        c.get("/api/inbox")  # what the page does while it's open
        if done(job):
            return job
        assert time.time() < end, job
        time.sleep(0.05)


def reviewable(job):
    return job["status"] == "arrived" and job["inbox"] and job["inbox"]["status"] in ("ready", "review")


def test_settings_never_send_the_key_back(client, tmp_path):
    c, _ = client()
    data = connect(c)
    assert data["configured"] and data["has_key"] and data["url"] == "http://slskd:5030"
    assert "secret" not in json.dumps(data)
    assert data["check"]["ok"] and data["check"]["shared_folders"] == 1
    # Saving other settings keeps the key.
    data = c.put("/api/slskd/settings", json={"url": "slskd:5030", "review": False}).json()
    assert data["has_key"] and data["settings"]["review"] is False
    c.post("/api/auth/logout")
    assert c.get("/api/slskd").status_code == 401
    assert c.post("/api/slskd/search", json={"query": "x"}).status_code == 401


def test_search_needs_the_connection_and_the_inbox(client):
    c, _ = client()
    assert c.post("/api/slskd/search", json={"query": "Fixture Album"}).status_code == 409  # not connected yet
    connect(c)
    c.put("/api/connections", json={"enabled": {"slskd": False}})
    assert c.post("/api/slskd/search", json={"query": "Fixture Album"}).status_code == 403


def test_search_download_review_import(client, music):  # noqa: F811
    c, fake = client()
    connect(c)
    job = c.post("/api/slskd/search", json={"query": "Coda Tester Fixture Album"}).json()["job"]
    job = wait_for(c, job["id"], reviewable)
    assert job["current"]["username"] == "seller" and job["current"]["quality"]
    assert job["inbox"]["release"]["title"]  # matched on MusicBrainz, but waits for a review (the default)
    assert not (music / NEW).exists()
    kinds = [n["kind"] for n in c.get("/api/notifications").json()["items"]]
    assert "soulseek" in kinds
    res = c.post(f"/api/slskd/jobs/{job['id']}/import").json()
    assert res["status"] == "filed" and res["moved_to"] == NEW
    assert (music / NEW / "01 Opening.flac").exists()
    assert next(j for j in res["jobs"] if j["id"] == job["id"])["status"] == "imported"


def test_automatic_mode_files_by_itself(client, music):  # noqa: F811
    c, _ = client()
    connect(c)
    c.put("/api/slskd/settings", json={"url": "slskd:5030", "review": False})
    job = c.post("/api/slskd/search", json={"query": "Coda Tester Fixture Album"}).json()["job"]
    wait_for(c, job["id"], lambda j: j["status"] == "imported")
    assert (music / NEW / "01 Opening.flac").exists()


def test_blocklist_and_try_next(client, tmp_path):
    c, fake = client(sellers=("first", "second"))
    connect(c)
    job = c.post("/api/slskd/search", json={"query": "Coda Tester Fixture Album"}).json()["job"]
    job = wait_for(c, job["id"], reviewable)
    assert job["current"]["username"] == "first"
    first_dir = tmp_path / "downloads" / "Fixture Album first"
    assert first_dir.is_dir()
    data = c.post(f"/api/slskd/jobs/{job['id']}/next", json={"block": True}).json()
    assert data["blocked"] == 1 and not first_dir.exists()  # what came is deleted from the downloads folder
    job = wait_for(c, job["id"], reviewable)
    assert job["current"]["username"] == "second"
    # A new search never offers the blocklisted folder again.
    again = c.post("/api/slskd/search", json={"query": "Coda Tester Fixture Album"}).json()["job"]
    again = wait_for(c, again["id"], lambda j: j["status"] != "searching")
    assert [x["username"] for x in again["candidates"]] == ["second"]
    assert c.delete("/api/slskd/blocklist").json()["blocked"] == 0


def test_failed_seller_falls_through(client):
    c, _ = client(sellers=("flaky", "good"), fail=("flaky",))
    connect(c)
    job = c.post("/api/slskd/search", json={"query": "Coda Tester Fixture Album"}).json()["job"]
    job = wait_for(c, job["id"], reviewable)
    assert job["current"]["username"] == "good" and job["candidates"][0]["tried"]


def test_upgrade_replaces_the_old_album_and_can_be_undone(client, music, tmp_path):  # noqa: F811
    old = music / NEW
    old.mkdir(parents=True)
    (old / "01 Opening.mp3").write_bytes(b"old lossy copy")
    (old / "cover.jpg").write_bytes(b"old cover")
    c, _ = client()
    connect(c)
    assert c.post("/api/slskd/search", json={"query": "x y", "upgrade": "../etc"}).status_code in (400, 422)
    job = c.post("/api/slskd/search", json={"query": "Coda Tester Fixture Album", "upgrade": NEW}).json()["job"]
    job = wait_for(c, job["id"], reviewable)
    assert job["upgrade"] == NEW
    res = c.post(f"/api/slskd/jobs/{job['id']}/import").json()
    assert res["status"] == "filed", res
    assert (old / "01 Opening.flac").exists() and not (old / "01 Opening.mp3").exists()
    kept = list((tmp_path / "config" / "replaced").rglob("01 Opening.mp3"))
    assert len(kept) == 1 and kept[0].read_bytes() == b"old lossy copy"
    entries = c.get("/api/activity").json()
    aside = next(e for e in entries if e["message"].startswith("Set aside"))
    # Undo the filing, then the set-aside: the old album is back as it was.
    organize = next(e for e in entries if e["kind"] == "organize" and e["id"] > aside["id"])
    assert c.post(f"/api/activity/{organize['id']}/undo").json()["failed"] == 0
    assert c.post(f"/api/activity/{aside['id']}/undo").json()["failed"] == 0
    assert (old / "01 Opening.mp3").read_bytes() == b"old lossy copy" and (old / "cover.jpg").read_bytes() == b"old cover"


def test_inbox_shows_progress_of_an_album_still_arriving(music, tmp_path):  # noqa: F811
    """Downloads started in slskd itself: the inbox item gets slskd's progress and time left."""
    downloads = tmp_path / "dl2"
    (downloads / "Some Album").mkdir(parents=True)
    (downloads / "Some Album" / "01 First.flac").write_bytes(b"x" * 100)  # arrived; 02 still on its way
    fake = FakeSlskd()
    fake.downloads["someone"] = [
        {"id": "1", "filename": "Music\\Some Album\\01 First.flac", "size": 100, "bytesTransferred": 100,
         "state": "Completed, Succeeded", "startedAt": "2020-01-01T00:00:00Z"},
        {"id": "2", "filename": "Music\\Some Album\\02 Second.flac", "size": 300, "bytesTransferred": 100,
         "state": "InProgress", "startedAt": "2020-01-01T00:00:00Z"}]
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "cfg2", inbox_dir=downloads, inbox_settle_seconds=600),
                     fetch_mb=FakeMB(), fetch_art=lambda url: None, slskd_request=fake)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.put("/api/connections", json={"enabled": {"slskd": True}})
        c.put("/api/slskd/settings", json={"url": "slskd:5030", "api_key": "secret"})
        g = c.put("/api/inbox/settings", json={"folder": "@inbox"}).json()["groups"][0]
        assert g["status"] == "downloading"
        assert g["transfer"]["progress"] == 0.5 and g["transfer"]["finished"] == 1 and g["transfer"]["files"] == 2
        assert g["transfer"]["eta"] is not None
        # Without the slskd connection, there's simply no bar.
        c.put("/api/connections", json={"enabled": {"slskd": False}})
        assert c.get("/api/inbox").json()["groups"][0]["transfer"] is None
