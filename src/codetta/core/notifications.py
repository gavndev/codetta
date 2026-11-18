"""Notifications: things Codetta did or noticed on its own, in the background.

Things *you* do (save, organize, a MusicBrainz match) already answer with a
toast and land in the activity log. Notifications are for the rest: the inbox
finished looking things up or filed an album by itself, a new version of
Codetta is out, the library index finished its first scan...

Kept in ``notifications.json`` in the config folder (the newest 200).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

KEEP = 200


class Notifications:
    def __init__(self, file: Path) -> None:
        self.file = file
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._next = 1
        try:
            data = json.loads(file.read_text("utf-8"))
            if isinstance(data, list):
                self._items = [n for n in data if isinstance(n, dict) and isinstance(n.get("id"), int)][-KEEP:]
                self._next = max((n["id"] for n in self._items), default=0) + 1
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".notifications-", dir=self.file.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False)
            os.replace(tmp, self.file)
        except OSError:
            pass  # a read-only config folder: notifications still work until restart

    def add(self, kind: str, title: str, body: str = "", action: dict | None = None, key: str | None = None) -> dict | None:
        """Add one. ``key`` makes it once-only (e.g. "update:0.6.0" is never repeated).
        ``action`` tells the page what tapping it does: {"open": "inbox"|"news"|"folder", "path": ...}."""
        with self._lock:
            if key and any(n.get("key") == key for n in self._items):
                return None
            n = {"id": self._next, "time": int(time.time()), "kind": kind, "title": title[:200], "body": body[:1000],
                 "action": action or None, "key": key, "read": False}
            self._next += 1
            self._items.append(n)
            del self._items[:-KEEP]
            self._save()
            return n

    def recent(self, after_id: int = 0, limit: int = 50) -> dict:
        with self._lock:
            items = [n for n in self._items if n["id"] > after_id][-limit:]
            unread = sum(not n["read"] for n in self._items)
            return {"items": list(reversed(items)), "unread": unread, "last_id": self._next - 1}

    def mark_read(self, ids: list[int] | None = None) -> None:
        with self._lock:
            for n in self._items:
                if ids is None or n["id"] in ids:
                    n["read"] = True
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._save()
