"""Codetta's web app: a JSON API plus the single-page UI.

Run locally:
    CODETTA_MUSIC_DIR=~/Music uvicorn codetta.web.app:app --reload --port 8111

Settings (environment variables):
    CODETTA_MUSIC_DIR   the music library to edit (default: /music)
    CODETTA_CONFIG_DIR  where presets, the activity log and the account are
                     stored (default: ./config)
    CODETTA_USERNAME    optional: set the account here instead of the setup screen
    CODETTA_PASSWORD      (both must be set; the password can't then be changed in the UI)
    CODETTA_AUTH        "off" disables sign-in entirely, e.g. behind a reverse proxy
                     that already handles it (default: on)

  Codetta is fully offline unless you opt in. Online features ("connections")
  are off until turned on in the app (first-run card or Account → Connections)
  or here. Setting one of these locks its switch in the app:
    CODETTA_OFFLINE       "on" blocks every connection, whatever else is set
    CODETTA_MUSICBRAINZ   "on"/"off": Match on MusicBrainz + Cover Art Archive
    CODETTA_MUSICBRAINZ_URL  a self-hosted MusicBrainz mirror, e.g. http://mb:5000
                          (no rate limit; http is allowed for this one)
    CODETTA_ACOUSTID      "on"/"off": Identify by sound (AcoustID; needs MusicBrainz too)
    CODETTA_ACOUSTID_KEY  your own AcoustID application key instead of Codetta's
    CODETTA_FPCALC        path to Chromaprint's fpcalc (default: found on PATH)
    CODETTA_INBOX_DIR     a downloads folder outside the music folder (e.g. slskd's) for
                          the import inbox; /inbox in the Docker image (mount it there)
    CODETTA_LYRICS_LOOKUP "on"/"off": Find lyrics (asks lrclib.net, only when pressed)
    CODETTA_UPDATE_CHECK  "on"/"off": twice-daily check for new releases on GitHub
    CODETTA_UPDATE_REPO   where to look for releases (default: gavndev/codetta)

    CODETTA_ALLOW_PUBLIC_SETUP  "on" lets the first-run setup screen be used from a
                          public (internet) address; by default only home networks,
                          Tailscale and this machine can create the account
    CODETTA_ALLOWED_HOSTS optional comma-separated host names Codetta answers to
                          (e.g. "music-server,192.168.1.50"); blocks DNS rebinding
"""

from __future__ import annotations

import getpass
import hmac
import os
import re
import secrets
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from codetta.core import changelog, configversion
from codetta.core.acoustid import (
    DEFAULT_KEY as ACOUSTID_KEY,
)
from codetta.core.acoustid import (
    LOOKUP_URL as ACOUSTID_URL,
)
from codetta.core.acoustid import (
    AcoustID,
    Fingerprinter,
    find_fpcalc,
)
from codetta.core.activity import ActivityLog
from codetta.core.artwork import MAX_ART_BYTES
from codetta.core.auth import (
    SESSION_DAYS,
    AccountStore,
    AuthError,
    BusyError,
    LoginRateLimiter,
    SessionStore,
    needs_rehash,
)
from codetta.core.avatar import AvatarError, AvatarStore
from codetta.core.connections import ConnectionStore
from codetta.core.describe import describe_file, describe_many
from codetta.core.editions import EditionStore
from codetta.core.engine import MetadataEngine, MetadataError, TrackMetadata
from codetta.core.index import LibraryIndex
from codetta.core.library import Library, LibraryPathError, count_contents
from codetta.core.musicbrainz import MAX_MB_BYTES, MB_BASE, MB_TIMEOUT, MusicBrainz
from codetta.core.notifications import Notifications
from codetta.core.organize import prune_replaced
from codetta.core.presets import (
    FileResult,
    PresetError,
    PresetNotFoundError,
    PresetStore,
)
from codetta.core.providers import LRCLib, http_get, http_get_json, http_post_json
from codetta.core.lidarr import Lidarr, LidarrStore
from codetta.core.lidarr import http_request as lidarr_http_request
from codetta.core.loudness import Meter, find_ffmpeg
from codetta.core.mediaserver import MediaServer, ServerStore
from codetta.core.mediaserver import http_request as server_http_request
from codetta.core.slskd import Soulseek, SoulseekStore
from codetta.core.slskd import http_request as slskd_http_request
from codetta.core.undo import ArtStore, art_hashes, sha256
from codetta.core.updates import Fetcher, UpdateChecker, fetch_latest_release
from codetta.web.common import (
    ACTIVITY_VALUE_CHARS,
    SESSION_COOKIE,
    STATIC_DIR,
    VERSION,
    ApplyResultOut,
    ArtInfo,
    Credentials,
    FolderOut,
    PasswordChange,
    Settings,
    TrackOut,
    _is_public_address,
    _to_track_out,
    log,
)
from codetta.web.routes import (
    Shared,
    activity,
    care,
    explore,
    files,
    health,
    inbox,
    library,
    lidarr as lidarr_routes,
    mediaserver as mediaserver_routes,
    replaygain as replaygain_routes,
    musicbrainz,
    onboarding,
    organize,
    presets,
    soulseek,
    status,
    support,
    tags,
    tools,
)
from codetta.web.security import GuardMiddleware, SelectiveGZip

