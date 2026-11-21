"""Soulseek through the user's own slskd (https://github.com/slskd/slskd).

Codetta never speaks the Soulseek protocol itself: it asks the user's slskd
over its REST API (``/api/v0``, ``X-API-Key``) to search and download, and
slskd saves the files into its downloads folder, which is Codetta's inbox.
From there the inbox does what it always does (match, review, file).

A *job* is one request ("T-Pain Bartender"):

    searching → downloading → fetched → arrived (in the inbox) → imported
                     ↑  failed / blocklisted: next candidate  |
                     └────────────────────────────────────────┘
    (no candidates left: nothing / failed; cancelled by the user)

Candidates are the folders other users share, ranked by how well their names
match the request, quality (lossless first by default), free upload slots,
queue length and speed. Folders the user blocklisted are never offered again.

State (settings incl. the API key, jobs, blocklist) lives in ``slskd.json``
in the config folder, readable by its owner only.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from datetime import datetime
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Job statuses.
SEARCHING = "searching"
CHOOSING = "choosing"  # found sources: waiting for you to pick one (the "pick the source first" setting)
DOWNLOADING = "downloading"
FETCHED = "fetched"  # slskd has every file: waiting for them to show up in the inbox
ARRIVED = "arrived"  # in the inbox, being matched / waiting for a review
IMPORTED = "imported"
NOTHING = "nothing"  # the search found nothing usable
FAILED = "failed"
CANCELLED = "cancelled"
ACTIVE = (SEARCHING, DOWNLOADING, FETCHED)

AUDIO = {"flac", "mp3", "m4a", "aac", "ogg", "opus", "wav", "aif", "aiff", "ape", "wv", "dsf", "alac", "wma"}
LOSSLESS = {"flac", "wav", "aif", "aiff", "ape", "wv", "dsf", "alac"}
MAX_CANDIDATES = 25
MAX_JOBS = 50
QUIET_SAVE_SECONDS = 30  # progress-only changes reach the disk at most this often
DONE = (IMPORTED, NOTHING, CANCELLED)  # finished for good: their file lists aren't needed any more
STALL_SECONDS = 15 * 60  # a download that hasn't moved for this long gives way to the next candidate
ARRIVE_SECONDS = 10 * 60  # finished in slskd but not in the inbox after this long: something's mounted wrong
FAILED_STATES = ("Errored", "Rejected", "TimedOut", "Cancelled", "Aborted")


class SlskdError(Exception):
    """slskd couldn't be reached or said no; the message is for people."""


# --- Settings -------------------------------------------------------------------------


@dataclass
class SlskdSettings:
    url: str = ""  # e.g. http://slskd:5030
    api_key: str = ""
    review: bool = True  # False: confident downloads are filed without asking
    choose: bool = True  # True: show the sources (user, slot, queue, speed, files) and wait for a pick
    lossless_only: bool = False  # default: lossless first, lossy (min_bitrate and up) if no one has it
    min_bitrate: int = 320  # kbps, for lossy files
    search_seconds: int = 20

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key)


def clean_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url and not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "http://" + url  # "slskd:5030" -> "http://slskd:5030"; any other scheme is left for the caller to refuse
    if url.endswith("/api/v0"):
        url = url[: -len("/api/v0")]
    return url


# --- Talking to slskd -------------------------------------------------------------------

Request = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]  # (method, url, headers, body) -> (status, body)


