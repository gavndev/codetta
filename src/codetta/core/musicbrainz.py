"""MusicBrainz: match an album folder to a release and propose its tags.

Like every provider this only *suggests*: it turns a MusicBrainz release into
"these files should get these values", and the web layer shows that as a
preview and writes it through ``MetadataEngine.update_tags()`` when asked.

The unit is the album: one folder of files <-> one MusicBrainz *release*
(a specific edition: "the 2011 UK CD"). Files are paired with the release's
tracks by disc and track number, then by title and length for the rest.

Tag names and values follow MusicBrainz Picard, which is what Navidrome and
most players expect (``musicbrainz_albumid``, ``releasetype`` = ``album``...).

MusicBrainz asks for at most one request per second and a User-Agent that
names the app; both are handled here. Cover art comes from the Cover Art
Archive. Data is CC0, so there are no licensing strings attached.
"""

from __future__ import annotations

import difflib
import re
import threading
import time
import unicodedata
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from codetta.core.providers import ProviderError

MB_BASE = "https://musicbrainz.org/ws/2"
CAA_BASE = "https://coverartarchive.org"
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"
MAX_MB_BYTES = 8 * 1024 * 1024  # a big box set with full credits is a few MB
MAX_VALUE_CHARS = 2000

_MBID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
MBID_RE = re.compile(f"^{_MBID}$")

# Everything the review screen needs about a release, in one request.
RELEASE_INC = "+".join((
    "artist-credits", "labels", "recordings", "release-groups", "media", "isrcs", "genres",
    "artist-rels", "recording-level-rels", "work-rels", "work-level-rels",
))

# MusicBrainz relationship type -> Codetta tag (as Picard maps them).
CREDIT_TYPES = {
    "producer": "producer",
    "engineer": "engineer", "audio": "engineer", "recording": "engineer", "sound": "engineer",
    "mix": "mixer",
    "mix-DJ": "djmixer",
    "remixer": "remixer",
    "arranger": "arranger", "orchestrator": "arranger", "instrument arranger": "arranger",
    "vocal arranger": "arranger", "instrumentator": "arranger",
    "conductor": "conductor", "chorus master": "conductor",
    "composer": "composer",
    "lyricist": "lyricist", "librettist": "lyricist",
}

# How the review screen groups the fields. Genre is opinionated (community
# tags), so it starts unticked.
FIELD_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("basics", "Titles & numbering", ("title", "artist", "album", "albumartist", "tracknumber", "discnumber", "date")),
    ("credits", "Credits", ("artists", "albumartists", "composer", "lyricist", "producer", "engineer",
                            "mixer", "djmixer", "remixer", "arranger", "conductor")),
    ("release", "Release details", ("originaldate", "releasetype", "releasestatus", "releasecountry", "label",
                                    "catalognumber", "barcode", "media", "discsubtitle", "compilation", "script")),
    ("sorting", "Sort names", ("artistsort", "albumartistsort")),
    ("ids", "MusicBrainz IDs & ISRC", ("musicbrainz_albumid", "musicbrainz_releasegroupid", "musicbrainz_trackid",
                                       "musicbrainz_releasetrackid", "musicbrainz_artistid",
                                       "musicbrainz_albumartistid", "musicbrainz_workid", "isrc")),
    ("genre", "Genre (community tags)", ("genre",)),
)
DEFAULT_OFF = frozenset({"genre"})
# Labels for fields the editor doesn't list (the rest come from tagmap.FIELDS).
ID_LABELS = {
    "musicbrainz_albumid": "Release ID",
    "musicbrainz_releasegroupid": "Release group ID",
    "musicbrainz_trackid": "Recording ID",
    "musicbrainz_releasetrackid": "Track ID",
    "musicbrainz_artistid": "Artist IDs",
    "musicbrainz_albumartistid": "Album artist IDs",
    "musicbrainz_workid": "Work ID",
    "script": "Script",
}
ALL_FIELDS = tuple(k for _, _, keys in FIELD_GROUPS for k in keys)


def default_fields() -> list[str]:
    return [k for k in ALL_FIELDS if k not in DEFAULT_OFF]


def parse_release_id(text: str) -> str | None:
    """A release MBID from a bare ID or a musicbrainz.org/release/<id> link."""
    text = (text or "").strip().lower()
    if MBID_RE.match(text):
        return text
    m = re.search(rf"musicbrainz\.org/(?:[a-z-]+/)?release/({_MBID})", text)
    return m.group(1) if m else None


