"""Which artists a credit names: "Justice & Michael McDonald", "Yung Lean, Metro Boomin & Future".

Tapping an artist name in the page lands on that artist. A credit can name several, so
it's split at the usual separators. Names the library has (an artist folder at the top of
the music folder, or a whole artist/album-artist tag value) lead there; the rest of a
collaboration's names lead to a search for their songs.
That keeps "Tyler, The Creator" and "Simon & Garfunkel" whole (the library has them under
those names, and not "Tyler" or "Garfunkel" alone) and never offers a stray piece like
"The Creator". A collaboration's own credit is a tag value too, so a run of several names counts as
one artist only with its own folder, or when its tag spans albums and none of its names is
an artist on its own (a duo); otherwise every name in it is offered.

The longest run of pieces that the library knows wins, left to right, so "Earth, Wind &
Fire feat. X" finds "Earth, Wind & Fire" before trying "Earth" or "Wind".
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from codetta.core.index import sfold

# Separators between artists in one credit. Words need spaces around them ("x" in
# "Metro Boomin x Future", never the x in "Xzibit").
SEPARATORS = re.compile(
    r"\s*(?:,|;|/|\s&\s|\s\+\s|\s(?:feat\.?|ft\.?|featuring|with|x|vs\.?|and)\s)\s*", re.IGNORECASE)
MAX_PIECES = 12  # a credit longer than this is cut (nobody needs 40 names in a menu)


def pieces(credit: str) -> list[tuple[int, int]]:
    """(start, end) of each name between separators in ``credit``."""
    out, pos = [], 0
    for m in SEPARATORS.finditer(credit):
        if m.start() > pos:
            out.append((pos, m.start()))
        pos = m.end()
    if pos < len(credit):
        out.append((pos, len(credit)))
    return [(a, b) for a, b in out if credit[a:b].strip()][:MAX_PIECES]


def top_folders(music_dir: Path) -> dict[str, str]:
    """Folder names at the top of the music folder, by their search form."""
    try:
        with os.scandir(music_dir) as it:
            return {sfold(e.name): e.name for e in it
                    if not e.name.startswith((".", "@")) and e.is_dir(follow_symlinks=False)}
    except OSError:
        return {}


def resolve(credits: Iterable[str], known: Callable[[str], int], folders: dict[str, str]) -> list[dict]:
    """The artists the credits name: [{"name", "folder", "own"}] in credit order. ``own``: the
    library has them under their own name (a folder or a tag of their own), not only credited
    alongside others; every name is listed either way.

    ``known(name)``: in how many folders ``name`` is a whole artist or album-artist value (0: none).
    ``folder`` is the top-level folder named after the artist, or None (then the page searches).

    A run of several names is one artist when it has its own folder, or when its tag is used
    across albums and none of its names is an artist on its own: a duo or band ("Simon &
    Garfunkel"). Otherwise it's a collaboration, and each name in it is offered: the ones the
    library knows lead to them, the others to a search of their songs."""
    found: dict[str, dict] = {}

    def has(name: str) -> dict | None:
        key = sfold(name)
        if not key:
            return None
        folder = folders.get(key)
        if folder is not None or known(name):
            return {"name": folder or name, "folder": folder, "own": True}
        return None

    def band(credit: str, parts: list[tuple[int, int]], i: int, j: int) -> dict | None:
        name = credit[parts[i][0]:parts[j][1]].strip()
        folder = folders.get(sfold(name))
        if folder is not None:
            return {"name": folder, "folder": folder, "own": True}
        if known(name) >= 2 and not any(has(credit[a:b].strip()) for a, b in parts[i:j + 1]):
            return {"name": name, "folder": None, "own": True}
        return None

    for credit in credits:
        credit = (credit or "").strip()[:500]
        parts = pieces(credit)
        i = 0
        while i < len(parts):
            for j in range(len(parts) - 1, i, -1):  # the longest run of several names first
                hit = band(credit, parts, i, j)
                if hit:
                    found.setdefault(sfold(hit["name"]), hit)
                    i = j + 1
                    break
            else:
                name = credit[parts[i][0]:parts[i][1]].strip()
                hit = has(name) or {"name": name, "folder": None, "own": False}
                if sfold(hit["name"]):
                    found.setdefault(sfold(hit["name"]), hit)
                i += 1
    return list(found.values())