def http_request(method: str, url: str, headers: dict, body: bytes | None, timeout: float = 15) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (the admin's own server)
            return resp.status, resp.read(20_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(100_000) if exc.fp else b""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SlskdError(f"Couldn't reach slskd: {reason}") from exc


class SlskdClient:
    def __init__(self, url: str, api_key: str, request: Request = http_request) -> None:
        self.base = clean_url(url) + "/api/v0"
        self.api_key = api_key
        self.request = request

    def call(self, method: str, path: str, body: object = None) -> object:
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        status, raw = self.request(method, self.base + path, headers, data)
        if status in (401, 403):
            raise SlskdError("slskd turned down the API key. Check it matches one in slskd's settings (web → authentication → api_keys).")
        if status == 404:
            raise SlskdError("slskd doesn't know that (404). Is the address right, and is slskd up to date?")
        if status >= 400:
            text = raw.decode("utf-8", "replace").strip()[:200]
            raise SlskdError(f"slskd said {status}" + (f": {text}" if text else ""))
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise SlskdError("slskd sent something that isn't JSON. Is the address pointing at slskd?") from exc

    @staticmethod
    def _user(username: str) -> str:
        return urllib.parse.quote(username, safe="")

    def version(self) -> str:
        v = self.call("GET", "/application/version")
        return v if isinstance(v, str) else str(v or "")

    def application(self) -> dict:
        return self.call("GET", "/application") or {}

    def shares(self) -> dict:
        return self.call("GET", "/shares") or {}

    def options(self) -> dict:
        return self.call("GET", "/options") or {}

    def start_search(self, search_id: str, text: str, seconds: int) -> None:
        self.call("POST", "/searches", {
            "id": search_id, "searchText": text, "searchTimeout": max(5, seconds) * 1000,
            "filterResponses": True, "responseLimit": 200, "fileLimit": 20000,
        })

    def search(self, search_id: str) -> dict:
        return self.call("GET", f"/searches/{search_id}") or {}

    def responses(self, search_id: str) -> list:
        r = self.call("GET", f"/searches/{search_id}/responses")
        return r if isinstance(r, list) else []

    def delete_search(self, search_id: str) -> None:
        try:
            self.call("DELETE", f"/searches/{search_id}")
        except SlskdError:
            pass

    def enqueue(self, username: str, files: list[dict]) -> None:
        self.call("POST", f"/transfers/downloads/{self._user(username)}",
                  [{"filename": f["filename"], "size": f["size"]} for f in files])

    def downloads(self, username: str) -> list[dict]:
        """Every download from this user, flattened."""
        try:
            r = self.call("GET", f"/transfers/downloads/{self._user(username)}")
        except SlskdError as exc:
            if "404" in str(exc):
                return []  # nothing from this user (any more)
            raise
        out = []
        for d in (r or {}).get("directories") or []:
            out.extend(t for t in d.get("files") or [] if isinstance(t, dict))
        return out

    def all_downloads(self) -> list[dict]:
        """Every download slskd knows, one entry per (user, remote folder)."""
        out = []
        for u in self.call("GET", "/transfers/downloads") or []:
            for d in (u or {}).get("directories") or []:
                out.append({"username": u.get("username") or "", "directory": d.get("directory") or "",
                            "files": [t for t in d.get("files") or [] if isinstance(t, dict)]})
        return out

    def cancel(self, username: str, transfer_id: str) -> None:
        try:
            self.call("DELETE", f"/transfers/downloads/{self._user(username)}/{transfer_id}?remove=true")
        except SlskdError:
            pass


def _when(text: object) -> float | None:
    """slskd's timestamps ("2026-11-18T18:50:01.1234567", UTC, with or without Z) -> epoch seconds."""
    if not isinstance(text, str) or not text:
        return None
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:?\d\d)?$", text.strip())
    if not m:
        return None
    frac = (m.group(2) or ".0")[:7]
    zone = m.group(3) or "+00:00"
    try:
        return datetime.fromisoformat(m.group(1) + frac + ("+00:00" if zone == "Z" else zone)).timestamp()
    except ValueError:
        return None


def transfer_progress(transfers: list[dict], now: float | None = None) -> dict | None:
    """How far a folder's download has got, and roughly how long the rest takes:
    the speed so far (bytes since the first file started) applied to what's left."""
    if not transfers:
        return None
    now = time.time() if now is None else now
    total = sum(int(t.get("size") or 0) for t in transfers)
    done = sum(int(t.get("bytesTransferred") or 0) for t in transfers)
    if total <= 0:
        return None
    starts = [s for t in transfers if (s := _when(t.get("startedAt"))) is not None]
    finished = sum("Succeeded" in str(t.get("state") or "") for t in transfers)
    eta = speed = None
    if starts and 0 < done < total:
        elapsed = max(1.0, now - min(starts))
        speed = done / elapsed
        eta = (total - done) / speed if speed > 0 else None
    # Every transfer over (slskd: "Completed, Succeeded", or Errored, Cancelled, Rejected, TimedOut).
    complete = all("Completed" in str(t.get("state") or "") for t in transfers)
    return {"progress": round(min(done / total, 1.0), 3), "eta": round(eta) if eta is not None else None,
            "speed": round(speed) if speed else None, "files": len(transfers), "finished": finished,
            "complete": complete}


def folder_progress(downloads: list[dict], names: set[str], now: float | None = None) -> dict | None:
    """The download (one slskd folder) that these files came from, by file name."""
    best = None
    for d in downloads:
        hit = len(names & {split_remote(t.get("filename") or "")[1] for t in d["files"]})
        if hit and (best is None or hit > best[0]):
            best = (hit, d)
    return transfer_progress(best[1]["files"], now) if best else None


def check(client: SlskdClient) -> dict:
    """What Account → Connections shows: reachable? shares? where downloads go?"""
    out = {"ok": False, "version": "", "shared_folders": 0, "shared_files": 0, "downloads_dir": "",
           "logged_in": None, "error": ""}
    try:
        out["version"] = client.version()
        shares = client.shares()
        for host_shares in shares.values() if isinstance(shares, dict) else []:
            for s in host_shares or []:
                if isinstance(s, dict) and not s.get("isExcluded"):
                    out["shared_folders"] += 1
                    out["shared_files"] += int(s.get("files") or 0)
        try:
            out["downloads_dir"] = ((client.options().get("directories") or {}).get("downloads")) or ""
        except SlskdError:
            pass  # older slskd or a key without admin rights: not essential
        try:
            server = (client.application().get("server") or {})
            out["logged_in"] = bool(server.get("isLoggedIn")) if "isLoggedIn" in server else None
        except SlskdError:
            pass
        out["ok"] = True
    except SlskdError as exc:
        out["error"] = str(exc)
    return out


# --- Ranking ------------------------------------------------------------------------------


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def split_remote(filename: str) -> tuple[str, str]:
    """Soulseek paths use backslashes (Windows sharers) or slashes."""
    sep = "\\" if "\\" in filename else "/"
    folder, _, name = filename.rpartition(sep)
    return folder, name


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^\w*]+", text.lower()) if w.strip("*")]


