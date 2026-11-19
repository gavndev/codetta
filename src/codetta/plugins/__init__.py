"""Codetta's plugin API. See docs/plugins.md for the full guide.

A plugin is a folder in ``<config>/plugins/<id>/`` with a ``plugin.json`` and a Python
file. Codetta imports it only after you enable it (Account -> Plugins) and calls its
``setup(codetta)`` with a :class:`PluginAPI`::

    # plugin.py
    def setup(codetta):
        codetta.add_action(
            id="shout", label="UPPERCASE titles",
            description="Make every title upper case.",
            fields=["title"],
            run=lambda tags: {"title": [t.upper() for t in tags.get("title", [])]},
        )

An *action* is a batch change to tags: Codetta calls ``run(tags)`` for each chosen track
(``tags`` maps lower-case tag names to lists of strings) and ``run`` returns the tags it
wants changed (a value of ``None`` or ``[]`` removes that tag; anything not returned is
left alone). Codetta shows a preview, writes with its usual safe writes, and logs one
undoable activity entry. ``run`` must not touch files itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

API_VERSION = 1  # bumped only when a change would break existing plugins

TagChanges = dict[str, "list[str] | str | None"]


@dataclass(frozen=True)
class Action:
    id: str  # "<plugin id>.<action id>"
    label: str
    description: str
    run: Callable[[dict[str, list[str]]], TagChanges | None]
    plugin: str
    fields: tuple[str, ...] = field(default_factory=tuple)  # the tags it reads/changes (shown to people)


class PluginError(Exception):
    """A plugin did something it shouldn't (a bad id, a duplicate...)."""


class PluginAPI:
    """What a plugin's ``setup`` receives. Only add things here in backwards-compatible ways."""

    api_version = API_VERSION

    def __init__(self, plugin_id: str, register: Callable[[Action], None]) -> None:
        self.plugin_id = plugin_id
        self._register = register

    def add_action(self, *, id: str, label: str, run: Callable, description: str = "",  # noqa: A002
                   fields: list[str] | tuple[str, ...] = ()) -> None:
        if not id or not id.replace("-", "").replace("_", "").isalnum() or len(id) > 40:
            raise PluginError(f"Action id {id!r}: use letters, numbers, - and _ (up to 40)")
        if not callable(run):
            raise PluginError(f"Action {id!r}: run must be a function")
        self._register(Action(f"{self.plugin_id}.{id}", str(label)[:60], str(description)[:300], run, self.plugin_id,
                              tuple(str(f).lower() for f in fields)))
