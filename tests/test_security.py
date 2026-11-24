"""Security tests: each one guards against a specific attack."""

import shutil

import pytest
from fastapi.testclient import TestClient
from mutagen.flac import FLAC, Picture

from codetta.core.auth import AccountStore, LoginRateLimiter, hash_password, needs_rehash
from codetta.core.updates import UpdateChecker
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    shutil.copy2(FIXTURES_DIR / "sample.flac", root / "song.flac")
    return root


def make_client(music, tmp_path, **kw):
    return TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config", **kw)))


@pytest.fixture
def client(music, tmp_path):
    with make_client(music, tmp_path) as c:
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        yield c


# --- 1. A booby-trapped "cover" can't run scripts ----------------------------------------


def test_cover_claiming_to_be_html_is_downloaded_not_rendered(client, music):
    f = FLAC(music / "song.flac")
    pic = Picture()
    pic.type, pic.mime, pic.data = 3, "text/html", b"<script>fetch('/api/tracks',{method:'PATCH'})</script>"
    f.add_picture(pic)
    f.save()

    res = client.get("/api/art", params={"path": "song.flac"})

    assert res.headers["content-type"] == "application/octet-stream"
    assert res.headers["content-disposition"].startswith("attachment")
    assert res.headers["x-content-type-options"] == "nosniff"


def test_real_covers_still_display(client):
    jpeg = (FIXTURES_DIR / "cover.jpg").read_bytes()
    client.put("/api/art", params={"path": "song.flac"}, content=jpeg, headers={"Content-Type": "image/jpeg"})
    assert client.get("/api/art", params={"path": "song.flac"}).headers["content-type"] == "image/jpeg"


# --- 2. Security headers ---------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/api/health", "/static/app.js", "/api/auth/status"])
def test_security_headers_everywhere(client, path):
    h = client.get(path).headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "same-origin"
    csp = h["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]  # no inline scripts allowed


def test_page_has_no_inline_scripts(client):
    html = client.get("/").text
    assert "<script>" not in html  # every script is a file, so the CSP can forbid inline ones


def test_api_docs_still_work(client):
    res = client.get("/docs")
    assert res.status_code == 200 and "content-security-policy" not in res.headers


# --- 3. Request size limits --------------------------------------------------------------------


def test_huge_sign_in_body_is_refused_before_reading(music, tmp_path):
    with make_client(music, tmp_path) as c:
        res = c.post("/api/auth/login", content=b"x" * (2 * 1024 * 1024), headers={"Content-Type": "application/json"})
        assert res.status_code == 413


def test_chunked_body_without_length_is_refused(client):
    def gen():
        yield b'{"username": "a", '
        yield b'"password": "b"}'
    res = client.post("/api/auth/login", content=gen(), headers={"Content-Type": "application/json"})
    assert res.status_code == 411


def test_album_art_limit_is_larger_than_json_limit(client):
    big_jpeg = b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024)  # 5 MB: fine for art, too big for JSON
    res = client.put("/api/art", params={"path": "song.flac"}, content=big_jpeg, headers={"Content-Type": "image/jpeg"})
    assert res.status_code == 200  # reaches the app (it then rejects the fake image itself)
    too_big = client.put("/api/art", params={"path": "song.flac"}, content=b"\x00" * (26 * 1024 * 1024))
    assert too_big.status_code == 413


def test_avatar_limit(client):
    res = client.put("/api/account/avatar", content=b"\x00" * (4 * 1024 * 1024), headers={"Content-Type": "image/webp"})
    assert res.status_code == 413


# --- 4. Cross-site requests -----------------------------------------------------------------------


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_cross_site_writes_are_blocked(client, site):
    # "same-site" covers other apps on the same server (different port).
    res = client.patch("/api/tracks", json={"paths": ["song.flac"], "changes": {"title": "pwned"}},
                       headers={"Sec-Fetch-Site": site})
    assert res.status_code == 403
    assert client.get("/api/track", params={"path": "song.flac"}).json()["tags"]["title"] == ["Test Track"]


