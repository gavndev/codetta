"""Discogs: album details, credits and covers from the Discogs database (https://www.discogs.com).

Strong where MusicBrainz is thin: vinyl and other physical pressings, electronic music, white
labels, rare and regional releases. A Discogs release becomes the same release shape Deezer and
iTunes produce (see catalogs.py), so the review, safe writing and undo all work the same.

* **Searching needs a token.** Discogs only lets signed-in apps search; looking up a release by its
  link works without one. Each person makes a free personal token (discogs.com → Settings →
  Developers → Generate new token). It's kept in ``discogs.json`` (owner only) and sent as a header,
  never in an address, so it can't end up in an error message or a log.
* **Polite:** at most one request a second (Discogs allows 60 a minute with a token).
* **What a release gives:** title, artists ("feat." and "&" credits kept), label, catalogue number,
  barcode, country, format (CD, vinyl, file), year, styles as genres, discs and vinyl sides, and
  per-track credits (producer, mixer, engineer, composer, lyricist, arranger, remixer, DJ mix).
  Names Discogs numbers to tell artists apart ("Nirvana (2)") lose the number.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

API = "https://api.discogs.com"
MIN_INTERVAL = 1.0  # seconds between requests

# Discogs' country names -> the ISO codes MusicBrainz (and Codetta's edition preference) use.
COUNTRIES = {
    "US": "US", "UK": "GB", "Germany": "DE", "France": "FR", "Japan": "JP", "Canada": "CA", "Netherlands": "NL",
    "Italy": "IT", "Spain": "ES", "Sweden": "SE", "Australia": "AU", "Brazil": "BR", "Belgium": "BE", "Norway": "NO",
    "Denmark": "DK", "Finland": "FI", "Austria": "AT", "Switzerland": "CH", "Poland": "PL", "Russia": "RU",
    "Mexico": "MX", "Argentina": "AR", "Portugal": "PT", "Greece": "GR", "Ireland": "IE", "New Zealand": "NZ",
    "South Korea": "KR", "Taiwan": "TW", "Hong Kong": "HK", "China": "CN", "India": "IN", "Turkey": "TR",
    "South Africa": "ZA", "Czech Republic": "CZ", "Hungary": "HU", "Israel": "IL", "Jamaica": "JM",
    "Europe": "XE", "Worldwide": "XW", "UK & Europe": "XE", "USA & Canada": "US", "UK, Europe & US": "XW",
}
# Discogs credit roles -> MusicBrainz relationship types (read by musicbrainz._credits).
ROLES = {
    "producer": "producer", "co-producer": "producer", "produced by": "producer",
    "mixed by": "mix", "mixing": "mix", "mixed": "mix",
    "engineer": "engineer", "recorded by": "recording", "recording engineer": "engineer", "engineer [recording]": "recording",
    "written-by": "composer", "written by": "composer", "composed by": "composer", "music by": "composer",
    "songwriter": "composer", "lyrics by": "lyricist", "words by": "lyricist",
    "arranged by": "arranger", "orchestrated by": "orchestrator", "conductor": "conductor",
    "remix": "remixer", "dj mix": "mix-DJ",
}
_NUMBERED = re.compile(r"\s+\(\d+\)$")
_POSITION = re.compile(r"^(?:(?:cd|dvd|disc|disk)\s*)?(\d{1,2})[-.](\d{1,3})$|^([a-z]{1,2})(\d{0,3})[a-z]?$|^(\d{1,3})[a-z]?$",
                       re.IGNORECASE)


class DiscogsTokenError(LookupError):
    """There's no token (searching needs one), or Discogs turned it down."""


def clean_name(name: str) -> str:
    """ "Nirvana (2)" -> "Nirvana": the number only tells Discogs' artists apart."""
    return _NUMBERED.sub("", (name or "").strip()).rstrip("*").strip()


