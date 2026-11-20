"""Library care: tagging (and organizing) the existing library gradually, against a fake MusicBrainz."""

import shutil
import time

from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR
from tests.test_musicbrainz import PASSWORD, REL, FakeMB, album_dir  # noqa: F401 (fixture)

FOLDER = "Coda Tester/Fixture Album"


def client(album_dir, tmp_path):  # noqa: F811
    app = create_app(Settings(music_dir=album_dir, config_dir=tmp_path / "config", care_pause_seconds=0.01),
                     fetch_mb=FakeMB(), fetch_art=lambda url: None)
    c = TestClient(app)
    c.__enter__()
    c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
    c.put("/api/connections", json={"enabled": {"musicbrainz": True}})
    end = time.time() + 10
    while c.get("/api/library-health/summary").json()["indexing"]:
        assert time.time() < end
        time.sleep(0.05)
    return c


def wait_done(c, timeout=15):
    end = time.time() + timeout
    while True:
        d = c.get("/api/library-care").json()
        if not d["running"] and d["done"] >= d["total"]:
            return d
        assert time.time() < end, d
        time.sleep(0.05)


def test_setup_offers_the_library_step(album_dir, tmp_path):  # noqa: F811
    c = client(album_dir, tmp_path)
    assert "library" in c.get("/api/onboarding").json()["steps"]
    assert c.get("/api/library-care").json()["mode"] == "off"  # nothing happens until you choose
    c.__exit__(None, None, None)


def test_tags_only_matches_and_keeps_names(album_dir, tmp_path):  # noqa: F811
    c = client(album_dir, tmp_path)
    c.put("/api/library-care", json={"mode": "tags"})
    d = wait_done(c)
    assert d["counts"]["tagged"] == 1
    t = c.get("/api/track", params={"path": f"{FOLDER}/01.flac"}).json()["tags"]
    assert t["title"] == ["Opening"] and t["musicbrainz_albumid"] == [REL]
    assert (album_dir / FOLDER / "01.flac").exists()  # names and folders untouched
    assert any(e["kind"] == "musicbrainz" and e["can_undo"] for e in c.get("/api/activity").json())
    c.__exit__(None, None, None)


def test_full_care_tags_then_organizes(album_dir, tmp_path):  # noqa: F811
    c = client(album_dir, tmp_path)
    c.put("/api/library-care", json={"mode": "full"})
    d = wait_done(c)
    assert d["counts"]["organized"] >= 1
    assert (album_dir / "Coda Tester" / "Fixture Album (2024)" / "01 Opening.flac").exists()
    assert not (album_dir / FOLDER).exists()
    time.sleep(0.3)
    d = c.get("/api/library-care").json()
    assert d["done"] <= d["total"]  # a moved album counts once, in its new folder
    assert d["started"] and d["finished"] and d["finished"] >= d["started"]
    c.__exit__(None, None, None)


def test_an_unknown_album_needs_a_look_and_is_left_alone(album_dir, tmp_path):  # noqa: F811
    other = album_dir / "Somebody" / "Bootleg"
    other.mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.flac", other / "a.flac")
    MetadataEngine().update_tags(other / "a.flac", {"title": "Live thing", "album": "Bootleg", "artist": "Somebody"})
    c = client(album_dir, tmp_path)
    # The fake MusicBrainz knows only the fixture album, which doesn't fit a one-track bootleg well.
    c.put("/api/library-care", json={"mode": "full"})
    d = wait_done(c)
    review = {r["folder"]: r for r in d["review"]}
    assert "Somebody/Bootleg" in review
    assert (other / "a.flac").exists()  # never renamed from a guess
    c.__exit__(None, None, None)


def test_pause_stops_and_off_is_the_default_choice(album_dir, tmp_path):  # noqa: F811
    c = client(album_dir, tmp_path)
    d = c.put("/api/library-care", json={"mode": "tags", "paused": True}).json()
    assert d["paused"] and not d["running"] and d["done"] == 0
    assert c.put("/api/library-care", json={"mode": "everything"}).status_code == 422
    c.__exit__(None, None, None)


def test_an_album_is_never_split_across_folders(album_dir, tmp_path):  # noqa: F811
    # Matched before, but one song's album name differs ("Rumours" / "Rumours (2004 Remaster)").
    engine = MetadataEngine()
    for n, f in enumerate(sorted((album_dir / FOLDER).iterdir()), 1):
        engine.update_tags(f, {"musicbrainz_albumid": REL, "artist": "Coda Tester", "albumartist": "Coda Tester",
                               "album": "Fixture Album (Remaster)" if n == 3 else "Fixture Album", "date": "1999"})
    c = client(album_dir, tmp_path)
    c.put("/api/library-care", json={"mode": "full"})
    wait_done(c)
    folders = {p.parent for p in album_dir.rglob("*.flac")} | {p.parent for p in album_dir.rglob("*.mp3")} \
        | {p.parent for p in album_dir.rglob("*.m4a")}
    assert len(folders) == 1, folders  # the names were made to agree first, so it moved as one album
    assert "(1999)" in next(iter(folders)).name  # and only the name was rewritten: the year stayed
    c.__exit__(None, None, None)