def test_same_origin_writes_work(client):
    res = client.patch("/api/tracks", json={"paths": ["song.flac"], "changes": {"title": "ok"}},
                       headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver"})
    assert res.status_code == 200


def test_mismatched_origin_blocked_for_older_browsers(client):
    res = client.post("/api/auth/logout", headers={"Origin": "http://evil.example"})
    assert res.status_code == 403


def test_reverse_proxy_host_is_respected(client):
    res = client.post("/api/auth/logout", headers={"Origin": "https://codetta.example.com",
                                                   "X-Forwarded-Host": "codetta.example.com"})
    assert res.status_code == 200


def test_reads_are_not_blocked(client):
    assert client.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


# --- 5. Release links -------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://evil.example/x", "http://github.com/x", None])
def test_only_github_release_links_reach_the_page(url):
    status = UpdateChecker("0.1.0", fetch=lambda repo: {"tag_name": "v9.0.0", "html_url": url}).status()
    assert status["release_url"] is None


def test_github_release_link_kept():
    url = "https://github.com/gavndev/codetta/releases/tag/v9.0.0"
    assert UpdateChecker("0.1.0", fetch=lambda repo: {"tag_name": "v9.0.0", "html_url": url}).status()["release_url"] == url


# --- 6. Password hashing strength ---------------------------------------------------------------------


def test_new_hashes_are_current_strength():
    assert not needs_rehash(hash_password("correct horse 1"))


def test_old_weak_hash_upgrades_on_sign_in(music, tmp_path):
    import base64, hashlib, os
    salt = os.urandom(16)
    weak = hashlib.scrypt(b"correct horse 1", salt=salt, n=2**14, r=8, p=1, dklen=32)
    old_hash = f"scrypt${2**14}$8$1${base64.b64encode(salt).decode()}${base64.b64encode(weak).decode()}"
    assert needs_rehash(old_hash)
    store = AccountStore(tmp_path / "config" / "auth.json")
    (tmp_path / "config").mkdir()
    store._save(type("A", (), {"username": "listener", "password_hash": old_hash})())

    with make_client(music, tmp_path) as c:
        assert c.post("/api/auth/login", json={"username": "listener", "password": "correct horse 1"}).status_code == 200
    upgraded = AccountStore(tmp_path / "config" / "auth.json").get().password_hash
    assert upgraded != old_hash and not needs_rehash(upgraded)


# --- 7. Brute-force tracker stays bounded --------------------------------------------------------------


def test_rate_limiter_memory_is_bounded():
    limiter = LoginRateLimiter()
    limiter.MAX_TRACKED = 100
    for i in range(1000):
        limiter.failed(f"10.0.{i // 256}.{i % 256}")
    assert len(limiter._failures) <= 100


# --- 8. Optional allowed hosts (DNS rebinding) ------------------------------------------------------------


def test_allowed_hosts(music, tmp_path):
    with make_client(music, tmp_path, allowed_hosts=("music-server", "192.168.1.50")) as c:
        assert c.get("/api/health", headers={"Host": "music-server:8111"}).status_code == 200
        assert c.get("/api/health", headers={"Host": "192.168.1.50:8111"}).status_code == 200
        assert c.get("/api/health", headers={"Host": "attacker.example"}).status_code == 421
        # The setup screen can't be reached through a rebinding domain.
        res = c.post("/api/auth/setup", json={"username": "x", "password": "yyyyyyyy"}, headers={"Host": "attacker.example"})
        assert res.status_code == 421


def test_allowed_hosts_from_env(monkeypatch):
    monkeypatch.setenv("CODETTA_ALLOWED_HOSTS", "music-server, 192.168.1.50")
    assert Settings.from_env().allowed_hosts == ("music-server", "192.168.1.50")


# --- Regression tests for the code-review findings ------------------------------------------


def test_limiter_cap_holds_when_checked_before_failing():
    # The login route calls retry_after() first; that used to create entries and skip the cap.
    limiter = LoginRateLimiter()
    limiter.MAX_TRACKED = 100
    for i in range(1000):
        key = f"10.1.{i // 256}.{i % 256}"
        limiter.retry_after(key)
        limiter.failed(key)
    assert len(limiter._failures) <= 100


def test_limiter_checks_and_successes_leave_no_entries():
    limiter = LoginRateLimiter()
    for i in range(50):
        limiter.retry_after(f"1.1.1.{i}")
        limiter.succeeded(f"1.1.1.{i}")
    assert len(limiter._failures) == 0


def test_null_origin_is_treated_as_cross_site(client):
    assert client.post("/api/auth/logout", headers={"Origin": "null"}).status_code == 403


def test_sign_in_required_responses_carry_security_headers(music, tmp_path):
    with make_client(music, tmp_path) as c:
        res = c.get("/api/browse")
        assert res.status_code == 401
        assert res.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy" in res.headers


def test_cover_lying_about_being_jpeg_is_still_downloaded(client, music):
    from mutagen.id3 import APIC, ID3
    shutil.copy2(FIXTURES_DIR / "sample.mp3", music / "liar.mp3")
    tags = ID3(music / "liar.mp3")
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=b"<svg onload=alert(1)>"))
    tags.save()
    res = client.get("/api/art", params={"path": "liar.mp3"})
    assert res.headers["content-type"] == "application/octet-stream"


