"""Deezer and iTunes: extra sources for album details and covers, next to MusicBrainz.

Both are free and need no account. They're opt-in connections, used when MusicBrainz is off, down,
or has nothing for an album (new releases often reach Deezer and iTunes first), and for covers the
Cover Art Archive doesn't have. Only the album and artist names you search for are sent.

Their albums are turned into the same shape as a MusicBrainz release, so matching, the per-file
review, safe writing and undo all work the same. Ids look like "deezer:302127" / "itunes:1440857781";
nothing from these sources is ever written as a MusicBrainz ID.
"""

from __future__ import annotations

import difflib
import re
import threading
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable

from codetta.core import discogs as discogs_mod
from codetta.core.providers import ProviderError

DEEZER_API = "https://api.deezer.com"


class DeezerBusy(Exception):
    """Deezer answered with an error (often "over quota"): try again later, don't conclude anything."""


def deezer_artist(fetch: Callable[[str], object], name: str, lenient: bool = False) -> dict | None:
    """Deezer's artist for ``name``: the same name with the most fans (search can put a tiny namesake
    first). None when Deezer has no artist by that name; DeezerBusy when it didn't really answer.
    ``lenient``: fall back to Deezer's top hit ("Beyonce" finds "Beyoncé"); fine for related artists,
    never for a picture (a stranger's face is worse than initials)."""
    found = fetch(f"{DEEZER_API}/search/artist?q={urllib.parse.quote(name)}&limit=10")
    if not isinstance(found, dict) or "error" in found or not isinstance(found.get("data"), list):
        raise DeezerBusy(str((found or {}).get("error") if isinstance(found, dict) else "no answer"))
    same = [a for a in found["data"] if isinstance(a, dict) and a.get("id")
            and str(a.get("name") or "").casefold() == name.casefold()]
    if same:
        return max(same, key=lambda a: a.get("nb_fan") or 0)
    top = [a for a in found["data"] if isinstance(a, dict) and a.get("id")][:1]
    return top[0] if lenient and top else None
ITUNES_API = "https://itunes.apple.com"
SOURCES = ("deezer", "itunes", "discogs")
Fetcher = Callable[[str], object]  # url -> parsed JSON (or None)


def catalog_link_id(text: str, itunes: bool = False) -> str | None:
    """"itunes:<id>" / "deezer:<id>" from a pasted album link, e.g.
    music.apple.com/de/album/kala/1440857781 or deezer.com/en/album/302127. With ``itunes`` (its
    connection is on), a bare iTunes collection id ("296393419" or "id296393419") counts too.
    None: not one."""
    text = (text or "").strip()
    if itunes and re.fullmatch(r"(?:id)?\d{6,12}", text, re.I):
        return f"itunes:{text.lower().removeprefix('id')}"
    m = re.search(r"(?:music|itunes)\.apple\.com/(?:[a-z]{2}/)?album/(?:[^/?#]+/)?(?:id)?(\d{5,})", text, re.I)
    if m:
        return f"itunes:{m.group(1)}"
    m = re.search(r"deezer\.(?:com|page\.link)/(?:[a-z]{2}/)?album/(\d{3,})", text, re.I)
    if m:
        return f"deezer:{m.group(1)}"
    m = re.search(r"discogs\.com/(?:[a-z]{2}/)?(?:[^/\s]+/)?(release|master)/(\d+)", text, re.I)
    return f"discogs:{'m' if m.group(1).lower() == 'master' else ''}{m.group(2)}" if m else None


def is_catalog_id(release_id: str) -> bool:
    return release_id.split(":", 1)[0] in SOURCES and ":" in release_id


def catalog_raw_ok(release_id: str) -> bool:
    """A well-formed catalog ID: digits, or "m" + digits for a Discogs album ("master")."""
    source, _, raw = release_id.partition(":")
    return raw.isdigit() or (source == "discogs" and raw[:1] == "m" and raw[1:].isdigit())