def name_match(query: str, haystack: str) -> float:
    """Share of the request's words found in the folder and file names.
    ``*`` is a wildcard (``*-Pain`` → any word ending in "pain")."""
    words = _words(query)
    if not words:
        return 0.0
    hay = " ".join(_words(haystack))
    hit = 0
    for w in words:
        pattern = r"\b" + ".*?".join(re.escape(p) for p in w.split("*")) + r"\b" if "*" in w else r"\b" + re.escape(w) + r"\b"
        if "*" in w and w.startswith("*"):
            pattern = pattern[2:]  # "*ain" may sit in the middle of a word
        if re.search(pattern, hay):
            hit += 1
    return hit / len(words)


def quality(files: list[dict]) -> tuple[int, str]:
    """(rank, label): 3 lossless, 2 lossy at a good bitrate, 1 lossy unknown, 0 lossy low."""
    exts = {_ext(f["filename"]) for f in files}
    lossless = all(_ext(f["filename"]) in LOSSLESS or (_ext(f["filename"]) == "m4a" and f.get("bitDepth")) for f in files)
    if lossless:
        depth = max((f.get("bitDepth") or 0 for f in files), default=0)
        rate = max((f.get("sampleRate") or 0 for f in files), default=0)
        fmt = "/".join(sorted(e.upper() for e in exts))
        return 3, f"{fmt} {depth}-bit/{rate / 1000:g} kHz" if depth and rate else fmt
    rates = [f.get("bitRate") for f in files if f.get("bitRate")]
    fmt = "/".join(sorted(e.upper() for e in exts))
    if not rates:
        return 1, fmt
    low = min(rates)
    vbr = any(f.get("isVariableBitRate") for f in files)
    return 2, f"{fmt} {'VBR ~' if vbr else ''}{low} kbps"


