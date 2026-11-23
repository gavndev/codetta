"""First-run setup: which steps someone has been through.

Each core feature that needs a choice gets a step. New installs see them all
after creating the account; existing installs see only the steps added since
(once). Steps can always be skipped and changed later.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

STEPS = ("connections", "organize", "library", "inbox", "health", "slskd", "lidarr", "mediaserver", "autoplay")  # in the order they're shown


class OnboardingStore:
    def __init__(self, file: Path) -> None:
        self.file = file
        self._lock = threading.Lock()
        try:
            data = json.loads(file.read_text("utf-8"))
            done = data.get("done") if isinstance(data, dict) else None
            self.done = {s for s in done if s in STEPS} if isinstance(done, list) else set()
        except (OSError, ValueError):
            self.done = set()

    def mark(self, step: str) -> None:
        if step not in STEPS:
            raise ValueError(f"Unknown step: {step}")
        with self._lock:
            self.done.add(step)
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".onboarding-", dir=self.file.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"done": sorted(self.done)}, f)
            os.replace(tmp, self.file)
