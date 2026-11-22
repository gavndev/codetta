"""Plugins: built-in actions; people's own plugins (paused: never loaded by Codetta); the loader's
handling of outside plugins, kept for when they come back."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.plugins import PluginManager
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


@pytest.fixture
def make(tmp_path):
    def build(plugins: dict | None = None):
        music = tmp_path / "music" / "Album"
        music.mkdir(parents=True, exist_ok=True)
        e = MetadataEngine()
        for i, t in enumerate(["Night Drive (Official Video)", "neon arcade ft. zayn", "Plain"], 1):
            f = music / f"0{i}.flac"
            if not f.exists():
                shutil.copy2(FIXTURES_DIR / "sample.flac", f)
                e.update_tags(f, {"title": t})
        for pid, files in (plugins or {}).items():
            d = tmp_path / "config" / "plugins" / pid
            d.mkdir(parents=True, exist_ok=True)
            for name, text in files.items():
                (d / name).write_text(text if isinstance(text, str) else json.dumps(text))
        return TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config", auth=False)))
    return build


def titles(c):
    return [c.get("/api/track", params={"path": f"Album/0{i}.flac"}).json()["tags"]["title"][0] for i in (1, 2, 3)]


def test_builtin_actions_preview_apply_undo(make):
    with make() as c:
        acts = {a["id"]: a for a in c.get("/api/plugins").json()["actions"]}
        assert {"tidy.clean-titles", "tidy.feat", "tidy.title-case", "tidy.trim"} <= set(acts)
        prev = c.post("/api/actions/tidy.clean-titles/run", json={"folder": "Album"}).json()
        assert prev["changing"] == 1 and titles(c)[0] == "Night Drive (Official Video)"
        c.post("/api/actions/tidy.clean-titles/run", json={"folder": "Album", "dry_run": False})
        c.post("/api/actions/tidy.title-case/run", json={"folder": "Album", "dry_run": False})
        c.post("/api/actions/tidy.feat/run", json={"folder": "Album", "dry_run": False})
        assert titles(c) == ["Night Drive", "Neon Arcade feat. Zayn", "Plain"]
        entry = c.get("/api/activity").json()[0]
        assert entry["message"].startswith("Write features") and entry["can_undo"]
        c.post(f"/api/activity/{entry['id']}/undo")
        assert titles(c)[1] == "Neon Arcade ft. Zayn"


SHOUT = {"plugin.json": {"id": "shout", "name": "Shout", "version": "1.0", "author": "Someone", "api": 1},
         "plugin.py": "def setup(codetta):\n    codetta.add_action(id='up', label='UPPERCASE', fields=['title'],\n"
                      "        run=lambda tags: {'title': [t.upper() for t in tags.get('title', [])]})\n"}


def test_peoples_plugins_are_paused(make, tmp_path):
    """A plugin folder in the config is ignored, even one plugins.json says is on: its code never runs."""
    marker = tmp_path / "imported"
    plugin = dict(SHOUT)
    plugin["plugin.py"] = f"open({str(marker)!r}, 'w').close()\n" + SHOUT["plugin.py"]
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "plugins.json").write_text(json.dumps({"enabled": ["shout"]}))
    with make({"shout": plugin}) as c:
        d = c.get("/api/plugins").json()
        assert [p["id"] for p in d["plugins"]] == ["tidy", "tagtools"] and not marker.exists()  # only the built-ins
        assert c.put("/api/plugins/shout", json={"enabled": True}).status_code == 404
        assert c.post("/api/actions/shout.up/run", json={"folder": "Album"}).status_code == 404
        assert not marker.exists()
        assert c.post("/api/actions/tidy.trim/run", json={"folder": "Album"}).status_code == 200  # built-ins still work


def _write_plugin(root, pid, files):
    d = root / "plugins" / pid
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text if isinstance(text, str) else json.dumps(text))


def test_loader_keeps_outside_plugins_off_until_enabled(tmp_path):
    marker = tmp_path / "imported"
    plugin = dict(SHOUT)
    plugin["plugin.py"] = f"open({str(marker)!r}, 'w').close()\n" + SHOUT["plugin.py"]
    _write_plugin(tmp_path, "shout", plugin)
    pm = PluginManager(tmp_path, outside=True)
    assert pm.plugins["shout"].enabled is False and not marker.exists()  # listed, but its code never ran
    pm.set_enabled("shout", True)
    assert marker.exists() and "shout.up" in pm.actions
    assert pm.run_action("shout.up", {"title": ["plain"]}) == {"title": ["PLAIN"]}
    pm.set_enabled("shout", False)
    assert "shout.up" not in pm.actions
    assert not PluginManager(tmp_path, outside=True).plugins["shout"].enabled  # remembered across restarts


def test_loader_reports_broken_outside_plugins(tmp_path):
    _write_plugin(tmp_path, "broken", {"plugin.json": {"id": "broken"}, "plugin.py": "raise RuntimeError('oops')\n"})
    _write_plugin(tmp_path, "escape", {"plugin.json": {"id": "escape", "entry": "../../evil.py"}})
    pm = PluginManager(tmp_path, outside=True)
    assert "oops" in pm.set_enabled("broken", True).error
    assert pm.set_enabled("escape", True).error
    with pytest.raises(KeyError):
        pm.set_enabled("tidy", False)  # built-ins stay on


def test_plugins_need_sign_in(tmp_path):
    with TestClient(create_app(Settings(music_dir=tmp_path, config_dir=tmp_path / "c"))) as c:
        assert c.get("/api/plugins").status_code == 401
        assert c.post("/api/actions/tidy.trim/run", json={"folder": ""}).status_code == 401
