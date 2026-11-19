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

import contextlib
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

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
from codetta.core.health import CATEGORIES as HEALTH_CATEGORIES
from codetta.core.health import CHECKS as HEALTH_CHECKS
from codetta.core.health import EDITION_RE, MB_RELEASE_KEYS, HealthStore, folder_has_image
from codetta.core.health import _base_artist as base_artist
from codetta.core.health import fold as health_fold
from codetta.core.health import run as health_run
from codetta.core.describe import describe_file, describe_many
from codetta.core.fileinfo import file_info, folder_info
from codetta.core.logbuffer import shared_buffer
from codetta.core.plugins import ActionError, PluginManager
from codetta.core.index import LibraryIndex, parse_query
from codetta.core import changelog
from codetta.core.notifications import Notifications
from codetta.core.onboarding import OnboardingStore
from codetta.core.inbox import (
    DOWNLOADING,
    ERROR as INBOX_ERROR,
    FILED,
    LOCAL,
    MATCHING,
    NO_MATCH,
    READY,
    REVIEW,
    SKIPPED,
    WAITING,
    InboxStore,
)
from codetta.core.inbox import signature as inbox_signature
from codetta.core.library import DELETED
from codetta.core.library import INBOX as INBOX_ALIAS
from codetta.core.library import Library, LibraryPathError, TooManyFilesError, audio_files, count_contents
from codetta.core.organize import (
    DEFAULT_PATTERN,
    PRESETS as ORGANIZE_PRESETS,
    SIDECAR_SUFFIXES,
    Move,
    PatternError,
    Source,
    apply_moves,
    check_pattern,
    remove_empty_dirs,
    load_pattern,
    plan_moves,
    prune_replaced,
    render,
    safe_name,
    save_pattern,
)
from codetta.core.acoustid import DEFAULT_KEY as ACOUSTID_KEY
from codetta.core.acoustid import LOOKUP_URL as ACOUSTID_URL
from codetta.core.acoustid import AcoustID, Fingerprinter, FingerprintError, find_fpcalc, rank_releases
from codetta.core.artwork import MAX_ART_BYTES
from codetta.core.connections import BY_ID as CONNECTION_BY_ID
from codetta.core.connections import ConnectionStore, parse_switch
from codetta.core.musicbrainz import (
    ALL_FIELDS as MB_FIELDS,
    FIELD_GROUPS as MB_FIELD_GROUPS,
    ID_LABELS as MB_ID_LABELS,
    MAX_MB_BYTES,
    MB_BASE,
    MB_TIMEOUT,
    MBID_RE,
    DEFAULT_OFF as MB_DEFAULT_OFF,
    FileInfo,
    MusicBrainz,
    album_tags,
    cover_url,
    default_fields as mb_default_fields,
    number,
    pair_files,
    parse_release_id,
    release_tracks,
    score_candidate,
    summarize,
    track_tags,
    artist_links,
    artist_summary,
    group_summary,
    pick_release,
    tracklist,
)
from codetta.core.providers import LRCLib, ProviderError, TrackQuery, http_get, http_get_json, http_post_json
from codetta.core.rawtags import read_raw
from codetta.core.slskd import (
    ARRIVED as SK_ARRIVED,
    CANCELLED as SK_CANCELLED,
    DOWNLOADING as SK_DOWNLOADING,
    FAILED as SK_FAILED,
    IMPORTED as SK_IMPORTED,
    NOTHING as SK_NOTHING,
    SlskdError,
    Soulseek,
    SoulseekStore,
    basenames as sk_basenames,
    check as slskd_check,
    clean_url as slskd_clean_url,
    folder_progress,
    http_request as slskd_http_request,
)
from codetta.core.presets import (
    PLACEHOLDERS,
    FileResult,
    Preset,
    PresetError,
    PresetNotFoundError,
    PresetStore,
    apply_preset,
    apply_preset_to_folder,
    slugify,
)
from codetta.core.tagmap import FIELDS, is_tag_supported, native_names
from codetta.core.undo import ArtStore, art_hashes, sha256, undo_change
from codetta.core.updates import DEFAULT_REPO, Fetcher, UpdateChecker, fetch_latest_release
from codetta.web.security import GuardMiddleware, SelectiveGZip

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
    # Connections: None = the user decides in the app (off until they opt in);
    # True/False = set by the environment, and the app's switch is locked.
    offline: bool = False  # CODETTA_OFFLINE: blocks every connection
    update_check: bool | None = None
    lyrics_lookup: bool | None = None  # "Find lyrics" (asks LRCLIB only when pressed)
    musicbrainz: bool | None = None  # "Match on MusicBrainz" + Cover Art Archive
    musicbrainz_url: str | None = None  # self-hosted mirror instead of musicbrainz.org
    acoustid: bool | None = None  # "Identify by sound" (fingerprints looked up on AcoustID)
    acoustid_key: str | None = None  # an own application key instead of Codetta's
    fpcalc: str | None = None  # Chromaprint's fpcalc; None = look on PATH
    slskd: bool | None = None  # Soulseek through the user's slskd
    slskd_url: str | None = None  # CODETTA_SLSKD_URL / _API_KEY: set (and lock) the connection details
    slskd_api_key: str | None = None
    inbox_dir: Path | None = None  # a downloads folder outside the library (e.g. slskd's), used as "@inbox"
    inbox_settle_seconds: float = 120  # wait this long after a file changes (downloads still arriving)
    slskd_poll_seconds: float = 4  # how often a Soulseek request under way is checked on
    index_workers: int = 0  # processes that help a big index scan (0: one fewer than the CPUs, up to 4)
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
            offline=parse_switch(env("OFFLINE")) is True,
            update_check=parse_switch(env("UPDATE_CHECK")),
            lyrics_lookup=parse_switch(env("LYRICS_LOOKUP")),
            musicbrainz=parse_switch(env("MUSICBRAINZ")),
            musicbrainz_url=(env("MUSICBRAINZ_URL") or "").strip() or None,
            acoustid=parse_switch(env("ACOUSTID")),
            acoustid_key=(env("ACOUSTID_KEY") or "").strip() or None,
            fpcalc=(env("FPCALC") or "").strip() or None,
            index_workers=int(env("INDEX_WORKERS") or 0) if (env("INDEX_WORKERS") or "0").isdigit() else 0,
            slskd=parse_switch(env("SLSKD")),
            slskd_url=(env("SLSKD_URL") or "").strip() or None,
            slskd_api_key=(env("SLSKD_API_KEY") or "").strip() or None,
            inbox_dir=Path(env("INBOX_DIR")).expanduser() if env("INBOX_DIR") else None,
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
MAX_PATH_CHARS = 4096  # longer than any real path (Linux allows 4096 bytes)


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
# Audio types for the in-browser player, by extension (only Codetta's audio files are served).
STREAM_TYPES = {
    ".flac": "audio/flac", ".mp3": "audio/mpeg", ".mp2": "audio/mpeg", ".m4a": "audio/mp4", ".m4b": "audio/mp4",
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg", ".spx": "audio/ogg", ".wav": "audio/wav",
    ".aif": "audio/aiff", ".aiff": "audio/aiff", ".aifc": "audio/aiff", ".wma": "audio/x-ms-wma",
    ".wv": "audio/x-wavpack", ".dsf": "audio/x-dsf", ".tta": "audio/x-tta",
}
MAX_IDENTIFY = 200
MAX_ORGANIZE = 5000  # files planned/moved in one request  # files fingerprinted in one request (each takes a moment to decode)


def _unique(paths: list[str]) -> list[str]:
    """Drop repeated paths (keeping order), so a file is never processed twice."""
    return list(dict.fromkeys(paths))


class FolderCoversIn(BaseModel):
    paths: list[Annotated[str, Field(max_length=MAX_PATH_CHARS)]] = Field(max_length=200)


class UpdateIn(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=MAX_PATHS_PER_REQUEST)
    # Tag name -> new value(s). null, "" or [] removes the tag.
    changes: dict[str, TagValueIn] = Field(max_length=200)


class UpdateResult(BaseModel):
    path: str
    ok: bool
    error: str | None = None
    track: TrackOut | None = None


class PresetOut(BaseModel):
    name: str
    slug: str
    description: str
    tags: dict[str, list[str]]


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field("", max_length=1000)
    tags: dict[str, str | list[str]] = Field(default={}, max_length=200)
    # When editing, the preset's name before the edit (handles renames).
    previous_name: str | None = Field(default=None, max_length=100)


class ApplyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    paths: list[str] = Field(default=[], max_length=MAX_PATHS_PER_REQUEST)  # apply to these files...
    folder: str | None = Field(default=None, max_length=MAX_PATH_CHARS)  # ...or to every audio file in this folder
    recursive: bool = False
    mode: Literal["fill", "overwrite"] = "fill"
    dry_run: bool = True  # preview by default; send false to actually write


class ApplyResultOut(BaseModel):
    path: str
    applied: dict[str, list[str]]
    kept_existing: list[str]
    unsupported: list[str]
    error: str | None = None


class OrganizeIn(BaseModel):
    paths: list[str] = Field(default=[], max_length=MAX_PATHS_PER_REQUEST)  # these files...
    folder: str | None = Field(default=None, max_length=MAX_PATH_CHARS)  # ...or the audio files in this folder
    recursive: bool = False  # ...and its subfolders
    pattern: str | None = Field(default=None, max_length=400)  # None: the saved pattern


class InboxSettingsIn(BaseModel):
    folder: str = Field(max_length=1000)
    auto: bool = False
    organize: bool = True
    watch: bool = False


class NotificationsReadIn(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=500)  # None: all


class InboxActionIn(BaseModel):
    key: str = Field(max_length=2000)
    release: str | None = Field(default=None, max_length=500)  # file with this release instead of the found one
    recordings: dict[str, list[str]] = Field(default={}, max_length=MAX_PATHS_PER_REQUEST)


class SlskdSettingsIn(BaseModel):
    url: str = Field("", max_length=500)
    api_key: str | None = Field(default=None, max_length=500)  # None: keep the saved key
    review: bool = True
    lossless_only: bool = False
    min_bitrate: int = Field(320, ge=0, le=3000)
    search_seconds: int = Field(20, ge=5, le=120)


class SlskdSearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    upgrade: str = Field("", max_length=2000)  # a library folder this download should replace


class SlskdNextIn(BaseModel):
    block: bool = True  # blocklist the folder that came (else just try the next one)


class SlskdImportIn(BaseModel):
    release: str | None = Field(default=None, max_length=500)  # file with this release instead of the found one
    recordings: dict[str, list[str]] = Field(default={}, max_length=MAX_PATHS_PER_REQUEST)


REPLACE_FIELDS = ("title", "artist", "album", "albumartist", "genre", "composer", "comment", "label", "grouping")


class ReplaceIn(BaseModel):
    paths: list[str] = Field(default=[], max_length=MAX_PATHS_PER_REQUEST)  # these files...
    folder: str | None = Field(default=None, max_length=MAX_PATH_CHARS)  # ...or the audio files in this folder
    find: str = Field(min_length=1, max_length=200)
    replace: str = Field("", max_length=500)
    fields: list[str] | None = Field(default=None, max_length=40)  # None: the usual text fields
    regex: bool = False
    match_case: bool = False
    dry_run: bool = True


class ActionRunIn(BaseModel):
    paths: list[str] = Field(default=[], max_length=MAX_PATHS_PER_REQUEST)  # these files...
    folder: str | None = Field(default=None, max_length=MAX_PATH_CHARS)  # ...or the audio files in this folder
    dry_run: bool = True


class PluginToggleIn(BaseModel):
    enabled: bool


class FilesIn(BaseModel):
    paths: list[Annotated[str, Field(max_length=MAX_PATH_CHARS)]] = Field(min_length=1, max_length=MAX_PATHS_PER_REQUEST)


class FilesMoveIn(FilesIn):
    to: str = Field(max_length=MAX_PATH_CHARS)  # a folder in the library ("" = the top)


class FileRenameIn(BaseModel):
    path: str = Field(min_length=1, max_length=MAX_PATH_CHARS)
    name: str = Field(min_length=1, max_length=255)


class FolderRenameIn(BaseModel):
    path: str = Field(min_length=1, max_length=MAX_PATH_CHARS)
    name: str = Field(min_length=1, max_length=255)


class HealthSettingsIn(BaseModel):
    enabled: bool | None = None  # the whole feature; None: leave as is
    disabled: list[str] | None = Field(default=None, max_length=100)  # check ids switched off; None: leave as is


