"""The top of an artist's folder: a Wikipedia bio found through MusicBrainz (never by name alone) and
similar artists from Deezer, each only with its connections on. Fake servers, never the internet."""

import shutil
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR
from tests.test_musicbrainz import PASSWORD

RAPPER = "11111111-1111-1111-1111-111111111111"
BAND = "22222222-2222-2222-2222-222222222222"


class Fakes:
    def __init__(self):
        self.urls = []

    def mb(self, url):
        self.urls.append(url)
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        if u.path.endswith("/artist") and "query" in q:
            return {"artists": [{"id": BAND, "name": "Future"}, {"id": RAPPER, "name": "Future"}]}
        if u.path.endswith("/release-group"):
            titles = ["HNDRXX", "DS2"] if q["artist"] == [RAPPER] else ["Our Tomorrow"]
            return {"release-groups": [{"id": f"{i:08d}-0000-0000-0000-000000000000", "title": t} for i, t in enumerate(titles)]}
        if u.path.endswith(f"/artist/{RAPPER}"):
            return {"id": RAPPER, "name": "Future", "relations": [
                {"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q3121"}}]}
        return None

    def wiki(self, url):
        self.urls.append(url)
        if url == "https://www.wikidata.org/wiki/Special:EntityData/Q3121.json":
            return {"entities": {"Q3121": {"sitelinks": {"enwiki": {"title": "Future (rapper)"}}}}}
        if url == "https://en.wikipedia.org/api/rest_v1/page/summary/Future_%28rapper%29":
            return {"extract": "Nayvadius DeMun Wilburn, known as Future, is an American rapper.",
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Future_(rapper)"}}}
        return None

    def deezer(self, url):
        self.urls.append(url)
        u = urllib.parse.urlparse(url)
        if u.path == "/search/artist":
            return {"data": [{"id": 615, "name": "Future", "nb_fan": 9}]}
        if u.path == "/artist/615/related":
            return {"data": [{"name": "Young Thug"}, {"name": "Metro Boomin"}]}
        return None


@pytest.fixture
def client(tmp_path):
    music = tmp_path / "music"
    engine = MetadataEngine()
    for album in ("HNDRXX", "DS2"):
        d = music / "Future" / album
        d.mkdir(parents=True)
        shutil.copy2(FIXTURES_DIR / "sample.flac", d / "01.flac")
        engine.update_tags(d / "01.flac", {"album": album, "albumartist": "Future", "title": "x"})
    (music / "Metro Boomin").mkdir()
    fakes = Fakes()
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"), fetch_mb=fakes.mb,
                     fetch_wiki=fakes.wiki, fetch_catalog=fakes.deezer)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.fakes = fakes
        yield c


def test_nothing_is_asked_with_the_connections_off(client):
    d = client.get("/api/artists/info", params={"folder": "Future"}).json()
    assert d["name"] == "Future" and d["bio"] is None and d["similar"] == [] and d["albums"] == 2
    assert not client.fakes.urls


def test_the_bio_comes_from_the_right_artist_and_similar_ones_you_have_come_first(client):
    client.put("/api/connections", json={"enabled": {"musicbrainz": True, "wikipedia": True, "deezer": True}})
    d = client.get("/api/artists/info", params={"folder": "Future", "lang": "es-ES"}).json()
    assert d["bio"]["text"].startswith("Nayvadius") and d["bio"]["url"].endswith("Future_(rapper)")  # the rapper, not the band
    assert d["bio"]["lang"] == "en"  # no Spanish page: English
    assert d["similar"] == [{"name": "Metro Boomin", "folder": "Metro Boomin"}, {"name": "Young Thug", "folder": None}]
    asked = len(client.fakes.urls)
    client.get("/api/artists/info", params={"folder": "Future", "lang": "es"})
    assert len(client.fakes.urls) == asked  # kept: the second visit asks nobody


def test_only_artist_folders(client):
    assert client.get("/api/artists/info", params={"folder": "Future/HNDRXX"}).status_code == 404
    assert client.get("/api/artists/info", params={"folder": "../etc"}).status_code == 404
