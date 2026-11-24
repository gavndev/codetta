"""Music apps: the Subsonic / OpenSubsonic API at /rest/."""

import hashlib
import time
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from codetta.core.subsonic import Catalog, check_login, make_id, read_id, to_xml, SubsonicError
from codetta.web.app import Settings, create_app
from tests.test_musicbrainz import PASSWORD, album_dir  # noqa: F401 (fixture)


@pytest.fixture
def client(album_dir, tmp_path):  # noqa: F811
    app = create_app(Settings(music_dir=album_dir, config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        for _ in range(200):  # the index scans in the background
            if c.get("/api/search", params={"q": "opening"}).json().get("tracks"):
                break
            time.sleep(0.05)
        yield c


def turn_on(c):
    return c.put("/api/subsonic", json={"enabled": True}).json()["password"]


def call(cl, method, pw, **extra):
    salt = "abc123"
    params = {"u": "owner", "t": hashlib.md5((pw + salt).encode()).hexdigest(), "s": salt, "v": "1.16.1",
              "c": "test", "f": "json", **extra}
    r = cl.get(f"/rest/{method}", params=params)
    return r, (r.json()["subsonic-response"] if r.headers["content-type"].startswith("application/json") else None)


def test_off_until_switched_on_and_never_opens_codettas_own_api(client):
    r = client.get("/rest/ping", params={"u": "owner", "p": "x", "f": "json"})
    body = r.json()["subsonic-response"]
    assert body["status"] == "failed" and body["error"]["code"] == 50
    anonymous = TestClient(client.app)
    assert anonymous.get("/api/subsonic").status_code == 401  # the settings need Codetta's sign-in
    assert anonymous.get("/api/browse", params={"path": ""}).status_code == 401
    assert client.get("/api/subsonic").json()["password"] == ""  # off: nothing to show


def test_signing_in_every_way(client):
    pw = turn_on(client)
    assert pw and len(pw) >= 20
    r, body = call(client, "ping", pw)
    assert body["status"] == "ok" and body["openSubsonic"] is True and body["type"] == "codetta"
    ok = lambda **p: client.get("/rest/ping.view", params={"f": "json", **p}).json()["subsonic-response"]  # noqa: E731
    assert ok(u="owner", p=pw)["status"] == "ok"
    assert ok(u="Owner", p="enc:" + pw.encode().hex())["status"] == "ok"
    assert ok(apiKey=pw)["status"] == "ok"
    assert ok(apiKey=pw, u="owner")["error"]["code"] == 43
    assert ok(apiKey="nope")["error"]["code"] == 44
    assert ok(u="owner", p="wrong")["error"]["code"] == 40
    assert ok(u="someone-else", p=pw)["error"]["code"] == 40
    assert ok(u="owner", p=PASSWORD)["error"]["code"] == 40  # the account password never works here


def test_a_new_app_password_signs_every_app_out(client):
    pw = turn_on(client)
    new = client.post("/api/subsonic/password").json()["password"]
    ok = lambda p: client.get("/rest/ping", params={"f": "json", "u": "owner", "p": p}).json()["subsonic-response"]  # noqa: E731
    assert new != pw and ok(new)["status"] == "ok" and ok(pw)["error"]["code"] == 40


def test_too_many_wrong_passwords_lock_out_for_a_while(client):
    pw = turn_on(client)
    for _ in range(8):
        client.get("/rest/ping", params={"u": "owner", "p": "wrong", "f": "json"})
    body = client.get("/rest/ping", params={"u": "owner", "p": pw, "f": "json"}).json()["subsonic-response"]
    assert body["status"] == "failed" and "Too many" in body["error"]["message"]


def test_xml_is_the_default(client):
    pw = turn_on(client)
    r = client.get("/rest/ping", params={"u": "owner", "p": pw})
    root = ET.fromstring(r.content)
    assert root.tag == "{http://subsonic.org/restapi}subsonic-response" and root.get("status") == "ok"
    assert root.get("openSubsonic") == "true"


def test_browsing_searching_and_streaming(client):
    pw = turn_on(client)
    _, body = call(client, "getArtists", pw)
    artists = [a for idx in body["artists"]["index"] for a in idx["artist"]]
    assert len(artists) == 1 and artists[0]["albumCount"] == 1
    _, body = call(client, "getArtist", pw, id=artists[0]["id"])
    album = body["artist"]["album"][0]
    _, body = call(client, "getAlbum", pw, id=album["id"])
    songs = body["album"]["song"]
    assert [s["title"] for s in songs] == ["opening", "Middle", "Closing"]  # in track order
    assert {s["suffix"] for s in songs} == {"flac", "mp3", "m4a"} and songs[0]["contentType"] == "audio/flac"
    _, body = call(client, "search3", pw, query="")  # what apps that sync the whole library send
    assert len(body["searchResult3"]["song"]) == 3
    _, body = call(client, "search3", pw, query="midd")
    assert [s["title"] for s in body["searchResult3"]["song"]] == ["Middle"]
    _, body = call(client, "getAlbumList2", pw, type="newest", size=5)
    assert body["albumList2"]["album"][0]["id"] == album["id"]
    _, body = call(client, "getIndexes", pw)
    folder = body["indexes"]["index"][0]["artist"][0]
    _, body = call(client, "getMusicDirectory", pw, id=folder["id"])
    sub = body["directory"]["child"][0]
    _, body = call(client, "getMusicDirectory", pw, id=sub["id"])
    assert len(body["directory"]["child"]) == 3
    # Streaming, with seeking
    r, _ = call(client, "stream", pw, id=songs[0]["id"])
    assert r.status_code == 200 and r.headers["content-type"] == "audio/flac" and r.content[:4] == b"fLaC"
    params = {"u": "owner", "p": pw, "id": songs[0]["id"]}
    part = client.get("/rest/stream", params=params, headers={"Range": "bytes=0-3"})
    assert part.status_code == 206 and part.content == b"fLaC"
    assert r.headers["access-control-allow-origin"] == "*"
    # Covers answer with an image or a "not found" error, never a crash
    r, body = call(client, "getCoverArt", pw, id=album["id"])
    assert r.status_code == 200 and (r.headers["content-type"].startswith("image/") or body["error"]["code"] == 70)


def test_ids_and_bad_ids(client):
    pw = turn_on(client)
    _, body = call(client, "getSong", pw, id=make_id("s", "../../etc/passwd"))
    assert body["error"]["code"] == 70
    _, body = call(client, "stream", pw, id="garbage")
    assert body["error"]["code"] == 70
    _, body = call(client, "getMusicDirectory", pw, id=make_id("d", "@deleted"))
    assert body["error"]["code"] == 70
    _, body = call(client, "getAlbum", pw)
    assert body["error"]["code"] == 10
    assert read_id(make_id("s", "Björk/Vespertine/01 – It's Not Up to You.flac")) == ("s", "Björk/Vespertine/01 – It's Not Up to You.flac")


def test_accepted_but_not_kept(client):
    pw = turn_on(client)
    for method in ("scrobble", "star", "unstar", "getStarred2", "getPlaylists", "getUser", "getLicense", "getGenres",
                   "getOpenSubsonicExtensions", "getMusicFolders", "getScanStatus", "getRandomSongs", "getNowPlaying"):
        _, body = call(client, method, pw, id="s-x")
        assert body["status"] == "ok", (method, body)
    _, body = call(client, "nosuchMethod", pw)
    assert body["error"]["code"] == 70


def test_catalog_groups_albums_by_tags_and_folders():
    rows = [("A/Alb/01.flac", 10, 1_700_000_000_000_000_000, {"tags": {"title": ["One"], "album": ["Alb"], "albumartist": ["A"],
                                                                       "tracknumber": ["2"]}, "format": "flac"}),
            ("A/Alb/CD2/01.flac", 10, 1, {"tags": {"title": ["Two"], "album": ["Alb"], "albumartist": ["A"], "discnumber": ["2"],
                                                   "tracknumber": ["1"]}}),
            ("A/Alb/00.flac", 10, 1, {"tags": {"title": ["Zero"], "album": ["Alb"], "albumartist": ["A"], "tracknumber": ["1"]}}),
            ("Loose/x.mp3", 10, 1, {"tags": {"title": ["X"]}}),
            ("Broken.flac", 10, 1, {"tags": {}, "error": "unreadable"})]
    cat = Catalog(rows)
    albums = {a.name: a for a in cat.albums.values()}
    assert set(albums) == {"Alb", "Loose"}  # multi-disc folders are one album; untagged files group by folder
    assert [cat.songs[s].path for s in albums["Alb"].songs] == ["A/Alb/00.flac", "A/Alb/01.flac", "A/Alb/CD2/01.flac"]
    assert len(cat.songs) == 4


def test_login_rules_and_xml_escaping():
    with pytest.raises(SubsonicError):
        check_login({"u": "a", "p": "x"}, "a", "")  # no app password yet: nothing gets in
    xml = to_xml({"status": "ok", "song": [{"title": 'A & "B" <C>'}]})
    assert ET.fromstring(xml).find("{http://subsonic.org/restapi}song").get("title") == 'A & "B" <C>'


# --- 0.13: the full integration ------------------------------------------------------------------

def j(cl, method, pw, **extra):
    return call(cl, method, pw, **extra)[1]


def first_song_ids(c, pw):
    artist = j(c, "getArtists", pw)["artists"]["index"][0]["artist"][0]
    album = j(c, "getArtist", pw, id=artist["id"])["artist"]["album"][0]
    songs = j(c, "getAlbum", pw, id=album["id"])["album"]["song"]
    return artist["id"], album["id"], [s["id"] for s in songs]


def test_form_posts_work(client):
    pw = turn_on(client)
    r = client.post("/rest/ping.view", data={"u": "owner", "p": pw, "f": "json"})
    assert r.status_code == 200 and r.json()["subsonic-response"]["status"] == "ok"


def test_going_up_from_a_top_level_folder(client):
    pw = turn_on(client)
    top = j(client, "getIndexes", pw)["indexes"]["index"][0]["artist"][0]
    d = j(client, "getMusicDirectory", pw, id=top["id"])["directory"]
    root = j(client, "getMusicDirectory", pw, id=d["parent"])
    assert root["status"] == "ok" and "parent" not in root["directory"]
    assert any(x["id"] == top["id"] for x in root["directory"]["child"])


def test_stars_ratings_and_plays_are_kept(client):
    pw = turn_on(client)
    artist, album, songs = first_song_ids(client, pw)
    params = [("u", "owner"), ("p", pw), ("f", "json"), ("id", songs[0]), ("id", songs[1]), ("albumId", album), ("artistId", artist)]
    assert client.get("/rest/star", params=params).json()["subsonic-response"]["status"] == "ok"
    starred = j(client, "getStarred2", pw)["starred2"]
    assert {s["id"] for s in starred["song"]} == {songs[0], songs[1]}
    assert starred["album"][0]["id"] == album and starred["artist"][0]["id"] == artist
    j(client, "unstar", pw, id=songs[1])
    assert [s["id"] for s in j(client, "getStarred2", pw)["starred2"]["song"]] == [songs[0]]
    j(client, "setRating", pw, id=songs[0], rating=5)
    for _ in range(2):
        j(client, "scrobble", pw, id=songs[0], submission="true")
    song = j(client, "getSong", pw, id=songs[0])["song"]
    assert song["starred"] and song["userRating"] == 5 and song["playCount"] == 2 and song["played"]
    assert j(client, "getAlbumList2", pw, type="frequent")["albumList2"]["album"][0]["id"] == album
    assert j(client, "getAlbumList2", pw, type="recent")["albumList2"]["album"][0]["id"] == album
    j(client, "scrobble", pw, id=songs[2], submission="false", c="Symfonium")
    now = j(client, "getNowPlaying", pw)["nowPlaying"]["entry"]
    assert now[0]["id"] == songs[2] and now[0]["playerName"] == "Symfonium"
    top = j(client, "getTopSongs", pw, artist=song["artist"])["topSongs"]["song"]
    assert top[0]["id"] == songs[0]


def test_playlists(client):
    pw = turn_on(client)
    _, _, songs = first_song_ids(client, pw)
    params = [("u", "owner"), ("p", pw), ("f", "json"), ("name", "Road trip"), ("songId", songs[2]), ("songId", songs[0])]
    pl = client.get("/rest/createPlaylist", params=params).json()["subsonic-response"]["playlist"]
    assert pl["name"] == "Road trip" and [e["id"] for e in pl["entry"]] == [songs[2], songs[0]] and pl["songCount"] == 2
    upd = [("u", "owner"), ("p", pw), ("f", "json"), ("playlistId", pl["id"]), ("name", "Trip"), ("songIdToAdd", songs[1]),
           ("songIndexToRemove", "0")]
    client.get("/rest/updatePlaylist", params=upd)
    got = j(client, "getPlaylist", pw, id=pl["id"])["playlist"]
    assert got["name"] == "Trip" and [e["id"] for e in got["entry"]] == [songs[0], songs[1]]
    assert [p["name"] for p in j(client, "getPlaylists", pw)["playlists"]["playlist"]] == ["Trip"]
    j(client, "deletePlaylist", pw, id=pl["id"])
    assert j(client, "getPlaylist", pw, id=pl["id"])["error"]["code"] == 70


def test_play_queue_and_bookmarks(client):
    pw = turn_on(client)
    _, _, songs = first_song_ids(client, pw)
    q = [("u", "owner"), ("p", pw), ("f", "json"), ("id", songs[0]), ("id", songs[1]), ("current", songs[1]), ("position", "4200"),
         ("c", "Narjo")]
    client.get("/rest/savePlayQueue", params=q)
    queue = j(client, "getPlayQueue", pw)["playQueue"]
    assert [e["id"] for e in queue["entry"]] == [songs[0], songs[1]] and queue["current"] == songs[1]
    assert queue["position"] == 4200 and queue["changedBy"] == "Narjo"
    assert j(client, "getPlayQueueByIndex", pw)["playQueueByIndex"]["currentIndex"] == 1
    qi = [("u", "owner"), ("p", pw), ("f", "json"), ("id", songs[2]), ("currentIndex", "0")]
    client.get("/rest/savePlayQueueByIndex", params=qi)
    assert j(client, "getPlayQueue", pw)["playQueue"]["current"] == songs[2]
    j(client, "createBookmark", pw, id=songs[0], position=90000, comment="chapter 2")
    bm = j(client, "getBookmarks", pw)["bookmarks"]["bookmark"]
    assert bm[0]["position"] == 90000 and bm[0]["entry"]["id"] == songs[0]
    j(client, "deleteBookmark", pw, id=songs[0])
    assert j(client, "getBookmarks", pw)["bookmarks"]["bookmark"] == []


def test_stars_follow_a_renamed_file(client):
    pw = turn_on(client)
    _, _, songs = first_song_ids(client, pw)
    path = j(client, "getSong", pw, id=songs[0])["song"]["path"]
    j(client, "star", pw, id=songs[0])
    r = client.post("/api/files/rename", json={"path": path, "name": "Renamed"})
    assert r.status_code == 200, r.text
    for _ in range(200):
        starred = j(client, "getStarred2", pw)["starred2"].get("song", [])
        if starred and starred[0]["path"] != path:
            break
        time.sleep(0.05)
    assert starred and starred[0]["path"].endswith("Renamed.flac")


def test_rich_details_and_extensions(client, album_dir):  # noqa: F811
    from mutagen.flac import FLAC
    f = FLAC(album_dir / "Coda Tester" / "Fixture Album" / "01.flac")
    f["replaygain_track_gain"] = "-7.50 dB"
    f["replaygain_track_peak"] = "0.988"
    f["musicbrainz_trackid"] = "11111111-2222-4333-8444-555555555555"
    f["genre"] = ["Neo Soul", "R&B"]
    f.save()
    pw = turn_on(client)
    j(client, "startScan", pw)  # the file changed behind Codetta's back, as apps would ask
    for _ in range(200):
        _, _, songs = first_song_ids(client, pw)
        song = j(client, "getSong", pw, id=songs[0])["song"]
        if song.get("replayGain"):
            break
        time.sleep(0.05)
    assert song["replayGain"] == {"trackGain": -7.5, "trackPeak": 0.988}
    assert song["musicBrainzId"] == "11111111-2222-4333-8444-555555555555"
    assert [g["name"] for g in song["genres"]] == ["Neo Soul", "R&B"] and song["artists"][0]["name"]
    names = {e["name"] for e in j(client, "getOpenSubsonicExtensions", pw)["openSubsonicExtensions"]}
    assert {"transcodeOffset", "indexBasedQueue", "formPost", "apiKeyAuthentication", "songLyrics"} <= names


def test_cover_sizes(client, album_dir):  # noqa: F811
    import io

    from mutagen.flac import FLAC, Picture
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (1000, 1000), (10, 120, 200)).save(out, "JPEG")
    for name in ("01.flac",):
        f = FLAC(album_dir / "Coda Tester" / "Fixture Album" / name)
        pic = Picture()
        pic.type, pic.mime, pic.data = 3, "image/jpeg", out.getvalue()
        f.clear_pictures()
        f.add_picture(pic)
        f.save()
    pw = turn_on(client)
    j(client, "startScan", pw)
    for _ in range(200):
        _, album, _ = first_song_ids(client, pw)
        r, _ = call(client, "getCoverArt", pw, id=album, size=150)
        if r.headers["content-type"].startswith("image/"):
            break
        time.sleep(0.05)
    assert Image.open(io.BytesIO(r.content)).size == (150, 150)
    r, _ = call(client, "getCoverArt", pw, id=album)
    assert Image.open(io.BytesIO(r.content)).size == (1000, 1000)


def test_streaming_raw_and_converted(client):
    import shutil as sh

    from codetta.core.transcode import Transcoder
    pw = turn_on(client)
    _, _, songs = first_song_ids(client, pw)
    r, _ = call(client, "stream", pw, id=songs[0], format="raw", maxBitRate=64)
    assert r.headers["content-type"] == "audio/flac" and r.content[:4] == b"fLaC"
    ffmpeg = sh.which("ffmpeg")
    if not ffmpeg or "mp3" not in Transcoder(ffmpeg).formats():
        pytest.skip("no ffmpeg with an MP3 encoder here")
    r, _ = call(client, "stream", pw, id=songs[0], format="mp3", maxBitRate=128)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and len(r.content) > 100
    client.put("/api/subsonic", json={"enabled": True, "transcode": False})
    r, _ = call(client, "stream", pw, id=songs[0], format="mp3", maxBitRate=128)
    assert r.headers["content-type"] == "audio/flac"  # conversion switched off: the original


def test_artist_info_and_settings_card(client):
    pw = turn_on(client)
    artist, _, _ = first_song_ids(client, pw)
    info = j(client, "getArtistInfo2", pw, id=artist)["artistInfo2"]
    url = info["largeImageUrl"]
    assert url.startswith("http") and "getCoverArt" in url and "sig=" in url
    assert "t=" not in url and "p=" not in url and pw not in url  # never the app's sign-in
    from urllib.parse import parse_qs, urlsplit
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    anon = client.get("/rest/getCoverArt", params=q)  # opens without signing in...
    assert anon.status_code == 200
    body = client.get("/rest/getCoverArt", params={**q, "id": artist + "x"})
    assert "error" in body.text  # ...but only that picture
    body = client.get("/rest/getAlbumList2", params={"sig": q["sig"], "f": "json"}).json()["subsonic-response"]
    assert body["status"] == "failed"  # and nothing else
    https = client.get("/rest/getArtistInfo2", params={"u": "owner", "p": pw, "f": "json", "id": artist},
                       headers={"X-Forwarded-Proto": "https"}).json()["subsonic-response"]["artistInfo2"]
    assert https["largeImageUrl"].startswith("https://")
    j(client, "ping", pw, c="Symfonium")
    card = client.get("/api/subsonic").json()
    assert card["transcode"] is True and card["format"] == "mp3"
    assert {x["name"] for x in card["clients"]} == {"Symfonium", "test"}  # the tests' own client says "test"


def test_removing_from_a_playlist_with_a_song_missing_from_the_library(client):
    pw = turn_on(client)
    _, _, songs = first_song_ids(client, pw)
    paths = [j(client, "getSong", pw, id=s)["song"]["path"] for s in songs]
    params = [("u", "owner"), ("p", pw), ("f", "json"), ("name", "Mix")] + [("songId", s) for s in songs]
    pl = client.get("/rest/createPlaylist", params=params).json()["subsonic-response"]["playlist"]
    assert client.post("/api/files/delete", json={"paths": [paths[1]]}).status_code == 200  # the middle song
    for _ in range(200):  # the app's view of the library catches up
        shown = j(client, "getPlaylist", pw, id=pl["id"])["playlist"].get("entry", [])
        if len(shown) == 2:
            break
        time.sleep(0.05)
    assert [e["id"] for e in shown] == [songs[0], songs[2]]
    # The app removes what it shows at index 1: the third song, not the hidden deleted one.
    client.get("/rest/updatePlaylist", params=[("u", "owner"), ("p", pw), ("f", "json"),
                                               ("playlistId", pl["id"]), ("songIndexToRemove", "1")])
    assert [e["id"] for e in j(client, "getPlaylist", pw, id=pl["id"])["playlist"]["entry"]] == [songs[0]]


def test_one_odd_track_number_never_freezes_the_library():
    from codetta.core.subsonic import Catalog, CatalogCache
    cat = Catalog([("A/1.flac", 1, 1, {"tags": {"title": ["X"], "tracknumber": ["①"], "date": ["²⁰²⁰"]}})])
    assert len(cat.songs) == 1
    calls = {"n": 0}

    def rows():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return [("A/1.flac", 1, calls["n"], {"tags": {"title": ["X"]}})]

    sig = {"v": 1}
    cache = CatalogCache(rows, lambda: sig["v"], every=0)
    assert cache.get()  # first build
    sig["v"] = 2
    cache.get()  # second build fails in the background
    for _ in range(100):
        if not cache._building:
            break
        time.sleep(0.01)
    assert not cache._building  # not stuck: the next change is picked up
    sig["v"] = 3
    cache.get()
    for _ in range(100):
        if cache._sig == 3:
            break
        time.sleep(0.01)
    assert cache._sig == 3
