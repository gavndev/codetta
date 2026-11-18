"""Library health: the checks (on made-up albums) and the API (fix, ignore, switch off, undo)."""

import shutil
import time

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.health import HealthStore, run
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


def tr(path, art=None, error=None, fmt="flac", bitrate=900_000, duration=200.0, **tags):
    return (path, {"tags": {k: [v] for k, v in tags.items()}, "art": art, "error": error, "format": fmt,
                   "bitrate": bitrate, "duration": duration})


COVER = {"hash": "x", "width": 1200, "height": 1200}


def album(folder, n=4, **common):
    return [tr(f"{folder}/{i:02} T{i}.flac", art=COVER, title=f"T{i}", artist="A", album="Alb",
               tracknumber=str(i), **common) for i in range(1, n + 1)]


def checks(tracks, images=()):
    return {(i["check"], i["folder"]): i for i in run(tracks, lambda f: f in images)["issues"]}


def test_a_tidy_album_has_no_issues():
    assert checks(album("A/Alb", albumartist="A", date="2020")) == {}


def test_split_album_name_offers_the_most_common_spelling():
    t = album("A/Alb", albumartist="A")
    t[3][1]["tags"]["album"] = ["alb (Deluxe)"]
    i = checks(t)[("split_album", "A/Alb")]
    assert i["fix"]["label"] == "Use “Alb”" and list(i["fix"]["per_file"]) == ["A/Alb/04 T4.flac"]
    # Case and punctuation alone aren't a split.
    t[3][1]["tags"]["album"] = ["ALB!"]
    assert ("split_album", "A/Alb") not in checks(t)


def test_features_without_album_artist_use_the_main_artist():
    t = album("K/Sweet")
    t[1][1]["tags"]["artist"] = ["A feat. Zayn"]
    t[2][1]["tags"]["artist"] = ["A & B"]
    i = checks(t)[("no_albumartist", "K/Sweet")]
    assert i["fix"]["per_file"]["K/Sweet/01 T1.flac"] == {"albumartist": "A"}


def test_real_compilation_gets_various_artists():
    t = album("Comp")
    for k, (_, tt) in enumerate(t):
        tt["tags"]["artist"] = [f"Artist {k}"]
    fix = checks(t)[("no_albumartist", "Comp")]["fix"]
    assert fix["per_file"]["Comp/01 T1.flac"] == {"albumartist": "Various Artists", "compilation": "1"}


def test_missing_tracks_but_not_continued_numbering_on_disc_two():
    t = album("A/Alb", n=5)
    del t[2]  # track 3
    assert checks(t)[("track_gaps", "A/Alb")]["detail"] == ["Track 3"]
    # Disc 2 carries on from 17: not "tracks 1-16 missing".
    two = [tr(f"D/{i:02}.flac", art=COVER, title=f"T{i}", artist="A", album="Alb", tracknumber=f"{i}/32",
              discnumber="1" if i <= 16 else "2") for i in range(1, 33)]
    assert ("track_gaps", "D") not in checks(two)
    # A total that can't be right (30 for 10 tracks) isn't trusted; a plausible one is.
    assert ("track_gaps", "E") not in checks([tr(f"E/{i}.flac", art=COVER, title=f"T{i}", artist="A", album="Alb",
                                                  tracknumber=f"{i}/30") for i in range(1, 11)])
    near = checks([tr(f"F/{i}.flac", art=COVER, title=f"T{i}", artist="A", album="Alb", tracknumber=f"{i}/12")
                   for i in range(1, 11)])
    assert near[("track_gaps", "F")]["detail"] == ["Track 11", "Track 12"]


def test_covers():
    no_art = [(p, {**t, "art": None}) for p, t in album("A/Alb")]
    assert ("no_cover", "A/Alb") in checks(no_art)
    assert ("no_cover", "A/Alb") not in checks(no_art, images={"A/Alb"})  # cover.jpg next to it
    small = [(p, {**t, "art": {"hash": "x", "width": 300, "height": 300}}) for p, t in album("A/Alb")]
    assert checks(small)[("small_cover", "A/Alb")]["message"] == "Cover is only 300 px"


def test_missing_track_numbers_fixed_from_file_names():
    t = [tr(f"S/{i}. 800pts - song{i}.m4a", art=COVER, title=f"song{i}", artist="A", album="S") for i in (1, 2, 3)]
    fix = checks(t)[("missing_tags", "S")]["fix"]
    assert fix["per_file"]["S/2. 800pts - song2.m4a"] == {"tracknumber": "2"}


def test_duplicate_songs_need_the_same_length():
    t = album("A/Alb", n=3)
    t.append(tr("A/Alb/01 T1.mp3", art=COVER, fmt="mp3", bitrate=320_000, duration=201.0, title="T1", artist="A",
                album="Alb", tracknumber="1"))
    found = checks(t)
    assert ("duplicate_track", "A/Alb") in found and ("mixed_quality", "A/Alb") in found
    remixes = [tr(f"R/{i}.flac", art=COVER, title="Deuces Remix", artist="A", album="R", tracknumber=str(i),
                  duration=200.0 + 20 * i) for i in (1, 2, 3)]
    assert ("duplicate_track", "R") not in checks(remixes)


