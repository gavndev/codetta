"""Autoplay: what plays when the queue runs out, and the AudioMuse-AI connection it can use."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException

from codetta.core.audiomuse import AudioMuse, AudioMuseStore
from codetta.core.autoplay import SOURCE_NAMES, Autoplay
from codetta.core.lidarr import clean_url
from codetta.core.library import LibraryPathError
from codetta.web.common import AudioMuseSettingsIn, AutoplayIn


def register(app, shared) -> None:
    settings = shared.settings
    connections = shared.connections
    library = shared.library
    lib_index = shared.lib_index
    audiomuse = AudioMuse(AudioMuseStore(settings.config_dir / "audiomuse.json", settings.audiomuse_url,
                                         settings.audiomuse_token),
                          lambda: connections.enabled("audiomuse"),
                          **({"request": shared.audiomuse_request} if shared.audiomuse_request else {}))
    store = audiomuse.store

    def tags_of(paths: list[str]) -> dict[str, dict]:
        known = lib_index.stored(paths)
        out = {p: hit[2].get("tags") or {} for p, hit in known.items()}
        for p in paths:  # not indexed yet (a brand-new file): read it
            if p not in out:
                try:
                    out[p] = shared.to_out(p, shared.engine.load_metadata(library.resolve(p))).tags
                except Exception:  # noqa: BLE001 - an unreadable seed just doesn't count
                    pass
        return out

    autoplay = Autoplay(lib_index, tags_of, connections.enabled, shared.fetch_catalog or shared.catalog_fetch, audiomuse)
    shared.share(audiomuse=audiomuse, autoplay=autoplay)

    @app.post("/api/autoplay/next")
    def autoplay_next(body: AutoplayIn) -> dict:
        """Songs from the library to play after ``seeds``: none of ``avoid``, nothing downloaded."""
        seeds = []
        for p in body.seeds:
            try:
                library.resolve(p)  # only paths inside the music folder
                seeds.append(p)
            except (LibraryPathError, ValueError):
                continue
        found = autoplay.next_tracks(seeds, set(body.avoid), body.n)
        tracks = [t for t in shared.tracks_out(found["paths"]) if not t.error]
        return {"tracks": tracks, "source": found["source"], "source_name": SOURCE_NAMES[found["source"]],
                "because": found["because"]}

    def audiomuse_out() -> dict:
        return {
            "enabled": connections.enabled("audiomuse"),
            "configured": store.configured,
            "url": store.url, "has_token": bool(store.token),
            "locked": {"url": store.env_url is not None, "token": store.env_token is not None},
            "checked": audiomuse.checked, "error": audiomuse.last_error,
        }

    @app.get("/api/audiomuse")
    def get_audiomuse() -> dict:
        """The AudioMuse-AI connection (never the token)."""
        return audiomuse_out()

    @app.put("/api/audiomuse")
    def put_audiomuse(body: AudioMuseSettingsIn) -> dict:
        url = clean_url(body.url)
        if url:
            parts = urlsplit(url)
            if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
                    or any(c.isspace() for c in url) or parts.query or parts.fragment):
                raise HTTPException(422, "AudioMuse-AI's address should look like http://audiomuse:8000 or http://192.168.1.50:8000")
            try:
                parts.port
            except ValueError:
                raise HTTPException(422, "The port in AudioMuse-AI's address should be a number, like :8000") from None
        if body.token is not None and body.token.strip():
            token = body.token.strip()
            if any(c.isspace() for c in token) or not token.isprintable():
                raise HTTPException(422, "That doesn't look like an AudioMuse-AI API token.")
        with store.lock:
            if store.env_url is None:
                store.settings.url = url
            if body.token is not None and store.env_token is None:
                store.settings.token = body.token.strip()
            try:
                store.save()
            except OSError as exc:
                raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        audiomuse.checked, audiomuse.last_error = False, None
        if connections.enabled("audiomuse") and store.configured:  # off, or offline mode: nothing leaves the server
            audiomuse.check()
        return audiomuse_out()

    @app.post("/api/audiomuse/test")
    def test_audiomuse() -> dict:
        shared.require_connection("audiomuse")
        if not store.configured:
            raise HTTPException(422, "Add AudioMuse-AI's address first.")
        audiomuse.check()
        return audiomuse_out()