@pytest.mark.parametrize(("data", "mime"), [
    (b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24, "image/webp"),
    (b"GIF89a" + b"\x00" * 32, "image/gif"),
])
def test_real_webp_and_gif_covers_display(client, music, data, mime):
    f = FLAC(music / "song.flac")
    pic = Picture()
    pic.type, pic.mime, pic.data = 3, mime, data
    f.clear_pictures()
    f.add_picture(pic)
    f.save()
    assert client.get("/api/art", params={"path": "song.flac"}).headers["content-type"] == mime


def test_parallel_sign_ins_are_capped(monkeypatch):
    import codetta.core.auth as auth
    monkeypatch.setattr(auth, "HASH_WAIT_SECONDS", 0.05)
    held = [auth._hash_slots.acquire() for _ in range(auth.MAX_CONCURRENT_HASHES)]
    try:
        with pytest.raises(auth.BusyError):
            auth.hash_password("x" * 12)
    finally:
        for _ in held:
            auth._hash_slots.release()


def test_busy_sign_in_answers_503(client, monkeypatch):
    import codetta.core.auth as auth
    monkeypatch.setattr(auth, "HASH_WAIT_SECONDS", 0.05)
    client.cookies.clear()
    held = [auth._hash_slots.acquire() for _ in range(auth.MAX_CONCURRENT_HASHES)]
    try:
        res = client.post("/api/auth/login", json={"username": "listener", "password": "correct horse 1"})
        assert res.status_code == 503 and res.headers["retry-after"]
    finally:
        for _ in held:
            auth._hash_slots.release()


def test_allowed_hosts_behind_a_reverse_proxy(music, tmp_path):
    with make_client(music, tmp_path, allowed_hosts=("music.example.com",)) as c:
        res = c.get("/api/health", headers={"Host": "codetta:8111", "X-Forwarded-Host": "music.example.com"})
        assert res.status_code == 200


def test_multi_hop_forwarded_host(client):
    res = client.post("/api/auth/logout", headers={
        "Origin": "https://a.example", "X-Forwarded-Host": "a.example, b.internal"})
    assert res.status_code == 200


@pytest.mark.parametrize("stored", ["scrypt$65536$1$1$AAAA$AAAA", "scrypt$32768$8$0$AAAA$AAAA", "scrypt$16384$8$1$AAAA$AAAA"])
def test_any_weaker_parameter_triggers_rehash(stored):
    assert needs_rehash(stored)


# --- Connections (online features) ------------------------------------------------------


def test_provider_redirects_never_downgrade_to_http():
    """A provider (or someone in the middle) can't bounce a request to plain http."""
    import urllib.request

    from codetta.core.providers import ProviderError, _HttpsOnlyRedirects

    req = urllib.request.Request("https://coverartarchive.org/release/x/front")
    with pytest.raises(ProviderError):
        _HttpsOnlyRedirects().redirect_request(req, None, 302, "Found", {}, "http://evil.example/cover.jpg")
    ok = _HttpsOnlyRedirects().redirect_request(req, None, 307, "Found", {}, "https://archive.org/cover.jpg")
    assert ok.full_url == "https://archive.org/cover.jpg"


