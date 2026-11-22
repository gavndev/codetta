"""Tags from file names: "03 - Radiohead - Bodysnatchers.flac" + "{track} - {artist} - {title}".

A pattern is matched against the end of a file's path (without its extension): text in braces
is a tag, anything else must be there as written, and "/" reaches into folders, so
"{artist}/{album} ({year})/{track} {title}" reads the artist and album from the folders too.
"{skip}" matches a part you don't want. Spaces in the pattern match any run of spaces, so
"01 -  Title" and "01 - Title" both fit "{track} - {title}".
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

# Names people type -> Codetta's tag names.
ALIASES = {
    "track": "tracknumber", "tracknumber": "tracknumber", "disc": "discnumber", "discnumber": "discnumber",
    "year": "date", "date": "date", "title": "title", "artist": "artist", "album": "album",
    "albumartist": "albumartist", "genre": "genre", "composer": "composer", "comment": "comment",
    "label": "label", "catalognumber": "catalognumber", "skip": None,
}
SUGGESTIONS = (
    "{track} - {artist} - {title}",
    "{track} - {title}",
    "{track}. {title}",
    "{track} {title}",
    "{artist} - {title}",
    "{artist} - {album} - {track} - {title}",
    "{artist} - {album} ({year})/{track} - {artist} - {title}",  # scene style: the artist in both, and they agree
    "{artist} - {album} ({year})/{track} - {title}",
    "{artist} - {album}/{track} - {title}",
    "{artist}/{album}/{track} - {title}",
    "{artist}/{album} ({year})/{track} - {title}",
    "{artist}/{year} - {album}/{track} - {title}",
    "{artist}/{album}/{track} {title}",
    "{title}",  # at least the title, from a plain name
)
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}", re.IGNORECASE)


class PatternError(ValueError):
    """The pattern can't be used; the message is for people."""


@dataclass(frozen=True)
class Pattern:
    text: str
    regex: re.Pattern
    fields: tuple[str | None, ...]  # the tag each group fills (None: skipped)

    def match(self, rel: str) -> dict[str, str] | None:
        """The tags this file's path gives (tag -> value), or None when it doesn't fit."""
        stem = posixpath.splitext(rel)[0] if "." in posixpath.basename(rel) else rel
        m = self.regex.search(stem)
        if not m:
            return None
        out: dict[str, str] = {}
        for tag, value in zip(self.fields, m.groups(), strict=True):
            value = " ".join(value.split())
            if tag is None or not value:
                continue
            if tag in ("tracknumber", "discnumber"):
                if not value.isdigit():
                    return None  # "{track}" over a word: this pattern isn't how the file is named
                value = str(int(value))
            if tag == "date" and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", value):
                return None
            if tag in out and out[tag] != value:
                return None
            out[tag] = value
        return out


def compile_pattern(text: str) -> Pattern:
    text = (text or "").strip().strip("/")
    if not text:
        raise PatternError("Type a pattern, like {track} - {title}.")
    if len(text) > 300:
        raise PatternError("That pattern is too long.")
    fields: list[str | None] = []
    parts = []
    for i, piece in enumerate(_PLACEHOLDER.split(text)):
        if i % 2:  # a placeholder
            name = piece.lower()
            if name not in ALIASES:
                known = ", ".join("{" + k + "}" for k in ("track", "title", "artist", "album", "albumartist", "year",
                                                          "disc", "genre", "skip"))
                raise PatternError(f"{{{piece}}} isn't a tag Codetta knows. Use {known}.")
            fields.append(ALIASES[name])
            parts.append(None)
        elif piece:
            parts.append(piece)
    if not any(f for f in fields):
        raise PatternError("Put at least one tag in braces, like {title}.")
    regex = []
    for n, part in enumerate(parts):
        if part is None:
            nxt = parts[n + 1] if n + 1 < len(parts) else None
            # A tag never crosses a folder; the last one in a name takes the rest of it.
            regex.append("([^/]+?)" if nxt is not None else "([^/]+)")
        else:
            regex.append(r"\s+".join(re.escape(w) for w in re.split(r"\s+", part)) if part.strip() else r"\s+")
    try:
        compiled = re.compile(r"(?:^|/)" + "".join(regex).replace(r"\/", "/") + "$")
    except re.error as exc:
        raise PatternError(f"That pattern doesn't work: {exc}") from exc
    return Pattern(text, compiled, tuple(fields))


def suggest(rels: list[str]) -> str | None:
    """The suggestion that reads the most tags across these files, or None if none fits. (Counting
    tags, not files: "{title}" fits every name but says the least.)"""
    best, score = None, 0.0
    for text in SUGGESTIONS:
        p = compile_pattern(text)
        s = 0.0
        for m in (p.match(r) for r in rels):
            if m is not None:  # each tag read counts; one still holding " - " was probably meant to be split
                s += len(m) - 1.5 * sum(" - " in v for v in m.values())
        if s > score:
            best, score = text, s
    return best
