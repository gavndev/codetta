"""MusicBrainz matching, with a fake MusicBrainz: tests never touch the internet."""

import io
import shutil
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.musicbrainz import (
    VARIOUS_ARTISTS,
    FileInfo,
    MusicBrainz,
    album_tags,
    pair_files,
    parse_release_id,
    release_tracks,
    similarity,
    summarize,
    track_tags,
)
from codetta.core.providers import ProviderError
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

PASSWORD = "correct horse 1"
REL = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
ARTIST = {"id": "33333333-3333-4333-8333-333333333333", "name": "Coda Tester", "sort-name": "Tester, Coda"}
GUEST = {"id": "44444444-4444-4444-8444-444444444444", "name": "Guest", "sort-name": "Guest"}


def png() -> bytes:
    # A real (tiny) PNG, so the image sniffing accepts it.
    with open(FIXTURES_DIR / "cover.png", "rb") as f:
        return f.read()


def track(n, title, ms=1000, credit=None, rels=None, isrcs=None):
    rid = f"aaaaaaaa-0000-4000-8000-{n:012d}"
    return {
        "id": f"bbbbbbbb-0000-4000-8000-{n:012d}", "position": n, "number": str(n), "title": title, "length": ms,
        "artist-credit": credit or [{"name": "Coda Tester", "joinphrase": "", "artist": ARTIST}],
        "recording": {"id": rid, "title": title, "length": ms, "isrcs": isrcs or [], "relations": rels or []},
    }


def release(mbid=REL, title="Fixture Album", tracks=None, discs=None, **extra):
    media = discs or [{"position": 1, "format": "CD", "track-count": len(tracks or []), "tracks": tracks or []}]
    return {
        "id": mbid, "title": title, "status": "Official", "date": "2024-03-01", "country": "GB",
        "barcode": "0123456789012", "text-representation": {"script": "Latn", "language": "eng"},
        "artist-credit": [{"name": "Coda Tester", "joinphrase": "", "artist": ARTIST}],
        "release-group": {"id": "55555555-5555-4555-8555-555555555555", "primary-type": "Album",
                          "secondary-types": ["Live"], "first-release-date": "2023"},
        "label-info": [{"catalog-number": "CODA-001", "label": {"name": "Fixture Records"}}],
        "genres": [{"name": "indie rock", "count": 5}, {"name": "pop", "count": 9}],
        "cover-art-archive": {"front": True},
        "media": media,
        **extra,
    }


PRODUCER = {"target-type": "artist", "type": "producer", "artist": {"name": "Pat Producer"}}
WORK = {"target-type": "work", "type": "performance", "work": {
    "id": "66666666-6666-4666-8666-666666666666",
    "relations": [{"target-type": "artist", "type": "composer", "artist": {"name": "Cam Composer"}},
                  {"target-type": "artist", "type": "lyricist", "artist": {"name": "Lee Lyricist"}}]}}

ALBUM = release(tracks=[
    track(1, "Opening", rels=[PRODUCER, WORK], isrcs=["GBAAA2400001"]),
    track(2, "Middle", credit=[{"name": "Coda Tester", "joinphrase": " feat. ", "artist": ARTIST},
                               {"name": "Guest", "joinphrase": "", "artist": GUEST}]),
    track(3, "Closing"),
])


class FakeMB:
    def __init__(self, releases=(ALBUM,), search=None, error=None):
        self.releases = {r["id"]: r for r in releases}
        self.search = search if search is not None else [
            {**summary_source(r), "score": 100} for r in releases]
        self.error = error
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        path = urllib.parse.urlparse(url).path
        if path.endswith("/release"):
            return {"releases": self.search}
        return self.releases.get(path.rsplit("/", 1)[-1])


def summary_source(r):
    """What a search result has (no track lists)."""
    return {k: v for k, v in r.items() if k != "media"} | {
        "track-count": sum(len(m["tracks"]) for m in r["media"]),
        "media": [{"format": m["format"], "track-count": len(m["tracks"])} for m in r["media"]]}


# --- Unit ---------------------------------------------------------------------------------


