"""What you do with your music in apps: stars, ratings, play counts, playlists, the play queue
and bookmarks. Kept in ``listening.sqlite3`` in the config folder (never in the music folder).

Songs are remembered by their path in the library. When Codetta moves a file (Organize, the
inbox, Move to, Rename, or undoing any of those), :meth:`Listening.move` carries everything
over; a song moved some other way is found again by its title, artist, album and length
(:meth:`Listening.relink`) when that matches exactly one song. Albums and artists are
remembered by the IDs the music-app API gives them, which come from their tags.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS marks (
    kind TEXT NOT NULL, key TEXT NOT NULL,          -- "s" song (path), "a" album / "r" artist (API id)
    starred REAL, rating INTEGER, plays INTEGER NOT NULL DEFAULT 0, last_played REAL,
    fp TEXT NOT NULL DEFAULT '',                    -- a song's fingerprint, to find it again after a move
    PRIMARY KEY (kind, key)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '',
    public INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, changed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS playlist_entries (
    playlist INTEGER NOT NULL, pos INTEGER NOT NULL, path TEXT NOT NULL,
    PRIMARY KEY (playlist, pos)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY CHECK (id = 1), entries TEXT NOT NULL, current INTEGER, position INTEGER NOT NULL DEFAULT 0,
    changed REAL NOT NULL, client TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS bookmarks (
    path TEXT PRIMARY KEY, position INTEGER NOT NULL, comment TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL, changed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS clients (name TEXT PRIMARY KEY, last_seen REAL NOT NULL);
"""
MAX_PLAYLIST = 10_000
MAX_QUEUE = 5_000


@dataclass
class Mark:
    starred: float | None = None
    rating: int | None = None
    plays: int = 0
    last_played: float | None = None


@dataclass
class Playlist:
    id: int
    name: str
    comment: str
    public: bool
    created: float
    changed: float
    paths: list[str]


