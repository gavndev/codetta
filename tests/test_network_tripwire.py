"""Connections off means nothing leaves the server: every route is called with real-looking requests
while a tripwire records any attempt to open a URL. Then offline mode is checked the same way."""

import urllib.request

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from codetta.core.connections import CONNECTIONS
from codetta.web.app import Settings, create_app
from tests.test_musicbrainz import PASSWORD, album_dir  # noqa: F401 (fixture)

FOLDER = "Coda Tester/Fixture Album"
TRACK = f"{FOLDER}/01.flac"

# Requests that would go online if their connection were on (and the settings that point at servers).
CALLS = [
    ("PUT", "/api/slskd/settings", {"url": "https://slskd.example", "api_key": "k" * 20}),
    ("PUT", "/api/lidarr/settings", {"url": "https://lidarr.example", "api_key": "k" * 32}),
    ("PUT", "/api/mediaserver/settings", {"kind": "jellyfin", "url": "https://jf.example", "token": "t" * 32}),
    ("PUT", "/api/discogs", {"token": "d" * 40}),
    ("PUT", "/api/audiomuse", {"url": "https://audiomuse.example", "token": "a" * 32}),
    ("POST", "/api/audiomuse/test", {}),
    ("POST", "/api/autoplay/next", {"seeds": [TRACK], "n": 5}),
    ("GET", "/api/artists/picture?name=Coda+Tester", None),
    ("GET", "/api/artists/info?folder=Coda+Tester", None),
    ("GET", f"/api/albums/like?folder={FOLDER}", None),
    ("GET", f"/api/albums/elsewhere?folder={FOLDER}", None),
    ("POST", "/api/harmony", {"folder": FOLDER}),
    ("PUT", "/api/listenbrainz", {"token": "l" * 36}),
    ("POST", "/api/listenbrainz/test", {}),
    ("POST", "/api/played", {"path": TRACK}),
    ("POST", "/api/musicbrainz/search", {"folder": FOLDER}),
    ("POST", "/api/musicbrainz/search", {"folder": FOLDER, "source": "deezer"}),
    ("POST", "/api/musicbrainz/search", {"folder": FOLDER, "source": "itunes"}),
    ("POST", "/api/musicbrainz/search", {"folder": FOLDER, "source": "discogs"}),
    ("POST", "/api/musicbrainz/search", {"folder": FOLDER, "release": "https://www.discogs.com/release/1-x"}),
    ("POST", "/api/musicbrainz/preview", {"folder": FOLDER, "release": "deezer:302127"}),
    ("POST", "/api/musicbrainz/apply", {"folder": FOLDER, "release": "itunes:1440857781"}),
    ("POST", "/api/musicbrainz/identify", {"folder": FOLDER}),
    ("GET", "/api/musicbrainz/cover/discogs:1?size=250", None),
    ("GET", "/api/musicbrainz/cover/deezer:302127?size=250", None),
    ("GET", "/api/musicbrainz/editions", None),
    ("GET", "/api/musicbrainz/covers/11111111-1111-4111-8111-111111111111", None),
    ("GET", "/api/mb/search?q=bjork", None),
    ("GET", "/api/catalog/search?source=deezer&q=in+rainbows", None),
    ("GET", "/api/catalog/search?source=itunes&q=rumours", None),
    ("GET", "/api/catalog/search?source=discogs&q=ok+computer", None),
    ("GET", f"/api/lyrics/lookup?path={TRACK}", None),
    ("POST", "/api/slskd/search", {"query": "some album"}),
    ("POST", "/api/slskd/test", {}),
    ("POST", "/api/lidarr/test", {}),
    ("POST", "/api/mediaserver/test", {}),
    ("POST", "/api/mediaserver/scan", {}),
    ("POST", "/api/discogs/test", {}),
    ("GET", "/api/update", None),
    ("POST", "/api/folder-covers", {"folder": FOLDER}),
    ("POST", "/api/tags", {"paths": [TRACK], "tags": {"comment": "tripwire"}}),  # a change: hooks would fire
    ("POST", "/api/library-care/rerun", {}),
    ("GET", "/api/library-care/preview", None),
]