def test_providers_refuse_plain_http_unless_a_mirror_was_configured():
    from codetta.core.providers import ProviderError, http_get

    with pytest.raises(ProviderError):
        http_get("http://musicbrainz.org/ws/2/release", "test")
    with pytest.raises(ProviderError):
        http_get("file:///etc/passwd", "test", allow_http=True)


def test_connections_and_musicbrainz_routes_need_sign_in(music, tmp_path):
    with make_client(music, tmp_path, musicbrainz=True) as c:
        for method, url in [("get", "/api/connections"), ("put", "/api/connections"),
                            ("post", "/api/musicbrainz/search"), ("post", "/api/musicbrainz/preview"),
                            ("post", "/api/musicbrainz/apply"), ("post", "/api/musicbrainz/identify"),
                            ("get", "/api/musicbrainz/cover/11111111-1111-4111-8111-111111111111")]:
            assert getattr(c, method)(url).status_code == 401, url


def test_nothing_goes_online_on_a_fresh_install(music, tmp_path):
    """Offline by default: no update check, lyrics or MusicBrainz until the user opts in."""
    calls = []

    def spy(*args):
        calls.append(args)
        raise AssertionError("network used")

    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"),
                     fetch_release=spy, fetch_json=spy, fetch_mb=spy, fetch_art=spy, post_acoustid=spy, run_fpcalc=spy)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        c.get("/api/update", params={"force": True})
        c.get("/api/lyrics/lookup", params={"path": "song.flac"})
        c.post("/api/musicbrainz/search", json={"folder": "", "album": "x"})
        c.get("/api/musicbrainz/cover/11111111-1111-4111-8111-111111111111")
        c.post("/api/musicbrainz/identify", json={"folder": ""})
    assert calls == []  # not even fpcalc ran


def test_fpcalc_only_ever_gets_a_resolved_library_path(music, tmp_path):
    """The file path handed to fpcalc is absolute and inside the library, so it
    can't be mistaken for an option or point anywhere else."""
    argvs = []

    def run(argv):
        argvs.append(argv)
        return '{"duration": 1, "fingerprint": "AQAA"}'

    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config", musicbrainz=True, acoustid=True),
                     run_fpcalc=run, post_acoustid=lambda form: {"status": "ok", "fingerprints": []},
                     fetch_mb=lambda url: {"releases": []})
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        assert c.post("/api/musicbrainz/identify", json={"paths": ["../../etc/passwd"]}).status_code in (400, 404, 200)
        c.post("/api/musicbrainz/identify", json={"paths": ["song.flac"]})
    assert len(argvs) == 1
    assert argvs[0][-1] == str((music / "song.flac").resolve()) and argvs[0][-1].startswith("/")


@pytest.mark.parametrize("name", ["codetta.png", "codetta-light.svg", "codetta-dark.webp"])
def test_dashboard_icons_load_without_sign_in(client, name):
    """Dashboards (Homepage, Homarr...) fetch the icon without a session."""
    client.cookies.clear()
    assert client.get(f"/static/icons/{name}").status_code == 200


