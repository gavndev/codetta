"""Coda's web app: a JSON API plus the single-page UI.

Run locally:
    CODA_MUSIC_DIR=~/Music uvicorn coda.web.app:app --reload --port 8111

Settings (environment variables):
    CODA_MUSIC_DIR   the music library to edit (default: /music)
    CODA_CONFIG_DIR  where loadouts are stored (default: ./config)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from coda.core.engine import MetadataEngine, MetadataError, TrackMetadata
from coda.core.library import Library, LibraryPathError
from coda.core.presets import (
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
from coda.core.tagmap import FIELDS

STATIC_DIR = Path(__file__).parent / "static"

try:
    VERSION = version("coda")
except PackageNotFoundError:  # running from a source checkout without install
    VERSION = "dev"


@dataclass
class Settings:
    music_dir: Path
    config_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            music_dir=Path(os.environ.get("CODA_MUSIC_DIR", "/music")).expanduser(),
            config_dir=Path(os.environ.get("CODA_CONFIG_DIR", "config")).expanduser(),
        )


# --- API models -------------------------------------------------------------------

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
    error: str | None = None  # set if the file couldn't be read


class Crumb(BaseModel):
    name: str
    path: str


class BrowseOut(BaseModel):
    path: str
    name: str
    breadcrumbs: list[Crumb]
    folders: list[Crumb]
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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # On startup (not on import), add the starter loadouts if missing.
        try:
            store.install_defaults()
        except OSError:
            pass  # read-only config folder: loadouts just won't be saved
        yield

    app = FastAPI(
        title="Coda", version=VERSION, docs_url="/docs", redoc_url=None, lifespan=lifespan
    )

    # Map Coda's errors to HTTP status codes, with a readable message.
    def _error(status: int):
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc)})

        return handler

    app.add_exception_handler(LibraryPathError, _error(400))
    app.add_exception_handler(FileNotFoundError, _error(404))
    app.add_exception_handler(MetadataError, _error(422))
    app.add_exception_handler(LoadoutNotFoundError, _error(404))
    app.add_exception_handler(LoadoutError, _error(422))

    def require_library() -> None:
        if not library.exists():
            raise HTTPException(
                503,
                f"Music folder not found: {library.root}. "
                "Set CODA_MUSIC_DIR (or mount your music at /music in Docker).",
            )

    def track_out(rel: str) -> TrackOut:
        name = rel.rsplit("/", 1)[-1]
        try:
            return _to_track_out(rel, engine.load_metadata(library.resolve(rel)))
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
            folders=[Crumb(name=f.rsplit("/", 1)[-1], path=f) for f in listing.folders],
            tracks=[track_out(f) for f in listing.files],
        )

    @app.get("/api/track", response_model=TrackOut)
    def get_track(path: str = Query(..., description="File, relative to the music folder")):
        require_library()
        return _to_track_out(path, engine.load_metadata(library.resolve(path)))

    @app.patch("/api/tracks", response_model=list[UpdateResult])
    def update_tracks(body: UpdateIn):
        """Apply the same tag changes to one or more files.

        Each file succeeds or fails on its own; check ``ok`` per result.
        """
        require_library()
        results = []
        for rel in body.paths:
            try:
                meta = engine.update_tags(library.resolve(rel), body.changes)
                results.append(UpdateResult(path=rel, ok=True, track=_to_track_out(rel, meta)))
            except (MetadataError, LibraryPathError, OSError) as exc:
                results.append(UpdateResult(path=rel, ok=False, error=str(exc)))
        return results

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
        return [result_out(r) for r in results]

    # --- UI ------------------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _to_track_out(rel: str, meta: TrackMetadata) -> TrackOut:
    return TrackOut(
        path=rel,
        name=rel.rsplit("/", 1)[-1],
        format=meta.format,
        tags=meta.tags,
        duration=meta.duration,
        bitrate=meta.bitrate,
        sample_rate=meta.sample_rate,
        channels=meta.channels,
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
