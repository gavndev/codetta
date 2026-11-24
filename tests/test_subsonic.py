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


def call(c, method, pw, **extra):
    salt = "abc123"
    params = {"u": "owner", "t": hashlib.md5((pw + salt).encode()).hexdigest(), "s": salt, "v": "1.16.1",
              "c": "test", "f": "json", **extra}
    r = c.get(f"/rest/{method}", params=params)
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
