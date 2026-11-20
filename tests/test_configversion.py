"""The config folder's version stamp and the upgrades between versions."""
import json
import os
import stat

import pytest
from fastapi.testclient import TestClient

from codetta.core import configversion as cv
from codetta.web.app import Settings, create_app


def stamp(d):
    return json.loads((d / cv.FILE).read_text())


def test_a_new_install_is_stamped_with_the_current_version(tmp_path):
    d = tmp_path / "config"
    r = cv.upgrade(d, "1.2.3")
    assert r.status == "fresh" and r.version == cv.CURRENT
    assert stamp(d) == {"version": cv.CURRENT, "written_by": "1.2.3"}
    assert not (d / cv.BACKUPS).exists()


def test_an_install_from_before_the_stamp_is_backed_up_and_upgraded(tmp_path):
    d = tmp_path / "config"
    (d / "loadouts").mkdir(parents=True)
    (d / "loadouts" / "single.json").write_text('{"name": "Single"}')
    (d / "auth.json").write_text("{}")
    os.chmod(d / "auth.json", 0o600)
    (d / "library-index.sqlite3").write_bytes(b"big and rebuildable")

    r = cv.upgrade(d, "0.9.1")

    assert r.status == "upgraded" and r.previous == 0 and r.version == cv.CURRENT
    assert (d / "presets" / "single.json").exists() and not (d / "loadouts").exists()
    assert stamp(d)["version"] == cv.CURRENT
    # The backup holds the settings as they were, private files stay private, the index isn't copied.
    assert (r.backup / "loadouts" / "single.json").exists()
    assert stat.S_IMODE((r.backup / "auth.json").stat().st_mode) == 0o600
    assert not (r.backup / "library-index.sqlite3").exists()


def test_an_up_to_date_folder_is_left_alone(tmp_path):
    d = tmp_path / "config"
    cv.upgrade(d, "0.9.1")
    before = (d / cv.FILE).stat().st_mtime_ns
    r = cv.upgrade(d, "0.9.2")
    assert r.status == "current"
    assert (d / cv.FILE).stat().st_mtime_ns == before
    assert not (d / cv.BACKUPS).exists()


def test_steps_run_in_order_and_each_is_stamped(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    (d / "settings.json").write_text('{"a": 1}')
    ran = []

    def step(n):
        def run(folder):
            ran.append(n)
            data = json.loads((folder / "settings.json").read_text())
            data[f"step{n}"] = True
            (folder / "settings.json").write_text(json.dumps(data))
        return run

    (d / cv.FILE).write_text('{"version": 1}')
    r = cv.upgrade(d, "x", steps={1: step(1), 2: step(2), 3: step(3)})
    assert ran == [2, 3]
    assert r.previous == 1 and r.version == 3 and stamp(d)["version"] == 3
    assert json.loads((d / "settings.json").read_text()) == {"a": 1, "step2": True, "step3": True}
    assert json.loads((r.backup / "settings.json").read_text()) == {"a": 1}


def test_a_failed_step_puts_every_file_back_and_stops_the_start(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    (d / "settings.json").write_text('{"a": 1}')
    (d / cv.FILE).write_text('{"version": 1}')

    def ok(folder):
        (folder / "settings.json").write_text('{"a": 2}')
        (folder / "new.json").write_text("{}")

    def broken(folder):
        (folder / "settings.json").write_text("half written")
        raise ValueError("boom")

    with pytest.raises(cv.ConfigUpgradeError, match="step 3: boom"):
        cv.upgrade(d, "x", steps={1: ok, 2: ok, 3: broken})
    assert (d / "settings.json").read_text() == '{"a": 1}'
    assert not (d / "new.json").exists()
    assert stamp(d)["version"] == 1
    assert list((d / cv.BACKUPS).iterdir())  # the copy is still there too


def test_settings_from_a_newer_codetta_are_never_touched(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    (d / cv.FILE).write_text(json.dumps({"version": cv.CURRENT + 5, "written_by": "9.0.0"}))
    (d / "loadouts").mkdir()
    r = cv.upgrade(d, "0.9.1")
    assert r.status == "newer" and r.version == cv.CURRENT + 5
    assert (d / "loadouts").exists() and not (d / "presets").exists()
    assert stamp(d)["written_by"] == "9.0.0"
    assert not (d / cv.BACKUPS).exists()


def test_a_damaged_stamp_reruns_the_safe_steps(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    (d / cv.FILE).write_text("not json")
    (d / "loadouts").mkdir()
    r = cv.upgrade(d, "0.9.1")
    assert r.status == "upgraded" and (d / "presets").exists()


def test_only_the_newest_backups_are_kept(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    (d / "settings.json").write_text("{}")
    for i in range(cv.KEEP_BACKUPS + 2):
        (d / cv.FILE).write_text('{"version": 0}')
        r = cv.upgrade(d, f"0.9.{i}", steps={1: lambda f: None})
        os.utime(r.backup, (i, i))
    assert len(list((d / cv.BACKUPS).iterdir())) == cv.KEEP_BACKUPS


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores permissions")
def test_a_read_only_config_folder_still_starts(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    (d / "settings.json").write_text("{}")
    os.chmod(d, 0o555)
    try:
        r = cv.upgrade(d, "0.9.1")
    finally:
        os.chmod(d, 0o755)
    assert r.status == "readonly"


def test_the_app_warns_once_about_settings_from_a_newer_codetta(tmp_path):
    music, config = tmp_path / "music", tmp_path / "config"
    music.mkdir()
    config.mkdir()
    (config / cv.FILE).write_text(json.dumps({"version": cv.CURRENT + 1}))
    settings = Settings(music_dir=music, config_dir=config, username="alex", password="correct horse 1")
    for _ in range(2):
        with TestClient(create_app(settings)):
            pass
    items = json.loads((config / "notifications.json").read_text())
    items = items.get("items", items) if isinstance(items, dict) else items
    assert [n["title"] for n in items].count("Settings from a newer Codetta") == 1


def test_every_step_is_safe_to_run_twice(tmp_path):
    """A crash can stop a step after its work but before its stamp."""
    for n, step in cv.STEPS.items():
        d = tmp_path / f"v{n}"
        d.mkdir()
        (d / "loadouts").mkdir()
        step(d)
        snapshot = sorted(p.relative_to(d).as_posix() for p in d.rglob("*"))
        step(d)
        assert sorted(p.relative_to(d).as_posix() for p in d.rglob("*")) == snapshot
