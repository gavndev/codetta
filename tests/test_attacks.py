"""Attack tests: hit every endpoint the way an attacker would.

These are deliberately broad so that new endpoints are covered automatically:
the route list comes from the app itself.
"""

import os
import shutil

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

# Routes anyone may call without signing in.
PUBLIC = {("GET", "/"), ("GET", "/api/health"), ("GET", "/api/changelog"), ("GET", "/api/auth/status"),
          ("POST", "/api/auth/setup"), ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"),
          ("POST", "/api/auth/password")}  # checks the session itself (tested below)


@pytest.fixture
def env(tmp_path):
    music = tmp_path / "music"
    (music / "Album").mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.flac", music / "Album" / "song.flac")
    secret = tmp_path / "secret.flac"  # outside the library
    shutil.copy2(FIXTURES_DIR / "sample.flac", secret)
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": "correct horse 1"})
        yield {"client": c, "app": app, "music": music, "secret": secret, "tmp": tmp_path}


def all_routes(app):
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in r.methods:
                yield m, r.path


def fill(path):
    return path.replace("{entry_id}", "1").replace("{name}", "x")


# --- 1. Every non-public route refuses unsigned requests ------------------------------------


def test_every_private_route_requires_sign_in(env):
    c = env["client"]
    c.cookies.clear()
    checked = 0
    for method, path in all_routes(env["app"]):
        if (method, path) in PUBLIC:
            continue
        res = c.request(method, fill(path), params={"path": "Album/song.flac"})
        assert res.status_code == 401, f"{method} {path} answered {res.status_code} without sign-in"
        checked += 1
    assert checked >= 15  # sanity: the route list really was walked


def test_password_change_requires_a_session(env):
    c = env["client"]
    c.cookies.clear()
    res = c.post("/api/auth/password", json={"current_password": "correct horse 1", "new_password": "hijacked pw 9"})
    assert res.status_code == 401


def test_static_files_cannot_escape(env):
    c = env["client"]
    for p in ["/static/../app.py", "/static/..%2fapp.py", "/static/%2e%2e/%2e%2e/pyproject.toml", "/static//etc/passwd"]:
        res = c.get(p)
        assert res.status_code in (400, 404), p
        assert b"import" not in res.content and b"root:" not in res.content


# --- 2. No path parameter escapes the music folder -----------------------------------------------

TRAVERSALS = [
    "../secret.flac", "Album/../../secret.flac", "/etc/passwd", "..", "../",
    "Album/..\\..\\secret.flac", "Album%2F..%2F..%2Fsecret.flac", "....//secret.flac",
    "Album/song.flac\x00.txt", "~/secret.flac", "//etc/passwd",
]


@pytest.mark.parametrize("evil", TRAVERSALS)
def test_traversal_on_every_path_endpoint(env, evil):
    c = env["client"]
    before = env["secret"].read_bytes()
    probes = [
        c.get("/api/browse", params={"path": evil}),
        c.get("/api/track", params={"path": evil}),
        c.get("/api/art", params={"path": evil}),
        c.put("/api/art", params={"path": evil}, content=(FIXTURES_DIR / "cover.jpg").read_bytes(),
              headers={"Content-Type": "image/jpeg"}),
        c.delete("/api/art", params={"path": evil}),
        c.patch("/api/tracks", json={"paths": [evil], "changes": {"title": "pwned"}}),
        c.post("/api/presets/apply", json={"name": "Single", "paths": [evil], "dry_run": False}),
        c.post("/api/presets/apply", json={"name": "Single", "folder": evil, "dry_run": False}),
    ]
    for res in probes:
        assert res.status_code != 500, res.text
        body = res.text
        assert "Test Track" not in body or "secret" not in body  # never the outside file's tags
        if res.status_code == 200 and res.headers.get("content-type", "").startswith("application/json"):
            data = res.json()
            if isinstance(data, list):
                assert all(not item.get("ok", False) for item in data if "ok" in item), (evil, data)
    assert env["secret"].read_bytes() == before, f"file outside the library changed via {evil!r}"


def test_symlinked_folder_outside_library_is_followed_only_as_documented(env):
    # A symlink placed inside the library by its owner is followed (that's how
    # people link music on other disks), but nothing can create such links via the API.
    routes = {p for _, p in all_routes(env["app"])}
    assert not any("link" in p or "upload" in p for p in routes)
    # The only "file" routes are the right-click menu's: they move, rename and set files aside
    # inside the library (through the same mover as Organize), and can't create links or new files.
    # The download ones only read: one file as it is, or a selection zipped on the fly.
    assert {p for p in routes if "file" in p} == {"/api/files/move", "/api/files/rename", "/api/files/delete", "/api/files/info",
                                                  "/api/files/download", "/api/files/zip", "/api/files/zip/{token}"}


# --- 3. Malicious content stays inert --------------------------------------------------------------