def test_parse_release_id():
    assert parse_release_id(REL) == REL
    assert parse_release_id(f"https://musicbrainz.org/release/{REL.upper()}/edit") == REL
    assert parse_release_id(f"https://beta.musicbrainz.org/release/{REL}") == REL
    assert parse_release_id(f"https://musicbrainz.org/release-group/{REL}") is None
    assert parse_release_id("not an id") is None


def test_similarity_is_forgiving():
    assert similarity("Sigur Rós", "sigur ros") == 1
    assert similarity("Abbey Road", "Abbey Road (Remastered)") >= 0.85
    assert similarity("Rock & Roll", "rock and roll") == 1
    assert similarity("Something", "Completely different") < 0.5


def test_album_and_track_tags():
    tracks = release_tracks(ALBUM)
    album = album_tags(ALBUM)
    assert album["releasetype"] == ["album", "live"] and album["releasestatus"] == ["official"]
    assert album["label"] == ["Fixture Records"] and album["catalognumber"] == ["CODA-001"]
    assert album["genre"] == ["Pop", "Indie Rock"]  # most votes first
    assert "compilation" not in album
    t1 = track_tags(ALBUM, tracks[0], album)
    assert t1["title"] == ["Opening"] and t1["tracknumber"] == ["1/3"] and t1["discnumber"] == ["1/1"]
    assert t1["musicbrainz_albumid"] == [REL] and t1["musicbrainz_trackid"] == ["aaaaaaaa-0000-4000-8000-000000000001"]
    assert t1["musicbrainz_releasetrackid"] == ["bbbbbbbb-0000-4000-8000-000000000001"]
    assert t1["producer"] == ["Pat Producer"] and t1["composer"] == ["Cam Composer"] and t1["lyricist"] == ["Lee Lyricist"]
    assert t1["musicbrainz_workid"] == ["66666666-6666-4666-8666-666666666666"]
    assert t1["isrc"] == ["GBAAA2400001"] and t1["media"] == ["CD"] and t1["script"] == ["Latn"]
    assert t1["albumartistsort"] == ["Tester, Coda"]
    t2 = track_tags(ALBUM, tracks[1], album)
    assert t2["artist"] == ["Coda Tester feat. Guest"] and t2["artists"] == ["Coda Tester", "Guest"]
    assert t2["musicbrainz_artistid"] == [ARTIST["id"], GUEST["id"]]
    assert t2["artistsort"] == ["Tester, Coda feat. Guest"]
    assert "producer" not in t2 and "discsubtitle" not in t2  # empty values are left out


def test_various_artists_is_a_compilation():
    va = release(tracks=[track(1, "x")], **{"artist-credit": [
        {"name": "Various Artists", "joinphrase": "", "artist": {"id": VARIOUS_ARTISTS, "name": "Various Artists"}}]})
    assert album_tags(va)["compilation"] == ["1"]


def test_summary():
    s = summarize(release(tracks=[track(1, "x")], discs=[
        {"position": 1, "format": "CD", "tracks": [track(1, "x")]},
        {"position": 2, "format": "CD", "tracks": [track(2, "y")]}]))
    assert s["formats"] == "2×CD" and s["labels"] == ["Fixture Records (CODA-001)"] and s["track_count"] == 2
    assert s["type"] == "Album · Live" and s["has_cover"] is True


def test_pairs_by_track_number():
    tracks = release_tracks(ALBUM)
    files = [FileInfo("c.flac", "Closing", tracknumber=3, duration=1.0),
             FileInfo("a.flac", "Opening", tracknumber=1, duration=1.0),
             FileInfo("b.flac", "", tracknumber=2)]
    p = pair_files(files, tracks)
    assert [p[f].track.title for f in ("a.flac", "b.flac", "c.flac")] == ["Opening", "Middle", "Closing"]
    assert p["a.flac"].confidence == "high"


def test_pairs_by_title_when_numbers_are_missing_or_wrong():
    tracks = release_tracks(ALBUM)
    files = [FileInfo("x.flac", "closing", tracknumber=1, duration=1.0),  # wrong number, title says Closing
             FileInfo("y.flac", "Opening", duration=1.0)]
    p = pair_files(files, tracks)
    assert p["x.flac"].track.title == "Closing" and p["y.flac"].track.title == "Opening"
    assert p["x.flac"].confidence == "check"


