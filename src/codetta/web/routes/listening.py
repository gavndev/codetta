"""Listening: stars, ratings, play counts and playlists (kept for music apps and Codetta's own
player), ListenBrainz scrobbling, and plays reported by Codetta's player."""

from __future__ import annotations

from fastapi import HTTPException

from codetta.core.library import LibraryPathError
from codetta.core.listenbrainz import ListenBrainzError, Scrobbler
from codetta.core.listening import Listening, moves_in
from codetta.web.common import VERSION, ListenBrainzIn, PlayedIn


def song_meta(tags: dict, duration: float | None) -> dict:
    """What ListenBrainz wants to know about a song, from its tags."""
    def first(key: str) -> str:
        v = tags.get(key)
        return str((v[0] if isinstance(v, list) and v else v) or "").strip()

    return {"artist": first("artist") or first("albumartist"), "title": first("title"), "album": first("album"),
            "recording_mbid": first("musicbrainz_trackid"), "release_mbid": first("musicbrainz_albumid"),
            "artist_mbids": [x for x in (tags.get("musicbrainz_artistid") or []) if x][:10],
            "tracknumber": first("tracknumber").split("/")[0], "duration": duration or 0}


def register(app, shared) -> None:
    settings = shared.settings
    connections = shared.connections
    library = shared.library
    listening = Listening(settings.config_dir / "listening.sqlite3")
    scrobbler = Scrobbler(settings.config_dir, lambda: connections.enabled("listenbrainz"),
                          env_token=settings.listenbrainz_token, version=VERSION,
                          **({"post": shared.listenbrainz_post} if shared.listenbrainz_post else {}))

    def follow_moves(entry: dict) -> None:
        pairs = moves_in(entry.get("undo"))
        if pairs:
            listening.move(pairs)

    shared.activity.listeners.append(follow_moves)
    shared.share(listening=listening, scrobbler=scrobbler, song_meta=song_meta)

    def lb_out() -> dict:
        return {"enabled": connections.enabled("listenbrainz"), "has_token": bool(scrobbler.token),
                "locked": scrobbler.locked, "user_name": scrobbler.user_name, "error": scrobbler.last_error,
                "pending": scrobbler.pending(), "sent": scrobbler.sent}

    @app.get("/api/listenbrainz")
    def get_listenbrainz() -> dict:
        """ListenBrainz scrobbling: is it set up (never the token itself)."""
        return lb_out()

    @app.put("/api/listenbrainz")
    def put_listenbrainz(body: ListenBrainzIn) -> dict:
        token = body.token.strip()
        if token and (len(token) < 20 or any(c.isspace() for c in token) or not token.isprintable()):
            raise HTTPException(422, "That doesn't look like a ListenBrainz user token (listenbrainz.org → Settings).")
        try:
            scrobbler.set_token(token)
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        if token and connections.enabled("listenbrainz"):  # off, or offline: nothing leaves the server
            try:
                scrobbler.validate()
                scrobbler.last_error = None
            except ListenBrainzError as exc:
                scrobbler.last_error = str(exc)
        return lb_out()

    @app.post("/api/listenbrainz/test")
    def test_listenbrainz() -> dict:
        shared.require_connection("listenbrainz")
        try:
            scrobbler.validate()
            scrobbler.last_error = None
        except ListenBrainzError as exc:
            scrobbler.last_error = str(exc)
        return lb_out()

    @app.post("/api/played")
    def played(body: PlayedIn) -> dict:
        """Codetta's own player finished (most of) a song: count it, and scrobble it when set up."""
        try:
            target = library.resolve(body.path)
        except (LibraryPathError, ValueError):
            raise HTTPException(400, "That file isn't in your music folder") from None
        if not target.is_file():
            raise HTTPException(404, "No such file")
        known = shared.lib_index.stored([body.path]).get(body.path)
        track = known[2] if known else {}
        tags = track.get("tags") or {}
        if not tags:
            try:
                tags = shared.engine.load_metadata(target).tags
            except Exception:  # noqa: BLE001 - count it anyway
                tags = {}
        from codetta.core.subsonic import artist_id, fingerprint, make_id
        album_key = (f"mb\x1f{tags['musicbrainz_albumid'][0].lower()}" if tags.get("musicbrainz_albumid") else None)
        also = [("r", artist_id((tags.get("albumartist") or tags.get("artist") or ["Unknown artist"])[0]))]
        if album_key:
            also.append(("a", make_id("a", album_key)))
        listening.played(body.path, fp=fingerprint(tags, track.get("duration") or 0), also=also)
        scrobbler.listened(song_meta(tags, track.get("duration")), player="Codetta")
        return {"ok": True}
