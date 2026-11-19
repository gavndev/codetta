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

from dataclasses import dataclass

from mutagen._vorbis import is_valid_key as _is_valid_vorbis_key
from mutagen.apev2 import TEXT as _APE_TEXT
from mutagen.apev2 import is_valid_apev2_key
from mutagen.asf import ASFBoolAttribute, ASFUnicodeAttribute
from mutagen.easyid3 import EasyID3
from mutagen.easymp4 import EasyMP4Tags
from mutagen.id3 import COMM, MVIN, TIPL, USLT

# Formats grouped by how they store tags. Each family shares one mapping.
VORBIS_FORMATS = frozenset({"flac", "ogg", "opus", "oggflac", "speex"})  # free-form comments
ID3_FORMATS = frozenset({"mp3", "mp2", "tta", "wav", "aiff", "dsf"})  # ID3 frames
ID3_CONTAINERS = frozenset({"wav", "aiff", "dsf"})  # ID3 inside another container (no "easy" class)
APE_FORMATS = frozenset({"wavpack"})  # APEv2 items
ASF_FORMATS = frozenset({"wma"})  # ASF attributes
MP4_FORMATS = frozenset({"m4a"})

# Old mutagen names that now duplicate one of our names (same underlying
# field). They are hidden when reading so each value shows up once.
_ID3_ALIASES = {
    "organization": "label",
    "musicbrainz_albumtype": "releasetype",
    "musicbrainz_albumstatus": "releasestatus",
}
HIDDEN_ALIASES: dict[str, dict[str, str]] = {
    **{fmt: _ID3_ALIASES for fmt in ID3_FORMATS},
    "m4a": {
        "musicbrainz_albumtype": "releasetype",
        "musicbrainz_albumstatus": "releasestatus",
    },
}


@dataclass(frozen=True)
class Field:
    """A well-known tag, as shown in the editor."""

    key: str
    label: str
    group: str
    multi: bool = False  # commonly holds several values (e.g. two artists)


# The editor's fields, in display order. Any other tag a file has still shows
# up (under "Custom"); this list just gives the common ones a home and a label.
FIELDS: tuple[Field, ...] = (
    Field("title", "Title", "Basics"),
    Field("artist", "Artist", "Basics", multi=True),
    Field("album", "Album", "Basics"),
    Field("albumartist", "Album artist", "Basics"),
    Field("tracknumber", "Track", "Basics"),
    Field("discnumber", "Disc", "Basics"),
    Field("date", "Date", "Basics"),
    Field("genre", "Genre", "Basics", multi=True),
    Field("artists", "Artists (all)", "Credits", multi=True),
    Field("albumartists", "Album artists (all)", "Credits", multi=True),
    Field("composer", "Composer", "Credits", multi=True),
    Field("lyricist", "Lyricist", "Credits", multi=True),
    Field("producer", "Producer", "Credits", multi=True),
    Field("engineer", "Engineer", "Credits", multi=True),
    Field("mixer", "Mixer", "Credits", multi=True),
    Field("djmixer", "DJ mixer", "Credits", multi=True),
    Field("arranger", "Arranger", "Credits", multi=True),
    Field("conductor", "Conductor", "Credits", multi=True),
    Field("releasetype", "Release type", "Release"),
    Field("releasestatus", "Release status", "Release"),
    Field("label", "Label", "Release", multi=True),
    Field("catalognumber", "Catalog number", "Release"),
    Field("barcode", "Barcode", "Release"),
    Field("media", "Media", "Release"),
    Field("originaldate", "Original date", "Release"),
    Field("releasecountry", "Release country", "Release"),
    Field("discsubtitle", "Disc subtitle", "Release"),
    Field("compilation", "Compilation (1 = yes)", "Release"),
    # Explicit content, the way Navidrome (OpenSubsonic explicitStatus) and Apple Music read it:
    # 1 = explicit, 2 = clean, 0 = not rated.
    Field("itunesadvisory", "Explicit (1 = explicit, 2 = clean)", "Release"),
    Field("titlesort", "Title sort", "Sorting"),
    Field("artistsort", "Artist sort", "Sorting"),
    Field("albumsort", "Album sort", "Sorting"),
    Field("albumartistsort", "Album artist sort", "Sorting"),
    Field("composersort", "Composer sort", "Sorting"),
    # Classical. Keys follow how Vorbis comments store them (as Picard writes):
    # MOVEMENTNAME is the name, MOVEMENT the number.
    Field("work", "Work", "Classical"),
    Field("movementname", "Movement", "Classical"),
    Field("movement", "Movement number", "Classical"),
    Field("movementtotal", "Movement count", "Classical"),
    Field("showmovement", "Show movement (1 = yes)", "Classical"),
    Field("lyrics", "Lyrics", "Lyrics"),  # plain text or synced LRC ("[01:23.45] line")
    Field("subtitle", "Subtitle", "More"),
    Field("mood", "Mood", "More", multi=True),
    Field("bpm", "BPM", "More"),
    Field("isrc", "ISRC", "More"),
    Field("language", "Language", "More"),
    Field("copyright", "Copyright", "More"),
    Field("grouping", "Grouping", "More"),
    Field("comment", "Comment", "More"),
)


