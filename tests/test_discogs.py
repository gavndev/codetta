"""Discogs: releases turned into tags, searching with a token, and the token kept private."""

import stat
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from codetta.core import discogs
from codetta.core.catalogs import Catalogs, catalog_link_id
from codetta.core.musicbrainz import album_tags, release_tracks, track_tags
from codetta.core.providers import ProviderError
from codetta.web.app import Settings, create_app
from tests.test_musicbrainz import PASSWORD, FakeMB, album_dir, png  # noqa: F401 (fixture)

TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
FOLDER = "Coda Tester/Fixture Album"

# Shaped like a real Discogs release (OK Computer on vinyl), trimmed.
RELEASE = {
    "id": 4950798, "title": "Fixture Album", "year": 1997, "released": "1997-05-21", "country": "UK",
    "uri": "https://www.discogs.com/release/4950798-Coda-Tester-Fixture-Album",
    "artists": [{"name": "Coda Tester (2)", "anv": "", "join": "Feat."}, {"name": "Guest", "join": ""}],
    "labels": [{"name": "Fixture Records (3)", "catno": "FIX 001"}],
    "formats": [{"name": "Vinyl", "qty": "2", "descriptions": ["LP", "Album", "Reissue"]}],
    "identifiers": [{"type": "Barcode", "value": "7 24385 52291 8"}],
    "genres": ["Rock"], "styles": ["Alternative Rock", "Art Rock"],
    "images": [{"type": "secondary", "uri": "https://i.discogs.com/back.jpg"}, {"type": "primary", "uri": "https://i.discogs.com/front.jpg"}],
    "extraartists": [
        {"name": "Nigel Producer", "role": "Producer", "tracks": ""},
        {"name": "Mix Person", "role": "Mixed By [Concerts], Recorded By", "tracks": "A2 to B3"},
        {"name": "Art Person", "role": "Artwork", "tracks": ""},
    ],
    "tracklist": [
        {"position": "", "type_": "heading", "title": "Side A"},
        {"position": "A1", "type_": "track", "title": "Opening", "duration": "4:44"},
        {"position": "A2", "type_": "track", "title": "Middle", "duration": "6:23",
         "extraartists": [{"name": "Writer (4)", "role": "Written-By"}]},
        {"position": "B3", "type_": "track", "title": "Closing", "duration": "4:27",
         "artists": [{"name": "Someone Else", "join": ""}]},
    ],
}


def test_a_release_becomes_tags():
    rel = discogs.release(RELEASE)
    album = album_tags(rel)
    assert album["album"] == ["Fixture Album"] and album["albumartist"] == ["Coda Tester feat. Guest"]
    assert album["date"] == ["1997-05-21"] and album["releasecountry"] == ["GB"] and album["barcode"] == ["724385522918"]
    assert album["label"] == ["Fixture Records"] and album["catalognumber"] == ["FIX 001"]  # "(3)" is Discogs' own
    assert album["genre"][:2] == ["Alternative Rock", "Art Rock"] and album["releasetype"] == ["album"]
    assert rel["_cover"] == "https://i.discogs.com/front.jpg" and rel["media"][0]["format"] == "Vinyl"
    tracks = release_tracks(rel)
    assert [(t.disc, t.position, t.title) for t in tracks] == [(1, 1, "Opening"), (1, 2, "Middle"), (1, 3, "Closing")]
    first, middle, last = (track_tags(rel, t, album) for t in tracks)
    assert first["producer"] == ["Nigel Producer"] and "mixer" not in first  # the mixer only did A2 to B3
    assert middle["mixer"] == ["Mix Person"] and middle["engineer"] == ["Mix Person"] and middle["composer"] == ["Writer"]
    assert last["artist"] == ["Someone Else"] and last["mixer"] == ["Mix Person"]
    assert not [k for k in {**album, **first} if k.startswith("musicbrainz_") and any(first.get(k, album.get(k, [])))]


