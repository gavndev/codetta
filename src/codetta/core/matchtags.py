"""Match album tags: give stray tracks the same album-wide tags as the rest of their album.

A track that "won't group" in a music player usually differs in one album-wide tag (a
slightly different album artist, a missing release ID, another date). Matching copies every
tag that isn't about the song itself from a reference (one track, or what most tracks in a
folder share) onto the chosen tracks, so players see one album.

What stays per song (never copied, never removed): see ``TRACK_KEYS``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

# Tags that describe the song, not the album. Everything else is album-wide.
TRACK_KEYS = frozenset({
    # what the song is and who made it
    "title", "titlesort", "subtitle", "artist", "artists", "artistsort", "work",
    "composer", "composersort", "lyricist", "arranger", "conductor", "producer", "engineer",
    "mixer", "djmixer", "remixer", "performer", "writer",
    # where it sits on the album
    "tracknumber", "tracktotal", "totaltracks", "discnumber", "disctotal", "totaldiscs", "discsubtitle",
    # this recording's own details
    "isrc", "bpm", "initialkey", "key", "mood", "lyrics", "unsyncedlyrics", "syncedlyrics", "comment",
    "replaygain_track_gain", "replaygain_track_peak",
    "musicbrainz_trackid", "musicbrainz_releasetrackid", "musicbrainz_recordingid", "musicbrainz_artistid",
    "musicbrainz_workid", "acoustid_id", "acoustid_fingerprint",
    # how this file was made
    "encoder", "encodedby", "encodersettings", "encoding", "encodingtime", "vendor", "itunsmpb", "itunnorm",
})


def is_track_key(key: str) -> bool:
    k = key.lower()
    return k in TRACK_KEYS or "lyrics" in k or k.startswith("acoustid")


def album_tags(tags: Mapping[str, list[str]]) -> dict[str, list[str]]:
    """The album-wide tags of one track."""
    return {k: list(v) for k, v in tags.items() if v and not is_track_key(k)}


def shared_album_tags(tracks: Iterable[Mapping[str, list[str]]]) -> dict[str, list[str]]:
    """What a folder's tracks agree on: for each album-wide tag that more than half of them
    have, the value most of them use (ties: the first one seen)."""
    tracks = list(tracks)
    if not tracks:
        return {}
    counts: dict[str, Counter] = {}
    for tags in tracks:
        for key, values in album_tags(tags).items():
            counts.setdefault(key, Counter())[tuple(values)] += 1
    out = {}
    for key, c in counts.items():
        if sum(c.values()) * 2 > len(tracks):
            out[key] = list(c.most_common(1)[0][0])
    return out


def changes_for(tags: Mapping[str, list[str]], reference: Mapping[str, list[str]], remove_extra: bool) -> dict:
    """The tag changes that make one track's album-wide tags the same as ``reference``
    (``None`` removes a tag). Per-song tags are never touched."""
    changes: dict[str, list[str] | None] = {}
    for key, values in reference.items():
        if list(tags.get(key) or []) != list(values):
            changes[key] = list(values)
    if remove_extra:
        for key, values in tags.items():
            if values and key not in reference and not is_track_key(key):
                changes[key] = None
    return changes
