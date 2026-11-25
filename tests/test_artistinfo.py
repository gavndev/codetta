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
        engine.update_tags(d / "01.flac", {"album": album, "albumartist": "Future", "title": "x", "musicbrainz_albumid": "33333333-3333-3333-3333-333333333333"})
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


def _make(tmp_music, folder, album, tags):
    d = tmp_music / folder / album
    d.mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.flac", d / "01.flac")
    MetadataEngine().update_tags(d / "01.flac", {"album": album, "title": "x", **tags})


@pytest.fixture
def several(tmp_path):
    music = tmp_path / "music"
    _make(music, "Ali Sethi & Nicolas Jaar", "Intiha", {"albumartist": "Ali Sethi & Nicolas Jaar"})
    _make(music, "Simon & Garfunkel", "Bookends", {"albumartist": "Simon & Garfunkel",
                                                   "musicbrainz_albumartistid": "5d02f264-e225-41ff-83f7-d9b1f0b1874a"})
    _make(music, "Metro Boomin & Future", "WDTY", {"albumartist": "Metro Boomin & Future", "albumartists": ["Metro Boomin", "Future"]})
    _make(music, "Future", "HNDRXX", {"albumartist": "Future"})
    _make(music, "Earth, Wind & Fire", "That's the Way", {"albumartist": "Earth, Wind & Fire", "albumartists": ["Earth, Wind & Fire"]})
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        yield c


def test_a_folder_for_several_artists_lists_each_of_them_and_no_bio(several):
    d = several.get("/api/artists/info", params={"folder": "Ali Sethi & Nicolas Jaar"}).json()
    assert [a["name"] for a in d["artists"]] == ["Ali Sethi", "Nicolas Jaar"]
    assert d["bio"] is None and d["similar"] == []
    d = several.get("/api/artists/info", params={"folder": "Metro Boomin & Future"}).json()
    assert [a["name"] for a in d["artists"]] == ["Metro Boomin", "Future"]
    assert d["artists"][1]["folder"] == "Future"  # a picture (and a tap) leads to their own folder


def test_a_duo_or_band_with_one_credit_stays_one_artist(several):
    for folder in ("Simon & Garfunkel", "Earth, Wind & Fire", "Future"):
        assert "artists" not in several.get("/api/artists/info", params={"folder": folder}).json(), folder


# ---- Albums like the one open ----------------------------------------------------------------------

class AlbumFakes(Fakes):
    def deezer(self, url):
        u = urllib.parse.urlparse(url)
        if u.path == "/artist/615/albums":
            self.urls.append(url)
            return {"data": [
                {"id": 1, "title": "DS2", "record_type": "album", "fans": 900, "release_date": "2015-07-17"},  # owned
                {"id": 2, "title": "Honest", "record_type": "album", "fans": 500, "release_date": "2014-04-22"},
                {"id": 5, "title": "DS2 (Deluxe)", "record_type": "album", "fans": 300, "release_date": "2015-07-17"},
                {"id": 6, "title": "HNDRX", "record_type": "album", "fans": 200, "release_date": "2017-02-17"},  # a typo of one you have
                {"id": 7, "title": "Honest (Deluxe)", "record_type": "album", "fans": 150, "release_date": "2014-04-22"},
                {"id": 8, "title": "The Best of Future", "record_type": "album", "fans": 100, "release_date": "2020-01-01"},
                {"id": 3, "title": "Mask Off", "record_type": "single", "fans": 999, "release_date": "2017-01-01"},
            ]}
        if u.path == "/search/artist" and "Young" in url:
            self.urls.append(url)
            return {"data": [{"id": 77, "name": "Young Thug", "nb_fan": 5}]}
        if u.path == "/artist/77/albums":
            self.urls.append(url)
            return {"data": [{"id": 4, "title": "So Much Fun", "record_type": "album", "fans": 50, "release_date": "2019-08-16"}]}
        return super().deezer(url)


@pytest.fixture
def shelf(tmp_path):
    music = tmp_path / "music"
    _make(music, "Future", "HNDRXX", {"albumartist": "Future", "genre": "Trap", "date": "2017", "musicbrainz_albumid": "33333333-3333-3333-3333-333333333333"})
    _make(music, "Future", "Mixtape", {"albumartist": "Future", "genre": "Trap"})  # nothing has identified it
    _make(music, "Future", "DS2", {"albumartist": "Future", "genre": "Trap", "date": "2015"})
    _make(music, "Future/Pluto", "CD1", {"albumartist": "Future", "album": "Pluto", "date": "2012"})  # an album in disc folders
    _make(music, "Future/HNDRXX", "CD2", {"albumartist": "Future", "album": "HNDRXX"})  # this album's other disc
    _make(music, "Metro Boomin", "Heroes", {"albumartist": "Metro Boomin", "genre": "Hip Hop", "date": "2022"})
    _make(music, "Migos", "Culture", {"albumartist": "Migos", "genre": "Trap", "date": "2017"})
    _make(music, "Gucci Mane", "Trap House", {"albumartist": "Gucci Mane", "genre": "Trap", "date": "2005"})
    _make(music, "Björk", "Vespertine", {"albumartist": "Björk", "genre": "Electronic", "date": "2001"})
    fakes = AlbumFakes()
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"), fetch_mb=fakes.mb,
                     fetch_wiki=fakes.wiki, fetch_catalog=fakes.deezer)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        import time
        for _ in range(200):
            if app.state.index.status().ready:
                break
            time.sleep(0.05)
        c.fakes = fakes
        yield c


