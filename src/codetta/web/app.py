"""Codetta's web app: a JSON API plus the single-page UI.

Run locally:
    CODETTA_MUSIC_DIR=~/Music uvicorn codetta.web.app:app --reload --port 8111

Settings (environment variables):
    CODETTA_MUSIC_DIR   the music library to edit (default: /music)
    CODETTA_CONFIG_DIR  where loadouts, the activity log and the account are
                     stored (default: ./config)
    CODETTA_USERNAME    optional: set the account here instead of the setup screen
    CODETTA_PASSWORD      (both must be set; the password can't then be changed in the UI)
    CODETTA_AUTH        "off" disables sign-in entirely, e.g. behind a reverse proxy
                     that already handles it (default: on)
    CODETTA_UPDATE_CHECK  "off" stops the twice-daily check for new releases on GitHub
    CODETTA_UPDATE_REPO   where to look for releases (default: gavndev/codetta)
    CODETTA_LYRICS_LOOKUP "off" hides "Find lyrics" (which asks lrclib.net, only when pressed)
    CODETTA_ALLOW_PUBLIC_SETUP  "on" lets the first-run setup screen be used from a
                          public (internet) address; by default only home networks,
                          Tailscale and this machine can create the account
    CODETTA_ALLOWED_HOSTS optional comma-separated host names Codetta answers to
                          (e.g. "music-server,192.168.1.50"); blocks DNS rebinding
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from codetta.core.activity import ActivityLog
from codetta.core.artwork import sniff_image_type
from codetta.core.avatar import AvatarError, AvatarStore
from codetta.core.auth import (
    SESSION_DAYS,
    AccountStore,
    AuthError,
    BusyError,
    LoginRateLimiter,
    SessionStore,
    needs_rehash,
)
from codetta.core.engine import MetadataEngine, MetadataError, TrackMetadata
from codetta.core.index import LibraryIndex, parse_query
from codetta.core.library import Library, LibraryPathError, count_contents
from codetta.core.providers import LRCLib, ProviderError, TrackQuery, http_get_json
from codetta.core.rawtags import read_raw
from codetta.core.presets import (
    PLACEHOLDERS,
    FileResult,
    Loadout,
    LoadoutError,
    LoadoutNotFoundError,
    LoadoutStore,
    apply_loadout,
    apply_loadout_to_folder,
    slugify,
)
from codetta.core.tagmap import FIELDS
from codetta.core.undo import ArtStore, art_hashes, sha256, undo_change
from codetta.core.updates import DEFAULT_REPO, Fetcher, UpdateChecker, fetch_latest_release
from codetta.web.security import GuardMiddleware

STATIC_DIR = Path(__file__).parent / "static"
SESSION_COOKIE = "codetta_session"
log = logging.getLogger("codetta")
if not log.handlers:  # show Codetta's own messages (sign-ins etc.) next to uvicorn's
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     codetta: %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False

try:
    VERSION = version("codetta")
except PackageNotFoundError:  # running from a source checkout without install
    VERSION = "dev"


def env(name: str, default: str | None = None) -> str | None:
    """Read CODETTA_<name>, falling back to the old CODA_<name> (Codetta's earlier name)."""
    return os.environ.get(f"CODETTA_{name}") or os.environ.get(f"CODA_{name}") or default


@dataclass
class Settings:
    music_dir: Path
    config_dir: Path
    auth: bool = True
    username: str | None = None  # from CODETTA_USERNAME (with password: overrides setup)
    password: str | None = None
    update_check: bool = False  # on by default via from_env; off for tests/embedding
    lyrics_lookup: bool = True  # "Find lyrics" button (asks LRCLIB only when pressed)
    update_repo: str = DEFAULT_REPO
    allowed_hosts: tuple[str, ...] = ()  # empty = answer to any host name
    allow_public_setup: bool = False  # first-run setup only from private addresses

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            music_dir=Path(env("MUSIC_DIR", "/music")).expanduser(),
            config_dir=Path(env("CONFIG_DIR", "config")).expanduser(),
            auth=env("AUTH", "on").strip().lower() not in ("off", "false", "0", "no"),
            username=env("USERNAME"),
            password=env("PASSWORD"),
            update_check=env("UPDATE_CHECK", "on").strip().lower() not in ("off", "false", "0", "no"),
            lyrics_lookup=env("LYRICS_LOOKUP", "on").strip().lower() not in ("off", "false", "0", "no"),
            update_repo=env("UPDATE_REPO", DEFAULT_REPO),
            allowed_hosts=tuple(h.strip() for h in (env("ALLOWED_HOSTS") or "").split(",") if h.strip()),
            allow_public_setup=(env("ALLOW_PUBLIC_SETUP") or "").strip().lower() in ("on", "true", "1", "yes"),
        )


