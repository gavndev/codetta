"""Lidarr: keeping the user's own Lidarr (https://lidarr.audio) in step with Codetta.

Lidarr finds and downloads albums; Codetta makes their tags right. They share a music
folder, so they need to agree on two things:

* **Lidarr should notice Codetta's changes straight away.** After Codetta changes files
  in Lidarr's folders it asks Lidarr to rescan just those folders (``RescanFolders``).
  Without that, moved files look missing to Lidarr until its next scheduled scan, and a
  monitored album could be downloaded again.
* **One app names the files.** When Lidarr's own renaming is on, Codetta leaves file
  names and folders in Lidarr's folders alone (it still fixes tags), unless the user
  chooses to let Codetta name them.

Codetta also reads Lidarr's settings to warn about one real conflict: with Write Audio
Tags set to "All files" (or "Sync"), Lidarr rewrites tags on its scheduled refresh,
undoing Codetta's fixes.

Lidarr and Codetta usually see the same music folder under different names (``/music``
and ``/data/music``, say). Codetta works out which of its folders each Lidarr root folder
is by finding Lidarr's artist folders in the library, so nothing has to be typed in.

Settings (address, API key, who names files) live in ``lidarr.json`` in the config folder,
readable by its owner only. The API key is never sent back to the page.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from codetta.core.library import is_special

NAMES_AUTO = "auto"  # Lidarr names files in its folders when its renaming is on
NAMES_CODETTA = "codetta"  # Codetta's Organize pattern everywhere, Lidarr's renaming or not
WRITES_ALL = ("allFiles", "sync")  # Lidarr's Write Audio Tags values that rewrite existing files
SYNC_QUIET_SECONDS = 3.0  # wait for changes to settle before asking Lidarr to rescan
CHECK_EVERY_SECONDS = 3600  # re-read Lidarr's settings this often (and whenever the page asks)
MAX_FOLDERS = 40  # more changed folders than this: rescan Lidarr's whole root folders instead
SAMPLE_ARTISTS = 30  # artists looked at to find where Lidarr's folders are in the library


class LidarrError(Exception):
    """Lidarr couldn't be reached or said no; the message is for people."""


Request = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]  # (method, url, headers, body) -> (status, body)


