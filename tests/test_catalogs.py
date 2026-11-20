"""Deezer and iTunes as album sources next to MusicBrainz, against fake servers (never the internet)."""

import urllib.parse

from fastapi.testclient import TestClient

from codetta.core.catalogs import Catalogs, is_catalog_id
from codetta.core.musicbrainz import album_tags, release_tracks, track_tags
from codetta.core.providers import ProviderError
from codetta.web.app import Settings, create_app
from tests.test_musicbrainz import PASSWORD, FakeMB, album_dir, png  # noqa: F401 (fixture)

FOLDER = "Coda Tester/Fixture Album"
TRACKS = [("Opening", 1, 1000), ("Middle", 2, 1000), ("Closing", 3, 1000)]


class FakeCatalogs:
    def __init__(self):
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        u = urllib.parse.urlparse(url)
        if u.netloc == "api.deezer.com" and u.path == "/search/album":
            return {"data": [{"id": 302127, "title": "Fixture Album", "artist": {"name": "Coda Tester"}, "nb_tracks": 3,
                              "record_type": "album", "cover_xl": "https://cdn-images.dzcdn.net/cover.jpg"}]}
        if u.netloc == "api.deezer.com" and u.path == "/album/302127":
            return {"id": 302127, "title": "Fixture Album", "artist": {"name": "Coda Tester"}, "release_date": "2024-03-01",
                    "label": "Fixture Records", "upc": "0123456789012", "nb_tracks": 3, "record_type": "album",
                    "cover_xl": "https://cdn-images.dzcdn.net/cover.jpg", "link": "https://www.deezer.com/album/302127",
                    "genres": {"data": [{"name": "Indie"}]},
                    "tracks": {"data": [{"title": t, "track_position": n, "disk_number": 1, "duration": d // 1000,
                                         "artist": {"name": "Coda Tester"}, "isrc": f"GBAAA240000{n}"} for t, n, d in TRACKS]}}
        if u.netloc == "itunes.apple.com" and u.path == "/search":
            return {"results": [{"wrapperType": "collection", "collectionId": 1440857781, "collectionName": "Fixture Album",
                                 "artistName": "Coda Tester", "artworkUrl100": "https://is1-ssl.mzstatic.com/a/100x100bb.jpg",
                                 "releaseDate": "2024-03-01T07:00:00Z", "trackCount": 3, "copyright": "℗ 2024 Fixture Records"}]}
        if u.netloc == "itunes.apple.com" and u.path == "/lookup":
            return {"results": [{"wrapperType": "collection", "collectionId": 1440857781, "collectionName": "Fixture Album",
                                 "artistName": "Coda Tester", "artworkUrl100": "https://is1-ssl.mzstatic.com/a/100x100bb.jpg",
                                 "releaseDate": "2024-03-01T07:00:00Z", "trackCount": 3, "primaryGenreName": "Alternative"}]
                    + [{"wrapperType": "track", "trackName": t, "trackNumber": n, "discNumber": 1, "trackTimeMillis": d,
                        "artistName": "Coda Tester"} for t, n, d in TRACKS]}
        return None


def make(album_dir, tmp_path, enabled, mb=None):  # noqa: F811
    fake = FakeCatalogs()
    arts = []
    app = create_app(Settings(music_dir=album_dir, config_dir=tmp_path / "config"),
                     fetch_mb=mb or FakeMB(), fetch_art=lambda url: (arts.append(url), png())[1], fetch_catalog=fake)
    c = TestClient(app)
    c.__enter__()
    c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
    c.put("/api/connections", json={"enabled": enabled})
    return c, fake, arts


def tags(c, name):
    return c.get("/api/track", params={"path": f"{FOLDER}/{name}"}).json()["tags"]


def test_deezer_album_becomes_a_release_without_musicbrainz_ids():
    cat = Catalogs(FakeCatalogs(), lambda s: True)
    rel = cat.release("deezer:302127")
    assert rel["title"] == "Fixture Album" and rel["_cover"].endswith("cover.jpg")
    t = release_tracks(rel)
    assert [x.title for x in t] == ["Opening", "Middle", "Closing"]
    tags_ = track_tags(rel, t[0])
    assert tags_["title"] == ["Opening"] and tags_["album"] == ["Fixture Album"] and tags_["label"] == ["Fixture Records"]
    assert tags_["isrc"] == ["GBAAA2400001"] and tags_["genre"] == ["Indie"]
    assert not [k for k in {**tags_, **album_tags(rel)} if k.startswith("musicbrainz_")]
    assert is_catalog_id("itunes:1") and not is_catalog_id("11111111-1111-4111-8111-111111111111")


def test_itunes_cleans_up_names_and_covers():
    cat = Catalogs(FakeCatalogs(), lambda s: True)
    (found,) = [r for r in cat.search("Fixture Album", "Coda Tester") if r["_source"] == "itunes"]
    assert found["_cover"].endswith("1200x1200bb.jpg")  # the big version, not the 100px thumbnail
    rel = cat.release("itunes:1440857781")
    assert [x.title for x in release_tracks(rel)] == ["Opening", "Middle", "Closing"] and rel["genres"][0]["name"] == "Alternative"


def test_off_connections_are_never_asked():
    fake = FakeCatalogs()
    cat = Catalogs(fake, lambda s: False)
    assert cat.search("Fixture Album", "Coda Tester") == [] and fake.urls == []


def test_match_from_deezer_when_musicbrainz_is_off(album_dir, tmp_path):  # noqa: F811
    c, fake, arts = make(album_dir, tmp_path, {"deezer": True})
    assert c.get("/api/status").json()["matching"] is True
    found = c.post("/api/musicbrainz/search", json={"folder": FOLDER}).json()["candidates"]
    assert found and found[0]["id"] == "deezer:302127" and found[0]["source"] == "deezer"
    res = c.post("/api/musicbrainz/apply", json={"folder": FOLDER, "release": "deezer:302127"}).json()
    assert res["updated"] == 3 and res["cover_error"] is None
    t = tags(c, "01.flac")
    assert t["title"] == ["Opening"] and t["album"] == ["Fixture Album"] and t["label"] == ["Fixture Records"]
    assert not [k for k in t if k.startswith("musicbrainz_")]  # nothing pretends to be a MusicBrainz ID
    assert arts == ["https://cdn-images.dzcdn.net/cover.jpg"]  # Deezer's cover, fetched by the server
    assert not [u for u in fake.urls if "itunes" in u]  # iTunes is off: never asked
    c.__exit__(None, None, None)


def test_itunes_answers_when_musicbrainz_is_down(album_dir, tmp_path):  # noqa: F811
    c, fake, arts = make(album_dir, tmp_path, {"musicbrainz": True, "itunes": True},
                         mb=FakeMB(error=ProviderError("MusicBrainz is busy right now.")))
    data = c.post("/api/musicbrainz/search", json={"folder": FOLDER}).json()
    assert data["candidates"][0]["id"] == "itunes:1440857781" and "didn't answer" in data["note"]
    assert c.get("/api/musicbrainz/cover/itunes:1440857781").status_code == 200  # thumbnails through the server
    c.__exit__(None, None, None)


def test_musicbrainz_first_and_no_fallback_when_it_fits(album_dir, tmp_path):  # noqa: F811
    c, fake, arts = make(album_dir, tmp_path, {"musicbrainz": True, "deezer": True})
    found = c.post("/api/musicbrainz/search", json={"folder": FOLDER}).json()["candidates"]
    assert found[0]["source"] == "musicbrainz" and fake.urls == []  # a good MusicBrainz match: Deezer isn't asked
    c.__exit__(None, None, None)
