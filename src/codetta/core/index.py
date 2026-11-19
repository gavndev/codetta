"""Library-wide tag index, so the whole library can be searched in an instant.

Browsing reads one folder at a time; searching every file that way would take
minutes on a big library. Instead, a background thread keeps a small SQLite
database (``library-index.sqlite3`` in the config folder) with each file's tags
and display details:

* The first scan reads every audio file once. Later scans only look at file
  sizes and modification times, and re-read just the files that changed.
* There is no timer: after the startup scan, the library is only re-checked
  when someone searches (at most every ``RESCAN_SECONDS``), so an idle Codetta
  never wakes sleeping hard drives.
* Files Codetta edits itself are refreshed right away (``mark_dirty``).
* Searches never block on a scan; while a scan runs, results cover what has
  been indexed so far.
* It stays small: fingerprints, IDs, ReplayGain values and very long text
  (lyrics) aren't indexed, and the stored track details are compressed. The
  editor reads full tags from the file itself.

Query syntax (see ``parse_query``)::

    genre: rap, hip-hop        tag "genre" contains Rap OR Hip-Hop
    artist: drake genre: rap   both must match
    night drive                every word in title/artist/album/file name

Matching is case- and accent-insensitive and works on word starts, so
``genre: rap`` finds "Rap" and "Hip-Hop, Rap" but not "Trap".
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from codetta.core.engine import SUPPORTED_EXTENSIONS
from codetta.core.library import _is_valid_text, _sort_text, natural_key
from codetta.core.tagmap import FIELDS

log = logging.getLogger("codetta.index")

SCHEMA_VERSION = 5  # 4: a stored natural sort key per file; 5: keeps musicbrainz_albumid (Library health)
RESCAN_SECONDS = 15 * 60  # a search re-checks the library if the last scan is older than this
BATCH = 200  # files per database transaction while scanning
PAR_CHUNK = 128  # files per job when worker processes help with a big scan
PAR_START = 256  # use worker processes once this many files need reading (a first scan, a big import)
MAX_QUERY_CHARS = 500

# Tags searched by plain words (no "key:").
FREE_TEXT_KEYS = ("title", "artist", "album", "albumartist")

# Not worth searching, and often large: fingerprints, IDs, loudness data. The MusicBrainz
# album ID stays: Library health tells matched albums from unmatched ones by it.
_SKIP_KEY = re.compile(r"^(lyrics$|unsyncedlyrics$|acoustid_|musicbrainz_(?!albumid$)|replaygain_|itunnorm|itunsmpb|isrc$|barcode$|tidal_|spotify_|discogs_|deezer_|qobuz_|.*_id$|.*fingerprint)")
# Searchable, but not worth an index entry: sort names and credits repeat the real names.
_DUPLICATE_KEY = re.compile(r"^(.*sort|.*_credit|.*sortorder)$")
MAX_INDEXED_VALUE = 300  # longer values (lyrics, essays in comments) aren't searchable
MAX_STORED_VALUE = 1000  # longer values are left out of the stored track details


def _searchable(key: str, value: str) -> bool:
    return len(value) <= MAX_INDEXED_VALUE and not _SKIP_KEY.match(key) and not _DUPLICATE_KEY.match(key)


def _slim(track: dict) -> dict:
    """The track details kept in the index: everything the track list shows,
    without huge values. Marked ``partial`` so the editor reloads full tags."""
    tags = {}
    for key, values in (track.get("tags") or {}).items():
        if _SKIP_KEY.match(key.lower()):
            continue
        kept = [v for v in values if len(v) <= MAX_STORED_VALUE]
        if kept:
            tags[key] = kept
    return {**track, "tags": tags, "partial": True}


def _pack(track: dict) -> bytes:
    return zlib.compress(json.dumps(_slim(track), ensure_ascii=False, separators=(",", ":")).encode(), 6)


def _unpack(blob: bytes) -> dict:
    return json.loads(zlib.decompress(blob))

# Scripts written without spaces between words: match anywhere, not on word starts.
_NO_SPACES = re.compile(r"[฀-๿⺀-鿿가-힯豈-﫿぀-ヿ]")


def sfold(text: str) -> str:
    """Search form of ``text``: no accents or case, punctuation as single spaces.

    "Beyoncé" -> "beyonce", "Hip-Hop" -> "hip hop", "Don't" -> "dont".
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = re.sub(r"['’`]", "", text)
    return " ".join(re.split(r"[\W_]+", text)).strip()


