"""Sign-in for Codetta: one account, password hashing, sessions, and rate limiting.

Design:
* One account (username + password). It's created on the first visit
  ("setup"), or supplied through environment variables in Docker.
* Passwords are hashed with scrypt (Python's standard library) and a random
  salt. The plain password is never stored.
* Signing in creates a random session token, sent to the browser as an
  HttpOnly cookie. Only a SHA-256 hash of each token is kept on disk, so the
  sessions file can't be used to sign in even if someone reads it.
* Repeated wrong passwords from the same address get locked out for a
  growing amount of time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

SESSION_DAYS = 30
MAX_SESSIONS = 200  # signed-in browsers kept at once; the oldest is signed out past this
MIN_PASSWORD_LENGTH = 8

# scrypt cost parameters (~100 ms and 32 MB per hash on a typical home server).
# Older hashes with a lower N are upgraded automatically at the next sign-in.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1


class AuthError(Exception):
    """A sign-in problem the user should see (wrong password, invalid input...)."""


# --- Password hashing ----------------------------------------------------------------


# At most this many password hashes run at once (each needs ~32 MB of RAM), so a
# burst of parallel sign-in attempts can't exhaust memory on a small server.
MAX_CONCURRENT_HASHES = 2
_hash_slots = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)
HASH_WAIT_SECONDS = 10.0


class BusyError(AuthError):
    """Too many sign-in attempts are being checked right now."""


def _with_hash_slot(fn, *args):
    if not _hash_slots.acquire(timeout=HASH_WAIT_SECONDS):
        raise BusyError("The server is busy checking other sign-ins. Try again in a moment.")
    try:
        return fn(*args)
    finally:
        _hash_slots.release()


def hash_password(password: str) -> str:
    return _with_hash_slot(_hash_password, password)


def verify_password(password: str, stored: str) -> bool:
    return _with_hash_slot(_verify_password, password, stored)


def _hash_password(password: str) -> str:
    """Return a self-describing hash string: ``scrypt$n$r$p$salt$hash``."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32,
                            maxmem=128 * 1024 * 1024)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(digest)}"


def needs_rehash(stored: str) -> bool:
    """True if ``stored`` was made with weaker settings than today's."""
    try:
        scheme, n, r, p, *_ = stored.split("$")
        return scheme != "scrypt" or int(n) < _SCRYPT_N or int(r) < _SCRYPT_R or int(p) < _SCRYPT_P
    except ValueError:
        return True


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected),
            maxmem=128 * 1024 * 1024,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def validate_new_credentials(username: str, password: str) -> str:
    """Check a new username/password; returns the cleaned-up username."""
    username = username.strip()
    if not username:
        raise AuthError("Choose a username")
    if len(username) > 64 or any(ch.isspace() for ch in username):
        raise AuthError("Usernames can't contain spaces (max 64 characters)")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Use a password of at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > 1024:
        raise AuthError("That password is too long")
    return username


# --- Small JSON file helper ----------------------------------------------------------------


