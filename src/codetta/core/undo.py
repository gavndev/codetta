"""Undo for changes recorded in the activity log.

Every change Codetta makes is logged with an ``undo`` record holding, per
file, the exact values before and after the change:

    {"type": "tags", "files": {"Artist/Album/01.flac": {"before": {"genre": ["Rock"]},
                                                        "after":  {"genre": ["Jazz"]}}}}
    {"type": "art",  "files": {"Artist/Album/01.flac": {"before": "<sha256 or null>",
                                                        "after":  "<sha256 or null>"}}}

    {"type": "multi", "parts": [<tags record>, <art record>]}   (e.g. a MusicBrainz match)
    {"type": "moves", "moves": [["old/path.flac", "new/path.flac"], ...]}   (Organize)

Album art is too big for the log, so images are kept in an ``ArtStore``
(one file per distinct image, so a cover shared by a whole album is stored
once) and the log only holds their SHA-256.

Undoing only touches files that still have the "after" values. A file that
was edited again since is skipped and reported, so undo never overwrites a
newer change. Undo produces its own undo record (before/after swapped), so
an undo can itself be undone.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from codetta.core.engine import MetadataEngine, MetadataError


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ArtStore:
    """Previous album-art images, stored by content hash in the config folder."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def save(self, data: bytes | None) -> str | None:
        if data is None:
            return None
        digest = sha256(data)
        path = self.directory / digest
        if not path.exists():
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".codetta-", dir=self.directory)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        return digest

    def load(self, digest: str | None) -> bytes | None:
        if digest is None:
            return None
        try:
            return (self.directory / digest).read_bytes()
        except OSError as exc:
            raise MetadataError("The saved album art for this change is no longer available") from exc

    def prune(self, keep: Iterable[str]) -> None:
        """Delete stored images no longer referenced by the activity log."""
        if not self.directory.is_dir():
            return
        keep = set(keep)
        for path in self.directory.iterdir():
            if path.is_file() and not path.name.startswith(".") and path.name not in keep:
                path.unlink(missing_ok=True)


def art_hashes(undo: dict | None) -> set[str]:
    """Image hashes an undo record refers to (for pruning the ArtStore)."""
    if undo and undo.get("type") == "multi":
        return {h for part in undo.get("parts", []) for h in art_hashes(part)}
    if not undo or undo.get("type") != "art":
        return set()
    return {h for f in undo["files"].values() for h in (f.get("before"), f.get("after")) if h}


@dataclass
class UndoResult:
    path: str
    ok: bool
    skipped: bool = False  # changed since; left alone on purpose
    error: str | None = None


@dataclass
class UndoOutcome:
    results: list[UndoResult] = field(default_factory=list)
    reverse: dict | None = None  # undo record for this undo (i.e. redo)


def undo_change(
    engine: MetadataEngine,
    resolve: Callable[[str], Path],
    art: ArtStore,
    record: dict,
) -> UndoOutcome:
    """Put each file in ``record`` back to its "before" state, where safe."""
    kind = record.get("type")
    if kind == "multi":
        return _undo_multi(engine, resolve, art, record)
    if kind == "moves":
        return _undo_moves(resolve, record)
    outcome = UndoOutcome()
    reverse_files: dict[str, dict] = {}

    for rel, change in record.get("files", {}).items():
        try:
            target = resolve(rel)
            if kind == "tags":
                current = engine.load_metadata(target).tags
                if any(current.get(k, []) != v for k, v in change["after"].items()):
                    outcome.results.append(UndoResult(rel, ok=False, skipped=True,
                                                      error="Changed since, so it was left as it is"))
                    continue
                engine.update_tags(target, {k: (v or None) for k, v in change["before"].items()})
                reverse_files[rel] = {"before": change["after"], "after": change["before"]}
            elif kind == "art":
                now = engine.read_artwork(target)
                if (sha256(now.data) if now else None) != change["after"]:
                    outcome.results.append(UndoResult(rel, ok=False, skipped=True,
                                                      error="Album art changed since, so it was left as it is"))
                    continue
                engine.update_artwork(target, art.load(change["before"]))
                reverse_files[rel] = {"before": change["after"], "after": change["before"]}
            else:
                outcome.results.append(UndoResult(rel, ok=False, error="Unknown change type"))
                continue
            outcome.results.append(UndoResult(rel, ok=True))
        except (MetadataError, OSError, ValueError) as exc:
            outcome.results.append(UndoResult(rel, ok=False, error=str(exc)))

    if reverse_files:
        outcome.reverse = {"type": kind, "files": reverse_files}
    return outcome


def _undo_multi(engine: MetadataEngine, resolve: Callable[[str], Path], art: ArtStore, record: dict) -> UndoOutcome:
    """Undo each part (tags, then art) and report one result per file: done if
    any part of it could be put back, skipped if every part changed since."""
    parts = [undo_change(engine, resolve, art, p) for p in record.get("parts", []) if isinstance(p, dict)]
    by_path: dict[str, list[UndoResult]] = {}
    for part in parts:
        for r in part.results:
            by_path.setdefault(r.path, []).append(r)
    outcome = UndoOutcome()
    for path, rs in by_path.items():
        if any(r.ok for r in rs):
            outcome.results.append(UndoResult(path, ok=True))
        else:
            skipped = all(r.skipped for r in rs)
            outcome.results.append(UndoResult(path, ok=False, skipped=skipped, error=next((r.error for r in rs if r.error), None)))
    reverse = [p.reverse for p in parts if p.reverse]
    if reverse:
        outcome.reverse = {"type": "multi", "parts": reverse}
    return outcome


def _undo_moves(resolve: Callable[[str], Path], record: dict) -> UndoOutcome:
    """Move organized files back to where they were."""
    from codetta.core.organize import undo_moves

    moves = [m for m in record.get("moves", []) if isinstance(m, list) and len(m) == 2]
    for src, dst in moves:  # validate every path before touching anything
        resolve(src)
        resolve(dst)
    report, reverse = undo_moves(resolve, moves)
    outcome = UndoOutcome()
    from codetta.core.engine import SUPPORTED_EXTENSIONS

    audio = {src for src, _ in moves if Path(src).suffix.lower() in SUPPORTED_EXTENSIONS}  # report per song
    for src, dst, ok, error in report:
        if src in audio or not ok:
            skipped = not ok and error is not None and "left alone" in error
            outcome.results.append(UndoResult(dst, ok=ok, skipped=skipped, error=error))
    if reverse:
        outcome.reverse = {"type": "moves", "moves": reverse}
    return outcome
