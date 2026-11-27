"""AcoustID: identify tracks by how they sound.

Two steps, only the second goes online:

1. **Fingerprint** each file on this server with Chromaprint's ``fpcalc``
   (it decodes the first two minutes and boils the sound down to a short
   code). The audio never leaves the server.
2. **Look up** the fingerprints on AcoustID, which answers with the
   MusicBrainz *recordings* that sound like that, and the releases they're on.

The results feed the MusicBrainz match: releases that contain most of a
folder's recordings become the candidates, and files pair with tracks by
recording ID, which beats guessing from track numbers.

``fpcalc`` ships in the Docker image (Chromaprint's official static build).
Outside Docker: ``apt install libchromaprint-tools`` or ``brew install
chromaprint``, or point ``CODETTA_FPCALC`` at the binary.

AcoustID is free for non-commercial use, at most 3 requests per second.

From 2027 a lookup needs the person's own AcoustID key as well as Codetta's
application key (``AcoustIDAccount``). Codetta gets one by *linking*: it asks
AcoustID for a key and a short code, the person approves Codetta on
acoustid.org, and the key starts working. A key copied from acoustid.org, or
set with CODETTA_ACOUSTID_USER_KEY, works too.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404: runs only the fpcalc binary, never a shell
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from codetta.core.musicbrainz import MBID_RE
from codetta.core.providers import ProviderError

LOOKUP_URL = "https://api.acoustid.org/v2/lookup"
LINK_URL = "https://api.acoustid.org/v2/user/request_link"
STATUS_URL = "https://api.acoustid.org/v2/user/link_status"
USER_KEY_REQUIRED = 21  # AcoustID's error number for "this lookup needs the user's own key"
# Codetta's application key (registered at acoustid.org for this open-source
# app, meant to ship with it like Picard's and beets'). CODETTA_ACOUSTID_KEY overrides it.
DEFAULT_KEY = "CvHAxs0B2q"
BATCH = 20  # fingerprints per request
FPCALC_TIMEOUT = 60  # seconds per file; a damaged file mustn't hang the request
MIN_SCORE = 0.5  # AcoustID's confidence below which a result is ignored
MAX_FINGERPRINT_CHARS = 20_000


class FingerprintError(Exception):
    """fpcalc is missing, or couldn't read this file."""


class UserKeyNeeded(ProviderError):
    """AcoustID wants the person's own key (none yet, or the one Codetta had stopped working)."""


def find_fpcalc(configured: str | None = None) -> str | None:
    if configured:
        return configured if os.access(configured, os.X_OK) else None
    return shutil.which("fpcalc")


@dataclass(frozen=True)
class Fingerprint:
    duration: float
    code: str


Runner = Callable[[list[str]], str]  # argv -> stdout; replaceable in tests


def _run(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=FPCALC_TIMEOUT, check=False)  # nosec B603: fixed argv
    except subprocess.TimeoutExpired as exc:
        raise FingerprintError("Took too long to read") from exc
    except OSError as exc:
        raise FingerprintError(f"Couldn't run fpcalc: {exc.strerror or exc}") from exc
    if done.returncode != 0:
        msg = done.stderr.decode("utf-8", "replace").strip().removeprefix("ERROR: ")
        raise FingerprintError(msg[:200] or "fpcalc couldn't read this file")
    return done.stdout.decode("utf-8", "replace")


