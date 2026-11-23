"""Music servers: telling the user's own Navidrome, Jellyfin, Emby or Plex about Codetta's changes.

Players read the tags Codetta writes, but only after their server rescans the library.
Most servers notice changes by themselves when the music folder is a local disk, but not
on network shares (NFS, SMB), where file-change events never arrive, and some only scan
on a schedule. With this connection, Codetta asks the server for a quick scan a few
seconds after it changes files, so edits show up in the player straight away.

* **Navidrome and other Subsonic servers** (Gonic, Airsonic-Advanced, Ampache, ...):
  ``startScan`` through the Subsonic API, with a username and password (the server's
  own token sign-in, so the password itself is never sent). Navidrome only lets admin
  users start scans.
* **Jellyfin and Emby:** a refresh of the music libraries only (never films or shows),
  with an API key (Dashboard → API Keys).
* **Plex:** a scan of the music libraries, with the server's token.

Scans are quick (servers only re-read files that changed), and Codetta waits for its
changes to settle and asks at most once a minute, so a big batch of edits means one scan.

Settings live in ``mediaserver.json`` in the config folder, readable by its owner only.
Passwords and keys are never sent back to the page.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from codetta.core.library import is_special

KINDS = {  # kind -> (name people know it by, what it signs in with)
    "subsonic": ("Navidrome or another Subsonic server", "password"),
    "jellyfin": ("Jellyfin", "token"),
    "emby": ("Emby", "token"),
    "plex": ("Plex", "token"),
}
SCAN_QUIET_SECONDS = 8.0  # wait for changes to settle before asking for a scan
SCAN_GAP_SECONDS = 60.0  # and ask at most this often (one scan picks up everything since the last)
CHECK_EVERY_SECONDS = 3600
CLIENT = "codetta"
SUBSONIC_VERSION = "1.16.1"


class ServerError(Exception):
    """The server couldn't be reached or said no; the message is for people."""


Request = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]  # (method, url, headers, body) -> (status, body)


