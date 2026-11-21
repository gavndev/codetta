"""Deezer and iTunes: extra sources for album details and covers, next to MusicBrainz.

Both are free and need no account. They're opt-in connections, used when MusicBrainz is off, down,
or has nothing for an album (new releases often reach Deezer and iTunes first), and for covers the
Cover Art Archive doesn't have. Only the album and artist names you search for are sent.

Their albums are turned into the same shape as a MusicBrainz release, so matching, the per-file
review, safe writing and undo all work the same. Ids look like "deezer:302127" / "itunes:1440857781";
nothing from these sources is ever written as a MusicBrainz ID.
"""

from __future__ import annotations

import threading
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable

DEEZER_API = "https://api.deezer.com"
ITUNES_API = "https://itunes.apple.com"
SOURCES = ("deezer", "itunes")
Fetcher = Callable[[str], object]  # url -> parsed JSON (or None)


def is_catalog_id(release_id: str) -> bool:
    return release_id.split(":", 1)[0] in SOURCES and ":" in release_id


class Catalogs:
    def __init__(self, fetch: Fetcher, enabled: Callable[[str], bool]) -> None:
        self.fetch = fetch
        self.enabled = enabled  # source -> is its connection on?
        self._releases: OrderedDict[str, dict] = OrderedDict()  # recent lookups (covers and re-opens)
        self._lock = threading.Lock()

    def available(self) -> list[str]:
        return [s for s in SOURCES if self.enabled(s)]

    # --- Searching ---------------------------------------------------------------------------

    def search(self, album: str, artist: str = "", limit: int = 6) -> list[dict]:
        """Albums from every source that's switched on, as release-shaped dicts (no track lists)."""
        out: list[dict] = []
        if self.enabled("deezer"):
            out += self._deezer_search(album, artist, limit)
        if self.enabled("itunes"):
            out += self._itunes_search(album, artist, limit)
        return out

    def _deezer_search(self, album: str, artist: str, limit: int) -> list[dict]:
        parts = [f'album:"{album}"' if album else "", f'artist:"{artist}"' if artist else ""]
        q = urllib.parse.quote(" ".join(p for p in parts if p))
        data = self.fetch(f"{DEEZER_API}/search/album?q={q}&limit={limit}") or {}
        return [_deezer_summary(a) for a in (data.get("data") or []) if isinstance(a, dict) and a.get("id")]

    def _itunes_search(self, album: str, artist: str, limit: int) -> list[dict]:
        term = urllib.parse.quote(" ".join(p for p in (artist, album) if p))
        data = self.fetch(f"{ITUNES_API}/search?term={term}&entity=album&media=music&limit={limit}") or {}
        return [_itunes_summary(a) for a in (data.get("results") or [])
                if isinstance(a, dict) and a.get("collectionId") and a.get("wrapperType") == "collection"]

    def search_text(self, source: str, text: str, limit: int = 24) -> list[dict]:
        """Albums matching free text on one source (the !dz and !it bangs), as release-shaped dicts."""
        if source not in SOURCES or not self.enabled(source):
            raise LookupError(f"{source.title()} isn't on")
        q = urllib.parse.quote(text.strip())
        if source == "deezer":
            data = self.fetch(f"{DEEZER_API}/search/album?q={q}&limit={limit}") or {}
            return [_deezer_summary(a) for a in (data.get("data") or []) if isinstance(a, dict) and a.get("id")]
        data = self.fetch(f"{ITUNES_API}/search?term={q}&entity=album&media=music&limit={limit}") or {}
        return [_itunes_summary(a) for a in (data.get("results") or [])
                if isinstance(a, dict) and a.get("collectionId") and a.get("wrapperType") == "collection"]

    # --- One album, with its tracks -----------------------------------------------------------

    def release(self, release_id: str) -> dict:
        with self._lock:
            if release_id in self._releases:
                self._releases.move_to_end(release_id)
                return self._releases[release_id]
        source, _, raw = release_id.partition(":")
        if not raw.isdigit() or not self.enabled(source):
            raise LookupError("That album isn't available (is its connection on?)")
        rel = self._deezer_release(raw) if source == "deezer" else self._itunes_release(raw)
        with self._lock:
            self._releases[release_id] = rel
            while len(self._releases) > 32:
                self._releases.popitem(last=False)
        return rel

    def _deezer_release(self, album_id: str) -> dict:
        a = self.fetch(f"{DEEZER_API}/album/{album_id}") or {}
        if not a.get("id"):
            raise LookupError("Deezer doesn't have that album")
        tracks = list(((a.get("tracks") or {}).get("data")) or [])
        nb = a.get("nb_tracks") or len(tracks)
        if len(tracks) < nb:  # long albums come in pages
            more = self.fetch(f"{DEEZER_API}/album/{album_id}/tracks?limit=500") or {}
            tracks = list(more.get("data") or tracks)
        rel = _deezer_summary(a)
        discs: dict[int, list[dict]] = {}
        for i, t in enumerate(tracks, 1):
            discs.setdefault(int(t.get("disk_number") or 1), []).append({
                "position": int(t.get("track_position") or i), "title": t.get("title") or "",
                "length": int(t.get("duration") or 0) * 1000 or None,
                "artist-credit": _credit((t.get("artist") or {}).get("name") or rel["_artist"]),
                "isrc": t.get("isrc") or "",
            })
        rel["media"] = _media(discs, "Digital Media", "deezer")
        rel["genres"] = [{"name": g.get("name"), "count": 1} for g in ((a.get("genres") or {}).get("data") or []) if g.get("name")]
        return rel

    def _itunes_release(self, collection_id: str) -> dict:
        data = self.fetch(f"{ITUNES_API}/lookup?id={collection_id}&entity=song&limit=200") or {}
        results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        album = next((r for r in results if r.get("wrapperType") == "collection"), None)
        if album is None:
            raise LookupError("iTunes doesn't have that album")
        rel = _itunes_summary(album)
        discs: dict[int, list[dict]] = {}
        for t in results:
            if t.get("wrapperType") != "track":
                continue
            discs.setdefault(int(t.get("discNumber") or 1), []).append({
                "position": int(t.get("trackNumber") or 0), "title": t.get("trackName") or "",
                "length": int(t.get("trackTimeMillis") or 0) or None,
                "artist-credit": _credit(t.get("artistName") or rel["_artist"]), "isrc": "",
            })
        rel["media"] = _media(discs, "Digital Media", "itunes")
        genre = album.get("primaryGenreName")
        rel["genres"] = [{"name": genre, "count": 1}] if genre and genre != "Music" else []
        return rel

    def cover(self, release_id: str) -> str | None:
        """The biggest cover the source offers for this album."""
        try:
            return self.release(release_id).get("_cover") or None
        except LookupError:
            return None

    def find_cover(self, album: str, artist: str) -> str | None:
        """A cover for an album found by name (when the Cover Art Archive has none)."""
        for found in self.search(album, artist, limit=3):
            if found.get("_cover") and _close(found.get("title", ""), album):
                return found["_cover"]
        return None