# --- API models -------------------------------------------------------------------


class Credentials(BaseModel):
    username: str = Field(max_length=200)
    password: str = Field(max_length=2000)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=2000)
    new_password: str = Field(max_length=2000)

TagValueIn = str | list[str] | None


class ArtInfo(BaseModel):
    hash: str  # SHA-256 of the image: identical covers share one URL, so they load once
    width: int | None = None
    height: int | None = None


class TrackOut(BaseModel):
    path: str
    name: str
    format: str | None = None
    tags: dict[str, list[str]] = {}
    duration: float | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    mtime: int | None = None  # changes whenever the file does (used to refresh cover art)
    art: ArtInfo | None = None  # embedded cover, if any
    error: str | None = None  # set if the file couldn't be read
    partial: bool = False  # from the search index: long/technical tags left out (editor reloads)


class Crumb(BaseModel):
    name: str
    path: str


class FolderOut(BaseModel):
    name: str
    path: str
    folders: int | None = None  # subfolders inside it (None if unreadable)
    tracks: int | None = None  # audio files directly inside it


class BrowseOut(BaseModel):
    path: str
    name: str
    breadcrumbs: list[Crumb]
    folders: list[FolderOut]
    skipped: int = 0  # items whose names aren't valid UTF-8
    tracks: list[TrackOut]


class ClauseOut(BaseModel):
    key: str
    label: str
    values: list[str]


class SearchInfo(BaseModel):
    query: str
    words: list[str]
    clauses: list[ClauseOut]
    total: int  # all matches; ``tracks`` holds the first ``limit``
    indexing: bool  # the first scan of the library is still running
    indexed: int  # files in the index so far


class SearchOut(BrowseOut):
    search: SearchInfo


MAX_PATHS_PER_REQUEST = 1000  # the UI sends bigger jobs in batches


def _unique(paths: list[str]) -> list[str]:
    """Drop repeated paths (keeping order), so a file is never processed twice."""
    return list(dict.fromkeys(paths))


class UpdateIn(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=MAX_PATHS_PER_REQUEST)
    # Tag name -> new value(s). null, "" or [] removes the tag.
    changes: dict[str, TagValueIn]


class UpdateResult(BaseModel):
    path: str
    ok: bool
    error: str | None = None
    track: TrackOut | None = None


class LoadoutOut(BaseModel):
    name: str
    slug: str
    description: str
    tags: dict[str, list[str]]


class LoadoutIn(BaseModel):
    name: str
    description: str = ""
    tags: dict[str, str | list[str]] = {}
    # When editing, the loadout's name before the edit (handles renames).
    previous_name: str | None = None


class ApplyIn(BaseModel):
    name: str
    paths: list[str] = Field(default=[], max_length=MAX_PATHS_PER_REQUEST)  # apply to these files...
    folder: str | None = None  # ...or to every audio file in this folder
    recursive: bool = False
    mode: Literal["fill", "overwrite"] = "fill"
    dry_run: bool = True  # preview by default; send false to actually write


class ApplyResultOut(BaseModel):
    path: str
    applied: dict[str, list[str]]
    kept_existing: list[str]
    unsupported: list[str]
    error: str | None = None


# --- App ----------------------------------------------------------------------------


