"""Update check, notifications, connections and the tag vocabulary."""
from __future__ import annotations

import os

from fastapi import HTTPException, Query

from codetta.core.connections import BY_ID as CONNECTION_BY_ID
from codetta.core.presets import PLACEHOLDERS
from codetta.core.tagmap import FIELDS
from codetta.web.common import VERSION, ConnectionsIn, NotificationsReadIn, log


def register(app, shared) -> None:
    connections = shared.connections
    fingerprinter = shared.fingerprinter
    library = shared.library
    mb_mirror = shared.mb_mirror
    notices = shared.notices
    settings = shared.settings
    updates = shared.updates

    @app.get("/api/update")
    def update_status(force: bool = Query(False, description="Check GitHub now instead of using the cached answer")) -> dict:
        """Installed version and, if enabled, the latest release on GitHub."""
        result = updates.status(force=force)
        if result.get("update_available") and result.get("latest"):
            notices.add("update", f"Codetta {result['latest']} is out",
                      "See what's new and how to update in Settings → About.", {"open": "about"},
                      key=f"update:{result['latest']}")
        return result

    # --- Notifications -------------------------------------------------------------------

    @app.get("/api/notifications")
    def get_notifications(after_id: int = Query(0, ge=0)) -> dict:
        """Newest first. ``after_id`` returns only newer ones (for the bell's pop-ups)."""
        return notices.recent(after_id)

    @app.post("/api/notifications/read")
    def read_notifications(body: NotificationsReadIn) -> dict:
        notices.mark_read(body.ids)
        return notices.recent()

    @app.delete("/api/notifications")
    def clear_notifications() -> dict:
        notices.clear()
        return notices.recent()

    @app.get("/api/status")
    def status() -> dict:
        return {
            "version": VERSION,
            "music_dir": str(library.root),
            "music_dir_found": library.exists(),
            "music_dir_writable": library.exists() and os.access(library.root, os.W_OK),
            "lyrics_lookup": connections.enabled("lyrics"),
            "musicbrainz": connections.enabled("musicbrainz"),
            # Album matching works with any of MusicBrainz, Deezer or iTunes switched on.
            "matching": any(connections.enabled(c) for c in ("musicbrainz", "deezer", "itunes", "discogs")),
            "replaygain": shared.meter.available,
        }

    # --- Connections (online features, all opt-in) ---------------------------------------

    def connections_out() -> dict:
        out = connections.status()
        for c in out["connections"]:
            if c["id"] == "acoustid" and not fingerprinter.available:
                c["unavailable"] = ("The fingerprint tool isn't installed on this server (fpcalc, from "
                                    "Chromaprint; it's included in the Docker image).")
        if mb_mirror:
            from urllib.parse import urlsplit

            for c in out["connections"]:
                if c["id"] == "musicbrainz":
                    c["hosts"] = [urlsplit(mb_mirror).netloc or mb_mirror, "coverartarchive.org"]
                    c["mirror"] = True
        return out

    @app.get("/api/connections")
    def get_connections() -> dict:
        """Which online features are on, who decided (the user or an env var), and
        whether the first-run choice has been made."""
        return connections_out()

    @app.put("/api/connections")
    def put_connections(body: ConnectionsIn) -> dict:
        unknown = [k for k in body.enabled if k not in CONNECTION_BY_ID]
        if unknown:
            raise HTTPException(422, f"Unknown connection: {unknown[0]}")
        try:
            connections.save(body.enabled)
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        on = [CONNECTION_BY_ID[c["id"]].name for c in connections.status()["connections"] if c["enabled"]]
        log.info("Connections: %s", ", ".join(on) if on else "none (offline)")
        return connections_out()

    def require_connection(cid: str) -> None:
        if connections.enabled(cid):
            return
        name = CONNECTION_BY_ID[cid].name
        if settings.offline:
            raise HTTPException(403, f"{name} is unavailable: Codetta is set to stay offline (CODETTA_OFFLINE).")
        locked = connections.locked_by(cid)
        where = f"it's turned off by {locked}" if locked else "turn it on in Settings → Connections"
        raise HTTPException(403, f"{name} is off: {where}.")

    @app.get("/api/fields")
    def fields() -> dict:
        """The editor's known tags (in display order) and preset placeholders."""
        return {
            "fields": [
                {"key": f.key, "label": f.label, "group": f.group, "multi": f.multi}
                for f in FIELDS
            ],
            "placeholders": sorted(PLACEHOLDERS),
        }

    shared.share(fields=fields, require_connection=require_connection, status=status)