def test_every_static_folder_ships_in_the_package():
    """Each folder under web/static must be listed in pyproject's package-data,
    or the Docker image silently leaves it out (0.4.0's dashboard icons)."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).parent.parent
    patterns = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["codetta"]
    static = root / "src" / "codetta" / "web" / "static"
    for folder in (p for p in static.iterdir() if p.is_dir()):
        assert f"web/static/{folder.name}/*" in patterns, folder.name


# --- In-browser player ---------------------------------------------------------------------


def test_stream_needs_sign_in(music, tmp_path):
    with make_client(music, tmp_path) as c:
        assert c.get("/api/stream", params={"path": "song.flac"}).status_code == 401


def test_stream_serves_audio_with_seeking(client, music):
    whole = (music / "song.flac").read_bytes()
    res = client.get("/api/stream", params={"path": "song.flac"})
    assert res.status_code == 200 and res.content == whole
    assert res.headers["content-type"] == "audio/flac" and res.headers["accept-ranges"] == "bytes"
    part = client.get("/api/stream", params={"path": "song.flac"}, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == whole[10:20]


@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "missing.flac", "notes.txt", ".hidden.flac/.."])
def test_stream_only_serves_audio_inside_the_library(client, music, path):
    (music / "notes.txt").write_text("secret")
    assert client.get("/api/stream", params={"path": path}).status_code in (400, 404)


def test_stream_type_never_comes_from_the_file(client, music):
    """A "song" that is really HTML is still sent as audio, so it can't run as a page."""
    (music / "evil.mp3").write_text("<script>alert(1)</script>")
    res = client.get("/api/stream", params={"path": "evil.mp3"})
    assert res.headers["content-type"] == "audio/mpeg" and res.headers["x-content-type-options"] == "nosniff"


# --- Organize --------------------------------------------------------------------------------


def test_organize_routes_need_sign_in(music, tmp_path):
    with make_client(music, tmp_path) as c:
        for method, url in [("get", "/api/organize/settings"), ("put", "/api/organize/settings"),
                            ("post", "/api/organize/preview"), ("post", "/api/organize/apply"),
                            ("post", "/api/organize/example")]:
            assert getattr(c, method)(url).status_code == 401, url


def test_organize_tags_cannot_move_files_out_of_the_library(client, music, tmp_path):
    """A file whose tags say "../../.." still lands inside the music folder."""
    from codetta.core.engine import MetadataEngine

    MetadataEngine().update_tags(music / "song.flac", {"albumartist": "../../../tmp", "album": "..", "title": "../x"})
    res = client.post("/api/organize/apply", json={"paths": ["song.flac"]}).json()
    assert res["moved"] == 1
    dst = (music / res["results"][0]["dst"]).resolve()
    assert dst.is_file() and dst.is_relative_to(music.resolve())


# --- Downloaded files (Soulseek) are untrusted: their tags can't steer files --------------


@pytest.mark.parametrize("artist", ["@replaced", "@inbox", "@inbox/../..", ".."])
def test_tags_cant_send_organize_into_codettas_own_folders(client, music, tmp_path, artist):
    from codetta.core.engine import MetadataEngine
    MetadataEngine().update_tags(music / "song.flac", {"albumartist": artist, "album": "X", "title": "t"})
    moves = client.post("/api/organize/preview", json={"paths": ["song.flac"]}).json()["moves"]
    dst = moves[0]["dst"]
    assert not dst.startswith("@") and ".." not in dst.split("/"), dst
    assert client.post("/api/organize/apply", json={"paths": ["song.flac"]}).json()["failed"] == 0
    assert not (tmp_path / "config" / "replaced").exists()
    assert (music / dst).is_file()


def test_inbox_cant_be_pointed_at_replaced_albums(client, tmp_path):
    (tmp_path / "config" / "replaced").mkdir(parents=True)
    r = client.put("/api/inbox/settings", json={"folder": "@replaced"})
    assert r.status_code == 422


def test_inbox_scan_has_a_limit(tmp_path, monkeypatch):
    from codetta.core import inbox
    from codetta.core.library import Library
    root = tmp_path / "m"
    for i in range(30):
        (root / "in" / f"empty{i:02}").mkdir(parents=True)
    (root / "in" / "zz" ).mkdir()
    (root / "in" / "zz" / "a.flac").write_bytes(b"x")
    monkeypatch.setattr(inbox, "MAX_SCAN_FOLDERS", 10)
    assert inbox.find_groups(Library(root), "in") == []  # stopped before reaching it
    monkeypatch.setattr(inbox, "MAX_SCAN_FOLDERS", 5000)
    assert inbox.find_groups(Library(root), "in") == [("in/zz", ["in/zz/a.flac"])]


