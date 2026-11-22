"""Tag tools that ship with Codetta: change case, fix garbled text, split / join / de-duplicate
values, and keep only the tags that matter. Written like any plugin (see tidy.py)."""

from __future__ import annotations

import re
import unicodedata

from codetta.plugins.builtin.tidy import _title_case

NAME = "Tag tools"
NOT_TEXT = re.compile(r"^(musicbrainz_|replaygain_|r128_|acoustid_|itunnorm|itunsmpb|isrc$|barcode$)")
FIELD_SETS = {
    "title": ("title",),
    "artist": ("artist", "albumartist", "artists", "albumartists"),
    "album": ("album",),
    "genre": ("genre",),
}
CASES = [["upper", "UPPER CASE"], ["lower", "lower case"], ["title", "Title Case"], ["sentence", "Sentence case"]]
SEPARATORS = [[";", "Semicolon (Rock; Pop)"], ["/", "Slash (Rock / Pop)"], [",", "Comma (Rock, Pop)"], ["&", "Ampersand (A & B)"]]
MULTI = ("genre", "artist", "albumartist", "artists", "albumartists", "composer", "lyricist", "producer", "mood", "label")
ALWAYS_KEPT = ("lyrics", "compilation", "itunesadvisory")  # plus replaygain_* / r128_* and the cover (not a text tag)
KEEP_SETS = {
    "basics": ("title", "artist", "album", "albumartist", "tracknumber", "tracktotal", "totaltracks", "discnumber",
               "disctotal", "totaldiscs", "date", "genre"),
}
KEEP_SETS["ids"] = KEEP_SETS["basics"] + ("originaldate", "releasetype", "releasestatus", "releasecountry", "label",
                                          "catalognumber", "barcode", "isrc", "media", "discsubtitle", "script")
KEEP_SETS["credits"] = KEEP_SETS["ids"] + ("artists", "albumartists", "composer", "lyricist", "producer", "engineer",
                                           "mixer", "djmixer", "remixer", "arranger", "conductor", "titlesort",
                                           "artistsort", "albumsort", "albumartistsort", "composersort", "work",
                                           "movementname", "movement", "movementtotal", "showmovement", "mood", "bpm")


def text_keys(tags: dict, which: str) -> list[str]:
    if which == "all":
        return [k for k in tags if not NOT_TEXT.match(k) and k != "lyrics"]
    return [k for k in FIELD_SETS[which] if k in tags]


def change_case(text: str, style: str) -> str:
    if style == "upper":
        return text.upper()
    if style == "lower":
        return text.lower()
    if style == "title":
        return _title_case(text.lower() if text.isupper() else text)
    low = text.lower()  # sentence case: only the first letter capital
    i = next((n for n, ch in enumerate(low) if ch.isalpha()), None)
    return low if i is None else low[:i] + low[i].upper() + low[i + 1:]


# --- Garbled text ("BeyoncÃ©", "Êèíî") ------------------------------------------------------------

_SCRIPTS = {"cp1251": "CYRILLIC", "shift_jis": ("CJK", "HIRAGANA", "KATAKANA"), "gbk": "CJK", "cp949": ("HANGUL", "CJK")}


def _as_bytes(text: str) -> bytes | None:
    """The bytes a program showed as this text when it wrongly read them as Windows-1252 (bytes
    Windows-1252 has no letter for show up as the Latin-1 control characters of the same number)."""
    out = bytearray()
    for ch in text:
        try:
            out += ch.encode("cp1252")
        except UnicodeEncodeError:
            if ord(ch) > 0xFF:
                return None
            out.append(ord(ch))
    return bytes(out)


def fix_garbled(text: str, source: str) -> str:
    """Undo a wrong reading, only when it's clearly one: the text must turn back into bytes and
    those bytes must read cleanly in ``source``, giving letters of the expected script."""
    if text.isascii():
        return text
    raw = _as_bytes(text)
    if raw is None:
        return text
    try:
        fixed = raw.decode("utf-8" if source == "utf8" else source)
    except UnicodeDecodeError:
        return text
    if fixed == text or "�" in fixed:
        return text
    if source == "utf8":
        return fixed  # strict UTF-8 decoding of Latin-looking text practically never succeeds by chance
    wanted = _SCRIPTS[source]
    wanted = (wanted,) if isinstance(wanted, str) else wanted
    letters = [ch for ch in fixed if ch.isalpha()]
    native = [ch for ch in letters if any(w in unicodedata.name(ch, "") for w in wanted)]
    strays = [ch for ch in letters if not ch.isascii() and ch not in native]
    # Real garbled Cyrillic or Japanese comes back as mostly that script; a correct name that merely has
    # an accent ("Beyoncé") would become one odd letter among Latin ones: leave those.
    if strays or len(native) < 2 or len(native) < 0.5 * len(letters):
        return text
    return fixed


# --- Running them ---------------------------------------------------------------------------------