@pytest.mark.parametrize(("positions", "expected"), [
    (["1-1", "1-2", "2-1"], [(1, 1), (1, 2), (2, 1)]),
    (["CD1-01", "CD2-01"], [(1, 1), (2, 1)]),
    (["A", "B", "C"], [(1, 1), (1, 2), (1, 3)]),  # 7" sides
    (["1", "2", "3"], [(1, 1), (1, 2), (1, 3)]),
    (["", "", ""], [(1, 1), (1, 2), (1, 3)]),
])
def test_positions(positions, expected):
    assert discogs._positions([{"position": p} for p in positions]) == expected


def test_names_and_dates_are_cleaned():
    assert discogs.clean_name("Nirvana (2)") == "Nirvana" and discogs.clean_name("Plank (3)") == "Plank"
    assert discogs.date_of({"released": "2007-00-00"}) == "2007" and discogs.date_of({"year": 1997}) == "1997"


class FakeDiscogs:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/oauth/identity":
            if headers.get("Authorization") != f"Discogs token={TOKEN}":
                raise ProviderError("Discogs answered with an error (401)")
            return {"username": "codetta_fan"}
        if u.path == "/database/search":
            if headers.get("Authorization") != f"Discogs token={TOKEN}":
                raise ProviderError("Discogs answered with an error (401)")
            if q.get("type") == "master":
                return {"results": [{"id": 21491, "title": "Coda Tester - Fixture Album", "year": "1997", "cover_image": "x.jpg"}]}
            return {"results": [
                {"id": 4950798, "title": "Coda Tester (2) - Fixture Album", "country": "UK", "year": "1997",
                 "format": ["Vinyl", "LP", "Album"], "label": ["Fixture Records"], "catno": "FIX 001", "cover_image": "c.jpg"},
                {"id": 1, "title": "Somebody - Greatest Hits", "format": ["CD"]},  # unrelated: never shown
            ]}
        if u.path == "/masters/21491":
            return {"id": 21491, "main_release": 4950798}
        if u.path == "/releases/4950798":
            return RELEASE
        return None


def test_searching_needs_a_token_and_keeps_only_matches():
    fake = FakeDiscogs()
    cat = Catalogs(lambda url: None, lambda s: s == "discogs", discogs=fake, discogs_token=lambda: "")
    with pytest.raises(discogs.DiscogsTokenError):
        cat.search("Fixture Album", "Coda Tester", only="discogs")
    assert cat.search("Fixture Album", "Coda Tester") == []  # a general search just skips Discogs
    cat = Catalogs(lambda url: None, lambda s: s == "discogs", discogs=fake, discogs_token=lambda: TOKEN)
    cat._throttle.interval = 0
    found = cat.search("Fixture Album", "Coda Tester", only="discogs")
    assert [(r["id"], r["title"], r["_artist"]) for r in found] == [("discogs:4950798", "Fixture Album", "Coda Tester")]
    assert all(TOKEN not in url for url, _ in fake.calls)  # the token travels in a header, never the address
    assert cat.release("discogs:m21491")["title"] == "Fixture Album"  # an album opens its main release


def test_links_can_be_pasted():
    assert catalog_link_id("https://www.discogs.com/release/4950798-Radiohead-OK-Computer") == "discogs:4950798"
    assert catalog_link_id("https://www.discogs.com/master/21491-Radiohead-OK-Computer") == "discogs:m21491"
    assert catalog_link_id("https://www.discogs.com/fr/release/99-x") == "discogs:99"


def make(album_dir, tmp_path, env_token=None):  # noqa: F811
    fake = FakeDiscogs()
    app = create_app(Settings(music_dir=album_dir, config_dir=tmp_path / "config", discogs_token=env_token),
                     fetch_mb=FakeMB(error=ProviderError("MusicBrainz is busy")), fetch_art=lambda url: png(),
                     fetch_discogs=fake)
    c = TestClient(app)
    c.__enter__()
    c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
    c.put("/api/connections", json={"enabled": {"discogs": True}})
    return c, fake


