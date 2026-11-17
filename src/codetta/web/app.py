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
from codetta.core.artwork import MAX_ART_BYTES
from codetta.core.auth import (
    SESSION_DAYS,
    AccountStore,
    AuthError,
    LoginRateLimiter,
    SessionStore,
)
from codetta.core.engine import MetadataEngine, MetadataError, TrackMetadata
from codetta.core.library import Library, LibraryPathError, count_contents
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

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            music_dir=Path(env("MUSIC_DIR", "/music")).expanduser(),
            config_dir=Path(env("CONFIG_DIR", "config")).expanduser(),
            auth=env("AUTH", "on").strip().lower() not in ("off", "false", "0", "no"),
            username=env("USERNAME"),
            password=env("PASSWORD"),
        )


# --- API models -------------------------------------------------------------------


class Credentials(BaseModel):
    username: str = Field(max_length=200)
    password: str = Field(max_length=2000)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=2000)
    new_password: str = Field(max_length=2000)

TagValueIn = str | list[str] | None


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
    error: str | None = None  # set if the file couldn't be read


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
    tracks: list[TrackOut]


class UpdateIn(BaseModel):
    paths: list[str] = Field(min_length=1)
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
    paths: list[str] = []  # apply to these files...
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    library = Library(settings.music_dir)
    store = LoadoutStore(settings.config_dir / "loadouts")
    engine = MetadataEngine()
    activity = ActivityLog(settings.config_dir / "activity.jsonl")
    accounts = AccountStore(settings.config_dir / "auth.json", settings.username, settings.password)
    sessions = SessionStore(settings.config_dir / "sessions.json")
    limiter = LoginRateLimiter()
    if not settings.auth:
        log.warning("Sign-in is turned OFF (CODETTA_AUTH=off). Anyone who can reach Codetta can edit your music.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # On startup (not on import), add the starter loadouts if missing.
        try:
            store.install_defaults()
        except OSError:
            pass  # read-only config folder: loadouts just won't be saved
        yield

    app = FastAPI(
        title="Codetta", version=VERSION, docs_url="/docs", redoc_url=None, lifespan=lifespan
    )

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
            "auth_enabled": settings.auth,
            "setup_required": settings.auth and accounts.setup_required,
            "signed_in": (not settings.auth) or user is not None,
            "username": user,
            "managed_by_env": accounts.managed_by_env,
        }

    @app.post("/api/auth/setup")
    def auth_setup(body: Credentials, request: Request, response: Response) -> dict:
        """First run only: create the account and sign in."""
        if not settings.auth:
            raise HTTPException(400, "Sign-in is turned off")
        if not accounts.setup_required:
            raise HTTPException(409, "Codetta is already set up. Sign in instead.")
        try:
            account = accounts.create(body.username, body.password)
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
        account = accounts.check(body.username, body.password)
        if account is None:
            limiter.failed(client_key(request))
            log.warning("Failed sign-in for %r from %s", body.username, client_key(request))
            raise HTTPException(401, "Wrong username or password")
        limiter.succeeded(client_key(request))
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
        if accounts.check(user, body.current_password) is None:
            limiter.failed(client_key(request))
            raise HTTPException(401, "Your current password is wrong")
        try:
            accounts.set_password(user, body.new_password)
        except AuthError as exc:
            raise HTTPException(422, str(exc)) from exc
        sessions.revoke_all(keep=token)
        log.info("Password changed for %r", user)
        return {"ok": True}

    def require_library() -> None:
        if not library.exists():
            raise HTTPException(
                503,
                f"Music folder not found: {library.root}. "
                "Set CODETTA_MUSIC_DIR (or mount your music at /music in Docker).",
            )

    def to_out(rel: str, meta: TrackMetadata) -> TrackOut:
        try:
            mtime = library.resolve(rel).stat().st_mtime_ns
        except OSError:
            mtime = None
        return _to_track_out(rel, meta, mtime)

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

    @app.get("/api/status")
    def status() -> dict:
        return {
            "version": VERSION,
            "music_dir": str(library.root),
            "music_dir_found": library.exists(),
            "music_dir_writable": library.exists() and os.access(library.root, os.W_OK),
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
            tracks=[track_out(f) for f in listing.files],
        )

    @app.get("/api/track", response_model=TrackOut)
    def get_track(path: str = Query(..., description="File, relative to the music folder")):
        require_library()
        return to_out(path, engine.load_metadata(library.resolve(path)))

    @app.patch("/api/tracks", response_model=list[UpdateResult])
    def update_tracks(body: UpdateIn):
        """Apply the same tag changes to one or more files.

        Each file succeeds or fails on its own; check ``ok`` per result.
        """
        require_library()
        results = []
        before: dict[str, dict[str, list[str]]] = {}  # for the activity log
        for rel in body.paths:
            try:
                target = library.resolve(rel)
                before[rel] = engine.load_metadata(target).tags
                meta = engine.update_tags(target, body.changes)
                results.append(UpdateResult(path=rel, ok=True, track=to_out(rel, meta)))
            except (MetadataError, LibraryPathError, OSError) as exc:
                results.append(UpdateResult(path=rel, ok=False, error=str(exc)))
        _log_edit(activity, body.changes, results, before)
        return results

    # --- Album art ---------------------------------------------------------------------

    @app.get("/api/art", responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}})
    def get_art(path: str = Query(..., description="File, relative to the music folder")):
        """The track's embedded cover image (404 if it has none)."""
        require_library()
        art = engine.read_artwork(library.resolve(path))
        if art is None:
            raise HTTPException(404, "This track has no album art")
        # The UI adds ?v=<mtime> to the URL, so a changed file gets a new URL.
        return Response(art.data, media_type=art.mime, headers={"Cache-Control": "private, max-age=86400"})

    @app.put("/api/art", response_model=list[UpdateResult])
    async def set_art(request: Request, path: list[str] = Query(..., description="One or more files")):
        """Embed the request body (a JPEG or PNG image) as album art in each file."""
        require_library()
        length = int(request.headers.get("content-length") or 0)
        if length > MAX_ART_BYTES:
            raise HTTPException(413, f"The image is too large (max {MAX_ART_BYTES // (1024 * 1024)} MB)")
        image = await request.body()
        return await run_in_threadpool(_change_art, path, image)

    @app.delete("/api/art", response_model=list[UpdateResult])
    def delete_art(path: list[str] = Query(..., description="One or more files")):
        """Remove all embedded pictures from each file."""
        require_library()
        return _change_art(path, None)

    def _change_art(paths: list[str], image: bytes | None) -> list[UpdateResult]:
        results, had_art = [], 0
        art = None
        for rel in paths:
            try:
                target = library.resolve(rel)
                had_art += engine.read_artwork(target) is not None
                art = engine.update_artwork(target, image)
                results.append(UpdateResult(path=rel, ok=True, track=to_out(rel, engine.load_metadata(target))))
            except (MetadataError, LibraryPathError, OSError) as exc:
                results.append(UpdateResult(path=rel, ok=False, error=str(exc)))
        _log_art(activity, image is not None, art, had_art, results)
        return results

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
            paths = [library.resolve(p) for p in body.paths]
            results = apply_loadout(engine, loadout, paths, mode=body.mode, dry_run=body.dry_run)
        else:
            raise HTTPException(400, "Choose some files or a folder to apply the loadout to")
        out = [result_out(r) for r in results]
        if not body.dry_run:
            _log_loadout(activity, loadout.name, body.mode, out)
        return out

    # --- UI ------------------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


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


def _join(values: list[str]) -> str:
    return "; ".join(values)


def _log_edit(activity: ActivityLog, changes: dict, results: list[UpdateResult], before: dict) -> None:
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
    )


def _log_art(activity: ActivityLog, adding: bool, art, had_art: int, results: list[UpdateResult]) -> None:
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
    )


def _log_loadout(activity: ActivityLog, name: str, mode: str, results: list[ApplyResultOut]) -> None:
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
    )
