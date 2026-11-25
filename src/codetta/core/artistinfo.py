"""An artist's bio and similar artists, for the top of their folder (a little like Last.fm's artist page).

Bio: from Wikipedia, found through MusicBrainz so the right page is used ("Future" is a rapper here,
not the idea of the future): the artist's MusicBrainz ID (from the files' tags, or the MusicBrainz
artist of that name whose albums match the folder's), its Wikidata link, then that Wikidata item's
Wikipedia page in the reader's language (English when there's none). Needs both the MusicBrainz and
the Wikipedia connections; nothing is guessed from the name alone.

Similar artists: Deezer's related artists (Deezer connection).

Everything found is kept for 30 days in ``artist-info.json`` (a miss for a day), so a folder opens
without waiting after the first time.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterable
from pathlib import Path

from codetta.core.catalogs import DEEZER_API, DeezerBusy, deezer_artist
from codetta.core.providers import ProviderError

KEEP = 30 * 86400
KEEP_MISS = 86400
WIKIDATA_RE = re.compile(r"^https?://(?:www\.)?wikidata\.org/wiki/(Q\d+)$")
LANG_RE = re.compile(r"^[a-z]{2,3}$")
MAX_BIO = 1200
# "(pronunciación en islandés: /pjœr̥k/ ;, ...)": pronunciation guides read as noise in a short bio.
PRONOUNCE_RE = re.compile(r"\s*\([^()]*/[^()/]+/[^()]*\)")


def _norm(s: str) -> str:
    return re.sub(r"[^\w]+", " ", s.casefold()).strip()


class ArtistInfo:
    def __init__(self, file: Path, mb, wiki: Callable[[str], object], deezer: Callable[[str], object],
                 enabled: Callable[[str], bool], clock: Callable[[], float] = time.time) -> None:
        self.file = file
        self.mb = mb
        self.wiki = wiki
        self.deezer = deezer
        self.enabled = enabled
        self.clock = clock
        self.lock = threading.Lock()
        try:
            self.cache: dict = json.loads(file.read_text("utf-8"))
        except (OSError, ValueError):
            self.cache = {}

    # --- Cache --------------------------------------------------------------------------------

    def _cached(self, key: str, make: Callable[[], object]) -> object:
        with self.lock:
            hit = self.cache.get(key)
        if hit and self.clock() - hit["at"] < (KEEP if hit["value"] else KEEP_MISS):
            return hit["value"]
        value = make()
        with self.lock:
            self.cache[key] = {"at": self.clock(), "value": value}
            if len(self.cache) > 2000:  # oldest out
                for k in sorted(self.cache, key=lambda k: self.cache[k]["at"])[:200]:
                    del self.cache[k]
            self._save()
        return value

    def _save(self) -> None:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".artist-info-", dir=self.file.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.cache, f)
            os.replace(tmp, self.file)
        except OSError:
            pass

    # --- Bio ----------------------------------------------------------------------------------

    def bio_ready(self) -> bool:
        return self.enabled("wikipedia") and self.enabled("musicbrainz")

    def bio(self, name: str, mbid: str = "", albums: Iterable[str] = (), lang: str = "en") -> dict | None:
        """{text, url, title, lang} from Wikipedia, or None (connections off, or no sure match)."""
        if not self.bio_ready() or not name.strip():
            return None
        lang = lang if LANG_RE.match(lang or "") else "en"
        albums = sorted({_norm(a) for a in albums if a.strip()})
        try:
            mbid = mbid or self._cached(f"mbid:{_norm(name)}:{'|'.join(albums[:20])}", lambda: self._find_mbid(name, albums))
            if not mbid:
                return None
            return self._cached(f"bio:{mbid}:{lang}", lambda: self._wikipedia(mbid, lang))
        except ProviderError:
            return None  # not now: shown without a bio, asked again next time

    def _find_mbid(self, name: str, albums: list[str]) -> str:
        """The MusicBrainz artist with exactly this name; when there are several, the one whose
        albums are the folder's. "" when unsure."""
        same = [a for a in self.mb.search_artists(name, limit=10)
                if _norm(a.get("name") or "") == _norm(name)
                or any(_norm(x.get("name") or "") == _norm(name) for x in a.get("aliases") or [])]
        if len(same) <= 1 or not albums:
            return same[0]["id"] if len(same) == 1 else ""
        best, best_hits = "", 0
        for a in same[:3]:
            titles = {_norm(g.get("title") or "") for g in self.mb.artist_release_groups(a["id"])}
            hits = sum(1 for t in albums if t in titles)
            if hits > best_hits:
                best, best_hits = a["id"], hits
        return best

    def _wikipedia(self, mbid: str, lang: str) -> dict | None:
        artist = self.mb.artist(mbid)
        qid = next((m.group(1) for r in artist.get("relations") or [] if r.get("type") == "wikidata"
                    for m in [WIKIDATA_RE.match(((r.get("url") or {}).get("resource") or "").strip())] if m), None)
        if not qid:
            return None
        entity = self.wiki(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
        links = ((entity or {}).get("entities") or {}).get(qid, {}).get("sitelinks") or {}
        for code in dict.fromkeys((lang, "en")):
            title = (links.get(f"{code}wiki") or {}).get("title")
            if not title:
                continue
            page = self.wiki(f"https://{code}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'), safe='')}")
            text = PRONOUNCE_RE.sub("", str((page or {}).get("extract") or ""))
            text = re.sub(r"\s+([;,.:])", r"\1", text).strip()  # "Thom Yorke ;" (left where Wikipedia cut a bracket)
            if text:
                if len(text) > MAX_BIO:
                    text = text[:MAX_BIO].rsplit(". ", 1)[0] + "."
                url = (((page or {}).get("content_urls") or {}).get("desktop") or {}).get("page") \
                    or f"https://{code}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                return {"text": text, "url": url, "title": title, "lang": code}
        return None

    def mb_name(self, mbid: str) -> str:
        """The name MusicBrainz has for this artist ID, or "" (MusicBrainz off, or no answer)."""
        if not self.enabled("musicbrainz") or not mbid:
            return ""
        try:
            return str(self._cached(f"mbname:{mbid}", lambda: str(self.mb.artist(mbid).get("name") or "")))
        except ProviderError:
            return ""

    # --- Albums on Deezer ----------------------------------------------------------------------

    def albums(self, name: str, limit: int = 4) -> list[dict]:
        """An artist's best-known albums on Deezer (most fans first, singles and EPs left out):
        [{"id": "deezer:123", "title", "artist", "year"}], or [] when Deezer is off."""
        if not self.enabled("deezer") or not name.strip():
            return []

        def ask() -> list[dict]:
            found = deezer_artist(self.deezer, name, lenient=True)
            if not found:
                return []
            got = self.deezer(f"{DEEZER_API}/artist/{found['id']}/albums?limit=100")
            out = []
            for a in (got or {}).get("data") or []:
                if not isinstance(a, dict) or not str(a.get("id") or "").isdigit() or a.get("record_type") != "album":
                    continue
                out.append({"id": f"deezer:{a['id']}", "title": str(a.get("title") or ""), "artist": str(found.get("name") or name),
                            "year": str(a.get("release_date") or "")[:4], "fans": int(a.get("fans") or 0)})
            out.sort(key=lambda a: -a["fans"])
            return [{k: v for k, v in a.items() if k != "fans"} for a in out[:20]]

        try:
            return list(self._cached(f"albums:{_norm(name)}", ask))[:limit]
        except (DeezerBusy, ProviderError):
            return []

    # --- Similar artists ----------------------------------------------------------------------

    def similar(self, name: str, limit: int = 12) -> list[str]:
        """Names of artists like this one (Deezer's related artists), or [] when Deezer is off."""
        if not self.enabled("deezer") or not name.strip():
            return []

        def ask() -> list[str]:
            found = deezer_artist(self.deezer, name)
            if not found:
                return []
            related = self.deezer(f"{DEEZER_API}/artist/{found['id']}/related?limit=25")
            return [str(a["name"]) for a in (related or {}).get("data") or [] if isinstance(a, dict) and a.get("name")][:25]

        try:
            return list(self._cached(f"similar:{_norm(name)}", ask))[:limit]
        except (DeezerBusy, ProviderError):
            return []