def http_request(method: str, url: str, headers: dict, body: bytes | None, timeout: float = 15) -> tuple[int, bytes]:
    if not url.lower().startswith(("http://", "https://")):  # an address set by env var skips the page's check
        raise ServerError("The address must start with http:// or https://")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (the admin's own server)
            return resp.status, resp.read(5_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(100_000) if exc.fp else b""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ServerError(f"Couldn't reach the server: {reason}") from exc


def clean_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url and not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "http://" + url  # "navidrome:4533" -> "http://navidrome:4533"
    for tail in ("/rest", "/web", "/web/index.html"):
        if url.endswith(tail):
            url = url[: -len(tail)]
    return url


def _json(raw: bytes, name: str) -> object:
    try:
        return json.loads(raw) if raw.strip() else None
    except ValueError as exc:
        raise ServerError(f"The server sent something that isn't JSON. Is the address pointing at {name}?") from exc


@dataclass
class Library:
    id: str
    name: str


@dataclass
class Info:
    name: str = ""  # "Navidrome", "Jellyfin", ...
    version: str = ""
    libraries: list[Library] = field(default_factory=list)  # the music libraries a scan covers
    can_scan: bool = True
    note: str = ""  # something worth knowing that isn't an error


# --- Subsonic (Navidrome, Gonic, Airsonic, Ampache...) ------------------------------------------


class SubsonicClient:
    def __init__(self, url: str, username: str, password: str, request: Request) -> None:
        self.base = clean_url(url) + "/rest/"
        self.username, self.password, self.request = username, password, request
        self.plain = False  # the server can't do token sign-in (Subsonic error 41): hex-encoded password

    def _auth(self) -> dict:
        if self.plain:
            return {"u": self.username, "p": "enc:" + self.password.encode().hex()}
        salt = secrets.token_hex(8)
        token = hashlib.md5((self.password + salt).encode(), usedforsecurity=False).hexdigest()  # the Subsonic API's own scheme
        return {"u": self.username, "t": token, "s": salt}

    def call(self, method: str, **params) -> dict:
        query = {**self._auth(), "v": SUBSONIC_VERSION, "c": CLIENT, "f": "json", **params}
        status, raw = self.request("GET", self.base + method + "?" + urllib.parse.urlencode(query), {"Accept": "application/json"}, None)
        if status == 404:
            raise ServerError("No Subsonic API at that address (404). For Navidrome it's the address you open it at, "
                              "like http://navidrome:4533.")
        if status in (401, 403) and not raw.strip():
            raise ServerError("The server turned down the username or password.")
        if status >= 400 and not raw.strip():
            raise ServerError(f"The server said {status}.")
        data = _json(raw, "a Subsonic server")
        r = data.get("subsonic-response") if isinstance(data, dict) else None
        if not isinstance(r, dict):
            raise ServerError("That doesn't look like a Subsonic server. For Navidrome, use the address you open it at.")
        if r.get("status") != "ok":
            err = r.get("error") or {}
            code = err.get("code")
            if code == 41 and not self.plain:  # token sign-in not supported: try once with the password
                self.plain = True
                return self.call(method, **params)
            if code == 40:
                raise ServerError("The server turned down the username or password.")
            if code == 50:
                raise ServerError("This user isn't allowed to start scans. Use an admin user (Navidrome only lets "
                                  "admins scan).")
            raise ServerError(f"The server said: {err.get('message') or 'error ' + str(code)}")
        return r

    def info(self) -> Info:
        r = self.call("ping")
        name = str(r.get("type") or "Subsonic server")
        name = {"navidrome": "Navidrome", "gonic": "Gonic", "airsonic": "Airsonic", "ampache": "Ampache",
                "lms": "LMS", "funkwhale": "Funkwhale"}.get(name.lower(), name)
        info = Info(name=name, version=str(r.get("serverVersion") or r.get("version") or ""))
        try:
            folders = self.call("getMusicFolders").get("musicFolders", {}).get("musicFolder") or []
            info.libraries = [Library(str(f.get("id")), str(f.get("name") or "Music")) for f in folders if isinstance(f, dict)]
        except ServerError:
            pass
        try:
            user = self.call("getUser", username=self.username).get("user") or {}
            if user.get("adminRole") is False and name == "Navidrome":
                info.can_scan = False
                info.note = ("This user isn't an admin, and Navidrome only lets admins start scans. Use an admin "
                             "user, or leave it to Navidrome's own watcher and schedule.")
        except ServerError:
            pass
        return info

    def scan(self) -> None:
        self.call("startScan")  # a quick scan: only folders that changed are read again


# --- Jellyfin and Emby ---------------------------------------------------------------------------


class JellyfinClient:
    def __init__(self, url: str, token: str, request: Request, emby: bool = False) -> None:
        self.base = clean_url(url)
        self.token, self.request, self.emby = token, request, emby
        self.name = "Emby" if emby else "Jellyfin"

    def call(self, method: str, path: str, query: dict | None = None) -> object:
        headers = {"Accept": "application/json"}
        if self.emby:
            headers["X-Emby-Token"] = self.token
        else:
            headers["Authorization"] = f'MediaBrowser Client="Codetta", Token="{self.token}"'
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        status, raw = self.request(method, url, headers, b"" if method == "POST" else None)
        if status in (401, 403):
            raise ServerError(f"{self.name} turned down the API key. Make one in {self.name}: Dashboard → API Keys.")
        if status == 404:
            raise ServerError(f"{self.name} doesn't know that (404). Is the address the one you open {self.name} at?")
        if status >= 400:
            raise ServerError(f"{self.name} said {status}.")
        return _json(raw, self.name)

    def music_libraries(self) -> list[Library]:
        r = self.call("GET", "/Library/VirtualFolders")
        return [Library(str(v.get("ItemId")), str(v.get("Name") or "Music")) for v in (r if isinstance(r, list) else [])
                if isinstance(v, dict) and (v.get("CollectionType") or "").lower() == "music" and v.get("ItemId")]

    def info(self) -> Info:
        st = self.call("GET", "/System/Info")
        st = st if isinstance(st, dict) else {}
        product = str(st.get("ProductName") or "")
        if self.emby is False and "emby" in product.lower() and "jellyfin" not in product.lower():
            raise ServerError("That's an Emby server. Pick Emby as the kind of server.")
        info = Info(name=self.name, version=str(st.get("Version") or ""), libraries=self.music_libraries())
        if not info.libraries:
            info.can_scan = False
            info.note = f"{self.name} has no music library yet, so there's nothing to scan."
        return info

    def scan(self) -> None:
        for lib in self.music_libraries():  # music only: films and shows are left alone
            self.call("POST", f"/Items/{urllib.parse.quote(lib.id)}/Refresh",
                      {"Recursive": "true", "MetadataRefreshMode": "Default", "ImageRefreshMode": "Default",
                       "ReplaceAllMetadata": "false", "ReplaceAllImages": "false"})


# --- Plex -----------------------------------------------------------------------------------------


class PlexClient:
    def __init__(self, url: str, token: str, request: Request) -> None:
        self.base = clean_url(url)
        self.token, self.request = token, request

    def call(self, path: str) -> object:
        headers = {"Accept": "application/json", "X-Plex-Token": self.token, "X-Plex-Product": "Codetta",
                   "X-Plex-Client-Identifier": "codetta"}
        status, raw = self.request("GET", self.base + path, headers, None)
        if status in (401, 403):
            raise ServerError("Plex turned down the token. See “Finding your Plex token” in Codetta's docs.")
        if status == 404:
            raise ServerError("Plex doesn't know that (404). Use the server's address, like http://plex:32400.")
        if status >= 400:
            raise ServerError(f"Plex said {status}.")
        return _json(raw, "Plex")

    def music_libraries(self) -> list[Library]:
        r = self.call("/library/sections")
        dirs = (r.get("MediaContainer") or {}).get("Directory") or [] if isinstance(r, dict) else []
        return [Library(str(d.get("key")), str(d.get("title") or "Music")) for d in dirs
                if isinstance(d, dict) and d.get("type") == "artist" and d.get("key") is not None]

    def info(self) -> Info:
        r = self.call("/")
        mc = r.get("MediaContainer") if isinstance(r, dict) else None
        info = Info(name="Plex", version=str((mc or {}).get("version") or ""), libraries=self.music_libraries())
        if not info.libraries:
            info.can_scan = False
            info.note = "Plex has no music library yet, so there's nothing to scan."
        return info

    def scan(self) -> None:
        for lib in self.music_libraries():
            self.call(f"/library/sections/{urllib.parse.quote(lib.id)}/refresh")


# --- Settings -------------------------------------------------------------------------------------


@dataclass
class ServerSettings:
    kind: str = "subsonic"
    url: str = ""
    username: str = ""  # Subsonic servers
    password: str = ""  # Subsonic servers (their token sign-in needs the password itself)
    token: str = ""  # Jellyfin/Emby API key, Plex token


class ServerStore:
    """Settings, saved to mediaserver.json (owner-only: it holds a password or key)."""

    def __init__(self, file: Path, env: dict[str, str | None] | None = None) -> None:
        self.file = file
        self.lock = threading.RLock()
        env = {k: (v.strip() if isinstance(v, str) else None) or None for k, v in (env or {}).items()}
        if env.get("kind") and env["kind"] not in KINDS:
            env["kind"] = None
        if env.get("url"):
            env["url"] = clean_url(env["url"])
        self.env = env  # set on the server (and locked in the app): kind, url, username, password, token
        self.settings = ServerSettings()
        try:
            data = json.loads(file.read_text("utf-8"))
            s = data.get("settings") if isinstance(data, dict) else None
            if isinstance(s, dict):
                self.settings = ServerSettings(**{k: str(v) for k, v in s.items() if k in ServerSettings.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            pass
        if self.settings.kind not in KINDS:
            self.settings.kind = "subsonic"

    def get(self, name: str) -> str:
        return self.env.get(name) or getattr(self.settings, name)

    def locked(self, name: str) -> bool:
        return bool(self.env.get(name))

    @property
    def kind(self) -> str:
        return self.get("kind")

    @property
    def configured(self) -> bool:
        if not self.get("url"):
            return False
        if KINDS[self.kind][1] == "password":
            return bool(self.get("username") and self.get("password"))
        return bool(self.get("token"))

    def save(self) -> None:
        with self.lock:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".mediaserver-", dir=self.file.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"settings": asdict(self.settings)}, f)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise


@dataclass
class Check:
    ok: bool = False
    error: str = ""
    info: Info = field(default_factory=Info)
    at: float = 0.0

    def public(self) -> dict:
        return {"ok": self.ok, "error": self.error, "at": self.at, **asdict(self.info)}


class MediaServer:
    """The connection: settings, a check of the server, and the scans Codetta asks for."""

    def __init__(self, store: ServerStore, enabled: Callable[[], bool], request: Request = http_request,
                 quiet: float | None = None, gap: float | None = None) -> None:
        self.store = store
        self.enabled = enabled
        self.request = request
        self.quiet, self.gap = quiet, gap  # None: the module constants (read when used, so tests can shorten them)
        self.check_result = Check()
        self.last_scan: dict = {"at": 0.0, "error": ""}
        self._pending = False
        self._last_change = 0.0
        self._last_scan_mono = -1e9
        self._cv = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stop = False

    @property
    def active(self) -> bool:
        return self.enabled() and self.store.configured

    def client(self):
        s, kind = self.store, self.store.kind
        if kind == "subsonic":
            return SubsonicClient(s.get("url"), s.get("username"), s.get("password"), self.request)
        if kind in ("jellyfin", "emby"):
            return JellyfinClient(s.get("url"), s.get("token"), self.request, emby=kind == "emby")
        return PlexClient(s.get("url"), s.get("token"), self.request)

    def check(self) -> Check:
        if not self.store.configured:
            how = "a username and password" if KINDS[self.store.kind][1] == "password" else "its API key or token"
            self.check_result = Check(error=f"Add your server's address and {how}.", at=time.time())
            return self.check_result
        try:
            result = Check(ok=True, info=self.client().info(), at=time.time())
        except ServerError as exc:
            result = Check(error=str(exc), at=time.time())
        self.check_result = result
        return result

    def fresh_check(self, max_age: float = CHECK_EVERY_SECONDS) -> Check:
        if self.active and time.time() - self.check_result.at > max_age:
            return self.check()
        return self.check_result

    # -- scans after Codetta changes files ---------------------------------------------------------

    def changed(self, rels: Iterable[str]) -> None:
        """Files Codetta just changed: ask the server for a scan soon (one for a whole batch)."""
        if not self.active or not any(r and not is_special(r) for r in rels):
            return
        with self._cv:  # the thread check too: two saves at once start one worker
            self._pending = True
            self._last_change = time.monotonic()
            self._cv.notify()
            if not (self._thread and self._thread.is_alive()):
                self._stop = False
                self._thread = threading.Thread(target=self._run, name="codetta-mediaserver", daemon=True)
                self._thread.start()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                quiet = SCAN_QUIET_SECONDS if self.quiet is None else self.quiet
                gap = SCAN_GAP_SECONDS if self.gap is None else self.gap
                now = time.monotonic()
                wait = max(self._last_change + quiet, self._last_scan_mono + gap) - now
                if wait > 0:
                    self._cv.wait(wait)
                    continue
                self._pending = False
                self._last_scan_mono = now
            self.scan()

    def scan(self) -> bool:
        """Ask the server for a scan now. False (and last_scan says why) when it didn't work."""
        if not self.active:
            return False
        try:
            self.client().scan()
            self.last_scan = {"at": time.time(), "error": ""}
            return True
        except ServerError as exc:
            self.last_scan = {"at": time.time(), "error": str(exc)}
            return False
