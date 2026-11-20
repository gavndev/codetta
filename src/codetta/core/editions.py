"""Album editions: which edition of an album Codetta prefers when it matches on its own.

An album on MusicBrainz often has dozens of editions (the original, reissues, remasters, deluxe sets,
CD, vinyl, digital, one per country). Matching by hand you pick one; the inbox and Tidy up pick for
you, so these preferences steer them:

* ``original_year``: write the album's original release year, even when the edition matched is a
  later reissue (so a 2011 reissue of a 1977 album is tagged and filed as 1977).
* ``format``: prefer digital, CD or vinyl editions.
* ``country``: prefer editions from one country (or worldwide releases, "XW").
* ``avoid_deluxe``: prefer the standard edition over deluxe/expanded ones, unless your files match.

Preferences only reorder candidates; they never make an uncertain match look certain.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

FORMATS = {"any": "", "digital": "digital media", "cd": "cd", "vinyl": "vinyl"}
# Whole words, so "CD" doesn't match a promo "CD-R"; "2×CD", "Enhanced CD" and '12" Vinyl' still do.
_FORMAT_RE = {k: re.compile(rf"(?<![\w-]){re.escape(v)}(?![\w-])", re.IGNORECASE) for k, v in FORMATS.items() if v}
_VIDEO = re.compile(r"dvd|blu-ray|vhs|video", re.IGNORECASE)  # a video-only edition isn't the music
# CD-Rs on MusicBrainz are nearly always promos, bootlegs or made-to-order copies, not the release.
_CDR = re.compile(r"(?<![\w-])cd-r(?![\w-])", re.IGNORECASE)
_AUDIO = re.compile(r"(?<![\w-])(?:cd|sacd|hdcd|dvd-audio|vinyl|digital media|cassette)(?![\w-])", re.IGNORECASE)
_DELUXE = re.compile(r"\b(deluxe|expanded|anniversary|bonus|special|collector'?s|super)\b", re.IGNORECASE)


@dataclass
class EditionPrefs:
    original_year: bool = True
    format: str = "any"
    country: str = ""  # ISO code ("US", "GB"), "XW" for worldwide, "" for any
    avoid_deluxe: bool = True


class EditionStore:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.prefs = EditionPrefs()
        try:
            data = json.loads(file.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            self.set(**{k: v for k, v in data.items() if k in asdict(self.prefs)}, save=False)

    def set(self, original_year: bool | None = None, format: str | None = None, country: str | None = None,
            avoid_deluxe: bool | None = None, save: bool = True) -> EditionPrefs:
        p = self.prefs
        if original_year is not None:
            p.original_year = bool(original_year)
        if format is not None:
            if format not in FORMATS:
                raise ValueError("Unknown format")
            p.format = format
        if country is not None:
            country = country.strip().upper()
            if country and not re.fullmatch(r"[A-Z]{2}", country):
                raise ValueError("Use a two-letter country code (like US or GB), XW for worldwide, or leave it empty")
            p.country = country
        if avoid_deluxe is not None:
            p.avoid_deluxe = bool(avoid_deluxe)
        if save:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".editions-", dir=self.file.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(asdict(p), f)
                os.replace(tmp, self.file)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return p


def is_deluxe(summary: dict) -> bool:
    return bool(_DELUXE.search(f"{summary.get('title', '')} {summary.get('disambiguation', '')}"))


def edition_fit(summary: dict, prefs: EditionPrefs, files: int | None = None) -> int:
    """How well an edition (a candidate summary) fits the preferences: a small number used to order
    candidates, never added to how sure a match is. Higher is better."""
    fit = 0
    want = _FORMAT_RE.get(prefs.format)
    formats = summary.get("formats") or ""
    if want and want.search(formats):
        fit += 3
    if prefs.country:
        country = (summary.get("country") or "").upper()
        if country == prefs.country:
            fit += 2
        elif country == "XW":
            fit += 1
    if prefs.avoid_deluxe and is_deluxe(summary) and not (files and summary.get("track_count") == files):
        fit -= 3
    if _VIDEO.search(formats) and not _AUDIO.search(formats):
        fit -= 4
    if _CDR.search(formats) and not _AUDIO.search(formats):
        fit -= 2
    if (summary.get("status") or "").lower() == "official":
        fit += 1
    return fit


def padded_date(date: str) -> str:
    """A date for sorting editions: a bare "1977" counts as late in 1977, so a dated original wins
    over an undated pressing from the same year."""
    d = date or "9999"
    return d + "-99-99"[len(d) - 4:]