def credit(artists: list | None) -> list[dict]:
    """Discogs artists (with their "join" words) as a MusicBrainz artist credit."""
    out = []
    for a in artists or []:
        if not isinstance(a, dict):
            continue
        name = clean_name(a.get("anv") or a.get("name") or "")
        if not name:
            continue
        join = (a.get("join") or "").strip()
        if join.lower().rstrip(".") in ("feat", "ft", "featuring"):
            join = "feat."  # Codetta's style, as "Write features as feat." does
        elif join.lower().rstrip(".") in ("vs", "versus"):
            join = "vs."
        joinphrase = "" if not join else ", " if join == "," else f" {join} "
        out.append({"name": name, "joinphrase": joinphrase, "artist": {"id": "", "name": name, "sort-name": name}})
    if out:
        out[-1]["joinphrase"] = ""
    return out


def credit_text(c: list[dict]) -> str:
    return "".join(x["name"] + x["joinphrase"] for x in c)


def date_of(rel: dict) -> str:
    released = (rel.get("released") or "").strip()
    released = re.sub(r"(-00)+$", "", released)  # "2007-00-00" -> "2007"
    return released or (str(rel.get("year")) if rel.get("year") else "")


def kind_of(formats: list | None) -> tuple[str, list[str]]:
    """(primary type, secondary types) from Discogs format descriptions."""
    words = {d.lower() for f in formats or [] if isinstance(f, dict) for d in f.get("descriptions") or []}
    primary = "Single" if "single" in words or "maxi-single" in words else "EP" if "ep" in words else "Album"
    return primary, ["Compilation"] if "compilation" in words else []


def media_format(formats: list | None) -> str:
    name = next((f.get("name") for f in formats or [] if isinstance(f, dict) and f.get("name")), "") or ""
    return {"File": "Digital Media", "CDr": "CD-R", "Cassette": "Cassette", "Vinyl": "Vinyl", "CD": "CD"}.get(name, name)


def _seconds(duration: str) -> int | None:
    parts = (duration or "").strip().split(":")
    if not all(p.isdigit() for p in parts) or not parts or parts == [""]:
        return None
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total or None


def _positions(tracks: list[dict]) -> list[tuple[int, int]]:
    """(disc, number) for each track, from Discogs positions: "1", "A1"/"B2" (vinyl sides, numbered on
    in order), "1-3"/"CD2-04" (disc and track). Anything else is numbered in order on disc 1."""
    out, counters = [], {}
    for t in tracks:
        m = _POSITION.match((t.get("position") or "").strip())
        if m and m.group(1):
            disc, num = int(m.group(1)), int(m.group(2))
        else:
            disc = 1
            num = counters.get(disc, 0) + 1
        counters[disc] = max(counters.get(disc, 0), num)
        out.append((disc, num))
    return out


def _in_range(spec: str, positions: list[str]) -> set[str]:
    """The track positions a credit's "tracks" covers: "1 to 4, 6", "A1 to B2"."""
    chosen: set[str] = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if " to " in part:
            a, b = (p.strip() for p in part.split(" to ", 1))
            if a in positions and b in positions:
                i, j = positions.index(a), positions.index(b)
                chosen.update(positions[min(i, j): max(i, j) + 1])
        elif part:
            chosen.add(part)
    return chosen


def _relations(extra: list | None) -> list[dict]:
    rels = []
    for e in extra or []:
        if not isinstance(e, dict):
            continue
        name = clean_name(e.get("anv") or e.get("name") or "")
        for role in (e.get("role") or "").split(","):
            role = re.sub(r"\s*\[.*?\]", "", role).strip().lower()
            mb = ROLES.get(role)
            if name and mb:
                rels.append({"type": mb, "target-type": "artist", "artist": {"name": name}})
    return rels


