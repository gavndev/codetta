"""Tests for sign-in: hashing, account, sessions, rate limiting, API, and CLI."""

import json
import os
import stat

import pytest
from fastapi.testclient import TestClient

from coda.cli.__main__ import main as cli_main
from coda.core.auth import (
    AccountStore,
    AuthError,
    LoginRateLimiter,
    SessionStore,
    hash_password,
    verify_password,
)
from coda.web.app import SESSION_COOKIE, Settings, create_app

USER, PASSWORD = "gavin", "correct horse battery"


# --- Password hashing ------------------------------------------------------------------


def test_hash_round_trip():
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$")
    assert PASSWORD not in stored
    assert verify_password(PASSWORD, stored)
    assert not verify_password("wrong password", stored)


def test_hashes_are_salted():
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


@pytest.mark.parametrize("stored", ["", "plain", "md5$abc", "scrypt$x$y$z$!!$!!"])
def test_verify_rejects_malformed_hashes(stored):
    assert verify_password(PASSWORD, stored) is False


# --- Account store -------------------------------------------------------------------------


def test_setup_then_check(tmp_path):
    accounts = AccountStore(tmp_path / "auth.json")
    assert accounts.setup_required
    accounts.create(USER, PASSWORD)
    assert not accounts.setup_required
    assert accounts.check(USER, PASSWORD).username == USER
    assert accounts.check("GAVIN", PASSWORD) is not None  # username isn't case-sensitive
    assert accounts.check(USER, "nope nope nope") is None
    assert accounts.check("someone", PASSWORD) is None


def test_auth_file_is_private_and_has_no_plain_password(tmp_path):
    file = tmp_path / "auth.json"
    AccountStore(file).create(USER, PASSWORD)
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert PASSWORD not in file.read_text()


def test_setup_only_once(tmp_path):
    accounts = AccountStore(tmp_path / "auth.json")
    accounts.create(USER, PASSWORD)
    with pytest.raises(AuthError, match="already set up"):
        accounts.create("intruder", "another password")


@pytest.mark.parametrize(("user", "pw"), [("", PASSWORD), ("has space", PASSWORD), (USER, "short")])
def test_bad_new_credentials(tmp_path, user, pw):
    with pytest.raises(AuthError):
        AccountStore(tmp_path / "auth.json").create(user, pw)


def test_env_account_overrides_file(tmp_path):
    accounts = AccountStore(tmp_path / "auth.json", "envuser", "env password 1")
    assert accounts.managed_by_env
    assert not accounts.setup_required
    assert accounts.check("envuser", "env password 1")
    with pytest.raises(AuthError, match="environment"):
        accounts.set_password("envuser", "something else")


# --- Sessions --------------------------------------------------------------------------------


def test_sessions_create_lookup_revoke(tmp_path):
    sessions = SessionStore(tmp_path / "sessions.json")
    token = sessions.create(USER)
    assert sessions.lookup(token) == USER
    assert sessions.lookup("forged-token") is None
    assert sessions.lookup(None) is None
    sessions.revoke(token)
    assert sessions.lookup(token) is None


def test_sessions_survive_restart_and_store_only_hashes(tmp_path):
    file = tmp_path / "sessions.json"
    token = SessionStore(file).create(USER)
    assert token not in file.read_text()
    assert SessionStore(file).lookup(token) == USER


def test_expired_sessions_are_rejected(tmp_path):
    sessions = SessionStore(tmp_path / "sessions.json", days=0)
    token = sessions.create(USER)
    assert sessions.lookup(token) is None


def test_revoke_all_keeps_one(tmp_path):
    sessions = SessionStore(None)
    a, b, c = (sessions.create(USER) for _ in range(3))
    sessions.revoke_all(keep=b)
    assert [sessions.lookup(t) for t in (a, b, c)] == [None, USER, None]


# --- Rate limiter ------------------------------------------------------------------------------