def natural_sort_text(path: str) -> str:
    """``natural_key`` as one string SQLite can sort by ("Disc 2" < "Disc 10", case and accents
    ignored), stored per file so a search of 100,000 hits is ordered in C, not in Python."""
    out = []
    for part in re.split(r"(\d+)", path):
        if not part:
            continue
        if part.isdecimal():
            digits = str(int(part))
            out.append("\x00" + digits.rjust(max(20, len(digits)), "0"))
        else:
            out.append("\x01" + _sort_text(part))
    return "".join(out)


def word_match(haystack: str | None, needle: str) -> bool:
    """True if ``needle`` (already folded) starts a word somewhere in ``haystack``.

    ``haystack`` holds one or more folded values separated by "\\x1f".
    """
    if not haystack or not needle:
        return False
    if _NO_SPACES.search(needle):
        return needle in haystack
    return any((" " + part).find(" " + needle) >= 0 for part in haystack.split("\x1f"))


# --- Query parsing ---------------------------------------------------------------------------


@dataclass
class Clause:
    key: str
    label: str
    values: list[str]  # as typed (for display); any of them may match


@dataclass
class Query:
    words: list[str] = field(default_factory=list)  # as typed
    clauses: list[Clause] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.words and not any(c.values for c in self.clauses)


def _norm_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


_FIELD_NAMES: dict[str, tuple[str, str]] = {}
for _f in FIELDS:
    _FIELD_NAMES[_norm_key(_f.key)] = (_f.key, _f.label)
    _FIELD_NAMES[_norm_key(_f.label)] = (_f.key, _f.label)
# A few names people naturally type.
for _alias, _key in {"year": "date", "track": "tracknumber", "disc": "discnumber",
                     "band": "albumartist", "albumartist": "albumartist", "label": "label"}.items():
    _label = next((f.label for f in FIELDS if f.key == _key), _key)
    _FIELD_NAMES.setdefault(_norm_key(_alias), (_key, _label))
# "movement: allegro" means the movement's name (the number is "movement number").
_FIELD_NAMES[_norm_key("movement")] = ("movementname", "Movement")


def parse_query(text: str, is_custom_key: Callable[[str], bool] = lambda k: False) -> Query:
    """Split a search into ``key: value, value`` clauses and plain words.

    A key is a known field name or label ("genre", "Album artist", "year"), or
    a single word that is the name of a tag found in the library (custom tags).
    Anything else, colons included, is plain text.
    """
    text = text[:MAX_QUERY_CHARS]
    markers: list[tuple[int, int, str, str]] = []  # (start, end, key, label)
    for colon in (m.start() for m in re.finditer(":", text)):
        before = text[: colon]
        floor = markers[-1][1] if markers else 0
        words = list(re.finditer(r"\S+", before))
        for n in (3, 2, 1):  # longest field name first ("album artist" before "artist")
            if len(words) < n or words[-n].start() < floor:
                continue
            start = words[-n].start()
            name = _norm_key(before[start:])
            if name in _FIELD_NAMES:
                key, label = _FIELD_NAMES[name]
            elif n == 1 and re.fullmatch(r"[\w.-]{1,64}", before[start:].strip()) and is_custom_key(before[start:].strip().lower()):
                key = label = before[start:].strip().lower()
            else:
                continue
            markers.append((start, colon + 1, key, label))
            break

    query = Query()
    head = text[: markers[0][0]] if markers else text
    query.words = [w for w in head.split() if sfold(w)]
    for i, (_, end, key, label) in enumerate(markers):
        stop = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        values = [v.strip() for v in re.split(r"[,;]", text[end:stop]) if sfold(v)]
        query.clauses.append(Clause(key, label, values))
    return query


# --- The index ---------------------------------------------------------------------------------


@dataclass
class IndexStatus:
    ready: bool  # the first full scan has finished
    scanning: bool
    files: int  # files currently in the index
    seen: int  # files looked at in the scan that's running


Describe = Callable[[Path, str], dict]  # (absolute path, library-relative path) -> track JSON