class HealthIssueIn(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{12}$")
    ignore: bool = True


class SlskdPickIn(BaseModel):
    index: int = Field(ge=0, le=100)


class PatternIn(BaseModel):
    pattern: str = Field(max_length=400)


class ConnectionsIn(BaseModel):
    enabled: dict[str, bool] = Field(default={}, max_length=50)  # connection id -> on/off


class MBTarget(BaseModel):
    paths: list[str] = Field(default=[], max_length=MAX_PATHS_PER_REQUEST)  # these files...
    folder: str | None = Field(default=None, max_length=MAX_PATH_CHARS)  # ...or the audio files directly in this folder (one album)


class MBSearchIn(MBTarget):
    album: str = Field("", max_length=500)
    artist: str = Field("", max_length=500)
    release: str = Field("", max_length=500)  # a release link or ID instead of a search


class MBProposalIn(MBTarget):
    release: str = Field(max_length=500)
    pairs: dict[str, str | None] = Field(default={}, max_length=MAX_PATHS_PER_REQUEST)  # path -> track id (None: skip)
    fields: list[str] | None = Field(default=None, max_length=200)  # None: the default set
    # From Identify by sound: recording IDs heard in each file (pairs files exactly).
    recordings: dict[str, list[str]] = Field(default={}, max_length=MAX_PATHS_PER_REQUEST)
    mode: Literal["overwrite", "fill"] = "overwrite"  # fill: only tags that are empty now
    cover: Literal["missing", "all", "none"] = "missing"


# --- App ----------------------------------------------------------------------------


def _migrate_presets_folder(config_dir: Path) -> None:
    """Tag Presets used to be called Tag Loadouts, kept in config/loadouts/. Move them over once."""
    old, new = config_dir / "loadouts", config_dir / "presets"
    try:
        if old.is_dir() and not new.exists():
            old.rename(new)
            log.info("Moved your Tag Presets from %s to %s", old, new)
    except OSError as exc:  # read-only config folder: presets just start fresh
        log.warning("Couldn't move %s to %s: %s", old, new, exc)


def create_app(settings: Settings | None = None, fetch_release: Fetcher = fetch_latest_release,
               fetch_json=None, fetch_mb=None, fetch_art=None, post_acoustid=None, run_fpcalc=None,
               slskd_request=None) -> FastAPI:
    """``fetch_*`` replace the network in tests: LRCLIB and MusicBrainz take
    (url) -> parsed JSON or None, the Cover Art Archive (url) -> bytes or None,
    AcoustID (form) -> parsed JSON; ``run_fpcalc`` replaces running fpcalc;
    ``slskd_request`` (method, url, headers, body) -> (status, body) stands in for slskd."""
    settings = settings or Settings.from_env()
    if settings.index_workers <= 0:
        settings.index_workers = max(1, min(4, (os.cpu_count() or 2) - 1))
    connections = ConnectionStore(
        settings.config_dir / "connections.json", offline=settings.offline,
        forced={"updates": settings.update_check, "lyrics": settings.lyrics_lookup, "musicbrainz": settings.musicbrainz,
                "acoustid": settings.acoustid, "slskd": settings.slskd},
    )
    updates = UpdateChecker(VERSION, settings.update_repo, lambda: connections.enabled("updates"), fetch_release)
    library = Library(settings.music_dir, settings.inbox_dir, settings.config_dir / "replaced", settings.config_dir / "deleted")
    _migrate_presets_folder(settings.config_dir)
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
    fpcalc_path = find_fpcalc(settings.fpcalc) or ("fpcalc" if run_fpcalc else None)
    fingerprinter = Fingerprinter(fpcalc_path, **({"run": run_fpcalc} if run_fpcalc else {}))
    acoustid = AcoustID(post_acoustid or (lambda form: http_post_json(ACOUSTID_URL, user_agent, form, service="AcoustID")),
                        key=settings.acoustid_key or ACOUSTID_KEY)
    download_art = fetch_art or (lambda url: http_get(url, user_agent, accept="image/*", max_bytes=MAX_ART_BYTES,
                                                 service="the Cover Art Archive"))

    lib_index = LibraryIndex(settings.music_dir, settings.config_dir / "library-index.sqlite3", describe_file,
                             parallel=describe_many, workers=settings.index_workers)
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
        yield
        inbox_wake.set()
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

    # --- Status & vocabulary ----------------------------------------------------------

    @app.get("/api/update")
    def update_status(force: bool = Query(False, description="Check GitHub now instead of using the cached answer")) -> dict:
        """Installed version and, if enabled, the latest release on GitHub."""
        result = updates.status(force=force)
        if result.get("update_available") and result.get("latest"):
            notices.add("update", f"Codetta {result['latest']} is out",
                      "See what's new and how to update in Account.", {"open": "account"},
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
        where = f"it's turned off by {locked}" if locked else "turn it on in Account → Connections"
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

    # --- Library ---------------------------------------------------------------------

    @app.get("/api/browse", response_model=BrowseOut)
    def browse(path: str = Query("", max_length=MAX_PATH_CHARS, description="Folder, relative to the music folder")):
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
            tracks=tracks_out(listing.files),
        )

    @app.post("/api/folder-covers")
    def folder_covers(body: FolderCoversIn) -> dict:
        """A cover for each folder in the grid: a track inside it with embedded art (from the
        search index, so nothing is read from disk). The page shows it with /api/art."""
        require_library()
        folders = []
        for rel in body.paths:
            try:
                folders.append(library.relative(library.resolve(rel)))  # rejects anything outside the library
            except (LibraryPathError, ValueError):
                continue
        found = lib_index.cover_tracks(f for f in folders if not f.startswith("@"))
        return {"covers": {f: {"path": p, "hash": h} for f, (p, h) in found.items()}}

    @app.get("/api/track", response_model=TrackOut)
    def get_track(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")):
        require_library()
        return to_out(path, engine.load_metadata(library.resolve(path)))

    @app.get("/api/stream", responses={200: {"content": {"audio/*": {}}}, 206: {"description": "Part of the file"}})
    def stream(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")):
        """The audio file itself, for the in-browser player. Supports seeking
        (HTTP range requests); nothing is converted or cached."""
        require_library()
        target = library.resolve(path)
        mime = STREAM_TYPES.get(target.suffix.lower())
        if mime is None or not target.is_file():
            raise HTTPException(404, "No such audio file")
        # The type comes from Codetta's own list (always audio/*), never from the file.
        return FileResponse(target, media_type=mime, content_disposition_type="inline",
                            headers={"Cache-Control": "private, max-age=3600"})

    LRC_LINE = re.compile(r"^\s*\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]")

    @app.get("/api/lyrics")
    def get_lyrics(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")) -> dict:
        """The track's lyrics for the player: the lyrics tag, else a ``.lrc`` file next to it
        (as Navidrome reads them). ``synced`` when it's timed LRC."""
        require_library()
        target = library.resolve(path)
        text, source = "", None
        try:
            text = "\n".join(engine.load_metadata(target).tags.get("lyrics", [])).strip()
            source = "tag" if text else None
        except (MetadataError, OSError):
            pass
        if not text:
            side = target.with_suffix(".lrc")
            try:
                if side.is_file() and side.stat().st_size <= 512 * 1024:
                    text, source = side.read_text("utf-8", errors="replace").strip(), "file"
            except OSError:
                pass
        synced = sum(1 for line in text.splitlines() if LRC_LINE.match(line)) >= 2
        return {"lyrics": text, "source": source, "synced": synced}

    @app.get("/api/lyrics/lookup")
    def lyrics_lookup(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")) -> dict:
        """Look up lyrics for a track on LRCLIB (sends artist, title, album and length only).
        Returns a suggestion; nothing is written."""
        require_connection("lyrics")
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

    # --- MusicBrainz ---------------------------------------------------------------------

    def mb_targets(body: MBTarget) -> list[str]:
        if body.folder is not None:
            rels = library.list_folder(body.folder).files
        else:
            rels = _unique(body.paths)
        if not rels:
            raise HTTPException(400, "Choose an album folder or some tracks first.")
        if len(rels) > MAX_PATHS_PER_REQUEST:
            raise HTTPException(422, f"Too many files for one album (max {MAX_PATHS_PER_REQUEST}).")
        return rels

    def mb_read(rels: list[str]) -> tuple[list[FileInfo], dict[str, TrackMetadata], dict[str, str]]:
        infos, metas, errors = [], {}, {}
        for rel in rels:
            try:
                meta = engine.load_metadata(library.resolve(rel))
            except (MetadataError, LibraryPathError, OSError) as exc:
                errors[rel] = str(exc)
                continue
            metas[rel] = meta
            one = lambda key: (meta.tags.get(key) or [""])[0].strip()  # noqa: E731
            infos.append(FileInfo(
                path=rel, title=one("title"), artist=one("artist"), album=one("album"),
                albumartist=one("albumartist"), tracknumber=number(one("tracknumber")),
                discnumber=number(one("discnumber")), duration=meta.duration, albumid=one("musicbrainz_albumid").lower(),
            ))
        return infos, metas, errors

    def most_common(values) -> str:
        counts: dict[str, int] = {}
        for v in values:
            if v:
                counts[v] = counts.get(v, 0) + 1
        return max(counts, key=counts.get) if counts else ""

    def mb_release_id(text: str) -> str:
        mbid = parse_release_id(text)
        if not mbid:
            raise HTTPException(422, "Paste a MusicBrainz release link (musicbrainz.org/release/…) or its ID.")
        return mbid

    @app.post("/api/musicbrainz/search")
    def mb_search(body: MBSearchIn) -> dict:
        """Find releases that could be this album. Sends only the album/artist
        names (or the release ID you pasted) to MusicBrainz."""
        require_connection("musicbrainz")
        require_library()
        rels = mb_targets(body)
        infos, _, _ = mb_read(rels)
        album = body.album.strip() or most_common(f.album for f in infos)
        artist = body.artist.strip() or most_common(f.albumartist or f.artist for f in infos)
        current = most_common(f.albumid for f in infos if MBID_RE.match(f.albumid))
        try:
            if body.release.strip():
                found = [mb.release(mb_release_id(body.release))]
            else:
                found = mb.search(album, artist) if (album or artist) else []
                if current and not body.album.strip() and not body.artist.strip() and all(r.get("id") != current for r in found):
                    try:  # already tagged with a release: offer it first
                        found.insert(0, mb.release(current))
                    except ProviderError:
                        pass
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        candidates = []
        for r in found:
            c = summarize(r)
            c["score"] = score_candidate(c, infos, album, artist)
            c["current"] = c["id"] == current
            candidates.append(c)
        if not body.release.strip():
            candidates.sort(key=lambda c: (not c["current"], -c["score"]))
        return {"query": {"album": album, "artist": artist, "files": len(rels)}, "current": current or None,
                "candidates": candidates}

    @app.post("/api/musicbrainz/identify")
    def mb_identify(body: MBTarget) -> dict:
        """Recognise the files by their sound: fingerprint them here, ask AcoustID
        which recordings they are, and offer the releases holding most of them."""
        require_connection("musicbrainz")
        require_connection("acoustid")
        require_library()
        if not fingerprinter.available:
            raise HTTPException(503, "The fingerprint tool (fpcalc) isn't installed on this server. "
                                     "It's included in the Docker image; elsewhere install Chromaprint.")
        rels = mb_targets(body)
        if len(rels) > MAX_IDENTIFY:
            raise HTTPException(422, f"Identify by sound works on up to {MAX_IDENTIFY} tracks at a time "
                                     "(one album). Select fewer tracks.")
        infos, _, read_errors = mb_read(rels)
        readable = [f.path for f in infos]
        prints = fingerprinter.many([library.resolve(r) for r in readable])
        ok = [(rel, fp) for rel, fp in zip(readable, prints) if not isinstance(fp, FingerprintError)]
        try:
            found = acoustid.lookup([fp for _, fp in ok]) if ok else []
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        heard = {rel: recs for (rel, _), recs in zip(ok, found)}
        files = []
        for rel in rels:
            if rel in read_errors:
                files.append({"path": rel, "status": "error", "error": read_errors[rel]})
                continue
            fp = prints[readable.index(rel)]
            if isinstance(fp, FingerprintError):
                files.append({"path": rel, "status": "error", "error": str(fp)})
            elif heard.get(rel):
                top = heard[rel][0]
                files.append({"path": rel, "status": "identified", "recording": {
                    "id": top.id, "title": top.title, "artist": top.artist, "score": round(top.score * 100)}})
            else:
                files.append({"path": rel, "status": "unknown"})
        ranked = rank_releases(heard, limit=25)
        try:
            found_releases = mb.releases_by_id([rid for rid, _ in ranked]) if ranked else []
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        covered = dict(ranked)
        n = len(rels)
        candidates = []
        for r in found_releases:
            c = summarize(r)
            tracks = c.get("track_count") or 0
            fit = 1.0 if tracks == n else max(0.0, 1 - abs(tracks - n) / max(n, tracks or 1) * 2)
            c["heard"] = covered.get(c["id"], 0)
            c["score"] = round(100 * (0.75 * c["heard"] / max(1, n) + 0.25 * fit))
            c["current"] = False
            candidates.append(c)
        candidates.sort(key=lambda c: -c["score"])
        identified = sum(f["status"] == "identified" for f in files)
        return {
            "query": {"album": "", "artist": "", "files": n},
            "identified": identified, "total": n,
            "files": files,
            "recordings": {rel: [r.id for r in recs[:20]] for rel, recs in heard.items() if recs},
            "candidates": candidates[:15],
        }

    def mb_proposal(body: MBProposalIn) -> tuple[dict, dict]:
        """What applying this release would change, per file. Returns (proposal, release)."""
        require_connection("musicbrainz")
        require_library()
        rels = mb_targets(body)
        mbid = mb_release_id(body.release)
        try:
            release = mb.release(mbid)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        tracks = release_tracks(release)
        if not tracks:
            raise HTTPException(422, "This release has no track list on MusicBrainz yet.")
        infos, metas, errors = mb_read(rels)
        heard = {p: [r for r in ids[:20] if MBID_RE.match(r)] for p, ids in body.recordings.items() if p in metas}
        pairs = pair_files(infos, tracks, {p: t for p, t in body.pairs.items() if p in metas}, heard)
        album = album_tags(release)
        wanted = set(mb_default_fields() if body.fields is None else body.fields) & set(MB_FIELDS)
        summary = summarize(release)
        files = []
        for rel in rels:
            if rel in errors:
                files.append({"path": rel, "error": errors[rel], "track": None, "changes": {}})
                continue
            meta, pairing = metas[rel], pairs[rel]
            changes, unsupported = {}, []
            if pairing.track:
                for key, new in track_tags(release, pairing.track, album).items():
                    if key not in wanted:
                        continue
                    if not is_tag_supported(meta.format or "", key):
                        unsupported.append(key)
                        continue
                    old = meta.tags.get(key, [])
                    if body.mode == "fill" and any(v.strip() for v in old):
                        continue
                    if old != new:
                        changes[key] = {"old": old, "new": new}
            target = library.resolve(rel)
            try:
                mtime = target.stat().st_mtime_ns
            except OSError:
                mtime = None
            has_art = art_info(rel, target, mtime) is not None
            files.append({
                "path": rel, "error": None,
                "track": pairing.track.to_dict() if pairing.track else None,
                "confidence": pairing.confidence, "notes": pairing.notes,
                "duration": meta.duration, "title": (meta.tags.get("title") or [""])[0],
                "changes": changes, "unsupported": unsupported, "has_art": has_art,
                "cover": bool(pairing.track) and summary["has_cover"] is not False
                         and (body.cover == "all" or (body.cover == "missing" and not has_art)),
            })
        labels = {f.key: f.label for f in FIELDS}
        groups = [
            {"id": gid, "label": label, "default": not set(keys) <= MB_DEFAULT_OFF,
             "fields": [{"key": k, "label": labels.get(k) or MB_ID_LABELS.get(k, k)} for k in keys]}
            for gid, label, keys in MB_FIELD_GROUPS
        ]
        return {
            "release": summary,
            "tracks": [t.to_dict() for t in tracks],
            "files": files,
            "groups": groups,
            "fields": sorted(wanted),
            "mode": body.mode, "cover": body.cover,
        }, release

    @app.post("/api/musicbrainz/preview")
    def mb_preview(body: MBProposalIn) -> dict:
        """Pair the files with a release's tracks and show what would change. Writes nothing."""
        return mb_proposal(body)[0]

    cover_cache: OrderedDict[tuple[str, int | None], bytes | None] = OrderedDict()
    cover_lock = threading.Lock()

    def fetch_cover(mbid: str, size: int | None) -> bytes | None:
        key = (mbid, size)
        with cover_lock:
            if key in cover_cache:
                cover_cache.move_to_end(key)
                return cover_cache[key]
        kind = "release"
        if mbid.startswith("rg:"):
            kind, mbid = "release-group", mbid[3:]
        data = download_art(cover_url(mbid, size, kind=kind))
        if data is not None and sniff_image_type(data) not in ("image/jpeg", "image/png"):
            data = None  # only real JPEG/PNG covers are used (and served to the page)
        if size and size <= 500:  # only small thumbnails are kept (the candidate list)
            with cover_lock:
                cover_cache[key] = data
                while len(cover_cache) > 48:
                    cover_cache.popitem(last=False)
        return data

    @app.get("/api/musicbrainz/cover/{mbid}", responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}})
    def mb_cover(mbid: str, size: int = Query(250, description="250 or 500 pixels"),
                 kind: Literal["release", "release-group"] = "release"):
        """A release's (or release group's) front cover from the Cover Art Archive, fetched
        by the server (so the page never loads anything from another site)."""
        require_connection("musicbrainz")
        if not MBID_RE.match(mbid) or size not in (250, 500):
            raise HTTPException(422, "Not a release ID or thumbnail size")
        try:
            data = fetch_cover(("rg:" if kind == "release-group" else "") + mbid, size)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        if data is None:
            raise HTTPException(404, "No cover art for this release")
        return Response(data, media_type=sniff_image_type(data), headers={"Cache-Control": "private, max-age=86400"})

    @app.post("/api/musicbrainz/apply")
    def mb_apply(body: MBProposalIn) -> dict:
        """Write the release's tags (and cover) to the paired files: one activity
        entry, undoable as a whole."""
        proposal, release = mb_proposal(body)
        summary = proposal["release"]
        art, art_error = None, None
        if any(f.get("cover") for f in proposal["files"]):
            try:
                art = fetch_cover(summary["id"], 1200) or fetch_cover(summary["id"], None)
                if art is None:
                    art_error = "This release has no cover art on the Cover Art Archive"
            except ProviderError as exc:
                art_error = str(exc)
        tag_undo, art_undo, results = {}, {}, []
        for f in proposal["files"]:
            rel = f["path"]
            if f["error"]:
                results.append({"path": rel, "ok": False, "error": f["error"]})
                continue
            set_art = bool(f["cover"] and art)
            if not f["changes"] and not set_art:
                continue
            target = library.resolve(rel)
            errors = []
            if f["changes"]:
                try:
                    meta = engine.update_tags(target, {k: c["new"] for k, c in f["changes"].items()})
                    tag_undo[rel] = {"before": {k: c["old"] for k, c in f["changes"].items()},
                                     "after": {k: meta.tags.get(k, []) for k in f["changes"]}}
                except (MetadataError, LibraryPathError, OSError) as exc:
                    errors.append(str(exc))
            if set_art and not errors:
                try:
                    old = engine.read_artwork(target)
                    new = engine.update_artwork(target, art)
                    try:
                        before, after = art_store.save(old.data if old else None), art_store.save(new.data if new else None)
                        if before != after:
                            art_undo[rel] = {"before": before, "after": after}
                    except OSError:
                        pass  # couldn't keep a copy: the cover part just won't be undoable
                except (MetadataError, LibraryPathError, OSError) as exc:
                    errors.append(f"Cover art: {exc}")
            results.append({"path": rel, "ok": not errors, "error": "; ".join(errors) or None,
                            "tags": len(f["changes"]), "cover": set_art and not errors})
        parts = [p for p in ({"type": "tags", "files": tag_undo}, {"type": "art", "files": art_undo}) if p["files"]]
        undo = parts[0] if len(parts) == 1 else {"type": "multi", "parts": parts} if parts else None
        if results:
            _log_musicbrainz(activity, summary, proposal["files"], results, bool(art_undo), undo)
        # Every file that changed, including one whose tags saved but cover didn't.
        lib_index.mark_dirty({r["path"] for r in results if r["ok"]} | set(tag_undo) | set(art_undo))
        return {
            "release": summary,
            "results": results,
            "updated": sum(r["ok"] for r in results),
            "failed": sum(not r["ok"] for r in results),
            "cover_error": art_error,
        }

    @app.get("/api/track/raw")
    def get_track_raw(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")) -> dict:
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
        before: dict[str, dict[str, list[str]]] = {}  # for the activity log

        paths = _unique(body.paths)
        # A tag edit never touches the embedded cover: reuse what the index knows about it
        # instead of opening every file once more just to hash its picture again.
        known_art = {p: (t.get("art"),) for p, (_, _, t) in lib_index.stored(paths).items()} if len(paths) > 8 else {}

        def write(rel: str) -> UpdateResult:
            try:
                target = library.resolve(rel)
                was: dict = {}
                meta = engine.update_tags(target, body.changes, before=was)  # safe write: copy, check, swap
                before[rel] = was["tags"]
                if rel in known_art:
                    try:
                        mtime = target.stat().st_mtime_ns
                    except OSError:
                        mtime = None
                    out = _to_track_out(rel, meta, mtime)
                    art = known_art[rel][0]
                    out.art = ArtInfo(**art) if art else None
                    return UpdateResult(path=rel, ok=True, track=out)
                return UpdateResult(path=rel, ok=True, track=to_out(rel, meta))
            except (MetadataError, LibraryPathError, OSError) as exc:
                return UpdateResult(path=rel, ok=False, error=str(exc))

        if len(paths) > 8:
            # Most of a safe write is waiting for the disk, so a few at once is ~1.6x faster
            # (more on hard drives). Each file still has its own lock and its own safe write.
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="codetta-write") as pool:
                results = list(pool.map(write, paths))
        else:
            results = [write(rel) for rel in paths]
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
    def get_art(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File, relative to the music folder")):
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

    # --- Organize ---------------------------------------------------------------------

    pattern_file = settings.config_dir / "organize.json"

    def organize_plan(body: OrganizeIn) -> tuple[str, list[Move]]:
        require_library()
        try:
            pattern = check_pattern(body.pattern) if body.pattern is not None else load_pattern(pattern_file)
        except PatternError as exc:
            raise HTTPException(422, str(exc)) from exc
        if body.folder is not None:
            try:
                rels = audio_files(library, body.folder, body.recursive, MAX_ORGANIZE)
            except TooManyFilesError as exc:
                raise HTTPException(422, str(exc)) from exc
        else:
            rels = _unique(body.paths)
        sources, errors = [], []
        for rel in rels:
            try:
                meta = engine.load_metadata(library.resolve(rel))
                sources.append(Source(rel, meta.tags, meta.format or ""))
            except (MetadataError, LibraryPathError, OSError) as exc:
                errors.append(Move(rel, rel, "error", str(exc)))
        return pattern, plan_moves(library.resolve, sources, pattern) + errors

    @app.get("/api/organize/settings")
    def organize_settings() -> dict:
        return {"pattern": load_pattern(pattern_file), "default": DEFAULT_PATTERN,
                "presets": [{"name": n, "pattern": p} for n, p in ORGANIZE_PRESETS]}

    @app.put("/api/organize/settings")
    def save_organize_settings(body: PatternIn) -> dict:
        try:
            save_pattern(pattern_file, body.pattern)
        except PatternError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return organize_settings()

    @app.post("/api/organize/example")
    def organize_example(body: PatternIn) -> dict:
        """What the pattern makes of a sample track (for the live example while typing)."""
        try:
            check_pattern(body.pattern)
        except PatternError as exc:
            return {"ok": False, "error": str(exc)}
        sample = Source("Some Folder/track.flac", {
            "albumartist": ["Kōsei Mori"], "artist": ["Kōsei Mori"], "album": ["Northern Signal"],
            "title": ["Harbour Lights"], "tracknumber": ["3/10"], "discnumber": ["2/2"], "date": ["2021-04-09"],
            "genre": ["Ambient"], "label": ["Low Orbit Records"],
        }, "flac")
        return {"ok": True, "single": render(body.pattern, sample, False), "multi": render(body.pattern, sample, True)}

    @app.post("/api/organize/preview")
    def organize_preview(body: OrganizeIn) -> dict:
        """Where each file would go. Nothing is moved."""
        pattern, moves = organize_plan(body)
        counts = {k: sum(m.status == k for m in moves) for k in ("move", "same", "conflict", "error")}
        return {"pattern": pattern, "counts": counts, "extras": sum(len(m.companions) for m in moves),
                "moves": [m.to_dict() for m in moves]}

    @app.post("/api/organize/apply")
    def organize_apply(body: OrganizeIn) -> dict:
        """Rename and move the files (and their extras). One undoable activity entry."""
        pattern, moves = organize_plan(body)
        results = apply_moves(library.resolve, moves)
        moved = [pair for r in results if r.ok for pair in r.moved]
        ok = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        if results:
            target = _name(ok[0].dst) if len(ok) == 1 else f"{len(ok)} tracks"
            message = (f"Organized {target}" if not failed else
                       f"Organized {len(ok)} of {len(results)} tracks" if ok else "Couldn't organize the tracks")
            activity.add(
                "organize", message, ok=not failed,
                files=[r.dst for r in ok] + [r.src for r in failed],
                changes=[{"key": "location", "old": ok[0].src, "new": ok[0].dst}] if len(ok) == 1 else
                        [{"key": "pattern", "old": "", "new": pattern}],
                errors=[{"path": r.src, "error": r.error or ""} for r in failed],
                undo={"type": "moves", "moves": [list(p) for p in moved]} if moved else None,
            )
        lib_index.mark_dirty([p for pair in moved for p in pair if not p.startswith("@")])  # the index covers the library only
        art_cache.clear()
        return {
            "moved": len(ok), "failed": len(failed), "extras": len(moved) - len(ok),
            "results": [{"src": r.src, "dst": r.dst, "ok": r.ok, "error": r.error} for r in results],
            # Not attempted: the name is taken (maybe a duplicate) or the file couldn't be read.
            "held": [{"src": m.src, "dst": m.dst, "reason": m.reason} for m in moves if m.status in ("conflict", "error")],
        }

    # --- First-run setup -----------------------------------------------------------------

    onboarding = OnboardingStore(settings.config_dir / "onboarding.json")

    @app.get("/api/onboarding")
    def get_onboarding() -> dict:
        """Setup steps still to show (new installs: all; after an update: only new ones)."""
        steps = []
        if connections.needs_choice:
            steps.append("connections")
        steps += [s for s in ("organize", "inbox", "health", "slskd") if s not in onboarding.done]
        return {"steps": steps}

    @app.post("/api/onboarding/{step}")
    def finish_onboarding_step(step: str) -> dict:
        if step == "connections":
            return get_onboarding()  # finished by saving the connections
        try:
            onboarding.mark(step)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return get_onboarding()

    # --- Import inbox ------------------------------------------------------------------

    inbox = InboxStore(settings.config_dir / "inbox.json", settings.inbox_settle_seconds)
    inbox_worker: dict = {"thread": None}
    inbox_wake = threading.Event()

    def inbox_tags(paths: list[str]) -> tuple[str, str]:
        infos, _, _ = mb_read(paths[:50])
        return (most_common(f.album for f in infos),
                most_common(f.albumartist or f.artist for f in infos))

    def inbox_match(key: str) -> None:
        g = inbox.update(key, status=MATCHING, note="")
        if g is None:
            return
        title, artist = inbox_tags(g.paths)
        if not connections.enabled("musicbrainz"):
            inbox.update(key, status=LOCAL, title=title, artist=artist,
                         note="Online lookups are off, so this files by its own tags.")
            return
        try:
            found = mb_search(MBSearchIn(paths=g.paths)) if (title or artist) else {"candidates": []}
            cands, recordings = found["candidates"], {}
            sound = connections.enabled("acoustid") and fingerprinter.available and len(g.paths) <= MAX_IDENTIFY
            if sound and (not cands or cands[0]["score"] < 85):
                heard = mb_identify(MBTarget(paths=g.paths))
                if heard["candidates"] and (not cands or heard["candidates"][0]["score"] >= cands[0]["score"]):
                    cands, recordings = heard["candidates"], heard["recordings"]
            if not cands:
                inbox.update(key, status=NO_MATCH, title=title, artist=artist,
                             note="Not found on MusicBrainz. Review it to search by hand, or file it by its own tags.")
                return
            best = cands[0]
            proposal = mb_preview(MBProposalIn(paths=g.paths, release=best["id"], recordings=recordings))
            files = [f for f in proposal["files"] if not f["error"]]
            exact = (all(f["track"] and f["confidence"] == "high" for f in files)
                     and best.get("track_count") == len(files) and best["score"] >= 85)
            inbox.update(key, status=READY if exact else REVIEW, title=best["title"], artist=best["artist"],
                         release=best, score=best["score"], recordings=recordings,
                         note="" if exact else "Check the match: not every track lines up for certain.")
            if exact and inbox_auto(key):
                inbox_file(key, automatic=True)
        except HTTPException as exc:
            if exc.status_code == 409 and key in inbox_filing:
                return  # someone tapped "File" a moment earlier: that filing carries on
            inbox.update(key, status=INBOX_ERROR, title=title, artist=artist, note=str(exc.detail))

    def inbox_auto(key: str) -> bool:
        """File a confident match without asking? Soulseek downloads follow the
        Soulseek setting (review by default), everything else the inbox's."""
        g = inbox.groups.get(key)
        if g is not None and g.source:
            return not soulseek_store.settings.review
        return inbox.settings.auto

    inbox_filing: set[str] = set()
    inbox_filing_lock = threading.Lock()

    def inbox_file(key: str, release: str | None = None, recordings: dict | None = None, automatic: bool = False) -> dict:
        """File one album. A second request for the same album while it's being filed (a double
        tap, or "File all" while it's filing itself) is turned away instead of running twice."""
        with inbox_filing_lock:
            if key in inbox_filing:
                raise HTTPException(409, "This album is already being filed.")
            inbox_filing.add(key)
        try:
            return inbox_file_locked(key, release, recordings, automatic)
        finally:
            with inbox_filing_lock:
                inbox_filing.discard(key)

    def inbox_file_locked(key: str, release: str | None, recordings: dict | None, automatic: bool) -> dict:
        g = inbox.groups.get(key)
        if g is None:
            raise HTTPException(404, "That album is no longer in the inbox")
        release = release or (g.release or {}).get("id")
        notes, moved_to = [], None
        if release:
            res = mb_apply(MBProposalIn(paths=g.paths, release=release, recordings=recordings or g.recordings))
            if res["failed"]:
                notes.append(f"{res['failed']} track(s) couldn't be tagged")
        if g.upgrade and not notes:
            notes.extend(set_aside(g.upgrade))
        if inbox.settings.organize or g.upgrade:
            org = organize_apply(OrganizeIn(paths=g.paths))
            ok = [r for r in org["results"] if r["ok"]]
            if ok:
                moved_to = ok[0]["dst"].rsplit("/", 1)[0]
            stuck = org["failed"] + len(org["held"])
            if stuck:
                notes.append(f"{stuck} file(s) couldn't move: a file with that name is already in your library (a duplicate?)")
        status = FILED if not notes else INBOX_ERROR
        if automatic:
            name = " by ".join(x for x in (f"“{g.title}”" if g.title else g.key.rsplit("/", 1)[-1], g.artist) if x)
            if status == FILED:
                notices.add("inbox", f"Filed {name}", f"Matched on MusicBrainz and moved to {moved_to or 'your library'}.",
                            {"open": "folder", "path": moved_to} if moved_to else {"open": "inbox"})
            else:
                notices.add("inbox", f"Couldn't file {name}", "; ".join(notes), {"open": "inbox"})
        inbox.update(key, status=status, dest=moved_to or "",
                     note="; ".join(notes) or (f"Filed in {moved_to}" if moved_to else "Tagged"),
                     release=g.release if not release or (g.release or {}).get("id") == release else {"id": release})
        job = soulseek_store.jobs.get(g.source) if g.source else None
        if job is not None and status == FILED:
            soulseek_store.update(job, status=SK_IMPORTED, note=f"Filed in {moved_to}" if moved_to else "Filed")
        return {"status": status, "moved_to": moved_to, "note": "; ".join(notes)}

    def set_aside(folder: str) -> list[str]:
        """An upgrade: move the album it replaces out of the library, into the
        config folder ("@replaced"), as one undoable activity entry. Returns problems."""
        try:
            top = library.resolve(folder)
        except LibraryPathError as exc:
            return [str(exc)]
        if folder.startswith("@") or not folder or not top.is_dir():
            return []  # nothing there (any more): the download is simply new
        stamp = time.strftime("%Y%m%d-%H%M%S")
        moves = []
        for dirpath, _, names in os.walk(top):
            for name in names:
                rel = library.relative(Path(dirpath) / name)
                moves.append(Move(rel, f"@replaced/{stamp}/{rel}", "move"))
        results = apply_moves(library.resolve, moves)
        moved = [pair for r in results if r.ok for pair in r.moved]
        failed = [r for r in results if not r.ok]
        if moved:
            activity.add("organize", f"Set aside {_name(folder)} for its upgrade", ok=not failed,
                         files=[a for a, _ in moved], changes=[{"key": "location", "old": folder, "new": "(replaced)"}],
                         errors=[{"path": r.src, "error": r.error or ""} for r in failed],
                         undo={"type": "moves", "moves": [list(p) for p in moved]})
            lib_index.mark_dirty([a for a, _ in moved])
            art_cache.clear()
        return [f"{len(failed)} file(s) of the old album couldn't be moved aside"] if failed else []

    def inbox_run() -> None:
        done: list[str] = []
        while True:
            with inbox.lock:
                nxt = next((g.key for g in inbox.groups.values() if g.status == WAITING), None)
            if nxt is None:
                inbox_summary(done)
                return
            done.append(nxt)
            try:
                inbox_match(nxt)
                soulseek_matched(nxt)
            except Exception as exc:  # never let one album stop the queue
                log.warning("Inbox: couldn't look up %s: %s", nxt, exc)
                inbox.update(nxt, status=INBOX_ERROR, note="Something went wrong looking this up")

    def inbox_summary(keys: list[str]) -> None:
        """One notification when a round of lookups ends (auto-filed albums have their own)."""
        groups = [g for k in keys if (g := inbox.groups.get(k))]
        ready = [g for g in groups if g.status in (READY, LOCAL)]
        look = [g for g in groups if g.status in (REVIEW, NO_MATCH, INBOX_ERROR)]
        if not ready and not look:
            return
        parts = []
        if ready:
            parts.append(f"{len(ready)} ready to file")
        if look:
            parts.append(f"{len(look)} need{'s' if len(look) == 1 else ''} a look")
        names = ", ".join(g.title or g.key.rsplit("/", 1)[-1] for g in (ready + look)[:3])
        more = len(ready) + len(look) - 3
        notices.add("inbox", f"Inbox: {' · '.join(parts)}", names + (f" and {more} more" if more > 0 else ""),
                    {"open": "inbox"})

    def inbox_start() -> None:
        t = inbox_worker["thread"]
        if t is None or not t.is_alive():
            inbox_worker["thread"] = threading.Thread(target=inbox_run, name="codetta-inbox", daemon=True)
            inbox_worker["thread"].start()

    def inbox_watch() -> None:
        last_prune = time.time()
        while not inbox_wake.wait(15 * 60):
            if time.time() - last_prune > 86400:
                last_prune = time.time()
                prune_replaced(settings.config_dir / "replaced")
                prune_replaced(settings.config_dir / "deleted")
            if inbox.settings.watch and inbox.settings.folder and library.exists():
                try:
                    inbox.sync(library)
                    inbox_start()
                except (OSError, LibraryPathError) as exc:
                    log.warning("Inbox check failed: %s", exc)

    app.state.inbox_watch = inbox_watch  # started in lifespan

    sk_transfers: dict = {"at": 0.0, "list": []}

    def inbox_transfers() -> list[dict]:
        """slskd's downloads, while something in the inbox is still arriving (for its progress bar)."""
        if not any(g.status == DOWNLOADING for g in list(inbox.groups.values())):
            return []
        if not (connections.enabled("slskd") and soulseek_store.configured):
            return []
        if time.time() - sk_transfers["at"] > 3:
            try:
                sk_transfers["list"] = soulseek.client().all_downloads()
            except SlskdError:
                sk_transfers["list"] = []
            sk_transfers["at"] = time.time()
        return sk_transfers["list"]

    def inbox_out() -> dict:
        transfers = inbox_transfers()
        with inbox.lock:
            groups = sorted(inbox.groups.values(), key=lambda g: (g.status == FILED, -g.updated if g.status == FILED else 0, g.key))
            counts = {}
            for g in groups:
                counts[g.status] = counts.get(g.status, 0) + 1
            folder = inbox.settings.folder
            running = bool(inbox_worker["thread"] and inbox_worker["thread"].is_alive())
            try:
                exists = bool(folder) and library.resolve(folder).is_dir()
            except LibraryPathError:
                exists = False
            return {
                # A downloads folder mounted outside the music folder (e.g. slskd's), offered first.
                "external": {"available": library.inbox_available(),
                             "path": str(settings.inbox_dir) if settings.inbox_dir else None},
                "downloading": sum(g.status == DOWNLOADING for g in groups),
                "settings": {"folder": folder, "auto": inbox.settings.auto, "organize": inbox.settings.organize,
                             "watch": inbox.settings.watch},
                "folder_exists": exists,
                "online": connections.enabled("musicbrainz"),
                "running": running, "counts": counts,
                "groups": [{"key": g.key, "files": len(g.paths), "paths": g.paths[:1000], "status": g.status,
                            "title": g.title, "artist": g.artist, "release": g.release, "score": g.score,
                            "recordings": g.recordings, "note": g.note, "dest": g.dest,
                            "transfer": folder_progress(transfers, {p.rsplit("/", 1)[-1] for p in g.paths})
                                        if transfers and g.status == DOWNLOADING else None} for g in groups],
            }

    @app.get("/api/inbox")
    def get_inbox() -> dict:
        """The inbox: re-read its folder and look up anything new (in the background)."""
        require_library()
        if inbox.settings.folder:
            try:
                inbox.sync(library)
            except (OSError, LibraryPathError) as exc:
                raise HTTPException(500, f"Couldn't read the inbox folder: {exc}") from exc
            inbox_start()
        return inbox_out()

    @app.put("/api/inbox/settings")
    def put_inbox_settings(body: InboxSettingsIn) -> dict:
        require_library()
        folder = body.folder.strip().strip("/")
        if folder.startswith("@") and folder != INBOX_ALIAS and not folder.startswith(INBOX_ALIAS + "/"):
            raise HTTPException(422, "The inbox can be your downloads folder or a folder in your music folder.")
        if not folder:
            raise HTTPException(422, "Choose your downloads folder, or a folder inside your music folder (not the whole library).")
        if not library.resolve(folder).is_dir():
            raise HTTPException(422, "The downloads folder isn't mounted (see CODETTA_INBOX_DIR)." if folder.startswith("@")
                                else f"There's no folder called “{folder}” in your music folder.")
        with inbox.lock:
            if folder != inbox.settings.folder:
                inbox.groups.clear()
            inbox.settings.folder, inbox.settings.auto = folder, body.auto
            inbox.settings.organize, inbox.settings.watch = body.organize, body.watch
            try:
                inbox.save()
            except OSError as exc:
                raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return get_inbox()

    @app.post("/api/inbox/accept")
    def inbox_file_route(body: InboxActionIn) -> dict:
        """File one album: write its MusicBrainz tags (if matched) and organize it into the library."""
        require_library()
        release = None
        if body.release:
            release = parse_release_id(body.release)
            if not release:
                raise HTTPException(422, "That isn't a MusicBrainz release.")
        result = inbox_file(body.key, release, body.recordings or None)
        return {**result, "inbox": inbox_out()}

    @app.post("/api/inbox/accept-ready")
    def inbox_file_ready() -> dict:
        """File every confident match in one go."""
        require_library()
        keys = [g.key for g in list(inbox.groups.values()) if g.status == READY]
        filed = 0
        for k in keys:
            try:
                filed += inbox_file(k)["status"] == FILED
            except HTTPException as exc:
                if exc.status_code != 409:  # 409: already being filed, by itself or another tap
                    raise
        return {"filed": filed, "total": len(keys), "inbox": inbox_out()}

    @app.post("/api/inbox/skip")
    def inbox_skip(body: InboxActionIn) -> dict:
        if inbox.update(body.key, status=SKIPPED, note="Skipped: left where it is") is None:
            raise HTTPException(404, "That album is no longer in the inbox")
        return inbox_out()

    @app.post("/api/inbox/rematch")
    def inbox_rematch(body: InboxActionIn) -> dict:
        if inbox.update(body.key, status=WAITING, note="", release=None, score=None) is None:
            raise HTTPException(404, "That album is no longer in the inbox")
        inbox_start()
        return inbox_out()

    # --- Soulseek through slskd -------------------------------------------------------------

    soulseek_store = SoulseekStore(settings.config_dir / "slskd.json", settings.slskd_url, settings.slskd_api_key)
    soulseek = Soulseek(soulseek_store, request=slskd_request or slskd_http_request,
                        notify=lambda title, body, action: notices.add("soulseek", title, body, action))
    sk_worker: dict = {"thread": None, "check": None}
    sk_wake = threading.Event()

    def sk_ready() -> None:
        if not connections.enabled("slskd"):
            raise HTTPException(403, "Soulseek is off. Turn it on in Account → Connections.")
        if not soulseek_store.configured:
            raise HTTPException(409, "Connect your slskd first: Account → Connections → Soulseek.")

    def sk_job(job_id: str):
        if not re.fullmatch(r"[0-9a-f-]{32,36}", job_id or ""):
            raise HTTPException(404, "That Soulseek request is gone")
        job = soulseek_store.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "That Soulseek request is gone")
        return job

    def sk_locate(job) -> str | None:
        """Find a finished download in the inbox (by its file names) and hand it over."""
        names = set(sk_basenames(job))
        if not names or not inbox.settings.folder:
            return None
        best = None
        for g in inbox.sync(library):
            if g.status == FILED or (g.source and g.source != job.id):
                continue  # filed already, or another request's download
            hit = len(names & {p.rsplit("/", 1)[-1] for p in g.paths})
            # Most of what was asked for, and most of what's there (an older album that happens
            # to share names like "01.flac" must never be taken for it: blocklisting deletes it).
            if hit < max(1, int(len(names) * 0.8)) or hit < int(len(g.paths) * 0.8):
                continue
            if inbox_signature(library, g.paths)[1] < job.created - 60:
                continue  # these files were there before the request
            if best is None or hit > best[0]:
                best = (hit, g.key)
        if best is None:
            return None
        # slskd says it's complete, so no need to wait for the files to settle.
        inbox.update(best[1], source=job.id, upgrade=job.upgrade, status=WAITING, note="", release=None, score=None)
        inbox_start()
        return best[1]

    def soulseek_matched(key: str) -> None:
        """A Soulseek download has been matched: ask for a review (unless it filed itself)."""
        g = inbox.groups.get(key)
        job = soulseek_store.jobs.get(g.source) if g and g.source else None
        if job is None or g.status in (FILED, MATCHING, WAITING):
            return
        name = g.title or job.query
        soulseek_store.update(job, note="Downloaded: have a look")
        notices.add("soulseek", f"Soulseek: “{name}” is here",
                    f"{(job.current or {}).get('quality', '')} from {(job.current or {}).get('username', '')}. "
                    "Import it, or blocklist it and try the next one.",
                    {"open": "soulseek", "job": job.id}, key=f"sk-review:{job.id}:{job.pick}")

    def sk_run() -> None:
        while soulseek_store.active():
            try:
                soulseek.tick(sk_locate)
            except Exception as exc:  # keep going whatever one job does
                log.warning("Soulseek: %s", exc)
            if sk_wake.wait(settings.slskd_poll_seconds):
                return

    def sk_start() -> None:
        t = sk_worker["thread"]
        if soulseek_store.active() and (t is None or not t.is_alive()):
            sk_wake.clear()
            sk_worker["thread"] = threading.Thread(target=sk_run, name="codetta-soulseek", daemon=True)
            sk_worker["thread"].start()

    app.state.soulseek_start = sk_start
    app.state.soulseek_stop = sk_wake.set

    def sk_drop_download(job) -> None:
        """Remove what a job brought into the inbox (when it's blocklisted or swapped)."""
        g = inbox.groups.get(job.inbox_key) if job.inbox_key else None
        if g is None or g.status == FILED:
            return
        folders = []
        for rel in g.paths:
            if not rel.startswith(inbox.settings.folder + "/"):
                continue  # only ever inside the inbox
            try:
                library.resolve(rel).unlink(missing_ok=True)
                folders.append(rel.rsplit("/", 1)[0])
            except (OSError, LibraryPathError):
                pass
        if g.key != inbox.settings.folder and g.key.startswith(inbox.settings.folder + "/"):
            try:  # the folder slskd made: its leftovers (cover.jpg, .nfo...) go too
                top = library.resolve(g.key)
                for p in sorted(top.rglob("*"), key=lambda p: -len(p.parts)):
                    p.unlink() if p.is_file() or p.is_symlink() else p.rmdir()
                top.rmdir()
            except (OSError, LibraryPathError):
                pass
        remove_empty_dirs(library.resolve, folders)
        with inbox.lock:
            inbox.groups.pop(g.key, None)
            inbox.save()

    def sk_job_out(job) -> dict:
        g = inbox.groups.get(job.inbox_key) if job.inbox_key else None
        def cand(i, c):
            return {k: c[k] for k in ("username", "folder", "name", "tracks", "size", "quality", "lossless",
                                      "free_slot", "speed", "queue", "score")} | {"index": i, "tried": i in job.tried}
        cur = job.current
        return {
            "id": job.id, "query": job.query, "status": job.status, "note": job.note, "progress": job.progress,
            "eta": job.eta,
            "created": job.created, "updated": job.updated, "upgrade": job.upgrade,
            "current": cand(job.pick, cur) | {"files": [split_name(f["filename"]) for f in cur.get("files", [])]} if cur else None,
            "candidates": [cand(i, c) for i, c in enumerate(job.candidates)],
            "inbox": {"key": g.key, "status": g.status, "title": g.title, "artist": g.artist, "release": g.release,
                      "score": g.score, "note": g.note, "paths": g.paths[:200], "recordings": g.recordings,
                      "dest": g.dest}
                     if g else None,
        }

    def split_name(remote: str) -> str:
        return remote.replace("\\", "/").rsplit("/", 1)[-1]

    def soulseek_out(check_result: dict | None = None) -> dict:
        with soulseek_store.lock:
            jobs = sorted(soulseek_store.jobs.values(), key=lambda j: -j.created)
            st = soulseek_store.settings
            return {
                "enabled": connections.enabled("slskd"),
                "configured": soulseek_store.configured,
                "url": soulseek_store.url, "has_key": bool(soulseek_store.api_key),
                "locked": {"url": soulseek_store.env_url is not None, "api_key": soulseek_store.env_key is not None},
                "settings": {"review": st.review, "lossless_only": st.lossless_only, "min_bitrate": st.min_bitrate,
                             "search_seconds": st.search_seconds},
                "inbox": {"folder": inbox.settings.folder, "external": library.inbox_available()},
                "blocked": len(soulseek_store.blocked),
                "check": check_result if check_result is not None else sk_worker["check"],
                "jobs": [sk_job_out(j) for j in jobs[:50]],
            }

    def sk_check() -> dict:
        if not soulseek_store.configured:
            return {"ok": False, "error": "Add your slskd's address and an API key."}
        result = slskd_check(soulseek.client())
        sk_worker["check"] = result
        return result

    @app.get("/api/slskd")
    def get_soulseek() -> dict:
        """Soulseek: connection details (never the API key), settings and requests."""
        return soulseek_out()

    @app.put("/api/slskd/settings")
    def put_soulseek_settings(body: SlskdSettingsIn) -> dict:
        url = slskd_clean_url(body.url)
        if url:
            parts = urlsplit(url)
            if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
                    or any(c.isspace() for c in url) or parts.query or parts.fragment):
                raise HTTPException(422, "slskd's address should look like http://slskd:5030 or http://192.168.1.50:5030")
            try:
                parts.port  # a port that isn't a number raises
            except ValueError:
                raise HTTPException(422, "The port in slskd's address should be a number, like :5030") from None
        if body.api_key is not None and body.api_key.strip():
            key = body.api_key.strip()
            if any(c.isspace() for c in key) or not key.isprintable() or len(key) < 8:
                raise HTTPException(422, "That doesn't look like an slskd API key (at least 8 characters, no spaces).")
        with soulseek_store.lock:
            st = soulseek_store.settings
            if soulseek_store.env_url is None:
                st.url = url
            if body.api_key is not None and soulseek_store.env_key is None:
                st.api_key = body.api_key.strip()
            st.review, st.lossless_only = body.review, body.lossless_only
            st.min_bitrate, st.search_seconds = body.min_bitrate, body.search_seconds
            try:
                soulseek_store.save()
            except OSError as exc:
                raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return soulseek_out(sk_check() if soulseek_store.configured else None)

    @app.post("/api/slskd/test")
    def test_soulseek() -> dict:
        return soulseek_out(sk_check())

    @app.post("/api/slskd/search")
    def soulseek_search(body: SlskdSearchIn) -> dict:
        """Ask slskd to search; the best match is downloaded into the inbox."""
        sk_ready()
        if not inbox.settings.folder:
            raise HTTPException(409, "Set up the inbox first: Soulseek downloads arrive there.")
        upgrade = body.upgrade.strip().strip("/")
        if upgrade:
            try:
                if upgrade.startswith("@") or not library.resolve(upgrade).is_dir():
                    raise HTTPException(422, "That album folder isn't in your library.")
            except LibraryPathError as exc:
                raise HTTPException(422, str(exc)) from exc
        try:
            job = soulseek.search(body.query, upgrade)
        except SlskdError as exc:
            raise HTTPException(502, str(exc)) from exc
        sk_start()
        return {"job": sk_job_out(job), **soulseek_out()}

    @app.post("/api/slskd/jobs/{job_id}/next")
    def soulseek_next(job_id: str, body: SlskdNextIn) -> dict:
        """Not this one: (blocklist it and) download the next best candidate."""
        sk_ready()
        job = sk_job(job_id)
        cur = job.current
        if cur is None:
            raise HTTPException(409, "Nothing has been downloaded for this request yet.")
        if body.block:
            soulseek.blocklist(cur["username"], cur["folder"])
        try:
            if job.status == SK_DOWNLOADING:
                soulseek.cancel_transfers(job)
            sk_drop_download(job)
            soulseek.next_candidate(job, f"Blocklisted {cur['name']} from {cur['username']}." if body.block else "")
        except SlskdError as exc:
            raise HTTPException(502, str(exc)) from exc
        sk_start()
        return soulseek_out()

    @app.post("/api/slskd/jobs/{job_id}/pick")
    def soulseek_pick(job_id: str, body: SlskdPickIn) -> dict:
        """Download a candidate of your choosing instead."""
        sk_ready()
        job = sk_job(job_id)
        if body.index >= len(job.candidates):
            raise HTTPException(404, "That result is gone")
        try:
            if job.status == SK_DOWNLOADING:
                soulseek.cancel_transfers(job)
            if job.status == SK_ARRIVED:
                sk_drop_download(job)
            soulseek.start(job, body.index)
        except SlskdError as exc:
            raise HTTPException(502, str(exc)) from exc
        sk_start()
        return soulseek_out()

    @app.post("/api/slskd/jobs/{job_id}/import")
    def soulseek_import(job_id: str, body: SlskdImportIn | None = None) -> dict:
        """Keep it: file the download into the library (replacing the album it upgrades)."""
        require_library()
        job = sk_job(job_id)
        if job.status != SK_ARRIVED or job.inbox_key not in inbox.groups:
            raise HTTPException(409, "This download isn't in the inbox (yet).")
        release = None
        if body and body.release:
            release = parse_release_id(body.release)
            if not release:
                raise HTTPException(422, "That isn't a MusicBrainz release.")
        result = inbox_file(job.inbox_key, release, (body.recordings if body else None) or None)
        return {**result, **soulseek_out()}

    @app.post("/api/slskd/jobs/{job_id}/cancel")
    def soulseek_cancel(job_id: str) -> dict:
        job = sk_job(job_id)
        if job.status == SK_DOWNLOADING and soulseek_store.configured:
            try:
                soulseek.cancel_transfers(job)
            except SlskdError:
                pass
        if job.status in (SK_DOWNLOADING, "searching", "fetched"):
            soulseek_store.update(job, status=SK_CANCELLED, note="Cancelled")
        return soulseek_out()

    @app.delete("/api/slskd/jobs/{job_id}")
    def soulseek_forget(job_id: str) -> dict:
        """Take a finished request off the list (the files stay wherever they are)."""
        job = sk_job(job_id)
        if job.status not in (SK_IMPORTED, SK_NOTHING, SK_FAILED, SK_CANCELLED, SK_ARRIVED):
            raise HTTPException(409, "Cancel it first.")
        with soulseek_store.lock:
            soulseek_store.jobs.pop(job.id, None)
            soulseek_store.save()
        return soulseek_out()

    @app.delete("/api/slskd/blocklist")
    def soulseek_clear_blocklist() -> dict:
        with soulseek_store.lock:
            soulseek_store.blocked.clear()
            soulseek_store.save()
        return soulseek_out()

    # --- Explore MusicBrainz (the !mb bang) -------------------------------------------------------

    owned_cache: dict = {"key": None, "albums": {}}

    def owned_albums() -> dict[str, dict[str, str]]:
        """Albums in the library: artist (folded) -> album name (folded, also without
        "(Deluxe)"-style suffixes) -> folder. From the index, rebuilt when it changes."""
        key = lib_index.version
        if owned_cache["key"] != key:
            albums: dict[str, dict[str, str]] = {}
            for path, track in lib_index.iter_tracks():
                tags = track.get("tags") or {}
                album = next((v for v in tags.get("album", []) if v.strip()), "")
                who = next((v for v in tags.get("albumartist", []) + tags.get("artist", []) if v.strip()), "")
                if not album or not who:
                    continue
                folder = path.rsplit("/", 1)[0] if "/" in path else ""
                names = albums.setdefault(health_fold(base_artist(who)), {})
                for name in {health_fold(album), health_fold(EDITION_RE.sub("", album))}:
                    names.setdefault(name, folder)
            owned_cache.update(key=key, albums=albums)
        return owned_cache["albums"]

    def owned_folder(artist: str, title: str) -> str | None:
        names = owned_albums().get(health_fold(base_artist(artist)))
        if not names:
            return None
        return names.get(health_fold(title)) or names.get(health_fold(EDITION_RE.sub("", title)))

    def with_owned(g: dict) -> dict:
        return {**g, "in_library": owned_folder(g["artist"], g["title"]) if g["artist"] else None}

    def explore(call, mbid: str | None = None):
        if mbid is not None and not MBID_RE.match(mbid):
            raise HTTPException(422, "That isn't a MusicBrainz ID.")
        require_connection("musicbrainz")
        try:
            return call()
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/api/mb/search")
    def mb_explore_search(q: str = Query(..., min_length=1, max_length=200)) -> dict:
        """Artists and releases on MusicBrainz matching ``q`` (two requests: about two seconds)."""
        q = " ".join(q.split())
        if sum(c.isalnum() for c in q) < 2:
            raise HTTPException(422, "Type at least two letters or numbers to search MusicBrainz.")
        def run():
            artists = [artist_summary(a) for a in mb.search_artists(q)]
            groups = [with_owned(group_summary(g)) for g in mb.search_release_groups(q)]
            return {"query": q, "artists": [a for a in artists if (a["score"] or 0) >= 60][:8],
                    "releases": [g for g in groups if (g["score"] or 0) >= 60][:15]}
        return explore(run)

    @app.get("/api/mb/artist/{mbid}")
    def mb_explore_artist(mbid: str) -> dict:
        """An artist: who they are, links, and their albums, EPs and singles."""
        def run():
            a = mb.artist(mbid)
            groups = [group_summary(g) for g in mb.artist_release_groups(mbid)]
            name = a.get("name") or ""
            for g in groups:
                g["artist"] = g["artist"] or name
                g["in_library"] = owned_folder(name, g["title"])
            genres = sorted((x for x in a.get("genres") or [] if isinstance(x, dict)), key=lambda x: -(x.get("count") or 0))
            return {**artist_summary(a), "links": artist_links(a), "genres": [x.get("name") for x in genres[:6]],
                    "groups": groups}
        return explore(run, mbid)

    @app.get("/api/mb/release-group/{mbid}")
    def mb_explore_group(mbid: str) -> dict:
        """A release: what it is, its first official edition's tracklist and label."""
        def run():
            g = mb.release_group(mbid)
            out = with_owned(group_summary(g))
            pick = pick_release(g)
            out["editions"] = len(g.get("releases") or [])
            genres = sorted((x for x in g.get("genres") or [] if isinstance(x, dict)), key=lambda x: -(x.get("count") or 0))
            out["genres"] = [x.get("name") for x in genres[:6]]
            out["release"] = None
            if pick:
                rel = mb.release_tracks_summary(pick["id"])
                labels = [li for li in rel.get("label-info") or [] if isinstance(li, dict)]
                media = [m for m in rel.get("media") or [] if isinstance(m, dict)]
                out["release"] = {
                    "id": rel.get("id"), "date": rel.get("date") or "", "country": rel.get("country") or "",
                    "label": next(((li.get("label") or {}).get("name") for li in labels if li.get("label")), ""),
                    "catno": next((li.get("catalog-number") for li in labels if li.get("catalog-number")), ""),
                    "format": " + ".join(dict.fromkeys(m.get("format") or "Digital" for m in media)),
                    "tracks": tracklist(rel),
                }
            return out
        return explore(run, mbid)

    # --- Library health -------------------------------------------------------------------------

    health_store = HealthStore(settings.config_dir / "health.json")
    health_cache: dict = {"key": None, "data": None, "at": 0.0, "fixed": {}, "complete": False}
    health_lock = threading.Lock()

    health_compute_lock = threading.Lock()
    health_worker: dict = {"thread": None}

    def health_compute() -> None:
        with health_compute_lock:
            key = lib_index.version
            complete = lib_index.status().ready  # made from the whole library, not mid-way through the first scan
            inbox_folder = inbox.settings.folder
            skip = [inbox_folder] if inbox_folder and not inbox_folder.startswith("@") else []
            data = health_run(lib_index.iter_tracks(), folder_has_image(library.resolve),
                              lib_index.paths_with_any(MB_RELEASE_KEYS), skip)
            with health_lock:
                health_cache.update(data=data, key=key, at=time.time(), complete=complete)

    def health_data() -> dict:
        """Every issue. The first check waits for the answer; after that, a change to the library
        (or 10 minutes, for cover files) re-checks in the background while the last answer is
        shown, so a big library never makes anyone wait twice."""
        with health_lock:
            data = health_cache["data"]
            stale = health_cache["key"] != lib_index.version or time.time() - health_cache["at"] > 600
            partial = not health_cache["complete"] and lib_index.status().ready
        if data is None or partial:  # never show an answer from half a library once the whole one is read
            health_compute()
        elif stale and not (health_worker["thread"] and health_worker["thread"].is_alive()):
            health_worker["thread"] = threading.Thread(target=health_compute, name="codetta-health", daemon=True)
            health_worker["thread"].start()
        return health_cache["data"]

    def health_public(issue: dict) -> dict:
        """What the page needs: never the file lists or the planned changes themselves."""
        fix = issue.get("fix")
        return {k: v for k, v in issue.items() if k not in ("paths", "fix")} | {
            "fix": {"label": fix["label"], "summary": fix["summary"]} if fix else None}

    def health_visible() -> tuple[dict, list[dict], list[dict]]:
        data = health_data()
        # A fixed issue stays hidden until a check made after the fix confirms it's gone.
        fixed = {i for i, v in health_cache["fixed"].items() if (health_cache["key"] or 0) <= v}
        shown, ignored = [], []
        for issue in data["issues"]:
            if issue["check"] in health_store.disabled or issue["id"] in fixed:
                continue
            (ignored if issue["id"] in health_store.ignored else shown).append(issue)
        return data, shown, ignored

    HEALTH_PAGE = 200  # issues per answer; "Show more" asks for the next ones

    @app.get("/api/library-health")
    def get_health_route(category: str = Query("all", max_length=20), offset: int = Query(0, ge=0, le=1_000_000),
                         limit: int = Query(HEALTH_PAGE, ge=1, le=1000)) -> dict:
        """Library health: things worth fixing, found from the search index. Issues come a page
        at a time (a big library can have thousands); ``count`` and the category counts are totals."""
        return get_health(category, offset, limit)

    def get_health(category: str = "all", offset: int = 0, limit: int = HEALTH_PAGE) -> dict:
        require_library()
        if not health_store.enabled:  # switched off: nothing is checked at all
            return {"enabled": False, "indexing": False, "albums": 0, "tracks": 0, "unmatched": None, "count": 0,
                    "categories": [], "checks": [], "issues": [], "ignored": []}
        data, shown, ignored = health_visible()
        return {
            "enabled": True,
            "indexing": not lib_index.status().ready,
            "albums": data["albums"], "tracks": data["tracks"],
            "unmatched": data["unmatched"] if connections.enabled("musicbrainz") else None,
            "count": len(shown),
            "categories": [{"id": c, "label": label, "count": sum(i["category"] == c for i in shown)}
                           for c, label in HEALTH_CATEGORIES.items()],
            "checks": [{"id": c.id, "category": c.category, "label": c.label, "about": c.about,
                        "enabled": c.id not in health_store.disabled} for c in HEALTH_CHECKS],
            "category": category, "offset": offset,
            "issues": [health_public(i) for i in (shown if category == "all" else [x for x in shown if x["category"] == category])[offset:offset + limit]],
            "shown_total": len(shown) if category == "all" else sum(x["category"] == category for x in shown),
            "ignored": [health_public(i) for i in ignored[:limit]],
            "ignored_total": len(ignored),
        }

    @app.get("/api/library-health/summary")
    def get_health_summary() -> dict:
        """Just the count (for the card on the Library page)."""
        require_library()
        if not health_store.enabled:
            return {"enabled": False, "count": 0, "indexing": False}
        _, shown, _ = health_visible()
        return {"enabled": True, "count": len(shown), "indexing": not lib_index.status().ready}

    @app.put("/api/library-health/settings")
    def put_health_settings(body: HealthSettingsIn) -> dict:
        known = {c.id for c in HEALTH_CHECKS}
        with health_store.lock:
            if body.enabled is not None:
                health_store.enabled = body.enabled
            if body.disabled is not None:
                health_store.disabled = {c for c in body.disabled if c in known}
        try:
            health_store.save()
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return get_health()

    @app.post("/api/library-health/ignore")
    def health_ignore(body: HealthIssueIn) -> dict:
        with health_store.lock:
            (health_store.ignored.add if body.ignore else health_store.ignored.discard)(body.id)
        try:
            health_store.save()
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return get_health()

    @app.post("/api/library-health/fix")
    def health_fix(body: HealthIssueIn) -> dict:
        """Apply an issue's one-tap fix: ordinary safe tag writes, one undoable activity entry."""
        require_library()
        if not health_store.enabled:
            raise HTTPException(409, "Library health is switched off.")
        with health_lock:
            stale = health_cache["key"] != lib_index.version
        if stale:  # the library changed since this list was made: check again before writing anything
            health_compute()
        issue = next((i for i in health_data()["issues"] if i["id"] == body.id), None)
        if issue is None:
            raise HTTPException(404, "That issue is gone (fixed already?)")
        fix = issue.get("fix")
        if not fix:
            raise HTTPException(409, "This one needs a look by hand.")
        version = lib_index.version
        done, failed = apply_per_file(fix["per_file"], f"Library health: {fix['summary']}")
        if not failed:
            health_cache["fixed"][issue["id"]] = version  # hidden until the index has the new tags
        return {"fixed": len(done), "failed": len(failed), "errors": failed[:20], "health": get_health()}

    # --- Plugins and actions -------------------------------------------------------------------

    plugins = PluginManager(settings.config_dir)

    @app.get("/api/plugins")
    def list_plugins() -> dict:
        """Installed plugins (built-in ones, and folders in <config>/plugins), and their actions."""
        with plugins.lock:
            return {"folder": str(plugins.dir), "plugins": [p.public() for p in plugins.plugins.values()],
                    "actions": [{"id": a.id, "label": a.label, "description": a.description, "fields": list(a.fields),
                                 "plugin": a.plugin} for a in plugins.actions.values()]}

    @app.put("/api/plugins/{plugin_id}")
    def toggle_plugin(plugin_id: str, body: PluginToggleIn) -> dict:
        """Turn a plugin on (its code is imported) or off."""
        try:
            info = plugins.set_enabled(plugin_id, body.enabled)
        except KeyError:
            raise HTTPException(404, "There's no plugin with that id (built-in ones are always on).") from None
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        if info.error and body.enabled:
            raise HTTPException(422, f"{info.name} couldn't load: {info.error}")
        return list_plugins()

    @app.post("/api/actions/{action_id}/run")
    def run_action(action_id: str, body: ActionRunIn) -> dict:
        """Run an action (built-in or from a plugin) on tracks. ``dry_run`` (the default) shows
        what would change; otherwise it writes, as one undoable activity entry."""
        require_library()
        if action_id not in plugins.actions:
            raise HTTPException(404, "That action isn't available (is its plugin turned on?).")
        targets = _unique(body.paths) if body.paths else (
            audio_files(library, body.folder.strip("/"), False, MAX_PATHS_PER_REQUEST) if body.folder is not None else [])
        if not targets:
            raise HTTPException(422, "Choose some tracks or a folder.")
        plan, preview, unreadable = {}, [], 0
        for rel in targets:
            try:
                tags = engine.load_metadata(library.resolve(rel)).tags
            except (MetadataError, LibraryPathError, OSError):
                unreadable += 1
                continue
            try:
                changes = plugins.run_action(action_id, tags)
            except ActionError as exc:
                raise HTTPException(422, str(exc)) from exc
            if changes:
                plan[rel] = changes
                if len(preview) < 200:
                    preview.append({"path": rel, "changes": [{"key": k, "old": "; ".join(tags.get(k, [])),
                                                              "new": "; ".join(v or [])} for k, v in changes.items()]})
        out = {"tracks": len(targets), "changing": len(plan), "unreadable": unreadable, "preview": preview}
        if body.dry_run or not plan:
            return out
        label = plugins.actions[action_id].label
        done, failed = apply_per_file(plan, f"{label}: {len(plan)} track{'s' if len(plan) != 1 else ''}")
        return {**out, "changed": len(done), "failed": len(failed), "errors": failed[:20]}

    @app.post("/api/tracks/replace")
    def replace_in_tags(body: ReplaceIn) -> dict:
        """Find & replace in the tags of many tracks (these files, or a folder's). ``dry_run`` (the
        default) only shows what would change; otherwise it writes, as one undoable activity entry."""
        require_library()
        targets = _unique(body.paths) if body.paths else (
            audio_files(library, body.folder.strip("/"), False, MAX_PATHS_PER_REQUEST) if body.folder is not None else [])
        if not targets:
            raise HTTPException(422, "Choose some tracks or a folder.")
        try:
            pattern = re.compile(body.find if body.regex else re.escape(body.find), 0 if body.match_case else re.IGNORECASE)
            if body.regex:
                pattern.sub(body.replace, "")  # a bad \1 reference fails here, not half-way through
        except re.error as exc:
            raise HTTPException(422, f"That pattern doesn't work: {exc}") from exc
        fields = [f.lower() for f in body.fields] if body.fields else list(REPLACE_FIELDS)
        swap = (lambda m: m.expand(body.replace)) if body.regex else (lambda m: body.replace)
        plan: dict[str, dict] = {}
        preview, unreadable = [], 0
        for rel in targets:
            try:
                tags = engine.load_metadata(library.resolve(rel)).tags
            except (MetadataError, LibraryPathError, OSError):
                unreadable += 1
                continue
            changes, shown = {}, []
            for key in fields:
                old = tags.get(key) or []
                new = [pattern.sub(swap, v) for v in old]
                if new != old:
                    changes[key] = [v for v in new if v.strip()] or None
                    shown.append({"key": key, "old": "; ".join(old), "new": "; ".join(v for v in new if v.strip())})
            if changes:
                plan[rel] = changes
                if len(preview) < 200:
                    preview.append({"path": rel, "changes": shown})
        out = {"tracks": len(targets), "changing": len(plan), "unreadable": unreadable, "preview": preview}
        if body.dry_run or not plan:
            return out
        what = f"“{body.find}” → “{body.replace}”" if body.replace else f"removed “{body.find}”"
        done, failed = apply_per_file(plan, f"Find & replace: {what} in {len(plan)} track{'s' if len(plan) != 1 else ''}")
        return {**out, "changed": len(done), "failed": len(failed), "errors": failed[:20]}

    @app.post("/api/folders/rename")
    def rename_folder(body: FolderRenameIn) -> dict:
        """Rename a folder (each file is moved like Organize does: nothing overwritten, one undo)."""
        require_library()
        folder = body.path.strip().strip("/")
        if not folder or folder.startswith("@"):
            raise HTTPException(422, "Choose a folder inside your music folder.")
        src = library.resolve(folder)
        if not src.is_dir():
            raise HTTPException(404, "That folder isn't there any more.")
        name = safe_name(body.name)
        parent = folder.rsplit("/", 1)[0] if "/" in folder else ""
        dest = f"{parent}/{name}" if parent else name
        if dest == folder:
            return {"path": folder, "moved": 0, "failed": 0}
        target = library.resolve(dest)
        if target.exists() and not (dest.casefold() == folder.casefold() and target.samefile(src)):
            raise HTTPException(409, f"There's already a folder called “{name}” there.")
        moves = []
        for dirpath, _, names in os.walk(src):
            for n in sorted(names):
                rel = library.relative(Path(dirpath) / n)
                moves.append(Move(rel, dest + rel[len(folder):], "move"))
        if dest.casefold() == folder.casefold():  # only the case changes: go via a temporary name
            tmp = f"{dest}.codetta-rename"
            first = apply_moves(library.resolve, [Move(m.src, tmp + m.src[len(folder):], "move") for m in moves])
            moves = [Move(tmp + m.src[len(folder):], m.dst, "move") for m in moves]
            results = apply_moves(library.resolve, moves)
            pairs = [(a, d) for r1, r2 in zip(first, results) if r1.ok and r2.ok
                     for (a, _), (_, d) in zip(r1.moved, r2.moved)]
        else:
            results = apply_moves(library.resolve, moves)
            pairs = [pair for r in results if r.ok for pair in r.moved]
        failed = [r for r in results if not r.ok]
        for dirpath, _, _ in sorted(os.walk(src), key=lambda x: -len(x[0])):  # tidy what's left (empty folders)
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
        if pairs:
            activity.add("organize", f"Renamed folder “{folder.rsplit('/', 1)[-1]}” to “{name}”", ok=not failed,
                         files=[b for _, b in pairs], changes=[{"key": "folder", "old": folder, "new": dest}],
                         errors=[{"path": r.src, "error": r.error or ""} for r in failed],
                         undo={"type": "moves", "moves": [list(p) for p in pairs]})
        lib_index.mark_dirty([p for pair in pairs for p in pair])
        art_cache.clear()
        return {"path": dest, "moved": len(pairs), "failed": len(failed)}

    # --- One file or folder at a time (the right-click / long-press menu) --------------------

    def _join(folder: str, name: str) -> str:
        return f"{folder}/{name}" if folder else name

    def _parent(rel: str) -> str:
        return rel.rsplit("/", 1)[0] if "/" in rel else ""

    def entry_moves(rel: str, new_rel: str) -> list[Move]:
        """Moves that put a file (with its .lrc) or a whole folder at ``new_rel``."""
        src = library.resolve(rel)
        if src.is_dir():
            moves = []
            for dirpath, _, names in os.walk(src):
                for n in sorted(names):
                    r = library.relative(Path(dirpath) / n)
                    moves.append(Move(r, new_rel + r[len(rel):], "move"))
            return moves
        if not src.is_file():
            raise HTTPException(404, f"“{rel.rsplit('/', 1)[-1]}” isn't there any more.")
        m = Move(rel, new_rel, "move")
        src_stem, dst_stem = os.path.splitext(rel)[0], os.path.splitext(new_rel)[0]
        for suffix in SIDECAR_SUFFIXES:  # lyrics files follow their song
            if library.resolve(src_stem + suffix).is_file() and not os.path.lexists(library.resolve(dst_stem + suffix)):
                m.companions.append((src_stem + suffix, dst_stem + suffix))
        return [m]

    def run_moves(moves: list[Move], kind: str, message: str, changes: list[dict]) -> dict:
        """Do the moves (nothing is ever overwritten), log them as one undoable entry, refresh."""
        results = apply_moves(library.resolve, moves)
        pairs = [p for r in results if r.ok for p in r.moved]
        failed = [r for r in results if not r.ok]
        if pairs:
            activity.add(kind, message, ok=not failed, files=[b for _, b in pairs], changes=changes,
                         errors=[{"path": r.src, "error": r.error or ""} for r in failed],
                         undo={"type": "moves", "moves": [list(p) for p in pairs]})
        lib_index.mark_dirty([p for pair in pairs for p in pair if not p.startswith("@")])
        art_cache.clear()
        return {"moved": len([r for r in results if r.ok]), "failed": len(failed),
                "errors": [{"path": r.src, "error": r.error or ""} for r in failed][:20]}

    def library_entries(paths: list[str]) -> list[str]:
        rels = [p.strip().strip("/") for p in _unique(paths)]
        for rel in rels:
            if not rel or rel.startswith("@"):
                raise HTTPException(422, "Choose files or folders inside your music folder.")
            library.resolve(rel)  # rejects anything outside the library
        return rels

    @app.post("/api/files/move")
    def move_entries(body: FilesMoveIn) -> dict:
        """Move files and folders into another folder (like Organize: nothing is overwritten, one undo)."""
        require_library()
        to = body.to.strip().strip("/")
        if to.startswith("@") or not library.resolve(to).is_dir():
            raise HTTPException(404, "That folder isn't there any more.")
        moves = []
        rels = library_entries(body.paths)
        for rel in rels:
            if to == rel or to.startswith(rel + "/"):
                raise HTTPException(422, "A folder can't go inside itself.")
            if _parent(rel) != to:
                moves += entry_moves(rel, _join(to, rel.rsplit("/", 1)[-1]))
        where = f"“{to.rsplit('/', 1)[-1]}”" if to else "the top of your library"
        what = f"“{rels[0].rsplit('/', 1)[-1]}”" if len(rels) == 1 else f"{len(rels)} items"
        if not moves:
            return {"moved": 0, "failed": 0, "errors": []}
        return run_moves(moves, "organize", f"Moved {what} to {where}", [{"key": "folder", "old": _parent(rels[0]), "new": to}])

    @app.post("/api/files/rename")
    def rename_entry(body: FileRenameIn) -> dict:
        """Rename one file (its extension stays; its .lrc follows). Folders use /api/folders/rename."""
        require_library()
        (rel,) = library_entries([body.path])
        src = library.resolve(rel)
        if src.is_dir():
            return rename_folder(FolderRenameIn(path=rel, name=body.name))
        ext = src.suffix
        stem = body.name.strip()
        if ext and stem.lower().endswith(ext.lower()):
            stem = stem[: -len(ext)]
        new_name = safe_name(stem) + ext
        new_rel = _join(_parent(rel), new_name)
        if new_rel == rel:
            return {"path": rel, "moved": 0, "failed": 0, "errors": []}
        target = library.resolve(new_rel)
        if os.path.lexists(target) and not (new_rel.casefold() == rel.casefold() and target.samefile(src)):
            raise HTTPException(409, f"There's already a file called “{new_name}” here.")
        out = run_moves(entry_moves(rel, new_rel), "organize", f"Renamed “{src.name}” to “{new_name}”",
                        [{"key": "name", "old": src.name, "new": new_name}])
        return {"path": new_rel if out["moved"] else rel, **out}

    @app.post("/api/files/delete")
    def delete_entries(body: FilesIn) -> dict:
        """Move files and folders to "Recently deleted" (kept 30 days in the config folder).
        Nothing is erased: Activity can put them back."""
        require_library()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        rels = library_entries(body.paths)
        moves = [m for rel in rels for m in entry_moves(rel, f"{DELETED}/{stamp}/{rel}")]
        what = f"“{rels[0].rsplit('/', 1)[-1]}”" if len(rels) == 1 else f"{len(rels)} items"
        out = run_moves(moves, "delete", f"Deleted {what} (in Recently deleted for 30 days)",
                        [{"key": "location", "old": _parent(rels[0]), "new": "(recently deleted)"}])
        for rel in rels:  # a deleted folder's empty subfolders go too
            src = library.resolve(rel)
            if src.is_dir():
                for dirpath, _, _ in sorted(os.walk(src), key=lambda x: -len(x[0])):
                    with contextlib.suppress(OSError):
                        os.rmdir(dirpath)
        return out

    @app.get("/api/files/info")
    def entry_info(path: str = Query(..., max_length=MAX_PATH_CHARS, description="File or folder, relative to the music folder")) -> dict:
        """Get info: format, quality, size and dates of a file, or what a folder holds."""
        require_library()
        target = library.resolve(path)
        info = folder_info(target) if target.is_dir() else file_info(engine, target)
        return {"path": path.strip("/"), **info}

    log_buffer = shared_buffer()

    @app.get("/api/logs")
    def server_log(after: int = Query(0, ge=0, description="Only lines after this id")) -> dict:
        """Advanced mode: Codetta's own recent log lines (memory only, the last 500), for the live view.
        No visitor records, and anything shaped like a secret is masked."""
        lines = log_buffer.since(after)
        return {"lines": lines, "last": lines[-1]["id"] if lines else after}

    @app.get("/api/tagnames")
    def tag_names(format: str = Query(..., max_length=20, description="A file format, e.g. flac, mp3, m4a")) -> dict:
        """Advanced mode: how this format stores each of Codetta's fields (None: it can't)."""
        return {"format": format, "names": native_names(format.lower(), [f.key for f in FIELDS])}

    @app.get("/api/folders")
    def list_subfolders(path: str = Query("", max_length=MAX_PATH_CHARS, description="Folder, relative to the music folder")) -> dict:
        """Just the subfolders of one folder (for the "Move to" picker): no tags are read."""
        require_library()
        if path.strip("/").startswith("@"):
            raise HTTPException(422, "Choose a folder inside your music folder.")
        listing = library.list_folder(path)
        return {"path": listing.path, "folders": [{"name": f.rsplit("/", 1)[-1], "path": f} for f in listing.folders]}

    def apply_per_file(per_file: dict[str, dict], message: str) -> tuple[list[str], list[dict]]:
        """Write different tag changes to each file (safe writes, a few at once) and log them as
        one undoable activity entry. Returns (files done, failures)."""
        undo_files: dict = {}

        def one(item):
            rel, changes = item
            try:
                target = library.resolve(rel)
                was: dict = {}
                after = engine.update_tags(target, changes, before=was).tags
                before = was["tags"]
                keys = {k.lower() for k in changes}
                diff = [k for k in keys if before.get(k, []) != after.get(k, [])]
                if diff:
                    undo_files[rel] = {"before": {k: before.get(k, []) for k in diff},
                                       "after": {k: after.get(k, []) for k in diff}}
                return rel, None
            except (MetadataError, LibraryPathError, OSError) as exc:
                return rel, str(exc)

        items = list(per_file.items())
        if len(items) > 8:
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="codetta-write") as pool:
                results = list(pool.map(one, items))
        else:
            results = [one(i) for i in items]
        done = [r for r, e in results if e is None]
        failed = [{"path": r, "error": e} for r, e in results if e is not None]
        keys = sorted({k for c in per_file.values() for k in c})
        news = {k: {str(c.get(k)) for c in per_file.values() if k in c} for k in keys}
        activity.add(
            "edit", message if not failed else f"{message.split(':')[0]}: changed {len(done)} of {len(items)} tracks",
            ok=not failed, files=done + [f["path"] for f in failed],
            changes=[{"key": k, "old": "", "new": news[k].pop() if len(news[k]) == 1 else "various"} for k in keys],
            errors=failed, undo={"type": "tags", "files": undo_files} if undo_files else None,
        )
        lib_index.mark_dirty(done)
        return done, failed

    undo_lock = threading.Lock()  # one undo at a time: a double tap can't run the same undo twice

    @app.post("/api/activity/{entry_id}/undo")
    def undo(entry_id: int) -> dict:
        """Reverse a logged change. Files edited again since are left alone."""
        require_library()
        with undo_lock:
            return undo_locked(entry_id)

    def undo_locked(entry_id: int) -> dict:
        entry = activity.get(entry_id)
        if entry is None:
            raise HTTPException(404, "That change is no longer in the activity log")
        if not entry.get("undo"):
            raise HTTPException(422, "This change can't be undone")
        if activity.is_undone(entry_id):
            raise HTTPException(409, "This change has already been undone")
        try:
            outcome = undo_change(engine, library.resolve, art_store, entry["undo"])
        except LibraryPathError as exc:  # e.g. it moved files in the inbox, and there's no inbox folder now
            raise HTTPException(409, f"This change can't be undone any more: {exc}") from exc
        lib_index.mark_dirty(r.path for r in outcome.results if r.ok)
        if entry["undo"].get("type") == "moves" and outcome.reverse:
            lib_index.mark_dirty(p for pair in outcome.reverse["moves"] for p in pair if not p.startswith("@"))
            art_cache.clear()
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

    # --- Presets --------------------------------------------------------------------

    @app.get("/api/presets", response_model=list[PresetOut])
    def list_presets():
        return [_to_preset_out(lo) for lo in store.list()]

    @app.post("/api/presets", response_model=PresetOut)
    def save_preset(body: PresetIn):
        """Create a preset, or edit one (pass ``previous_name`` when editing)."""
        preset = Preset(name=body.name, tags=body.tags, description=body.description)
        editing = body.previous_name is not None
        renamed = editing and slugify(body.previous_name) != preset.slug
        if (not editing or renamed) and _exists(store, preset.name):
            raise HTTPException(409, f"A preset named '{preset.name}' already exists")
        try:
            store.save(preset)
        except OSError as exc:
            raise HTTPException(500, f"Could not save preset: {exc}") from exc
        if renamed and _exists(store, body.previous_name):
            store.delete(body.previous_name)
        return _to_preset_out(preset)

    @app.delete("/api/presets/{name}", status_code=204)
    def delete_preset(name: str):
        store.delete(name)

    @app.post("/api/presets/apply", response_model=list[ApplyResultOut])
    def apply(body: ApplyIn):
        """Apply a preset to files or a folder. ``dry_run`` (default) only previews."""
        require_library()
        preset = store.get(body.name)
        if body.folder is not None:
            results = apply_preset_to_folder(
                engine,
                preset,
                library.resolve(body.folder),
                mode=body.mode,
                recursive=body.recursive,
                dry_run=body.dry_run,
            )
        elif body.paths:
            paths = [library.resolve(p) for p in _unique(body.paths)]
            results = apply_preset(engine, preset, paths, mode=body.mode, dry_run=body.dry_run)
        else:
            raise HTTPException(400, "Choose some files or a folder to apply the preset to")
        out = [result_out(r) for r in results]
        if not body.dry_run:
            undo_files = {
                library.relative(r.path): {"before": r.previous, "after": r.applied}
                for r in results if not r.error and r.applied
            }
            _log_preset(activity, preset.name, body.mode, out,
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
    app.add_middleware(SelectiveGZip)  # inside the guard: rejected requests never reach it
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


def _to_preset_out(lo: Preset) -> PresetOut:
    return PresetOut(name=lo.name, slug=lo.slug, description=lo.description, tags=lo.tags)


def _exists(store: PresetStore, name: str) -> bool:
    try:
        store.get(name)
        return True
    except PresetNotFoundError:
        return False
    except PresetError:
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


def _log_preset(activity: ActivityLog, name: str, mode: str, results: list[ApplyResultOut], undo: dict | None = None) -> None:
    changed = [r for r in results if not r.error and r.applied]
    failed = [r for r in results if r.error]
    keys = sorted({k for r in changed for k in r.applied})
    diff = [{"key": k, "old": "", "new": _join(changed[0].applied[k]) if len(changed) == 1 and k in changed[0].applied else "set"} for k in keys]
    how = "filled empty tags" if mode == "fill" else "overwrote tags"
    message = f"Applied preset “{name}” to {len(changed)} of {len(results)} files ({how})"
    activity.add(
        "preset", message, ok=not failed,
        files=[r.path for r in changed], changes=diff,
        errors=[{"path": r.path, "error": r.error or ""} for r in failed],
        undo=undo,
    )


def _log_musicbrainz(activity: ActivityLog, release: dict, files: list[dict], results: list[dict],
                     covers: bool, undo: dict | None) -> None:
    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    changed = {f["path"]: f["changes"] for f in files if f["path"] in {r["path"] for r in ok}}
    keys = list(dict.fromkeys(k for ch in changed.values() for k in ch))
    diff = []
    for key in keys:
        news = {_join(ch[key]["new"]) for ch in changed.values() if key in ch}
        olds = {_join(ch[key]["old"]) for ch in changed.values() if key in ch}
        diff.append({"key": key, "old": olds.pop() if len(olds) == 1 else "various",
                     "new": news.pop() if len(news) == 1 else "set per track"})
    if covers:
        diff.append({"key": "cover art", "old": "", "new": "from the Cover Art Archive"})
    detail = " · ".join(p for p in (release.get("date", "")[:4], release.get("formats"), release.get("country")) if p)
    what = f"“{release.get('title')}” by {release.get('artist')}" + (f" ({detail})" if detail else "")
    target = _name(ok[0]["path"]) if len(ok) == 1 else f"{len(ok)} tracks"
    if not ok:
        message = f"Couldn't tag from MusicBrainz: {what}"
    elif failed:
        message = f"Tagged {len(ok)} of {len(results)} tracks from MusicBrainz: {what}"
    else:
        message = f"Tagged {target} from MusicBrainz: {what}"
    activity.add(
        "musicbrainz", message, ok=not failed,
        files=[r["path"] for r in results], changes=diff if ok else [],
        errors=[{"path": r["path"], "error": r["error"] or ""} for r in failed],
        undo=undo, extra={"release": release.get("id")},
    )