class Catalogs:
    def __init__(self, fetch: Fetcher, enabled: Callable[[str], bool],
                 country: Callable[[], str] | None = None, discogs: discogs_mod.Fetch | None = None,
                 discogs_token: Callable[[], str] | None = None) -> None:
        self.fetch = fetch
        self.enabled = enabled  # source -> is its connection on?
        self.country = country or (lambda: "")  # the preferred edition country: iTunes' storefront
        self.discogs = discogs  # (url, headers) -> JSON; the token goes in a header, never the address
        self.discogs_token = discogs_token or (lambda: "")
        self._throttle = discogs_mod.Throttle()
        self._covers: OrderedDict[str, str] = OrderedDict()  # Discogs covers seen in search results
        self._releases: OrderedDict[str, dict] = OrderedDict()  # recent lookups (covers and re-opens)
        self._lock = threading.Lock()

    def _remember_covers(self, rels: list[dict]) -> None:
        with self._lock:
            for r in rels:
                if r.get("_cover"):
                    self._covers[r["id"]] = r["_cover"]
                    self._covers.move_to_end(r["id"])
            while len(self._covers) > 200:
                self._covers.popitem(last=False)

    def available(self) -> list[str]:
        return [s for s in SOURCES if self.enabled(s)]

    # --- Searching ---------------------------------------------------------------------------

    def search(self, album: str, artist: str = "", limit: int = 6, only: str | None = None) -> list[dict]:
        """Albums from every source that's switched on (or just ``only``), as release-shaped dicts."""
        out: list[dict] = []
        if self.enabled("deezer") and only in (None, "deezer"):
            out += self._deezer_search(album, artist, limit)
        if self.enabled("itunes") and only in (None, "itunes"):
            out += self._itunes_search(album, artist, limit)
        if self.enabled("discogs") and only in (None, "discogs"):
            if self.discogs_token():
                out += self._discogs_search(album, artist, limit)
            elif only == "discogs":
                raise discogs_mod.DiscogsTokenError("Searching Discogs needs your Discogs token: add it in Account → Connections → Discogs.")
        return out

    # --- Discogs ------------------------------------------------------------------------------

    def _dg(self, path: str) -> object:
        if self.discogs is None:
            raise LookupError("Discogs isn't set up on this server")
        self._throttle.wait()
        token = self.discogs_token()
        headers = {"Authorization": f"Discogs token={token}"} if token else {}
        try:
            return self.fetch_discogs(discogs_mod.API + path, headers)
        except ProviderError as exc:
            if "(401)" in str(exc) or "(403)" in str(exc):
                raise discogs_mod.DiscogsTokenError("Discogs turned down the token. Make a new one on discogs.com "
                                                    "(Settings → Developers) and add it in Account → Connections.") from exc
            raise

    def fetch_discogs(self, url: str, headers: dict) -> object:
        return self.discogs(url, headers)

    def _discogs_search(self, album: str, artist: str, limit: int) -> list[dict]:
        q = {"type": "release", "per_page": "40"}
        if album:
            q["release_title"] = album
        if artist:
            q["artist"] = artist
        data = self._dg("/database/search?" + urllib.parse.urlencode(q)) or {}
        found = [r for r in (data.get("results") or []) if isinstance(r, dict) and r.get("id")]
        rels = [discogs_mod.summary(r) for r in found]
        rels = [r for r in rels if not album or _similar(r["title"], album)]
        picked = _only_the_artist(rels, album, artist, lambda r: r["title"], lambda r: r["_artist"])[:limit]
        self._remember_covers(picked)
        return picked

    def _deezer_search(self, album: str, artist: str, limit: int) -> list[dict]:
        parts = [f'album:"{album}"' if album else "", f'artist:"{artist}"' if artist else ""]
        q = urllib.parse.quote(" ".join(p for p in parts if p))
        data = self.fetch(f"{DEEZER_API}/search/album?q={q}&limit={max(limit, 25)}") or {}
        results = [a for a in (data.get("data") or []) if isinstance(a, dict) and a.get("id")]
        title = lambda a: a.get("title") or ""  # noqa: E731
        name = lambda a: (a.get("artist") or {}).get("name") or ""  # noqa: E731
        results = [a for a in results if not album or _similar(title(a), album)]  # Deezer's search is loose too
        return [_deezer_summary(a) for a in _only_the_artist(results, album, artist, title, name)[:limit]]

    def _store(self) -> str:
        """``&country=..`` for iTunes when a preferred edition country is set (stores differ by country)."""
        c = (self.country() or "").upper()
        return f"&country={c.lower()}" if re.fullmatch(r"[A-Z]{2}", c) and c != "XW" else ""

    def _itunes(self, path: str) -> list[dict]:
        """An iTunes API call in the preferred store, falling back to the US store when it has nothing."""
        store = self._store()
        data = self.fetch(f"{ITUNES_API}{path}{store}") or {}
        results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        if not results and store:
            data = self.fetch(f"{ITUNES_API}{path}") or {}
            results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        return results

    def _itunes_search(self, album: str, artist: str, limit: int) -> list[dict]:
        """Apple's free-text search stumbles on names like "M.I.A." (it falls back to popular albums), so:
        find the artist and look through their albums first, then the combined search, then the album
        title alone, keeping only albums whose title or artist actually match."""
        found: dict[str, dict] = {}

        def keep(results: list[dict], need_artist: bool) -> None:
            for a in results:
                if not (a.get("wrapperType") == "collection" and a.get("collectionId")):
                    continue
                name = a.get("collectionName") or ""
                title_ok = not album or _similar(name, album)
                exact = bool(album) and _norm(name) == _norm(album)  # the very title: kept, ranked by artist
                artist_ok = not artist or _similar(a.get("artistName") or "", artist, artist=True)
                if title_ok and (artist_ok or exact or not need_artist):
                    found.setdefault(str(a["collectionId"]), a)

        enc = urllib.parse.quote
        if artist:
            people = self._itunes(f"/search?term={enc(artist)}&entity=musicArtist&attribute=artistTerm&limit=10")
            same = [p for p in people if p.get("artistId") and _norm(p.get("artistName") or "") == _norm(artist)]
            for person in (same or [p for p in people if p.get("artistId") and _similar(p.get("artistName") or "", artist)])[:3]:
                keep(self._itunes(f"/lookup?id={person['artistId']}&entity=album&limit=200"), need_artist=False)
        if len(found) < limit:
            term = enc(" ".join(p for p in (artist, album) if p))
            keep(self._itunes(f"/search?term={term}&entity=album&media=music&limit=50"), need_artist=bool(artist))
        if len(found) < limit and album:
            keep(self._itunes(f"/search?term={enc(album)}&entity=album&media=music&attribute=albumTerm&limit=50"),
                 need_artist=bool(artist))
        picked = _only_the_artist(list(found.values()), album, artist, lambda a: a.get("collectionName") or "",
                                  lambda a: a.get("artistName") or "")
        return [_itunes_summary(a) for a in picked[:limit]]

    def search_text(self, source: str, text: str, limit: int = 24) -> list[dict]:
        """Albums matching free text on one source (the !dz and !it bangs), as release-shaped dicts."""
        if source not in SOURCES or not self.enabled(source):
            raise LookupError(f"{source.title()} isn't on")
        if source == "discogs":  # one entry per album (a "master"), not every pressing
            if not self.discogs_token():
                raise discogs_mod.DiscogsTokenError("Searching Discogs needs your Discogs token: add it in Account → Connections → Discogs.")
            data = self._dg("/database/search?" + urllib.parse.urlencode({"q": text.strip(), "type": "master",
                                                                           "per_page": str(limit)})) or {}
            out = []
            for r in data.get("results") or []:
                if isinstance(r, dict) and r.get("id"):
                    rel = discogs_mod.summary(r)
                    rel["id"] = f"discogs:m{r['id']}"
                    rel["_url"] = f"https://www.discogs.com/master/{r['id']}"
                    out.append(rel)
            self._remember_covers(out)
            return out
        q = urllib.parse.quote(text.strip())
        if source == "deezer":
            data = self.fetch(f"{DEEZER_API}/search/album?q={q}&limit={limit}") or {}
            return [_deezer_summary(a) for a in (data.get("data") or []) if isinstance(a, dict) and a.get("id")]
        return [_itunes_summary(a) for a in self._itunes(f"/search?term={q}&entity=album&media=music&limit={limit}")
                if a.get("collectionId") and a.get("wrapperType") == "collection"]

    # --- One album, with its tracks -----------------------------------------------------------

    def release(self, release_id: str) -> dict:
        with self._lock:
            if release_id in self._releases:
                self._releases.move_to_end(release_id)
                return self._releases[release_id]
        source, _, raw = release_id.partition(":")
        if not catalog_raw_ok(release_id) or not self.enabled(source):
            raise LookupError("That album isn't available (is its connection on?)")
        if source == "discogs":
            rel = self._discogs_release(raw)
        else:
            rel = self._deezer_release(raw) if source == "deezer" else self._itunes_release(raw)
        with self._lock:
            self._releases[release_id] = rel
            while len(self._releases) > 32:
                self._releases.popitem(last=False)
        return rel

    def _discogs_release(self, raw: str) -> dict:
        if raw.startswith("m"):  # an album ("master"): its main release
            m = self._dg(f"/masters/{raw[1:]}") or {}
            raw = str(m.get("main_release") or "")
            if not raw.isdigit():
                raise LookupError("Discogs doesn't have that album")
        r = self._dg(f"/releases/{raw}") or {}
        if not r.get("id"):
            raise LookupError("Discogs doesn't have that release")
        return discogs_mod.release(r)

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
        results = self._itunes(f"/lookup?id={collection_id}&entity=song&limit=200")
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
        with self._lock:
            known = self._covers.get(release_id)  # Discogs: already known from the search (saves a slow lookup)
        if known:
            return known
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