def test_rate_limiter_locks_after_five_failures():
    limiter = LoginRateLimiter()
    for _ in range(4):
        limiter.failed("1.2.3.4")
        assert limiter.retry_after("1.2.3.4") == 0
    limiter.failed("1.2.3.4")
    assert 25 <= limiter.retry_after("1.2.3.4") <= 31
    assert limiter.retry_after("5.6.7.8") == 0  # other devices unaffected
    limiter.failed("1.2.3.4")
    assert limiter.retry_after("1.2.3.4") > 31  # grows with more failures
    limiter.succeeded("1.2.3.4")
    assert limiter.retry_after("1.2.3.4") == 0


# --- API -----------------------------------------------------------------------------------------


@pytest.fixture
def make_client(tmp_path):
    music = tmp_path / "music"
    music.mkdir()

    def _make(**kwargs):
        settings = Settings(music_dir=music, config_dir=tmp_path / "config", **kwargs)
        return TestClient(create_app(settings))

    return _make


@pytest.fixture
def client(make_client):
    with make_client() as c:
        yield c


def test_first_run_requires_setup(client):
    assert client.get("/api/auth/status").json() == {
        "auth_enabled": True, "setup_required": True, "signed_in": False,
        "username": None, "managed_by_env": False,
    }
    assert client.get("/api/browse").status_code == 401


@pytest.mark.parametrize("path", [
    "/api/browse", "/api/track?path=x.flac", "/api/fields", "/api/status", "/api/loadouts",
    "/api/activity", "/api/art?path=x.flac", "/docs", "/openapi.json",
])
def test_everything_private_is_locked(client, path):
    client.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
    client.cookies.clear()
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("method,path", [
    ("patch", "/api/tracks"), ("put", "/api/art?path=x"), ("delete", "/api/art?path=x"),
    ("post", "/api/loadouts"), ("post", "/api/loadouts/apply"), ("delete", "/api/loadouts/Single"),
])
def test_writes_are_locked(client, method, path):
    res = getattr(client, method)(path)
    assert res.status_code == 401


def test_public_pages_still_load(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/health").json() == {"ok": True}


def test_setup_signs_in_and_cookie_is_safe(client):
    res = client.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE}=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert client.get("/api/auth/status").json()["signed_in"] is True
    assert client.get("/api/browse").status_code == 200


def test_setup_cannot_be_repeated(client):
    client.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
    client.cookies.clear()
    res = client.post("/api/auth/setup", json={"username": "intruder", "password": "taking over now"})
    assert res.status_code == 409


def test_setup_validation(client):
    res = client.post("/api/auth/setup", json={"username": USER, "password": "short"})
    assert res.status_code == 422
    assert "8 characters" in res.json()["detail"]


def test_login_logout(client):
    client.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"username": USER, "password": "wrong!!!"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": USER, "password": PASSWORD}).status_code == 200
    assert client.get("/api/browse").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/browse").status_code == 401


def test_logout_revokes_the_session_server_side(client):
    client.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
    token = client.cookies.get(SESSION_COOKIE)
    client.post("/api/auth/logout")
    client.cookies.set(SESSION_COOKIE, token)  # replaying the old cookie must not work
    assert client.get("/api/browse").status_code == 401


def test_forged_cookie_rejected(client):
    client.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, "made-up-token")
    assert client.get("/api/browse").status_code == 401


def test_brute_force_gets_locked_out(client):
    client.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
    client.cookies.clear()
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": USER, "password": "guess guess"}).status_code == 401
    res = client.post("/api/auth/login", json={"username": USER, "password": PASSWORD})
    assert res.status_code == 429  # even the right password waits during a lockout
    assert int(res.headers["retry-after"]) > 0
    assert "Try again" in res.json()["detail"]