class Listening:
    def __init__(self, file: Path | None) -> None:
        self.file = file
        if file is not None:
            file.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(file) if file else ":memory:", check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self.version = 0  # bumps on every change (callers cache snapshots by it)
        self._snapshot: tuple[int, dict] | None = None
        self.now_playing: dict[str, tuple[str, float]] = {}  # client -> (path, since)

    def _write(self, sql: str, args: Iterable = ()) -> None:
        with self._lock:
            self.db.execute(sql, tuple(args))
            self.version += 1

    # --- Stars, ratings, plays ----------------------------------------------------------------

    def star(self, kind: str, keys: Iterable[str], on: bool = True, fps: dict[str, str] | None = None) -> None:
        now = time.time() if on else None
        with self._lock:
            for key in keys:
                self.db.execute("INSERT INTO marks (kind, key, starred, fp) VALUES (?, ?, ?, ?) "
                                "ON CONFLICT(kind, key) DO UPDATE SET starred = excluded.starred",
                                (kind, key, now, (fps or {}).get(key, "")))
            self.version += 1

    def rate(self, kind: str, key: str, rating: int, fp: str = "") -> None:
        value = rating if 1 <= rating <= 5 else None
        self._write("INSERT INTO marks (kind, key, rating, fp) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(kind, key) DO UPDATE SET rating = excluded.rating", (kind, key, value, fp))

    def played(self, path: str, when: float | None = None, fp: str = "", also: Iterable[tuple[str, str]] = ()) -> None:
        """One play of the song at ``path`` (and of its album and artist, given as (kind, id) in ``also``)."""
        when = when or time.time()
        with self._lock:
            for kind, key, f in [("s", path, fp), *[(k, i, "") for k, i in also]]:
                self.db.execute("INSERT INTO marks (kind, key, plays, last_played, fp) VALUES (?, ?, 1, ?, ?) "
                                "ON CONFLICT(kind, key) DO UPDATE SET plays = plays + 1, "
                                "last_played = MAX(COALESCE(last_played, 0), excluded.last_played)", (kind, key, when, f))
            self.version += 1

    def marks(self) -> dict[str, dict[str, Mark]]:
        """Every mark by kind: {"s": {path: Mark}, "a": {...}, "r": {...}} (cached until something changes)."""
        with self._lock:
            if self._snapshot and self._snapshot[0] == self.version:
                return self._snapshot[1]
            out: dict[str, dict[str, Mark]] = {"s": {}, "a": {}, "r": {}}
            for kind, key, starred, rating, plays, last in self.db.execute(
                    "SELECT kind, key, starred, rating, plays, last_played FROM marks"):
                out.setdefault(kind, {})[key] = Mark(starred, rating, plays or 0, last)
            self._snapshot = (self.version, out)
            return out

    # --- Following songs that move --------------------------------------------------------------

    def move(self, pairs: Iterable[tuple[str, str]]) -> None:
        """Files moved from old to new path: their stars, plays, playlist places, queue and bookmarks follow."""
        pairs = [(a, b) for a, b in pairs if a and b and a != b]
        if not pairs:
            return
        with self._lock:
            for old, new in pairs:
                # Both have history (a song played under both names): add them together, never lose either.
                self.db.execute(
                    "UPDATE marks SET plays = plays + (SELECT plays FROM marks WHERE kind = 's' AND key = ?), "
                    "starred = COALESCE(starred, (SELECT starred FROM marks WHERE kind = 's' AND key = ?)), "
                    "rating = COALESCE(rating, (SELECT rating FROM marks WHERE kind = 's' AND key = ?)), "
                    "last_played = MAX(COALESCE(last_played, 0), COALESCE((SELECT last_played FROM marks WHERE kind = 's' AND key = ?), 0)) "
                    "WHERE kind = 's' AND key = ? AND EXISTS (SELECT 1 FROM marks WHERE kind = 's' AND key = ?)",
                    (old, old, old, old, new, old))
                self.db.execute("DELETE FROM marks WHERE kind = 's' AND key = ? AND EXISTS "
                                "(SELECT 1 FROM marks WHERE kind = 's' AND key = ?)", (old, new))
                self.db.execute("UPDATE marks SET key = ? WHERE kind = 's' AND key = ?", (new, old))
                self.db.execute("UPDATE playlist_entries SET path = ? WHERE path = ?", (new, old))
                self.db.execute("DELETE FROM bookmarks WHERE path = ? AND EXISTS (SELECT 1 FROM bookmarks WHERE path = ?)", (new, old))
                self.db.execute("UPDATE bookmarks SET path = ? WHERE path = ?", (new, old))
            row = self.db.execute("SELECT entries FROM queue WHERE id = 1").fetchone()
            if row:
                moved = dict(pairs)
                entries = [moved.get(p, p) for p in json.loads(row[0])]
                self.db.execute("UPDATE queue SET entries = ? WHERE id = 1", (json.dumps(entries),))
            self.version += 1

    def relink(self, known: set[str], by_fp: dict[str, str], gone=lambda path: True) -> int:
        """Song marks whose file is really gone (``gone(path)``) are moved to the one song with the same
        fingerprint, merging with any history it already has. Returns how many."""
        with self._lock:
            lost = [(k, fp) for k, fp in self.db.execute("SELECT key, fp FROM marks WHERE kind = 's' AND fp != ''")
                    if k not in known and gone(k)]
        pairs = [(k, by_fp[fp]) for k, fp in lost if fp in by_fp]
        self.move(pairs)
        return len(pairs)

    # --- Playlists -------------------------------------------------------------------------------

    def playlists(self) -> list[Playlist]:
        with self._lock:
            rows = self.db.execute("SELECT id, name, comment, public, created, changed FROM playlists ORDER BY name COLLATE NOCASE").fetchall()
            return [self._playlist(r) for r in rows]

    def playlist(self, pid: int) -> Playlist | None:
        with self._lock:
            row = self.db.execute("SELECT id, name, comment, public, created, changed FROM playlists WHERE id = ?", (pid,)).fetchone()
            return self._playlist(row) if row else None

    def _playlist(self, row) -> Playlist:
        paths = [p for (p,) in self.db.execute("SELECT path FROM playlist_entries WHERE playlist = ? ORDER BY pos", (row[0],))]
        return Playlist(row[0], row[1], row[2], bool(row[3]), row[4], row[5], paths)

    def create_playlist(self, name: str, paths: list[str]) -> int:
        now = time.time()
        with self._lock:
            cur = self.db.execute("INSERT INTO playlists (name, created, changed) VALUES (?, ?, ?)", (name.strip()[:200] or "Playlist", now, now))
            pid = cur.lastrowid
            self._set_entries(pid, paths)
            self.version += 1
            return pid

    def replace_playlist(self, pid: int, paths: list[str], name: str | None = None) -> bool:
        with self._lock:
            if self.playlist(pid) is None:
                return False
            if name is not None:
                self.db.execute("UPDATE playlists SET name = ? WHERE id = ?", (name.strip()[:200] or "Playlist", pid))
            self._set_entries(pid, paths)
            self.db.execute("UPDATE playlists SET changed = ? WHERE id = ?", (time.time(), pid))
            self.version += 1
            return True

    def update_playlist(self, pid: int, *, name: str | None = None, comment: str | None = None, public: bool | None = None,
                        add: list[str] = (), remove: list[int] = ()) -> bool:
        with self._lock:
            pl = self.playlist(pid)
            if pl is None:
                return False
            drop = set(remove)
            paths = [p for i, p in enumerate(pl.paths) if i not in drop] + list(add)
            for col, value in (("name", name.strip()[:200] if name is not None else None),
                               ("comment", comment[:1000] if comment is not None else None),
                               ("public", int(public) if public is not None else None)):
                if value is not None:
                    self.db.execute(f"UPDATE playlists SET {col} = ? WHERE id = ?", (value, pid))  # noqa: S608 (fixed names)
            self._set_entries(pid, paths)
            self.db.execute("UPDATE playlists SET changed = ? WHERE id = ?", (time.time(), pid))
            self.version += 1
            return True

    def delete_playlist(self, pid: int) -> bool:
        with self._lock:
            gone = self.db.execute("DELETE FROM playlists WHERE id = ?", (pid,)).rowcount
            self.db.execute("DELETE FROM playlist_entries WHERE playlist = ?", (pid,))
            self.version += 1
            return bool(gone)

    def _set_entries(self, pid: int, paths: list[str]) -> None:
        self.db.execute("DELETE FROM playlist_entries WHERE playlist = ?", (pid,))
        self.db.executemany("INSERT INTO playlist_entries (playlist, pos, path) VALUES (?, ?, ?)",
                            [(pid, i, p) for i, p in enumerate(paths[:MAX_PLAYLIST])])

    # --- Play queue and bookmarks ---------------------------------------------------------------

    def save_queue(self, paths: list[str], current: int | None, position: int, client: str) -> None:
        self._write("INSERT INTO queue (id, entries, current, position, changed, client) VALUES (1, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET entries = excluded.entries, current = excluded.current, "
                    "position = excluded.position, changed = excluded.changed, client = excluded.client",
                    (json.dumps(paths[:MAX_QUEUE]), current, max(0, position), time.time(), client[:100]))

    def queue(self) -> tuple[list[str], int | None, int, float, str] | None:
        with self._lock:
            row = self.db.execute("SELECT entries, current, position, changed, client FROM queue WHERE id = 1").fetchone()
        return (json.loads(row[0]), row[1], row[2], row[3], row[4]) if row else None

    def bookmarks(self) -> list[tuple[str, int, str, float, float]]:
        with self._lock:
            return self.db.execute("SELECT path, position, comment, created, changed FROM bookmarks ORDER BY changed DESC").fetchall()

    def set_bookmark(self, path: str, position: int, comment: str = "") -> None:
        now = time.time()
        self._write("INSERT INTO bookmarks (path, position, comment, created, changed) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET position = excluded.position, comment = excluded.comment, "
                    "changed = excluded.changed", (path, max(0, position), comment[:1000], now, now))

    def delete_bookmark(self, path: str) -> None:
        self._write("DELETE FROM bookmarks WHERE path = ?", (path,))

    # --- Which apps are connected ----------------------------------------------------------------

    def seen(self, client: str) -> None:
        client = (client or "").strip()[:100]
        if client:
            with self._lock:
                self.db.execute("INSERT INTO clients (name, last_seen) VALUES (?, ?) ON CONFLICT(name) DO UPDATE "
                                "SET last_seen = excluded.last_seen", (client, time.time()))

    def clients(self, within: float = 30 * 86400) -> list[tuple[str, float]]:
        with self._lock:
            return self.db.execute("SELECT name, last_seen FROM clients WHERE last_seen > ? ORDER BY last_seen DESC",
                                   (time.time() - within,)).fetchall()


def moves_in(undo: dict | None) -> list[tuple[str, str]]:
    """Every (old, new) file move an activity entry's undo record describes, however deeply nested.

    A "moves" record lists the moves as they happened, [old, new] (undo moves them back), and
    the entry logged for an undo carries the reverse record, also as they happened."""
    out: list[tuple[str, str]] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("type") == "moves":
                for pair in node.get("moves") or []:
                    if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(isinstance(x, str) for x in pair):
                        out.append((pair[0], pair[1]))
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(undo)
    return out
