"""Converting songs on the fly for music apps on mobile data.

Apps ask for a format (``format=mp3|opus|aac``) and/or a maximum bitrate (``maxBitRate=128``).
Codetta's bundled ffmpeg converts with LAME (MP3), libopus (Opus) or its own AAC encoder and
streams the result as it's made, so playback starts at once and nothing is written to disk.

Rules (as Navidrome does): ``format=raw`` always sends the original; a requested format the
song is already in, within the bitrate cap, sends the original; otherwise the song is
converted, at the requested bitrate or a sensible default. At most a few conversions run at
once (the server may be small); when they're all busy, or the encoder isn't available, the
original is sent instead, which always plays.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

# format -> (ffmpeg encoder, ffmpeg muxer, content type, default kbps, min, max)
FORMATS = {
    "mp3": ("libmp3lame", "mp3", "audio/mpeg", 192, 32, 320),
    "opus": ("libopus", "ogg", "audio/ogg", 128, 32, 256),
    "aac": ("aac", "adts", "audio/aac", 192, 32, 320),
}
ALIASES = {"m4a": "aac", "ogg": "opus", "oga": "opus"}
LOSSLESS = {"flac", "wav", "aiff", "aif", "ape", "wv", "tta", "dsf", "dff", "alac"}
MAX_JOBS = 3
CHUNK = 64 * 1024

Popen = Callable[..., subprocess.Popen]


@dataclass
class Plan:
    fmt: str  # key of FORMATS
    kbps: int

    @property
    def content_type(self) -> str:
        return FORMATS[self.fmt][2]


class Transcoder:
    def __init__(self, ffmpeg: str | None, popen: Popen = subprocess.Popen, max_jobs: int = MAX_JOBS) -> None:
        self.ffmpeg = ffmpeg
        self.popen = popen
        self._slots = threading.BoundedSemaphore(max_jobs)
        self._encoders: set[str] | None = None
        self._lock = threading.Lock()

    def encoders(self) -> set[str]:
        """The encoders this ffmpeg has (asked once)."""
        with self._lock:
            if self._encoders is None:
                self._encoders = set()
                if self.ffmpeg:
                    try:
                        out = subprocess.run([self.ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                             text=True, timeout=10, check=False).stdout
                        for line in out.splitlines():
                            parts = line.split()
                            if len(parts) >= 2 and parts[0].startswith("A"):
                                self._encoders.add(parts[1])
                    except (OSError, subprocess.SubprocessError):
                        pass
            return self._encoders

    def formats(self) -> list[str]:
        have = self.encoders()
        return [f for f, spec in FORMATS.items() if spec[0] in have]

    def plan(self, requested: str | None, max_kbps: int, suffix: str, file_kbps: int, default: str = "mp3") -> Plan | None:
        """What to send: a Plan to convert, or None for the original file."""
        fmt = ALIASES.get((requested or "").lower(), (requested or "").lower())
        suffix = ALIASES.get(suffix.lower(), suffix.lower())
        if fmt == "raw":
            return None
        if fmt and fmt not in FORMATS:
            fmt = ""  # a format we can't make (e.g. "flv"): decide by bitrate alone
        lossless = suffix in LOSSLESS
        over_cap = max_kbps > 0 and (lossless or file_kbps > max_kbps)
        if fmt and fmt == suffix and not over_cap:
            return None
        if not fmt:
            if not over_cap:
                return None
            fmt = default if default in FORMATS else "mp3"
        enc, _, _, base, lo, hi = FORMATS[fmt]
        if enc not in self.encoders():
            fallback = next((f for f in ("opus", "aac", "mp3") if FORMATS[f][0] in self.encoders()), None)
            if fallback is None:
                return None
            fmt = fallback
            enc, _, _, base, lo, hi = FORMATS[fmt]
        kbps = max_kbps if max_kbps > 0 else base
        return Plan(fmt, max(lo, min(hi, kbps)))

    def stream(self, path: Path, plan: Plan, offset: float = 0.0) -> Iterator[bytes] | None:
        """The converted song as it's made, or None when every slot is busy (send the original)."""
        if not self.ffmpeg or not self._slots.acquire(timeout=5):
            return None
        enc, muxer = FORMATS[plan.fmt][0], FORMATS[plan.fmt][1]
        args = [self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
        if offset > 0:
            args += ["-ss", f"{offset:.3f}"]
        args += ["-i", str(path), "-map", "0:a:0", "-vn", "-c:a", enc, "-b:a", f"{plan.kbps}k"]
        if plan.fmt == "mp3":
            args += ["-ar", "44100"]  # LAME refuses some rates (e.g. DSD's) at low bitrates
        args += ["-f", muxer, "pipe:1"]
        try:
            proc = self.popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError:
            self._slots.release()
            return None

        def chunks() -> Iterator[bytes]:
            try:
                while True:
                    data = proc.stdout.read(CHUNK)
                    if not data:
                        break
                    yield data
            finally:  # done, or the app hung up: never leave ffmpeg running
                if proc.poll() is None:
                    proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                self._slots.release()

        return chunks()
