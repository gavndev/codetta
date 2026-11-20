"""Connections: the only parts of Codetta that talk to the internet.

Codetta on its own is fully offline. Each online feature is a *connection*
the user opts in to: on the first-run card, in Account → Connections, or with
an environment variable. Everything is off until someone turns it on.

Who decides, strongest first:
  1. ``CODETTA_OFFLINE=on`` blocks every connection (a hard guarantee).
  2. A connection's own env var (``CODETTA_MUSICBRAINZ=on|off`` ...) sets it
     and locks the switch in the UI.
  3. Otherwise the user's choice, saved in ``connections.json`` in the config
     folder. No file yet means "not chosen": the UI asks once.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Connection:
    id: str
    name: str
    summary: str  # what it gives you
    sends: str  # what leaves the server, in plain words
    hosts: tuple[str, ...]
    env: str  # CODETTA_<env> sets it from the environment


CONNECTIONS: tuple[Connection, ...] = (
    Connection(
        "musicbrainz", "MusicBrainz",
        "Match albums to the open music encyclopedia: official titles, credits, dates, labels, "
        "catalog numbers, MusicBrainz IDs and cover art.",
        "The album and artist names you search for, and the IDs of releases you pick.",
        ("musicbrainz.org", "coverartarchive.org"), "MUSICBRAINZ",
    ),
    Connection(
        "deezer", "Deezer",
        "Album details and big covers from Deezer's catalogue, for albums MusicBrainz doesn't have "
        "yet (new releases often appear here first), or when it's down. No account needed.",
        "The album and artist names you search for, and the IDs of albums you pick.",
        ("api.deezer.com", "cdn-images.dzcdn.net"), "DEEZER",
    ),
    Connection(
        "itunes", "iTunes",
        "Album details and high-resolution covers from Apple's iTunes catalogue, as another fallback "
        "next to MusicBrainz and Deezer. No account needed.",
        "The album and artist names you search for, and the IDs of albums you pick.",
        ("itunes.apple.com", "is1-ssl.mzstatic.com"), "ITUNES",
    ),
    Connection(
        "acoustid", "AcoustID: identify by sound",
        "Recognise tracks by how they sound, even untagged ones, to find the right MusicBrainz "
        "release. Works together with MusicBrainz.",
        "A fingerprint of each track's sound (a short code, never the audio itself) and its length, "
        "when you press Listen.",
        ("api.acoustid.org",), "ACOUSTID",
    ),
    Connection(
        "lyrics", "LRCLIB lyrics",
        "Find plain and synced lyrics for a track.",
        "The track's artist, title, album and length, when you press Find lyrics.",
        ("lrclib.net",), "LYRICS_LOOKUP",
    ),
    Connection(
        "slskd", "Soulseek (slskd)",
        "Find and download music on the Soulseek network through your own slskd: type !slskd in the "
        "search bar, or use Find in slskd on an album. Downloads land in the inbox for a review.",
        "Your searches go to your slskd, which asks other Soulseek users. Downloads come from them, "
        "and slskd shares the folders you chose with them in return.",
        ("your slskd server", "the Soulseek network"), "SLSKD",
    ),
    Connection(
        "updates", "Update check",
        "Tell you when a new version of Codetta is out.",
        "Nothing about you or your music: it asks GitHub for the latest release, twice a day.",
        ("api.github.com",), "UPDATE_CHECK",
    ),
)
BY_ID = {c.id: c for c in CONNECTIONS}

ON = ("on", "true", "1", "yes")
OFF = ("off", "false", "0", "no")


def parse_switch(value: str | None) -> bool | None:
    """ "on"/"off" (and friends) -> True/False; unset or unrecognised -> None."""
    if value is None:
        return None
    value = value.strip().lower()
    return True if value in ON else False if value in OFF else None


class ConnectionStore:
    def __init__(self, file: Path, offline: bool = False, forced: dict[str, bool] | None = None) -> None:
        self.file = file
        self.offline = offline  # CODETTA_OFFLINE
        self.forced = {k: v for k, v in (forced or {}).items() if k in BY_ID and v is not None}
        self._lock = threading.Lock()
        self._chosen, self._enabled = self._load()

    def _load(self) -> tuple[bool, dict[str, bool]]:
        try:
            data = json.loads(self.file.read_text("utf-8"))
        except (OSError, ValueError):
            return False, {}
        if not isinstance(data, dict):
            return False, {}
        raw = data.get("enabled")
        enabled = {k: v for k, v in raw.items() if k in BY_ID and isinstance(v, bool)} if isinstance(raw, dict) else {}
        return bool(data.get("chosen")), enabled

    def locked_by(self, cid: str) -> str | None:
        """The env var that decides this connection, if any."""
        if self.offline:
            return "CODETTA_OFFLINE"
        if cid in self.forced:
            return f"CODETTA_{BY_ID[cid].env}"
        return None

    def enabled(self, cid: str) -> bool:
        if self.offline:
            return False
        if cid in self.forced:
            return self.forced[cid]
        with self._lock:
            return self._enabled.get(cid, False)

    @property
    def needs_choice(self) -> bool:
        """Show the first-run card? Not if the admin already decided everything by env."""
        if self.offline or all(c.id in self.forced for c in CONNECTIONS):
            return False
        with self._lock:
            return not self._chosen

    def status(self) -> dict:
        return {
            "offline": not any(self.enabled(c.id) for c in CONNECTIONS),
            "offline_locked": self.offline,
            "needs_choice": self.needs_choice,
            "connections": [
                {
                    "id": c.id, "name": c.name, "summary": c.summary, "sends": c.sends,
                    "hosts": list(c.hosts), "enabled": self.enabled(c.id), "locked_by": self.locked_by(c.id),
                }
                for c in CONNECTIONS
            ],
        }

    def save(self, enabled: dict[str, bool]) -> None:
        """Store the user's choices (switches set by env are left as the env says)."""
        with self._lock:
            for cid, on in enabled.items():
                if cid in BY_ID and self.locked_by(cid) is None:
                    self._enabled[cid] = bool(on)
            self._chosen = True
            data = {"chosen": True, "enabled": dict(sorted(self._enabled.items()))}
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".connections-", dir=self.file.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
