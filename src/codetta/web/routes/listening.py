"""Listening: stars, ratings, play counts and playlists (kept for music apps and Codetta's own
player), ListenBrainz scrobbling, and plays reported by Codetta's player."""

from __future__ import annotations

from collections import Counter

from fastapi import HTTPException, Query

from codetta.core.library import LibraryPathError
from codetta.core.listenbrainz import ListenBrainzError, Scrobbler
from codetta.core.listening import Listening, moves_in
from codetta.web.common import VERSION, ListenBrainzIn, PlayedIn, PlaylistChangeIn, PlaylistIn, StarIn

LIST_SIZE = 100  # most played / recently played
SONGS_MAX = 10_000  # Your music → Songs lists this many at most (search finds the rest)
PREVIEW = 12  # albums and songs on the Your music overview


def _first(tags: dict, key: str) -> str:
    v = tags.get(key)
    return str((v[0] if isinstance(v, list) and v else v) or "").strip()


def tagged_library(cat) -> dict:
    """Your music's Albums and Songs, from the music apps' catalogue: only what's properly tagged.
    An album needs an album title and an album artist (so leftover tracks and untagged folders
    stay out); a song needs a title and an artist."""
    from posixpath import commonpath, dirname

    from codetta.core.subsonic import sfold

    albums = []
    for a in cat.albums.values():
        if not (_first(a.tags, "album") and _first(a.tags, "albumartist")):
            continue
        paths = [cat.songs[s].path for s in a.songs]
        # Where it opens: the album's folder (its disc folders' parent), or, when copies sit in unrelated
        # folders, the one holding most of it.
        counts = Counter(dirname(p) for p in paths)
        try:
            folder = commonpath(list(counts)) if len(counts) > 1 else next(iter(counts))
        except ValueError:
            folder = ""
        if not folder or folder.count("/") < min(d.count("/") for d in counts) - 1:
            folder = counts.most_common(1)[0][0]
        cover = cat.songs[next((s for s in a.songs if cat.songs[s].path == a.cover), a.songs[0])].track if a.cover else None
        albums.append({"id": a.id, "name": a.name, "artist": a.artist, "year": a.year, "folder": folder, "songs": len(a.songs),
                       "added": int(a.created), "cover": {"path": a.cover, "hash": (cover.get("art") or {}).get("hash")} if a.cover else None,
                       "_sort": (sfold(_first(a.tags, "albumartistsort") or a.artist), a.year or 0, sfold(a.name))})
    albums.sort(key=lambda x: x.pop("_sort"))
    songs = []
    for a in sorted(cat.albums.values(), key=lambda a: (sfold(a.artist), a.year or 0, sfold(a.name))):
        for sid in a.songs:
            s = cat.songs[sid]
            t = s.track.get("tags") or {}
            if _first(t, "title") and _first(t, "artist"):
                songs.append(s)
    return {"albums": albums, "songs": songs}