@pytest.fixture
def tripwire(monkeypatch):
    opened = []

    def refuse(self, req, *a, **k):
        opened.append(req.full_url if hasattr(req, "full_url") else str(req))
        raise OSError("tripwire: no network in this test")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)
    return opened


def sweep(c: TestClient, app) -> None:
    for method, url, body in CALLS:
        c.request(method, url, json=body)
    # And every other route, with empty input (most refuse it; none may reach out).
    for r in app.routes:
        if not isinstance(r, APIRoute) or "{" in r.path or r.path.startswith("/api/auth"):
            continue
        for m in r.methods - {"HEAD"}:
            if m == "DELETE":
                continue
            c.request(m, r.path, json={} if m != "GET" else None)


@pytest.mark.parametrize("offline", [False, True])
def test_nothing_leaves_while_connections_are_off(album_dir, tmp_path, tripwire, offline):  # noqa: F811
    app = create_app(Settings(music_dir=album_dir, config_dir=tmp_path / "config", offline=offline))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        if offline:  # every switch "on" in the file: offline mode must still win
            c.put("/api/connections", json={"enabled": {x.id: True for x in CONNECTIONS}})
        else:
            c.put("/api/connections", json={"enabled": {x.id: False for x in CONNECTIONS}})
        sweep(c, app)
    assert tripwire == []


SECRETS = {"slskd": "SLSKDKEY" + "s" * 24, "lidarr": "LIDARRKEY" + "l" * 23, "jfpass": "JFPASS" + "p" * 20,
           "jftoken": "JFTOKEN" + "t" * 25, "discogs": "DISCOGSTOKEN" + "d" * 28,
           "audiomuse": "AUDIOMUSETOKEN" + "a" * 26, "listenbrainz": "LISTENBRAINZTOKEN" + "b" * 23}


def test_saved_secrets_never_come_back(album_dir, tmp_path, tripwire):  # noqa: F811
    """Keys, passwords and tokens are kept on the server: no page request, report or log shows them,
    even when the servers they belong to can't be reached."""
    app = create_app(Settings(music_dir=album_dir, config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        c.put("/api/connections", json={"enabled": {x.id: True for x in CONNECTIONS}})
        c.put("/api/slskd/settings", json={"url": "https://slskd.example", "api_key": SECRETS["slskd"]})
        c.put("/api/lidarr/settings", json={"url": "https://lidarr.example", "api_key": SECRETS["lidarr"]})
        c.put("/api/mediaserver/settings", json={"kind": "subsonic", "url": "https://nd.example", "username": "me",
                                                  "password": SECRETS["jfpass"]})
        c.put("/api/mediaserver/settings", json={"kind": "jellyfin", "url": "https://jf.example", "token": SECRETS["jftoken"]})
        seen = []
        c.put("/api/discogs", json={"token": SECRETS["discogs"]})  # refused by the tripwire: not kept
        seen.append(c.put("/api/audiomuse", json={"url": "https://am.example", "token": SECRETS["audiomuse"]}).text)
        seen.append(c.put("/api/listenbrainz", json={"token": SECRETS["listenbrainz"]}).text)
        for r in app.routes:
            if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path:
                seen.append(c.get(r.path).text)
        seen.append(c.post("/api/slskd/test").text)
        seen.append(c.post("/api/lidarr/test").text)
        seen.append(c.post("/api/mediaserver/test").text)
        seen.append(c.post("/api/audiomuse/test").text)
        seen.append(c.post("/api/autoplay/next", json={"seeds": [], "n": 3}).text)
    found = [name for name, secret in SECRETS.items() if any(secret in text for text in seen)]
    assert found == []