class _Workers:
    """Helper processes (``python -m codetta.core.describe``) that read files during a big scan.

    Jobs go out as JSON lines, results come back the same way; each worker has at most one job.
    A worker that dies hands its job back to be read here, so a scan never gets stuck."""

    def __init__(self, n: int, fallback: Callable[[list], list]) -> None:
        import subprocess
        import sys
        self.fallback = fallback
        self.procs = []
        for _ in range(n):
            try:
                # A packaged app (one .exe) has no "python -m": it starts itself in helper mode instead.
                cmd = [sys.executable, "--codetta-describe-worker"] if getattr(sys, "frozen", False) else \
                    [sys.executable, "-m", "codetta.core.describe"]
                self.procs.append(subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                                   stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1))
            except OSError as exc:
                log.warning("Couldn't start an index helper: %s", exc)
        self.started = list(self.procs)  # every helper ever started: all are reaped in close()
        self.busy: list[tuple[object, str, list]] = []  # (process, root, items), oldest first

    def __bool__(self) -> bool:
        return bool(self.procs)

    def _collect(self) -> list:
        proc, root, items = self.busy.pop(0)
        line = proc.stdout.readline()
        if not line:  # the helper died: read its files here instead
            log.warning("An index helper stopped; carrying on without it")
            self.procs.remove(proc)
            return self.fallback(items)
        try:
            return [tuple(r) for r in json.loads(line)]
        except ValueError:
            return self.fallback(items)

    def submit(self, root: str, items: list) -> list:
        """Hand ``items`` to a free helper; returns whatever finished meanwhile."""
        done = []
        busy_procs = {id(b[0]) for b in self.busy}
        free = next((p for p in self.procs if id(p) not in busy_procs), None)
        while free is None and self.busy:
            proc = self.busy[0][0]
            done.extend(self._collect())
            free = proc if proc in self.procs else next((p for p in self.procs if id(p) not in {id(b[0]) for b in self.busy}), None)
        if free is None:  # every helper is gone
            return done + self.fallback(items)
        try:
            free.stdin.write(json.dumps({"root": root, "items": items}, ensure_ascii=False) + "\n")
            free.stdin.flush()
            self.busy.append((free, root, items))
        except OSError:
            self.procs.remove(free)
            done.extend(self.fallback(items))
        return done

    def finish(self) -> list:
        done = []
        while self.busy:
            done.extend(self._collect())
        return done

    def close(self) -> None:
        """Stop every helper and close its pipes (including any that died along the way)."""
        for p in self.started:
            try:
                p.stdin.close()
            except Exception:  # noqa: BLE001 - already closed or broken
                pass
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()
                p.wait()
            try:
                p.stdout.close()
            except Exception:  # noqa: BLE001
                pass
        self.procs, self.started = [], []


