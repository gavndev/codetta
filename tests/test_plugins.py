"""Plugins: built-in actions, people's plugins (off until enabled), and plugins that misbehave."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
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


def test_plugins_stay_off_until_enabled(make, tmp_path):
    marker = tmp_path / "imported"
    plugin = dict(SHOUT)
    plugin["plugin.py"] = f"open({str(marker)!r}, 'w').close()\n" + SHOUT["plugin.py"]
    with make({"shout": plugin}) as c:
        listed = {p["id"]: p for p in c.get("/api/plugins").json()["plugins"]}
        assert listed["shout"]["enabled"] is False and not marker.exists()  # listed, but its code never ran
        assert c.post("/api/actions/shout.up/run", json={"folder": "Album"}).status_code == 404
        on = c.put("/api/plugins/shout", json={"enabled": True}).json()
        assert marker.exists() and "shout.up" in {a["id"] for a in on["actions"]}
        c.post("/api/actions/shout.up/run", json={"folder": "Album", "dry_run": False})
        assert titles(c)[2] == "PLAIN"
        off = c.put("/api/plugins/shout", json={"enabled": False}).json()
        assert "shout.up" not in {a["id"] for a in off["actions"]}
    with make() as c:  # remembered across restarts
        assert not {p["id"]: p for p in c.get("/api/plugins").json()["plugins"]}["shout"]["enabled"]


def test_broken_plugins_are_reported_not_fatal(make):
    bad = {"plugin.json": {"id": "broken"}, "plugin.py": "raise RuntimeError('oops')\n"}
    escape = {"plugin.json": {"id": "escape", "entry": "../../evil.py"}}
    buggy = {"plugin.json": {"id": "buggy"}, "plugin.py": "def setup(c):\n    c.add_action(id='x', label='X', run=lambda t: 1/0)\n"}
    with make({"broken": bad, "escape": escape, "buggy": buggy}) as c:
        r = c.put("/api/plugins/broken", json={"enabled": True})
        assert r.status_code == 422 and "oops" in r.json()["detail"]
        assert c.put("/api/plugins/escape", json={"enabled": True}).status_code == 422
        c.put("/api/plugins/buggy", json={"enabled": True})
        r = c.post("/api/actions/buggy.x/run", json={"folder": "Album"})
        assert r.status_code == 422 and "ZeroDivisionError" in r.json()["detail"]
        assert c.get("/api/browse", params={"path": "Album"}).status_code == 200  # Codetta carries on
        assert c.put("/api/plugins/tidy", json={"enabled": False}).status_code == 404  # built-ins stay on


def test_plugins_need_sign_in(tmp_path):
    with TestClient(create_app(Settings(music_dir=tmp_path, config_dir=tmp_path / "c"))) as c:
        assert c.get("/api/plugins").status_code == 401
        assert c.post("/api/actions/tidy.trim/run", json={"folder": ""}).status_code == 401