def rank(responses: list[dict], query: str, settings: SlskdSettings, blocked: set[str]) -> list[dict]:
    """Candidate folders, best first."""
    cands = []
    for r in responses:
        user = r.get("username") or ""
        if not user:
            continue
        folders: dict[str, list[dict]] = {}
        for f in r.get("files") or []:
            if not isinstance(f, dict) or _ext(f.get("filename") or "") not in AUDIO or f.get("isLocked"):
                continue
            folder, _ = split_remote(f["filename"])
            folders.setdefault(folder, []).append(f)
        for folder, files in folders.items():
            if block_key(user, folder) in blocked or block_key(user, "") in blocked:
                continue
            q, label = quality(files)
            if q < 3:
                if settings.lossless_only:
                    continue
                rates = [f.get("bitRate") for f in files if f.get("bitRate")]
                if rates and min(rates) < settings.min_bitrate and not any(f.get("isVariableBitRate") for f in files):
                    q = 0
            tail = "\\".join(re.split(r"[\\/]", folder)[-2:])
            names = tail + " " + " ".join(split_remote(f["filename"])[1] for f in files)
            match = name_match(query, names)
            if match < 0.5:
                continue
            speed = int(r.get("uploadSpeed") or 0)
            queue = int(r.get("queueLength") or 0)
            free = bool(r.get("hasFreeUploadSlot"))
            score = (match * 100 + q * 25 + (15 if free else 0) + min(speed / 1_000_000, 1) * 10
                     - min(queue, 50) / 5 + min(len(files), 12))
            cands.append({
                "username": user, "folder": folder, "name": re.split(r"[\\/]", folder)[-1] or folder,
                "files": [{k: f.get(k) for k in ("filename", "size", "bitRate", "bitDepth", "sampleRate", "length",
                                                 "isVariableBitRate")} for f in sorted(files, key=lambda f: f["filename"])],
                "tracks": len(files), "size": sum(int(f.get("size") or 0) for f in files),
                "quality": label, "lossless": q == 3, "free_slot": free, "speed": speed, "queue": queue,
                "match": round(match, 2), "score": round(score, 1),
            })
    cands.sort(key=lambda c: -c["score"])
    return cands[:MAX_CANDIDATES]


def block_key(username: str, folder: str) -> str:
    return f"{username}\n{folder}"


# --- Jobs -----------------------------------------------------------------------------------


@dataclass
class Job:
    id: str
    query: str
    status: str = SEARCHING
    created: float = 0.0
    updated: float = 0.0
    upgrade: str = ""  # a library folder this download is meant to replace ("" = new music)
    candidates: list[dict] = field(default_factory=list)
    pick: int = -1  # index into candidates being downloaded
    tried: list[int] = field(default_factory=list)
    progress: float = 0.0  # 0..1 of the current pick
    eta: float | None = None  # seconds left, roughly (speed since the first file started)
    moved: float = 0.0  # when the download last made progress
    note: str = ""
    inbox_key: str = ""  # its album in the inbox, once it's there
    # Files that already arrived from a source this job gave up on: {"folder": name, "files": [names]}.
    # The app moves them to Recently deleted, so they never show up as a second album in the inbox.
    leftovers: list[dict] = field(default_factory=list)

    @property
    def current(self) -> dict | None:
        return self.candidates[self.pick] if 0 <= self.pick < len(self.candidates) else None


def _slim(job: Job) -> None:
    """A finished request keeps its summary, not every candidate's file list (most of its size)."""
    if job.status in DONE and any("files" in c for c in job.candidates):
        job.candidates = [{k: v for k, v in c.items() if k != "files"} for c in job.candidates]


