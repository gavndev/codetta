"""Privacy guarantees (PRIVACY.md), checked: Codetta never tracks you, the page loads nothing
from other sites, and nothing leaves the server unless you turned a connection on."""

import re
import shutil
import socket
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

STATIC = Path(__file__).parent.parent / "src" / "codetta" / "web" / "static"
# The usual analytics / crash-reporting services, by the domains and calls they're loaded with.
TRACKERS = re.compile(r"google-analytics\.com|googletagmanager\.com|\bgtag\(|plausible\.io|matomo\.(js|php)|"
                      r"umami\.(is|js)|segment\.(io|com)|mixpanel\.com|amplitude\.com|hotjar\.com|sentry\.io|"
                      r"sentry_sdk|posthog\.com|clarity\.ms|connect\.facebook\.net|doubleclick\.net", re.I)


def test_no_tracking_code_anywhere():
    for f in list((Path(__file__).parent.parent / "src" / "codetta").rglob("*.py")) + list(STATIC.glob("*.*")):
        if f.suffix in (".py", ".js", ".html", ".css"):
            assert not TRACKERS.search(f.read_text("utf-8", errors="ignore")), f"tracking code in {f}"


def test_page_loads_nothing_from_other_sites():
    html = (STATIC / "index.html").read_text("utf-8")
    css = (STATIC / "app.css").read_text("utf-8")
    js = (STATIC / "app.js").read_text("utf-8")
    # Scripts, styles, fonts and images: only from Codetta itself.
    assert not re.search(r'<(script|link|img|iframe)[^>]+(src|href)="(https?:)?//', html)
    assert not re.search(r'url\(\s*["\']?(https?:)?//', css) and "@import" not in css
    assert not re.search(r'fetch\(\s*["\'`]https?://', js)
    assert not re.search(r'new (WebSocket|EventSource)\(\s*["\'`]wss?://', js)


@pytest.fixture
def offline_app(tmp_path, monkeypatch):
    """A Codetta with every connection off, where any attempt to reach the network fails the test."""
    music = tmp_path / "music" / "Album"
    music.mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.flac", music / "01.flac")
    calls = []

    def blocked(*a, **k):
        calls.append(a)
        raise AssertionError(f"tried to reach the network: {a[:1]}")
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blocked)
    real_connect = socket.socket.connect

    def connect(self, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost", "testserver"):
            blocked(address)
        return real_connect(self, address)
    monkeypatch.setattr(socket.socket, "connect", connect)
    app = create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config", auth=False))
    with TestClient(app) as c:
        yield c, calls


def test_nothing_leaves_the_server_while_connections_are_off(offline_app):
    c, calls = offline_app
    assert c.get("/api/connections").json()["offline"] is True
    for method, url, body in [
        ("GET", "/api/browse?path=Album", None), ("GET", "/api/search?q=sample", None),
        ("GET", "/api/library-health", None), ("GET", "/api/update", None), ("GET", "/api/update?force=true", None),
        ("POST", "/api/organize/preview", {"folder": "Album"}), ("GET", "/api/lyrics?path=Album/01.flac", None),
    ]:
        assert c.request(method, url, json=body).status_code < 500, url
    # Online features say they're off instead of quietly reaching out.
    assert c.get("/api/lyrics/lookup?path=Album/01.flac").status_code == 403
    assert c.post("/api/musicbrainz/search", json={"folder": "Album"}).status_code == 403
    assert c.get("/api/mb/search?q=kehlani").status_code == 403
    assert c.post("/api/slskd/search", json={"query": "kehlani"}).status_code in (403, 409)
    assert calls == []


def test_offline_switch_blocks_everything(tmp_path):
    app = create_app(Settings(music_dir=tmp_path, config_dir=tmp_path / "c", auth=False, offline=True))
    with TestClient(app) as c:
        r = c.put("/api/connections", json={"enabled": {"musicbrainz": True, "lyrics": True, "updates": True}}).json()
        assert all(not x["enabled"] for x in r["connections"]) and r["offline_locked"]


def test_sessions_keep_nothing_about_the_device(tmp_path):
    import json
    app = create_app(Settings(music_dir=tmp_path, config_dir=tmp_path / "c"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "me", "password": "correct horse 1"}, headers={"User-Agent": "Secret Browser 9"})
    stored = (tmp_path / "c" / "sessions.json").read_text()
    assert "Secret Browser" not in stored and "testclient" not in stored and "127.0.0.1" not in stored
    for s in json.loads(stored).values():
        assert set(s) <= {"username", "created", "expires"}