# --- Text helpers ---------------------------------------------------------------------


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("&", " and ")
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def similarity(a: str, b: str) -> float:
    """0..1, forgiving of case, accents, punctuation and "(Deluxe)" style extras."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if f" {a} " in f" {b} " or f" {b} " in f" {a} ":
        ratio = max(ratio, 0.85)
    return ratio


# Junk that downloads (YouTube rips especially) add to song titles.
_JUNK = re.compile(
    r"\s*[(\[]\s*(?:official\b[^)\]]*|(?:with\s+)?lyrics?\b[^)\]]*|lyric video|visuali[sz]er|audio|video|music video|"
    r"hd|hq|4k|explicit|clean|dirty|mv|m/v|remaster(?:ed)?\b[^)\]]*|\d{4}\s+remaster(?:ed)?[^)\]]*|"
    r"from [^)\]]*|prod\.?\s[^)\]]*)\s*[)\]]", re.IGNORECASE)
_FEAT = re.compile(r"\s*[(\[]?\s*\b(?:ft|feat|featuring)\b\.?\s+[^)\]]*[)\]]?", re.IGNORECASE)
_SPLIT_ARTIST = re.compile(r"\s+(?:ft|feat|featuring)\b\.?\s+|\s+x\s+|\s*,\s*", re.IGNORECASE)


def clean_title(title: str) -> str:
    """"Frontin ft. Jay-Z (Official Audio)" -> "Frontin"; "Dreams (Remastered) (Official Video)" -> "Dreams"."""
    prev = None
    while prev != title:
        prev, title = title, _JUNK.sub("", title)
    title = _FEAT.sub("", title)
    return " ".join(title.split()).strip(" -_")


def clean_artist(artist: str) -> str:
    """The main artist: "Pharrell ft. Jay-Z" -> "Pharrell"; "Bjork, Someone" -> "Bjork"."""
    return _SPLIT_ARTIST.split(artist.strip(), maxsplit=1)[0].strip()


def song_from_name(filename: str) -> tuple[str, str]:
    """A song's (title, artist) from a file name like "Artist - Title (Official Video).mp3"."""
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", filename.rsplit("/", 1)[-1])
    stem = re.sub(r"^\d{1,3}\s*[-._]\s*", "", stem)  # "04 - ", "04. "
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return clean_title(title), clean_artist(artist)
    return "", ""


def _lucene(text: str) -> str:
    """Escape a value for MusicBrainz's search syntax."""
    return re.sub(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)', r"\\\1", " ".join(text.split()))


def _clip(value: str) -> str:
    return value[:MAX_VALUE_CHARS]


def _unique(values) -> list[str]:
    return list(dict.fromkeys(_clip(v) for v in values if isinstance(v, str) and v.strip()))


def credit_string(credits: list | None, sort: bool = False) -> str:
    out = []
    for c in credits or []:
        if not isinstance(c, dict):
            continue
        artist = c.get("artist") or {}
        name = (artist.get("sort-name") if sort else None) or c.get("name") or artist.get("name") or ""
        out.append(f"{name}{c.get('joinphrase') or ''}")
    return _clip("".join(out).strip())


def credit_names(credits: list | None) -> list[str]:
    return _unique(c.get("name") or (c.get("artist") or {}).get("name") for c in credits or [] if isinstance(c, dict))


def credit_ids(credits: list | None) -> list[str]:
    ids = ((c.get("artist") or {}).get("id") for c in credits or [] if isinstance(c, dict))
    return _unique(i for i in ids if isinstance(i, str) and MBID_RE.match(i))


# --- The client -------------------------------------------------------------------------

Fetcher = Callable[[str], object]  # url -> parsed JSON, or None for 404
RETRY_WAITS = (2.0, 4.0)  # seconds before the 2nd and 3rd try when MusicBrainz is busy or slow
MAX_RETRY_WAIT = 15.0  # never wait longer than this for one "Retry-After"
MB_TIMEOUT = 20  # big releases with credits can take MusicBrainz well over 8 seconds


