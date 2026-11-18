"""Import inbox: a folder where new music lands (downloads, rips) before it
joins the library.

Codetta groups what's in it into albums, finds each album on MusicBrainz
(by its tags, or by sound when AcoustID is on), and either files it straight
away (confident matches, if the user allows it) or waits for a review.
"Filing" an album = writing the MusicBrainz tags + organizing it into the
library with the saved pattern, each an ordinary undoable activity entry.

This module only knows about groups and their state; the matching and filing
use the same code as "Find in MusicBrainz" and "Organize" (see web/app.py).
State lives in ``inbox.json`` in the config folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from codetta.core.library import Library

# Statuses an album in the inbox can have.
DOWNLOADING = "downloading"  # files changed moments ago (still arriving): wait before looking it up
WAITING = "waiting"  # found, not looked up yet
MATCHING = "matching"
READY = "ready"  # confident match: can be filed in one tap (or automatically)
REVIEW = "review"  # a match that needs a look
NO_MATCH = "nomatch"
LOCAL = "local"  # online lookups are off: file it by its own tags
FILED = "filed"
SKIPPED = "skipped"
ERROR = "error"

DISC_FOLDER = re.compile(r"^(cd|disc|disk)[\s_.-]*\d+\b", re.IGNORECASE)
MAX_GROUPS = 500
MAX_SCAN_FOLDERS = 5000  # one look at the inbox never walks more folders than this (e.g. a symlink to "/")
SETTLE_SECONDS = 120  # an album is looked up once its files have been still this long


@dataclass
class InboxSettings:
    folder: str = ""  # relative to the music folder; "" = not set up
    auto: bool = False  # file confident matches without asking
    organize: bool = True  # move filed albums into the library with the Organize pattern
    watch: bool = False  # check the inbox every 15 minutes (off: only when you open it)


@dataclass
class Group:
    key: str  # the album's folder (relative to the music folder)
    paths: list[str]
    signature: str  # changes when files are added, removed or modified
    status: str = WAITING
    title: str = ""  # best guess from tags or the match
    artist: str = ""
    release: dict | None = None  # summary of the chosen MusicBrainz release
    score: int | None = None
    recordings: dict[str, list[str]] = field(default_factory=dict)  # from Identify by sound
    note: str = ""
    dest: str = ""  # where it was filed (a library folder)
    source: str = ""  # the Soulseek job that brought it ("" = it just appeared)
    upgrade: str = ""  # a library folder it replaces when filed (Find in slskd on an album)
    updated: float = 0.0


def find_groups(library: Library, inbox: str, limit: int = MAX_GROUPS) -> list[tuple[str, list[str]]]:
    """Albums in the inbox: each folder that holds audio files is one album,
    except disc folders ("CD1", "Disc 2"), which join their parent. Loose
    files right in the inbox are one item each."""
    groups: dict[str, list[str]] = {}
    pending = [inbox]
    seen = 0
    while pending and len(groups) <= limit and seen < MAX_SCAN_FOLDERS:
        listing = library.list_folder(pending.pop(0))
        seen += 1
        if listing.files and listing.path == inbox:
            for rel in listing.files:  # loose tracks: usually unrelated singles, so one item each
                groups[rel] = [rel]
        elif listing.files:
            name = listing.path.rsplit("/", 1)[-1]
            parent = listing.path.rsplit("/", 1)[0] if "/" in listing.path else ""
            key = parent if DISC_FOLDER.match(name) and listing.path != inbox and parent else listing.path
            groups.setdefault(key, []).extend(listing.files)
        pending.extend(listing.folders)
    return sorted(groups.items())[:limit]


def signature(library: Library, paths: list[str]) -> tuple[str, float]:
    """(fingerprint of names, sizes and times; when the newest file last changed)."""
    h = hashlib.sha256()
    newest = 0.0
    for rel in sorted(paths):
        try:
            st = library.resolve(rel).stat()
            h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
            # ctime too: a downloader that moves a finished file in keeps its old mtime.
            newest = max(newest, st.st_mtime, st.st_ctime)
        except OSError:
            h.update(f"{rel}\0missing\n".encode())
    return h.hexdigest()[:16], newest


class InboxStore:
    """Settings and per-album state, saved to inbox.json."""

    def __init__(self, file: Path, settle_seconds: float = SETTLE_SECONDS) -> None:
        self.file = file
        self.settle_seconds = settle_seconds
        self.lock = threading.RLock()
        self.settings = InboxSettings()
        self.groups: dict[str, Group] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.file.read_text("utf-8"))
        except (OSError, ValueError):
            return
        s = data.get("settings") if isinstance(data, dict) else None
        if isinstance(s, dict):
            self.settings = InboxSettings(
                folder=str(s.get("folder") or ""), auto=bool(s.get("auto")),
                organize=s.get("organize") is not False, watch=bool(s.get("watch")),
            )
        for g in (data.get("groups") or {}).values() if isinstance(data, dict) else []:
            try:
                group = Group(**{k: v for k, v in g.items() if k in Group.__dataclass_fields__})
            except TypeError:
                continue
            if group.status == MATCHING:
                group.status = WAITING  # interrupted by a restart
            self.groups[group.key] = group

    def save(self) -> None:
        with self.lock:
            data = {"settings": asdict(self.settings), "groups": {k: asdict(g) for k, g in self.groups.items()}}
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".inbox-", dir=self.file.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise

    def sync(self, library: Library) -> list[Group]:
        """Re-read the inbox folder: new albums appear, changed ones are looked
        up again, albums that left the inbox are forgotten (unless filed)."""
        with self.lock:
            inbox = self.settings.folder
            if not inbox or not library.resolve(inbox).is_dir():
                return []
            found = find_groups(library, inbox)
            keys = set()
            now = time.time()
            for key, paths in found:
                keys.add(key)
                sig, newest = signature(library, paths)
                settled = now - newest >= self.settle_seconds
                g = self.groups.get(key)
                if g is None or (g.signature != sig and g.status not in (SKIPPED, FILED)):
                    self.groups[key] = Group(key=key, paths=paths, signature=sig, updated=now,
                                             status=WAITING if settled else DOWNLOADING,
                                             note="" if settled else "Still arriving: waiting for the download to finish")
                else:
                    g.paths = paths
                    if g.status == DOWNLOADING and settled:
                        g.status, g.note = WAITING, ""
            for key in [k for k, g in self.groups.items() if k not in keys and g.status != FILED]:
                del self.groups[key]
            # Filed albums are kept for a while so the list can say where they went.
            filed = sorted((g for g in self.groups.values() if g.status == FILED), key=lambda g: -g.updated)
            for g in filed[50:]:
                del self.groups[g.key]
            self.save()
            return list(self.groups.values())

    def update(self, key: str, **changes) -> Group | None:
        with self.lock:
            g = self.groups.get(key)
            if g is None:
                return None
            for k, v in changes.items():
                setattr(g, k, v)
            g.updated = time.time()
            self.save()
            return g