def test_change_password_signs_out_other_devices(make_client):
    with make_client() as phone, make_client() as laptop:
        phone.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
        laptop.post("/api/auth/login", json={"username": USER, "password": PASSWORD})
        bad = phone.post("/api/auth/password", json={"current_password": "wrong one!", "new_password": "new password 2"})
        assert bad.status_code == 401
        ok = phone.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "new password 2"})
        assert ok.status_code == 200
        assert phone.get("/api/browse").status_code == 200  # this device stays signed in
        assert laptop.get("/api/browse").status_code == 401  # the other one is signed out
        laptop.cookies.clear()
        assert laptop.post("/api/auth/login", json={"username": USER, "password": PASSWORD}).status_code == 401
        assert laptop.post("/api/auth/login", json={"username": USER, "password": "new password 2"}).status_code == 200


def test_sessions_survive_server_restart(make_client):
    with make_client() as c:
        c.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
        token = c.cookies.get(SESSION_COOKIE)
    with make_client() as c2:
        c2.cookies.set(SESSION_COOKIE, token)
        assert c2.get("/api/browse").status_code == 200


def test_env_managed_account(make_client):
    with make_client(username="envuser", password="from the env 1") as c:
        status = c.get("/api/auth/status").json()
        assert status["setup_required"] is False and status["managed_by_env"] is True
        assert c.post("/api/auth/setup", json={"username": "x", "password": "yyyyyyyy"}).status_code == 409
        assert c.post("/api/auth/login", json={"username": "envuser", "password": "from the env 1"}).status_code == 200
        res = c.post("/api/auth/password", json={"current_password": "from the env 1", "new_password": "changed pw 2"})
        assert res.status_code == 422


def test_auth_off(make_client):
    with make_client(auth=False) as c:
        status = c.get("/api/auth/status").json()
        assert status["auth_enabled"] is False and status["signed_in"] is True
        assert c.get("/api/browse").status_code == 200


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("CODA_AUTH", "off")
    monkeypatch.setenv("CODA_USERNAME", "a")
    monkeypatch.setenv("CODA_PASSWORD", "b")
    s = Settings.from_env()
    assert (s.auth, s.username, s.password) == (False, "a", "b")
    monkeypatch.delenv("CODA_AUTH")
    assert Settings.from_env().auth is True


# --- CLI -------------------------------------------------------------------------------------------


def test_cli_set_password_and_sign_out_all(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config"
    AccountStore(config / "auth.json").create(USER, PASSWORD)
    sessions = SessionStore(config / "sessions.json")
    token = sessions.create(USER)

    answers = iter(["brand new pass", "brand new pass"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli_main(["--config", str(config), "set-password"]) == 0

    assert AccountStore(config / "auth.json").check(USER, "brand new pass")
    assert SessionStore(config / "sessions.json").lookup(token) is None  # everyone signed out
    assert "Password set" in capsys.readouterr().out


def test_cli_mismatched_passwords_change_nothing(tmp_path, monkeypatch):
    config = tmp_path / "config"
    AccountStore(config / "auth.json").create(USER, PASSWORD)
    answers = iter(["one password", "another password"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli_main(["--config", str(config), "set-password"]) == 1
    assert AccountStore(config / "auth.json").check(USER, PASSWORD)


def test_cli_creates_account_when_none(tmp_path, monkeypatch):
    config = tmp_path / "config"
    answers = iter(["first password", "first password"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli_main(["--config", str(config), "set-password", "--username", "admin"]) == 0
    assert AccountStore(config / "auth.json").check("admin", "first password")
    assert json.loads((config / "auth.json").read_text())["username"] == "admin"
    assert os.path.exists(config / "auth.json")


def test_cli_sign_out_all_affects_running_server(make_client, tmp_path):
    with make_client() as c:
        c.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
        assert c.get("/api/browse").status_code == 200
        assert cli_main(["--config", str(tmp_path / "config"), "sign-out-all"]) == 0
        assert c.get("/api/browse").status_code == 401
