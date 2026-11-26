"""AcoustID: connecting the person's own AcoustID account (lookups need it from 2027).

The key is never sent back to the page."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import HTTPException

from codetta.core.providers import ProviderError
from codetta.web.common import AcoustIDKeyIn, AcoustIDLinkIn


def device_name(return_url: str) -> str:
    """What acoustid.org shows when asking the person to approve: the address they open Codetta at,
    when that's a name ("gav-homeserver"), else this machine's name (in Docker, often the container's)."""
    host = urlsplit(return_url).hostname or ""
    try:
        ipaddress.ip_address(host)
        host = ""
    except ValueError:
        pass
    if host in ("", "localhost"):
        host = socket.gethostname()
    return host[:100] or "Codetta"


def safe_return_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or any(c.isspace() for c in url) or not url.isprintable():
        raise HTTPException(422, "That isn't a web address Codetta can send you back to.")
    return url


def register(app, shared) -> None:
    account = shared.acoustid_account
    connections = shared.connections

    def out() -> dict:
        return {"enabled": connections.enabled("acoustid"), **account.out()}

    @app.get("/api/acoustid")
    def get_acoustid() -> dict:
        """Whether Codetta has the person's AcoustID key; while a link waits, asks AcoustID (every few seconds)."""
        if connections.enabled("acoustid") and account.state == "pending":
            try:
                account.refresh()
            except ProviderError:
                pass  # asked again on the next check
        return out()

    @app.post("/api/acoustid/connect")
    def connect_acoustid(body: AcoustIDLinkIn) -> dict:
        """Start connecting: AcoustID gives a key (kept now) and a code to approve on acoustid.org."""
        shared.require_connection("acoustid")
        if account.locked:
            raise HTTPException(409, "The AcoustID key is set on the server (CODETTA_ACOUSTID_USER_KEY).")
        url = safe_return_url(body.return_url)
        try:
            account.request_link(device_name(url), url)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return out()

    @app.put("/api/acoustid")
    def put_acoustid(body: AcoustIDKeyIn) -> dict:
        """Use a key copied from acoustid.org (checked with AcoustID first), or forget the key with an empty one."""
        if account.locked:
            raise HTTPException(409, "The AcoustID key is set on the server (CODETTA_ACOUSTID_USER_KEY).")
        key = body.key.strip()
        try:
            if not key:
                account.forget()
                return out()
            shared.require_connection("acoustid")
            state = account.use_key(key)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        if state != "approved":
            raise HTTPException(422, "AcoustID doesn't accept that key. Copy it again from your account page on acoustid.org.")
        return out()