def test_multi_disc_numbered_straight_through():
    rel = release(discs=[{"position": 1, "format": "CD", "tracks": [track(1, "One"), track(2, "Two")]},
                         {"position": 2, "format": "CD", "tracks": [track(1, "Three") | {"id": "t3"}]}])
    p = pair_files([FileInfo("3.flac", tracknumber=3)], release_tracks(rel))
    assert p["3.flac"].track.title == "Three" and p["3.flac"].track.disc == 2


def test_multi_disc_with_disc_numbers():
    rel = release(discs=[{"position": 1, "format": "CD", "tracks": [track(1, "One")]},
                         {"position": 2, "format": "CD", "tracks": [track(1, "Uno") | {"id": "t2"}]}])
    p = pair_files([FileInfo("d2.flac", tracknumber=1, discnumber=2)], release_tracks(rel))
    assert p["d2.flac"].track.title == "Uno"


def test_users_pick_wins_and_none_skips():
    tracks = release_tracks(ALBUM)
    files = [FileInfo("a.flac", "Opening", tracknumber=1), FileInfo("b.flac", "Middle", tracknumber=2)]
    p = pair_files(files, tracks, {"a.flac": tracks[2].id, "b.flac": None})
    assert p["a.flac"].track.title == "Closing" and p["b.flac"].track is None


def test_unmatched_files_are_reported():
    p = pair_files([FileInfo("z.flac", "Nothing like it", duration=600)], release_tracks(ALBUM))
    assert p["z.flac"].track is None and p["z.flac"].confidence == "none"


def test_rate_limit_and_cache():
    now = [100.0]
    slept = []
    fake = FakeMB()
    mb = MusicBrainz(fake, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    mb.release(REL)
    mb.search("Fixture Album", "Coda Tester")
    assert slept and abs(slept[0] - 1.0) < 1e-6  # waited a second between the two
    mb.release(REL)
    assert len(fake.urls) == 2  # the second lookup came from the cache


def test_search_query_is_escaped():
    fake = FakeMB()
    MusicBrainz(fake, min_interval=0).search('AC/DC: "Live"', "Guns N' Roses")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(fake.urls[0]).query)["query"][0]
    assert q == 'release:(AC\\/DC\\: \\"Live\\") AND artist:(Guns N\' Roses)'


def test_bad_release_id_never_reaches_the_network():
    fake = FakeMB()
    with pytest.raises(ProviderError):
        MusicBrainz(fake).release("../../etc")
    assert fake.urls == []


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
def album_dir(tmp_path):
    """Three files of one album in three formats, with rough tags."""
    music = tmp_path / "music"
    album = music / "Coda Tester" / "Fixture Album"
    album.mkdir(parents=True)
    engine = MetadataEngine()
    for n, (src, title) in enumerate([("sample.flac", "opening"), ("sample.mp3", "Middle"), ("sample.m4a", "Closing")], 1):
        dest = album / f"0{n}.{src.split('.')[1]}"
        shutil.copy2(FIXTURES_DIR / src, dest)
        engine.update_tags(dest, {"title": title, "tracknumber": str(n), "discnumber": None})
    return music


@pytest.fixture
def make_client(album_dir, tmp_path):
    opened = []

    def make(fake=None, art=None, enable=True, **settings):
        fake = fake or FakeMB()
        art_calls = []

        def fetch_art(url):
            art_calls.append(url)
            if isinstance(art, Exception):
                raise art
            return art

        app = create_app(Settings(music_dir=album_dir, config_dir=tmp_path / "config", **settings),
                         fetch_mb=fake, fetch_art=fetch_art)
        c = TestClient(app)
        c.__enter__()
        opened.append(c)
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        if enable:
            c.put("/api/connections", json={"enabled": {"musicbrainz": True}})
        c.fake, c.art_calls = fake, art_calls
        return c
    yield make
    for c in opened:
        c.__exit__(None, None, None)