def create_app(settings: Settings | None = None, fetch_release: Fetcher = fetch_latest_release,
               fetch_json=None) -> FastAPI:
    settings = settings or Settings.from_env()
    updates = UpdateChecker(VERSION, settings.update_repo, settings.update_check, fetch_release)
    library = Library(settings.music_dir)
    store = LoadoutStore(settings.config_dir / "loadouts")
    engine = MetadataEngine()
    activity = ActivityLog(settings.config_dir / "activity.jsonl")
    art_store = ArtStore(settings.config_dir / "undo-art")
    avatars = AvatarStore(settings.config_dir / "avatars")
    accounts = AccountStore(settings.config_dir / "auth.json", settings.username, settings.password)
    sessions = SessionStore(settings.config_dir / "sessions.json")
    limiter = LoginRateLimiter()
    user_agent = f"Codetta/{VERSION} (https://github.com/gavndev/codetta)"
    lrclib = LRCLib(fetch_json or (lambda url: http_get_json(url, user_agent)))

    def describe(path: Path, rel: str) -> dict:  # what the search index stores per file
        return to_out(rel, engine.load_metadata(path)).model_dump()

    lib_index = LibraryIndex(settings.music_dir, settings.config_dir / "library-index.sqlite3", describe)
    if not settings.auth:
        log.warning("Sign-in is turned OFF (CODETTA_AUTH=off). Anyone who can reach Codetta can edit your music.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # On startup (not on import), add the starter loadouts if missing.
        try:
            store.install_defaults()
        except OSError:
            pass  # read-only config folder: loadouts just won't be saved
        # Drop saved album art that no remembered change refers to any more.
        try:
            art_store.prune(h for rec in activity.undo_records() for h in art_hashes(rec))
        except OSError:
            pass
        lib_index.start()  # builds/refreshes the search index in the background
        yield
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
    app.add_exception_handler(LoadoutNotFoundError, _error(404))
    app.add_exception_handler(LoadoutError, _error(422))

    # --- Sign-in --------------------------------------------------------------------------

    # Everything needs a signed-in session except the page shell, its static
    # files, the sign-in endpoints themselves, and the health check.
    PUBLIC_PATHS = {"/", "/api/health"}
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
            # Changes when the profile picture does; None if there isn't one.
            "avatar": avatars.version(user) if user else None,
        }

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
            log.warning("Failed sign-in for %r from %s", body.username, client_key(request))
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

    def track_out(rel: str) -> TrackOut:
        name = rel.rsplit("/", 1)[-1]
        try:
            return to_out(rel, engine.load_metadata(library.resolve(rel)))
        except (MetadataError, OSError) as exc:
            return TrackOut(path=rel, name=name, error=str(exc))

    def result_out(r: FileResult) -> ApplyResultOut:
        return ApplyResultOut(
            path=library.relative(r.path),
            applied=r.applied,
            kept_existing=r.kept_existing,
            unsupported=r.unsupported,
            error=r.error,
        )

    # --- Status & vocabulary ----------------------------------------------------------

    @app.get("/api/update")
    def update_status(force: bool = Query(False, description="Check GitHub now instead of using the cached answer")) -> dict:
        """Installed version and, if enabled, the latest release on GitHub."""
        return updates.status(force=force)

    @app.get("/api/status")
    def status() -> dict:
        return {
            "version": VERSION,
            "music_dir": str(library.root),
            "music_dir_found": library.exists(),
            "music_dir_writable": library.exists() and os.access(library.root, os.W_OK),
            "lyrics_lookup": settings.lyrics_lookup,
        }

    @app.get("/api/fields")
    def fields() -> dict:
        """The editor's known tags (in display order) and loadout placeholders."""
        return {
            "fields": [
                {"key": f.key, "label": f.label, "group": f.group, "multi": f.multi}
                for f in FIELDS
            ],
            "placeholders": sorted(PLACEHOLDERS),
        }

    # --- Library ---------------------------------------------------------------------

    @app.get("/api/browse", response_model=BrowseOut)
    def browse(path: str = Query("", description="Folder, relative to the music folder")):
        """One folder: its subfolders and the tags of its audio files."""
        require_library()
        listing = library.list_folder(path)
        crumbs = [Crumb(name="Library", path="")]
        parts = listing.path.split("/") if listing.path else []
        for i, part in enumerate(parts):
            crumbs.append(Crumb(name=part, path="/".join(parts[: i + 1])))
        return BrowseOut(
            path=listing.path,
            name=crumbs[-1].name,
            breadcrumbs=crumbs,
            folders=[folder_out(f) for f in listing.folders],
            skipped=listing.skipped,
            tracks=[track_out(f) for f in listing.files],
        )

    @app.get("/api/track", response_model=TrackOut)
    def get_track(path: str = Query(..., description="File, relative to the music folder")):
        require_library()
        return to_out(path, engine.load_metadata(library.resolve(path)))

    @app.get("/api/lyrics/lookup")
    def lyrics_lookup(path: str = Query(..., description="File, relative to the music folder")) -> dict:
        """Look up lyrics for a track on LRCLIB (sends artist, title, album and length only).
        Returns a suggestion; nothing is written."""
        if not settings.lyrics_lookup:
            raise HTTPException(403, "Lyrics lookup is turned off (CODETTA_LYRICS_LOOKUP=off).")
        require_library()
        meta = engine.load_metadata(library.resolve(path))
        first = lambda key: (meta.tags.get(key) or [""])[0].strip()  # noqa: E731
        artist = first("artist") or first("albumartist")
        title = first("title")
        if not artist or not title:
            raise HTTPException(422, "Add the artist and title first, so the right song can be found.")
        try:
            result = lrclib.lyrics(TrackQuery(artist=artist, title=title, album=first("album"), duration=meta.duration))
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {"found": result is not None, "result": result.to_dict() if result else None}

    @app.get("/api/track/raw")
    def get_track_raw(path: str = Query(..., description="File, relative to the music folder")) -> dict:
        """Advanced mode: every stored field exactly as the file has it (read-only)."""
        require_library()
        return read_raw(engine, library.resolve(path))

    @app.get("/api/search", response_model=SearchOut)
    def search(
        q: str = Query(..., max_length=500, description='e.g. "genre: rap, hip-hop artist: drake" or plain words'),
        limit: int = Query(500, ge=1, le=MAX_PATHS_PER_REQUEST),
    ):
        """Search the whole library by tag. Commas mean "or"; clauses and words must all match."""
        require_library()
        query = parse_query(q, lib_index.has_key)
        tracks, total = lib_index.search(query, limit)
        lib_index.request_rescan()  # pick up music added outside Codetta (in the background)
        status = lib_index.status()
        return SearchOut(
            path="", name="Search", breadcrumbs=[Crumb(name="Library", path="")], folders=[], tracks=tracks,
            search=SearchInfo(
                query=q, words=query.words, total=total, indexing=not status.ready, indexed=status.files,
                clauses=[ClauseOut(key=c.key, label=c.label, values=c.values) for c in query.clauses if c.values],
            ),
        )

    @app.patch("/api/tracks", response_model=list[UpdateResult])
    def update_tracks(body: UpdateIn):
        """Apply the same tag changes to one or more files.

        Each file succeeds or fails on its own; check ``ok`` per result.
        """
        require_library()
        results = []
        before: dict[str, dict[str, list[str]]] = {}  # for the activity log
        for rel in _unique(body.paths):
            try:
                target = library.resolve(rel)
                before[rel] = engine.load_metadata(target).tags
                meta = engine.update_tags(target, body.changes)
                results.append(UpdateResult(path=rel, ok=True, track=to_out(rel, meta)))
            except (MetadataError, LibraryPathError, OSError) as exc:
                results.append(UpdateResult(path=rel, ok=False, error=str(exc)))
        keys = {k.lower() for k in body.changes}
        undo_files = {}
        for r in results:
            if r.ok and r.path in before:
                b = {k: before[r.path].get(k, []) for k in keys}
                a = {k: r.track.tags.get(k, []) for k in keys}
                changed = [k for k in keys if b[k] != a[k]]
                if changed:
                    undo_files[r.path] = {"before": {k: b[k] for k in changed}, "after": {k: a[k] for k in changed}}
        _log_edit(activity, body.changes, results, before,
                  undo={"type": "tags", "files": undo_files} if undo_files else None)
        lib_index.mark_dirty(r.path for r in results if r.ok)
        return results

    # --- Album art ---------------------------------------------------------------------

    @app.get("/api/art", responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}})
    def get_art(path: str = Query(..., description="File, relative to the music folder")):
        """The track's embedded cover image (404 if it has none)."""
        require_library()
        art = engine.read_artwork(library.resolve(path))
        if art is None:
            raise HTTPException(404, "This track has no album art")
        # The type is decided from the image's actual bytes, never from what the
        # file claims ("image/jpeg" holding HTML, "text/html", SVG...). Anything
        # that isn't a real JPEG/PNG/WebP/GIF is sent as a download, so a
        # booby-trapped file can never run a script inside Codetta.
        mime = sniff_image_type(art.data)
        if mime:
            return Response(art.data, media_type=mime, headers={"Cache-Control": "private, max-age=31536000, immutable"})
        return Response(art.data, media_type="application/octet-stream", headers={
            "Content-Disposition": 'attachment; filename="cover.bin"', "Cache-Control": "no-store"})

    @app.put("/api/art", response_model=list[UpdateResult])
    async def set_art(request: Request, path: list[str] = Query(..., description="One or more files")):
        """Embed the request body (a JPEG or PNG image) as album art in each file."""
        require_library()
        if len(path) > MAX_PATHS_PER_REQUEST:
            raise HTTPException(422, f"Too many files in one request (max {MAX_PATHS_PER_REQUEST})")
        image = await request.body()  # size already capped by GuardMiddleware
        return await run_in_threadpool(_change_art, _unique(path), image)

    @app.delete("/api/art", response_model=list[UpdateResult])
    def delete_art(path: list[str] = Query(..., description="One or more files")):
        """Remove all embedded pictures from each file."""
        require_library()
        if len(path) > MAX_PATHS_PER_REQUEST:
            raise HTTPException(422, f"Too many files in one request (max {MAX_PATHS_PER_REQUEST})")
        return _change_art(_unique(path), None)

    def _change_art(paths: list[str], image: bytes | None) -> list[UpdateResult]:
        results, had_art = [], 0
        art = None
        undo_files = {}
        for rel in paths:
            try:
                target = library.resolve(rel)
                old = engine.read_artwork(target)
                had_art += old is not None
                art = engine.update_artwork(target, image)
                # Keep both images so the change can be undone (and redone).
                try:
                    before = art_store.save(old.data if old else None)
                    after = art_store.save(art.data if art else None)
                    if before != after:
                        undo_files[rel] = {"before": before, "after": after}
                except OSError:
                    pass  # couldn't keep a copy: this change just won't be undoable
                results.append(UpdateResult(path=rel, ok=True, track=to_out(rel, engine.load_metadata(target))))
            except (MetadataError, LibraryPathError, OSError) as exc:
                results.append(UpdateResult(path=rel, ok=False, error=str(exc)))
        _log_art(activity, image is not None, art, had_art, results,
                 undo={"type": "art", "files": undo_files} if undo_files else None)
        lib_index.mark_dirty(r.path for r in results if r.ok)
        return results

    @app.post("/api/activity/{entry_id}/undo")
    def undo(entry_id: int) -> dict:
        """Reverse a logged change. Files edited again since are left alone."""
        require_library()
        entry = activity.get(entry_id)
        if entry is None:
            raise HTTPException(404, "That change is no longer in the activity log")
        if not entry.get("undo"):
            raise HTTPException(422, "This change can't be undone")
        if activity.is_undone(entry_id):
            raise HTTPException(409, "This change has already been undone")
        outcome = undo_change(engine, library.resolve, art_store, entry["undo"])
        lib_index.mark_dirty(r.path for r in outcome.results if r.ok)
        done = [r for r in outcome.results if r.ok]
        skipped = [r for r in outcome.results if r.skipped]
        failed = [r for r in outcome.results if not r.ok and not r.skipped]
        n = len(outcome.results)
        # Name the original change, however many times it's been undone/redone.
        what = entry.get("root_message") or entry["message"]
        redo = entry.get("kind") == "undo" and not entry.get("redo")
        verb = "Redid" if redo else "Undid"
        if not done:
            message = f"Couldn't {'redo' if redo else 'undo'} “{what}”"
        elif len(done) == n:
            message = f"{verb} “{what}”"
        else:
            message = f"{verb} “{what}” on {len(done)} of {n} files"
        if done:
            activity.add(
                "undo", message, ok=not failed,
                files=[r.path for r in done],
                changes=[{"key": c["key"], "old": c["new"], "new": c["old"]} for c in entry.get("changes", [])
                         if c.get("old") != "various"],
                errors=[{"path": r.path, "error": r.error or ""} for r in skipped + failed],
                undo=outcome.reverse, undoes=entry_id,
                extra={"root_message": what, "redo": redo},
            )
        return {
            "message": message,
            "undone": len(done), "skipped": len(skipped), "failed": len(failed),
            "results": [{"path": r.path, "ok": r.ok, "skipped": r.skipped, "error": r.error} for r in outcome.results],
        }

    # --- Activity -------------------------------------------------------------------------

    @app.get("/api/activity")
    def get_activity(limit: int = Query(50, ge=1, le=500), after_id: int = Query(0, ge=0)) -> list[dict]:
        """Recent changes, newest first. Pass ``after_id`` to get only newer ones."""
        return activity.recent(limit=limit, after_id=after_id)

    # --- Loadouts --------------------------------------------------------------------

    @app.get("/api/loadouts", response_model=list[LoadoutOut])
    def list_loadouts():
        return [_to_loadout_out(lo) for lo in store.list()]

    @app.post("/api/loadouts", response_model=LoadoutOut)
    def save_loadout(body: LoadoutIn):
        """Create a loadout, or edit one (pass ``previous_name`` when editing)."""
        loadout = Loadout(name=body.name, tags=body.tags, description=body.description)
        editing = body.previous_name is not None
        renamed = editing and slugify(body.previous_name) != loadout.slug
        if (not editing or renamed) and _exists(store, loadout.name):
            raise HTTPException(409, f"A loadout named '{loadout.name}' already exists")
        try:
            store.save(loadout)
        except OSError as exc:
            raise HTTPException(500, f"Could not save loadout: {exc}") from exc
        if renamed and _exists(store, body.previous_name):
            store.delete(body.previous_name)
        return _to_loadout_out(loadout)

    @app.delete("/api/loadouts/{name}", status_code=204)
    def delete_loadout(name: str):
        store.delete(name)

    @app.post("/api/loadouts/apply", response_model=list[ApplyResultOut])
    def apply(body: ApplyIn):
        """Apply a loadout to files or a folder. ``dry_run`` (default) only previews."""
        require_library()
        loadout = store.get(body.name)
        if body.folder is not None:
            results = apply_loadout_to_folder(
                engine,
                loadout,
                library.resolve(body.folder),
                mode=body.mode,
                recursive=body.recursive,
                dry_run=body.dry_run,
            )
        elif body.paths:
            paths = [library.resolve(p) for p in _unique(body.paths)]
            results = apply_loadout(engine, loadout, paths, mode=body.mode, dry_run=body.dry_run)
        else:
            raise HTTPException(400, "Choose some files or a folder to apply the loadout to")
        out = [result_out(r) for r in results]
        if not body.dry_run:
            undo_files = {
                library.relative(r.path): {"before": r.previous, "after": r.applied}
                for r in results if not r.error and r.applied
            }
            _log_loadout(activity, loadout.name, body.mode, out,
                         undo={"type": "tags", "files": undo_files} if undo_files else None)
            lib_index.mark_dirty(o.path for o in out if not o.error and o.applied)
        return out

    # --- UI ------------------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    # Size limits, cross-site protection and security headers (see web/security.py).
    # Added last so it wraps everything, including the sign-in check's 401s.
    app.add_middleware(GuardMiddleware, allowed_hosts=set(settings.allowed_hosts))
    return app