def test_the_token_is_checked_saved_privately_and_never_shown(album_dir, tmp_path):  # noqa: F811
    c, _fake = make(album_dir, tmp_path)
    assert c.get("/api/discogs").json()["has_token"] is False
    bad = c.put("/api/discogs", json={"token": "x" * 40}).json()
    assert bad["check"]["ok"] is False and bad["has_token"] is False  # Discogs turned it down: not kept
    d = c.put("/api/discogs", json={"token": TOKEN})
    assert d.json()["check"] == {"ok": True, "username": "codetta_fan"} and TOKEN not in d.text
    assert stat.S_IMODE((tmp_path / "config" / "discogs.json").stat().st_mode) == 0o600
    assert TOKEN not in c.get("/api/discogs").text and TOKEN not in c.get("/api/connections").text
    assert c.put("/api/discogs", json={"token": "short"}).status_code == 422
    assert c.put("/api/discogs", json={"token": ""}).json()["has_token"] is False
    c.__exit__(None, None, None)


def test_find_in_discogs_then_write(album_dir, tmp_path):  # noqa: F811
    c, _fake = make(album_dir, tmp_path, env_token=TOKEN)
    assert c.get("/api/discogs").json()["locked"] is True
    d = c.post("/api/musicbrainz/search", json={"folder": FOLDER, "source": "discogs"}).json()
    assert [x["id"] for x in d["candidates"]] == ["discogs:4950798"]
    res = c.post("/api/musicbrainz/apply", json={"folder": FOLDER, "release": "discogs:4950798"}).json()
    assert res["updated"] == 3
    tags = c.get("/api/track", params={"path": f"{FOLDER}/02.mp3"}).json()["tags"]
    assert tags["composer"] == ["Writer"] and tags["label"] == ["Fixture Records"]
    bang = c.get("/api/catalog/search", params={"source": "discogs", "q": "fixture album"}).json()
    assert bang["albums"][0]["id"] == "discogs:m21491"
    c.__exit__(None, None, None)


def test_searching_without_a_token_explains_itself(album_dir, tmp_path):  # noqa: F811
    c, _fake = make(album_dir, tmp_path)
    r = c.post("/api/musicbrainz/search", json={"folder": FOLDER, "source": "discogs"})
    assert r.status_code == 409 and "Discogs token" in r.json()["detail"]
    r = c.get("/api/catalog/search", params={"source": "discogs", "q": "fixture album"})
    assert r.status_code == 403 and "Discogs token" in r.json()["detail"]
    c.__exit__(None, None, None)


def test_search_results_carry_their_cover_and_catalogue_number():
    """Thumbnails come from the search itself: no slow release lookup per cover (one request a second)."""
    fake = FakeDiscogs()
    cat = Catalogs(lambda url: None, lambda s: s == "discogs", discogs=fake, discogs_token=lambda: TOKEN)
    cat._throttle.interval = 0
    found = cat.search("Fixture Album", "Coda Tester", only="discogs")
    assert found[0]["label-info"][0]["catalog-number"] == "FIX 001"
    asked = len(fake.calls)
    assert cat.cover("discogs:4950798") == "c.jpg" and len(fake.calls) == asked
    albums = cat.search_text("discogs", "fixture album")
    assert cat.cover(albums[0]["id"]) == "x.jpg" and len(fake.calls) == asked + 1


def test_album_thumbnails_from_dg_load(album_dir, tmp_path):  # noqa: F811
    """!dg lists albums ("discogs:m21491"); their thumbnails must load like any other."""
    c, _fake = make(album_dir, tmp_path, env_token=TOKEN)
    c.get("/api/catalog/search", params={"source": "discogs", "q": "fixture album"})
    r = c.get("/api/musicbrainz/cover/discogs:m21491", params={"size": 250})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert c.get("/api/musicbrainz/cover/discogs:mx1", params={"size": 250}).status_code in (403, 422)  # refused
    c.__exit__(None, None, None)