FOLDER = "Coda Tester/Fixture Album"


def tags(c, name):
    return c.get("/api/track", params={"path": f"{FOLDER}/{name}"}).json()["tags"]


def test_routes_are_private_and_off_by_default(make_client):
    c = make_client(enable=False)
    for method, url in [("post", "/api/musicbrainz/search"), ("post", "/api/musicbrainz/preview"),
                        ("post", "/api/musicbrainz/apply")]:
        res = getattr(c, method)(url, json={"folder": FOLDER, "release": REL})
        assert res.status_code == 403
    assert c.get(f"/api/musicbrainz/cover/{REL}").status_code == 403
    assert c.fake.urls == [] and c.art_calls == []  # nothing left the server
    c.post("/api/auth/logout")
    assert c.post("/api/musicbrainz/search", json={"folder": FOLDER}).status_code == 401


def test_search_scores_the_right_edition_first(make_client):
    other = release(OTHER, title="Fixture Album (Deluxe)", tracks=[track(i, f"t{i}") for i in range(1, 13)])
    c = make_client(FakeMB([ALBUM, other], search=[{**summary_source(other), "score": 100},
                                                   {**summary_source(ALBUM), "score": 95}]))
    data = c.post("/api/musicbrainz/search", json={"folder": FOLDER}).json()
    assert data["query"] == {"album": "Fixture Album", "artist": "Coda Collective", "files": 3}
    assert [x["id"] for x in data["candidates"]] == [REL, OTHER]  # 3 tracks beats 12
    assert data["candidates"][0]["score"] > data["candidates"][1]["score"]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(c.fake.urls[0]).query)["query"][0]
    assert "Fixture Album" in q and "Coda Collective" in q


def test_search_by_pasted_link(make_client):
    c = make_client()
    data = c.post("/api/musicbrainz/search", json={"folder": FOLDER, "release": f"https://musicbrainz.org/release/{REL}"}).json()
    assert [x["id"] for x in data["candidates"]] == [REL]
    assert c.post("/api/musicbrainz/search", json={"folder": FOLDER, "release": "nope"}).status_code == 422


def test_already_tagged_release_is_offered_first(make_client, album_dir):
    MetadataEngine().update_tags(album_dir / FOLDER / "01.flac", {"musicbrainz_albumid": REL})
    c = make_client(FakeMB(search=[]))
    data = c.post("/api/musicbrainz/search", json={"folder": FOLDER}).json()
    assert data["current"] == REL and data["candidates"][0]["current"]


def test_preview_writes_nothing(make_client):
    c = make_client()
    before = tags(c, "01.flac")
    p = c.post("/api/musicbrainz/preview", json={"folder": FOLDER, "release": REL}).json()
    assert tags(c, "01.flac") == before
    files = {f["path"].rsplit("/", 1)[1]: f for f in p["files"]}
    assert files["01.flac"]["track"]["title"] == "Opening"
    assert files["01.flac"]["changes"]["title"] == {"old": ["opening"], "new": ["Opening"]}
    assert files["02.mp3"]["changes"]["artist"]["new"] == ["Coda Tester feat. Guest"]
    assert "genre" not in files["01.flac"]["changes"]  # off unless asked for
    assert files["01.flac"]["cover"] is True  # sample has no art, release has a cover
    assert {g["id"] for g in p["groups"]} >= {"basics", "credits", "ids", "genre"}
    assert next(g for g in p["groups"] if g["id"] == "genre")["default"] is False