def _is_public_address(host: str) -> bool:
    """True for internet addresses. Home networks, Tailscale (100.64.0.0/10 and
    fd7a:115c:a1e0::/48), loopback and link-local are not public."""
    import ipaddress

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # e.g. "testclient" or a Unix socket: not an internet peer
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


def _to_track_out(rel: str, meta: TrackMetadata, mtime: int | None = None) -> TrackOut:
    return TrackOut(
        path=rel,
        name=rel.rsplit("/", 1)[-1],
        format=meta.format,
        tags=meta.tags,
        duration=meta.duration,
        bitrate=meta.bitrate,
        sample_rate=meta.sample_rate,
        channels=meta.channels,
        mtime=mtime,
    )


def _to_loadout_out(lo: Loadout) -> LoadoutOut:
    return LoadoutOut(name=lo.name, slug=lo.slug, description=lo.description, tags=lo.tags)


def _exists(store: LoadoutStore, name: str) -> bool:
    try:
        store.get(name)
        return True
    except LoadoutNotFoundError:
        return False
    except LoadoutError:
        return True  # a file exists under that name, even if it's broken


app = create_app()


# --- Activity log messages ------------------------------------------------------------


def _name(rel: str) -> str:
    return rel.rsplit("/", 1)[-1]


ACTIVITY_VALUE_CHARS = 160  # long values (lyrics) are shortened in the log; undo keeps the full text


