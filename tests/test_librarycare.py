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


def test_the_preview_shows_before_and_after_and_moves_nothing(album_dir, tmp_path):  # noqa: F811
    engine = MetadataEngine()
    for f in (album_dir / FOLDER).iterdir():
        engine.update_tags(f, {"artist": "Coda Tester", "albumartist": "Coda Tester", "album": "Fixture Album", "date": "2024"})
    c = client(album_dir, tmp_path)
    d = c.get("/api/library-care/preview").json()
    assert d["albums"] and d["albums"][0]["folder"] == FOLDER
    ex = d["albums"][0]["examples"][0]
    assert ex["from"].startswith(FOLDER) and "(2024)" in ex["to"]
    assert (album_dir / FOLDER / "01.flac").exists()  # nothing moved
    c.__exit__(None, None, None)


def test_a_split_album_says_which_folders_it_would_go_to(album_dir, tmp_path):  # noqa: F811
    """Matched before, but with MusicBrainz now off Tidy up can't make the names agree. It leaves the album where it
    is and the note names the folders, so the cause (one song's album tag) is easy to spot."""
    engine = MetadataEngine()
    for n, f in enumerate(sorted((album_dir / FOLDER).iterdir()), 1):
        engine.update_tags(f, {"musicbrainz_albumid": REL, "artist": "Coda Tester", "albumartist": "Coda Tester",
                               "date": "1999", "album": "Fixture Album (Remaster)" if n == 2 else "Fixture Album"})
    c = client(album_dir, tmp_path)
    c.put("/api/connections", json={"enabled": {"musicbrainz": False}})
    c.put("/api/library-care", json={"mode": "full"})
    d = wait_done(c)
    note = next(r["note"] for r in d["review"] if r["folder"] == FOLDER)
    assert "“Fixture Album (1999)”" in note and "“Fixture Album (Remaster) (1999)”" in note
    assert {p.parent for p in (album_dir / FOLDER).iterdir()} == {album_dir / FOLDER}  # nothing moved
    c.__exit__(None, None, None)


def test_loose_songs_go_to_their_own_albums_but_never_split_one(tmp_path):
    """A folder of loose songs (each already matched to a different album) is filed song by song.
    Different folders are expected there; two songs of the same album that would land in different
    folders stay put."""
    music = tmp_path / "music"
    loose = music / "Downloads"
    loose.mkdir(parents=True)
    engine = MetadataEngine()
    songs = [  # file, artist, album, year, album id
        ("a.flac", "Björk", "Post", "1995", "rel-post"),
        ("b.flac", "Frank Ocean", "Blonde", "2016", "rel-blonde"),
        ("c.flac", "Fleetwood Mac", "Rumours", "1977", "rel-rumours-1977"),
        ("d.flac", "Fleetwood Mac", "Rumours", "2004", "rel-rumours-2004"),  # same album, other year
    ]
    for i, (name, artist, album, year, rid) in enumerate(songs, 1):
        shutil.copy2(FIXTURES_DIR / "sample.flac", loose / name)
        engine.update_tags(loose / name, {"title": f"Song {i}", "artist": artist, "albumartist": artist, "album": album,
                                          "date": year, "tracknumber": "1", "musicbrainz_albumid": rid})
    c = client(music, tmp_path)
    c.put("/api/connections", json={"enabled": {"musicbrainz": False}})
    c.put("/api/library-care", json={"mode": "full"})
    d = wait_done(c)
    assert (music / "Björk" / "Post (1995)").is_dir() and (music / "Frank Ocean" / "Blonde (2016)").is_dir()
    assert {p.name for p in loose.iterdir()} == {"c.flac", "d.flac"}  # Rumours would split: both stay
    note = next(r["note"] for r in d["review"] if r["folder"] == "Downloads")
    assert "2 would split an album" in note
    c.__exit__(None, None, None)


def test_a_loose_song_already_in_the_library_stays_and_says_so(tmp_path):
    """Filing a downloaded MP3 next to the album's FLAC of the same song would make a duplicate."""
    music = tmp_path / "music"
    album, loose = music / "Björk" / "Post (1995)", music / "Downloads"
    album.mkdir(parents=True)
    loose.mkdir()
    engine = MetadataEngine()
    tags = {"title": "Hyper-Ballad", "artist": "Björk", "albumartist": "Björk", "album": "Post", "date": "1995",
            "tracknumber": "2"}
    shutil.copy2(FIXTURES_DIR / "sample.flac", album / "02 Hyper-Ballad.flac")
    engine.update_tags(album / "02 Hyper-Ballad.flac", {**tags, "musicbrainz_albumid": "rel-post"})
    shutil.copy2(FIXTURES_DIR / "sample.mp3", loose / "bjork - hyperballad.mp3")
    engine.update_tags(loose / "bjork - hyperballad.mp3", {**tags, "musicbrainz_albumid": "rel-post-2"})
    shutil.copy2(FIXTURES_DIR / "sample.flac", loose / "other.flac")
    engine.update_tags(loose / "other.flac", {"title": "Nights", "artist": "Frank Ocean", "albumartist": "Frank Ocean",
                                              "album": "Blond", "date": "2016", "tracknumber": "9", "musicbrainz_albumid": "rel-blond"})
    c = client(music, tmp_path)
    c.put("/api/connections", json={"enabled": {"musicbrainz": False}})
    c.put("/api/library-care", json={"mode": "full"})
    d = wait_done(c)
    assert (loose / "bjork - hyperballad.mp3").exists()  # the album's FLAC is the same song
    assert not list(album.glob("*.mp3"))
    assert list((music / "Frank Ocean" / "Blond (2016)").glob("*Nights.flac"))  # a new song is filed
    downloads = next(r for r in [*d["review"], *d.get("recent", [])] if r["folder"] == "Downloads") if d["review"] else None
    assert downloads is None or "already in your library" in downloads["note"]
    c.__exit__(None, None, None)