def is_tag_supported(format_name: str, key: str) -> bool:
    """Can a file of ``format_name`` store a tag called ``key``?"""
    key = key.lower()
    if format_name in VORBIS_FORMATS:
        return bool(key) and _is_valid_vorbis_key(key)
    if format_name in ID3_FORMATS:
        return key in EasyID3.valid_keys
    if format_name in MP4_FORMATS:
        return key in EasyMP4Tags.Set
    if format_name in APE_FORMATS:
        name = _APE_NAMES.get(key, key)  # reserved names are blocked in any case ("id3" too)
        return is_valid_apev2_key(name) and name.upper() not in ("ID3", "TAG", "OGGS", "MP+")
    if format_name in ASF_FORMATS:
        return 0 < len(key) <= 255 and key.isprintable() and _asf_name(key) not in _ASF_SYSTEM
    return False


def tag_view(audio, format_name: str, create: bool = False):
    """The file's tags as a mapping of Codetta tag names -> lists of strings.

    For most formats that's mutagen's own (easy) tag object. ID3-in-a-container
    formats (WAV, AIFF, DSF), APEv2 and ASF get a small adapter here, so the
    engine treats every format the same way. ``create`` adds empty tags first.
    """
    if audio.tags is None:
        if not create:
            return {}
        audio.add_tags()
    if format_name in ID3_CONTAINERS:
        view = EasyID3()
        view._EasyID3__id3 = audio.tags  # EasyID3 is a thin layer over an ID3 object
        return view
    if format_name in APE_FORMATS:
        return _APEView(audio.tags)
    if format_name in ASF_FORMATS:
        return _ASFView(audio.tags)
    return audio.tags


