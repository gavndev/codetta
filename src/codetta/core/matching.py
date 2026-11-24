"""How sure Codetta must be before it files or tags an album on its own (the Inbox's automatic
filing and Tidy up), saved in ``matching.json`` in the config folder.

Whatever the level, every track must pair with the release for certain (and a whole album must
have the same number of tracks): that's what stops a song's tags landing on another song. The
level only sets how close the album's overall match score must be. Anything below waits for a
review, and everything Codetta does can be undone in Activity.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

# level -> (lowest score for an album, lowest score for one loose song)
LEVELS = {"strict": (85, 90), "balanced": (75, 85), "relaxed": (65, 80)}
DEFAULT = "strict"


def confident(best: dict, files: list[dict], level: str = DEFAULT) -> bool:
    """Sure enough to write without asking: every track paired for certain, and the release fits
    (a whole album: same number of tracks; one loose song: the song itself) at the level's score."""
    album_min, single_min = LEVELS.get(level, LEVELS[DEFAULT])
    if not files or not all(f.get("track") and f.get("confidence") == "high" for f in files):
        return False
    if best.get("single"):
        return best.get("score", 0) >= single_min
    return best.get("track_count") == len(files) and best.get("score", 0) >= album_min


class MatchingStore:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        self.level = DEFAULT
        try:
            data = json.loads(file.read_text("utf-8"))
            if isinstance(data, dict) and data.get("confidence") in LEVELS:
                self.level = data["confidence"]
        except (OSError, ValueError):
            pass

    def set(self, level: str) -> None:
        if level not in LEVELS:
            raise ValueError(level)
        with self.lock:
            self.level = level
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".matching-", dir=self.file.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"confidence": level}, f)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
