"""Shared pieces of the web app: settings, request and response models, and helpers.

Plain module-level code; the routes live in codetta.web.routes."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from codetta.core.activity import ActivityLog
from codetta.core.connections import parse_switch
from codetta.core.engine import TrackMetadata
from codetta.core.presets import Preset, PresetError, PresetNotFoundError, PresetStore
from codetta.core.updates import DEFAULT_REPO

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
    ffmpeg: str | None = None  # ffmpeg, for ReplayGain; None = look on PATH
    slskd: bool | None = None  # Soulseek through the user's slskd
    slskd_url: str | None = None  # CODETTA_SLSKD_URL / _API_KEY: set (and lock) the connection details
    slskd_api_key: str | None = None
    lidarr: bool | None = None  # keeping the user's Lidarr in step
    lidarr_url: str | None = None  # CODETTA_LIDARR_URL / _API_KEY: set (and lock) the connection details
    lidarr_api_key: str | None = None
    media_server: bool | None = None  # rescans on the user's Navidrome / Jellyfin / Emby / Plex
    media_server_env: dict | None = None  # CODETTA_MEDIA_SERVER_KIND/_URL/_USER/_PASSWORD/_TOKEN: set (and lock) details
    inbox_dir: Path | None = None  # a downloads folder outside the library (e.g. slskd's), used as "@inbox"
    inbox_settle_seconds: float = 120  # wait this long after a file changes (downloads still arriving)
    slskd_poll_seconds: float = 4  # how often a Soulseek request under way is checked on
    care_pause_seconds: float = 2  # Library care: the pause between albums (online lookups are rate limited)
    index_workers: int = 0  # processes that help a big index scan (0: one fewer than the CPUs, up to 4)
    update_repo: str = DEFAULT_REPO
    allowed_hosts: tuple[str, ...] = ()  # empty = answer to any host name
    allow_public_setup: bool = False  # first-run setup only from private addresses
    desktop_token: str | None = None  # the desktop app: its window signs in with this (fresh each launch)

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
            ffmpeg=(env("FFMPEG") or "").strip() or None,
            index_workers=int(env("INDEX_WORKERS") or 0) if (env("INDEX_WORKERS") or "0").isdigit() else 0,
            slskd=parse_switch(env("SLSKD")),
            slskd_url=(env("SLSKD_URL") or "").strip() or None,
            slskd_api_key=(env("SLSKD_API_KEY") or "").strip() or None,
            lidarr=parse_switch(env("LIDARR")),
            lidarr_url=(env("LIDARR_URL") or "").strip() or None,
            lidarr_api_key=(env("LIDARR_API_KEY") or "").strip() or None,
            media_server=parse_switch(env("MEDIA_SERVER")),
            media_server_env={"kind": env("MEDIA_SERVER_KIND"), "url": env("MEDIA_SERVER_URL"),
                              "username": env("MEDIA_SERVER_USER"), "password": env("MEDIA_SERVER_PASSWORD"),
                              "token": env("MEDIA_SERVER_TOKEN")},
            inbox_dir=Path(env("INBOX_DIR")).expanduser() if env("INBOX_DIR") else None,
            update_repo=env("UPDATE_REPO", DEFAULT_REPO),
            allowed_hosts=tuple(h.strip() for h in (env("ALLOWED_HOSTS") or "").split(",") if h.strip()),
            allow_public_setup=(env("ALLOW_PUBLIC_SETUP") or "").strip().lower() in ("on", "true", "1", "yes"),
            desktop_token=(env("DESKTOP_TOKEN") or "").strip() or None,
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
    choose: bool = True  # pick the source before anything downloads
    lossless_only: bool = False
    min_bitrate: int = Field(320, ge=0, le=3000)
    search_seconds: int = Field(20, ge=5, le=120)


class LidarrSettingsIn(BaseModel):
    url: str = Field("", max_length=500)
    api_key: str | None = Field(default=None, max_length=500)  # None: keep the saved key
    names: Literal["auto", "codetta"] = "auto"


class MediaServerSettingsIn(BaseModel):
    kind: Literal["subsonic", "jellyfin", "emby", "plex"] = "subsonic"
    url: str = Field("", max_length=500)
    username: str = Field("", max_length=200)
    password: str | None = Field(default=None, max_length=500)  # None: keep the saved one
    token: str | None = Field(default=None, max_length=500)  # None: keep the saved one


class SlskdSearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    upgrade: str = Field("", max_length=2000)  # a library folder this download should replace


class SlskdNextIn(BaseModel):
    block: bool = True  # blocklist the folder that came (else just try the next one)


class SlskdImportIn(BaseModel):
    release: str | None = Field(default=None, max_length=500)  # file with this release instead of the found one
    recordings: dict[str, list[str]] = Field(default={}, max_length=MAX_PATHS_PER_REQUEST)


REPLACE_FIELDS = ("title", "artist", "album", "albumartist", "genre", "composer", "comment", "label", "grouping")


class ReplayGainIn(BaseModel):
    paths: list[str] = Field(default=[], max_length=MAX_PATHS_PER_REQUEST)  # these files...
    folder: str | None = Field(default=None, max_length=MAX_PATH_CHARS)  # ...or this folder (and its subfolders)
    mode: Literal["album", "track"] = "album"  # album: each album folder together; track: each on its own
    dry_run: bool = True


class FromNamesIn(BaseModel):
    paths: list[str] = Field(default=[], max_length=MAX_PATHS_PER_REQUEST)  # these files...
    folder: str | None = Field(default=None, max_length=MAX_PATH_CHARS)  # ...or the audio files in this folder
    pattern: str = Field("", max_length=300)  # "": Codetta suggests one
    keep_existing: bool = True  # tags that already have a value stay as they are
    underscores: bool = False  # "_" in names means a space
    dry_run: bool = True


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
    options: dict[str, Annotated[str, Field(max_length=100)]] = Field(default={}, max_length=10)  # the action's choices
    dry_run: bool = True


class PluginToggleIn(BaseModel):
    enabled: bool


class LibraryCareIn(BaseModel):
    mode: Literal["off", "tags", "full"] | None = None
    paused: bool | None = None


class LibraryCareIgnoreIn(BaseModel):
    folder: str = Field("", max_length=MAX_PATH_CHARS)
    ignore: bool = True
    all: bool = False  # every album that needs you


class LibraryCareFolderIn(BaseModel):
    folder: str = Field(max_length=MAX_PATH_CHARS)


class ImportDoneIn(BaseModel):
    batch: str = Field(max_length=40)
    paths: list[Annotated[str, Field(max_length=MAX_PATH_CHARS)]] = Field(max_length=10_000)


class EditionPrefsIn(BaseModel):
    original_year: bool | None = None
    format: Literal["any", "digital", "cd", "vinyl"] | None = None
    country: str | None = Field(None, max_length=2)
    avoid_deluxe: bool | None = None
    store: str | None = Field(None, max_length=2)  # the iTunes store; "" = the preferred country's


class TrashIn(BaseModel):
    ids: list[Annotated[str, Field(max_length=20)]] = Field(min_length=1, max_length=500)
    confirm: int | None = None  # deleting for good: how many files you typed (must match)


class FilesIn(BaseModel):
    paths: list[Annotated[str, Field(max_length=MAX_PATH_CHARS)]] = Field(min_length=1, max_length=MAX_PATHS_PER_REQUEST)


class FilesMoveIn(FilesIn):
    to: str = Field(max_length=MAX_PATH_CHARS)  # a folder in the library ("" = the top)


class FileRenameIn(BaseModel):
    path: str = Field(min_length=1, max_length=MAX_PATH_CHARS)
    name: str = Field(min_length=1, max_length=255)


class FolderNewIn(BaseModel):
    parent: str = Field("", max_length=MAX_PATH_CHARS)  # "" = the top of the library
    name: str = Field(min_length=1, max_length=255)


class FolderRenameIn(BaseModel):
    path: str = Field(min_length=1, max_length=MAX_PATH_CHARS)
    name: str = Field(min_length=1, max_length=255)


class HealthSettingsIn(BaseModel):
    enabled: bool | None = None  # the whole feature; None: leave as is
    disabled: list[str] | None = Field(default=None, max_length=100)  # check ids switched off; None: leave as is


class HealthIgnoreAllIn(BaseModel):
    category: str = Field("all", max_length=20)


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
    # "auto": MusicBrainz first, Deezer / iTunes when it has nothing good. Or just one of those two.
    source: Literal["auto", "deezer", "itunes"] = "auto"


class MBProposalIn(MBTarget):
    release: str = Field(max_length=500)
    pairs: dict[str, str | None] = Field(default={}, max_length=MAX_PATHS_PER_REQUEST)  # path -> track id (None: skip)
    fields: list[str] | None = Field(default=None, max_length=200)  # None: the default set
    # From Identify by sound: recording IDs heard in each file (pairs files exactly).
    recordings: dict[str, list[str]] = Field(default={}, max_length=MAX_PATHS_PER_REQUEST)
    mode: Literal["overwrite", "fill"] = "overwrite"  # fill: only tags that are empty now
    cover: Literal["missing", "all", "none"] = "missing"


# --- App ----------------------------------------------------------------------------


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