class SoulseekStore:
    """Settings, jobs and the blocklist, saved to slskd.json (owner-only: it holds the API key)."""

    def __init__(self, file: Path, env_url: str | None = None, env_key: str | None = None) -> None:
        self.file = file
        self.lock = threading.RLock()
        self.settings = SlskdSettings()
        self.jobs: dict[str, Job] = {}
        self.blocked: set[str] = set()
        self.env_url, self.env_key = (clean_url(env_url) if env_url else None), (env_key or None)
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.file.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        s = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        known = SlskdSettings.__dataclass_fields__
        try:
            self.settings = SlskdSettings(**{k: v for k, v in s.items() if k in known})
        except TypeError:
            self.settings = SlskdSettings()
        for j in (data.get("jobs") or {}).values() if isinstance(data.get("jobs"), dict) else []:
            try:
                job = Job(**{k: v for k, v in j.items() if k in Job.__dataclass_fields__})
            except TypeError:
                continue
            self.jobs[job.id] = job
        self.blocked = {b for b in data.get("blocked") or [] if isinstance(b, str)}
        self._saved = 0.0
        for job in self.jobs.values():
            _slim(job)

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
            data = {"settings": asdict(self.settings), "jobs": {k: asdict(j) for k, j in self.jobs.items()},
                    "blocked": sorted(self.blocked)}
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".slskd-", dir=self.file.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp, self.file)
                self._saved = time.time()
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise

    def add_job(self, query: str, upgrade: str = "") -> Job:
        with self.lock:
            now = time.time()
            job = Job(id=str(uuid.uuid4()),  # slskd wants a standard GUID (with dashes)
                       query=query, created=now, updated=now, moved=now, upgrade=upgrade)
            self.jobs[job.id] = job
            # Forget the oldest finished jobs.
            done = sorted((j for j in self.jobs.values() if j.status not in ACTIVE + (ARRIVED,)), key=lambda j: j.updated)
            for j in done[: max(0, len(self.jobs) - MAX_JOBS)]:
                del self.jobs[j.id]
            self.save()
            return job

    def update(self, job: Job, quiet: bool = False, **changes) -> Job:
        """Change a job and save. ``quiet``: only progress moved, so the file is
        written at most every QUIET_SAVE_SECONDS (a download ticks every few seconds)."""
        with self.lock:
            for k, v in changes.items():
                setattr(job, k, v)
            job.updated = time.time()
            _slim(job)
            if not quiet or job.updated - self._saved >= QUIET_SAVE_SECONDS:
                self.save()
            return job

    def active(self) -> list[Job]:
        with self.lock:
            return [j for j in self.jobs.values() if j.status in ACTIVE]


