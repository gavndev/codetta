"""The API, one module per area. Each module has ``register(app, shared)``, called once
from ``codetta.web.app.create_app``.

``shared`` holds what the areas share: the stores and helpers made at startup, and what
each area shares with the ones after it (``shared.share(...)``). An area that needs a
function from an area registered after it asks for ``shared.later("name")``, which looks
the function up when it's called."""
from __future__ import annotations

from types import SimpleNamespace


class Shared(SimpleNamespace):
    def share(self, **names) -> None:
        for name, value in names.items():
            if hasattr(self, name):
                raise RuntimeError(f"{name} is already shared by another area")
            setattr(self, name, value)

    def later(self, name: str):
        def call(*args, **kwargs):
            return getattr(self, name)(*args, **kwargs)
        call.__name__ = name
        return call