class LibraryIndex:
    """Keeps the searchable copy of the library's tags up to date.

    ``describe(path, rel)`` returns the JSON-able track dict (the same shape the
    browse API sends: tags, format, duration, art…), or raises ``OSError`` /
    any exception for unreadable files, which are indexed with an ``error``.
    """

    def __init__(self, root: Path, db_path: Path | None, describe: Describe, rescan_seconds: float = RESCAN_SECONDS,
                 parallel: Callable[[str, list[tuple[str, int, int]]], list] | None = None, workers: int = 0):
        """``parallel`` (a picklable function: (root, [(rel, mtime, size)]) -> [(rel, mtime, size, track)])
        lets big scans use ``workers`` processes; 0/1 workers reads everything here."""
        self.root = Path(os.path.abspath(root))
        self.describe = describe
        self.parallel = parallel
        self.workers = workers
        self.rescan_seconds = rescan_seconds
        self._lock = threading.Lock()  # guards the connection
        self.version = 0  # goes up whenever a file is added, changed or removed (for caches)
        self._dirty: set[str] = set()
        self._dirty_lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._scanning = False
        self._seen = 0
        self._ready = False
        self._last_scan = 0.0  # monotonic time the last full scan finished
        self._scan_requested = True  # scan once at startup
        self.db = self._open(db_path)

    # -- database ------------------------------------------------------------------------------

    def _open(self, db_path: Path | None) -> sqlite3.Connection:
        db = None
        if db_path is not None:
            try:
                db_path.parent.mkdir(parents=True, exist_ok=True)
                db = sqlite3.connect(db_path, check_same_thread=False)
                db.execute("PRAGMA journal_mode=WAL")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, SCHEMA_VERSION):  # older layout: rebuild from scratch
                    db.executescript("DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS tags; DROP TABLE IF EXISTS keys; VACUUM;")
            except (OSError, sqlite3.Error) as exc:
                log.warning("Library index can't be saved in the config folder (%s); keeping it in memory.", exc)
                db = None
        if db is None:
            db = sqlite3.connect(":memory:", check_same_thread=False)
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, mtime INTEGER, size INTEGER,
                text TEXT, track BLOB NOT NULL, nkey TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS keys (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            -- One row per file and tag; tag names are stored once, in "keys".
            CREATE TABLE IF NOT EXISTS tags (
                key INTEGER NOT NULL, file INTEGER NOT NULL, value TEXT NOT NULL,
                PRIMARY KEY (key, file)) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS tags_file ON tags(file);
            """
        )
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        db.create_function("wm", 2, word_match, deterministic=True)
        db.commit()
        self._key_ids = dict(db.execute("SELECT name, id FROM keys").fetchall())
        return db

    def _key_id(self, cur: sqlite3.Cursor, name: str) -> int:
        if name not in self._key_ids:
            cur.execute("INSERT OR IGNORE INTO keys(name) VALUES (?)", (name,))
            self._key_ids[name] = cur.execute("SELECT id FROM keys WHERE name=?", (name,)).fetchone()[0]
        return self._key_ids[name]

    def _store(self, rows: list[tuple[str, int, int, dict]]) -> None:
        with self._lock:
            cur = self.db.cursor()
            for rel, mtime, size, track in rows:
                tags = track.get("tags") or {}
                text = "\x1f".join(
                    [sfold(v) for k in FREE_TEXT_KEYS for v in tags.get(k, [])] + [sfold(Path(rel).stem)]
                )
                row = cur.execute("SELECT id FROM files WHERE path=?", (rel,)).fetchone()
                if row:
                    file_id = row[0]
                    cur.execute("DELETE FROM tags WHERE file=?", (file_id,))
                    cur.execute("UPDATE files SET mtime=?, size=?, text=?, track=?, nkey=? WHERE id=?",
                                (mtime, size, text, _pack(track), natural_sort_text(rel), file_id))
                else:
                    cur.execute("INSERT INTO files(path, mtime, size, text, track, nkey) VALUES (?,?,?,?,?,?)",
                                (rel, mtime, size, text, _pack(track), natural_sort_text(rel)))
                    file_id = cur.lastrowid
                merged: dict[str, list[str]] = {}  # "Genre" and "genre" are the same tag
                for k, vals in tags.items():
                    kept = [sfold(v) for v in vals if _searchable(k.lower(), v)]
                    if kept:
                        merged.setdefault(k.lower(), []).extend(kept)
                cur.executemany("INSERT INTO tags(key, file, value) VALUES (?,?,?)",
                                [(self._key_id(cur, k), file_id, "\x1f".join(v)) for k, v in merged.items()])
            self.db.commit()
            if rows:
                self.version += 1

    def _remove(self, rels: Iterable[str]) -> None:
        rels = list(rels)
        if not rels:
            return
        with self._lock:
            for r in rels:
                row = self.db.execute("SELECT id FROM files WHERE path=?", (r,)).fetchone()
                if row:
                    self.db.execute("DELETE FROM tags WHERE file=?", (row[0],))
                    self.db.execute("DELETE FROM files WHERE id=?", (row[0],))
            self.db.commit()
            self.version += 1

    def _read_item(self, item: tuple[str, int, int]) -> tuple[str, int, int, dict]:
        rel, mtime, size = item
        try:
            track = self.describe(self.root / rel, rel)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the scan
            track = {"path": rel, "name": rel.rsplit("/", 1)[-1], "error": str(exc) or type(exc).__name__}
        return rel, mtime, size, track

    def _read(self, rel: str, st: os.stat_result) -> tuple[str, int, int, dict]:
        try:
            track = self.describe(self.root / rel, rel)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the scan
            track = {"path": rel, "name": rel.rsplit("/", 1)[-1], "error": str(exc) or type(exc).__name__}
        return rel, st.st_mtime_ns, st.st_size, track

    # -- scanning ----------------------------------------------------------------------------------

    def _walk(self) -> Iterable[tuple[str, os.stat_result]]:
        """Every audio file under the root (following folder links, once each)."""
        seen_dirs: set[tuple[int, int]] = set()
        stack = [""]
        while stack and not self._stop.is_set():
            rel_dir = stack.pop()
            folder = self.root / rel_dir if rel_dir else self.root
            try:
                st = folder.stat()
                if (st.st_dev, st.st_ino) in seen_dirs:
                    continue  # a link loop, or the same folder linked twice
                seen_dirs.add((st.st_dev, st.st_ino))
                with os.scandir(folder) as entries:
                    items = list(entries)
            except OSError:
                continue
            for entry in items:
                if entry.name.startswith(".") or not _is_valid_text(entry.name):
                    continue
                rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                try:
                    if entry.is_dir():
                        stack.append(rel)
                    elif entry.is_file() and Path(entry.name).suffix.lower() in SUPPORTED_EXTENSIONS:
                        yield rel, entry.stat()
                except OSError:
                    continue

    def scan(self) -> None:
        """Bring the index up to date with the files on disk."""
        if not self.root.is_dir():
            return
        self._scanning, self._seen = True, 0
        started = time.monotonic()
        pool = None
        try:
            with self._lock:
                known = {p: (m, s) for p, m, s in self.db.execute("SELECT path, mtime, size FROM files")}
            present: set[str] = set()
            batch: list[tuple[str, int, int, dict]] = []
            changed = 0
            pending: list[tuple[str, int, int]] = []  # waiting to be read (in a helper, once it's worth it)

            def store(rows: list) -> None:
                nonlocal changed, batch
                batch.extend(rows)
                if len(batch) >= BATCH:
                    self._store(batch)
                    changed += len(batch)
                    batch = []

            def read_here(items: list) -> list:
                return [self._read_item(i) for i in items]

            for rel, st in self._walk():
                present.add(rel)
                self._seen += 1
                if known.get(rel) == (st.st_mtime_ns, st.st_size):
                    continue
                pending.append((rel, st.st_mtime_ns, st.st_size))
                if pool is None and len(pending) >= PAR_START and self.parallel and self.workers > 1:
                    pool = _Workers(self.workers, read_here) or None
                if pool is not None and len(pending) >= PAR_CHUNK:
                    store(pool.submit(str(self.root), pending))  # bounded: one job per helper at a time
                    pending = []
                elif pool is None and len(pending) >= PAR_START:
                    store([self._read_item(i) for i in pending])  # no workers: read here, in order
                    pending = []
                self._flush_dirty()  # edits made during a long first scan show up quickly
            if pool is not None:
                if pending:
                    store(pool.submit(str(self.root), pending))
                    pending = []
                store(pool.finish())
                pool.close()
            store([self._read_item(i) for i in pending])
            if batch:
                self._store(batch)
                changed += len(batch)
            if not self._stop.is_set():
                gone = set(known) - present
                self._remove(gone)
                self._ready = True
                self._last_scan = time.monotonic()
                if changed or gone:
                    with self._lock:  # fold the write-ahead log back in, so it doesn't linger on disk
                        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                if changed or gone:
                    log.info("Library index: %d files, %d updated, %d removed (%.1fs)",
                             len(present), changed, len(gone), time.monotonic() - started)
        finally:
            if pool is not None:
                pool.close()  # never leave helpers behind, even if the scan stopped half-way
            self._scanning = False

    def mark_dirty(self, rels: Iterable[str]) -> None:
        """Files Codetta just changed: re-read them before the next search."""
        with self._dirty_lock:
            self._dirty.update(rels)
        self._wake.set()

    def _flush_dirty(self) -> None:
        with self._dirty_lock:
            dirty, self._dirty = self._dirty, set()
        if not dirty:
            return
        rows, gone = [], []
        for rel in dirty:
            try:
                st = (self.root / rel).stat()
            except OSError:
                gone.append(rel)
                continue
            rows.append(self._read(rel, st))
        if rows:
            self._store(rows)
        self._remove(gone)

    # -- background thread -------------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="codetta-index", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def request_rescan(self) -> None:
        """Called on each search: re-check the library if the last scan is old."""
        if not self._scanning and time.monotonic() - self._last_scan > self.rescan_seconds:
            self._scan_requested = True
            self._wake.set()

    def _run(self) -> None:
        # No timer: sleeps until something asks (startup, a search, an edit).
        while not self._stop.is_set():
            try:
                if self._scan_requested:
                    self._scan_requested = False
                    self.scan()
                self._flush_dirty()
            except Exception:  # noqa: BLE001 - keep the index alive; try again on the next request
                log.exception("Library index scan failed")
                self._last_scan = time.monotonic()
            self._wake.wait()
            self._wake.clear()

    # -- searching ---------------------------------------------------------------------------------

    def status(self) -> IndexStatus:
        with self._lock:
            files = self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        return IndexStatus(ready=self._ready, scanning=self._scanning, files=files, seen=self._seen)

    def all_tracks(self) -> list[tuple[str, dict]]:
        """Every indexed track (path, details), in path order. ~5,000 tracks take
        about a tenth of a second: no file is opened."""
        with self._lock:
            rows = self.db.execute("SELECT path, track FROM files ORDER BY path").fetchall()
        return [(p, _unpack(t)) for p, t in rows]

    def stored(self, rels: list[str]) -> dict[str, tuple[int, int, dict]]:
        """What the index has for these files: path -> (mtime_ns, size, details)."""
        out: dict[str, tuple[int, int, dict]] = {}
        for i in range(0, len(rels), 900):  # SQLite's limit on query parameters
            chunk = rels[i:i + 900]
            q = "SELECT path, mtime, size, track FROM files WHERE path IN (" + ",".join("?" * len(chunk)) + ")"
            with self._lock:
                rows = self.db.execute(q, chunk).fetchall()
            for path, mtime, size, blob in rows:
                out[path] = (mtime, size, _unpack(blob))
        return out

    def iter_tracks(self, chunk: int = 2000):
        """Every indexed track (path, details) in path order, read a chunk at a time, so even a
        huge library is never all in memory at once (and indexing isn't blocked meanwhile)."""
        last = ""
        while True:
            with self._lock:
                rows = self.db.execute("SELECT path, track FROM files WHERE path > ? ORDER BY path LIMIT ?",
                                       (last, chunk)).fetchall()
            if not rows:
                return
            for path, blob in rows:
                yield path, _unpack(blob)
            last = rows[-1][0]

    def paths_with_any(self, keys: Iterable[str]) -> set[str]:
        """Files that have at least one of these tags (by name, any case)."""
        with self._lock:
            ids = [self._key_ids[k] for k in {k.lower() for k in keys} if k in self._key_ids]
            if not ids:
                return set()
            q = ("SELECT DISTINCT f.path FROM files f JOIN tags t ON t.file = f.id WHERE t.key IN ("
                 + ",".join("?" * len(ids)) + ")")
            return {p for (p,) in self.db.execute(q, ids)}

    def has_key(self, key: str) -> bool:
        with self._lock:
            return key in self._key_ids

    def search(self, query: Query, limit: int = 500) -> tuple[list[dict], int]:
        """Tracks matching ``query``, in library order (first ``limit``), and the total count."""
        if query.empty:
            return [], 0
        self._flush_dirty()
        sql = ["SELECT path FROM files WHERE 1"]
        args: list[str] = []
        # instr() (in C) rules most rows out before the Python word check runs on what's left.
        for word in query.words:
            sql.append("AND instr(text, ?) AND wm(text, ?)")
            args += [sfold(word), sfold(word)]
        for clause in query.clauses:
            needles = [sfold(v) for v in clause.values]
            if not needles:
                continue
            sql.append("AND id IN (SELECT file FROM tags WHERE key=(SELECT id FROM keys WHERE name=?) AND ("
                       + " OR ".join(["(instr(value, ?) AND wm(value, ?))"] * len(needles)) + "))")
            args += [clause.key, *[x for n in needles for x in (n, n)]]
        sql.append("ORDER BY nkey")  # library order ("Disc 2" before "Disc 10"), sorted by SQLite
        with self._lock:
            paths = [p for (p,) in self.db.execute(" ".join(sql), args)]
        shown = paths[:limit]
        with self._lock:
            tracks = {}
            for i in range(0, len(shown), 500):
                chunk = shown[i:i + 500]
                q = "SELECT path, track FROM files WHERE path IN (" + ",".join("?" * len(chunk)) + ")"
                tracks.update({p: _unpack(t) for p, t in self.db.execute(q, chunk)})
        return [tracks[p] for p in shown if p in tracks], len(paths)
