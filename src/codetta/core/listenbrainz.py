"""ListenBrainz scrobbling: what you play in music apps (and Codetta's own player) is added to
your ListenBrainz listening history.

Opt-in twice: the ListenBrainz connection must be on, and you add your own user token (from
https://listenbrainz.org/settings/). The token lives in ``listenbrainz.json`` in the config
folder (owner-only) or ``CODETTA_LISTENBRAINZ_TOKEN``, and is never sent back to the page.

Sends happen on a background thread so apps never wait. A listen that can't be sent (no
network, ListenBrainz down) is kept in ``listenbrainz-pending.jsonl`` and sent with the next
successful one.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("codetta")

API = "https://api.listenbrainz.org/1"
MAX_PENDING = 2000
BATCH = 100

Post = Callable[[str, dict, bytes | None], tuple[int, bytes]]  # (url, headers, body or None for GET) -> (status, body)


def http_post(url: str, headers: dict, body: bytes | None, timeout: float = 10) -> tuple[int, bytes]:
    if not url.startswith(API + "/"):
        raise ValueError("Only api.listenbrainz.org")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host above)
            return resp.status, resp.read(100_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(10_000) if exc.fp else b""


class ListenBrainzError(Exception):
    pass


class Scrobbler:
    def __init__(self, folder: Path, enabled: Callable[[], bool], env_token: str | None = None,
                 post: Post = http_post, version: str = "") -> None:
        self.file = folder / "listenbrainz.json"
        self.pending_file = folder / "listenbrainz-pending.jsonl"
        self.enabled = enabled
        self.env_token = (env_token or "").strip() or None
        self.post = post
        self.version = version
        self._token = ""
        self.user_name = ""
        self.last_error: str | None = None
        self.sent = 0
        try:
            data = json.loads(self.file.read_text("utf-8"))
            self._token = str(data.get("token") or "")
            self.user_name = str(data.get("user_name") or "")
        except (OSError, ValueError, AttributeError):
            pass
        self._queue: queue.Queue = queue.Queue(maxsize=500)
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    # --- Settings --------------------------------------------------------------------------------

    @property
    def token(self) -> str:
        return self.env_token or self._token

    @property
    def locked(self) -> bool:
        return self.env_token is not None

    @property
    def ready(self) -> bool:
        return bool(self.token) and self.enabled()

    def set_token(self, token: str) -> None:
        if self.locked:
            return
        self._token = token.strip()
        self.user_name = ""
        self._save()

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".listenbrainz-", dir=self.file.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"token": self._token, "user_name": self.user_name}, f)
            os.replace(tmp, self.file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def validate(self) -> str:
        """The ListenBrainz user name the token belongs to; ListenBrainzError if it's not valid."""
        if not self.token:
            raise ListenBrainzError("Add your ListenBrainz user token first.")
        try:
            status, body = self.post(f"{API}/validate-token", {"Authorization": f"Token {self.token}"}, None)
        except (OSError, ValueError) as exc:
            raise ListenBrainzError(f"Couldn't reach ListenBrainz: {exc}") from exc
        data = _json(body)
        if status != 200 or not data.get("valid"):
            raise ListenBrainzError("ListenBrainz didn't accept that token. Copy it from listenbrainz.org → Settings.")
        self.user_name = str(data.get("user_name") or "")
        if not self.locked:
            self._save()
        return self.user_name

    # --- Listens ---------------------------------------------------------------------------------

    def now_playing(self, meta: dict, player: str = "") -> None:
        self._enqueue({"listen_type": "playing_now", "payload": [{"track_metadata": self._meta(meta, player)}]}, keep=False)

    def listened(self, meta: dict, when: float | None = None, player: str = "") -> None:
        listen = {"listened_at": int(when or time.time()), "track_metadata": self._meta(meta, player)}
        self._enqueue({"listen_type": "single", "payload": [listen]}, keep=True)

    def _meta(self, meta: dict, player: str) -> dict:
        info = {k: v for k, v in (
            ("recording_mbid", meta.get("recording_mbid")), ("release_mbid", meta.get("release_mbid")),
            ("artist_mbids", meta.get("artist_mbids") or None), ("tracknumber", meta.get("tracknumber")),
            ("duration_ms", int(meta["duration"] * 1000) if meta.get("duration") else None),
        ) if v}
        info.update({"submission_client": "Codetta", "submission_client_version": self.version,
                     "media_player": (player or "Codetta")[:100]})
        out = {"artist_name": meta.get("artist") or "Unknown artist", "track_name": meta.get("title") or "Unknown title",
               "additional_info": info}
        if meta.get("album"):
            out["release_name"] = meta["album"]
        return out

    def _enqueue(self, body: dict, keep: bool) -> None:
        if not self.ready:
            return  # connection off or no token: nothing leaves the server
        try:
            self._queue.put_nowait((body, keep))
        except queue.Full:
            if keep:
                self._keep([body])
            return
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="listenbrainz", daemon=True)
                self._worker.start()

    def _run(self) -> None:
        while True:
            try:
                body, keep = self._queue.get(timeout=30)
            except queue.Empty:
                return
            if self._send(body):
                if keep:
                    self.flush()
            elif keep:
                self._keep([body])

    def _send(self, body: dict) -> bool:
        if not self.ready:
            return False
        try:
            status, raw = self.post(f"{API}/submit-listens", {"Authorization": f"Token {self.token}",
                                                             "Content-Type": "application/json"},
                                    json.dumps(body).encode())
        except (OSError, ValueError) as exc:
            self.last_error = f"Couldn't reach ListenBrainz: {exc}"
            return False
        if status == 200:
            self.last_error = None
            self.sent += len(body.get("payload") or [])
            return True
        self.last_error = f"ListenBrainz said {status}: {_json(raw).get('error', '')}".rstrip(": ")
        return status in (400,)  # a listen ListenBrainz refuses as malformed is dropped, not retried forever

    # --- Listens that couldn't be sent yet ---------------------------------------------------------

    def _keep(self, bodies: list[dict]) -> None:
        listens = [x for b in bodies for x in b.get("payload") or []]
        with self._lock:
            try:
                lines = self.pending_file.read_text("utf-8").splitlines() if self.pending_file.exists() else []
                lines = (lines + [json.dumps(x) for x in listens])[-MAX_PENDING:]
                self.pending_file.parent.mkdir(parents=True, exist_ok=True)
                self.pending_file.write_text("\n".join(lines) + "\n", "utf-8")
            except OSError:
                pass

    def pending(self) -> int:
        try:
            return sum(1 for line in self.pending_file.read_text("utf-8").splitlines() if line.strip())
        except OSError:
            return 0

    def flush(self) -> None:
        """Send listens kept from earlier failures (in batches; whatever fails stays kept)."""
        with self._lock:
            try:
                lines = [line for line in self.pending_file.read_text("utf-8").splitlines() if line.strip()]
            except OSError:
                return
            self.pending_file.unlink(missing_ok=True)
        listens = []
        for line in lines:
            try:
                listens.append(json.loads(line))
            except ValueError:
                continue
        for i in range(0, len(listens), BATCH):
            chunk = listens[i:i + BATCH]
            if not self._send({"listen_type": "import", "payload": chunk}):
                self._keep([{"payload": listens[i:]}])
                return


def _json(raw: bytes) -> dict:
    try:
        data = json.loads(raw or b"{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}
