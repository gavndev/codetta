"""Activity log: a record of every change Codetta makes to your files.

Entries are kept in memory for the UI and appended to ``activity.jsonl`` in
the config folder (one JSON object per line), so the history survives
restarts and you can always check what Codetta did to your library.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_FILES_PER_ENTRY = 50  # keep entries readable for huge batch edits


class ActivityLog:
    def __init__(self, file: Path | None = None, keep: int = 1000) -> None:
        self.file = file
        self.keep = keep
        self._entries: deque[dict[str, Any]] = deque(maxlen=keep)
        self._lock = threading.Lock()
        self._next_id = 1
        self._lines_in_file = 0
        self._load()

    def add(
        self,
        kind: str,
        message: str,
        *,
        ok: bool = True,
        files: list[str] | None = None,
        changes: list[dict[str, str]] | None = None,
        errors: list[dict[str, str]] | None = None,
        undo: dict | None = None,
        undoes: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record one action. ``kind`` is "edit", "art", "loadout" or "undo".

        ``undo`` holds what's needed to reverse it (see codetta.core.undo);
        ``undoes`` is the id of the entry this one reversed.
        """
        files = files or []
        with self._lock:
            entry = {
                "id": self._next_id,
                "time": datetime.now(UTC).isoformat(timespec="seconds"),
                "kind": kind,
                "ok": ok,
                "message": message,
                "files": files[:MAX_FILES_PER_ENTRY],
                "file_count": len(files),
                "changes": changes or [],
                "errors": (errors or [])[:MAX_FILES_PER_ENTRY],
            }
            if undo:
                entry["undo"] = undo
            if undoes is not None:
                entry["undoes"] = undoes
            if extra:
                entry.update(extra)
            self._next_id += 1
            self._entries.append(entry)
            self._append_to_file(entry)
        return self._public(entry, self._undone_ids())

    def recent(self, limit: int = 50, after_id: int = 0) -> list[dict[str, Any]]:
        """Newest first, without the (possibly large) undo records.

        Each entry gets ``can_undo`` and ``undone``. ``after_id`` returns only
        entries newer than that id.
        """
        with self._lock:
            undone = self._undone_ids()
            entries = [self._public(e, undone) for e in self._entries if e["id"] > after_id]
        return list(reversed(entries))[:limit]

    def get(self, entry_id: int) -> dict[str, Any] | None:
        """The full entry, including its undo record."""
        with self._lock:
            for e in self._entries:
                if e["id"] == entry_id:
                    return dict(e)
        return None

    def is_undone(self, entry_id: int) -> bool:
        with self._lock:
            return entry_id in self._undone_ids()

    def undo_records(self) -> list[dict]:
        with self._lock:
            return [e["undo"] for e in self._entries if e.get("undo")]

    def _undone_ids(self) -> set[int]:
        """Entries currently undone. Undoing an undo (redo) re-activates the original."""
        undone: set[int] = set()
        # Newest first: a later undo decides the fate of everything before it.
        for e in sorted(self._entries, key=lambda x: x["id"], reverse=True):
            target = e.get("undoes")
            if target is not None and e["id"] not in undone:
                undone.add(target)
        return undone

    @staticmethod
    def _public(entry: dict[str, Any], undone: set[int]) -> dict[str, Any]:
        out = {k: v for k, v in entry.items() if k != "undo"}
        out["undone"] = entry["id"] in undone
        out["can_undo"] = bool(entry.get("undo")) and not out["undone"]
        return out

    # --- Persistence ---------------------------------------------------------------

    def _load(self) -> None:
        if not self.file or not self.file.is_file():
            return
        try:
            lines = self.file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:  # the deque keeps only the newest ``keep`` entries
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # a half-written line from a crash: skip it
            if isinstance(entry, dict) and isinstance(entry.get("id"), int):
                self._entries.append(entry)
        if self._entries:
            self._next_id = max(e["id"] for e in self._entries) + 1
        self._lines_in_file = len(lines)
        if len(lines) > self.keep * 2:
            self._rewrite()  # keep the file from growing forever

    def _append_to_file(self, entry: dict[str, Any]) -> None:
        if not self.file:
            return
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._lines_in_file += 1
            if self._lines_in_file > self.keep * 2:
                self._rewrite()  # trim while running, not only at the next restart
        except OSError:
            pass  # logging must never break an edit

    def _rewrite(self) -> None:
        try:
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(
                "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self._entries),
                encoding="utf-8",
            )
            tmp.replace(self.file)
            self._lines_in_file = len(self._entries)
        except OSError:
            pass