def summary(r: dict) -> dict:
    """A search result (or a release) as a release-shaped summary, before its tracks are read."""
    from codetta.core.catalogs import (
        _base,  # shared shape, defined there (imported here to avoid a cycle)
    )

    title = r.get("title") or ""
    artist = ""
    if r.get("artists"):
        artist = credit_text(credit(r["artists"]))
    elif " - " in title:  # search results: "Artist - Title"
        artist, title = (clean_name(p) for p in title.split(" - ", 1))
    primary, _secondary = kind_of(r.get("formats") or [{"descriptions": r.get("format") or []}])
    labels = r.get("labels") or [{"name": n, "catno": r.get("catno")} for n in (r.get("label") or [])[:1]]
    label = clean_name((labels[0] or {}).get("name", "")) if labels else ""
    cover = next((i.get("uri") for i in r.get("images") or [] if i.get("type") == "primary"), None) \
        or next((i.get("uri") for i in r.get("images") or []), None) or r.get("cover_image") or ""
    if "spacer.gif" in cover:
        cover = ""
    barcode = next((re.sub(r"\D", "", i.get("value") or "") for i in r.get("identifiers") or []
                    if (i.get("type") or "").lower() == "barcode"), "") or next((re.sub(r"\D", "", b) for b in r.get("barcode") or []), "")
    url = r.get("uri") or ""
    url = url if url.startswith("http") else f"https://www.discogs.com{url}" if url else f"https://www.discogs.com/release/{r.get('id')}"
    rel = _base("discogs", str(r.get("id")), title, artist, date_of(r), cover, url, primary.lower(), label, barcode,
                len([t for t in r.get("tracklist") or [] if (t.get("type_") or "track") != "heading"]) or None)
    rel["country"] = COUNTRIES.get(r.get("country") or "", "")
    rel["_format"] = media_format(r.get("formats") or [{"name": (r.get("format") or [""])[0]}])
    catno = (labels[0] or {}).get("catno") if labels else r.get("catno")
    if label and catno and catno.lower() != "none":
        rel["label-info"] = [{"label": {"name": label}, "catalog-number": catno}]
    return rel


def release(r: dict) -> dict:
    """A full Discogs release as a release with discs, tracks, credits and genres."""
    from codetta.core.catalogs import _media

    rel = summary(r)
    primary, secondary = kind_of(r.get("formats"))
    rel["release-group"] = {"id": "", "primary-type": primary, "secondary-types": secondary}
    album_credit = credit(r.get("artists"))
    tracks = [t for t in r.get("tracklist") or [] if isinstance(t, dict) and (t.get("type_") or "track") in ("track", "index")]
    positions = [(t.get("position") or "").strip() for t in tracks]
    numbers = _positions(tracks)
    wide = [e for e in r.get("extraartists") or [] if isinstance(e, dict)]
    discs: dict[int, list[dict]] = {}
    for t, (disc, num), pos in zip(tracks, numbers, positions, strict=True):
        extra = list(t.get("extraartists") or [])
        extra += [e for e in wide if not (e.get("tracks") or "").strip() or pos in _in_range(e["tracks"], positions)]
        c = credit(t.get("artists")) or album_credit
        discs.setdefault(disc, []).append({
            "position": num, "title": t.get("title") or "", "length": (_seconds(t.get("duration")) or 0) * 1000 or None,
            "artist-credit": c, "isrc": "", "relations": _relations(extra),
        })
    rel["media"] = _media(discs, rel.pop("_format", "") or "CD", "discogs")
    for medium in rel["media"]:  # credits ride on each track's recording, where the matcher reads them
        for track in medium["tracks"]:
            src = next(x for x in discs[medium["position"]] if x["position"] == track["position"])
            track["recording"]["relations"] = src["relations"]
    rel["track-count"] = sum(len(m["tracks"]) for m in rel["media"])
    names = [s for s in (r.get("styles") or []) + (r.get("genres") or []) if s]
    rel["genres"] = [{"name": n, "count": len(names) - i} for i, n in enumerate(dict.fromkeys(names))]
    return rel


class DiscogsToken:
    """The person's Discogs token: from CODETTA_DISCOGS_TOKEN, or saved in discogs.json (owner only)."""

    def __init__(self, file: Path, env_token: str | None = None) -> None:
        self.file = file
        self.env = (env_token or "").strip() or None
        self.lock = threading.Lock()
        try:
            data = json.loads(file.read_text("utf-8"))
            self.saved = str(data.get("token") or "") if isinstance(data, dict) else ""
        except (OSError, ValueError):
            self.saved = ""

    @property
    def token(self) -> str:
        return self.env or self.saved

    @property
    def locked(self) -> bool:
        return self.env is not None

    def save(self, token: str) -> None:
        with self.lock:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".discogs-", dir=self.file.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"token": token}, f)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            self.saved = token


class Throttle:
    """At most one call every ``interval`` seconds, across threads."""

    def __init__(self, interval: float = MIN_INTERVAL) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            pause = self._last + self.interval - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            self._last = time.monotonic()


Fetch = Callable[[str, dict], object]  # (url, headers) -> JSON
