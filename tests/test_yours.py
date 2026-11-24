"""Your music: favourites, most and recently played, and playlists, from the page. The same stars,
plays and playlists music apps see (listening.sqlite3); your files are never touched."""

import shutil

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
    assert client.get("/api/yours").json() == {"starred": 0, "played": 0, "playlists": []}
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
