"""AudioMuse-AI: songs that sound alike, from the user's own AudioMuse-AI server.

AudioMuse-AI (https://github.com/NeptuneHub/AudioMuse-AI) listens to a library through a
music server (Navidrome, Jellyfin, ...) and learns how each song sounds. Autoplay asks it
for songs similar to the one playing (by title and artist) and plays the ones that are in
Codetta's library too. Nothing leaves the user's network.

With sign-in on, AudioMuse-AI only answers API callers that send its API token (the
``API_TOKEN`` setting of the AudioMuse-AI container) as a Bearer token.

Settings (address, token) live in ``audiomuse.json`` in the config folder, readable by its
owner only. The token is never sent back to the page.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from codetta.core.lidarr import clean_url

TIMEOUT = 8  # seconds: Autoplay would rather fall back to another source than keep music waiting


class AudioMuseError(Exception):
    """AudioMuse-AI couldn't be reached or said no; the message is for people."""


Request = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]  # (method, url, headers, body) -> (status, body)


def http_request(method: str, url: str, headers: dict, body: bytes | None, timeout: float = TIMEOUT) -> tuple[int, bytes]:
    if not url.lower().startswith(("http://", "https://")):  # an address set by env var skips the page's check
        raise AudioMuseError("The address must start with http:// or https://")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (the admin's own server)
            return resp.status, resp.read(5_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(100_000) if exc.fp else b""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise AudioMuseError(f"Couldn't reach AudioMuse-AI: {reason}") from exc


class AudioMuseClient:
    def __init__(self, url: str, token: str, request: Request = http_request) -> None:
        self.base = clean_url(url)
        self.token = token
        self.request = request

    def call(self, path: str, query: dict | None = None) -> object:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        status, raw = self.request("GET", url, headers, None)
        if status in (401, 403):
            raise AudioMuseError("AudioMuse-AI turned down the token. Use the API_TOKEN set on the AudioMuse-AI "
                                 "container (or turn its sign-in off).")
        if status == 404:
            return None  # a song it doesn't know, or an older AudioMuse-AI
        if status >= 400:
            raise AudioMuseError(f"AudioMuse-AI said {status}")
        try:
            return json.loads(raw) if raw.strip() else None
        except ValueError as exc:
            raise AudioMuseError("AudioMuse-AI sent something that isn't JSON. Is the address pointing at "
                                 "AudioMuse-AI (usually port 8000)?") from exc

    def check(self) -> None:
        """Raises AudioMuseError unless the address and token work."""
        self.call("/api/search_tracks", {"search_query": "a"})

    def similar(self, title: str, artist: str, n: int = 30) -> list[dict]:
        """Songs that sound like ``title`` by ``artist``: [{"title", "artist", "album"}], closest first."""
        r = self.call("/api/similar_tracks", {"title": title, "artist": artist, "n": n, "eliminate_duplicates": "true"})
        out = []
        for x in r if isinstance(r, list) else []:
            if isinstance(x, dict) and x.get("title") and x.get("author"):
                album = str(x.get("album") or "")
                out.append({"title": str(x["title"]), "artist": str(x["author"]),
                            "album": "" if album.lower() == "unknown" else album})
        return out


# --- Settings -------------------------------------------------------------------------


@dataclass
class AudioMuseSettings:
    url: str = ""  # e.g. http://192.168.1.50:8000
    token: str = ""


class AudioMuseStore:
    """Settings, saved to audiomuse.json (owner-only: it holds the token)."""

    def __init__(self, file: Path, env_url: str | None = None, env_token: str | None = None) -> None:
        self.file = file
        self.lock = threading.RLock()
        self.env_url, self.env_token = (clean_url(env_url) if env_url else None), (env_token or None)
        self.settings = AudioMuseSettings()
        try:
            data = json.loads(file.read_text("utf-8"))
            s = data.get("settings") if isinstance(data, dict) else None
            if isinstance(s, dict):
                self.settings = AudioMuseSettings(**{k: str(v) for k, v in s.items()
                                                     if k in AudioMuseSettings.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            pass

    @property
    def url(self) -> str:
        return self.env_url or self.settings.url

    @property
    def token(self) -> str:
        return self.env_token or self.settings.token

    @property
    def configured(self) -> bool:
        return bool(self.url)  # the token is optional: AudioMuse-AI's sign-in can be off

    def save(self) -> None:
        with self.lock:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".audiomuse-", dir=self.file.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"settings": asdict(self.settings)}, f)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise


class AudioMuse:
    """The connection: settings plus the last check's outcome."""

    def __init__(self, store: AudioMuseStore, enabled: Callable[[], bool], request: Request = http_request) -> None:
        self.store = store
        self.enabled = enabled
        self.request = request
        self.last_error: str | None = None
        self.checked = False

    def client(self) -> AudioMuseClient:
        return AudioMuseClient(self.store.url, self.store.token, self.request)

    @property
    def ready(self) -> bool:
        return self.enabled() and self.store.configured

    def check(self) -> None:
        """Try the address and token; remembers the outcome for the settings card."""
        self.checked = True
        try:
            self.client().check()
            self.last_error = None
        except AudioMuseError as exc:
            self.last_error = str(exc)

    def similar(self, title: str, artist: str, n: int = 30) -> list[dict]:
        if not self.ready:
            return []
        return self.client().similar(title, artist, n)
