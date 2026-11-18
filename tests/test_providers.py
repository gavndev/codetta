"""Lyrics lookup (LRCLIB), with a fake service: tests never touch the internet."""

import shutil
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from codetta.core.providers import LRCLib, ProviderError, TrackQuery, http_get_json
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

SONG = {"artistName": "Coda Tester", "trackName": "Test Track", "albumName": "Fixture Album", "duration": 1.0,
        "syncedLyrics": "[00:00.10] la la", "plainLyrics": "la la", "instrumental": False}


class FakeService:
    def __init__(self, get=None, search=None, error=None):
        self.get, self.search, self.error, self.urls = get, search, error, []

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.get if "/get?" in url else self.search


def test_exact_match():
    svc = FakeService(get=SONG)
    r = LRCLib(svc).lyrics(TrackQuery("Coda Tester", "Test Track", "Fixture Album", 1.0))
    assert r.synced == "[00:00.10] la la" and r.provider == "LRCLIB"
    params = urllib.parse.parse_qs(urllib.parse.urlparse(svc.urls[0]).query)
    assert params == {"artist_name": ["Coda Tester"], "track_name": ["Test Track"], "album_name": ["Fixture Album"], "duration": ["1"]}


def test_falls_back_to_search_and_picks_the_closest_length():
    far = {**SONG, "duration": 300, "syncedLyrics": "[00:00.00] wrong version"}
    near = {**SONG, "duration": 182, "syncedLyrics": "", "plainLyrics": "right version"}
    r = LRCLib(FakeService(get=None, search=[far, near])).lyrics(TrackQuery("A", "B", duration=181))
    assert r.plain == "right version"


def test_no_close_match_means_not_found():
    r = LRCLib(FakeService(get=None, search=[{**SONG, "duration": 300}])).lyrics(TrackQuery("A", "B", duration=181))
    assert r is None


def test_results_are_cached():
    svc = FakeService(get=SONG)
    lib = LRCLib(svc)
    q = TrackQuery("Coda Tester", "Test Track", duration=1.0)
    lib.lyrics(q)
    lib.lyrics(q)
    assert len(svc.urls) == 1


def test_only_https_is_allowed():
    with pytest.raises(ProviderError):
        http_get_json("http://lrclib.net/api/get", "test")


@pytest.fixture
def client_for(tmp_path):
    opened = []

    def make(fake, **settings):
        music = tmp_path / "music"
        music.mkdir(exist_ok=True)
        shutil.copy2(FIXTURES_DIR / "sample.flac", music / "a.flac")
        shutil.copy2(FIXTURES_DIR / "untagged.flac", music / "untagged.flac")
        app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config", **settings), fetch_json=fake)
        c = TestClient(app)
        c.__enter__()
        opened.append(c)
        c.post("/api/auth/setup", json={"username": "owner", "password": "correct horse 1"})
        c.put("/api/connections", json={"enabled": {"lyrics": True}})  # opt in, as the first-run card does
        return c
    yield make
    for c in opened:
        c.__exit__(None, None, None)


def test_lookup_api(client_for):
    c = client_for(FakeService(get=SONG))
    data = c.get("/api/lyrics/lookup", params={"path": "a.flac"}).json()
    assert data["found"] and data["result"]["synced"] == "[00:00.10] la la"
    assert "lyrics" not in c.get("/api/track", params={"path": "a.flac"}).json()["tags"]  # nothing written


def test_lookup_needs_artist_and_title(client_for):
    c = client_for(FakeService(get=SONG))
    assert c.get("/api/lyrics/lookup", params={"path": "untagged.flac"}).status_code == 422


def test_service_errors_are_reported_kindly(client_for):
    c = client_for(FakeService(error=ProviderError("Couldn't reach the lyrics service.")))
    res = c.get("/api/lyrics/lookup", params={"path": "a.flac"})
    assert res.status_code == 502 and "Couldn't reach" in res.json()["detail"]


def test_lookup_is_off_until_opted_in(tmp_path):
    svc = FakeService(get=SONG)
    music = tmp_path / "music"
    music.mkdir()
    shutil.copy2(FIXTURES_DIR / "sample.flac", music / "a.flac")
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config"), fetch_json=svc)) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": "correct horse 1"})
        assert c.get("/api/status").json()["lyrics_lookup"] is False
        res = c.get("/api/lyrics/lookup", params={"path": "a.flac"})
        assert res.status_code == 403 and "Connections" in res.json()["detail"]
    assert svc.urls == []


def test_lookup_can_be_turned_off(client_for):
    svc = FakeService(get=SONG)
    c = client_for(svc, lyrics_lookup=False)
    assert c.get("/api/lyrics/lookup", params={"path": "a.flac"}).status_code == 403
    assert c.get("/api/status").json()["lyrics_lookup"] is False
    assert svc.urls == []  # nothing was sent anywhere
