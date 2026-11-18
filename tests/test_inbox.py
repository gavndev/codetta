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

    def make(online=True, fake=None):
        app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"),
                         fetch_mb=fake or FakeMB(), fetch_art=lambda url: None)
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
    assert g["status"] == "review" and "Check" in g["note"]
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
        assert c.get("/api/onboarding").json()["steps"] == ["connections", "organize", "inbox"]
        c.put("/api/connections", json={"enabled": {}})
        assert c.post("/api/onboarding/organize").json()["steps"] == ["inbox"]
        assert c.post("/api/onboarding/inbox").json()["steps"] == []
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
