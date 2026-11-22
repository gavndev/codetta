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


def test_the_dz_and_it_bangs_search_albums_and_mark_what_you_have(album_dir, tmp_path):  # noqa: F811
    c, fake, _ = make(album_dir, tmp_path, {"deezer": True, "itunes": False})
    d = c.get("/api/catalog/search", params={"source": "deezer", "q": "fixture album"}).json()
    a = d["albums"][0]
    assert a["id"] == "deezer:302127" and a["title"] == "Fixture Album" and a["artist"] == "Coda Tester"
    assert a["url"].startswith("https://www.deezer.com/") and "in_library" in a
    assert any("q=fixture%20album" in u for u in fake.urls)  # free text, as typed
    assert c.get("/api/catalog/search", params={"source": "itunes", "q": "fixture"}).status_code == 403  # off: never asked
    assert not [u for u in fake.urls if "itunes" in u]
    assert c.get("/api/catalog/search", params={"source": "deezer", "q": "!"}).status_code == 422
    assert c.get("/api/catalog/search", params={"source": "spotify", "q": "x"}).status_code == 422
    c.put("/api/connections", json={"enabled": {"deezer": True, "itunes": True}})
    d = c.get("/api/catalog/search", params={"source": "itunes", "q": "fixture"}).json()
    assert d["albums"][0]["id"] == "itunes:1440857781"
    c.__exit__(None, None, None)


def test_find_in_deezer_or_itunes_searches_only_there(album_dir, tmp_path):  # noqa: F811
    """The chevron next to Find in MusicBrainz: the same review, sourced from one other service."""
    mb = FakeMB()
    c, fake, _ = make(album_dir, tmp_path, {"musicbrainz": True, "deezer": True, "itunes": True}, mb=mb)
    d = c.post("/api/musicbrainz/search", json={"folder": FOLDER, "source": "deezer"}).json()
    assert [x["id"] for x in d["candidates"]] == ["deezer:302127"] and d["query"]["source"] == "deezer"
    assert mb.urls == [] and not [u for u in fake.urls if "itunes" in u]  # only Deezer was asked
    d = c.post("/api/musicbrainz/search", json={"folder": FOLDER, "source": "itunes"}).json()
    assert [x["id"] for x in d["candidates"]] == ["itunes:1440857781"]
    # Then the usual review and write, from that source.
    res = c.post("/api/musicbrainz/apply", json={"folder": FOLDER, "release": "deezer:302127"}).json()
    assert res["updated"] == 3
    c.put("/api/connections", json={"enabled": {"musicbrainz": True, "deezer": False, "itunes": True}})
    assert c.post("/api/musicbrainz/search", json={"folder": FOLDER, "source": "deezer"}).status_code == 403
    c.__exit__(None, None, None)


# --- Issue #3: iTunes matching returned unrelated albums (M.I.A. – Kala) ------------------------------


class FakeITunesForKala:
    """Apple's search as it behaves: "M.I.A. Kala" falls back to popular albums, "Kala" finds other artists'."""

    def __init__(self):
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        album = lambda cid, name, artist: {"wrapperType": "collection", "collectionId": cid, "collectionName": name,  # noqa: E731
                                           "artistName": artist, "trackCount": 10, "releaseDate": "2007-08-08T07:00:00Z"}
        if u.path == "/search" and q.get("entity") == "musicArtist":
            return {"results": [{"wrapperType": "artist", "artistId": 14677454, "artistName": "M.I.A."},
                                {"wrapperType": "artist", "artistId": 262217748, "artistName": "M.I.A."}]}
        if u.path == "/lookup" and q.get("id") == "14677454":
            return {"results": [{"wrapperType": "artist", "artistId": 14677454},
                                album(1440857781, "Kala", "M.I.A."), album(1, "Arular", "M.I.A."), album(2, "MAYA", "M.I.A.")]}
        if u.path == "/lookup":
            return {"results": []}
        if u.path == "/search" and q.get("attribute") == "albumTerm":
            return {"results": [album(10, "KALA (Deluxe Edition)", "Trevor Hall"), album(11, "Kala - Single", "Professional Beat")]}
        if u.path == "/search":
            return {"results": [album(20, "Greatest Hits", "Fleetwood Mac"), album(21, "CrazySexyCool", "TLC"),
                                album(22, "Daydream", "Mariah Carey")]}
        return None


def test_issue_3_the_right_album_comes_first_and_unrelated_ones_never_show():
    fake = FakeITunesForKala()
    found = Catalogs(fake, lambda s: s == "itunes").search("Kala", "M.I.A.", only="itunes")
    assert found[0]["id"] == "itunes:1440857781" and found[0]["title"] == "Kala"
    shown = {(r["title"], r["_artist"]) for r in found}
    assert not shown & {("Greatest Hits", "Fleetwood Mac"), ("CrazySexyCool", "TLC"), ("Daydream", "Mariah Carey")}
    assert ("Arular", "M.I.A.") not in shown  # the artist's other albums aren't this one


def test_the_preferred_edition_country_picks_the_itunes_store():
    fake = FakeITunesForKala()
    Catalogs(fake, lambda s: True, country=lambda: "DE").search("Kala", "M.I.A.", only="itunes")
    urls = [u for u in fake.urls if "itunes.apple.com" in u]
    assert urls[0].endswith("&country=de")
    for i, u in enumerate(urls):  # the US store only as a second try, when the German one had nothing
        assert "country=de" in u or urls[i - 1] == u + "&country=de"
    fake2 = FakeITunesForKala()
    Catalogs(fake2, lambda s: True, country=lambda: "XW").search("Kala", "M.I.A.", only="itunes")
    assert not any("country=" in u for u in fake2.urls)  # "worldwide" isn't a store


def test_apple_music_and_deezer_links_can_be_pasted():
    from codetta.core.catalogs import catalog_link_id
    assert catalog_link_id("https://music.apple.com/de/album/kala/1440857781") == "itunes:1440857781"
    assert catalog_link_id("https://itunes.apple.com/us/album/kala/id1440857781?i=1440857800") == "itunes:1440857781"
    assert catalog_link_id("https://www.deezer.com/en/album/302127") == "deezer:302127"
    assert catalog_link_id("https://musicbrainz.org/release/abc") is None and catalog_link_id("Kala") is None


def test_a_pasted_apple_music_link_opens_that_album(album_dir, tmp_path):  # noqa: F811
    c, fake, arts = make(album_dir, tmp_path, {"musicbrainz": True, "itunes": True})
    r = c.post("/api/musicbrainz/search", json={"folder": FOLDER, "release": "https://music.apple.com/us/album/x/1440857781"})
    assert r.status_code == 200, r.text
    assert r.json()["candidates"][0]["id"] == "itunes:1440857781"
    c.__exit__(None, None, None)
