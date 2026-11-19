"""Tidy-up actions that ship with Codetta, written exactly like a plugin anyone could write."""

from __future__ import annotations

import re

# Things download sites add to titles.
_NOISE = re.compile(
    r"\s*[\(\[]\s*(official\s+(music\s+)?(video|audio|lyric video|visualizer)|lyrics?|audio|hq|hd|"
    r"explicit|clean|free\s*(dl|download)|visualizer)\s*[\)\]]", re.IGNORECASE)
_FEAT = re.compile(r"\b(?:ft|feat|featuring)\b\.?(?=\s)", re.IGNORECASE)  # "ft", "ft.", "Feat", "featuring" -> "feat."
_SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of", "on", "or", "the", "to", "vs", "via"}
_ALWAYS_LOWER = {"feat", "ft", "vs", "x"}  # "Song ft. Zayn", "A vs. B": lower case wherever they are


def _title_case(text: str) -> str:
    words = text.split(" ")
    out = []
    for i, w in enumerate(words):
        if not w:
            out.append(w)
            continue
        core = w.strip("([{\"'")
        if w.isupper() and len(core) > 1 and not core.isalpha():  # "BPM", "R&B", "4x4": leave them
            out.append(w)
        elif core.lower().rstrip(".") in _ALWAYS_LOWER and i > 0:
            out.append(w.lower())
        elif 0 < i < len(words) - 1 and core.lower() in _SMALL:
            out.append(w.lower())
        else:
            lead = len(w) - len(w.lstrip("([{\"'"))
            out.append(w[:lead] + w[lead:lead + 1].upper() + w[lead + 1:].lower() if not any(c.isupper() for c in w[lead + 1:])
                       or w.isupper() else w)
    return " ".join(out)


def _each(tags: dict, key: str, fn) -> dict | None:
    old = tags.get(key) or []
    new = [fn(v) for v in old]
    return {key: new} if new != old else None


def setup(codetta) -> None:
    codetta.add_action(
        id="clean-titles", label="Clean up titles",
        description="Remove “(Official Video)”, “[Explicit]”, “(Lyrics)”, “(Free DL)” and similar from titles.",
        fields=["title"],
        run=lambda tags: _each(tags, "title", lambda t: " ".join(_NOISE.sub("", t).split())),
    )
    codetta.add_action(
        id="feat", label="Write features as “feat.”",
        description="Turn “ft.”, “ft”, “featuring” into “feat.” in titles and artists.",
        fields=["title", "artist"],
        run=lambda tags: {**(_each(tags, "title", lambda t: _FEAT.sub("feat.", t)) or {}),
                          **(_each(tags, "artist", lambda t: _FEAT.sub("feat.", t)) or {})} or None,
    )
    codetta.add_action(
        id="title-case", label="Title Case",
        description="Capitalise titles: “night drive in the city” → “Night Drive in the City”. Words in capitals stay.",
        fields=["title"],
        run=lambda tags: _each(tags, "title", _title_case),
    )
    codetta.add_action(
        id="trim", label="Trim spaces",
        description="Remove extra spaces at the start, end and inside every text tag.",
        fields=["title", "artist", "album", "albumartist", "genre"],
        run=lambda tags: {k: [" ".join(v.split()) for v in tags.get(k, [])] for k in
                          ("title", "artist", "album", "albumartist", "genre")
                          if [" ".join(v.split()) for v in tags.get(k, [])] != (tags.get(k) or [])} or None,
    )