def _join(values: list[str]) -> str:
    text = " ".join("; ".join(values).split())  # one line
    return text if len(text) <= ACTIVITY_VALUE_CHARS else text[: ACTIVITY_VALUE_CHARS - 1].rstrip() + "…"


def _log_edit(activity: ActivityLog, changes: dict, results: list[UpdateResult], before: dict, undo: dict | None = None) -> None:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    keys = list(changes)
    diff = []
    for key in keys:
        olds = {_join(before[r.path].get(key, [])) for r in ok if r.path in before}
        new = _join(ok[0].track.tags.get(key, [])) if ok else ""
        old = olds.pop() if len(olds) == 1 else ("various" if olds else "")
        diff.append({"key": key, "old": old, "new": new})
    field_list = ", ".join(keys[:4]) + (f" +{len(keys) - 4} more" if len(keys) > 4 else "")
    target = _name(results[0].path) if len(results) == 1 else f"{len(results)} tracks"
    if not failed:
        message = f"Edited {field_list} on {target}"
    elif not ok:
        message = f"Couldn't edit {target}"
    else:
        message = f"Edited {field_list} on {len(ok)} of {len(results)} tracks"
    activity.add(
        "edit", message, ok=not failed,
        files=[r.path for r in results], changes=diff if ok else [],
        errors=[{"path": r.path, "error": r.error or ""} for r in failed],
        undo=undo,
    )


