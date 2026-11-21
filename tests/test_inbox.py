"""Import inbox, first-run steps and What's new. A fake MusicBrainz; never the internet."""

import shutil
import time

import pytest
from fastapi.testclient import TestClient

from codetta.core import changelog
from codetta.core.engine import MetadataEngine
from codetta.core.inbox import find_groups
from codetta.core.library import Library
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR
from tests.test_musicbrainz import ALBUM, PASSWORD, REL, FakeMB

ALBUM_DIR = "Downloads/Coda Tester - Fixture Album"


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "music"
    album = root / ALBUM_DIR
    album.mkdir(parents=True)
    engine = MetadataEngine()
    for n, (src, title) in enumerate([("sample.flac", "Opening"), ("sample.mp3", "Middle"), ("sample.m4a", "Closing")], 1):
        dest = album / f"0{n}.{src.split('.')[1]}"
        shutil.copy2(FIXTURES_DIR / src, dest)
        engine.update_tags(dest, {"title": title, "tracknumber": str(n), "discnumber": None})
    (album / "cover.jpg").write_bytes((FIXTURES_DIR / "cover.jpg").read_bytes())
    (root / "Library").mkdir()
    return root


@pytest.fixture
def make_client(music, tmp_path):
    opened = []

    def make(online=True, fake=None, art=None):
        app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config", inbox_settle_seconds=0,
                                  inbox_dir=tmp_path / "downloads"),
                         fetch_mb=fake or FakeMB(), fetch_art=art or (lambda url: None))
        c = TestClient(app)
        c.__enter__()
        opened.append(c)
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.put("/api/connections", json={"enabled": {"musicbrainz": online}})
        return c
    yield make
    for c in opened:
        c.__exit__(None, None, None)


def settle(c, timeout=10):
    """Open the inbox and wait for the background lookups to finish."""
    end = time.time() + timeout
    while True:
        data = c.get("/api/inbox").json()
        if not data["running"] and not any(g["status"] in ("waiting", "matching") for g in data["groups"]):
            return data
        assert time.time() < end, data
        time.sleep(0.05)