def song_out(s) -> dict:
    return {**s.track, "path": s.path}


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

    # --- Your music: favourites, most and recently played, playlists (the same ones music apps see) ----

    def existing(paths: list[str]) -> list[str]:
        out = []
        for p in paths:
            try:
                if library.resolve(p).is_file():
                    out.append(p)
            except (LibraryPathError, ValueError):
                continue
        return out

    def checked(paths: list[str]) -> list[str]:
        good = existing(list(dict.fromkeys(paths)))
        if len(good) != len(set(paths)):
            raise HTTPException(400, "Some of those files aren't in your music folder")
        return paths

    memo: dict = {}

    def library_now() -> dict:
        """Albums and songs as the catalogue has them now (worked out once per catalogue)."""
        try:
            cat = shared.music_catalog.get()
        except Exception:  # noqa: BLE001 - Your music still shows lists and playlists
            return {"albums": [], "songs": []}
        if memo.get("cat") is not cat:
            memo["cat"], memo["lib"] = cat, tagged_library(cat)
        return memo["lib"]

    def summary() -> dict:
        songs = listening.marks().get("s", {})
        lists = [{"id": pl.id, "name": pl.name, "tracks": len(pl.paths), "changed": pl.changed, "first": pl.paths[0] if pl.paths else None}
                 for pl in listening.playlists()]
        return {"starred": sum(1 for m in songs.values() if m.starred), "played": sum(1 for m in songs.values() if m.plays),
                "playlists": lists}

    @app.get("/api/yours")
    def yours(view: str = Query("", max_length=20), id: int = Query(0, ge=0)) -> dict:
        """Your music: the overview (counts and playlists), or one list as tracks: "starred",
        "most" (played), "recent" (played) or "playlist" (``id``)."""
        shared.require_library()
        songs = listening.marks().get("s", {})
        if view in ("", "albums", "songs"):
            lib = library_now()
            if view == "":
                newest = sorted(lib["songs"], key=lambda s: -s.mtime)[:PREVIEW]
                return {**summary(), "albums": len(lib["albums"]), "songs": len(lib["songs"]),
                        "recent_albums": sorted(lib["albums"], key=lambda a: -a["added"])[:PREVIEW],
                        "recent_songs": [song_out(s) for s in newest]}
            if view == "albums":
                return {"name": "Albums", "albums": lib["albums"], "tracks": []}
            shown = lib["songs"][:SONGS_MAX]
            return {"name": "Songs", "tracks": [song_out(s) for s in shown], "total": len(lib["songs"]),
                    "plays": {s.path: songs[s.path].plays for s in shown if s.path in songs},
                    "starred": [s.path for s in shown if s.path in songs and songs[s.path].starred]}
        if view == "starred":
            paths = [p for p, m in sorted(songs.items(), key=lambda kv: -(kv[1].starred or 0)) if m.starred]
            name = "Favourites"
        elif view == "most":
            paths = [p for p, m in sorted(songs.items(), key=lambda kv: (-kv[1].plays, -(kv[1].last_played or 0))) if m.plays][:LIST_SIZE]
            name = "Most played"
        elif view == "recent":
            paths = [p for p, m in sorted(songs.items(), key=lambda kv: -(kv[1].last_played or 0)) if m.last_played][:LIST_SIZE]
            name = "Recently played"
        elif view == "playlist":
            pl = listening.playlist(id)
            if pl is None:
                raise HTTPException(404, "That playlist is gone")
            paths, name = pl.paths, pl.name
        else:
            raise HTTPException(404, "Nothing here")
        paths = existing(paths)
        plays = {p: songs[p].plays for p in paths if p in songs}
        starred = [p for p in paths if p in songs and songs[p].starred]
        return {"name": name, "tracks": [t.model_dump() for t in shared.tracks_out(paths)], "plays": plays, "starred": starred}

    @app.get("/api/yours/starred")
    def starred_paths(paths: list[str] = Query(default=[], max_length=2000)) -> dict:
        """Which of these songs are favourites (for the heart on a folder's rows)."""
        songs = listening.marks().get("s", {})
        return {"starred": [p for p in paths if p in songs and songs[p].starred]}

    @app.post("/api/yours/star")
    def star(body: StarIn) -> dict:
        """Add songs to (or take them out of) your favourites: the same stars music apps show."""
        listening.star("s", checked(body.paths), body.on)
        return summary()

    @app.post("/api/playlists")
    def new_playlist(body: PlaylistIn) -> dict:
        pid = listening.create_playlist(body.name.strip() or "New playlist", checked(body.paths))
        return {"id": pid, **summary()}

    @app.put("/api/playlists/{pid}")
    def change_playlist(pid: int, body: PlaylistChangeIn) -> dict:
        """Rename, add songs to the end, or take songs out (every copy of them)."""
        pl = listening.playlist(pid)
        if pl is None:
            raise HTTPException(404, "That playlist is gone")
        if body.order is not None:
            shown = existing(pl.paths)  # the page never sees songs whose file is gone: they keep their place at the end
            if Counter(body.order) != Counter(shown):
                raise HTTPException(409, "This playlist changed somewhere else (a music app?). Here it is as it is now: try again.")
            missing = Counter(pl.paths) - Counter(shown)
            listening.replace_playlist(pid, body.order + list(missing.elements()), name=body.name)
            return summary()
        gone = set(body.remove)
        drop = [i for i, p in enumerate(pl.paths) if p in gone]
        listening.update_playlist(pid, name=body.name, add=checked(body.add), remove=drop)
        return summary()

    @app.delete("/api/playlists/{pid}")
    def delete_playlist(pid: int) -> dict:
        if not listening.delete_playlist(pid):
            raise HTTPException(404, "That playlist is gone")
        return summary()