class MusicBrainz:
    def __init__(self, fetch: Fetcher, base: str = MB_BASE, min_interval: float = 1.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.fetch = fetch
        self.base = base.rstrip("/")
        self.min_interval = min_interval
        self._clock, self._sleep = clock, sleep
        self._rate_lock = threading.Lock()
        self._last = -1e9
        self._cache: OrderedDict[str, object] = OrderedDict()
        self._cache_lock = threading.Lock()

    def _get(self, path: str, params: dict[str, str]) -> object:
        url = f"{self.base}/{path}?{urllib.parse.urlencode({**params, 'fmt': 'json'})}"
        with self._cache_lock:
            if url in self._cache:
                self._cache.move_to_end(url)
                return self._cache[url]
        with self._rate_lock:  # one request at a time, at most one per min_interval
            for attempt in range(1, len(RETRY_WAITS) + 2):
                wait = self._last + self.min_interval - self._clock()
                if wait > 0:
                    self._sleep(wait)
                try:
                    data = self.fetch(url)
                    break
                except ProviderError as exc:
                    # Busy (503/429), timed out or dropped: MusicBrainz is often briefly overloaded.
                    # Back off (as long as it asks, within reason) and try again, a few times.
                    if not getattr(exc, "transient", False) or attempt > len(RETRY_WAITS):
                        raise
                    asked = getattr(exc, "retry_after", None)
                    self._sleep(min(MAX_RETRY_WAIT, asked) if asked else RETRY_WAITS[attempt - 1])
                finally:
                    self._last = self._clock()
        with self._cache_lock:
            self._cache[url] = data
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
        return data

    def search(self, album: str, artist: str = "", limit: int = 10) -> list[dict]:
        album, artist = album.strip(), artist.strip()
        if not album and not artist:
            raise ProviderError("Type an album or artist to search for.")
        parts = []
        if album:
            parts.append(f"release:({_lucene(album)})")
        if artist:
            parts.append(f"artist:({_lucene(artist)})")
        data = self._get("release", {"query": " AND ".join(parts), "limit": str(limit)})
        releases = data.get("releases") if isinstance(data, dict) else None
        return [r for r in releases or [] if isinstance(r, dict) and MBID_RE.match(str(r.get("id", "")))]

    def search_recordings(self, title: str, artist: str = "", limit: int = 25) -> list[dict]:
        """Songs (recordings) by title and artist, each with the releases it's on."""
        title, artist = title.strip(), artist.strip()
        if not title:
            return []
        who = f" AND artist:({_lucene(artist)})" if artist else ""
        # Two searches: a popular song's studio version is often buried under live and bootleg
        # recordings, so the second asks for official albums only. Merged, album ones first.
        queries = [f'recording:"{_lucene(title)}"{who} AND status:official AND primarytype:album',
                   f"recording:({_lucene(title)}){who}"]
        out, seen = [], set()
        for q in queries:
            data = self._get("recording", {"query": q, "limit": str(limit)})
            for r in (data.get("recordings") if isinstance(data, dict) else None) or []:
                if isinstance(r, dict) and MBID_RE.match(str(r.get("id", ""))) and r["id"] not in seen:
                    seen.add(r["id"])
                    out.append(r)
        return out

    def releases_by_id(self, ids: list[str]) -> list[dict]:
        """Search-result summaries for up to 25 known releases, in one request."""
        ids = [i for i in ids if MBID_RE.match(i)][:25]
        if not ids:
            return []
        data = self._get("release", {"query": " OR ".join(f"reid:{i}" for i in ids), "limit": str(len(ids))})
        releases = data.get("releases") if isinstance(data, dict) else None
        return [r for r in releases or [] if isinstance(r, dict) and r.get("id") in ids]

    def release(self, mbid: str) -> dict:
        if not MBID_RE.match(mbid or ""):
            raise ProviderError("That isn't a MusicBrainz release ID.")
        data = self._get(f"release/{mbid}", {"inc": RELEASE_INC})
        if data is None:
            raise ProviderError("MusicBrainz doesn't have that release (it may have been merged or removed).")
        if not isinstance(data, dict) or not isinstance(data.get("media"), list):
            raise ProviderError("MusicBrainz sent a release Codetta couldn't read.")
        return data


    # --- Exploring (the !mb bang): artists and their releases, not tied to any files ---

    def search_artists(self, text: str, limit: int = 8) -> list[dict]:
        data = self._get("artist", {"query": _lucene(text), "limit": str(limit)})
        items = data.get("artists") if isinstance(data, dict) else None
        return [a for a in items or [] if isinstance(a, dict) and MBID_RE.match(str(a.get("id", "")))]

    def search_release_groups(self, text: str, limit: int = 15) -> list[dict]:
        data = self._get("release-group", {"query": _lucene(text), "limit": str(limit)})
        items = data.get("release-groups") if isinstance(data, dict) else None
        return [g for g in items or [] if isinstance(g, dict) and MBID_RE.match(str(g.get("id", ""))) and not _unofficial(g)]

    def artist(self, mbid: str) -> dict:
        if not MBID_RE.match(mbid or ""):
            raise ProviderError("That isn't a MusicBrainz artist ID.")
        data = self._get(f"artist/{mbid}", {"inc": "url-rels+genres"})
        if not isinstance(data, dict):
            raise ProviderError("MusicBrainz doesn't have that artist.")
        return data

    def artist_release_groups(self, mbid: str) -> list[dict]:
        """The artist's albums, EPs and singles (up to 100), oldest first.

        Filtered the way MusicBrainz's own artist page is by default: release groups made only of
        bootlegs, promos or pseudo-releases (fan uploads, fake covers, slowed remixes) are left out.
        """
        data = self._get("release-group", {"artist": mbid, "limit": "100", "type": "album|ep|single",
                                           "release-group-status": "website-default"})
        items = data.get("release-groups") if isinstance(data, dict) else None
        groups = [g for g in items or [] if isinstance(g, dict) and MBID_RE.match(str(g.get("id", "")))]
        return sorted(groups, key=lambda g: (g.get("first-release-date") or "9999", g.get("title") or ""))

    def release_group(self, mbid: str) -> dict:
        if not MBID_RE.match(mbid or ""):
            raise ProviderError("That isn't a MusicBrainz release group ID.")
        data = self._get(f"release-group/{mbid}", {"inc": "releases+artist-credits+genres"})
        if not isinstance(data, dict):
            raise ProviderError("MusicBrainz doesn't have that release.")
        return data

    def releases_in_group(self, group_id: str) -> list[dict]:
        """Every edition of an album (up to 100): formats, track counts, labels, countries."""
        if not MBID_RE.match(group_id or ""):
            raise ProviderError("That isn't a MusicBrainz release group ID.")
        data = self._get("release", {"release-group": group_id, "inc": "media+labels+artist-credits", "limit": "100"})
        items = data.get("releases") if isinstance(data, dict) else None
        return [r for r in items or [] if isinstance(r, dict) and MBID_RE.match(str(r.get("id", "")))]

    def release_tracks_summary(self, mbid: str) -> dict:
        """A release with its tracklist and labels (lighter than ``release``)."""
        if not MBID_RE.match(mbid or ""):
            raise ProviderError("That isn't a MusicBrainz release ID.")
        data = self._get(f"release/{mbid}", {"inc": "recordings+labels+artist-credits+media"})
        if not isinstance(data, dict):
            raise ProviderError("MusicBrainz doesn't have that release.")
        return data


_UNOFFICIAL = {"bootleg", "pseudo-release", "withdrawn", "cancelled"}


def _unofficial(group: dict) -> bool:
    """True when every release MusicBrainz lists in a group is a bootleg (or similar): fan uploads,
    fake covers, slowed remixes. A group without any release statuses is kept."""
    statuses = {str(r.get("status") or "").lower() for r in group.get("releases") or [] if isinstance(r, dict)}
    statuses.discard("")
    return bool(statuses) and statuses <= _UNOFFICIAL


def cover_url(mbid: str, size: int | None = 1200, base: str = CAA_BASE, kind: str = "release") -> str:
    if not MBID_RE.match(mbid or ""):
        raise ProviderError("That isn't a MusicBrainz release ID.")
    if kind not in ("release", "release-group"):
        raise ProviderError("Unknown cover kind.")
    return f"{base}/{kind}/{mbid}/front" + (f"-{size}" if size else "")


# --- Exploring: plain summaries for the page ------------------------------------------------

_SAFE_LINK = re.compile(r"^https?://[^\s<>\"']+$")
LINK_TYPES = {"official homepage": "Website", "wikipedia": "Wikipedia", "wikidata": "Wikidata",
              "bandcamp": "Bandcamp", "discogs": "Discogs", "allmusic": "AllMusic", "last.fm": "Last.fm",
              "soundcloud": "SoundCloud", "youtube": "YouTube", "streaming": "Streaming",
              "free streaming": "Streaming", "social network": "Social"}


def _year(date: str | None) -> str:
    return (date or "")[:4]


def artist_summary(a: dict) -> dict:
    life = a.get("life-span") or {}
    area = (a.get("area") or {}).get("name") or ""
    return {"id": a.get("id"), "name": a.get("name") or "", "type": a.get("type") or "",
            "country": a.get("country") or "", "area": area, "disambiguation": a.get("disambiguation") or "",
            "begin": _year(life.get("begin")), "end": _year(life.get("end")), "ended": bool(life.get("ended")),
            "score": a.get("score")}


def group_summary(g: dict) -> dict:
    credit = g.get("artist-credit")
    first = next((c.get("artist") or {} for c in credit or [] if isinstance(c, dict)), {})
    return {"id": g.get("id"), "title": g.get("title") or "", "artist": credit_string(credit) if credit else "",
            "artist_id": first.get("id") or "", "type": g.get("primary-type") or "",
            "secondary": [t for t in g.get("secondary-types") or [] if isinstance(t, str)],
            "year": _year(g.get("first-release-date")), "date": g.get("first-release-date") or "",
            "score": g.get("score")}


def artist_links(a: dict) -> list[dict]:
    out, seen = [], set()
    for rel in a.get("relations") or []:
        url = ((rel or {}).get("url") or {}).get("resource") or ""
        label = LINK_TYPES.get((rel or {}).get("type") or "")
        if label and _SAFE_LINK.match(url) and url not in seen:
            seen.add(url)
            out.append({"label": label, "url": url})
    return out[:10]


def pick_release(group: dict) -> dict | None:
    """The edition to show for a release group: the earliest official one."""
    rels = [r for r in group.get("releases") or [] if isinstance(r, dict) and MBID_RE.match(str(r.get("id", "")))]
    official = [r for r in rels if (r.get("status") or "").lower() == "official"] or rels
    return min(official, key=lambda r: r.get("date") or "9999") if official else None


def tracklist(rel: dict) -> list[dict]:
    out = []
    discs = [m for m in rel.get("media") or [] if isinstance(m, dict)]
    for disc_no, m in enumerate(discs, 1):
        for t in m.get("tracks") or []:
            if not isinstance(t, dict):
                continue
            length = t.get("length") or (t.get("recording") or {}).get("length")
            out.append({"disc": disc_no, "discs": len(discs), "number": t.get("number") or str(t.get("position") or ""),
                        "title": t.get("title") or "", "length": round(length / 1000) if isinstance(length, int) else None,
                        "artist": credit_string(t.get("artist-credit")) if t.get("artist-credit") else ""})
    return out


# --- Turning a release into something readable -------------------------------------------


def summarize(rel: dict) -> dict:
    """The facts that tell two editions apart, for the candidate list."""
    rg = rel.get("release-group") or {}
    media = [m for m in rel.get("media") or [] if isinstance(m, dict)]
    formats: OrderedDict[str, int] = OrderedDict()
    for m in media:
        fmt = m.get("format") or "Unknown format"
        formats[fmt] = formats.get(fmt, 0) + 1
    track_count = rel.get("track-count")
    if not isinstance(track_count, int):
        track_count = sum(m.get("track-count") or len(m.get("tracks") or []) for m in media)
    labels = []
    for li in rel.get("label-info") or []:
        if not isinstance(li, dict):
            continue
        name = (li.get("label") or {}).get("name") or ""
        cat = li.get("catalog-number") or ""
        if cat == "[none]":
            cat = ""
        labels.append(" ".join(p for p in (name, cat and f"({cat})") if p))
    types = [rg.get("primary-type")] + list(rg.get("secondary-types") or [])
    caa = rel.get("cover-art-archive") or {}
    return {
        "id": rel.get("id"),
        "title": rel.get("title") or "",
        "artist": credit_string(rel.get("artist-credit")),
        "disambiguation": rel.get("disambiguation") or "",
        "date": rel.get("date") or "",
        "country": rel.get("country") or "",
        "status": rel.get("status") or "",
        "type": " · ".join(t for t in types if t),
        "labels": _unique(labels),
        "barcode": rel.get("barcode") or "",
        "formats": " + ".join(f"{n}×{f}" if n > 1 else f for f, n in formats.items()),
        "track_count": track_count,
        "disc_count": len(media) or None,
        "mb_score": rel.get("score") if isinstance(rel.get("score"), int) else None,
        # Search results don't say; a full lookup does. None = unknown, try anyway.
        "has_cover": caa.get("front") if isinstance(caa.get("front"), bool) else None,
        "url": rel.get("_url") or f"https://musicbrainz.org/release/{rel.get('id')}",
        "source": rel.get("_source") or "musicbrainz",
        "cover": rel.get("_cover") or None,
    }


@dataclass
class FileInfo:
    """What Codetta knows about one file before matching."""

    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    albumartist: str = ""
    tracknumber: int | None = None
    discnumber: int | None = None
    duration: float | None = None
    albumid: str = ""


def number(value: str | None) -> int | None:
    """ "3/12" -> 3, "A2" -> None."""
    m = re.match(r"^\s*(\d+)", value or "")
    return int(m.group(1)) if m else None


def song_releases(recordings: list[dict], title: str, artist: str, duration: float | None,
                  limit: int = 6, prefer=None) -> list[dict]:
    """For one loose song: the releases it's on, best first. Fit comes from the song itself (title,
    main artist, a little from length); among good fits the original studio album comes first:
    by the same artist, official, no compilation/live/soundtrack, album before single, earliest
    (an album's date is its earliest edition's). One edition per album.
    Returns [{"release", "recording", "score"}]."""
    found = []
    for rec in recordings:
        t = similarity(title, clean_title(rec.get("title") or ""))
        names = credit_names(rec.get("artist-credit"))
        a = max([similarity(artist, n) for n in names[:1]] + [similarity(artist, credit_string(rec.get("artist-credit")))]) \
            if artist else 0.5
        if t < 0.75 or (artist and a < 0.6):
            continue
        length = rec.get("length")
        if duration and isinstance(length, int | float):
            d = abs(length / 1000 - duration)
            fit = 1.0 if d <= 3 else 0.7 if d <= 10 else 0.0
        else:
            fit = 0.5
        # Length is only a small nudge: rips add intros, and MusicBrainz lengths can be an edit's.
        score = round((0.55 * t + 0.35 * a + 0.10 * fit) * 100)
        for r in rec.get("releases") or []:
            if not isinstance(r, dict) or not MBID_RE.match(str(r.get("id", ""))):
                continue
            rg = r.get("release-group") or {}
            own = r.get("artist-credit")  # only there when the release's artist differs (compilations)
            other = bool(own) and artist and similarity(artist, (credit_names(own) or [""])[0]) < 0.8
            rel = {**r, "artist-credit": own or rec.get("artist-credit")}
            found.append({"score": score, "t": t, "a": a, "other": other, "rg": rg, "group": rg.get("id") or r["id"],
                          "release": rel, "recording": rec["id"]})
    if not found:
        return []
    first: dict[str, str] = {}
    for f in found:
        d = f["release"].get("date") or "9999"
        first[f["group"]] = min(first.get(f["group"], "9999"), d)
    top = max(f["score"] for f in found)
    top_a = max(f["a"] for f in found)
    top_t = max(f["t"] for f in found)

    def rank(f: dict) -> tuple:  # the exact song by the same artist first, then the original album
        return (f["t"] < top_t - 0.05, f["a"] < top_a - 0.05, f["other"], f["release"].get("status") != "Official", bool(f["rg"].get("secondary-types")),
                {"Album": 0, "Single": 1, "EP": 2}.get(f["rg"].get("primary-type"), 3), first[f["group"]],
                -(prefer(summarize(f["release"])) if prefer else 0), -f["score"],  # within an album: the
                f["release"].get("date") or "9999")  # preferred edition (not a length nudge), else the first

    out, groups = [], set()
    for f in sorted((f for f in found if f["score"] >= top - 12), key=rank):
        if f["group"] in groups:
            continue
        groups.add(f["group"])
        out.append({"release": f["release"], "recording": f["recording"], "score": max(0, f["score"] - 3 * len(out))})
        if len(out) >= limit:
            break
    return out


def score_candidate(summary: dict, files: list[FileInfo], album: str, artist: str) -> int:
    """0..100: how well a release fits these files and the search."""
    n = len(files)
    tracks = summary.get("track_count") or 0
    if n and tracks:
        count = 1.0 if tracks == n else max(0.0, 1 - abs(tracks - n) / max(n, tracks) * 2)
    else:
        count = 0.5
    title = similarity(album, summary["title"]) if album else 0.5
    who = similarity(artist, summary["artist"]) if artist else 0.5
    mb = (summary.get("mb_score") or 50) / 100
    score = 0.35 * title + 0.25 * who + 0.30 * count + 0.10 * mb
    if summary.get("status") == "Official":
        score += 0.02
    return max(0, min(100, round(score * 100)))


# --- Tracks and pairing -------------------------------------------------------------------


@dataclass
class TrackRef:
    id: str
    disc: int
    position: int
    index: int  # position across the whole release (1-based)
    number: str  # as printed ("A1" on vinyl)
    title: str
    artist: str
    length: float | None  # seconds
    medium: dict = field(repr=False, default_factory=dict)
    track: dict = field(repr=False, default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "disc": self.disc, "position": self.position, "number": self.number,
                "title": self.title, "artist": self.artist, "length": self.length}


def release_tracks(rel: dict) -> list[TrackRef]:
    out: list[TrackRef] = []
    for mi, medium in enumerate(m for m in rel.get("media") or [] if isinstance(m, dict)):
        disc = medium.get("position") if isinstance(medium.get("position"), int) else mi + 1
        for ti, track in enumerate(t for t in medium.get("tracks") or [] if isinstance(t, dict)):
            if not isinstance(track.get("id"), str):
                continue
            rec = track.get("recording") or {}
            length = track.get("length") or rec.get("length")
            out.append(TrackRef(
                id=track["id"], disc=disc,
                position=track.get("position") if isinstance(track.get("position"), int) else ti + 1,
                index=len(out) + 1, number=str(track.get("number") or ""),
                title=track.get("title") or rec.get("title") or "",
                artist=credit_string(track.get("artist-credit") or rec.get("artist-credit")),
                length=length / 1000 if isinstance(length, (int, float)) else None,
                medium=medium, track=track,
            ))
    return out


@dataclass
class Pairing:
    track: TrackRef | None
    confidence: str  # "high", "check" or "none"
    notes: list[str] = field(default_factory=list)


def _fit_notes(f: FileInfo, t: TrackRef) -> tuple[float, list[str]]:
    """How well a file fits a track by title and length (0..1), and what looks off."""
    notes = []
    title = similarity(f.title, t.title) if f.title else None
    diff = abs(f.duration - t.length) if f.duration and t.length else None
    if diff is not None and diff > 10:
        notes.append(f"Length differs by {round(diff)} s")
    if title is not None and title < 0.6:
        notes.append(f"Title differs (file: “{f.title[:60]}”)")
    parts = []
    if title is not None:
        parts.append((0.6, title))
    if diff is not None:
        parts.append((0.4, max(0.0, 1 - diff / 20)))
    fit = sum(w * v for w, v in parts) / sum(w for w, _ in parts) if parts else 0.5
    return fit, notes


def pair_files(files: list[FileInfo], tracks: list[TrackRef],
               chosen: dict[str, str | None] | None = None,
               recordings: dict[str, list[str]] | None = None) -> dict[str, Pairing]:
    """Pair each file with a release track. ``chosen`` holds the user's own
    picks (path -> track id, or None for "leave this file alone");
    ``recordings`` what AcoustID heard in each file (path -> recording IDs)."""
    chosen = chosen or {}
    recordings = recordings or {}
    by_id = {t.id: t for t in tracks}
    discs = len({t.disc for t in tracks})
    result: dict[str, Pairing] = {}
    taken: set[str] = set()

    for f in files:  # 1. the user's picks
        if f.path in chosen:
            t = by_id.get(chosen[f.path] or "")
            result[f.path] = Pairing(t, "high" if t else "none", _fit_notes(f, t)[1] if t else [])
            if t:
                taken.add(t.id)

    for f in files:  # 2. identified by sound: the track that is that recording
        heard = recordings.get(f.path)
        if f.path in result or not heard:
            continue
        options = [t for t in tracks if t.id not in taken and (t.track.get("recording") or {}).get("id") in heard]
        if f.duration:
            options.sort(key=lambda t: abs((t.length or f.duration) - f.duration))
        if options:
            t = options[0]
            notes = [n for n in _fit_notes(f, t)[1] if n.startswith("Length")]
            result[f.path] = Pairing(t, "high" if not notes else "check", notes)
            taken.add(t.id)

    for f in files:  # 3. disc + track number, when the title/length don't contradict it
        if f.path in result or f.tracknumber is None:
            continue
        if discs > 1 and f.discnumber is None:
            # Multi-disc release, files numbered straight through (1..N).
            t = next((t for t in tracks if t.index == f.tracknumber), None)
        else:
            disc = f.discnumber if discs > 1 else None
            t = next((t for t in tracks if t.position == f.tracknumber and (disc is None or t.disc == disc)), None)
        if t is None or t.id in taken:
            continue
        fit, notes = _fit_notes(f, t)
        if fit < 0.35 and len(notes) == 2:  # both title and length disagree: numbering is probably off
            continue
        if f.title and similarity(f.title, t.title) < 0.6 and any(
                o.id not in taken and o is not t and similarity(f.title, o.title) >= 0.85 for o in tracks):
            continue  # the title clearly names another track: numbering is off, pair by title below
        result[f.path] = Pairing(t, "high" if not notes else "check", notes)
        taken.add(t.id)

    # 4. everything else by title and length, best pairs first.
    left_files = [f for f in files if f.path not in result]
    left_tracks = [t for t in tracks if t.id not in taken]
    scored = sorted(((_fit_notes(f, t)[0], fi, ti) for fi, f in enumerate(left_files)
                     for ti, t in enumerate(left_tracks)), reverse=True)
    used_f, used_t = set(), set()
    for fit, fi, ti in scored:
        if fit < 0.55 or fi in used_f or ti in used_t:
            continue
        f, t = left_files[fi], left_tracks[ti]
        notes = _fit_notes(f, t)[1]
        result[f.path] = Pairing(t, "check", notes or ["Matched by title and length"])
        used_f.add(fi)
        used_t.add(ti)

    for f in files:
        result.setdefault(f.path, Pairing(None, "none", ["No matching track on this release"]))
    return result


# --- Tags ---------------------------------------------------------------------------------


def _credits(relations: list | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in relations or []:
        if not isinstance(r, dict) or r.get("target-type") != "artist":
            continue
        key = CREDIT_TYPES.get(r.get("type") or "")
        artist = r.get("artist") or {}
        name = r.get("target-credit") or artist.get("name")
        if key and name:
            out.setdefault(key, []).append(name)
    return out


def album_tags(rel: dict) -> dict[str, list[str]]:
    rg = rel.get("release-group") or {}
    credits = rel.get("artist-credit")
    tags: dict[str, list[str]] = {
        "album": [rel.get("title") or ""],
        "albumartist": [credit_string(credits)],
        "albumartists": credit_names(credits),
        "albumartistsort": [credit_string(credits, sort=True)],
        "musicbrainz_albumartistid": credit_ids(credits),
        "musicbrainz_albumid": [rel.get("id") or ""],
        "musicbrainz_releasegroupid": [rg.get("id") or ""],
        "date": [rel.get("date") or ""],
        "originaldate": [rg.get("first-release-date") or ""],
        "releasetype": [t.lower() for t in [rg.get("primary-type")] + list(rg.get("secondary-types") or []) if t],
        "releasestatus": [(rel.get("status") or "").lower()],
        "releasecountry": [rel.get("country") or ""],
        "barcode": [rel.get("barcode") or ""],
        "script": [(rel.get("text-representation") or {}).get("script") or ""],
    }
    infos = [li for li in rel.get("label-info") or [] if isinstance(li, dict)]
    tags["label"] = _unique((li.get("label") or {}).get("name") for li in infos)
    tags["catalognumber"] = _unique(li.get("catalog-number") for li in infos if li.get("catalog-number") != "[none]")
    if VARIOUS_ARTISTS in tags["musicbrainz_albumartistid"]:
        tags["compilation"] = ["1"]
    genres = [g for g in (rel.get("genres") or rg.get("genres") or []) if isinstance(g, dict) and g.get("name")]
    genres.sort(key=lambda g: -(g.get("count") or 0))
    tags["genre"] = _unique(g["name"].title() for g in genres[:3])
    if rel.get("_source"):  # Deezer / iTunes: their ids are not MusicBrainz IDs, so none are written
        tags = {k: v for k, v in tags.items() if not k.startswith("musicbrainz_")}
    return tags


def track_tags(rel: dict, t: TrackRef, album: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """Every tag this release has for one track (empty values left out)."""
    tags = dict(album if album is not None else album_tags(rel))
    track, medium = t.track, t.medium
    rec = track.get("recording") or {}
    credits = track.get("artist-credit") or rec.get("artist-credit")
    media_count = len([m for m in rel.get("media") or [] if isinstance(m, dict)])
    track_count = medium.get("track-count") or len(medium.get("tracks") or [])
    tags.update({
        "title": [t.title],
        "artist": [credit_string(credits)],
        "artists": credit_names(credits),
        "artistsort": [credit_string(credits, sort=True)],
        "musicbrainz_artistid": credit_ids(credits),
        "musicbrainz_trackid": [rec.get("id") or ""],
        "musicbrainz_releasetrackid": [track.get("id") or ""],
        "tracknumber": [f"{t.position}/{track_count}" if track_count else str(t.position)],
        "discnumber": [f"{t.disc}/{media_count}" if media_count else str(t.disc)],
        "media": [medium.get("format") or ""],
        "discsubtitle": [medium.get("title") or ""],
        "isrc": _unique(rec.get("isrcs") or []),
    })
    # Credits: the release's own (apply to every track), the recording's, and
    # the composer/lyricist of the work it performs.
    credit_map: dict[str, list[str]] = {}
    for source in (_credits(rel.get("relations")), _credits(rec.get("relations"))):
        for k, v in source.items():
            credit_map.setdefault(k, []).extend(v)
    work_ids = []
    for r in rec.get("relations") or []:
        if isinstance(r, dict) and r.get("target-type") == "work" and r.get("type") == "performance":
            work = r.get("work") or {}
            if isinstance(work.get("id"), str):
                work_ids.append(work["id"])
            for k, v in _credits(work.get("relations")).items():
                credit_map.setdefault(k, []).extend(v)
    for k, v in credit_map.items():
        tags[k] = _unique(v)
    tags["musicbrainz_workid"] = _unique(work_ids)
    if rel.get("_source"):  # Deezer / iTunes: never written as MusicBrainz IDs
        tags = {k: v for k, v in tags.items() if not k.startswith("musicbrainz_")}
    return _without_placeholders({k: _unique(v) for k, v in tags.items() if _unique(v)})


# MusicBrainz's stand-ins for what it doesn't know yet (e.g. unreleased songs on a soundtrack listed
# as "[unknown]" by "[unknown]"). They're not real names: a file keeps the title and artist it has.
PLACEHOLDER_NAMES = frozenset({"[unknown]", "[untitled]", "[no artist]", "[unknown artist]", "[data]"})
PLACEHOLDER_ARTIST_IDS = frozenset({"125ec42a-7229-4250-afc5-e057484327fe"})  # the "[unknown]" artist


def _without_placeholders(tags: dict[str, list[str]]) -> dict[str, list[str]]:
    out = {}
    for key, values in tags.items():
        kept = [v for v in values if v.strip().lower() not in PLACEHOLDER_NAMES and v.lower() not in PLACEHOLDER_ARTIST_IDS]
        if kept:
            out[key] = kept
    return out
