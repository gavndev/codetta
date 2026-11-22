"""Library health: one list of things worth fixing across the whole library.

Everything comes from the search index (no music file is opened), so a check of
thousands of albums takes a fraction of a second. An *album* is a folder of
audio files; disc folders ("CD1", "Disc 2") join their parent.

Each check has an id and a category, and the user can switch any of them off.
Where the fix is obvious (e.g. "use 'Kehlani' as the album artist on all 17
tracks") an issue carries it: a set of tag changes for some files, applied
through the normal save path (safe writes, activity log, undo). Everything else
points at the right tool (the album itself, Find in MusicBrainz, Find in slskd).

Settings (switched-off checks, ignored issues) live in ``health.json``.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import tempfile
import threading
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from codetta.core.inbox import DISC_FOLDER

CATEGORIES = {
    "splits": "Shows up split in your player",
    "tracks": "Tracks",
    "covers": "Covers",
    "tags": "Tags & files",
}


@dataclass(frozen=True)
class Check:
    id: str
    category: str
    label: str
    about: str


CHECKS: tuple[Check, ...] = (
    Check("split_album", "splits", "Album name differs",
          "Tracks in one folder spell the album differently, so players show two albums."),
    Check("split_albumartist", "splits", "Album artist differs",
          "Tracks in one folder have different album artists, so players split the album."),
    Check("no_albumartist", "splits", "No album artist",
          "Tracks have different artists (often features) and no album artist to hold them together."),
    Check("split_year", "splits", "Year differs",
          "Tracks in one album have different years, which some players treat as different releases."),
    Check("track_gaps", "tracks", "Missing tracks",
          "Gaps in the track numbers (1, 2, 4), or fewer tracks than the album says it has."),
    Check("track_dupes", "tracks", "Same track number twice",
          "Two tracks on the same disc share a track number."),
    Check("disc_numbers", "tracks", "Disc numbers missing",
          "A multi-disc album where some tracks have no disc number."),
    Check("no_cover", "covers", "No cover",
          "No embedded cover and no cover image in the folder."),
    Check("small_cover", "covers", "Small cover",
          "The only cover is smaller than 500 pixels, which looks blurry on big screens."),
    Check("missing_tags", "tags", "Missing basic tags",
          "Tracks without a title, artist, album or track number."),
    Check("duplicate_album", "tags", "Album in two folders",
          "The same album (same album artist and name) lives in more than one folder."),
    Check("duplicate_track", "tags", "Same song twice",
          "The same title appears twice on one disc of an album (often an MP3 next to a FLAC)."),
    Check("unreadable", "tags", "Unreadable files",
          "Audio files Codetta couldn't read (damaged, or not what their name says)."),
    Check("mixed_quality", "tags", "Mixed quality",
          "An album that mixes lossless files (FLAC, ALAC...) with lossy ones (MP3, AAC...)."),
)
BY_ID = {c.id: c for c in CHECKS}

LOSSLESS = {"flac", "wav", "aiff", "aif", "ape", "wv", "wavpack", "dsf", "dff", "tta", "alac", "oggflac"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
SMALL_COVER = 500
MB_RELEASE_KEYS = ("musicbrainz_albumid", "musicbrainz album id")
MAX_PATHS = 1000
MAX_DETAIL = 12

_FEAT = re.compile(r"\s+(?:feat\.?|ft\.?|featuring|with|x|&|,|/|;|\+|vs\.?)\s+|\s*[,;/]\s*", re.IGNORECASE)
EDITION_RE = re.compile(r"\s*[\(\[][^)\]]*(?:deluxe|edition|remaster|version|expanded|bonus|explicit|clean)[^)\]]*[\)\]]", re.IGNORECASE)
_LEADING_NUMBER = re.compile(r"^\s*(?:(\d{1,2})[-.])?(\d{1,3})(?=[\s._-])")


_NON_WORD = re.compile(r"[^\w]+")


@functools.lru_cache(maxsize=65536)  # the same album and artist names come up track after track
def fold(text: str) -> str:
    """Compare form: no accents, case, or punctuation differences."""
    if not text.isascii():
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(_NON_WORD.sub(" ", text.casefold()).split())


def _first(tags: dict, key: str) -> str:
    v = tags.get(key)
    if v.__class__ is str:  # already reduced to its first value (see _slim)
        return v
    for x in v or []:
        if isinstance(x, str) and x.strip():
            return x.strip()
    return ""


_NUM = re.compile(r"^\s*(\d+)")
_TOTAL = re.compile(r"^\s*\d*\s*/\s*(\d+)")


def _num(value: str) -> int | None:
    m = _NUM.match(value or "")
    return int(m.group(1)) if m else None


def _total(value: str) -> int | None:
    m = _TOTAL.match(value or "")
    return int(m.group(1)) if m else None


def _base_artist(artist: str) -> str:
    """ "Kehlani feat. Zayn" -> "Kehlani"."""
    return _FEAT.split(artist, 1)[0].strip() if artist else ""


def _lossless(track: dict) -> bool:
    fmt = (track.get("format") or "").lower()
    if fmt in ("m4a", "mp4", "m4b"):  # ALAC or AAC: tell them apart by bitrate
        return (track.get("bitrate") or 0) >= 500_000
    return fmt in LOSSLESS


def issue_id(check: str, folder: str) -> str:
    return hashlib.sha1(f"{check}\0{folder}".encode(), usedforsecurity=False).hexdigest()[:12]  # an id, not a secret


@dataclass
class Album:
    folder: str
    tracks: list[tuple[str, dict]] = field(default_factory=list)  # (path, track details)

    def values(self, key: str) -> list[str]:
        cache = self.__dict__.setdefault("_values", {})
        if key not in cache:
            cache[key] = [_first(t.get("tags") or {}, key) for _, t in self.tracks]
        return cache[key]

    def common(self, key: str) -> str:
        """The most common non-empty value (ties: the first one seen)."""
        vals = [v for v in self.values(key) if v]
        return Counter(vals).most_common(1)[0][0] if vals else ""

    @functools.cached_property
    def is_album(self) -> bool:
        """Most tracks agree on the album name (a "Singles" folder doesn't)."""
        names = [fold(v) for v in self.values("album") if v]
        if not names:
            return False
        return Counter(names).most_common(1)[0][1] >= 0.6 * len(self.tracks)

    def disc_of(self, path: str, track: dict) -> int:
        d = _num(_first(track.get("tags") or {}, "discnumber"))
        if d:
            return d
        sub = path[len(self.folder) + 1:].split("/")[0] if path.startswith(self.folder + "/") else ""
        m = re.search(r"(\d+)", sub) if DISC_FOLDER.match(sub or "") else None
        return int(m.group(1)) if m else 1


def group_albums(tracks: Iterable[tuple[str, dict]], skip: Iterable[str] = ()) -> dict[str, Album]:
    skip = tuple(s.rstrip("/") + "/" for s in skip if s)
    albums: dict[str, Album] = {}
    for path, track in tracks:
        if path.startswith("@") or (skip and path.startswith(skip)):
            continue
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        name = folder.rsplit("/", 1)[-1]
        if folder and "/" in folder and DISC_FOLDER.match(name):
            folder = folder.rsplit("/", 1)[0]
        albums.setdefault(folder, Album(folder)).tracks.append((path, track))
    return albums


def _issue(check: str, album: Album, message: str, paths: list[str], detail: list[str] | None = None,
           fix: dict | None = None, actions: tuple[str, ...] = ()) -> dict:
    # ``paths`` isn't kept: nothing needs the file list once the issue is found, and on a
    # library of thousands of albums those lists were most of the memory health used.
    return {
        "id": issue_id(check, album.folder), "check": check, "category": BY_ID[check].category,
        "folder": album.folder, "album": album.common("album") or album.folder.rsplit("/", 1)[-1] or "Library",
        "artist": album.common("albumartist") or album.common("artist"),
        "tracks": len(album.tracks), "message": message, "detail": (detail or [])[:MAX_DETAIL],
        "more": max(0, len(detail or []) - MAX_DETAIL), "fix": fix, "actions": list(actions),
    }


def _set_fix(album: Album, key: str, value: str, label: str, extra: dict | None = None) -> dict | None:
    """Set ``key`` to ``value`` on every track that has something else."""
    paths = [p for p, t in album.tracks if _first(t.get("tags") or {}, key) != value][:MAX_PATHS]
    if not paths or not value:
        return None
    return {"label": label, "per_file": {p: {key: value, **(extra or {})} for p in paths},
            "summary": f"Set {key.replace('albumartist', 'album artist').replace('date', 'year')} to “{value}” on "
                       f"{len(paths)} track{'s' if len(paths) != 1 else ''}"}


def _differs(album: Album, key: str) -> list[str]:
    """``key``'s distinct values (as spelled), if the tracks disagree once case and punctuation are ignored."""
    seen: dict[str, str] = {}
    for v in album.values(key):
        if v:
            seen.setdefault(fold(v) if key != "date" else v[:4], v)
    return list(seen.values()) if len(seen) > 1 else []


def check_album(album: Album, has_folder_image: Callable[[str], bool]) -> list[dict]:
    out: list[dict] = []
    tracks = album.tracks
    paths = [p for p, _ in tracks]
    is_album = album.is_album

    # --- Shows up split in your player ---
    if is_album:
        names = _differs(album, "album")
        if names:
            best = album.common("album")
            out.append(_issue("split_album", album, f"{len(names)} spellings of the album name",
                              paths, [f"“{n}”" for n in names],
                              _set_fix(album, "album", best, f"Use “{best}”")))
        aas = _differs(album, "albumartist")
        if aas:
            best = album.common("albumartist")
            out.append(_issue("split_albumartist", album, f"{len(aas)} different album artists",
                              paths, [f"“{a}”" for a in aas],
                              _set_fix(album, "albumartist", best, f"Use “{best}”")))
        elif not any(album.values("albumartist")):
            artists = [a for a in album.values("artist") if a]
            if len({fold(a) for a in artists}) > 1:
                bases = Counter(_base_artist(a) for a in artists)
                base, n = bases.most_common(1)[0]
                if n >= 0.6 * len(tracks) and base:
                    fix = _set_fix(album, "albumartist", base, f"Use “{base}”")
                else:
                    fix = _set_fix(album, "albumartist", "Various Artists", "Use “Various Artists”", {"compilation": "1"})
                out.append(_issue("no_albumartist", album, f"{len(set(artists))} artists and no album artist",
                                  paths, [f"“{a}”" for a in dict.fromkeys(artists)], fix))
        years = _differs(album, "date")
        if years:
            best = album.common("date")
            out.append(_issue("split_year", album, f"{len(years)} different years", paths,
                              sorted(years), _set_fix(album, "date", best, f"Use {best}")))

    # --- Tracks ---
    if is_album and len(tracks) >= 2:
        discs: dict[int, list[tuple[str, dict]]] = {}
        for p, t in tracks:
            discs.setdefault(album.disc_of(p, t), []).append((p, t))
        missing, dupes = [], []
        first_disc = min(discs)
        for disc, items in sorted(discs.items()):
            label = f"Disc {disc}, track " if len(discs) > 1 else "Track "
            nums = Counter()
            total = 0
            for _, t in items:
                tn = _first(t.get("tags") or {}, "tracknumber")
                n = _num(tn)
                if n:
                    nums[n] += 1
                total = max(total, _total(tn) or 0,
                            _num(_first(t.get("tags") or {}, "tracktotal")) or 0,
                            _num(_first(t.get("tags") or {}, "totaltracks")) or 0)
            if not nums:
                continue
            # Later discs may carry on the numbering (disc 2 starting at 17): count from where they start.
            start = 1 if disc == first_disc else min(nums)
            # A track total on a multi-disc album often counts every disc, so there only gaps count.
            # A single disc trusts its total when it's plausible (not, say, 30 for 15 tracks).
            plausible = len(discs) == 1 and total - len(items) <= max(3, len(items) // 2)
            last = max(total, max(nums)) if plausible else max(nums)
            if any(c > 1 for c in nums.values()) and len(nums) <= len(items) // 2:
                last = max(nums)  # numbering is broken (every track "1"): that's the duplicate check's job
            missing += [f"{label}{n}" for n in range(start, last + 1) if n not in nums]
            dupes += [f"{label}{n} ({c}×)" for n, c in sorted(nums.items()) if c > 1]
        if missing:
            out.append(_issue("track_gaps", album, f"{len(missing)} track{'s' if len(missing) != 1 else ''} missing",
                              paths, missing, None, ("open", "slskd")))
        if dupes:
            out.append(_issue("track_dupes", album, "The same track number twice", paths, dupes))
        disc_vals = [_num(v) for v in album.values("discnumber")]
        has_disc_folders = any(album.disc_of(p, {"tags": {}}) > 1 for p in paths)
        lacking = [p for p, t in tracks if not _num(_first(t.get("tags") or {}, "discnumber"))]
        if lacking and (any(d and d > 1 for d in disc_vals) or has_disc_folders):
            fix = None
            if all(p.rsplit("/", 1)[0] != album.folder for p in lacking):
                # Every track without one sits in a "CD2"-style folder: number them from it.
                fix = {"label": "Number from disc folders",
                       "per_file": {p: {"discnumber": str(album.disc_of(p, {"tags": {}}))} for p in lacking},
                       "summary": f"Set the disc number from its folder (“CD2” → 2) on {len(lacking)} track{'s' if len(lacking) != 1 else ''}"}
            out.append(_issue("disc_numbers", album, f"{len(lacking)} track{'s' if len(lacking) != 1 else ''} without a disc number",
                              lacking, [p.rsplit("/", 1)[-1] for p in lacking], fix))

    # --- Covers ---
    arts = [t.get("art") for _, t in tracks if t.get("art")]
    if not has_folder_image(album.folder):
        if not arts:
            out.append(_issue("no_cover", album, "No cover", paths, None, None, ("open", "musicbrainz")))
        else:
            biggest = max(max(a.get("width") or 0, a.get("height") or 0) for a in arts)
            if 0 < biggest < SMALL_COVER:
                out.append(_issue("small_cover", album, f"Cover is only {biggest} px", paths, None, None,
                                  ("open", "musicbrainz")))

    # --- Tags & files ---
    needs = {"title": "title", "artist": "artist", "album": "album", "tracknumber": "track number"}
    gaps: dict[str, list[str]] = {}
    for p, t in tracks:
        if t.get("error"):
            continue
        tags = t.get("tags") or {}
        for key, name in needs.items():
            if not _first(tags, key):
                gaps.setdefault(name, []).append(p)
    if gaps:
        affected = sorted({p for ps in gaps.values() for p in ps})
        fix = None
        no_number = gaps.get("track number", [])
        if no_number and len(gaps) == 1:
            numbered = {p: _LEADING_NUMBER.match(p.rsplit("/", 1)[-1]) for p in no_number}
            if all(numbered.values()):
                fix = {"label": "Number from file names", "per_file": {p: {"tracknumber": str(int(m.group(2)))}
                                                                       for p, m in numbered.items()},
                       "summary": f"Take the track number from the file name on {len(no_number)} track{'s' if len(no_number) != 1 else ''} (“01 Title.flac” → 1)"}
        out.append(_issue("missing_tags", album,
                          "; ".join(f"{len(ps)} without {name}" for name, ps in gaps.items()),
                          affected, [p.rsplit("/", 1)[-1] for p in affected], fix))

    if is_album:
        by_title: dict[tuple[int, str], list[tuple[str, float]]] = {}
        for p, t in tracks:
            title = _first(t.get("tags") or {}, "title")
            if title:
                by_title.setdefault((album.disc_of(p, t), fold(title)), []).append((p, t.get("duration") or 0))
        doubles = []
        for items in by_title.values():
            # The same recording twice (an MP3 next to the FLAC) is the same length; remixes and
            # versions sharing a title aren't.
            items.sort(key=lambda x: x[1])
            same = [items[i] for i in range(len(items))
                    if any(j != i and abs(items[i][1] - items[j][1]) <= 2 for j in range(len(items)))]
            if len(same) > 1:
                doubles.append([p for p, _ in same])
        if doubles:
            out.append(_issue("duplicate_track", album, f"{len(doubles)} song{'s' if len(doubles) != 1 else ''} twice",
                              [p for ps in doubles for p in ps],
                              [" = ".join(p.rsplit("/", 1)[-1] for p in ps) for ps in doubles]))

    broken = [p for p, t in tracks if t.get("error")]
    if broken:
        out.append(_issue("unreadable", album, f"{len(broken)} file{'s' if len(broken) != 1 else ''} can't be read",
                          broken, [p.rsplit("/", 1)[-1] for p in broken]))

    readable = [(p, t) for p, t in tracks if not t.get("error")]
    kinds = {_lossless(t) for _, t in readable}
    if len(kinds) == 2:
        lossy = [p for p, t in readable if not _lossless(t)]
        out.append(_issue("mixed_quality", album, f"{len(lossy)} lossy track{'s' if len(lossy) != 1 else ''} in a lossless album"
                          if len(lossy) < len(readable) / 2 else "Lossless and lossy tracks mixed",
                          lossy, [p.rsplit("/", 1)[-1] for p in lossy], None, ("open", "slskd")))
    return out


def duplicate_albums(albums: dict[str, Album]) -> list[dict]:
    keyed: dict[tuple[str, str], list[Album]] = {}
    for a in albums.values():
        if a.is_album:
            key = _album_key(a)
            if key:
                keyed.setdefault(key, []).append(a)
    return [_duplicate_issue(group) for group in keyed.values() if len(group) > 1]


def _album_key(a: Album) -> tuple[str, str] | None:
    name = fold(a.common("album"))
    return (fold(a.common("albumartist") or _base_artist(a.common("artist"))), name) if name else None


def _duplicate_issue(group: list[Album]) -> dict:
    first, *rest = sorted(group, key=lambda a: a.folder)
    issue = _issue("duplicate_album", first, f"Also in {len(rest)} other folder{'s' if len(rest) != 1 else ''}",
                   [], [a.folder for a in group], None, ("open",))
    issue["folders"] = [a.folder for a in sorted(group, key=lambda a: a.folder)]
    return issue


# Only what the checks read is kept per track while an album is being checked.
_KEEP_TAGS = ("album", "albumartist", "artist", "title", "tracknumber", "discnumber", "date", "tracktotal", "totaltracks")


def _slim(track: dict) -> dict:
    tags = track.get("tags") or {}
    kept = {}
    for k in _KEEP_TAGS:
        first = _first(tags, k) if tags.get(k) else ""
        if first:
            kept[k] = first  # the first value is all the checks read: keep just that
    return {"tags": kept, "art": track.get("art"), "error": track.get("error"),
            "format": track.get("format"), "bitrate": track.get("bitrate"), "duration": track.get("duration")}


def _album_folder(path: str) -> str:
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    name = folder.rsplit("/", 1)[-1]
    if folder and "/" in folder and DISC_FOLDER.match(name):
        folder = folder.rsplit("/", 1)[0]
    return folder


def run(tracks: Iterable[tuple[str, dict]], has_folder_image: Callable[[str], bool],
        matched_paths: set[str] = frozenset(), skip: Iterable[str] = ()) -> dict:
    """Every issue (whatever the settings), plus a few numbers.

    Streams: ``tracks`` in path order (as the index gives them) is checked one album at a
    time, so a library of 100,000 tracks never sits in memory at once. A list is sorted first."""
    if isinstance(tracks, list):
        tracks = sorted(tracks, key=lambda x: x[0])
    skip = tuple(s.rstrip("/") + "/" for s in skip if s)
    issues: list[dict] = []
    open_albums: dict[str, Album] = {}  # albums whose files may still come (nested folders interleave)
    dupes: dict[tuple[str, str], list[Album]] = {}
    stats = {"albums": 0, "folders": 0, "tracks": 0, "unmatched": 0}

    def finish(album: Album) -> None:
        stats["folders"] += 1
        issues.extend(check_album(album, has_folder_image))
        if album.is_album:
            stats["albums"] += 1
            if not any(p in matched_paths for p, _ in album.tracks):
                stats["unmatched"] += 1
            key = _album_key(album)
            if key:  # keep a light copy (names only) for the duplicate check at the end
                light = Album(album.folder, [(p, {"tags": {k: t["tags"].get(k, "") for k in ("album", "albumartist", "artist")}})
                                             for p, t in album.tracks[:3]])
                dupes.setdefault(key, []).append(light)

    for path, track in tracks:
        if path.startswith("@") or (skip and path.startswith(skip)):
            continue
        stats["tracks"] += 1
        folder = _album_folder(path)
        for key in [k for k in open_albums if k and k != folder and not path.startswith(k + "/")]:
            finish(open_albums.pop(key))  # sorted input: this album's files are all behind us
        open_albums.setdefault(folder, Album(folder)).tracks.append((path, _slim(track)))
    for album in open_albums.values():
        finish(album)
    issues.extend(_duplicate_issue(g) for g in dupes.values() if len(g) > 1)
    order = list(CATEGORIES)
    issues.sort(key=lambda i: (order.index(i["category"]), i["folder"].casefold(), i["check"]))
    return {**stats, "issues": issues}


def folder_has_image(root: Callable[[str], Path]) -> Callable[[str], bool]:
    """A cover file (cover.jpg, folder.png, front.webp...) in the album folder or a disc folder."""
    def check(folder: str) -> bool:
        try:
            top = root(folder)
            with os.scandir(top) as entries:
                subs = []
                for e in entries:
                    if e.is_file() and Path(e.name).suffix.lower() in IMAGE_EXT and not e.name.startswith("."):
                        return True
                    if e.is_dir() and DISC_FOLDER.match(e.name):
                        subs.append(e.path)
            for s in subs:
                with os.scandir(s) as entries:
                    if any(e.is_file() and Path(e.name).suffix.lower() in IMAGE_EXT for e in entries):
                        return True
        except OSError:
            pass
        return False
    return check


class HealthStore:
    """Switched-off checks and ignored issues, saved to health.json."""

    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        self.enabled = True  # the whole feature (off: no card, nothing is checked)
        self.disabled: set[str] = set()
        self.ignored: set[str] = set()
        try:
            data = json.loads(file.read_text("utf-8"))
            if isinstance(data, dict):
                self.enabled = data.get("enabled") is not False
                self.disabled = {c for c in data.get("disabled") or [] if c in BY_ID}
                self.ignored = {i for i in data.get("ignored") or [] if isinstance(i, str)}
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        with self.lock:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".health-", dir=self.file.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"enabled": self.enabled, "disabled": sorted(self.disabled),
                               "ignored": sorted(self.ignored)}, f)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
