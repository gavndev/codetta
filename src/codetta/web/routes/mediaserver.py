"""The music server (Navidrome / Subsonic, Jellyfin, Emby, Plex): connection details, a check, scans."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException

from codetta.core.mediaserver import KINDS, clean_url
from codetta.web.common import MediaServerSettingsIn

SECRETS = ("password", "token")


def register(app, shared) -> None:
    server = shared.media_server
    store = server.store
    connections = shared.connections

    def server_out() -> dict:
        check = server.check_result
        return {
            "enabled": connections.enabled("mediaserver"),
            "configured": store.configured,
            "kinds": {k: {"name": name, "auth": auth} for k, (name, auth) in KINDS.items()},
            "kind": store.kind, "url": store.get("url"), "username": store.get("username"),
            "has_password": bool(store.get("password")), "has_token": bool(store.get("token")),
            "locked": {k: store.locked(k) for k in ("kind", "url", "username", "password", "token")},
            "check": check.public() if check.at else None,
            "last_scan": server.last_scan,
        }

    @app.get("/api/mediaserver")
    def get_media_server() -> dict:
        """The music server connection (never its password or key) and how the server answered."""
        server.fresh_check()
        return server_out()

    @app.put("/api/mediaserver/settings")
    def put_media_server_settings(body: MediaServerSettingsIn) -> dict:
        url = clean_url(body.url)
        if url:
            parts = urlsplit(url)
            if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
                    or any(c.isspace() for c in url) or parts.query or parts.fragment):
                raise HTTPException(422, "The server's address should look like http://navidrome:4533 or http://192.168.1.50:8096")
            try:
                parts.port
            except ValueError:
                raise HTTPException(422, "The port in the server's address should be a number, like :4533") from None
        for name in SECRETS:
            value = getattr(body, name)
            if value and (not value.isprintable() or (name == "token" and any(c.isspace() for c in value.strip()))):
                raise HTTPException(422, "That doesn't look like an API key or token." if name == "token"
                                    else "The password has characters that can't be sent.")
        if body.username and (not body.username.isprintable() or body.username != body.username.strip()):
            raise HTTPException(422, "The username has spaces at the ends or characters that can't be sent.")
        with store.lock:
            st = store.settings
            if not store.locked("kind"):
                if body.kind != st.kind:  # a different server: its sign-in doesn't carry over
                    st.password = st.token = ""
                st.kind = body.kind
            if not store.locked("url"):
                st.url = url
            if not store.locked("username"):
                st.username = body.username
            if body.password is not None and not store.locked("password"):
                st.password = body.password
            if body.token is not None and not store.locked("token"):
                st.token = body.token.strip()
            try:
                store.save()
            except OSError as exc:
                raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        server.check()
        return server_out()

    @app.post("/api/mediaserver/test")
    def test_media_server() -> dict:
        """Check the connection again."""
        server.check()
        return server_out()

    @app.post("/api/mediaserver/scan")
    def scan_media_server() -> dict:
        """Ask the server for a scan now (Codetta also does this by itself after changing files)."""
        if not server.active:
            raise HTTPException(409, "Connect a music server first.")
        server.scan()
        return server_out()