def http_request(method: str, url: str, headers: dict, body: bytes | None, timeout: float = 15) -> tuple[int, bytes]:
    if not url.lower().startswith(("http://", "https://")):  # an address set by env var skips the page's check
        raise LidarrError("The address must start with http:// or https://")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (the admin's own server)
            return resp.status, resp.read(20_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(100_000) if exc.fp else b""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise LidarrError(f"Couldn't reach Lidarr: {reason}") from exc


def clean_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url and not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "http://" + url  # "lidarr:8686" -> "http://lidarr:8686"
    for tail in ("/api/v1", "/api"):
        if url.endswith(tail):
            url = url[: -len(tail)]
    return url


class LidarrClient:
    def __init__(self, url: str, api_key: str, request: Request = http_request) -> None:
        self.base = clean_url(url) + "/api/v1"
        self.api_key = api_key
        self.request = request

    def call(self, method: str, path: str, body: object = None) -> object:
        headers = {"X-Api-Key": self.api_key, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        status, raw = self.request(method, self.base + path, headers, data)
        if status in (401, 403):
            raise LidarrError("Lidarr turned down the API key. Copy it from Lidarr: Settings → General → API Key.")
        if status == 404:
            raise LidarrError("Lidarr doesn't know that (404). Is the address right, and is Lidarr version 1 or newer?")
        if status >= 400:
            text = raw.decode("utf-8", "replace").strip()[:200]
            raise LidarrError(f"Lidarr said {status}" + (f": {text}" if text else ""))
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise LidarrError("Lidarr sent something that isn't JSON. Is the address pointing at Lidarr?") from exc

    def status(self) -> dict:
        s = self.call("GET", "/system/status")
        return s if isinstance(s, dict) else {}

    def root_folders(self) -> list[str]:
        r = self.call("GET", "/rootfolder")
        return [str(x["path"]) for x in r if isinstance(x, dict) and x.get("path")] if isinstance(r, list) else []

    def artist_paths(self) -> list[str]:
        r = self.call("GET", "/artist")
        return [str(a["path"]) for a in r if isinstance(a, dict) and a.get("path")] if isinstance(r, list) else []

    def write_tags(self) -> str:
        r = self.call("GET", "/config/metadataprovider")
        return str(r.get("writeAudioTags") or "no") if isinstance(r, dict) else "no"

    def renames(self) -> bool:
        r = self.call("GET", "/config/naming")
        return bool(r.get("renameTracks")) if isinstance(r, dict) else False

    def rescan(self, folders: list[str]) -> None:
        self.call("POST", "/command", {"name": "RescanFolders", "folders": folders})


# --- Settings -------------------------------------------------------------------------


@dataclass
class LidarrSettings:
    url: str = ""  # e.g. http://lidarr:8686
    api_key: str = ""
    names: str = NAMES_AUTO


class LidarrStore:
    """Settings, saved to lidarr.json (owner-only: it holds the API key)."""

    def __init__(self, file: Path, env_url: str | None = None, env_key: str | None = None) -> None:
        self.file = file
        self.lock = threading.RLock()
        self.env_url, self.env_key = (clean_url(env_url) if env_url else None), (env_key or None)
        self.settings = LidarrSettings()
        try:
            data = json.loads(file.read_text("utf-8"))
            s = data.get("settings") if isinstance(data, dict) else None
            if isinstance(s, dict):
                self.settings = LidarrSettings(**{k: v for k, v in s.items() if k in LidarrSettings.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            pass
        if self.settings.names not in (NAMES_AUTO, NAMES_CODETTA):
            self.settings.names = NAMES_AUTO

    @property
    def url(self) -> str:
        return self.env_url or self.settings.url

    @property
    def api_key(self) -> str:
        return self.env_key or self.settings.api_key

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key)

    def save(self) -> None:
        with self.lock:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".lidarr-", dir=self.file.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"settings": asdict(self.settings)}, f)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise


# --- Where Lidarr's folders are in the library ----------------------------------------------


def find_folder(root: str, artist_paths: Iterable[str], music_dir: Path) -> str | None:
    """The library folder (relative, "" for the music folder itself) that Lidarr's ``root`` is,
    found by looking for Lidarr's artist folders in the library. None: not in this library."""
    root = root.rstrip("/") or "/"
    rels = []
    for p in artist_paths:
        p = p.rstrip("/")
        if p.startswith(root + "/") or (root == "/" and p.startswith("/")):
            rels.append(p[len(root):].lstrip("/"))
    rels = [r for r in rels if r and ".." not in r.split("/")][:SAMPLE_ARTISTS]
    if not rels:
        return None
    candidates = [""]
    try:
        candidates += sorted(d.name for d in music_dir.iterdir() if d.is_dir() and not d.name.startswith("."))[:200]
    except OSError:
        return None
    best, hits = None, 0
    for c in candidates:
        n = sum(1 for r in rels if (music_dir / c / r).is_dir())
        if n > hits:
            best, hits = c, n
    return best if hits and hits * 2 >= len(rels) else None  # at least half of its artists, or it's a guess


@dataclass
class Root:
    lidarr: str  # Lidarr's path
    folder: str | None  # the library folder it is ("" = the music folder); None: not found in this library


@dataclass
class Check:
    ok: bool = False
    error: str = ""
    version: str = ""
    roots: list[Root] = field(default_factory=list)
    write_tags: str = "no"
    renames: bool = False
    at: float = 0.0

    def public(self) -> dict:
        return {"ok": self.ok, "error": self.error, "version": self.version, "write_tags": self.write_tags,
                "renames": self.renames, "roots": [asdict(r) for r in self.roots], "at": self.at}


class Lidarr:
    """The connection: settings, what Lidarr's set up like, and the rescans Codetta asks for."""

    def __init__(self, store: LidarrStore, music_dir: Path, enabled: Callable[[], bool],
                 request: Request = http_request, quiet: float | None = None) -> None:
        self.store = store
        self.music_dir = music_dir
        self.enabled = enabled
        self.request = request
        self.quiet = quiet  # None: SYNC_QUIET_SECONDS (read when used, so tests can shorten it)
        self.check_result = Check()
        self._pending: set[str] = set()
        self._last_change = 0.0
        self._cv = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stop = False
        self.last_sync: dict = {"at": 0.0, "folders": 0, "error": ""}

    @property
    def active(self) -> bool:
        return self.enabled() and self.store.configured

    def client(self) -> LidarrClient:
        return LidarrClient(self.store.url, self.store.api_key, self.request)

    # -- what Lidarr is set up like ----------------------------------------------------------

    def check(self) -> Check:
        if not self.store.configured:
            self.check_result = Check(error="Add your Lidarr's address and its API key.", at=time.time())
            return self.check_result
        c = self.client()
        try:
            st = c.status()
            roots, artists = c.root_folders(), c.artist_paths()
            result = Check(ok=True, version=str(st.get("version") or ""), write_tags=c.write_tags(),
                           renames=c.renames(), at=time.time(),
                           roots=[Root(r, find_folder(r, artists, self.music_dir)) for r in roots])
        except LidarrError as exc:
            result = Check(error=str(exc), at=time.time())
        self.check_result = result
        return result

    def fresh_check(self, max_age: float = CHECK_EVERY_SECONDS) -> Check:
        if self.active and time.time() - self.check_result.at > max_age:
            return self.check()
        return self.check_result

    def warnings(self) -> list[dict]:
        c = self.check_result
        if not (self.active and c.ok):
            return []
        out = []
        if c.write_tags in WRITES_ALL:
            out.append({"id": "write_tags", "title": "Lidarr will undo your tag fixes",
                        "text": "Lidarr is set to write tags to all files, so its scheduled refresh rewrites the tags "
                                "you fixed in Codetta. In Lidarr, go to Settings → Metadata and set Write Audio Tags to "
                                "“For new files only” (or “Never”)."})
        if c.roots and not any(r.folder is not None for r in c.roots):
            out.append({"id": "no_folders", "title": "Codetta can't find Lidarr's folders",
                        "text": "None of Lidarr's root folders (" + ", ".join(r.lidarr for r in c.roots) + ") seem to be "
                                "in your music folder, so Codetta can't tell Lidarr about changes. Check both apps "
                                "use the same music folder."})
        if c.renames and self.store.settings.names == NAMES_CODETTA:
            out.append({"id": "both_rename", "title": "Both apps rename files",
                        "text": "Lidarr's renaming is on and Codetta is set to name files too, so the next time Lidarr "
                                "imports or renames, it moves files back to its own pattern. Pick one: turn off "
                                "Rename Tracks in Lidarr (Settings → Media Management), or let Lidarr name files here."})
        return out

    # -- folders ----------------------------------------------------------------------------

    def folders(self) -> list[tuple[str, str]]:
        """(library folder, Lidarr path) for each of Lidarr's root folders found in the library."""
        return [(r.folder, r.lidarr.rstrip("/")) for r in self.check_result.roots if r.folder is not None]

    def managed(self, rel: str) -> bool:
        """Is this library path inside one of Lidarr's folders?"""
        return any(f == "" or rel == f or rel.startswith(f + "/") for f, _ in self.folders())

    def names_files(self, rel: str) -> bool:
        """Should Codetta leave this file's name and folder to Lidarr?"""
        return (self.active and self.check_result.ok and self.check_result.renames
                and self.store.settings.names == NAMES_AUTO and self.managed(rel))

    def lidarr_path(self, rel_folder: str) -> str | None:
        for f, lp in self.folders():
            if f == "" or rel_folder == f or rel_folder.startswith(f + "/"):
                rest = rel_folder[len(f):].lstrip("/") if f else rel_folder
                return posixpath.join(lp, rest) if rest else lp
        return None

    # -- rescans after Codetta changes files --------------------------------------------------

    def changed(self, rels: Iterable[str]) -> None:
        """Files Codetta just changed (library paths): tell Lidarr soon, in one go."""
        if not self.active:
            return
        folders = {posixpath.dirname(r) for r in rels if r and not is_special(r)}
        if not folders:
            return
        with self._cv:
            self._pending |= folders
            self._last_change = time.monotonic()
            self._cv.notify()
            self._ensure_thread()

    def _ensure_thread(self) -> None:
        """Start the worker unless it's running (called holding the lock: two saves at once start one)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="codetta-lidarr", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stop:
                    self._cv.wait(60)
                    if not self._pending and not self._stop and self.active:
                        break  # a quiet minute: a chance to re-read Lidarr's settings below
                if self._stop:
                    return
                quiet = SYNC_QUIET_SECONDS if self.quiet is None else self.quiet
                wait = self._last_change + quiet - time.monotonic()
                if self._pending and wait > 0:
                    self._cv.wait(wait)
                    continue
                pending, self._pending = self._pending, set()
            if pending:
                self.flush(pending)
            else:
                self.fresh_check()

    def flush(self, rel_folders: Iterable[str]) -> list[str]:
        """Ask Lidarr to rescan these library folders (the ones inside its root folders)."""
        if not self.active:
            return []
        self.fresh_check()
        targets: set[str] = set()
        for rel in rel_folders:
            rel = rel.strip("/")
            while rel and not (self.music_dir / rel).is_dir():  # moved away or deleted: its nearest folder
                rel = posixpath.dirname(rel)
            path = self.lidarr_path(rel)
            if path:
                targets.add(path)
        if not targets:
            return []
        if len(targets) > MAX_FOLDERS:
            targets = {lp for _, lp in self.folders()}
        folders = sorted(targets)
        try:
            self.client().rescan(folders)
            self.last_sync = {"at": time.time(), "folders": len(folders), "error": ""}
        except LidarrError as exc:
            self.last_sync = {"at": time.time(), "folders": 0, "error": str(exc)}
        return folders
