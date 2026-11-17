"""One shared tag vocabulary across every audio format.

FLAC, OGG Vorbis and Opus store tags as free-form "Vorbis comments", so any
name works (``MOOD=Chill``). MP3 (ID3) and M4A (MP4 atoms) only understand a
fixed set of fields, and mutagen's "easy" interface leaves out many tags that
Navidrome / OpenSubsonic clients display (mood, release type, label, credits,
multi-artist lists, ...).

Importing this module registers those missing names with mutagen, using the
same storage locations MusicBrainz Picard uses, which is what Navidrome (via
TagLib) reads. After that, ``engine.update_tags(path, {"mood": "Chill"})``
works the same on every format.
"""

from __future__ import annotations

from mutagen._vorbis import is_valid_key as _is_valid_vorbis_key
from mutagen.easyid3 import EasyID3
from mutagen.easymp4 import EasyMP4Tags
from mutagen.id3 import COMM, TIPL

VORBIS_FORMATS = frozenset({"flac", "ogg", "opus"})

# Old mutagen names that now duplicate one of our names (same underlying
# field). They are hidden when reading so each value shows up once.
HIDDEN_ALIASES: dict[str, dict[str, str]] = {
    "mp3": {
        "organization": "label",
        "musicbrainz_albumtype": "releasetype",
        "musicbrainz_albumstatus": "releasestatus",
    },
    "m4a": {
        "musicbrainz_albumtype": "releasetype",
        "musicbrainz_albumstatus": "releasestatus",
    },
}


def is_tag_supported(format_name: str, key: str) -> bool:
    """Can a file of ``format_name`` store a tag called ``key``?"""
    key = key.lower()
    if format_name in VORBIS_FORMATS:
        return bool(key) and _is_valid_vorbis_key(key)
    if format_name == "mp3":
        return key in EasyID3.valid_keys
    if format_name == "m4a":
        return key in EasyMP4Tags.Set
    return False


# --- MP3 (ID3) ---------------------------------------------------------------

# Plain text frames / user-defined TXXX frames.
EasyID3.RegisterTextKey("label", "TPUB")
EasyID3.RegisterTXXXKey("releasetype", "MusicBrainz Album Type")
EasyID3.RegisterTXXXKey("releasestatus", "MusicBrainz Album Status")
EasyID3.RegisterTXXXKey("artists", "ARTISTS")
EasyID3.RegisterTXXXKey("albumartists", "ALBUMARTISTS")


def _register_id3_comment() -> None:
    """``comment`` -> COMM frame with an empty description."""

    def keys(id3):
        # Leave other comments alone (e.g. iTunes' "iTunNORM" volume data).
        return [k for k in id3.keys() if k.startswith("COMM:") and id3[k].desc == ""]

    def get(id3, key):
        values = [text for k in keys(id3) for text in id3[k].text]
        if not values:
            raise KeyError(key)
        return values

    def delete(id3, key):
        for k in keys(id3):
            del id3[k]

    def set_(id3, key, value):
        delete(id3, key)
        id3.add(COMM(encoding=3, lang="eng", desc="", text=list(value)))

    EasyID3.RegisterKey("comment", get, set_, delete)


def _register_id3_credit(key: str, role: str) -> None:
    """Credits like engineer/mixer live in the TIPL "involved people" frame.

    TIPL holds [role, name] pairs, e.g. [["engineer", "Ann"], ["mix", "Bob"]].
    Each Coda tag reads and writes only the pairs for its own role.
    """

    def people(id3):
        frame = id3.get("TIPL")
        return list(frame.people) if frame else []

    def get(id3, k):
        names = [name for r, name in people(id3) if r == role]
        if not names:
            raise KeyError(k)
        return names

    def set_(id3, k, value):
        others = [[r, name] for r, name in people(id3) if r != role]
        pairs = others + [[role, v] for v in value]
        id3.delall("TIPL")
        if pairs:
            id3.add(TIPL(encoding=3, people=pairs))

    def delete(id3, k):
        set_(id3, k, [])

    EasyID3.RegisterKey(key, get, set_, delete)


_register_id3_comment()
for _key, _role in {
    "engineer": "engineer",
    "mixer": "mix",
    "producer": "producer",
    "djmixer": "DJ-mix",
}.items():
    _register_id3_credit(_key, _role)


# --- M4A (MP4 atoms) -----------------------------------------------------------

EasyMP4Tags.RegisterTextKey("composer", "\xa9wrt")

# Everything else uses iTunes-style "freeform" atoms
# (----:com.apple.iTunes:NAME), as Picard does.
for _key, _atom_name in {
    "artists": "ARTISTS",
    "albumartists": "ALBUMARTISTS",
    "originaldate": "ORIGINALDATE",
    "discsubtitle": "DISCSUBTITLE",
    "releasetype": "MusicBrainz Album Type",
    "releasestatus": "MusicBrainz Album Status",
    "label": "LABEL",
    "catalognumber": "CATALOGNUMBER",
    "barcode": "BARCODE",
    "isrc": "ISRC",
    "media": "MEDIA",
    "mood": "MOOD",
    "lyricist": "LYRICIST",
    "conductor": "CONDUCTOR",
    "arranger": "ARRANGER",
    "engineer": "ENGINEER",
    "mixer": "MIXER",
    "producer": "PRODUCER",
    "djmixer": "DJMIXER",
    "language": "LANGUAGE",
}.items():
    EasyMP4Tags.RegisterFreeformKey(_key, _atom_name)


def _register_mp4_compilation() -> None:
    """``compilation`` -> the boolean ``cpil`` atom. Values are "1" or "0"."""

    def get(tags, key):
        return ["1" if tags["cpil"] else "0"]

    def set_(tags, key, value):
        if len(value) != 1 or value[0] not in ("0", "1"):
            raise ValueError("compilation must be '1' or '0'")
        tags["cpil"] = value[0] == "1"

    def delete(tags, key):
        del tags["cpil"]

    EasyMP4Tags.RegisterKey("compilation", get, set_, delete)


_register_mp4_compilation()