def test_disc_folders_join_and_number_themselves():
    t = album("A/Alb/CD1", n=2) + album("A/Alb/CD2", n=2)
    for p, tt in t:
        tt["tags"]["discnumber"] = ["1"] if "CD1" in p else []
    i = checks(t)[("disc_numbers", "A/Alb")]
    assert i["fix"]["per_file"] == {"A/Alb/CD2/01 T1.flac": {"discnumber": "2"}, "A/Alb/CD2/02 T2.flac": {"discnumber": "2"}}


def test_duplicate_albums_and_unreadable_files_and_skips():
    t = album("A/Alb", albumartist="A") + album("Old/Alb copy", albumartist="A")
    t.append(tr("A/Alb/broken.flac", error="Not a FLAC file"))
    found = checks(t)
    assert found[("duplicate_album", "A/Alb")]["folders"] == ["A/Alb", "Old/Alb copy"]
    assert found[("unreadable", "A/Alb")]["detail"] == ["broken.flac"]
    assert run(t, lambda f: False, skip=["Old"])["albums"] == 1  # the inbox folder isn't checked


def test_health_store_roundtrip(tmp_path):
    s = HealthStore(tmp_path / "health.json")
    s.disabled, s.ignored = {"small_cover", "nonsense"}, {"abc"}
    s.save()
    again = HealthStore(tmp_path / "health.json")
    assert again.disabled == {"small_cover"} and again.ignored == {"abc"}


# --- Through the API -------------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    music = tmp_path / "music"
    folder = music / "Kehlani" / "Sweet"
    folder.mkdir(parents=True)
    engine = MetadataEngine()
    for i in (1, 2, 3):
        shutil.copy2(FIXTURES_DIR / "sample.flac", folder / f"0{i} Song.flac")
        engine.update_tags(folder / f"0{i} Song.flac", {"title": f"Song {i}", "artist": "Kehlani" if i != 2 else "Kehlani feat. Zayn",
                                                       "album": "Sweet", "tracknumber": str(i), "albumartist": None})
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config", auth=False))) as c:
        end = time.time() + 10
        while c.get("/api/library-health/summary").json()["indexing"]:
            assert time.time() < end
            time.sleep(0.05)
        yield c, music


def issues(c):
    return {i["check"]: i for i in c.get("/api/library-health").json()["issues"]}


def test_api_fix_ignore_and_switch_off(client):
    c, music = client
    data = c.get("/api/library-health").json()
    i = {x["check"]: x for x in data["issues"]}["no_albumartist"]
    assert "paths" not in i and set(i["fix"]) == {"label", "summary"}  # file lists stay on the server
    assert c.get("/api/library-health/summary").json()["count"] == data["count"]
    res = c.post("/api/library-health/fix", json={"id": i["id"]}).json()
    assert res["fixed"] == 3 and "no_albumartist" not in {x["check"] for x in res["health"]["issues"]}
    tags = c.get("/api/track", params={"path": "Kehlani/Sweet/02 Song.flac"}).json()["tags"]
    assert tags["albumartist"] == ["Kehlani"]
    entry = c.get("/api/activity").json()[0]
    assert entry["message"].startswith("Library health:") and entry["can_undo"]
    # One undo puts all three back.
    assert c.post(f"/api/activity/{entry['id']}/undo").json()["undone"] == 3
    assert "albumartist" not in c.get("/api/track", params={"path": "Kehlani/Sweet/02 Song.flac"}).json()["tags"]
    # Ignore, and switch a check off.
    cover = issues(c)["no_cover"]
    after = c.post("/api/library-health/ignore", json={"id": cover["id"]}).json()
    assert "no_cover" not in {x["check"] for x in after["issues"]} and after["ignored"][0]["id"] == cover["id"]
    off = c.put("/api/library-health/settings", json={"disabled": ["no_albumartist"]}).json()
    assert not any(x["check"] == "no_albumartist" for x in off["issues"])
    assert not next(x for x in off["checks"] if x["id"] == "no_albumartist")["enabled"]
    assert c.post("/api/library-health/fix", json={"id": "nope"}).status_code == 404


def test_health_needs_sign_in(tmp_path):
    with TestClient(create_app(Settings(music_dir=tmp_path, config_dir=tmp_path / "cfg"))) as c:
        assert c.get("/api/library-health").status_code == 401
        assert c.get("/api/health").json() == {"ok": True}  # the public "am I up" check is untouched
        assert c.post("/api/library-health/fix", json={"id": "x"}).status_code == 401


def test_library_health_can_be_switched_off(client, monkeypatch):
    c, _ = client
    assert c.get("/api/library-health").json()["enabled"] is True
    issue = issues(c)["no_albumartist"]
    off = c.put("/api/library-health/settings", json={"enabled": False}).json()
    assert off["enabled"] is False and off["issues"] == [] and off["count"] == 0
    assert c.get("/api/library-health/summary").json() == {"enabled": False, "count": 0, "indexing": False}
    assert c.post("/api/library-health/fix", json={"id": issue["id"]}).status_code == 409
    # Off means nothing is checked at all.
    monkeypatch.setattr(c.app.state.index, "all_tracks", lambda: (_ for _ in ()).throw(AssertionError("checked while off")))
    c.get("/api/library-health"); c.get("/api/library-health/summary")
    monkeypatch.undo()
    # Switching checks off and on keeps the master switch, and vice versa.
    c.put("/api/library-health/settings", json={"disabled": ["small_cover"]})
    on = c.put("/api/library-health/settings", json={"enabled": True}).json()
    assert on["enabled"] and not next(x for x in on["checks"] if x["id"] == "small_cover")["enabled"]