def test_apply_writes_tags_and_cover_and_undoes(make_client):
    c = make_client(art=png())
    res = c.post("/api/musicbrainz/apply", json={"folder": FOLDER, "release": REL}).json()
    assert res["updated"] == 3 and res["failed"] == 0 and res["cover_error"] is None
    for name, title in [("01.flac", "Opening"), ("02.mp3", "Middle"), ("03.m4a", "Closing")]:
        t = tags(c, name)
        assert t["title"] == [title] and t["musicbrainz_albumid"] == [REL]
        assert t["musicbrainz_releasegroupid"] == ["55555555-5555-4555-8555-555555555555"]
        assert t["label"] == ["Fixture Records"] and t["releasetype"] == ["album", "live"]
        assert c.get("/api/art", params={"path": f"{FOLDER}/{name}"}).status_code == 200
    assert tags(c, "01.flac")["composer"] == ["Cam Composer"]
    assert c.art_calls == [f"https://coverartarchive.org/release/{REL}/front-1200"]  # fetched once for the album

    entry = c.get("/api/activity").json()[0]
    assert entry["kind"] == "musicbrainz" and "Fixture Album" in entry["message"] and entry["can_undo"]
    undo = c.post(f"/api/activity/{entry['id']}/undo").json()
    assert undo["undone"] == 3
    assert tags(c, "01.flac")["title"] == ["opening"] and "musicbrainz_albumid" not in tags(c, "01.flac")
    assert c.get("/api/art", params={"path": f"{FOLDER}/01.flac"}).status_code == 404


def test_apply_respects_fields_mode_pairs_and_cover(make_client):
    c = make_client(art=png())
    res = c.post("/api/musicbrainz/apply", json={
        "folder": FOLDER, "release": REL, "fields": ["title", "genre", "musicbrainz_trackid"], "mode": "fill",
        "cover": "none",
        "pairs": {f"{FOLDER}/03.m4a": None},
    }).json()
    assert res["updated"] == 2
    t1 = tags(c, "01.flac")
    assert t1["title"] == ["opening"]  # fill mode keeps the existing title
    assert t1["genre"] == ["Test"]  # ...and the existing genre
    assert t1["musicbrainz_trackid"] == ["aaaaaaaa-0000-4000-8000-000000000001"]  # was empty: filled
    assert "musicbrainz_albumid" not in t1  # not one of the chosen fields
    assert tags(c, "03.m4a")["title"] == ["Closing"]  # skipped file untouched
    assert c.art_calls == []


def test_cover_failure_still_writes_tags(make_client):
    c = make_client(art=ProviderError("Couldn't reach the Cover Art Archive."))
    res = c.post("/api/musicbrainz/apply", json={"folder": FOLDER, "release": REL}).json()
    assert res["updated"] == 3 and "Cover Art Archive" in res["cover_error"]
    assert tags(c, "01.flac")["title"] == ["Opening"]


def test_non_image_cover_is_never_used(make_client):
    c = make_client(art=b"<html><script>alert(1)</script></html>")
    assert c.get(f"/api/musicbrainz/cover/{REL}").status_code == 404
    res = c.post("/api/musicbrainz/apply", json={"folder": FOLDER, "release": REL}).json()
    assert res["cover_error"] and c.get("/api/art", params={"path": f"{FOLDER}/01.flac"}).status_code == 404


def test_cover_proxy(make_client):
    c = make_client(art=png())
    res = c.get(f"/api/musicbrainz/cover/{REL}", params={"size": "250"})  # as the page asks for it
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    assert c.get(f"/api/musicbrainz/cover/{REL}", params={"size": "9999"}).status_code == 422
    assert c.get("/api/musicbrainz/cover/not-an-id").status_code == 422
    c.get(f"/api/musicbrainz/cover/{REL}")
    assert len(c.art_calls) == 1  # thumbnails are cached


def test_service_errors_are_reported(make_client):
    c = make_client(FakeMB(error=ProviderError("MusicBrainz is busy right now. Try again in a moment.")))
    res = c.post("/api/musicbrainz/search", json={"folder": FOLDER})
    assert res.status_code == 502 and "busy" in res.json()["detail"]


def test_unknown_release_is_reported(make_client):
    c = make_client()
    res = c.post("/api/musicbrainz/preview", json={"folder": FOLDER, "release": OTHER})
    assert res.status_code == 502 and "doesn't have that release" in res.json()["detail"]


def test_paths_must_stay_in_the_library(make_client):
    c = make_client()
    res = c.post("/api/musicbrainz/preview", json={"paths": ["../../etc/passwd"], "release": REL})
    assert res.status_code in (400, 200)
    if res.status_code == 200:  # reported per file, never read
        assert res.json()["files"][0]["error"]