def test_groups_join_disc_folders(tmp_path):
    root = tmp_path / "m"
    for rel in ("in/Album/CD1/a.flac", "in/Album/CD2/b.flac", "in/Single.mp3", "in/Other/x.flac"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x")
    groups = dict(find_groups(Library(root), "in"))
    assert groups == {"in/Single.mp3": ["in/Single.mp3"], "in/Album": ["in/Album/CD1/a.flac", "in/Album/CD2/b.flac"],
                      "in/Other": ["in/Other/x.flac"]}


def test_inbox_is_off_until_set_up(make_client):
    c = make_client()
    data = c.get("/api/inbox").json()
    assert data["settings"]["folder"] == "" and data["groups"] == []
    assert c.put("/api/inbox/settings", json={"folder": ""}).status_code == 422  # never the whole library
    assert c.put("/api/inbox/settings", json={"folder": "Nope"}).status_code == 422
    assert c.put("/api/inbox/settings", json={"folder": "../.."}).status_code == 400


def test_match_and_file(make_client, music):
    c = make_client()
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    data = settle(c)
    g = data["groups"][0]
    assert g["key"] == ALBUM_DIR and g["status"] == "ready" and g["release"]["id"] == REL and g["files"] == 3
    res = c.post("/api/inbox/accept", json={"key": g["key"]}).json()
    assert res["status"] == "filed" and res["moved_to"] == "Coda Tester/Fixture Album (2024)"
    new = music / "Coda Tester" / "Fixture Album (2024)"
    assert (new / "01 Opening.flac").exists() and (new / "cover.jpg").exists()
    assert not (music / ALBUM_DIR).exists()
    tags = c.get("/api/track", params={"path": "Coda Tester/Fixture Album (2024)/01 Opening.flac"}).json()["tags"]
    assert tags["musicbrainz_albumid"] == [REL]
    kinds = [e["kind"] for e in c.get("/api/activity").json()[:2]]
    assert kinds == ["organize", "musicbrainz"]  # two ordinary, undoable entries
    assert settle(c)["groups"][0]["status"] == "filed"  # remembered after it left the inbox


def test_auto_files_confident_matches(make_client, music):
    c = make_client()
    c.put("/api/inbox/settings", json={"folder": "Downloads", "auto": True})
    assert settle(c)["groups"][0]["status"] == "filed"
    assert (music / "Coda Tester" / "Fixture Album (2024)" / "02 Middle.mp3").exists()


def test_uncertain_matches_wait_for_review(make_client, music):
    (music / ALBUM_DIR / "bonus.flac").write_bytes((FIXTURES_DIR / "sample.flac").read_bytes())  # 4 files, 3 tracks
    c = make_client()
    c.put("/api/inbox/settings", json={"folder": "Downloads", "auto": True})
    g = settle(c)["groups"][0]
    assert g["status"] == "review" and "isn't sure" in g["note"]
    assert (music / ALBUM_DIR / "01.flac").exists()  # nothing moved


def test_offline_files_by_own_tags(make_client, music):
    c = make_client(online=False)
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    g = settle(c)["groups"][0]
    assert g["status"] == "local"
    assert c.post("/api/inbox/accept", json={"key": g["key"]}).json()["status"] == "filed"
    assert (music / "Coda Collective" / "Fixture Album (2024)" / "01 Opening.flac").exists()  # by its own tags


def test_skip_and_rematch(make_client):
    c = make_client()
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    key = settle(c)["groups"][0]["key"]
    assert c.post("/api/inbox/skip", json={"key": key}).json()["groups"][0]["status"] == "skipped"
    assert settle(c)["groups"][0]["status"] == "skipped"  # stays skipped
    c.post("/api/inbox/rematch", json={"key": key})
    assert settle(c)["groups"][0]["status"] == "ready"
    assert c.post("/api/inbox/skip", json={"key": "nope"}).status_code == 404


def test_file_all_ready(make_client):
    c = make_client()
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    settle(c)
    assert c.post("/api/inbox/accept-ready").json()["filed"] == 1


def test_duplicates_are_not_overwritten(make_client, music):
    dup = music / "Coda Tester" / "Fixture Album (2024)"
    dup.mkdir(parents=True)
    (dup / "01 Opening.flac").write_bytes(b"already in my library")
    c = make_client()
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    res = c.post("/api/inbox/accept", json={"key": settle(c)["groups"][0]["key"]}).json()
    assert res["status"] == "error" and "couldn't move" in res["note"]
    assert (dup / "01 Opening.flac").read_bytes() == b"already in my library"


# --- First-run steps and What's new ---------------------------------------------------------------


def test_onboarding_steps(make_client, tmp_path):
    app = create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "fresh"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        assert c.get("/api/onboarding").json()["steps"] == ["connections", "organize", "library", "inbox", "health", "slskd"]
        c.put("/api/connections", json={"enabled": {}})
        assert c.post("/api/onboarding/organize").json()["steps"] == ["library", "inbox", "health", "slskd"]
        assert c.post("/api/onboarding/library").json()["steps"] == ["inbox", "health", "slskd"]
        assert c.post("/api/onboarding/inbox").json()["steps"] == ["health", "slskd"]
        assert c.post("/api/onboarding/health").json()["steps"] == ["slskd"]
        assert c.post("/api/onboarding/slskd").json()["steps"] == []
        assert c.post("/api/onboarding/nope").status_code == 404
        c.post("/api/auth/logout")
        assert c.get("/api/onboarding").status_code == 401


def test_changelog_is_public_and_parsed(tmp_path):
    with TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "c"))) as c:
        data = c.get("/api/changelog").json()
    assert data["versions"] and data["versions"][0]["items"]
    assert any(v["version"] == "0.4.0" and v["date"] == "2026-11-18" for v in data["versions"])