def test_soulseek_download_never_claims_an_older_album_with_the_same_file_names(music, tmp_path):
    """Blocklisting deletes the download from the inbox, so it must be the right folder."""
    import time
    from tests.test_inbox import ALBUM_DIR  # noqa: F401
    from tests.test_musicbrainz import FakeMB
    from tests.test_soulseek_api import DownloadingSlskd, wait_for
    src = tmp_path / "src"
    src.mkdir()
    for n in ("01.flac", "02.flac"):
        shutil.copy2(FIXTURES_DIR / "sample.flac", src / n)
    downloads = tmp_path / "downloads"
    old = downloads / "My Own Rip"  # already in the inbox: shares "01.flac", "02.flac", but has more
    old.mkdir(parents=True)
    for n in ("01.flac", "02.flac", "03.flac", "04.flac", "05.flac"):
        shutil.copy2(FIXTURES_DIR / "sample.flac", old / n)
    fake = DownloadingSlskd(src, downloads)
    fake.dl = tmp_path / "elsewhere"  # slskd "downloads" somewhere Codetta doesn't see
    fake.dl.mkdir()
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config", inbox_dir=downloads,
                              inbox_settle_seconds=0, slskd_poll_seconds=0.02),
                     fetch_mb=FakeMB(), fetch_art=lambda url: None, slskd_request=fake)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        c.put("/api/connections", json={"enabled": {"slskd": True}})
        c.put("/api/slskd/settings", json={"url": "slskd:5030", "api_key": "codetta-test-key-0001", "choose": False})
        c.put("/api/inbox/settings", json={"folder": "@inbox"})
        job = c.post("/api/slskd/search", json={"query": "Coda Tester Fixture Album"}).json()["job"]
        job = wait_for(c, job["id"], lambda j: j["status"] == "fetched")
        time.sleep(0.3)
        job = wait_for(c, job["id"], lambda j: True)
        assert job["status"] == "fetched" and job["inbox"] is None  # still waiting: not "My Own Rip"
        assert c.post(f"/api/slskd/jobs/{job['id']}/next", json={"block": True}).status_code == 200
        assert all((old / f"0{i}.flac").exists() for i in range(1, 6))


# --- Input validation: bad input gets a clear answer, never reaches deeper code ------------------


def test_inputs_are_validated(client):
    c = client
    long_path = "a/" * 3000
    assert c.get("/api/browse", params={"path": long_path}).status_code == 422
    assert c.get("/api/track", params={"path": long_path}).status_code == 422
    assert c.post("/api/presets", json={"name": "", "tags": {}}).status_code == 422
    assert c.post("/api/presets", json={"name": "x" * 101, "tags": {}}).status_code == 422
    assert c.patch("/api/tracks", json={"paths": ["song.flac"], "changes": {f"k{i}": "v" for i in range(201)}}).status_code == 422
    assert c.post("/api/library-health/ignore", json={"id": "../../etc"}).status_code == 422
    assert c.post("/api/slskd/jobs/..%2F..%2Fx/cancel").status_code == 404
    assert c.post("/api/slskd/search", json={"query": "a"}).status_code == 422
    for bad in ("ftp://slskd:5030", "http://user:pw@slskd:5030", "http://slskd:port", "http://slskd:5030/?x=1", "http:// slskd"):
        r = c.put("/api/slskd/settings", json={"url": bad})
        assert r.status_code == 422, bad
    assert c.put("/api/slskd/settings", json={"url": "slskd:5030", "api_key": "short"}).status_code == 422
    assert c.put("/api/slskd/settings", json={"url": "slskd:5030", "api_key": "has a space in it"}).status_code == 422
    assert c.put("/api/slskd/settings", json={"url": "http://192.168.1.50:5030"}).status_code == 200


def test_failed_sign_in_never_logs_the_typed_username(tmp_path, caplog):
    """People sometimes type their password into the username box: that must never reach the log."""
    import logging

    from fastapi.testclient import TestClient

    from codetta.web.app import Settings, create_app
    with TestClient(create_app(Settings(music_dir=tmp_path, config_dir=tmp_path / "c"))) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": "correct horse 1"})
        c.post("/api/auth/logout")
        with caplog.at_level(logging.WARNING, logger="codetta"):
            c.post("/api/auth/login", json={"username": "my-real-password-oops", "password": "wrong"})
    assert "Failed sign-in" in caplog.text and "my-real-password-oops" not in caplog.text