class Soulseek:
    """Moves jobs along. ``tick()`` is called every few seconds by a background
    thread while any job is active. ``locate(job)`` (from the app) finds the
    finished download in the inbox and returns its album key, or None."""

    def __init__(self, store: SoulseekStore, request: Request = http_request,
                 notify: Callable[[str, str, dict | None], None] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.request = request
        self.notify = notify or (lambda title, body, action: None)
        self.clock = clock
        self._snapshot: dict[str, list[dict]] | None = None  # this round's transfers, by user (one request)
        self._failures = 0  # rounds in a row slskd couldn't be reached
        self._resume = 0.0  # don't ask slskd again before this time (backing off after errors)

    def client(self) -> SlskdClient:
        if not self.store.configured:
            raise SlskdError("Connect your slskd first (Account → Connections).")
        return SlskdClient(self.store.url, self.store.api_key, self.request)

    def search(self, query: str, upgrade: str = "") -> Job:
        query = " ".join(query.split())
        if sum(c.isalnum() for c in query) < 2:
            raise SlskdError("Type at least two letters or numbers to search Soulseek.")
        client = self.client()
        key = query.casefold()
        with self.store.lock:  # the same search twice (a double tap, two tabs) shares one request
            for existing in self.store.jobs.values():
                if existing.status in (SEARCHING, CHOOSING, DOWNLOADING, FETCHED) and existing.query.casefold() == key \
                        and existing.upgrade == upgrade:
                    return existing
        job = self.store.add_job(query, upgrade)
        try:
            client.start_search(job.id, query, self.store.settings.search_seconds)
        except SlskdError as exc:
            self.store.update(job, status=FAILED, note=str(exc))
            raise
        return job

    def tick(self, locate: Callable[[Job], str | None]) -> None:
        if self.clock() < self._resume:
            return  # slskd was unreachable: give it a moment instead of asking again at once
        jobs = self.store.active()
        self._snapshot = None
        try:
            if any(j.status == DOWNLOADING for j in jobs):
                # One request for every download this round, instead of one per job (and per cancel).
                self._snapshot = {}
                for d in self.client().all_downloads():
                    self._snapshot.setdefault(d["username"], []).extend(d["files"])
            failed = False
            for job in jobs:
                try:
                    if job.status == SEARCHING:
                        self._tick_search(job)
                    elif job.status == DOWNLOADING:
                        self._tick_download(job)
                    elif job.status == FETCHED:
                        self._tick_fetched(job, locate)
                except SlskdError as exc:
                    failed = True
                    self.store.update(job, quiet=True, note=f"{exc} (trying again)")
        except SlskdError as exc:
            failed = True
            for job in jobs:
                self.store.update(job, quiet=True, note=f"{exc} (trying again)")
        finally:
            self._snapshot = None
        # Back off while slskd is struggling: 5 s, 10 s, 20 s... up to 2 minutes, then normal again.
        self._failures = self._failures + 1 if failed else 0
        self._resume = self.clock() + min(120, 5 * 2 ** (self._failures - 1)) if failed else 0.0

    def _tick_search(self, job: Job) -> None:
        client = self.client()
        state = client.search(job.id)
        elapsed = self.clock() - job.created
        if not state.get("isComplete") and "Completed" not in str(state.get("state") or "") \
                and elapsed < self.store.settings.search_seconds + 30:
            n = int(state.get("responseCount") or 0)
            self.store.update(job, quiet=True, note=f"Asking Soulseek… {n} {'user has' if n == 1 else 'users have'} answered")
            return
        cands = rank(client.responses(job.id), job.query, self.store.settings, self.store.blocked)
        client.delete_search(job.id)
        if not cands:
            note = ("No one shares a lossless copy that matches." if self.store.settings.lossless_only else
                    "No one shares anything that matches. Try fewer words, or a * wildcard for a filtered name.")
            self.store.update(job, status=NOTHING, note=note)
            self.notify(f"Soulseek: nothing for “{job.query}”", note, {"open": "soulseek"})
            return
        self.store.update(job, candidates=cands)
        if self.store.settings.choose:
            note = f"Found {len(cands)} {'source' if len(cands) == 1 else 'sources'}: pick one to download"
            self.store.update(job, status=CHOOSING, note=note)
            self.notify(f"Soulseek: pick a source for “{job.query}”", note, {"open": "soulseek", "job": job.id})
            return
        self.start(job, 0)

    def start(self, job: Job, index: int) -> None:
        """Download candidate ``index``."""
        cand = job.candidates[index]
        self.client().enqueue(cand["username"], cand["files"])
        tried = job.tried + ([index] if index not in job.tried else [])
        self.store.update(job, status=DOWNLOADING, pick=index, tried=tried, progress=0.0, eta=None, moved=self.clock(),
                          inbox_key="", note=f"Downloading {cand['name']} from {cand['username']}")

    def next_candidate(self, job: Job, reason: str) -> bool:
        """Move on to the best candidate not tried yet. False if there's none."""
        for i in range(len(job.candidates)):
            c = job.candidates[i]
            if i not in job.tried and block_key(c["username"], c["folder"]) not in self.store.blocked:
                try:
                    self.start(job, i)
                    return True
                except SlskdError:
                    job.tried.append(i)
        self.store.update(job, status=FAILED, note=f"{reason} No other candidates left: search again, maybe with other words.")
        self.notify(f"Soulseek: couldn't get “{job.query}”", job.note, {"open": "soulseek"})
        return False

    def _transfers(self, job: Job) -> list[dict]:
        cand = job.current
        wanted = {f["filename"] for f in cand["files"]}
        source = self._snapshot.get(cand["username"], []) if self._snapshot is not None \
            else self.client().downloads(cand["username"])
        return [t for t in source if t.get("filename") in wanted]

    def cancel_transfers(self, job: Job) -> None:
        """Stop the current source: cancel what's still coming, and note what already arrived
        (``job.leftovers``) so it can be cleared from the inbox instead of lingering there."""
        cand = job.current
        if cand is None:
            return
        client = self.client()
        transfers = self._transfers(job)
        arrived = [split_remote(t["filename"])[1] for t in transfers if "Succeeded" in str(t.get("state"))]
        if arrived:
            job.leftovers = job.leftovers + [{"folder": cand["name"], "files": arrived}]
        for t in transfers:
            if "Completed" not in str(t.get("state")):
                client.cancel(cand["username"], str(t.get("id")))

    def _tick_download(self, job: Job) -> None:
        cand = job.current
        transfers = self._transfers(job)
        total = sum(int(f.get("size") or 0) for f in cand["files"]) or 1
        done = sum(int(t.get("bytesTransferred") or 0) for t in transfers)
        states = [str(t.get("state") or "") for t in transfers]
        now = self.clock()
        if any(any(s in st for s in FAILED_STATES) for st in states):
            self.cancel_transfers(job)
            self.next_candidate(job, f"{cand['username']} couldn't send {cand['name']}.")
            return
        if len(transfers) == len(cand["files"]) and all("Succeeded" in st for st in states):
            self.store.update(job, status=FETCHED, progress=1.0, moved=now, note="Downloaded: moving into your inbox")
            return
        progress = min(done / total, 0.999)
        if progress > job.progress:
            est = transfer_progress(transfers + [{"size": f["size"]} for f in cand["files"]
                                                 if f["filename"] not in {t.get("filename") for t in transfers}], now)
            self.store.update(job, quiet=True, progress=progress, moved=now, eta=est["eta"] if est else None,
                              note=f"Downloading {cand['name']} from {cand['username']}")
        elif now - job.moved > STALL_SECONDS:
            self.cancel_transfers(job)
            queued = any("Queued" in st for st in states)
            self.next_candidate(job, f"{cand['username']} {'kept you waiting in their queue' if queued else 'stopped sending'}.")
        elif any("Queued" in st for st in states) and job.progress == 0:
            place = min((t.get("placeInQueue") for t in transfers if t.get("placeInQueue")), default=None)
            self.store.update(job, quiet=True, note=f"Waiting in {cand['username']}'s queue" + (f" (place {place})" if place else ""))

    def _tick_fetched(self, job: Job, locate: Callable[[Job], str | None]) -> None:
        key = locate(job)
        if key:
            self.store.update(job, status=ARRIVED, inbox_key=key, note="In your inbox: matching it")
            return
        if self.clock() - job.moved > ARRIVE_SECONDS:
            self.store.update(job, status=FAILED, note=(
                "slskd finished the download, but it never showed up in Codetta's inbox. "
                "Is slskd's downloads folder mounted at /inbox (and set as the inbox)?"))
            self.notify(f"Soulseek: “{job.query}” didn't reach the inbox", job.note, {"open": "soulseek"})

    def blocklist(self, username: str, folder: str) -> None:
        with self.store.lock:
            self.store.blocked.add(block_key(username, folder))
            self.store.save()


def basenames(job: Job) -> list[str]:
    cand = job.current
    return [split_remote(f["filename"])[1] for f in cand.get("files", [])] if cand else []