def test_changelog_parser(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text("# Changelog\n\nIntro.\n\n## Unreleased (1.1.0)\n\n- New thing\n  that wraps\n\n## 1.0.0 (2026-01-02)\n\n- First\n")
    changelog.load.cache_clear()
    v = changelog.load(f)
    changelog.load.cache_clear()
    assert v[0]["version"] == "1.1.0" and v[0]["unreleased"] and v[0]["items"] == ["New thing that wraps"]
    assert v[1] == {"title": "1.0.0 (2026-01-02)", "version": "1.0.0", "date": "2026-01-02", "unreleased": False,
                    "items": ["First"], "text": []}


# --- Notifications -----------------------------------------------------------------------------------


def test_inbox_round_sends_one_notification(make_client):
    c = make_client()
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    settle(c)
    n = c.get("/api/notifications").json()
    assert n["unread"] == 1 and n["items"][0]["title"] == "Inbox: 1 ready to file"
    assert n["items"][0]["action"] == {"open": "inbox"}
    last = n["last_id"]
    assert c.get("/api/notifications", params={"after_id": last}).json()["items"] == []
    assert c.post("/api/notifications/read", json={}).json()["unread"] == 0
    assert c.delete("/api/notifications").json()["items"] == []


def test_auto_filed_album_is_announced(make_client):
    c = make_client()
    c.put("/api/inbox/settings", json={"folder": "Downloads", "auto": True})
    settle(c)
    titles = [x["title"] for x in c.get("/api/notifications").json()["items"]]
    assert "Filed “Fixture Album” by Coda Tester" in titles
    filed = next(x for x in c.get("/api/notifications").json()["items"] if x["title"].startswith("Filed"))
    assert filed["action"] == {"open": "folder", "path": "Coda Tester/Fixture Album (2024)"}


def test_update_is_announced_once(tmp_path):
    from codetta.core.notifications import Notifications

    n = Notifications(tmp_path / "n.json")
    assert n.add("update", "Codetta 9.9 is out", key="update:9.9")
    assert n.add("update", "Codetta 9.9 is out", key="update:9.9") is None
    again = Notifications(tmp_path / "n.json")  # survives a restart
    assert again.recent()["items"][0]["title"] == "Codetta 9.9 is out"
    assert again.add("update", "x", key="update:9.9") is None


def test_update_check_notifies(tmp_path):
    (tmp_path / "music").mkdir()
    app = create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "c", update_check=True),
                     fetch_release=lambda repo: {"tag_name": "v99.0.0"})
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.get("/api/update")
        c.get("/api/update")
        items = c.get("/api/notifications").json()["items"]
    assert [i["title"] for i in items] == ["Codetta 99.0.0 is out"]


# --- A downloads folder outside the music folder (slskd's, mounted at /inbox) ---------------------