def test_import_names_can_never_escape_or_overwrite(tmp_path):
    from fastapi.testclient import TestClient

    from codetta.web.app import Settings, create_app
    music = tmp_path / "music"
    music.mkdir()
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "c"))) as c:
        assert c.put("/api/import", params={"batch": "abc-1234", "path": "x.flac"}, content=b"x").status_code == 401
        c.post("/api/auth/setup", json={"username": "owner", "password": "correct horse 1"})
        for evil in ("../../etc/passwd", "/etc/passwd", "..\\..\\boot.ini", "a/../../../x", "./.hidden"):
            r = c.put("/api/import", params={"batch": "abc-1234", "path": evil}, content=b"data")
            assert r.status_code == 200, evil
            assert r.json()["path"].startswith("Imported/Import abc-1234/"), r.json()
        assert not (tmp_path / "etc").exists() and not (music / "etc").exists()
        assert not [p for p in (music / "Imported").rglob("*") if p.name.startswith(".")]  # never a hidden file
        a = c.put("/api/import", params={"batch": "abc-1234", "path": "same.flac"}, content=b"first").json()["path"]
        b = c.put("/api/import", params={"batch": "abc-1234", "path": "same.flac"}, content=b"second").json()["path"]
        assert a != b and (music / a).read_bytes() == b"first"  # the second never replaces the first
        assert c.put("/api/import", params={"batch": "../../x", "path": "a.flac"}, content=b"x").status_code == 422
        big = c.put("/api/import", params={"batch": "abc-1234", "path": "big.flac"}, content=b"x",
                    headers={"Content-Length": str(3 * 1024 * 1024 * 1024)})
        assert big.status_code == 413  # refused before anything is read


def test_deleting_for_good_needs_the_typed_count_and_stays_inside(tmp_path):
    import shutil as sh

    from fastapi.testclient import TestClient

    from codetta.web.app import Settings, create_app
    music = tmp_path / "music"
    (music / "A").mkdir(parents=True)
    for n in ("1.flac", "2.flac"):
        sh.copy2(FIXTURES_DIR / "sample.flac", music / "A" / n)
    outside = tmp_path / "keep-me.txt"
    outside.write_text("precious")
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "c", auth=False))) as c:
        c.post("/api/files/delete", json={"paths": ["A"]})
        bid = c.get("/api/deleted").json()["items"][0]["id"]
        assert c.post("/api/deleted/erase", json={"ids": [bid]}).status_code == 409  # no confirmation
        assert c.post("/api/deleted/erase", json={"ids": [bid], "confirm": 1}).status_code == 409  # wrong count
        for evil in ("..", "../..", "20260101-000000/../..", "keep-me.txt"):
            assert c.post("/api/deleted/erase", json={"ids": [evil], "confirm": 1}).status_code in (404, 422)
        assert outside.read_text() == "precious"
        r = c.post("/api/deleted/erase", json={"ids": [bid], "confirm": 2}).json()
        assert r["erased"] == 2 and r["files"] == 0
        entry = c.get("/api/activity").json()[0]
        assert entry["kind"] == "erase" and not entry["can_undo"]  # the one change that can't be undone


def test_problem_report_is_private_and_has_no_account_details(tmp_path):
    from fastapi.testclient import TestClient

    from codetta.web.app import Settings, create_app
    music = tmp_path / "music"
    music.mkdir()
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "c"))) as c:
        assert c.get("/api/report").status_code == 401
        c.post("/api/auth/setup", json={"username": "secret-owner-name", "password": "correct horse 1"})
        r = c.get("/api/report")
        assert r.status_code == 200 and r.json()["version"]
        assert "secret-owner-name" not in r.text


# --- Lidarr: its routes are private, and its API key never leaves the server -----------------------


