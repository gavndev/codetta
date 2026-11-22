"""Paste a tracklist: turn text copied from Discogs, Bandcamp, Wikipedia or a .txt into tracks,
then pair them with an album's files.

Each line can carry a position ("1.", "01", "A1", "2-03"), a title (in "quotes" on Wikipedia),
an artist ("Artist – Title", or Discogs' "–Artist" column) and a length ("3:45", "(03:45)").
"Disc 2" / "CD 2" headings start a new disc; headers like "No. Title Length" and totals are
skipped. Tracks are paired with files by disc and track number when both have them, and in
order otherwise; lengths that disagree by more than a few seconds are flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_LINES = 500
LENGTH_SLACK = 8  # seconds: more than this apart, the pairing gets a warning

_DISC = re.compile(r"^\s*(?:(?:disc|disk|cd)\s*(\d{1,2})|side\s+([a-z]))\s*(?:[:.\-–—].*)?$", re.IGNORECASE)
_HEADER_WORDS = {"no", "no.", "#", "track", "title", "length", "time", "duration", "writer", "writers", "writer(s)",
                 "artist", "artists", "producer", "producer(s)", "composer", "lyricist", "position", "pos", "duration"}
_HEADING = re.compile(r"^\s*(?:track\s*list(?:ing)?|tracks|track listing)\s*:?\s*$", re.IGNORECASE)


def _header(line: str) -> bool:
    """A table's header row ("No. Title Writer(s) Length") or a "Tracklist:" heading, not a song called "Time"."""
    if _HEADING.match(line):
        return True
    words = [w.lower() for w in re.split(r"[\t ]+", line.strip()) if w]
    return len(words) >= 2 and all(w in _HEADER_WORDS for w in words)

_TOTAL = re.compile(r"^\s*total(?:\s+(?:length|time|running time|duration|playing time))?\s*(?::|[\t ]+\(?\d{1,2}:\d{2}|$)",
                    re.IGNORECASE)  # "Total length: 53:21", not a song called "Total Eclipse of the Heart"
_TIME = re.compile(r"[\s\t]*[(\[]?(\d{1,2}):([0-5]\d)(?::([0-5]\d))?[)\]]?\s*$")
_POSITION = re.compile(r"^\s*(?:(\d{1,2})[-.](\d{1,3})|([A-Z]{1,2})(\d{1,3})|(\d{1,3})|([A-Z]))(?:\t|[.)\]:][ \t]*|[ ]+[-–—.][ ]+|[ ]+)")
_DASH = re.compile(r"\s+[-–—]\s+")
_QUOTED = re.compile(r"^[\"“”„«]([^\"“”„»]+)[\"“”»]")


@dataclass
class Track:
    title: str
    number: int | None = None  # from the position (vinyl A1/A2/B1 count up in order)
    disc: int | None = None
    artist: str | None = None
    seconds: int | None = None
    line: str = ""
    plain: str = ""  # the title if the leading number is part of it ("7 Rings")


@dataclass
class Parsed:
    tracks: list[Track] = field(default_factory=list)
    artist_first: bool = False  # lines look like "Artist – Title"


def _length(text: str) -> tuple[str, int | None]:
    m = _TIME.search(text)
    if not m:
        return text, None
    h_or_m, m_or_s, s = m.groups()
    secs = int(h_or_m) * 3600 + int(m_or_s) * 60 + int(s) if s else int(h_or_m) * 60 + int(m_or_s)
    return text[: m.start()].rstrip(), secs


