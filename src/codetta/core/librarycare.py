"""Library care: Codetta looking after the music already in your library, gradually.

Chosen once in setup (and changeable any time):

* ``off``: leave files as they are (the default for existing libraries).
* ``tags``: match each album online and write its tags. File names and folders stay.
* ``full``: tags, then file names and folders with your Organize pattern.

A background worker goes through the album folders one at a time, gently (online lookups are rate
limited). Only confident matches are applied; the rest are listed as "needs a look". Files are only
renamed after a confident match (or when the album was matched before), never from guesswork. Every
album is its own undoable change in Activity. This module keeps the choice and the progress.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

MODES = ("off", "tags", "full")
# Album outcomes.
TAGGED = "tagged"  # matched and tagged
ORGANIZED = "organized"  # tagged (or already matched) and moved into place
REVIEW = "review"  # no confident match: needs a look
SKIPPED = "skipped"  # nothing to do (already matched, nothing to rename)
ERROR = "error"
MAX_REVIEW_SHOWN = 500


class LibraryCareStore:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.RLock()
        self.mode = "off"
        self.paused = False
        self.albums: dict[str, dict] = {}  # folder -> {"status", "note", "at", "title"}
        try:
            data = json.loads(file.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            self.mode = data.get("mode") if data.get("mode") in MODES else "off"
            self.paused = bool(data.get("paused"))
            albums = data.get("albums")
            self.albums = {k: v for k, v in albums.items() if isinstance(v, dict)} if isinstance(albums, dict) else {}

    def save(self) -> None:
        with self.lock:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".library-care-", dir=self.file.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"mode": self.mode, "paused": self.paused, "albums": self.albums}, f, ensure_ascii=False)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise

    def set(self, mode: str | None = None, paused: bool | None = None) -> None:
        with self.lock:
            if mode is not None:
                if mode not in MODES:
                    raise ValueError(f"Unknown mode: {mode}")
                if mode != self.mode:
                    # A new choice starts over (a "tags" pass doesn't count as "full"), but albums that
                    # needed a look keep their note until they're looked at again.
                    self.albums = {k: v for k, v in self.albums.items() if v.get("status") == REVIEW}
                self.mode = mode
            if paused is not None:
                self.paused = paused
            self.save()

    def record(self, folder: str, status: str, note: str = "", title: str = "") -> None:
        with self.lock:
            self.albums[folder] = {"status": status, "note": note, "title": title, "at": int(time.time())}
            self.save()

    def forget(self, folder: str) -> None:
        with self.lock:
            self.albums.pop(folder, None)
            self.save()

    def summary(self, total: int) -> dict:
        with self.lock:
            counts = {s: 0 for s in (TAGGED, ORGANIZED, REVIEW, SKIPPED, ERROR)}
            for v in self.albums.values():
                if v.get("status") in counts:
                    counts[v["status"]] += 1
            review = sorted(((k, v) for k, v in self.albums.items() if v.get("status") in (REVIEW, ERROR)),
                            key=lambda kv: kv[0])[:MAX_REVIEW_SHOWN]
            return {"mode": self.mode, "paused": self.paused, "total": total, "done": len(self.albums), "counts": counts,
                    "review": [{"folder": k, "status": v["status"], "note": v.get("note", ""), "title": v.get("title", "")}
                               for k, v in review]}