def _each(tags: dict, keys: list[str], fn) -> dict | None:
    out = {}
    for k in keys:
        old = tags.get(k) or []
        new = [fn(v) for v in old]
        if new != old:
            out[k] = new
    return out or None


def split_values(tags: dict, o: dict) -> dict | None:
    sep = o["separator"]
    keys = MULTI if o["field"] == "all" else (o["field"],)
    pattern = re.compile(r"\s*" + re.escape(sep) + r"\s*")
    out = {}
    for k in keys:
        old = tags.get(k) or []
        new = [p for v in old for p in (x.strip() for x in pattern.split(v)) if p]
        if new != old:
            out[k] = new
    return out or None


def join_values(tags: dict, o: dict) -> dict | None:
    sep = {";": "; ", "/": " / ", ",": ", ", "&": " & "}[o["separator"]]
    keys = MULTI if o["field"] == "all" else (o["field"],)
    return {k: [sep.join(tags[k])] for k in keys if len(tags.get(k) or []) > 1} or None


def dedupe(tags: dict) -> dict | None:
    out = {}
    for k, values in tags.items():
        seen, kept = set(), []
        for v in values:
            key = " ".join(v.split()).casefold()
            if key not in seen:
                seen.add(key)
                kept.append(v)
        if kept != values:
            out[k] = kept
    return out or None


def keep_only(tags: dict, o: dict) -> dict | None:
    keep = set(KEEP_SETS[o["set"]]) | set(ALWAYS_KEPT)
    gone = {k: None for k in tags if k not in keep and not k.startswith(("replaygain_", "r128_"))
            and not (o["set"] != "basics" and k.startswith("musicbrainz_"))}
    return gone or None


def setup(codetta) -> None:
    field_choice = {"id": "field", "label": "Tags", "choices": [["title", "Titles"], ["artist", "Artists"],
                                                                ["album", "Albums"], ["genre", "Genres"], ["all", "All text tags"]]}
    codetta.add_action(
        id="case", label="Change case",
        description="UPPER CASE, lower case, Title Case or Sentence case, on titles, artists, albums or every text tag.",
        fields=["title", "artist", "album"],
        options=[field_choice, {"id": "style", "label": "Make it", "choices": CASES}],
        run=lambda tags, o: _each(tags, text_keys(tags, o["field"]), lambda v: change_case(v, o["style"])),
    )
    codetta.add_action(
        id="fix-garbled", label="Fix garbled text",
        description="Repair names a program read in the wrong text encoding: “BeyoncÃ©” → “Beyoncé”, or Cyrillic, "
                    "Japanese, Chinese and Korean from old Windows rips. Only clear cases change.",
        fields=["title", "artist", "album"],
        options=[{"id": "source", "label": "It should be", "choices": [
            ["utf8", "Accents and symbols (BeyoncÃ© → Beyoncé)"], ["cp1251", "Cyrillic (Windows-1251)"],
            ["shift_jis", "Japanese (Shift-JIS)"], ["gbk", "Chinese (GBK)"], ["cp949", "Korean (CP949)"]]}],
        run=lambda tags, o: _each(tags, [k for k in tags if not NOT_TEXT.match(k)], lambda v: fix_garbled(v, o["source"])),
    )
    multi_choice = {"id": "field", "label": "Tags", "choices": [["genre", "Genres"], ["artist", "Artists"],
                                                                ["albumartist", "Album artists"], ["composer", "Composers"],
                                                                ["mood", "Moods"], ["all", "All of these"]]}
    codetta.add_action(
        id="split", label="Split into separate values",
        description="Turn “Rock; Pop” into two genres (players show and search each one), using the separator you pick.",
        fields=["genre", "artist"],
        options=[multi_choice, {"id": "separator", "label": "At each", "choices": SEPARATORS}],
        run=split_values,
    )
    codetta.add_action(
        id="join", label="Join into one value",
        description="Turn several values into one (“Rock; Pop”), for players that only show the first.",
        fields=["genre", "artist"],
        options=[multi_choice, {"id": "separator", "label": "With", "choices": SEPARATORS}],
        run=join_values,
    )
    codetta.add_action(
        id="dedupe", label="Remove duplicate values",
        description="Drop repeated values in any tag (“Rock; rock; Pop” → “Rock; Pop”), ignoring capitals and spaces.",
        fields=["genre", "artist"],
        run=dedupe,
    )
    codetta.add_action(
        id="keep-only", label="Keep only the essentials",
        description="Remove every other tag (encoder notes, old ratings, leftovers from other apps). Covers, lyrics "
                    "and ReplayGain always stay.",
        fields=[],
        options=[{"id": "set", "label": "Keep", "choices": [
            ["credits", "Basics, release details, IDs and credits"], ["ids", "Basics, release details and IDs"],
            ["basics", "Only the basics (title, artist, album, numbers, date, genre)"]]}],
        run=keep_only,
    )