def parse(text: str, artist_first: bool | None = None) -> Parsed:
    """The tracks in a pasted tracklist. ``artist_first``: None works it out from the lines."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r", "").split("\n")][: MAX_LINES * 2]
    raw: list[Track] = []
    disc = None
    vinyl = 0
    for line in lines:
        if not line.strip() or _header(line) or _TOTAL.match(line):
            continue
        d = _DISC.match(line)
        if d and not _TIME.search(line):
            if d.group(1):
                disc = int(d.group(1))  # "Side A" headings don't change the disc
            continue
        rest, secs = _length(line)
        unnumbered = rest.strip().strip(" \"“”")
        number = None
        m = _POSITION.match(rest)
        if m:
            disc_n, track_n, side, side_n, plain, letter = m.groups()
            if disc_n:
                disc, number = int(disc_n), int(track_n)
            elif side:
                vinyl += 1
                number = vinyl
            elif plain:
                number = int(plain)
            elif letter and len(rest) > 2 and rest[1] in ".)\t":
                vinyl += 1
                number = vinyl
            else:
                m = None
            if m:
                rest = rest[m.end():]
        cols = [c.strip() for c in rest.split("\t") if c.strip()]
        artist = None
        if len(cols) > 1:  # Discogs: "–Artist <tab> Title"; Wikipedia: "Title <tab> Writer"
            if cols[0][:1] in "–—-" and len(cols[0]) > 1:
                artist, cols = cols[0].lstrip("–—- ").strip(), cols[1:]
            title = cols[0]
        else:
            title = cols[0] if cols else ""
        q = _QUOTED.match(title)
        if q:  # Wikipedia: "Title" (feat. X): keep what follows the quotes too
            title = (q.group(1) + title[q.end():]).strip()
        title = title.strip(" \"“”")
        if not title or len(title) > 300:
            continue
        raw.append(Track(title=title, number=number, disc=disc, artist=artist, seconds=secs, line=line.strip(),
                         plain=unnumbered if "\t" not in unnumbered else title))
        if len(raw) >= MAX_LINES:
            break
    numbered = [t for t in raw if t.number]
    if numbered and len(numbered) < 0.5 * len(raw):  # a list of titles, a few starting with numbers ("7 Rings")
        for t in numbered:
            t.title, t.number = t.plain, None
    if artist_first is None:
        with_dash = [t for t in raw if t.artist is None and _DASH.search(t.title)]
        lefts = {_DASH.split(t.title, 1)[0].casefold() for t in with_dash}
        # Most lines split the same way, and the left side repeats (one artist) or the list is
        # long enough to be a compilation: "Artist – Title". A few remix titles don't count.
        artist_first = bool(raw) and len(with_dash) >= max(2, 0.8 * len(raw)) and (
            len(lefts) <= max(1, len(with_dash) // 2) or len(with_dash) == len(raw))
    if artist_first:
        for t in raw:
            if t.artist is None and _DASH.search(t.title):
                t.artist, t.title = (p.strip() for p in _DASH.split(t.title, 1))
    return Parsed(raw, artist_first)


@dataclass
class Pair:
    path: str
    track: Track | None
    warning: str = ""


def pair(files: list[tuple[str, int | None, int | None, float | None]], tracks: list[Track]) -> list[Pair]:
    """Pair files (path, disc, track number, seconds) with tracks: by disc and number when the
    tracklist is numbered and the files are too, in order otherwise."""
    out: list[Pair] = []
    numbered = tracks and all(t.number for t in tracks) and all(f[2] for f in files)
    if numbered:
        multi = len({t.disc or 1 for t in tracks}) > 1 or any(f[1] not in (None, 1) for f in files)
        by_key = {((t.disc or 1) if multi else 1, t.number): t for t in tracks}
        for path, disc, number, secs in files:
            t = by_key.get(((disc or 1) if multi else 1, number))
            out.append(Pair(path, t, _check(t, secs)))
        return out
    for i, (path, _disc, _number, secs) in enumerate(files):
        t = tracks[i] if i < len(tracks) else None
        out.append(Pair(path, t, _check(t, secs)))
    return out


def _check(t: Track | None, secs: float | None) -> str:
    if t is None or t.seconds is None or not secs:
        return ""
    diff = abs(t.seconds - secs)
    return f"Lengths differ by {round(diff)} s" if diff > LENGTH_SLACK else ""
