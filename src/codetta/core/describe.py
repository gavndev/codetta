"""What the search index stores about one file, as plain data.

A module-level function (not a closure) so the index can run it in worker
processes when it has thousands of files to read: reading tags is CPU-bound
Python, so processes scale where threads don't (threads were 3x *slower*).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from codetta.core.engine import MetadataEngine

_engine: MetadataEngine | None = None


def describe_file(path: Path, rel: str) -> dict:
    """The track details for ``rel`` (same shape as the API's TrackOut)."""
    global _engine
    if _engine is None:
        _engine = MetadataEngine()
    meta = _engine.load_metadata(path)
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        mtime = None
    art = None
    try:
        a = _engine.read_artwork(path)
        if a is not None:
            art = {"hash": hashlib.sha256(a.data).hexdigest()[:16], "width": a.width, "height": a.height}
    except Exception:  # noqa: BLE001 - a broken picture must not hide the track
        art = None
    return {"path": rel, "name": rel.rsplit("/", 1)[-1], "format": meta.format, "tags": meta.tags,
            "duration": meta.duration, "bitrate": meta.bitrate, "sample_rate": meta.sample_rate,
            "channels": meta.channels, "mtime": mtime, "art": art, "error": None, "partial": False}


def describe_many(root: str, items: list[tuple[str, int, int]]) -> list[tuple[str, int, int, dict]]:
    """Worker-process entry point: describe a chunk of files (rel, mtime_ns, size)."""
    out = []
    for rel, mtime, size in items:
        try:
            track = describe_file(Path(root) / rel, rel)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the scan
            track = {"path": rel, "name": rel.rsplit("/", 1)[-1], "error": str(exc) or type(exc).__name__}
        out.append((rel, mtime, size, track))
    return out


def _worker_main() -> None:
    """``python -m codetta.core.describe``: a helper process for big index scans.

    Reads one JSON job per line on stdin ({"root": ..., "items": [[rel, mtime, size], ...]}) and
    answers with one JSON line of results. A plain subprocess (not multiprocessing), so it never
    re-imports whatever started Codetta, whichever way that was."""
    import json
    import sys
    for line in sys.stdin:
        job = json.loads(line)
        result = describe_many(job["root"], [tuple(i) for i in job["items"]])
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _worker_main()