# The order matters a little: an area can use what earlier areas share right away,
# and reaches later ones through shared.later(...).
ROUTES = (status, library, musicbrainz, tags, organize, onboarding, inbox, care, soulseek, lidarr_routes, mediaserver_routes, replaygain_routes, explore, health, tools,
          files, support, activity, presets)
# Also importable from here, as before the split.
__all__ = ["ACTIVITY_VALUE_CHARS", "VERSION", "Settings", "_is_public_address", "_to_track_out", "app", "create_app"]


def create_app(settings: Settings | None = None, fetch_release: Fetcher = fetch_latest_release,
               fetch_json=None, fetch_mb=None, fetch_art=None, post_acoustid=None, run_fpcalc=None,
               slskd_request=None, fetch_catalog=None, lidarr_request=None,
               server_request=None, run_ffmpeg=None) -> FastAPI:
    """``fetch_*`` replace the network in tests: LRCLIB and MusicBrainz take
    (url) -> parsed JSON or None, the Cover Art Archive (url) -> bytes or None,
    AcoustID (form) -> parsed JSON; ``run_fpcalc`` replaces running fpcalc;
    ``slskd_request`` (method, url, headers, body) -> (status, body) stands in for slskd, and
    ``lidarr_request`` the same for Lidarr, ``server_request`` for the music server."""
    settings = settings or Settings.from_env()
    config_state = configversion.upgrade(settings.config_dir, VERSION)
    if settings.index_workers <= 0:
        settings.index_workers = max(1, min(4, (os.cpu_count() or 2) - 1))
    connections = ConnectionStore(
        settings.config_dir / "connections.json", offline=settings.offline,
        forced={"updates": settings.update_check, "lyrics": settings.lyrics_lookup, "musicbrainz": settings.musicbrainz,
                "acoustid": settings.acoustid, "slskd": settings.slskd, "lidarr": settings.lidarr,
                "mediaserver": settings.media_server},
    )
    updates = UpdateChecker(VERSION, settings.update_repo, lambda: connections.enabled("updates"), fetch_release)
    library = Library(settings.music_dir, settings.inbox_dir, settings.config_dir / "replaced", settings.config_dir / "deleted")
    store = PresetStore(settings.config_dir / "presets")
    engine = MetadataEngine()
    activity = ActivityLog(settings.config_dir / "activity.jsonl")
    art_store = ArtStore(settings.config_dir / "undo-art")
    avatars = AvatarStore(settings.config_dir / "avatars")
    accounts = AccountStore(settings.config_dir / "auth.json", settings.username, settings.password)
    sessions = SessionStore(settings.config_dir / "sessions.json")
    limiter = LoginRateLimiter()
    user_agent = f"Codetta/{VERSION} (https://github.com/gavndev/codetta)"
    notices = Notifications(settings.config_dir / "notifications.json")
    if config_state.status == "newer":
        notices.add("warning", "Settings from a newer Codetta",
                    "These settings were saved by a newer version of Codetta. They're used as they are, "
                    "but some may be ignored. Update Codetta again to get everything back.",
                    key=f"config-newer:{config_state.version}:{VERSION}")
    editions = EditionStore(settings.config_dir / "editions.json")
    soulseek_store = SoulseekStore(settings.config_dir / "slskd.json", settings.slskd_url, settings.slskd_api_key)
    soulseek = Soulseek(soulseek_store, request=slskd_request or slskd_http_request,
                        notify=lambda title, body, action: notices.add("soulseek", title, body, action))
    lrclib = LRCLib(fetch_json or (lambda url: http_get_json(url, user_agent)))
    mb_mirror = settings.musicbrainz_url.rstrip("/") if settings.musicbrainz_url else None
    if mb_mirror and not mb_mirror.endswith("/ws/2"):
        mb_mirror += "/ws/2"
    mb = MusicBrainz(
        fetch_mb or (lambda url: http_get_json(url, user_agent, max_bytes=MAX_MB_BYTES, service="MusicBrainz",
                                               allow_http=mb_mirror is not None, timeout=MB_TIMEOUT)),
        base=mb_mirror or MB_BASE,
        min_interval=0 if mb_mirror else 1.0,  # musicbrainz.org allows one request a second
    )
    def catalog_fetch(url: str):
        service = "Deezer" if "deezer" in url else "iTunes"
        return http_get_json(url, user_agent, max_bytes=MAX_MB_BYTES, service=service)

    fpcalc_path = find_fpcalc(settings.fpcalc) or ("fpcalc" if run_fpcalc else None)
    fingerprinter = Fingerprinter(fpcalc_path, **({"run": run_fpcalc} if run_fpcalc else {}))
    meter = Meter(find_ffmpeg(settings.ffmpeg), run=run_ffmpeg)
    acoustid = AcoustID(post_acoustid or (lambda form: http_post_json(ACOUSTID_URL, user_agent, form, service="AcoustID")),
                        key=settings.acoustid_key or ACOUSTID_KEY)
    download_art = fetch_art or (lambda url: http_get(url, user_agent, accept="image/*", max_bytes=MAX_ART_BYTES,
                                                 service="the Cover Art Archive"))

    lib_index = LibraryIndex(settings.music_dir, settings.config_dir / "library-index.sqlite3", describe_file,
                             parallel=describe_many, workers=settings.index_workers)
    lidarr = Lidarr(LidarrStore(settings.config_dir / "lidarr.json", settings.lidarr_url, settings.lidarr_api_key),
                    settings.music_dir, lambda: connections.enabled("lidarr"), request=lidarr_request or lidarr_http_request)
    media_server = MediaServer(ServerStore(settings.config_dir / "mediaserver.json", settings.media_server_env),
                               lambda: connections.enabled("mediaserver"), request=server_request or server_http_request)
    index_mark_dirty = lib_index.mark_dirty

    def mark_dirty(rels) -> None:
        """Every route that changes files calls this: the search index re-reads them, and Lidarr
        and the music server (when connected) are asked to rescan."""
        rels = list(rels)
        index_mark_dirty(rels)
        lidarr.changed(rels)
        media_server.changed(rels)

    lib_index.mark_dirty = mark_dirty
    if not settings.auth:
        log.warning("Sign-in is turned OFF (CODETTA_AUTH=off). Anyone who can reach Codetta can edit your music.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # On startup (not on import), add the starter presets if missing.
        try:
            store.install_defaults()
        except OSError:
            pass  # read-only config folder: presets just won't be saved
        # Drop saved album art that no remembered change refers to any more.
        try:
            art_store.prune(h for rec in activity.undo_records() for h in art_hashes(rec))
        except OSError:
            pass
        lib_index.start()  # builds/refreshes the search index in the background
        prune_replaced(settings.config_dir / "replaced")  # upgrades' old albums, after 30 days
        prune_replaced(settings.config_dir / "deleted")  # "Recently deleted", after 30 days
        watcher = threading.Thread(target=app.state.inbox_watch, name="codetta-inbox-watch", daemon=True)
        watcher.start()  # sleeps; only looks at the inbox if "check every 15 minutes" is on
        app.state.soulseek_start()  # carries on with downloads that were under way
        app.state.care_start()  # Library care carries on where it left off (if it's switched on)
        if lidarr.active:  # what Lidarr is set up like (folders, renaming, tag writing)
            threading.Thread(target=lidarr.check, name="codetta-lidarr-check", daemon=True).start()
        if media_server.active:
            threading.Thread(target=media_server.check, name="codetta-mediaserver-check", daemon=True).start()
        yield
        lidarr.stop()
        media_server.stop()
        app.state.care_stop()
        app.state.inbox_stop()
        app.state.soulseek_stop()
        try:
            soulseek_store.save()  # the latest download progress (written to disk only now and then)
        except OSError:
            pass
        lib_index.stop()

    app = FastAPI(
        title="Codetta", version=VERSION, docs_url="/docs", redoc_url=None, lifespan=lifespan
    )
    app.state.index = lib_index

    # Map Codetta's errors to HTTP status codes, with a readable message.
    def _error(status: int):
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc)})

        return handler

    app.add_exception_handler(LibraryPathError, _error(400))
    app.add_exception_handler(FileNotFoundError, _error(404))
    app.add_exception_handler(MetadataError, _error(422))
    app.add_exception_handler(PresetNotFoundError, _error(404))
    app.add_exception_handler(PresetError, _error(422))

    # --- Sign-in --------------------------------------------------------------------------

    # Everything needs a signed-in session except the page shell, its static
    # files, the sign-in endpoints themselves, and the health check.
    PUBLIC_PATHS = {"/", "/api/health", "/api/changelog"}  # the changelog is the public CHANGELOG.md
    PUBLIC_PREFIXES = ("/static/", "/api/auth/")

    @app.middleware("http")
    async def require_sign_in(request: Request, call_next):
        path = request.url.path
        if settings.auth and not (path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)):
            if sessions.lookup(request.cookies.get(SESSION_COOKIE)) is None:
                return JSONResponse(status_code=401, content={"detail": "Sign in required"})
        return await call_next(request)

    def client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def start_session(request: Request, response: Response, username: str) -> None:
        token = sessions.create(username)
        response.set_cookie(
            SESSION_COOKIE, token,
            max_age=SESSION_DAYS * 86400,
            httponly=True,  # not readable by JavaScript
            samesite="lax",  # not sent with other sites' form posts
            secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
            path="/",
        )

    def check_rate_limit(request: Request) -> None:
        wait = limiter.retry_after(client_key(request))
        if wait:
            raise HTTPException(
                429, f"Too many attempts. Try again in {wait} seconds.", headers={"Retry-After": str(wait)}
            )

    @app.get("/api/changelog")
    def get_changelog() -> dict:
        """What's new in each version (also shown on the sign-in screen)."""
        return {"current": VERSION, "versions": changelog.load()}

    @app.get("/api/health", include_in_schema=False)
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/auth/status")
    def auth_status(request: Request) -> dict:
        user = sessions.lookup(request.cookies.get(SESSION_COOKIE)) if settings.auth else None
        return {
            "version": VERSION,
            "auth_enabled": settings.auth,
            "setup_required": settings.auth and accounts.setup_required,
            "signed_in": (not settings.auth) or user is not None,
            "username": user,
            "managed_by_env": accounts.managed_by_env,
            "desktop": settings.desktop_token is not None,
            # Changes when the profile picture does; None if there isn't one.
            "avatar": avatars.version(user) if user else None,
        }

    @app.get("/api/auth/desktop", include_in_schema=False)
    def auth_desktop(request: Request, token: str = ""):
        """The desktop app's window: signs in with the secret made for this launch (no sign-in screen).
        The first time, it makes the account itself, with a random password nobody needs to know
        (``codetta set-password`` sets a real one, to reach Codetta from other devices)."""
        expected = settings.desktop_token
        if not settings.auth or not expected or not hmac.compare_digest(token.encode(), expected.encode()):
            raise HTTPException(404, "Not Found")
        if accounts.setup_required:
            try:
                name = re.sub(r"[^A-Za-z0-9._-]", "", getpass.getuser())[:64]
            except (OSError, KeyError, ImportError):
                name = ""
            try:
                accounts.create(name if len(name) >= 3 else "codetta", secrets.token_urlsafe(24))
            except (AuthError, OSError) as exc:
                raise HTTPException(500, f"Could not save the account to the config folder: {exc}") from exc
        account = accounts.get()
        response = RedirectResponse("/", status_code=303)
        start_session(request, response, account.username)
        return response

    @app.post("/api/desktop/quit", include_in_schema=False)
    def desktop_quit() -> dict:
        """Quit the desktop app (when it opened in a browser tab, there's no window to close)."""
        quit_app = getattr(app.state, "desktop_quit", None)
        if settings.desktop_token is None or quit_app is None:
            raise HTTPException(404, "Not Found")
        threading.Timer(0.3, quit_app).start()  # answer first, then stop
        return {"ok": True}

    @app.post("/api/auth/setup")
    def auth_setup(body: Credentials, request: Request, response: Response) -> dict:
        """First run only: create the account and sign in."""
        if not settings.auth:
            raise HTTPException(400, "Sign-in is turned off")
        if not accounts.setup_required:
            raise HTTPException(409, "Codetta is already set up. Sign in instead.")
        if not settings.allow_public_setup and _is_public_address(client_key(request)):
            # Someone on the internet must never be able to claim a fresh install.
            log.warning("Refused first-run setup from public address %s", client_key(request))
            raise HTTPException(403, "For safety, set up Codetta from your home network or Tailscale "
                                     "(or set CODETTA_ALLOW_PUBLIC_SETUP=on).")
        try:
            account = accounts.create(body.username, body.password)
        except BusyError as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "5"}) from exc
        except AuthError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"Could not save the account to the config folder: {exc}") from exc
        log.info("Account %r created", account.username)
        start_session(request, response, account.username)
        return {"username": account.username}

    @app.post("/api/auth/login")
    def auth_login(body: Credentials, request: Request, response: Response) -> dict:
        if not settings.auth:
            return {"username": None}
        check_rate_limit(request)
        try:
            account = accounts.check(body.username, body.password)
        except BusyError as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "5"}) from exc
        if account is None:
            limiter.failed(client_key(request))
            # Never the typed username: people sometimes type their password into that box.
            log.warning("Failed sign-in from %s", client_key(request))
            raise HTTPException(401, "Wrong username or password")
        limiter.succeeded(client_key(request))
        if needs_rehash(account.password_hash) and not accounts.managed_by_env:
            try:  # upgrade older, weaker password hashes now that we have the password
                accounts.set_password(account.username, body.password)
            except (AuthError, OSError):
                pass
        start_session(request, response, account.username)
        return {"username": account.username}

    @app.post("/api/auth/logout")
    def auth_logout(request: Request, response: Response) -> dict:
        sessions.revoke(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/auth/password")
    def auth_change_password(body: PasswordChange, request: Request) -> dict:
        """Change the password; every other signed-in device is signed out."""
        token = request.cookies.get(SESSION_COOKIE)
        user = sessions.lookup(token)
        if not settings.auth or user is None:
            raise HTTPException(401, "Sign in required")
        check_rate_limit(request)
        try:
            current_ok = accounts.check(user, body.current_password) is not None
        except BusyError as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "5"}) from exc
        if not current_ok:
            limiter.failed(client_key(request))
            raise HTTPException(401, "Your current password is wrong")
        try:
            accounts.set_password(user, body.new_password)
        except BusyError as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "5"}) from exc
        except AuthError as exc:
            raise HTTPException(422, str(exc)) from exc
        sessions.revoke_all(keep=token)
        log.info("Password changed for %r", user)
        return {"ok": True}

    # --- Profile picture ------------------------------------------------------------------

    def current_user(request: Request) -> str:
        user = sessions.lookup(request.cookies.get(SESSION_COOKIE)) if settings.auth else "codetta"
        if user is None:
            raise HTTPException(401, "Sign in required")
        return user

    @app.get("/api/account/avatar", responses={200: {"content": {"image/webp": {}, "image/jpeg": {}, "image/png": {}}}})
    def get_avatar(request: Request):
        found = avatars.get(current_user(request))
        if found is None:
            raise HTTPException(404, "No profile picture")
        data, mime = found
        # The UI adds ?v=<version> to the URL, so a new picture gets a new URL.
        return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.put("/api/account/avatar")
    async def set_avatar(request: Request) -> dict:
        """Body: a square JPEG, PNG or WebP image (the browser crops and resizes it)."""
        user = current_user(request)
        data = await request.body()  # size already capped by GuardMiddleware
        try:
            await run_in_threadpool(avatars.save, user, data)
        except AvatarError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"Could not save the picture: {exc}") from exc
        return {"avatar": avatars.version(user)}

    @app.delete("/api/account/avatar")
    def delete_avatar(request: Request) -> dict:
        avatars.delete(current_user(request))
        return {"avatar": None}

    def require_library() -> None:
        if not library.exists():
            raise HTTPException(
                503,
                f"Music folder not found: {library.root}. "
                "Set CODETTA_MUSIC_DIR (or mount your music at /music in Docker).",
            )

    # Embedded-art fingerprints, remembered per (file, version) so re-opening a
    # folder doesn't re-read every cover.
    # Small tuples (hash, width, height), not models: this can hold thousands of entries.
    art_cache: dict[tuple[str, int], tuple[str, int | None, int | None] | None] = {}

    def art_info(rel: str, target: Path, mtime: int | None) -> ArtInfo | None:
        key = (rel, mtime or 0)
        if mtime is not None and key in art_cache:
            hit = art_cache[key]
            return ArtInfo(hash=hit[0], width=hit[1], height=hit[2]) if hit else None
        try:
            art = engine.read_artwork(target)
        except (MetadataError, OSError):
            art = None
        info = (sha256(art.data)[:16], art.width, art.height) if art else None
        if mtime is not None:
            if len(art_cache) > 10000:
                art_cache.clear()
            art_cache[key] = info
        return ArtInfo(hash=info[0], width=info[1], height=info[2]) if info else None

    def to_out(rel: str, meta: TrackMetadata) -> TrackOut:
        target = library.resolve(rel)
        try:
            mtime = target.stat().st_mtime_ns
        except OSError:
            mtime = None
        out = _to_track_out(rel, meta, mtime)
        out.art = art_info(rel, target, mtime)
        return out

    def folder_out(rel: str) -> FolderOut:
        counts = count_contents(library.resolve(rel))
        return FolderOut(
            name=rel.rsplit("/", 1)[-1], path=rel,
            folders=counts[0] if counts else None, tracks=counts[1] if counts else None,
        )

    # Tags of files that haven't changed since they were last read (same modification
    # time, size and inode; every save through the engine replaces the file, so all
    # three change). Opening a folder again then skips reading every file.
    track_memory: OrderedDict[str, tuple[tuple[int, int, int], TrackOut]] = OrderedDict()
    TRACK_MEMORY = 3000
    track_memory_lock = threading.Lock()  # requests run in a thread pool

    def track_out(rel: str) -> TrackOut:
        name = rel.rsplit("/", 1)[-1]
        try:
            target = library.resolve(rel)
            st = target.stat()
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
            with track_memory_lock:
                hit = track_memory.get(rel)
                if hit is not None and hit[0] == stamp:
                    track_memory.move_to_end(rel)
                    return hit[1]
            out = to_out(rel, engine.load_metadata(target))
            with track_memory_lock:
                track_memory[rel] = (stamp, out)
                while len(track_memory) > TRACK_MEMORY:
                    track_memory.popitem(last=False)
            return out
        except (MetadataError, OSError) as exc:
            with track_memory_lock:
                track_memory.pop(rel, None)
            return TrackOut(path=rel, name=name, error=str(exc))

    def tracks_out(rels: list[str]) -> list[TrackOut]:
        """A folder's tracks. Files the search index already knows unchanged (same modification
        time and size) come from the index: a folder of thousands opens without reading a file."""
        known = lib_index.stored(rels) if len(rels) > 20 else {}
        out = []
        for rel in rels:
            hit = known.get(rel)
            if hit is not None:
                try:
                    st = library.resolve(rel).stat()
                    if (st.st_mtime_ns, st.st_size) == (hit[0], hit[1]) and not hit[2].get("error"):
                        out.append(TrackOut(**hit[2]))
                        continue
                except (OSError, LibraryPathError, ValueError):
                    pass
            out.append(track_out(rel))
        return out

    def result_out(r: FileResult) -> ApplyResultOut:
        return ApplyResultOut(
            path=library.relative(r.path),
            applied=r.applied,
            kept_existing=r.kept_existing,
            unsupported=r.unsupported,
            error=r.error,
        )

    # --- The API, one area per module in codetta/web/routes ----------------------------------
    shared = Shared(
        acoustid=acoustid, activity=activity, art_cache=art_cache, art_info=art_info, art_store=art_store,
        catalog_fetch=catalog_fetch, connections=connections, download_art=download_art, editions=editions,
        engine=engine, fetch_catalog=fetch_catalog, fingerprinter=fingerprinter, folder_out=folder_out, meter=meter,
        lib_index=lib_index, library=library, lidarr=lidarr, lrclib=lrclib, media_server=media_server, mb=mb, mb_mirror=mb_mirror, notices=notices,
        require_library=require_library, result_out=result_out, settings=settings, soulseek=soulseek,
        soulseek_store=soulseek_store, store=store, to_out=to_out, tracks_out=tracks_out, updates=updates,
    )
    for area in ROUTES:
        area.register(app, shared)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    # Size limits, cross-site protection and security headers (see web/security.py).
    # Added last so it wraps everything, including the sign-in check's 401s.
    app.add_middleware(SelectiveGZip)  # inside the guard: rejected requests never reach it
    app.add_middleware(GuardMiddleware, allowed_hosts=set(settings.allowed_hosts))
    return app


app = create_app()
