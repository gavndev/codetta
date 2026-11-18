"""Is a newer Codetta release available?

The server asks GitHub for the latest published release of the Codetta repo,
at most every ``ttl`` seconds, and compares version numbers. The request
carries no information about you or your library (just a generic
User-Agent), and it can be turned off with ``CODETTA_UPDATE_CHECK=off``.

Codetta never updates itself: doing that from inside a container would need
control of Docker, which means control of the whole server. Instead the UI
shows what's new and the commands to update.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

DEFAULT_REPO = "gavndev/codetta"
CHECK_EVERY = 12 * 3600  # seconds

# fetch(repo) -> {"tag_name", "html_url", "body", "published_at"} or raises
Fetcher = Callable[[str], dict]


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """ "v0.10.2" -> (0, 10, 2). Pre-release suffixes ("-beta") are ignored."""
    if not text:
        return None
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", text)
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def is_newer(candidate: str | None, current: str | None) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def fetch_latest_release(repo: str) -> dict:
    """Latest published (non-draft, non-prerelease) GitHub release."""
    if not _REPO_RE.match(repo):
        raise ValueError(f"Not a GitHub owner/repo: {repo!r}")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Codetta-update-check"},
    )
    with urllib.request.urlopen(req, timeout=5) as res:  # nosec B310: fixed https://api.github.com URL
        return json.loads(res.read().decode("utf-8"))


def _github_url(url: object) -> str | None:
    """Only real GitHub links are passed to the page (never javascript: etc.)."""
    return url if isinstance(url, str) and url.startswith("https://github.com/") else None


class UpdateChecker:
    def __init__(
        self,
        current: str,
        repo: str = DEFAULT_REPO,
        enabled: bool = True,
        fetch: Fetcher = fetch_latest_release,
        ttl: float = CHECK_EVERY,
    ) -> None:
        self.current = current
        self.repo = repo
        self.enabled = enabled
        self.fetch = fetch
        self.ttl = ttl
        self._lock = threading.Lock()
        self._result: dict | None = None
        self._checked_at = 0.0

    MIN_FORCE_INTERVAL = 60  # seconds; "Check for updates" can't hammer GitHub

    def status(self, force: bool = False) -> dict:
        """Current version, and the latest release if the check is on."""
        base = {
            "current": self.current,
            "enabled": self.enabled,
            "latest": None,
            "update_available": False,
            "release_url": None,
            "notes": None,
            "published_at": None,
            "checked_at": None,
            "error": None,
            "note": None,  # neutral info, e.g. no releases published yet
        }
        if not self.enabled:
            return base
        with self._lock:
            age = time.time() - self._checked_at
            fresh = self._result is not None and age < self.ttl
            if (force and age >= self.MIN_FORCE_INTERVAL) or not fresh:
                self._result = self._check()
                self._checked_at = time.time()
            return {**base, **self._result, "checked_at": int(self._checked_at)}

    def _check(self) -> dict:
        try:
            release = self.fetch(self.repo)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"note": "No releases published yet"}
            return {"error": f"GitHub answered {exc.code}"}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return {"error": f"Couldn't reach GitHub ({exc.__class__.__name__})"}
        tag = release.get("tag_name")
        latest = ".".join(map(str, parse_version(tag))) if parse_version(tag) else None
        return {
            "latest": latest,
            "update_available": is_newer(tag, self.current),
            "release_url": _github_url(release.get("html_url")),
            "notes": (release.get("body") or "")[:4000] or None,
            "published_at": release.get("published_at"),
        }