class _View:
    """Minimal dict-like base: keys(), items(), get/set/delete by Codetta name."""

    def keys(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def items(self):
        out = []
        for key in self.keys():
            try:
                out.append((key, self[key]))
            except KeyError:
                continue
        return out

    def __contains__(self, key):
        try:
            self[key]
        except KeyError:
            return False
        return True


# --- APEv2 (WavPack) ---------------------------------------------------------

# APEv2 item names are case-insensitive. Standard names where they differ from
# ours (as Picard writes them); everything else uses our name.
_APE_NAMES = {
    "tracknumber": "Track",
    "discnumber": "Disc",
    "date": "Year",
    "albumartist": "Album Artist",
    "releasetype": "MUSICBRAINZ_ALBUMTYPE",
    "releasestatus": "MUSICBRAINZ_ALBUMSTATUS",
}
_FROM_APE = {v.lower(): k for k, v in _APE_NAMES.items()}
_FIELD_KEYS = None  # filled in below, once FIELDS exists


class _APEView(_View):
    def __init__(self, tags):
        self.tags = tags

    def keys(self):
        return [_FROM_APE.get(k.lower(), k.lower()) for k in self.tags.keys() if self.tags[k].kind == _APE_TEXT]

    def _name(self, key):
        if key in _APE_NAMES:
            return _APE_NAMES[key]
        return key.title() if key in _FIELD_KEYS else key  # "Title", "Genre"... like other taggers

    def __getitem__(self, key):
        value = self.tags.get(self._name(key))
        if value is None or value.kind != _APE_TEXT:
            raise KeyError(key)
        return list(value)

    def __setitem__(self, key, values):
        self.tags[self._name(key)] = list(values)

    def __delitem__(self, key):
        del self.tags[self._name(key)]


# --- ASF (WMA) -----------------------------------------------------------------

# Codetta name -> ASF attribute, following Picard.
_ASF_NAMES = {
    "title": "Title",
    "artist": "Author",
    "album": "WM/AlbumTitle",
    "albumartist": "WM/AlbumArtist",
    "tracknumber": "WM/TrackNumber",
    "discnumber": "WM/PartOfSet",
    "date": "WM/Year",
    "genre": "WM/Genre",
    "artists": "WM/ARTISTS",
    "composer": "WM/Composer",
    "lyricist": "WM/Writer",
    "conductor": "WM/Conductor",
    "producer": "WM/Producer",
    "label": "WM/Publisher",
    "catalognumber": "WM/CatalogNo",
    "barcode": "WM/Barcode",
    "isrc": "WM/ISRC",
    "media": "WM/Media",
    "mood": "WM/Mood",
    "bpm": "WM/BeatsPerMinute",
    "language": "WM/Language",
    "copyright": "Copyright",
    "grouping": "WM/ContentGroupDescription",
    "comment": "Description",
    "discsubtitle": "WM/SetSubTitle",
    "compilation": "WM/IsCompilation",
    "originaldate": "WM/OriginalReleaseTime",
    "releasetype": "MusicBrainz/Album Type",
    "releasestatus": "MusicBrainz/Album Status",
    "releasecountry": "MusicBrainz/Album Release Country",
    "titlesort": "WM/TitleSortOrder",
    "artistsort": "WM/ArtistSortOrder",
    "albumsort": "WM/AlbumSortOrder",
    "albumartistsort": "WM/AlbumArtistSortOrder",
    "composersort": "WM/ComposerSortOrder",
    "work": "WM/Work",
    "subtitle": "WM/SubTitle",
    "lyrics": "WM/Lyrics",
    "script": "WM/Script",
    "musicbrainz_trackid": "MusicBrainz/Track Id",
    "musicbrainz_releasetrackid": "MusicBrainz/Release Track Id",
    "musicbrainz_albumid": "MusicBrainz/Album Id",
    "musicbrainz_artistid": "MusicBrainz/Artist Id",
    "musicbrainz_albumartistid": "MusicBrainz/Album Artist Id",
    "musicbrainz_releasegroupid": "MusicBrainz/Release Group Id",
    "musicbrainz_workid": "MusicBrainz/Work Id",
}
_FROM_ASF = {v.lower(): k for k, v in _ASF_NAMES.items()}
# Technical attributes written by encoders: never shown or edited as tags.
_ASF_SYSTEM = frozenset(n.lower() for n in (
    "WM/Picture", "WMFSDKVersion", "WMFSDKNeeded", "IsVBR", "DeviceConformanceTemplate",
    "WM/MediaPrimaryClassID", "WM/WMContentID", "WM/WMCollectionID", "WM/WMCollectionGroupID",
    "WM/EncodingTime", "WM/ToolName", "WM/ToolVersion", "WM/UniqueFileIdentifier",
))


def _asf_name(key: str) -> str:
    return _ASF_NAMES.get(key, key).lower()


class _ASFView(_View):
    def __init__(self, tags):
        self.tags = tags

    def _native(self, key):
        """The attribute name actually used in this file (names are case-insensitive)."""
        wanted = _asf_name(key)
        for name in self.tags.keys():
            if name.lower() == wanted:
                return name
        return _ASF_NAMES.get(key, key)

    @staticmethod
    def _text(attr):
        if isinstance(attr, ASFBoolAttribute):
            return "1" if attr.value else "0"
        value = attr.value
        return value if isinstance(value, str) else str(value) if isinstance(value, int) else None

    def keys(self):
        out = []
        for name in self.tags.keys():
            if name.lower() in _ASF_SYSTEM:
                continue
            if any(self._text(a) is not None for a in self.tags[name]):
                out.append(_FROM_ASF.get(name.lower(), name.lower()))
        return out

    def __getitem__(self, key):
        name = self._native(key)
        if name.lower() in _ASF_SYSTEM or name not in self.tags.keys():
            raise KeyError(key)
        values = [t for t in (self._text(a) for a in self.tags[name]) if t is not None]
        if not values:
            raise KeyError(key)
        return values

    def __setitem__(self, key, values):
        self.tags[self._native(key)] = [ASFUnicodeAttribute(v) for v in values]

    def __delitem__(self, key):
        del self.tags[self._native(key)]


# --- MP3 (ID3) ---------------------------------------------------------------

# Plain text frames / user-defined TXXX frames.
EasyID3.RegisterTextKey("label", "TPUB")
EasyID3.RegisterTXXXKey("releasetype", "MusicBrainz Album Type")
EasyID3.RegisterTXXXKey("releasestatus", "MusicBrainz Album Status")
EasyID3.RegisterTXXXKey("artists", "ARTISTS")
EasyID3.RegisterTXXXKey("albumartists", "ALBUMARTISTS")
EasyID3.RegisterTextKey("subtitle", "TIT3")
EasyID3.RegisterTextKey("movementname", "MVNM")
EasyID3.RegisterTXXXKey("work", "WORK")
EasyID3.RegisterTXXXKey("showmovement", "SHOWMOVEMENT")
EasyID3.RegisterTXXXKey("script", "SCRIPT")
EasyID3.RegisterTXXXKey("itunesadvisory", "ITUNESADVISORY")


def _register_id3_movement() -> None:
    """``movement`` / ``movementtotal`` share the MVIN frame ("2/4")."""

    def parts(id3):
        frame = id3.get("MVIN")
        text = str(frame.text[0]) if frame and frame.text else ""
        number, _, total = text.partition("/")
        return number.strip(), total.strip()

    def write(id3, number, total):
        id3.delall("MVIN")
        if number or total:
            id3.add(MVIN(encoding=3, text=[f"{number}/{total}" if total else number]))

    def make(index):
        def get(id3, key):
            value = parts(id3)[index]
            if not value:
                raise KeyError(key)
            return [value]

        def set_(id3, key, value):
            if len(value) != 1:
                raise ValueError(f"{key} takes a single value")
            current = list(parts(id3))
            current[index] = value[0].strip()
            write(id3, *current)

        def delete(id3, key):
            current = list(parts(id3))
            current[index] = ""
            write(id3, *current)

        return get, set_, delete

    EasyID3.RegisterKey("movement", *make(0))
    EasyID3.RegisterKey("movementtotal", *make(1))


_register_id3_movement()


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
    Each Codetta tag reads and writes only the pairs for its own role.
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


def _register_id3_lyrics() -> None:
    """``lyrics`` -> the USLT frame with an empty description (what Picard,
    Navidrome and most players use; synced LRC text works here too)."""

    def keys(id3):
        return [k for k in id3.keys() if k.startswith("USLT:") and id3[k].desc == ""]

    def get(id3, key):
        values = [id3[k].text for k in keys(id3) if id3[k].text]
        if not values:
            raise KeyError(key)
        return values

    def delete(id3, key):
        for k in keys(id3):
            del id3[k]

    def set_(id3, key, value):
        delete(id3, key)
        id3.add(USLT(encoding=3, lang="eng", desc="", text="\n".join(value)))

    EasyID3.RegisterKey("lyrics", get, set_, delete)


_register_id3_lyrics()
for _key, _role in {
    "engineer": "engineer",
    "mixer": "mix",
    "producer": "producer",
    "djmixer": "DJ-mix",
}.items():
    _register_id3_credit(_key, _role)


# --- M4A (MP4 atoms) -----------------------------------------------------------

EasyMP4Tags.RegisterTextKey("composer", "\xa9wrt")
EasyMP4Tags.RegisterTextKey("work", "\xa9wrk")
EasyMP4Tags.RegisterTextKey("lyrics", "\xa9lyr")
EasyMP4Tags.RegisterTextKey("movementname", "\xa9mvn")
EasyMP4Tags.RegisterIntKey("movement", "\xa9mvi", min_value=0, max_value=65535)
EasyMP4Tags.RegisterIntKey("movementtotal", "\xa9mvc", min_value=0, max_value=65535)
EasyMP4Tags.RegisterIntKey("showmovement", "shwm", min_value=0, max_value=1)

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
    "subtitle": "SUBTITLE",
    "script": "SCRIPT",
    # mutagen already knows the album/artist/track IDs; these complete Picard's set.
    "musicbrainz_releasetrackid": "MusicBrainz Release Track Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    "musicbrainz_workid": "MusicBrainz Work Id",
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


def _register_mp4_advisory() -> None:
    """``itunesadvisory`` -> Apple's ``rtng`` atom (a number): "1" explicit, "2" clean, "0" none."""

    def get(tags, key):
        return [str(v) for v in tags["rtng"]]

    def set_(tags, key, value):
        if len(value) != 1 or value[0] not in ("0", "1", "2", "4"):
            raise ValueError("explicit must be 1 (explicit), 2 (clean) or 0 (not rated)")
        tags["rtng"] = [int(value[0])]

    def delete(tags, key):
        del tags["rtng"]

    EasyMP4Tags.RegisterKey("itunesadvisory", get, set_, delete)


_register_mp4_advisory()


_FIELD_KEYS = frozenset(f.key for f in FIELDS)
