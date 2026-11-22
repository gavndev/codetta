"""ReplayGain: measure how loud tracks and albums are, so players can play them all at one volume.

Loudness is measured the EBU R128 way (what ReplayGain 2.0 uses) with ffmpeg's ``ebur128``
filter, reading each file once. ffmpeg reports a loudness reading for every 100 ms (each over
the last 400 ms); Codetta gates them itself (blocks under -70 LUFS, then under 10 LU below the
average, don't count), so an album's loudness comes from all its tracks' readings together,
exactly as if it were one long track, without decoding anything twice.

Tags written, as rsgain, Picard and foobar2000 write them (ReplayGain 2.0, reference -18 LUFS):

* ``REPLAYGAIN_TRACK_GAIN`` "-6.48 dB" and ``REPLAYGAIN_TRACK_PEAK`` "0.988553" (sample peak, 1.0 = full scale)
* ``REPLAYGAIN_ALBUM_GAIN`` / ``REPLAYGAIN_ALBUM_PEAK`` when tracks are measured as an album
* Opus instead gets ``R128_TRACK_GAIN`` / ``R128_ALBUM_GAIN`` (RFC 7845: a whole number in 1/256 dB,
  relative to -23 LUFS), which is what Opus players read.

Results are remembered per file (path, size, modification time), so the preview and the save
measure once.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess  # nosec B404: runs only ffmpeg, never a shell
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

REFERENCE_LUFS = -18.0  # ReplayGain 2.0
OPUS_REFERENCE_LUFS = -23.0  # R128_* tags (RFC 7845)
ABSOLUTE_GATE = -70.0
RELATIVE_GATE = -10.0
TIMEOUT_SECONDS = 600  # per file (a three-hour DJ mix still reads in well under this)
WORKERS = max(1, min(4, (os.cpu_count() or 2)))

_M = re.compile(r"\bM:\s*(-?\d+(?:\.\d+)?)")
_PEAK = re.compile(r"Peak:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dBFS")

TAGS = ("replaygain_track_gain", "replaygain_track_peak", "replaygain_album_gain", "replaygain_album_peak",
        "r128_track_gain", "r128_album_gain")


class LoudnessError(Exception):
    """ffmpeg is missing, or couldn't read this file; the message is for people."""


def find_ffmpeg(configured: str | None = None) -> str | None:
    if configured:
        return configured if os.access(configured, os.X_OK) else None
    return shutil.which("ffmpeg")


@dataclass
class Measured:
    loudness: float  # integrated, LUFS (-inf for silence)
    peak: float  # sample peak, linear (1.0 = full scale)
    blocks: list[float] = field(default_factory=list, repr=False)  # 400 ms readings, LUFS


def integrated(blocks: Iterable[float]) -> float:
    """EBU R128 gated loudness of 400 ms readings (LUFS). -inf when everything is under the gate."""
    kept = [b for b in blocks if b >= ABSOLUTE_GATE]
    if not kept:
        return -math.inf

    def mean(xs: list[float]) -> float:
        return 10 * math.log10(sum(10 ** (x / 10) for x in xs) / len(xs))

    gate = mean(kept) + RELATIVE_GATE
    kept = [b for b in kept if b >= gate]
    return mean(kept) if kept else -math.inf


class Meter:
    """Measures files with ffmpeg, remembering what it measured."""

    def __init__(self, ffmpeg: str | None, run: Callable[[list[str]], str] | None = None) -> None:
        self.ffmpeg = ffmpeg
        self._run = run or self._ffmpeg_stderr
        self._cache: dict[tuple[str, int, int], Measured] = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg)

    @staticmethod
    def _ffmpeg_stderr(cmd: list[str]) -> str:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",  # noqa: S603
                                  timeout=TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired as exc:
            raise LoudnessError("Took too long to read") from exc
        except OSError as exc:
            raise LoudnessError(f"Couldn't run ffmpeg: {exc}") from exc
        if proc.returncode != 0:
            last = (proc.stderr.strip().splitlines() or ["unknown error"])[-1]
            raise LoudnessError(f"ffmpeg couldn't read it: {last[:200]}")
        return proc.stderr

    def measure(self, path: Path) -> Measured:
        if not self.ffmpeg:
            raise LoudnessError("ffmpeg isn't installed on this server (it's included in the Docker image)")
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        out = self._run([self.ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-v", "verbose", "-i", str(path),
                         "-map", "0:a:0", "-af", "ebur128=peak=sample:framelog=verbose", "-f", "null", "-"])
        blocks = [float(m.group(1)) for m in _M.finditer(out)]
        peaks = _PEAK.findall(out)
        if not blocks or not peaks:
            raise LoudnessError("ffmpeg didn't report a loudness for it (is there any audio in it?)")
        peak_db = peaks[-1]
        result = Measured(integrated(blocks), 0.0 if "inf" in peak_db else 10 ** (float(peak_db) / 20), blocks)
        with self._lock:
            if len(self._cache) > 20000:
                self._cache.clear()
            self._cache[key] = result
        return result

    def measure_many(self, paths: list[Path]) -> dict[Path, Measured | LoudnessError]:
        """Several files at once (a few ffmpeg processes side by side)."""
        def one(p: Path) -> Measured | LoudnessError:
            try:
                return self.measure(p)
            except (LoudnessError, OSError) as exc:
                return exc if isinstance(exc, LoudnessError) else LoudnessError(str(exc))
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            return dict(zip(paths, pool.map(one, paths), strict=True))


def album(measured: Iterable[Measured]) -> Measured:
    """An album's loudness: all its tracks' readings gated together; its peak is the loudest track's."""
    ms = list(measured)
    blocks = [b for m in ms for b in m.blocks]
    return Measured(integrated(blocks), max((m.peak for m in ms), default=0.0), blocks)


def gain_text(loudness: float) -> str | None:
    return None if math.isinf(loudness) else f"{REFERENCE_LUFS - loudness:.2f} dB"


def r128_value(loudness: float) -> str | None:
    if math.isinf(loudness):
        return None
    q78 = round((OPUS_REFERENCE_LUFS - loudness) * 256)
    return str(max(-32768, min(32767, q78)))


def tag_changes(fmt: str, track: Measured, whole: Measured | None) -> dict[str, list[str] | None]:
    """The tags to write for one file. ``whole`` is its album (None: measured on its own, so any
    album values are removed, since they'd describe some other grouping)."""
    if fmt == "opus":
        changes: dict[str, list[str] | None] = {
            "r128_track_gain": [v] if (v := r128_value(track.loudness)) else None,
            "r128_album_gain": [v] if whole and (v := r128_value(whole.loudness)) else None,
        }
        return changes
    changes = {
        "replaygain_track_gain": [v] if (v := gain_text(track.loudness)) else None,
        "replaygain_track_peak": [f"{track.peak:.6f}"],
        "replaygain_album_gain": [v] if whole and (v := gain_text(whole.loudness)) else None,
        "replaygain_album_peak": [f"{whole.peak:.6f}"] if whole else None,
    }
    return changes