# --- Turning their answers into release-shaped dicts ----------------------------------------------


def _credit(name: str) -> list[dict]:
    return [{"name": name, "joinphrase": "", "artist": {"id": "", "name": name, "sort-name": name}}] if name else []


def _media(discs: dict[int, list[dict]], fmt: str, source: str = "catalog") -> list[dict]:
    """Discs and tracks as MusicBrainz shapes them. Each track gets its own internal id (the matcher
    tells tracks apart by id); ids from these sources are never written to files."""
    media = []
    for disc in sorted(discs):
        tracks = sorted(discs[disc], key=lambda t: t["position"])
        media.append({"position": disc, "format": fmt, "track-count": len(tracks), "tracks": [
            {"id": f"{source}-{disc}-{t['position']}", "position": t["position"], "number": str(t["position"]),
             "title": t["title"], "length": t["length"], "artist-credit": t["artist-credit"],
             "recording": {"id": f"{source}-rec-{disc}-{t['position']}", "title": t["title"], "length": t["length"],
                           "isrcs": [t["isrc"]] if t["isrc"] else []}}
            for t in tracks]})
    return media


def _base(source: str, rid: str, title: str, artist: str, date: str, cover: str, url: str, kind: str,
          label: str = "", barcode: str = "", tracks: int | None = None) -> dict:
    types = {"album": "Album", "single": "Single", "ep": "EP", "compile": "Album"}
    return {
        "id": f"{source}:{rid}", "_source": source, "_artist": artist, "_cover": cover, "_url": url,
        "title": title, "date": date, "country": "", "status": "Official", "barcode": barcode,
        "artist-credit": _credit(artist),
        "release-group": {"id": "", "primary-type": types.get((kind or "album").lower(), "Album"), "secondary-types": []},
        "label-info": [{"label": {"name": label}}] if label else [],
        "track-count": tracks, "media": [], "cover-art-archive": {"front": bool(cover)},
    }


def _deezer_summary(a: dict) -> dict:
    artist = (a.get("artist") or {}).get("name") or ""
    return _base("deezer", str(a["id"]), a.get("title") or "", artist, a.get("release_date") or "",
                 a.get("cover_xl") or a.get("cover_big") or "", a.get("link") or f"https://www.deezer.com/album/{a['id']}",
                 a.get("record_type") or "album", a.get("label") or "", a.get("upc") or "", a.get("nb_tracks"))


def _itunes_summary(a: dict) -> dict:
    art = a.get("artworkUrl100") or ""
    big = art.replace("100x100bb", "1200x1200bb") if "100x100bb" in art else art
    date = (a.get("releaseDate") or "")[:10]
    kind = "single" if a.get("collectionName", "").endswith(" - Single") else "ep" if a.get("collectionName", "").endswith(" - EP") else "album"
    title = a.get("collectionName") or ""
    for suffix in (" - Single", " - EP"):
        title = title[: -len(suffix)] if title.endswith(suffix) else title
    label = (a.get("copyright") or "").lstrip("℗© ").split(" under ")[0].strip()
    label = label[5:].strip() if label[:4].isdigit() else label  # "2016 Boys Don't Cry" -> "Boys Don't Cry"
    return _base("itunes", str(a["collectionId"]), title, a.get("artistName") or "", date, big,
                 a.get("collectionViewUrl") or "", kind, label, "", a.get("trackCount"))


def _close(a: str, b: str) -> bool:
    norm = lambda s: "".join(ch for ch in s.casefold() if ch.isalnum())  # noqa: E731
    return bool(a and b) and (norm(a) == norm(b) or norm(b) in norm(a) or norm(a) in norm(b))
