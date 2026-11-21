"""Lidarr: connection details, a check of how Lidarr is set up, and warnings about conflicts."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException

from codetta.core.lidarr import clean_url
from codetta.web.common import LidarrSettingsIn


def register(app, shared) -> None:
    lidarr = shared.lidarr
    store = lidarr.store
    connections = shared.connections

    def lidarr_out() -> dict:
        check = lidarr.check_result
        return {
            "enabled": connections.enabled("lidarr"),
            "configured": store.configured,
            "url": store.url, "has_key": bool(store.api_key),
            "locked": {"url": store.env_url is not None, "api_key": store.env_key is not None},
            "settings": {"names": store.settings.names},
            "check": check.public() if check.at else None,
            "names_by_lidarr": bool(check.ok and check.renames and store.settings.names == "auto"),
            "warnings": lidarr.warnings(),
            "last_sync": lidarr.last_sync,
        }

    @app.get("/api/lidarr")
    def get_lidarr() -> dict:
        """The Lidarr connection (never the API key), how Lidarr is set up, and any conflicts."""
        lidarr.fresh_check()  # re-reads Lidarr's settings at most once an hour
        return lidarr_out()

    @app.put("/api/lidarr/settings")
    def put_lidarr_settings(body: LidarrSettingsIn) -> dict:
        url = clean_url(body.url)
        if url:
            parts = urlsplit(url)
            if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
                    or any(c.isspace() for c in url) or parts.query or parts.fragment):
                raise HTTPException(422, "Lidarr's address should look like http://lidarr:8686 or http://192.168.1.50:8686")
            try:
                parts.port  # a port that isn't a number raises
            except ValueError:
                raise HTTPException(422, "The port in Lidarr's address should be a number, like :8686") from None
        if body.api_key is not None and body.api_key.strip():
            key = body.api_key.strip()
            if any(c.isspace() for c in key) or not key.isprintable() or len(key) < 16:
                raise HTTPException(422, "That doesn't look like a Lidarr API key (Settings → General → API Key: 32 letters and numbers).")
        with store.lock:
            st = store.settings
            if store.env_url is None:
                st.url = url
            if body.api_key is not None and store.env_key is None:
                st.api_key = body.api_key.strip()
            st.names = body.names
            try:
                store.save()
            except OSError as exc:
                raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        lidarr.check()
        return lidarr_out()

    @app.post("/api/lidarr/test")
    def test_lidarr() -> dict:
        """Check the connection again and re-read Lidarr's folders and settings."""
        lidarr.check()
        return lidarr_out()
