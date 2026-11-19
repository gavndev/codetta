"""The ``codetta`` command (pipx/uv installs): folders, ports, admin commands, packaging."""

import os
import socket
import tomllib
from pathlib import Path

import pytest

from codetta.cli import run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def music(tmp_path, monkeypatch):
    for name in ("CODETTA_MUSIC_DIR", "CODETTA_CONFIG_DIR", "CODETTA_HOST", "SNAP_USER_COMMON", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(name, raising=False)
    folder = tmp_path / "music"
    folder.mkdir()
    return folder


@pytest.fixture
def served(monkeypatch):
    """Stands in for uvicorn: records what would have been served."""
    import uvicorn
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.setattr(run, "_open_when_ready", lambda *a: pytest.fail("opened a browser"))
    return calls


def test_runs_on_this_computer_only_by_default(music, tmp_path, served, capsys):
    config = tmp_path / "cfg"
    assert run.main([str(music), "--config", str(config), "--no-browser"]) == 0
    (kw,) = served
    assert kw["host"] == "127.0.0.1" and 8111 <= kw["port"] < 8131
    assert kw["access_log"] is False and kw["server_header"] is False  # no record of visitors (PRIVACY.md)
    assert config.is_dir()
    assert os.environ["CODETTA_MUSIC_DIR"] == str(music.resolve())
    assert os.environ["CODETTA_CONFIG_DIR"] == str(config)
    assert "http://localhost:" in capsys.readouterr().out


def test_missing_folder_and_bad_port_are_plain_errors(music, tmp_path, served, capsys):
    assert run.main([str(tmp_path / "nope"), "--no-browser"]) == 2
    assert "there's no folder" in capsys.readouterr().err
    assert run.main([str(music), "--port", "70000", "--no-browser"]) == 2
    assert served == []


def test_a_port_in_use_is_reported_or_skipped(music, tmp_path, served, capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        assert run.main([str(music), "--port", str(busy), "--config", str(tmp_path / "c"), "--no-browser"]) == 2
        assert "in use" in capsys.readouterr().err
        assert served == []
    assert run._free("127.0.0.1", busy)


def test_config_folder_per_system(monkeypatch, tmp_path):
    monkeypatch.delenv("SNAP_USER_COMMON", raising=False)
    monkeypatch.setattr(run.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(run.sys, "platform", "darwin")
    assert run.default_config_dir() == tmp_path / "Library" / "Application Support" / "Codetta"
    monkeypatch.setattr(run.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert run.default_config_dir() == tmp_path / "xdg" / "codetta"
    monkeypatch.setattr(run.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert run.default_config_dir() == tmp_path / "roaming" / "Codetta"
    monkeypatch.setenv("SNAP_USER_COMMON", str(tmp_path / "snap"))  # snap wins: it survives updates
    assert run.default_config_dir() == tmp_path / "snap" / "config"


def test_music_folder_in_a_snap_is_the_real_home(monkeypatch, tmp_path):
    (tmp_path / "real" / "Music").mkdir(parents=True)
    monkeypatch.setattr(run.Path, "home", lambda: tmp_path / "snap" / "codetta" / "12")
    monkeypatch.setenv("SNAP_REAL_HOME", str(tmp_path / "real"))
    assert run.default_music_dir() == tmp_path / "real" / "Music"
    monkeypatch.delenv("SNAP_REAL_HOME")
    assert run.default_music_dir() == tmp_path / "snap" / "codetta" / "12" / "Music"


def test_admin_commands_use_the_same_config_folder(monkeypatch, tmp_path):
    seen = []
    import codetta.cli.__main__ as admin
    monkeypatch.setattr(admin, "main", lambda argv: seen.append(argv) or 0)
    monkeypatch.setenv("CODETTA_CONFIG_DIR", str(tmp_path))
    assert run.main(["sign-out-all"]) == 0
    assert seen == [["--config", str(tmp_path), "sign-out-all"]]


def test_packaged_app_starts_index_helpers_in_helper_mode(monkeypatch):
    import codetta.core.describe as describe
    ran = []
    monkeypatch.setattr(describe, "_worker_main", lambda: ran.append(True))
    assert run.main(["--codetta-describe-worker"]) == 0 and ran == [True]


def test_package_metadata_and_bundled_changelog():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["scripts"]["codetta"] == "codetta.cli.run:main"
    assert project["readme"] == "README.md"
    # The installed package's "What's new" reads its own copy: a link to the real one, never a stale copy.
    bundled = ROOT / "src" / "codetta" / "CHANGELOG.md"
    assert bundled.is_symlink() and bundled.resolve() == (ROOT / "CHANGELOG.md").resolve()