@pytest.fixture
def external(tmp_path, music):
    """The album sits in a separate downloads folder, not in the music folder."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    shutil.move(str(music / ALBUM_DIR), str(downloads / "Coda Tester - Fixture Album"))
    return downloads


def test_external_inbox_files_into_the_library(make_client, music, external, monkeypatch):
    import os as _os

    real_rename = _os.rename

    def cross_device(a, b, *args, **kwargs):  # the inbox is another mount: rename fails like in Docker
        if str(external) in str(a) and str(music) in str(b):
            raise OSError(18, "Invalid cross-device link")
        return real_rename(a, b, *args, **kwargs)

    monkeypatch.setattr("codetta.core.organize.os.rename", cross_device)
    c = make_client()
    data = c.get("/api/inbox").json()
    assert data["external"]["available"] is True
    c.put("/api/inbox/settings", json={"folder": "@inbox"})
    g = settle(c)["groups"][0]
    assert g["key"] == "@inbox/Coda Tester - Fixture Album" and g["status"] == "ready"
    res = c.post("/api/inbox/accept", json={"key": g["key"]}).json()
    assert res["status"] == "filed"
    new = music / "Coda Tester" / "Fixture Album (2024)"
    assert (new / "01 Opening.flac").exists() and (new / "cover.jpg").exists()
    assert list(external.iterdir()) == []  # copied, checked, then removed; the inbox folder itself stays
    assert not any(p.name.startswith(".codetta-move") for p in new.iterdir())

    entry = c.get("/api/activity").json()[0]
    assert c.post(f"/api/activity/{entry['id']}/undo").json()["undone"] == 3  # back into the downloads folder
    assert (external / "Coda Tester - Fixture Album" / "01.flac").exists()


def test_albums_still_downloading_wait(tmp_path, music):
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config2", inbox_settle_seconds=3600),
                     fetch_mb=FakeMB(), fetch_art=lambda url: None)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.put("/api/connections", json={"enabled": {"musicbrainz": True}})
        c.put("/api/inbox/settings", json={"folder": "Downloads", "auto": True})
        data = c.get("/api/inbox").json()
    assert data["groups"][0]["status"] == "downloading" and data["downloading"] == 1
    assert (music / ALBUM_DIR / "01.flac").exists()  # never filed half-downloaded


def test_inbox_path_cannot_escape(make_client):
    c = make_client()
    assert c.put("/api/inbox/settings", json={"folder": "@inbox/../../etc"}).status_code == 400
    assert c.put("/api/inbox/settings", json={"folder": "@nowhere"}).status_code in (400, 422)
    assert c.get("/api/track", params={"path": "@inbox/../../../etc/passwd"}).status_code == 400


def test_an_album_is_never_filed_twice_at_once(make_client, music):
    import threading

    def slow_cover(url):  # filing waits on the Cover Art Archive for a moment
        time.sleep(1.0)
        return None

    c = make_client(art=slow_cover)
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    g = settle(c)["groups"][0]
    first = {}
    t = threading.Thread(target=lambda: first.update(c.post("/api/inbox/accept", json={"key": g["key"], "release": REL}).json()))
    t.start()
    time.sleep(0.4)  # the first tap is busy filing
    second = c.post("/api/inbox/accept", json={"key": g["key"], "release": REL})
    t.join()
    assert second.status_code == 409 and "already being filed" in second.json()["detail"]
    assert first["status"] == "filed"  # the first one finished normally, not marked as failed


def test_remove_from_the_inbox_sends_files_to_recently_deleted(make_client, music, tmp_path):
    c = make_client(online=False)
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    g = settle(c)["groups"][0]
    res = c.post("/api/inbox/remove", json={"key": g["key"]}).json()
    assert not res["groups"] and not (music / ALBUM_DIR).exists()
    assert list((tmp_path / "config" / "deleted").rglob("01.flac"))
    entry = c.get("/api/activity").json()[0]
    assert entry["kind"] == "delete" and entry["can_undo"]


def test_an_album_you_already_have_is_labelled(make_client, music):
    shutil.copytree(music / ALBUM_DIR, music / "Library" / "Have it")
    c = make_client(online=False)
    end = time.time() + 10
    while c.get("/api/library-health/summary").json()["indexing"]:
        assert time.time() < end
        time.sleep(0.05)
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    g = settle(c)["groups"][0]
    assert g["owned"] == {"folder": "Library/Have it", "tracks": 3}


# --- "Still arriving" must always end -----------------------------------------------------------

def _downloading_inbox(tmp_path, settle_seconds=120):
    """An inbox with one album whose files changed just now."""
    from codetta.core.inbox import InboxStore
    music = tmp_path / "music"
    album = music / "Downloads" / "VA-Some_Album-2CD-FLAC-2026"
    album.mkdir(parents=True)
    for n in (1, 2):
        shutil.copy2(FIXTURES_DIR / "sample.flac", album / f"0{n}.flac")
    store = InboxStore(tmp_path / "inbox.json", settle_seconds=settle_seconds)
    store.settings.folder = "Downloads"
    return Library(music), store, album


def test_an_album_slskd_says_is_complete_stops_arriving_right_away(tmp_path):
    """slskd showed 38 of 38 files done, yet the inbox kept saying "Still arriving"."""
    lib, store, _ = _downloading_inbox(tmp_path)
    (g,) = store.sync(lib)
    assert g.status == "downloading"  # the files changed moments ago
    store.arrived = lambda paths: len(paths) == 2
    (g,) = store.sync(lib)
    assert g.status == "waiting"  # ready to be looked up


def test_an_album_whose_files_stop_changing_arrives_whatever_the_clocks_say(tmp_path):
    import os
    lib, store, album = _downloading_inbox(tmp_path)
    future = time.time() + 7 * 24 * 3600  # a file time in the future (copied from elsewhere, odd drive)
    for f in album.iterdir():
        os.utime(f, (future, future))
    from codetta.core.inbox import signature
    _, newest = signature(lib, [f"Downloads/{album.name}/01.flac"])
    assert newest <= time.time() + 1  # the future time doesn't count as "just changed"
    (g,) = store.sync(lib)
    assert g.status == "downloading"  # copied moments ago (its change time is now)
    g.updated = time.time() - 300  # then: the same names, sizes and times for five minutes
    (g,) = store.sync(lib)
    assert g.status == "waiting"


def test_slskd_being_unreachable_never_breaks_the_inbox(tmp_path):
    lib, store, _ = _downloading_inbox(tmp_path)

    def broken(paths):
        raise ConnectionError("slskd is down")

    store.arrived = broken
    (g,) = store.sync(lib)
    assert g.status == "downloading"  # just falls back to the file times


def test_transfer_progress_says_when_every_file_is_over():
    from codetta.core.slskd import transfer_progress
    done = [{"size": 10, "bytesTransferred": 10, "state": "Completed, Succeeded"},
            {"size": 10, "bytesTransferred": 3, "state": "Completed, Errored"}]
    assert transfer_progress(done)["complete"] is True
    going = [*done, {"size": 10, "bytesTransferred": 5, "state": "InProgress"}]
    assert transfer_progress(going)["complete"] is False