def _norm(s: str) -> str:
    """For comparing names: "M.I.A." == "MIA" == "m i a"; "Kala (Deluxe Edition) - Single" -> "kala"."""
    s = re.sub(r"\s*[([](?:[^)\]]*(?:edition|version|remaster|deluxe|expanded|bonus|explicit|clean)[^)\]]*)[)\]]", "", s, flags=re.I)
    s = re.sub(r"\s+-\s+(single|ep)$", "", s, flags=re.I)
    return "".join(ch for ch in s.casefold() if ch.isalnum())


def _lead_artist(s: str) -> str:
    """The first credited artist: "Drake feat. Rihanna" / "Drake & Future" -> "Drake"."""
    return re.split(r"\s+(?:feat\.?|ft\.?|featuring|with|x|vs\.?)\s+|\s*[&,;/]\s*", s, maxsplit=1, flags=re.I)[0]


def _similar(found: str, wanted: str, artist: bool = False) -> bool:
    if artist and (_norm(_lead_artist(found)) == _norm(_lead_artist(wanted)) != ""):
        return True
    a, b = _norm(found), _norm(wanted)
    if not a or not b:
        return False
    if a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8:
        return True
    short, long_ = sorted((a, b), key=len)  # one inside the other only counts when it's most of it
    return len(short) >= 3 and short in long_ and len(short) >= 0.6 * len(long_)


def _only_the_artist(items: list, album: str, artist: str, title, name) -> list:
    """Best first. When some albums are by the artist asked for, other artists' albums that only
    share the title (another band's "Kala") are left out; otherwise they stay, ranked lower."""
    if artist:
        theirs = [a for a in items if _similar(name(a), artist, artist=True)]
        if theirs:
            items = theirs
    return sorted(items, key=lambda a: -(_closeness(title(a), album) + _closeness(name(a), artist)))


def _closeness(found: str, wanted: str) -> float:
    return difflib.SequenceMatcher(None, _norm(found), _norm(wanted)).ratio() if wanted else 0.0


def _close(a: str, b: str) -> bool:
    norm = lambda s: "".join(ch for ch in s.casefold() if ch.isalnum())  # noqa: E731
    return bool(a and b) and (norm(a) == norm(b) or norm(b) in norm(a) or norm(a) in norm(b))
