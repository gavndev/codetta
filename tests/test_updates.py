"""Tests for the update check (codetta.core.updates + /api/update)."""

import urllib.error

import pytest
from fastapi.testclient import TestClient

from codetta.core.updates import UpdateChecker, is_newer, parse_version
from codetta.web.app import VERSION, Settings, create_app


@pytest.mark.parametrize(("text", "expected"), [
    ("v0.2.0", (0, 2, 0)), ("0.10.1", (0, 10, 1)), ("v1.0.0-beta.2", (1, 0, 0)), ("1", (1,)),
    ("", None), (None, None), ("latest", None),
])
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize(("candidate", "current", "newer"), [
    ("v0.2.0", "0.1.0", True), ("0.10.0", "0.9.9", True), ("v0.1.0", "0.1.0", False),
    ("0.1", "0.1.0", False), ("0.0.9", "0.1.0", False), ("garbage", "0.1.0", False),
])
def test_is_newer(candidate, current, newer):
    assert is_newer(candidate, current) is newer


def release(tag, notes="Fixes and improvements"):
    return lambda repo: {"tag_name": tag, "html_url": f"https://github.com/{repo}/releases/tag/{tag}",
                         "body": notes, "published_at": "2026-12-01T10:00:00Z"}


def test_update_available():
    status = UpdateChecker("0.1.0", fetch=release("v0.2.0")).status()
    assert status["update_available"] is True
    assert status["latest"] == "0.2.0"
    assert status["release_url"].endswith("/v0.2.0")
    assert status["notes"] == "Fixes and improvements"


def test_up_to_date():
    status = UpdateChecker("0.2.0", fetch=release("v0.2.0")).status()
    assert status["update_available"] is False and status["error"] is None


def test_no_releases_yet():
    def missing(repo):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    status = UpdateChecker("0.1.0", fetch=missing).status()
    assert status["update_available"] is False
    assert status["error"] is None
    assert status["note"] == "No releases published yet"


def test_offline():
    def offline(repo):
        raise urllib.error.URLError("no network")
    status = UpdateChecker("0.1.0", fetch=offline).status()
    assert status["update_available"] is False and "Couldn't reach GitHub" in status["error"]


def test_disabled_never_contacts_github():
    def boom(repo):
        raise AssertionError("should not be called")
    status = UpdateChecker("0.1.0", enabled=False, fetch=boom).status(force=True)
    assert status["enabled"] is False and status["current"] == "0.1.0"


def test_results_are_cached_until_forced():
    calls = []
    def counting(repo):
        calls.append(repo)
        return {"tag_name": "v0.1.0"}
    checker = UpdateChecker("0.1.0", fetch=counting)
    checker.status(); checker.status()
    assert len(calls) == 1
    checker.status(force=True)
    assert len(calls) == 1  # a forced re-check right away is throttled
    checker._checked_at -= checker.MIN_FORCE_INTERVAL
    checker.status(force=True)
    assert len(calls) == 2


def test_api_update_endpoint(tmp_path):
    (tmp_path / "music").mkdir()
    settings = Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config", update_check=True)
    with TestClient(create_app(settings, fetch_release=release("v99.0.0"))) as c:
        assert c.get("/api/update").status_code == 401  # private
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        data = c.get("/api/update").json()
        assert data["current"] == VERSION
        assert data["latest"] == "99.0.0" and data["update_available"] is True


def test_update_check_setting_from_env(monkeypatch):
    monkeypatch.delenv("CODETTA_UPDATE_CHECK", raising=False)
    assert Settings.from_env().update_check is None  # unset: the user decides in the app (off until then)
    monkeypatch.setenv("CODETTA_UPDATE_CHECK", "off")
    assert Settings.from_env().update_check is False
    monkeypatch.setenv("CODETTA_UPDATE_CHECK", "on")
    assert Settings.from_env().update_check is True


def test_update_check_is_off_until_opted_in(tmp_path):
    (tmp_path / "music").mkdir()
    calls = []

    def fetch(repo):
        calls.append(repo)
        return {"tag_name": "v99.0.0"}

    settings = Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config")
    with TestClient(create_app(settings, fetch_release=fetch)) as c:
        c.post("/api/auth/setup", json={"username": "listener", "password": "correct horse 1"})
        assert c.get("/api/update").json()["enabled"] is False
        assert calls == []  # GitHub was never asked
        c.put("/api/connections", json={"enabled": {"updates": True}})
        assert c.get("/api/update").json()["update_available"] is True