def _log_art(activity: ActivityLog, adding: bool, art, had_art: int, results: list[UpdateResult], undo: dict | None = None) -> None:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    target = _name(results[0].path) if len(results) == 1 else f"{len(ok)} tracks"
    if adding:
        verb = "Replaced" if had_art else "Added"
        detail = ""
        if art is not None:
            size = f"{art.width}×{art.height} " if art.width and art.height else ""
            detail = f" ({size}{art.mime.split('/')[-1].upper()}, {max(1, len(art.data) // 1024)} KB)"
        message = f"{verb} album art on {target}{detail}" if ok else f"Couldn't set album art on {_name(results[0].path) if len(results) == 1 else f'{len(results)} tracks'}"
    else:
        message = f"Removed album art from {target}" if ok else "Couldn't remove album art"
    activity.add(
        "art", message, ok=not failed,
        files=[r.path for r in results],
        errors=[{"path": r.path, "error": r.error or ""} for r in failed],
        undo=undo,
    )


def _log_loadout(activity: ActivityLog, name: str, mode: str, results: list[ApplyResultOut], undo: dict | None = None) -> None:
    changed = [r for r in results if not r.error and r.applied]
    failed = [r for r in results if r.error]
    keys = sorted({k for r in changed for k in r.applied})
    diff = [{"key": k, "old": "", "new": _join(changed[0].applied[k]) if len(changed) == 1 and k in changed[0].applied else "set"} for k in keys]
    how = "filled empty tags" if mode == "fill" else "overwrote tags"
    message = f"Applied loadout “{name}” to {len(changed)} of {len(results)} files ({how})"
    activity.add(
        "loadout", message, ok=not failed,
        files=[r.path for r in changed], changes=diff,
        errors=[{"path": r.path, "error": r.error or ""} for r in failed],
        undo=undo,
    )