def test_lidarr_routes_need_sign_in_and_never_show_the_key(music, tmp_path):
    key = "0123456789abcdef0123456789abcdef"

    def fake(method, url, headers, body):
        return 401, b""  # a Lidarr that turns the key down: enough for this test

    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config"), lidarr_request=fake)) as c:
        assert c.get("/api/lidarr").status_code == 401
        assert c.put("/api/lidarr/settings", json={"url": "lidarr:8686", "api_key": key}).status_code == 401
        assert c.post("/api/lidarr/test").status_code == 401
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        c.put("/api/connections", json={"enabled": {"lidarr": True}})
        for res in (c.put("/api/lidarr/settings", json={"url": "lidarr:8686", "api_key": key}),
                    c.get("/api/lidarr"), c.post("/api/lidarr/test"), c.get("/api/connections")):
            assert res.status_code == 200 and key not in res.text


# --- Music server: its routes are private, and its password / token never leave the server ---------


def test_media_server_routes_need_sign_in_and_never_show_secrets(music, tmp_path):
    password, token = "server-password-123", "0123456789abcdef0123456789abcdef"

    def fake(method, url, headers, body):
        return 401, b""  # a server that turns everything down: enough for this test

    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config"), server_request=fake)) as c:
        body = {"kind": "subsonic", "url": "navidrome:4533", "username": "admin", "password": password}
        assert c.get("/api/mediaserver").status_code == 401
        assert c.put("/api/mediaserver/settings", json=body).status_code == 401
        assert c.post("/api/mediaserver/test").status_code == 401
        assert c.post("/api/mediaserver/scan").status_code == 401
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        c.put("/api/connections", json={"enabled": {"mediaserver": True}})
        for res in (c.put("/api/mediaserver/settings", json=body), c.get("/api/mediaserver"),
                    c.post("/api/mediaserver/test"), c.post("/api/mediaserver/scan"), c.get("/api/connections")):
            assert res.status_code == 200 and password not in res.text
        res = c.put("/api/mediaserver/settings", json={"kind": "jellyfin", "url": "jellyfin:8096", "token": token})
        assert res.status_code == 200 and token not in res.text and token not in c.get("/api/mediaserver").text


def test_zip_download_needs_sign_in_and_stays_in_the_library(music, tmp_path):
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config"))) as c:
        (music / "Album").mkdir()
        shutil.copy2(music / "song.flac", music / "Album" / "song.flac")
        folder = "Album"
        assert c.get("/api/folders/zip", params={"path": folder}).status_code == 401
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        assert c.get("/api/folders/zip", params={"path": folder}).status_code == 200
        for bad in ("../", "/etc", "..%2F..", "a/../../b"):
            assert c.get("/api/folders/zip", params={"path": bad}).status_code in (400, 404, 422)


def test_file_downloads_need_sign_in(music, tmp_path):
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config"))) as c:
        assert c.get("/api/files/download", params={"path": "song.flac"}).status_code == 401
        assert c.post("/api/files/zip", json={"paths": ["song.flac"]}).status_code == 401
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        url = c.post("/api/files/zip", json={"paths": ["song.flac"]}).json()["url"]
        assert c.get("/api/files/download", params={"path": "song.flac"}).status_code == 200
        c.post("/api/auth/logout")
        c.cookies.clear()
        assert c.get(url).status_code == 401  # a prepared link is no use without signing in


def test_music_app_api_is_the_only_new_public_path(tmp_path):
    """/rest/ skips Codetta's session check because apps sign in with the app password on every
    request; it must not open anything else, and it stays shut until switched on."""
    from fastapi.testclient import TestClient

    from codetta.web.app import Settings, create_app
    (tmp_path / "music").mkdir()
    app = create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": "a-long-enough-password-1"})
        anon = TestClient(app)
        assert anon.get("/rest/ping", params={"f": "json"}).json()["subsonic-response"]["error"]["code"] == 50
        assert anon.get("/rest/../api/browse", params={"path": ""}).status_code in (401, 404)
        assert anon.get("/api/subsonic").status_code == 401
        assert anon.put("/api/subsonic", json={"enabled": True}).status_code == 401
