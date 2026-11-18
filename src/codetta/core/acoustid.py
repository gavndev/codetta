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
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404: runs only the fpcalc binary, never a shell
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from codetta.core.musicbrainz import MBID_RE
from codetta.core.providers import ProviderError

LOOKUP_URL = "https://api.acoustid.org/v2/lookup"
# Codetta's application key (registered at acoustid.org for this open-source
# app, meant to ship with it like Picard's and beets'). CODETTA_ACOUSTID_KEY overrides it.
DEFAULT_KEY = "CvHAxs0B2q"
BATCH = 20  # fingerprints per request
FPCALC_TIMEOUT = 60  # seconds per file; a damaged file mustn't hang the request
MIN_SCORE = 0.5  # AcoustID's confidence below which a result is ignored
MAX_FINGERPRINT_CHARS = 20_000


class FingerprintError(Exception):
    """fpcalc is missing, or couldn't read this file."""


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
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.post = post
        self.key = key
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
            for i, fp in enumerate(chunk):
                form[f"duration.{i}"] = str(round(fp.duration))
                form[f"fingerprint.{i}"] = fp.code
            with self._lock:
                wait = self._last + self.min_interval - self._clock()
                if wait > 0:
                    self._sleep(wait)
                try:
                    data = self.post(form)
                finally:
                    self._last = self._clock()
            out.extend(_parse_batch(data, len(chunk)))
        return out


def _parse_batch(data: object, n: int) -> list[list[Recording]]:
    if not isinstance(data, dict) or data.get("status") != "ok":
        msg = (data.get("error") or {}).get("message") if isinstance(data, dict) else None
        raise ProviderError(f"AcoustID answered with an error ({msg or 'unexpected answer'})")
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
