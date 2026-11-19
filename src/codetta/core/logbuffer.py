"""The server log, for Advanced mode's live log view: Codetta's own log lines (what `docker logs`
shows), kept in memory only. Nothing is written to disk, and the page only ever gets them through
a signed-in, private route.

Kept out on purpose: per-request access lines (Codetta keeps no record of who visits; they're off
anyway) and anything that looks like a secret (tokens, keys, passwords), which is masked even
though Codetta never logs them.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import deque

MAX_LINES = 500
MAX_LINE_CHARS = 2000

# key=value / key: value pairs whose value must never be shown, and bearer tokens.
_SECRET = re.compile(r"(?i)\b(api[_-]?key|token|password|passwd|secret|session|cookie|authorization)(\s*[=:]\s*)(\S+)")
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")


def redact(text: str) -> str:
    text = _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}•••", text)
    return _BEARER.sub("Bearer •••", text)


class LogBuffer(logging.Handler):
    """The last ``MAX_LINES`` log lines, each with an increasing id the page polls from."""

    def __init__(self, capacity: int = MAX_LINES) -> None:
        super().__init__(level=logging.INFO)
        self.lines: deque[dict] = deque(maxlen=capacity)
        self._next = 1
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("uvicorn.access"):
            return  # never a record of who visited
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + "".join(logging.Formatter().formatException(record.exc_info).splitlines(True)[-6:])
        except Exception:  # noqa: BLE001 - a bad log call must never break the app
            return
        line = {"time": record.created, "level": record.levelname.lower(), "source": record.name,
                "message": redact(message)[:MAX_LINE_CHARS]}
        with self._lock:
            line["id"] = self._next
            self._next += 1
            self.lines.append(line)

    def since(self, after: int = 0) -> list[dict]:
        with self._lock:
            return [line for line in self.lines if line["id"] > after]


_shared: LogBuffer | None = None
_shared_lock = threading.Lock()


def shared_buffer() -> LogBuffer:
    """One buffer per process, collecting Codetta's and the web server's log lines. "uvicorn" is
    the parent of "uvicorn.error" (and "uvicorn.access", dropped above), so each line arrives once."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = LogBuffer()
            for name in ("codetta", "uvicorn"):
                logging.getLogger(name).addHandler(_shared)
        return _shared
