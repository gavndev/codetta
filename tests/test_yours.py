"""Your music: favourites, most and recently played, and playlists, from the page. The same stars,
plays and playlists music apps see (listening.sqlite3); your files are never touched."""

import shutil
import time

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR
from tests.test_musicbrainz import PASSWORD

A = "Artist/Album"


@pytest.fixture
def client(tmp_path):
    d = tmp_path / "music" / A
    d.mkdir(parents=True)
    engine = MetadataEngine()
    for n in (1, 2, 3):
        shutil.copy2(FIXTURES_DIR / "sample.flac", d / f"0{n}.flac")
        engine.update_tags(d / f"0{n}.flac", {"title": f"Song {n}", "artist": "Artist", "album": "Album", "tracknumber": str(n)})
    app = create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.music = tmp_path / "music"
        yield c


def names(d):
    return [t["path"].rsplit("/", 1)[1] for t in d["tracks"]]


def test_favourites_and_plays(client):
    d = client.get("/api/yours").json()
    assert (d["starred"], d["played"], d["playlists"]) == (0, 0, [])
    assert client.post("/api/yours/star", json={"paths": [f"{A}/02.flac", f"{A}/03.flac"]}).json()["starred"] == 2
    assert sorted(names(client.get("/api/yours", params={"view": "starred"}).json())) == ["02.flac", "03.flac"]
    assert client.get("/api/yours/starred", params={"paths": [f"{A}/01.flac", f"{A}/02.flac"]}).json() == {"starred": [f"{A}/02.flac"]}
    client.post("/api/yours/star", json={"paths": [f"{A}/03.flac"], "on": False})
    assert names(client.get("/api/yours", params={"view": "starred"}).json()) == ["02.flac"]
    for p in ("01", "01", "03"):
        client.post("/api/played", json={"path": f"{A}/{p}.flac"})
    most = client.get("/api/yours", params={"view": "most"}).json()
    assert names(most) == ["01.flac", "03.flac"] and most["plays"][f"{A}/01.flac"] == 2
    assert names(client.get("/api/yours", params={"view": "recent"}).json())[0] == "03.flac"
    assert client.post("/api/yours/star", json={"paths": ["../../etc/passwd"]}).status_code == 400


def test_playlists(client):
    pid = client.post("/api/playlists", json={"name": "Road trip", "paths": [f"{A}/03.flac", f"{A}/01.flac"]}).json()["id"]
    d = client.get("/api/yours", params={"view": "playlist", "id": pid}).json()
    assert d["name"] == "Road trip" and names(d) == ["03.flac", "01.flac"]
    client.put(f"/api/playlists/{pid}", json={"name": "Drive", "add": [f"{A}/02.flac"], "remove": [f"{A}/03.flac"]})
    d = client.get("/api/yours", params={"view": "playlist", "id": pid}).json()
    assert d["name"] == "Drive" and names(d) == ["01.flac", "02.flac"]
    (client.music / A / "01.flac").unlink()  # a song deleted outside Codetta is just left out
    assert names(client.get("/api/yours", params={"view": "playlist", "id": pid}).json()) == ["02.flac"]
    assert client.get("/api/yours").json()["playlists"][0]["name"] == "Drive"
    assert client.delete(f"/api/playlists/{pid}").json()["playlists"] == []
    assert client.get("/api/yours", params={"view": "playlist", "id": pid}).status_code == 404


def test_reorder_a_playlist(client):
    songs = [f"{A}/01.flac", f"{A}/02.flac", f"{A}/03.flac", f"{A}/01.flac"]  # a song can be in twice
    pid = client.post("/api/playlists", json={"name": "Mix", "paths": songs}).json()["id"]
    new = [f"{A}/03.flac", f"{A}/01.flac", f"{A}/01.flac", f"{A}/02.flac"]
    assert client.put(f"/api/playlists/{pid}", json={"order": new}).status_code == 200
    assert names(client.get("/api/yours", params={"view": "playlist", "id": pid}).json()) == ["03.flac", "01.flac", "01.flac", "02.flac"]
    # Changed somewhere else meanwhile (a song added in a music app): the page's order is refused, nothing is lost.
    client.put(f"/api/playlists/{pid}", json={"add": [f"{A}/02.flac"]})
    res = client.put(f"/api/playlists/{pid}", json={"order": new})
    assert res.status_code == 409
    assert len(client.get("/api/yours", params={"view": "playlist", "id": pid}).json()["tracks"]) == 5


def test_reorder_keeps_songs_whose_file_is_gone(client):
    pid = client.post("/api/playlists", json={"name": "Mix", "paths": [f"{A}/01.flac", f"{A}/02.flac", f"{A}/03.flac"]}).json()["id"]
    (client.music / A / "02.flac").unlink()
    assert client.put(f"/api/playlists/{pid}", json={"order": [f"{A}/03.flac", f"{A}/01.flac"]}).status_code == 200
    assert names(client.get("/api/yours", params={"view": "playlist", "id": pid}).json()) == ["03.flac", "01.flac"]


def wait_for_index(c, n):
    for _ in range(200):  # the index scans in the background; the catalogue follows it
        if c.get("/api/yours").json()["songs"] >= n:
            return
        time.sleep(0.05)
    raise AssertionError("the library index never caught up")


def test_albums_and_songs_are_only_the_tagged_ones(tmp_path):
    music = tmp_path / "music"
    engine = MetadataEngine()
    files = {  # path: tags
        "Radiohead/In Rainbows/01.flac": {"title": "15 Step", "artist": "Radiohead", "album": "In Rainbows",
                                          "albumartist": "Radiohead", "date": "2007", "tracknumber": "1"},
        "Radiohead/In Rainbows/CD2/01.flac": {"title": "MK 1", "artist": "Radiohead", "album": "In Rainbows",
                                              "albumartist": "Radiohead", "date": "2007", "tracknumber": "1", "discnumber": "2"},
        "Björk/Vespertine/01.flac": {"title": "Hidden Place", "artist": "Björk", "album": "Vespertine", "albumartist": "Björk"},
        "Leftovers/no-album-artist.flac": {"title": "Loose", "artist": "Someone", "album": "Some Album", "albumartist": None},  # a song, not an album
        "Leftovers/untagged.flac": {"title": None, "artist": None, "album": None, "albumartist": None},  # neither
    }
    for rel, tags in files.items():
        (music / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FIXTURES_DIR / "sample.flac", music / rel)
        engine.update_tags(music / rel, tags)
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config", auth=False))) as c:
        wait_for_index(c, 4)
        d = c.get("/api/yours").json()
        assert (d["albums"], d["songs"]) == (2, 4)
        assert len(d["recent_albums"]) == 2 and len(d["recent_songs"]) == 4
        albums = c.get("/api/yours", params={"view": "albums"}).json()["albums"]
        # A to Z by album artist; an album with a disc folder opens at the album's own folder.
        assert [(a["artist"], a["name"], a["folder"], a["songs"]) for a in albums] == [
            ("Björk", "Vespertine", "Björk/Vespertine", 1), ("Radiohead", "In Rainbows", "Radiohead/In Rainbows", 2)]
        assert albums[1]["year"] == 2007
        songs = c.get("/api/yours", params={"view": "songs"}).json()
        assert songs["total"] == 4 and {t["tags"]["title"][0] for t in songs["tracks"]} == {"15 Step", "MK 1", "Hidden Place", "Loose"}
        assert all("Leftovers/untagged.flac" != t["path"] for t in songs["tracks"])