def test_albums_like_this_one_come_from_the_library_first(shelf):
    d = shelf.get("/api/albums/like", params={"folder": "Future/HNDRXX"}).json()
    assert [a["folder"] for a in d["more"]] == ["Future/DS2", "Future/Mixtape", "Future/Pluto"]  # not itself; an album, not its disc
    assert d["more"][0]["title"] == "DS2" and d["more"][0]["year"] == "2015"
    # Deezer off: the same genre, the closest years first; nothing asked online.
    assert [a["folder"] for a in d["like"]] == ["Migos/Culture", "Gucci Mane/Trap House"]
    assert not shelf.fakes.urls
    shelf.put("/api/connections", json={"enabled": {"deezer": True}})
    d = shelf.get("/api/albums/like", params={"folder": "Future/HNDRXX"}).json()
    assert [a["folder"] for a in d["like"]][0] == "Metro Boomin/Heroes"  # a similar artist before the genre


def test_albums_not_in_the_library_need_deezer_and_leave_out_what_you_have(shelf):
    assert shelf.get("/api/albums/elsewhere", params={"folder": "Future/HNDRXX"}).json() == {"albums": [], "can": False}
    assert not shelf.fakes.urls
    shelf.put("/api/connections", json={"enabled": {"deezer": True}})
    d = shelf.get("/api/albums/elsewhere", params={"folder": "Future/HNDRXX"}).json()
    got = [(a["title"], a["why"]) for a in d["albums"]]
    assert got == [("Honest", "artist"), ("So Much Fun", "similar")]  # DS2 is owned, Mask Off is a single
    assert d["albums"][0]["id"] == "deezer:2" and d["albums"][0]["year"] == "2014"


def test_albums_like_only_for_folders_in_the_library(shelf):
    assert shelf.get("/api/albums/like", params={"folder": "../etc"}).status_code == 404
    assert shelf.get("/api/albums/elsewhere", params={"folder": "Nope"}).status_code in (200, 404)


def test_an_album_nothing_has_identified_gets_no_suggestions(shelf):
    shelf.put("/api/connections", json={"enabled": {"deezer": True}})
    d = shelf.get("/api/albums/like", params={"folder": "Future/Mixtape"}).json()
    assert d["identified"] is False and d["more"] == [] and d["like"] == []
    assert shelf.get("/api/albums/elsewhere", params={"folder": "Future/Mixtape"}).json()["albums"] == []
    assert not shelf.fakes.urls  # nothing asked about it


def test_an_artist_with_no_identified_album_gets_no_bio_or_similar_artists(several):
    several.put("/api/connections", json={"enabled": {"musicbrainz": True, "wikipedia": True, "deezer": True}})
    d = several.get("/api/artists/info", params={"folder": "Future"}).json()
    assert d["identified"] is False and d["bio"] is None and d["similar"] == []


def test_one_musicbrainz_id_naming_only_one_of_the_artists_still_splits(tmp_path):
    music = tmp_path / "music"
    sethi = "9da378d4-2a00-46c7-8050-26d51dd522ac"
    _make(music, "Ali Sethi & Nicolas Jaar", "Intiha", {"albumartist": "Ali Sethi & Nicolas Jaar", "musicbrainz_albumartistid": sethi})
    _make(music, "Simon & Garfunkel", "Bookends", {"albumartist": "Simon & Garfunkel", "musicbrainz_albumartistid": "5d02f264-e225-41ff-83f7-d9b1f0b1874a"})
    names = {sethi: "Ali Sethi", "5d02f264-e225-41ff-83f7-d9b1f0b1874a": "Simon & Garfunkel"}

    def mb(url):
        mbid = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
        return {"id": mbid, "name": names[mbid]} if mbid in names else None
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"), fetch_mb=mb)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.put("/api/connections", json={"enabled": {"musicbrainz": True}})
        d = c.get("/api/artists/info", params={"folder": "Ali Sethi & Nicolas Jaar"}).json()
        assert [a["name"] for a in d["artists"]] == ["Ali Sethi", "Nicolas Jaar"]
        assert "artists" not in c.get("/api/artists/info", params={"folder": "Simon & Garfunkel"}).json()


def test_a_collaboration_gets_albums_by_the_pair_or_none(tmp_path):
    music = tmp_path / "music"
    _make(music, "Ali Sethi & Nicolas Jaar", "Intiha", {"albumartist": "Ali Sethi & Nicolas Jaar", "genre": "Ambient",
                                                        "musicbrainz_albumid": "33333333-3333-3333-3333-333333333333"})
    _make(music, "Ali Sethi", "Love Language", {"albumartist": "Ali Sethi", "genre": "Pop"})
    asked = []

    def deezer(url):
        asked.append(url)
        u = urllib.parse.urlparse(url)
        if u.path == "/search/artist":  # Deezer's top hit for the pair is one of them alone
            return {"data": [{"id": 9, "name": "Ali Sethi", "nb_fan": 5}]}
        if u.path == "/artist/9/albums":
            return {"data": [{"id": 1, "title": "Room Jhoom", "record_type": "album", "fans": 9}]}
        if u.path == "/artist/9/related":
            return {"data": [{"name": "Abida Parveen"}]}
        return None
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"), fetch_catalog=deezer)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.put("/api/connections", json={"enabled": {"deezer": True}})
        folder = {"folder": "Ali Sethi & Nicolas Jaar/Intiha"}
        assert c.get("/api/albums/elsewhere", params=folder).json()["albums"] == []
        like = c.get("/api/albums/like", params=folder).json()
        assert like["more"] == [] and like["like"] == []  # not Ali Sethi's own album
        assert not any("/artist/9/" in u for u in asked)  # nothing asked (or kept) about either one alone
