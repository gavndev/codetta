"""Explore MusicBrainz (the !mb bang): artist and release pages, marked when they're in the library."""

import shutil
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.musicbrainz import artist_links, pick_release, tracklist
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

ART = "11111111-1111-1111-1111-111111111111"
RG1 = "22222222-2222-2222-2222-222222222222"
RG2 = "33333333-3333-3333-3333-333333333333"
REL = "44444444-4444-4444-4444-444444444444"
CREDIT = [{"name": "Kehlani", "artist": {"id": ART, "name": "Kehlani"}}]


class FakeExplore:
    def __init__(self):
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        if u.path.endswith("/artist") and "query" in q:
            return {"artists": [{"id": ART, "name": "Kehlani", "type": "Person", "country": "US", "score": 100,
                                 "area": {"name": "Oakland"}, "life-span": {"begin": "1995-04-24"}},
                                {"id": "55555555-5555-5555-5555-555555555555", "name": "Kehl", "score": 30}]}
        if u.path.endswith("/release-group") and "query" in q:
            return {"release-groups": [{"id": RG1, "title": "SweetSexySavage (Deluxe)", "primary-type": "Album",
                                        "first-release-date": "2017-01-27", "artist-credit": CREDIT, "score": 95}]}
        if u.path.endswith("/release-group") and "artist" in q:
            return {"release-groups": [
                {"id": RG2, "title": "Nights Like This", "primary-type": "Single", "first-release-date": "2019-02-01"},
                {"id": RG1, "title": "SweetSexySavage", "primary-type": "Album", "first-release-date": "2017-01-27"}]}
        if u.path.endswith(f"/artist/{ART}"):
            return {"id": ART, "name": "Kehlani", "type": "Person", "genres": [{"name": "r&b", "count": 5}],
                    "relations": [{"type": "official homepage", "url": {"resource": "https://kehlani.com"}},
                                  {"type": "wikipedia", "url": {"resource": "javascript:alert(1)"}}]}
        if u.path.endswith(f"/release-group/{RG1}"):
            return {"id": RG1, "title": "SweetSexySavage", "primary-type": "Album", "first-release-date": "2017-01-27",
                    "artist-credit": CREDIT, "releases": [
                        {"id": "66666666-6666-6666-6666-666666666666", "status": "Bootleg", "date": "2016-01-01"},
                        {"id": REL, "status": "Official", "date": "2017-01-27"}]}
        if u.path.endswith(f"/release/{REL}"):
            return {"id": REL, "date": "2017-01-27", "country": "US",
                    "label-info": [{"catalog-number": "551384-2", "label": {"name": "Atlantic"}}],
                    "media": [{"format": "Digital Media", "tracks": [
                        {"number": "1", "title": "Intro", "length": 61000},
                        {"number": "2", "title": "Keep On", "length": 218000,
                         "artist-credit": [{"name": "Kehlani", "joinphrase": " feat. ", "artist": {"id": ART}},
                                           {"name": "Zayn", "artist": {"id": "x"}}]}]}]}
        return None


def test_helpers():
    assert artist_links({"relations": [{"type": "wikipedia", "url": {"resource": "javascript:alert(1)"}},
                                       {"type": "bandcamp", "url": {"resource": "https://x.bandcamp.com"}}]}) == [
        {"label": "Bandcamp", "url": "https://x.bandcamp.com"}]  # only http(s) links reach the page
    assert pick_release({"releases": [{"id": REL, "status": "Official", "date": "2017"},
                                      {"id": RG1, "status": "Bootleg", "date": "2000"}]})["id"] == REL
    t = tracklist({"media": [{"tracks": [{"number": "1", "title": "A", "length": 61000}]}]})
    assert t == [{"disc": 1, "discs": 1, "number": "1", "title": "A", "length": 61, "artist": ""}]


@pytest.fixture
def client(tmp_path):
    music = tmp_path / "music"
    folder = music / "Kehlani" / "SweetSexySavage"
    folder.mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.flac", folder / "01.flac")
    MetadataEngine().update_tags(folder / "01.flac", {"album": "SweetSexySavage", "albumartist": "Kehlani", "title": "Intro"})
    fake = FakeExplore()
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config", auth=False), fetch_mb=fake)
    with TestClient(app) as c:
        end = time.time() + 10
        while not app.state.index.status().ready:
            assert time.time() < end
            time.sleep(0.05)
        c.put("/api/connections", json={"enabled": {"musicbrainz": True}})
        yield c, fake


def test_search_finds_artists_and_releases_marking_what_you_have(client):
    c, _ = client
    d = c.get("/api/mb/search", params={"q": "kehlani"}).json()
    assert [a["name"] for a in d["artists"]] == ["Kehlani"]  # weak matches (score < 60) are dropped
    assert d["artists"][0]["area"] == "Oakland" and d["artists"][0]["begin"] == "1995"
    rel = d["releases"][0]
    assert rel["title"] == "SweetSexySavage (Deluxe)" and rel["year"] == "2017"
    assert rel["in_library"] == "Kehlani/SweetSexySavage"  # "(Deluxe)" doesn't hide it


def test_artist_page(client):
    c, _ = client
    d = c.get(f"/api/mb/artist/{ART}").json()
    assert d["name"] == "Kehlani" and d["genres"] == ["r&b"]
    assert d["links"] == [{"label": "Website", "url": "https://kehlani.com"}]
    groups = {g["title"]: g for g in d["groups"]}
    assert [g["title"] for g in d["groups"]] == ["SweetSexySavage", "Nights Like This"]  # oldest first
    assert groups["SweetSexySavage"]["in_library"] == "Kehlani/SweetSexySavage"
    assert groups["Nights Like This"]["in_library"] is None


def test_release_page_shows_the_first_official_edition(client):
    c, _ = client
    d = c.get(f"/api/mb/release-group/{RG1}").json()
    assert d["artist_id"] == ART and d["editions"] == 2 and d["in_library"] == "Kehlani/SweetSexySavage"
    r = d["release"]
    assert r["id"] == REL and r["label"] == "Atlantic" and r["catno"] == "551384-2" and r["format"] == "Digital Media"
    assert [t["title"] for t in r["tracks"]] == ["Intro", "Keep On"] and r["tracks"][1]["artist"] == "Kehlani feat. Zayn"
    assert r["tracks"][0]["length"] == 61


def test_explore_needs_the_musicbrainz_connection_and_valid_ids(client):
    c, fake = client
    assert c.get("/api/mb/artist/not-an-id").status_code == 502
    c.put("/api/connections", json={"enabled": {"musicbrainz": False}})
    before = len(fake.urls)
    assert c.get("/api/mb/search", params={"q": "x"}).status_code == 403
    assert len(fake.urls) == before  # nothing was sent
    assert c.get("/api/musicbrainz/cover/" + RG1, params={"kind": "nope"}).status_code in (403, 422)
