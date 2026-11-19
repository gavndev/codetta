"""Loading plugins: Codetta's built-in ones, and the ones people put in <config>/plugins/.

A plugin folder holds ``plugin.json``::

    {"id": "my-plugin", "name": "My plugin", "version": "1.0", "description": "...",
     "author": "...", "url": "https://...", "entry": "plugin.py", "api": 1}

Folders are listed always, but their code is imported only once enabled (plugins.json in
the config folder). A plugin that fails to load is reported, never fatal.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import re
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from codetta.plugins import API_VERSION, Action, PluginAPI
from codetta.plugins.builtin import BUILTIN

log = logging.getLogger("codetta")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


@dataclass
class PluginInfo:
    id: str
    name: str
    version: str = ""
    description: str = ""
    author: str = ""
    url: str = ""
    builtin: bool = False
    enabled: bool = False
    error: str = ""
    path: Path | None = None
    entry: str = "plugin.py"
    actions: list[str] = field(default_factory=list)

    def public(self) -> dict:
        url = self.url if self.url.startswith(("https://", "http://")) else ""
        return {"id": self.id, "name": self.name, "version": self.version, "description": self.description,
                "author": self.author, "url": url, "builtin": self.builtin, "enabled": self.enabled,
                "error": self.error, "actions": self.actions}


class PluginManager:
    def __init__(self, config_dir: Path) -> None:
        self.dir = config_dir / "plugins"
        self.state_file = config_dir / "plugins.json"
        self.lock = threading.RLock()
        self.plugins: dict[str, PluginInfo] = {}
        self.actions: dict[str, Action] = {}
        self.enabled: set[str] = self._load_state()
        self.reload()

    def _load_state(self) -> set[str]:
        try:
            data = json.loads(self.state_file.read_text("utf-8"))
            return {i for i in data.get("enabled", []) if isinstance(i, str)}
        except (OSError, ValueError, AttributeError):
            return set()

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".plugins-", dir=self.state_file.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"enabled": sorted(self.enabled)}, f)
        os.replace(tmp, self.state_file)

    def _register(self, info: PluginInfo, action: Action) -> None:
        self.actions[action.id] = action
        info.actions.append(action.id)

    def _setup(self, info: PluginInfo, module) -> None:
        setup = getattr(module, "setup", None)
        if not callable(setup):
            raise RuntimeError("it has no setup(codetta) function")
        setup(PluginAPI(info.id, lambda a: self._register(info, a)))

    def reload(self) -> None:
        """Rebuild the list (and import enabled plugins). Safe to call any time."""
        with self.lock:
            self.plugins, self.actions = {}, {}
            for name in BUILTIN:  # built-ins: always on, they're part of Codetta
                info = PluginInfo(id=name, name=name.title(), builtin=True, enabled=True)
                try:
                    module = importlib.import_module(f"codetta.plugins.builtin.{name}")
                    info.name = getattr(module, "NAME", "Tidy-up actions" if name == "tidy" else name)
                    info.description = (module.__doc__ or "").strip().splitlines()[0] if module.__doc__ else ""
                    self._setup(info, module)
                except Exception as exc:  # noqa: BLE001 - never let a plugin stop Codetta
                    info.error = f"{type(exc).__name__}: {exc}"
                self.plugins[info.id] = info
            for folder in sorted(self.dir.iterdir()) if self.dir.is_dir() else []:
                self._discover(folder)

    def _discover(self, folder: Path) -> None:
        manifest = folder / "plugin.json"
        if not folder.is_dir() or not manifest.is_file():
            return
        try:
            meta = json.loads(manifest.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            self.plugins[folder.name] = PluginInfo(id=folder.name, name=folder.name, error=f"plugin.json can't be read: {exc}")
            return
        pid = str(meta.get("id") or folder.name)
        if not ID_RE.match(pid) or pid in self.plugins:
            self.plugins.setdefault(folder.name, PluginInfo(id=folder.name, name=folder.name,
                                                            error=f"The id {pid!r} isn't valid or is taken"))
            return
        info = PluginInfo(id=pid, name=str(meta.get("name") or pid)[:60], version=str(meta.get("version") or "")[:20],
                          description=str(meta.get("description") or "")[:300], author=str(meta.get("author") or "")[:80],
                          url=str(meta.get("url") or "")[:300], path=folder, entry=str(meta.get("entry") or "plugin.py"),
                          enabled=pid in self.enabled)
        self.plugins[pid] = info
        if int(meta.get("api") or 1) > API_VERSION:
            info.error = f"It needs a newer Codetta (plugin API {meta.get('api')})."
            return
        if info.enabled:
            self._import(info)

    def _import(self, info: PluginInfo) -> None:
        entry = (info.path / info.entry).resolve()
        if info.path.resolve() not in entry.parents or not entry.is_file():
            info.error = f"{info.entry} isn't in the plugin's folder"
            return
        try:
            name = f"codetta_plugin_{info.id.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(name, entry)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            self._setup(info, module)
            log.info("Plugin loaded: %s %s", info.name, info.version)
        except Exception as exc:  # noqa: BLE001
            info.error = f"{type(exc).__name__}: {exc}"
            for aid in info.actions:
                self.actions.pop(aid, None)
            info.actions = []
            log.warning("Plugin %s couldn't load: %s", info.id, info.error)

    def set_enabled(self, pid: str, on: bool) -> PluginInfo:
        with self.lock:
            info = self.plugins.get(pid)
            if info is None or info.builtin:
                raise KeyError(pid)
            (self.enabled.add if on else self.enabled.discard)(pid)
            self._save_state()
            self.reload()
            return self.plugins[pid]

    def run_action(self, action_id: str, tags: dict[str, list[str]]) -> dict:
        """The changes an action wants for one track (only real changes, values as lists)."""
        action = self.actions[action_id]
        try:
            result = action.run({k: list(v) for k, v in tags.items()})
        except Exception as exc:  # noqa: BLE001 - a plugin bug is reported, never crashes Codetta
            raise ActionError(f"{action.label} failed: {type(exc).__name__}: {exc}") from exc
        if not result:
            return {}
        if not isinstance(result, dict):
            raise ActionError(f"{action.label} returned something that isn't a set of tags")
        changes = {}
        for key, value in result.items():
            key = str(key).lower()
            new = [] if value is None else [value] if isinstance(value, str) else [str(v) for v in value]
            new = [v for v in new if v.strip()]
            if new != [v for v in tags.get(key, []) if v.strip()]:
                changes[key] = new or None
        return changes


class ActionError(Exception):
    pass