class Fingerprinter:
    """Runs fpcalc, a few files at a time, and remembers results per file version."""

    def __init__(self, fpcalc: str | None, run: Runner = _run, workers: int = 4) -> None:
        self.fpcalc = fpcalc
        self.run = run
        self.workers = max(1, workers)
        self._cache: OrderedDict[tuple[str, int, int], Fingerprint] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.fpcalc is not None

    def one(self, path: Path) -> Fingerprint:
        if not self.fpcalc:
            raise FingerprintError("The fingerprint tool (fpcalc) isn't installed on this server")
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        # Paths are absolute (resolved inside the library), so they can't be read as options.
        out = self.run([self.fpcalc, "-json", "-length", "120", str(path)])
        try:
            data = json.loads(out)
            fp = Fingerprint(float(data["duration"]), str(data["fingerprint"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise FingerprintError("fpcalc gave an unexpected answer") from exc
        if not fp.code or len(fp.code) > MAX_FINGERPRINT_CHARS or fp.duration <= 0:
            raise FingerprintError("Too short or too quiet to recognise")
        with self._lock:
            self._cache[key] = fp
            while len(self._cache) > 5000:
                self._cache.popitem(last=False)
        return fp

    def many(self, paths: list[Path]) -> list[Fingerprint | FingerprintError]:
        def safe(p: Path):
            try:
                return self.one(p)
            except FingerprintError as exc:
                return exc
            except OSError as exc:
                return FingerprintError(f"Couldn't read the file: {exc.strerror or exc}")

        with ThreadPoolExecutor(max_workers=min(self.workers, max(1, len(paths)))) as pool:
            return list(pool.map(safe, paths))


@dataclass
class Recording:
    id: str
    score: float  # AcoustID's confidence, 0..1
    title: str = ""
    artist: str = ""
    duration: float | None = None
    releases: list[str] = field(default_factory=list)


Poster = Callable[[dict[str, str]], object]  # form -> parsed JSON


class AcoustID:
    def __init__(self, post: Poster, key: str = DEFAULT_KEY, min_interval: float = 1 / 3,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 account: AcoustIDAccount | None = None) -> None:
        self.post = post
        self.key = key
        self.account = account
        self.min_interval = min_interval
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._last = -1e9

    def lookup(self, fingerprints: list[Fingerprint]) -> list[list[Recording]]:
        """For each fingerprint, the recordings it matches (best first)."""
        out: list[list[Recording]] = []
        for start in range(0, len(fingerprints), BATCH):
            chunk = fingerprints[start:start + BATCH]
            # batch=1 makes AcoustID answer every fingerprint.N (without it only the first).
            form = {"client": self.key, "meta": "recordings releaseids", "format": "json", "batch": "1"}
            user = self.account.usable_key() if self.account else ""
            if user:  # in the form body (POSTed, never in an address), as AcoustID's "user" parameter
                form["user"] = user
            for i, fp in enumerate(chunk):
                form[f"duration.{i}"] = str(round(fp.duration))
                form[f"fingerprint.{i}"] = fp.code
            with self._lock:
                wait = self._last + self.min_interval - self._clock()
                if wait > 0:
                    self._sleep(wait)
                try:
                    data = self.post(form)
                    parsed = _parse_batch(data, len(chunk))
                except ProviderError as exc:
                    raise self._explain(exc, bool(user)) from exc
                finally:
                    self._last = self._clock()
            out.extend(parsed)
        return out

    def _explain(self, exc: ProviderError, sent_user: bool) -> ProviderError:
        """Turn "needs the user's key" (or a key that stopped working) into what to do about it."""
        if exc.code == USER_KEY_REQUIRED:
            return UserKeyNeeded("AcoustID now needs your own free account. Connect it in Settings → Connections → AcoustID.",
                                 code=exc.code)
        if sent_user and exc.code is not None and self.account and not self.account.locked:
            try:  # the key may have been disconnected on acoustid.org: ask, and forget it if so
                gone = self.account.refresh(force=True) == "none"
            except ProviderError:
                gone = False
            if gone:
                return UserKeyNeeded(GONE_TEXT.get(self.account.outcome, GONE_TEXT["unknown"]), code=exc.code)
        return exc


def _api_error(data: object) -> ProviderError:
    err = (data.get("error") or {}) if isinstance(data, dict) else {}
    msg, code = (err.get("message"), err.get("code")) if isinstance(err, dict) else (None, None)
    return ProviderError(f"AcoustID answered with an error ({msg or 'unexpected answer'})",
                         code=code if isinstance(code, int) else None)


def _parse_batch(data: object, n: int) -> list[list[Recording]]:
    if not isinstance(data, dict) or data.get("status") != "ok":
        raise _api_error(data)
    per_index: dict[int, list] = {}
    if isinstance(data.get("fingerprints"), list):
        for item in data["fingerprints"]:
            if isinstance(item, dict):
                try:
                    per_index[int(item.get("index"))] = item.get("results") or []
                except (TypeError, ValueError):
                    continue
    elif isinstance(data.get("results"), list):  # a single lookup
        per_index[0] = data["results"]
    return [_recordings(per_index.get(i, [])) for i in range(n)]


def _recordings(results: list) -> list[Recording]:
    best: dict[str, Recording] = {}
    for res in results:
        if not isinstance(res, dict):
            continue
        score = res.get("score")
        if not isinstance(score, (int, float)) or score < MIN_SCORE:
            continue
        for rec in res.get("recordings") or []:
            if not isinstance(rec, dict) or not MBID_RE.match(str(rec.get("id", ""))):
                continue
            releases = [r.get("id") for r in rec.get("releases") or [] if isinstance(r, dict)]
            artists = [a.get("name") for a in rec.get("artists") or [] if isinstance(a, dict) and a.get("name")]
            r = Recording(
                id=rec["id"], score=float(score), title=str(rec.get("title") or "")[:500],
                artist=", ".join(artists)[:500],
                duration=rec.get("duration") if isinstance(rec.get("duration"), (int, float)) else None,
                releases=[x for x in releases if isinstance(x, str) and MBID_RE.match(x)],
            )
            if r.id not in best or r.score > best[r.id].score:
                best[r.id] = r
    return sorted(best.values(), key=lambda r: -r.score)


def rank_releases(per_file: dict[str, list[Recording]], limit: int = 10) -> list[tuple[str, int]]:
    """Releases ordered by how many of these files they contain: [(release id, files)]."""
    counts: dict[str, int] = {}
    for recs in per_file.values():
        seen = {rel for r in recs for rel in r.releases}
        for rel in seen:
            counts[rel] = counts.get(rel, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:limit]


# --- The person's own AcoustID key ---------------------------------------------------------

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{4,100}$")
ApiCall = Callable[[str, dict[str, str]], object]  # (url, form) -> parsed JSON
GONE = {"declined", "expired", "revoked", "unknown"}  # AcoustID's states of a key that won't work
GONE_TEXT = {  # why a lookup failed, when the key stopped working
    "declined": "You declined Codetta on acoustid.org. To identify by sound, connect your AcoustID account in Settings → Connections → AcoustID.",
    "expired": "Codetta's AcoustID key expired. Connect your AcoustID account again in Settings → Connections → AcoustID.",
    "revoked": "Codetta was disconnected from your AcoustID account. Connect it again in Settings → Connections → AcoustID.",
    "unknown": "AcoustID no longer knows Codetta's key. Connect your AcoustID account again in Settings → Connections → AcoustID.",
}
STATUS_EVERY = 3.0  # seconds: AcoustID asks for a check "every few seconds" while a link waits


class AcoustIDAccount:
    """The person's AcoustID key, in acoustid.json in the config folder (owner only).

    ``state``: "none", "pending" (linking: waiting for the person to approve on
    acoustid.org; the key isn't sent until then) or "approved". ``how``: "linked",
    "pasted" or "env" (CODETTA_ACOUSTID_USER_KEY, which locks it)."""

    def __init__(self, file: Path, api: ApiCall, client: str, env_key: str | None = None,
                 clock: Callable[[], float] = time.monotonic, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.file, self.api, self.client = file, api, client
        self.env = (env_key or "").strip() or None
        self._clock, self._now = clock, now
        self.lock = threading.Lock()
        self.outcome = ""  # why the last key went away (one of GONE), shown once in Settings
        self._checked = -1e9
        self.data: dict = {}
        try:
            data = json.loads(file.read_text("utf-8"))
            if isinstance(data, dict) and KEY_RE.match(str(data.get("key") or "")) and data.get("state") in ("pending", "approved"):
                self.data = {k: data[k] for k in ("key", "state", "how", "code", "url", "expires") if k in data}
        except (OSError, ValueError):
            pass

    @property
    def locked(self) -> bool:
        return self.env is not None

    @property
    def state(self) -> str:
        return "approved" if self.env else self.data.get("state", "none")

    def usable_key(self) -> str:
        """The key to send with a lookup: only one that works (a waiting one is turned down like a wrong key)."""
        if self.env:
            return self.env
        return self.data["key"] if self.data.get("state") == "approved" else ""

    def _save(self, data: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".acoustid-", dir=self.file.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.data = data

    def forget(self, outcome: str = "") -> None:
        with self.lock:
            self._save({})
            self.outcome = outcome

    def _call(self, url: str, form: dict[str, str]) -> dict:
        data = self.api(url, {"client": self.client, "format": "json", **form})
        if not isinstance(data, dict) or data.get("status") != "ok":
            raise _api_error(data)
        return data

    def key_state(self, key: str) -> tuple[str, str]:
        """What AcoustID says about a key: (state, expires)."""
        info = self._call(STATUS_URL, {"user": key}).get("key")
        info = info if isinstance(info, dict) else {}
        return str(info.get("state") or "unknown"), str(info.get("expires") or "")

    def request_link(self, device: str, return_url: str = "") -> dict:
        """Ask AcoustID for a key to link: saved at once, working once the person approves it."""
        form = {"device": device[:100] or "Codetta"}
        if return_url:
            form["return_url"] = return_url
        data = self._call(LINK_URL, form)
        user, link = data.get("user"), data.get("link")
        if not isinstance(link, dict) and isinstance(user, dict):
            link = user.get("link")  # the live API puts it inside "user"; its docs show it beside it
        key = user.get("apikey") if isinstance(user, dict) else None
        code = link.get("code") if isinstance(link, dict) else None
        url = link.get("url") if isinstance(link, dict) else None
        if not (isinstance(key, str) and KEY_RE.match(key) and isinstance(code, str) and 0 < len(code) <= 40
                and isinstance(url, str) and url.startswith("https://acoustid.org/") and len(url) <= 500):
            raise ProviderError("AcoustID sent an unexpected answer")
        with self.lock:
            self._save({"key": key, "state": "pending", "how": "linked", "code": code, "url": url,
                        "expires": str(link.get("expires") or "")[:40]})
            self.outcome = ""
            self._checked = self._clock()
        return self.data

    def use_key(self, key: str) -> str:
        """A key the person copied from acoustid.org: kept only if AcoustID says it works."""
        if not KEY_RE.match(key):
            raise ValueError("That doesn't look like an AcoustID key (copy it from your account page on acoustid.org).")
        state, _ = self.key_state(key)
        if state == "approved":
            with self.lock:
                self._save({"key": key, "state": "approved", "how": "pasted"})
                self.outcome = ""
        return state

    def _expired(self) -> bool:
        try:
            return datetime.fromisoformat(self.data.get("expires", "")) < self._now()
        except (TypeError, ValueError):
            return False

    def refresh(self, force: bool = False) -> str:
        """Check a waiting (or, with ``force``, any) key with AcoustID; a key it won't take is forgotten."""
        if self.env or not self.data.get("key"):
            return self.state
        if self.data.get("state") == "pending" and self._expired():
            self.forget("expired")
            return "none"
        if not force and (self.data.get("state") != "pending" or self._clock() - self._checked < STATUS_EVERY):
            return self.state
        self._checked = self._clock()
        key = self.data["key"]
        state, _ = self.key_state(key)
        with self.lock:
            if self.data.get("key") != key:
                return self.state  # replaced meanwhile
            if state == "approved" and self.data.get("state") != "approved":
                self._save({k: v for k, v in {**self.data, "state": "approved"}.items() if k not in ("code", "url", "expires")})
            elif state in GONE:
                self._save({})
                self.outcome = state
        return self.state

    def out(self) -> dict:
        """For the page: never the key itself."""
        d = {"state": self.state, "how": "env" if self.env else self.data.get("how", ""), "locked": self.locked,
             "outcome": self.outcome if self.state == "none" else ""}  # one of GONE: the page says why
        if self.state == "pending":
            d["link"] = {k: self.data.get(k, "") for k in ("code", "url", "expires")}
        return d
