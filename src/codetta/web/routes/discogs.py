"""Discogs: the person's token (searching needs one), checked with Discogs, never sent back to the page."""

from __future__ import annotations

from fastapi import HTTPException

from codetta.core.discogs import API
from codetta.core.providers import ProviderError
from codetta.web.common import DiscogsTokenIn


def register(app, shared) -> None:
    token = shared.discogs_token
    fetch = shared.discogs_fetch
    connections = shared.connections

    def check() -> dict:
        """Who Discogs says the token belongs to (it isn't saved unless Discogs agrees)."""
        if not token.token:
            return {"ok": False, "error": "Add your Discogs token to search Discogs."}
        try:
            me = fetch(f"{API}/oauth/identity", {"Authorization": f"Discogs token={token.token}"}) or {}
        except ProviderError as exc:
            msg = str(exc)
            if "(401)" in msg or "(403)" in msg:
                msg = "Discogs turned down that token. Make a new one on discogs.com (Settings → Developers)."
            return {"ok": False, "error": msg}
        return {"ok": True, "username": str(me.get("username") or "")}

    def out(state: dict | None = None) -> dict:
        return {"enabled": connections.enabled("discogs"), "has_token": bool(token.token), "locked": token.locked,
                "check": state}

    @app.get("/api/discogs")
    def get_discogs() -> dict:
        """The Discogs connection: whether there's a token (never the token itself)."""
        return out()

    @app.put("/api/discogs")
    def put_discogs(body: DiscogsTokenIn) -> dict:
        """Save (or forget, with an empty one) the Discogs token, after checking it with Discogs."""
        if token.locked:
            raise HTTPException(409, "The Discogs token is set on the server (CODETTA_DISCOGS_TOKEN).")
        new = body.token.strip()
        if new:  # it's checked with Discogs before it's kept, so Discogs must be on (forgetting it never needs to)
            shared.require_connection("discogs")
        if new and (any(c.isspace() for c in new) or not new.isprintable() or len(new) < 20):
            raise HTTPException(422, "That doesn't look like a Discogs token (Settings → Developers → Generate new token).")
        old = token.saved
        try:
            token.save(new)
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        state = check() if new else None
        if new and not state["ok"]:
            token.save(old)  # a token Discogs turns down isn't kept
        return out(state)

    @app.post("/api/discogs/test")
    def test_discogs() -> dict:
        shared.require_connection("discogs")
        return out(check())