def _write_private_json(path: Path, data: object) -> None:
    """Write JSON atomically, readable only by the owner (chmod 600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".codetta-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# --- The account ---------------------------------------------------------------------------


@dataclass
class Account:
    username: str
    password_hash: str


class AccountStore:
    """The single Codetta account, from env vars or ``auth.json`` in the config folder."""

    def __init__(self, file: Path, env_username: str | None = None, env_password: str | None = None) -> None:
        self.file = file
        self._lock = threading.Lock()
        self.managed_by_env = bool(env_username and env_password)
        self._env_account = (
            Account(env_username.strip(), hash_password(env_password)) if self.managed_by_env else None
        )

    def get(self) -> Account | None:
        if self._env_account:
            return self._env_account
        data = _read_json(self.file)
        if isinstance(data, dict) and isinstance(data.get("username"), str) and isinstance(data.get("password_hash"), str):
            return Account(data["username"], data["password_hash"])
        return None

    @property
    def setup_required(self) -> bool:
        return self.get() is None

    def create(self, username: str, password: str) -> Account:
        """First-run setup. Refused once an account exists."""
        username = validate_new_credentials(username, password)
        with self._lock:
            if self.get() is not None:
                raise AuthError("Codetta is already set up. Sign in instead.")
            account = Account(username, hash_password(password))
            self._save(account)
        return account

    def set_password(self, username: str, new_password: str) -> Account:
        if self.managed_by_env:
            raise AuthError("The password is set by environment variables (CODETTA_USERNAME / CODETTA_PASSWORD).")
        username = validate_new_credentials(username, new_password)
        with self._lock:
            account = Account(username, hash_password(new_password))
            self._save(account)
        return account

    def check(self, username: str, password: str) -> Account | None:
        account = self.get()
        if account is None:
            hash_password(password)  # spend the same time either way
            return None
        name_ok = hmac.compare_digest(username.strip().lower().encode(), account.username.lower().encode())
        pass_ok = verify_password(password, account.password_hash)
        return account if name_ok and pass_ok else None

    def _save(self, account: Account) -> None:
        _write_private_json(self.file, {
            "username": account.username,
            "password_hash": account.password_hash,
            "updated": int(time.time()),
        })


# --- Sessions ---------------------------------------------------------------------------------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SessionStore:
    """Signed-in browsers. Persisted (as token hashes) so restarts don't sign you out.

    The file is re-read whenever it changes on disk, so ``python -m codetta.cli
    sign-out-all`` (a separate process) takes effect on a running server.
    """

    def __init__(self, file: Path | None, days: int = SESSION_DAYS) -> None:
        self.file = file
        self.lifetime = days * 86400
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._mtime: int | None = None
        self._reload_if_changed()

    def _file_mtime(self) -> int | None:
        try:
            return self.file.stat().st_mtime_ns if self.file else None
        except OSError:
            return None

    def _reload_if_changed(self) -> None:
        mtime = self._file_mtime()
        if mtime == self._mtime:
            return
        self._mtime = mtime
        data = _read_json(self.file) if mtime is not None else None
        now = time.time()
        self._sessions = {
            k: v for k, v in (data.items() if isinstance(data, dict) else [])
            if isinstance(v, dict) and isinstance(v.get("expires"), (int, float)) and v["expires"] > now
        }

    def create(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._reload_if_changed()
            self._sessions[_token_hash(token)] = {
                "username": username, "created": int(now), "expires": int(now + self.lifetime),
            }
            if len(self._sessions) > MAX_SESSIONS:  # each sign-in (and each desktop window) adds one: drop the oldest
                for key, _ in sorted(self._sessions.items(), key=lambda kv: kv[1].get("created", 0))[:len(self._sessions) - MAX_SESSIONS]:
                    del self._sessions[key]
            self._persist()
        return token

    def lookup(self, token: str | None) -> str | None:
        """The username for a valid session token, or None. Extends active sessions."""
        if not token:
            return None
        key = _token_hash(token)
        now = time.time()
        with self._lock:
            self._reload_if_changed()
            session = self._sessions.get(key)
            if session is None:
                return None
            if session["expires"] <= now:
                del self._sessions[key]
                self._persist()
                return None
            # Sliding expiry, written at most once an hour to avoid constant disk writes.
            if session["expires"] - now < self.lifetime - 3600:
                session["expires"] = int(now + self.lifetime)
                self._persist()
            return session["username"]

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._reload_if_changed()
            if self._sessions.pop(_token_hash(token), None) is not None:
                self._persist()

    def revoke_all(self, keep: str | None = None) -> None:
        """Sign out every browser (except, optionally, the one with token ``keep``)."""
        with self._lock:
            self._reload_if_changed()
            kept = _token_hash(keep) if keep else None
            self._sessions = {k: v for k, v in self._sessions.items() if k == kept}
            self._persist()

    def _persist(self) -> None:
        if self.file:
            try:
                _write_private_json(self.file, self._sessions)
                self._mtime = self._file_mtime()
            except OSError:
                pass  # sessions still work in memory


# --- Rate limiting -------------------------------------------------------------------------------


class LoginRateLimiter:
    """Slow down password guessing: after ``free`` failures in ``window`` seconds
    from one address, lock it out for 30 s, doubling per extra failure (max 15 min).

    Memory is bounded: at most ``MAX_TRACKED`` addresses are remembered; the
    least recently failing one is forgotten first (O(1)).
    """

    MAX_TRACKED = 10_000

    def __init__(self, free: int = 5, window: float = 15 * 60, base_lock: float = 30, max_lock: float = 15 * 60) -> None:
        self.free, self.window, self.base_lock, self.max_lock = free, window, base_lock, max_lock
        self._failures: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        """Failures still inside the window (expired ones are dropped). Never adds keys."""
        fails = self._failures.get(key)
        if fails is None:
            return []
        fails = [t for t in fails if now - t < self.window]
        if fails:
            self._failures[key] = fails
        else:
            del self._failures[key]
        return fails

    def retry_after(self, key: str) -> int:
        """Seconds until ``key`` may try again (0 = allowed now)."""
        now = time.time()
        with self._lock:
            fails = self._recent(key, now)
            if len(fails) < self.free:
                return 0
            lock = min(self.base_lock * 2 ** (len(fails) - self.free), self.max_lock)
            remaining = fails[-1] + lock - now
            return int(remaining) + 1 if remaining > 0 else 0

    def failed(self, key: str) -> None:
        now = time.time()
        with self._lock:
            fails = self._recent(key, now)
            fails.append(now)
            self._failures[key] = fails
            self._failures.move_to_end(key)  # most recently failing goes last
            while len(self._failures) > self.MAX_TRACKED:
                self._failures.popitem(last=False)  # forget the least recently failing

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