def test_script_in_tags_is_stored_and_returned_as_plain_data(env):
    c = env["client"]
    xss = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    c.patch("/api/tracks", json={"paths": ["Album/song.flac"], "changes": {"title": xss, "artist": xss}})
    data = c.get("/api/track", params={"path": "Album/song.flac"}).json()
    assert data["tags"]["title"] == [xss]  # stored exactly; the UI only ever renders it as text
    page = c.get("/").text
    assert xss not in page  # never injected into HTML by the server


def test_ui_never_uses_html_sinks_for_data():
    static = FIXTURES_DIR.parent.parent / "src/codetta/web/static"
    js = "\n".join(p.read_text() for p in [static / "app.js", *sorted((static / "js").glob("*.js"))])
    # The only innerHTML use is for the app's own constant SVG icons.
    assert js.count("innerHTML") == 1 and "t.innerHTML = ICONS[name]" in js
    for sink in ("insertAdjacentHTML", "document.write", "eval(", "new Function", "outerHTML ="):
        assert sink not in js


def test_malicious_file_names_are_listed_safely(env):
    c = env["client"]
    weird = '"><img src=x onerror=alert(1)>.flac'
    shutil.copy2(FIXTURES_DIR / "sample.flac", env["music"] / "Album" / weird)
    data = c.get("/api/browse", params={"path": "Album"}).json()
    assert weird in [t["name"] for t in data["tracks"]]  # data, not markup


def test_oversized_tag_values_are_refused(env):
    c = env["client"]
    res = c.patch("/api/tracks", json={"paths": ["Album/song.flac"], "changes": {"comment": "x" * 100_001}})
    assert res.json()[0]["ok"] is False and "too long" in res.json()[0]["error"]
    res = c.patch("/api/tracks", json={"paths": ["Album/song.flac"], "changes": {"comment": "x" * 50_000}})
    assert res.json()[0]["ok"] is True  # long lyrics are fine


def test_repeated_paths_are_processed_once(env):
    # This exact request (one file listed thousands of times, with a big tag) used to
    # build a multi-gigabyte response.
    c = env["client"]
    res = c.patch("/api/tracks", json={"paths": ["Album/song.flac"] * 1000, "changes": {"comment": "y" * 50_000}})
    assert res.status_code == 200 and len(res.json()) == 1
    assert len(res.content) < 200_000


def test_too_many_paths_in_one_request_is_refused(env):
    c = env["client"]
    many = [f"Album/{i}.flac" for i in range(1001)]
    assert c.patch("/api/tracks", json={"paths": many, "changes": {"genre": "x"}}).status_code == 422
    assert c.delete("/api/art", params={"path": many[:1001]}).status_code in (422, 431)


def test_preset_names_cannot_write_outside_config(env):
    c = env["client"]
    for name in ["../../evil", "..\\evil", "/etc/evil", "evil/../../x"]:
        c.post("/api/presets", json={"name": name, "tags": {"genre": "x"}})
    presets_dir = env["tmp"] / "config" / "presets"
    for f in env["tmp"].rglob("*.json"):
        assert f.parent in (presets_dir, env["tmp"] / "config"), f"preset written outside config: {f}"


def test_undo_cannot_be_pointed_at_other_files(env):
    c = env["client"]
    # Undo only replays records the server itself wrote; ids are integers only.
    for bad in ["../../etc", "1;rm -rf /", "-1", "99999999999999999999999"]:
        res = c.post(f"/api/activity/{bad}/undo")
        assert res.status_code in (404, 422)


# --- 4. A fresh install can't be claimed from the internet --------------------------------------


@pytest.mark.parametrize(("ip", "public"), [
    ("8.8.8.8", True), ("2001:4860:4860::8888", True), ("::ffff:8.8.8.8", True),
    ("192.168.1.20", False), ("10.0.0.5", False), ("172.16.3.4", False),
    ("100.101.0.1", False), ("fd7a:115c:a1e0::1", False),  # Tailscale
    ("127.0.0.1", False), ("::1", False), ("testclient", False),
])
def test_public_address_detection(ip, public):
    from codetta.web.app import _is_public_address
    assert _is_public_address(ip) is public


def test_setup_refused_from_the_internet(tmp_path, monkeypatch):
    import codetta.web.app as webapp
    monkeypatch.setattr(webapp, "_is_public_address", lambda host: True)  # pretend the visitor is on the internet
    (tmp_path / "music").mkdir()
    with TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config"))) as c:
        res = c.post("/api/auth/setup", json={"username": "intruder", "password": "taking over now"})
        assert res.status_code == 403 and "home network" in res.json()["detail"]
        assert c.get("/api/auth/status").json()["setup_required"] is True
    with TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config2",
                                        allow_public_setup=True))) as c:
        assert c.post("/api/auth/setup", json={"username": "owner", "password": "correct horse 1"}).status_code == 200
