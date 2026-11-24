"""Matching on MusicBrainz (and Deezer/iTunes): search, editions, identify by sound, apply."""
from __future__ import annotations

import re
import threading
import urllib.parse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Literal

from fastapi import HTTPException, Query
from fastapi.responses import Response

from codetta.core.acoustid import FingerprintError, rank_releases
from codetta.core.artwork import sniff_image_type
from codetta.core.catalogs import Catalogs, catalog_link_id, catalog_raw_ok, is_catalog_id
from codetta.core.editions import FORMATS as EDITION_FORMATS
from codetta.core.editions import edition_fit, padded_date
from codetta.core.engine import MetadataError, TrackMetadata
from codetta.core.library import LibraryPathError
from codetta.core.musicbrainz import (
    ALL_FIELDS as MB_FIELDS,
)
from codetta.core.musicbrainz import (
    DEFAULT_OFF as MB_DEFAULT_OFF,
)
from codetta.core.musicbrainz import (
    FIELD_GROUPS as MB_FIELD_GROUPS,
)
from codetta.core.musicbrainz import (
    ID_LABELS as MB_ID_LABELS,
)
from codetta.core.musicbrainz import (
    MBID_RE,
    FileInfo,
    album_tags,
    clean_artist,
    clean_title,
    cover_url,
    number,
    pair_files,
    parse_release_id,
    release_tracks,
    score_candidate,
    similarity,
    song_from_name,
    song_releases,
    summarize,
    track_tags,
)
from codetta.core.musicbrainz import (
    default_fields as mb_default_fields,
)
from codetta.core.providers import ProviderError
from codetta.core.tagmap import FIELDS, is_tag_supported
from codetta.web.common import (
    MAX_IDENTIFY,
    MAX_PATHS_PER_REQUEST,
    EditionPrefsIn,
    MBProposalIn,
    MBSearchIn,
    MBTarget,
    _log_musicbrainz,
    _unique,
)


def register(app, shared) -> None:
    acoustid = shared.acoustid
    activity = shared.activity
    art_info = shared.art_info
    art_store = shared.art_store
    catalog_fetch = shared.catalog_fetch
    connections = shared.connections
    download_art = shared.download_art
    editions = shared.editions
    engine = shared.engine
    fetch_catalog = shared.fetch_catalog
    fingerprinter = shared.fingerprinter
    lib_index = shared.lib_index
    library = shared.library
    mb = shared.mb
    require_connection = shared.require_connection
    require_library = shared.require_library

    def mb_targets(body: MBTarget) -> list[str]:
        if body.folder is not None:
            rels = library.list_folder(body.folder).files
        else:
            rels = _unique(body.paths)
        if not rels:
            raise HTTPException(400, "Choose an album folder or some tracks first.")
        if len(rels) > MAX_PATHS_PER_REQUEST:
            raise HTTPException(422, f"Too many files for one album (max {MAX_PATHS_PER_REQUEST}).")
        return rels

    def mb_read(rels: list[str]) -> tuple[list[FileInfo], dict[str, TrackMetadata], dict[str, str]]:
        infos, metas, errors = [], {}, {}
        for rel in rels:
            try:
                meta = engine.load_metadata(library.resolve(rel))
            except (MetadataError, LibraryPathError, OSError) as exc:
                errors[rel] = str(exc)
                continue
            metas[rel] = meta
            one = lambda key: (meta.tags.get(key) or [""])[0].strip()
            infos.append(FileInfo(
                path=rel, title=one("title"), artist=one("artist"), album=one("album"),
                albumartist=one("albumartist"), tracknumber=number(one("tracknumber")),
                discnumber=number(one("discnumber")), duration=meta.duration, albumid=one("musicbrainz_albumid").lower(),
            ))
        return infos, metas, errors

    def most_common(values) -> str:
        counts: dict[str, int] = {}
        for v in values:
            if v:
                counts[v] = counts.get(v, 0) + 1
        return max(counts, key=counts.get) if counts else ""

    catalogs = Catalogs(fetch_catalog or catalog_fetch, connections.enabled,
                        country=lambda: editions.prefs.store or editions.prefs.country,
                        discogs=shared.discogs_fetch, discogs_token=lambda: shared.discogs_token.token)

    def require_matching() -> None:
        """Matching needs MusicBrainz, Deezer or iTunes (any one of them)."""
        if not catalogs.available():
            require_connection("musicbrainz")

    def get_release(release_id: str) -> dict:
        """A full release (with tracks) from whichever source the id belongs to."""
        if is_catalog_id(release_id):
            try:
                return catalogs.release(release_id)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
        require_connection("musicbrainz")
        return mb.release(release_id)

    def better_edition(release: dict, recording: str, title: str, duration: float | None) -> tuple[dict, str]:
        """A song search lists only a few editions of each album (Hyperballad came back on Post's DualDisc
        DVD side, a video edit, not the CD). Look through every edition for one the preferences like
        better that has this song: the same recording, or the same title at your file's length.
        Keep what was found when nothing beats it or MusicBrainz won't say."""
        group = (release.get("release-group") or {}).get("id") or ""
        fit = lambda r: edition_fit(summarize(r), editions.prefs, 1)
        here = fit(release)
        try:
            others = mb.releases_in_group(group) if MBID_RE.match(group) else []
        except ProviderError:
            return release, recording
        ranked = sorted((r for r in others if r["id"] != release.get("id") and fit(r) > here),
                        key=lambda r: (-fit(r), padded_date(r.get("date") or "")))
        for r in ranked[:2]:
            try:
                full = mb.release(r["id"])
            except ProviderError:
                continue
            tracks = [t for m in full.get("media") or [] for t in m.get("tracks") or []]
            same = next((t for t in tracks if (t.get("recording") or {}).get("id") == recording), None)
            if same is None and duration:
                same = next((t for t in tracks if similarity(title, clean_title(t.get("title") or "")) >= 0.9
                             and isinstance(t.get("length"), int) and abs(t["length"] / 1000 - duration) <= 10), None)
            rec = (same or {}).get("recording") or {}
            if MBID_RE.match(str(rec.get("id", ""))):
                return ({**r, "release-group": release.get("release-group"),
                         "artist-credit": r.get("artist-credit") or release.get("artist-credit")}, rec["id"])
        return release, recording

    def mb_release_id(text: str) -> str:
        if is_catalog_id(text.strip()):
            return text.strip()
        linked = catalog_link_id(text, itunes=connections.enabled("itunes"))  # an album link, or an iTunes id
        if linked:
            return linked
        mbid = parse_release_id(text)
        if not mbid:
            raise HTTPException(422, "Paste a release link from MusicBrainz, Apple Music or Deezer (or a MusicBrainz ID).")
        return mbid

    @app.post("/api/musicbrainz/search")
    def mb_search(body: MBSearchIn) -> dict:
        """Find releases that could be this album. Sends only the album/artist
        names (or the release ID you pasted) to MusicBrainz, and to Deezer / iTunes when they're on
        and MusicBrainz is off, down, or not confident."""
        require_matching()
        require_library()
        rels = mb_targets(body)
        infos, _, _ = mb_read(rels)
        album = body.album.strip() or most_common(f.album for f in infos)
        artist = body.artist.strip() or most_common(f.albumartist or f.artist for f in infos)
        current = most_common(f.albumid for f in infos if MBID_RE.match(f.albumid))
        if body.source != "auto":
            return catalog_only_search(body.source, infos, album, artist, len(rels))
        mb_error = None
        found = []
        # One loose song with no album tag (a single download, a YouTube rip): look for the song,
        # not an album, and offer the album it's from. Junk like "(Official Audio)" is cleaned off.
        song = None
        if len(infos) == 1 and not album and not body.release.strip() and not current:
            f = infos[0]
            t, a = clean_title(f.title), clean_artist(f.artist or f.albumartist)
            if not t:
                t, a2 = song_from_name(f.path)
                a = a or a2
            if t:
                song = (t, a)
                artist = a
        if song and connections.enabled("musicbrainz"):
            try:
                hits = song_releases(mb.search_recordings(*song), song[0], song[1], infos[0].duration,
                                     prefer=lambda c: edition_fit(c, editions.prefs, 1))
            except ProviderError as exc:
                hits, mb_error = [], str(exc)
            if hits:
                rel0, rec0 = better_edition(hits[0]["release"], hits[0]["recording"], song[0], infos[0].duration)
                hits[0] = {**hits[0], "release": rel0, "recording": rec0}
                candidates = []
                for hit in hits:
                    c = summarize(hit["release"])
                    c.update(score=hit["score"], current=False, single=True)
                    candidates.append(c)
                return {"query": {"album": "", "artist": song[1], "title": song[0], "files": 1}, "current": None,
                        "candidates": candidates, "recordings": {infos[0].path: _unique([h["recording"] for h in hits])},
                        "note": None}
        if song:
            album = song[0]  # nothing found as a song: it may be a single of the same name
        try:
            if body.release.strip():
                found = [get_release(mb_release_id(body.release))]
            elif connections.enabled("musicbrainz"):
                found = mb.search(album, artist) if (album or artist) else []
                if current and not body.album.strip() and not body.artist.strip() and all(r.get("id") != current for r in found):
                    try:  # already tagged with a release: offer it first
                        found.insert(0, mb.release(current))
                    except ProviderError:
                        pass
        except ProviderError as exc:
            if not catalogs.available() or body.release.strip():
                raise HTTPException(502, str(exc)) from exc
            mb_error = str(exc)  # MusicBrainz is down: Deezer / iTunes can still answer
        candidates = []
        for r in found:
            c = summarize(r)
            c["score"] = score_candidate(c, infos, album, artist)
            c["current"] = c["id"] == current
            candidates.append(c)
        if not body.release.strip() and catalogs.available() and (album or artist) \
                and (not candidates or max(c["score"] for c in candidates) < 70):
            # Fallback: MusicBrainz is off, down, has nothing, or nothing it has fits well.
            try:
                for r in catalogs.search(album, artist):
                    c = summarize(r)
                    c["score"] = score_candidate(c, infos, album, artist)
                    c["current"] = False
                    candidates.append(c)
            except ProviderError as exc:
                if not candidates:
                    raise HTTPException(502, mb_error or str(exc)) from exc
        if not body.release.strip():  # preferences only reorder; the score stays what it is
            candidates.sort(key=lambda c: (not c["current"], -(c["score"] + edition_fit(c, editions.prefs, len(rels)))))
        return {"query": {"album": album, "artist": artist, "files": len(rels)}, "current": current or None,
                "candidates": candidates, "recordings": {}, "note": f"MusicBrainz didn't answer ({mb_error}), so these come from other sources." if mb_error else None}

    HARMONY = "https://harmony.pulsewidth.org.uk/release"

    @app.post("/api/harmony")
    def harmony_link(body: MBTarget) -> dict:
        """A link that opens Harmony (a MusicBrainz importer) with this album already looked up, for
        albums MusicBrainz doesn't have yet. Harmony looks albums up by barcode or by a store link,
        not by name: so the album's barcode if the files have one, else its Deezer or iTunes page
        (found by album and artist, only when that connection is on)."""
        require_library()
        rels = mb_targets(body)
        infos, metas, _ = mb_read(rels)
        album = most_common(f.album for f in infos)
        artist = most_common(f.albumartist or f.artist for f in infos)
        codes = [re.sub(r"\D", "", (m.tags.get("barcode") or [""])[0]) for m in metas.values()]
        barcode = most_common(c for c in codes if 8 <= len(c) <= 14)
        if barcode:
            return {"url": f"{HARMONY}?{urllib.parse.urlencode({'gtin': barcode, 'category': 'default'})}",
                    "how": "barcode", "found": barcode}
        if not (album or artist):
            raise HTTPException(422, "These files have no album, artist or barcode for Harmony to look up.")
        sources = [s for s in ("deezer", "itunes") if connections.enabled(s)]
        if not sources:
            raise HTTPException(409, "Harmony looks albums up by barcode or by a store link. These files have no barcode: "
                                     "turn on Deezer or iTunes in Settings → Connections so Codetta can find the album's link.")
        best = None
        for source in sources:
            try:
                for r in catalogs.search(album, artist, limit=5, only=source):
                    c = summarize(r)
                    score = score_candidate(c, infos, album, artist)
                    if r.get("_url") and score >= 60 and (best is None or score > best[0]):
                        best = (score, r["_url"], source, f"{r.get('_artist') or ''} – {r.get('title') or ''}".strip(" –"))
            except ProviderError:
                continue
            if best and best[0] >= 85:
                break  # good enough: no need to ask the next store
        if not best:
            raise HTTPException(404, f"Couldn't find “{album or artist}” on {' or '.join(s.title() if s == 'deezer' else 'iTunes' for s in sources)} "
                                     "to give Harmony a link. If you have a store link for it, paste it into Harmony yourself.")
        return {"url": f"{HARMONY}?{urllib.parse.urlencode({'url': best[1], 'category': 'default'})}",
                "how": best[2], "found": best[3]}

    def catalog_only_search(source: str, infos: list, album: str, artist: str, files: int) -> dict:
        """Find in Deezer / Find in iTunes: that source only, the same review afterwards."""
        require_connection(source)
        if not album and len(infos) == 1:  # a loose song: its title is the best guess at the album (a single)
            t, a = clean_title(infos[0].title), clean_artist(infos[0].artist or infos[0].albumartist)
            if not t:
                t, a2 = song_from_name(infos[0].path)
                a = a or a2
            album, artist = t, artist or a
        if not (album or artist):
            raise HTTPException(422, "These files have no album or artist to search for. Type one in.")
        try:
            found = catalogs.search(album, artist, limit=10, only=source)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        except LookupError as exc:  # Discogs without a token (or one it turned down)
            raise HTTPException(409, str(exc)) from exc
        candidates = []
        for r in found:
            c = summarize(r)
            c["score"] = score_candidate(c, infos, album, artist)
            c["current"] = False
            candidates.append(c)
        candidates.sort(key=lambda c: -(c["score"] + edition_fit(c, editions.prefs, files)))
        return {"query": {"album": album, "artist": artist, "files": files, "source": source}, "current": None,
                "candidates": candidates, "recordings": {}, "note": None}

    @app.get("/api/musicbrainz/editions")
    def mb_editions(release: str = Query(..., max_length=500)) -> dict:
        """Every edition of the album this release belongs to, with the one your preferences like best."""
        require_connection("musicbrainz")
        mbid = mb_release_id(release)
        if is_catalog_id(mbid):
            raise HTTPException(422, "Editions come from MusicBrainz; this album came from another source.")
        try:
            rel = get_release(mbid)
            group = (rel.get("release-group") or {})
            found = mb.releases_in_group(group.get("id") or "")
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        out = []
        for r in found:
            c = summarize(r)
            c["fit"] = edition_fit(c, editions.prefs)
            c["current"] = c["id"] == mbid
            out.append(c)
        out.sort(key=lambda c: (c["date"] or "9999", c["country"]))
        # Your preferences first, then the earliest edition (a bare "1977" counts as late in 1977, so a
        # dated original wins over an undated pressing from the same year).
        best = min(out, key=lambda c: (-c["fit"], padded_date(c["date"])), default=None)
        for c in out:
            c["recommended"] = best is not None and c["id"] == best["id"]
        return {"title": group.get("title") or rel.get("title") or "", "first": group.get("first-release-date") or "",
                "editions": out}

    @app.get("/api/editions")
    def get_edition_prefs() -> dict:
        """Which edition of an album Codetta prefers when it matches on its own."""
        return {**asdict(editions.prefs), "formats": list(EDITION_FORMATS)}

    @app.put("/api/editions")
    def put_edition_prefs(body: EditionPrefsIn) -> dict:
        try:
            editions.set(**body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return get_edition_prefs()

    @app.post("/api/musicbrainz/identify")
    def mb_identify(body: MBTarget) -> dict:
        """Recognise the files by their sound: fingerprint them here, ask AcoustID
        which recordings they are, and offer the releases holding most of them."""
        require_connection("musicbrainz")
        require_connection("acoustid")
        require_library()
        if not fingerprinter.available:
            raise HTTPException(503, "The fingerprint tool (fpcalc) isn't installed on this server. "
                                     "It's included in the Docker image; elsewhere install Chromaprint.")
        rels = mb_targets(body)
        if len(rels) > MAX_IDENTIFY:
            raise HTTPException(422, f"Identify by sound works on up to {MAX_IDENTIFY} tracks at a time "
                                     "(one album). Select fewer tracks.")
        infos, _, read_errors = mb_read(rels)
        readable = [f.path for f in infos]
        prints = fingerprinter.many([library.resolve(r) for r in readable])
        ok = [(rel, fp) for rel, fp in zip(readable, prints) if not isinstance(fp, FingerprintError)]
        try:
            found = acoustid.lookup([fp for _, fp in ok]) if ok else []
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        heard = {rel: recs for (rel, _), recs in zip(ok, found)}
        files = []
        for rel in rels:
            if rel in read_errors:
                files.append({"path": rel, "status": "error", "error": read_errors[rel]})
                continue
            fp = prints[readable.index(rel)]
            if isinstance(fp, FingerprintError):
                files.append({"path": rel, "status": "error", "error": str(fp)})
            elif heard.get(rel):
                top = heard[rel][0]
                files.append({"path": rel, "status": "identified", "recording": {
                    "id": top.id, "title": top.title, "artist": top.artist, "score": round(top.score * 100)}})
            else:
                files.append({"path": rel, "status": "unknown"})
        ranked = rank_releases(heard, limit=25)
        try:
            found_releases = mb.releases_by_id([rid for rid, _ in ranked]) if ranked else []
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        covered = dict(ranked)
        n = len(rels)
        candidates = []
        for r in found_releases:
            c = summarize(r)
            tracks = c.get("track_count") or 0
            fit = 1.0 if tracks == n else max(0.0, 1 - abs(tracks - n) / max(n, tracks or 1) * 2)
            c["heard"] = covered.get(c["id"], 0)
            c["score"] = round(100 * (0.75 * c["heard"] / max(1, n) + 0.25 * fit))
            c["current"] = False
            candidates.append(c)
        candidates.sort(key=lambda c: -c["score"])
        identified = sum(f["status"] == "identified" for f in files)
        return {
            "query": {"album": "", "artist": "", "files": n},
            "identified": identified, "total": n,
            "files": files,
            "recordings": {rel: [r.id for r in recs[:20]] for rel, recs in heard.items() if recs},
            "candidates": candidates[:15],
        }

    def mb_proposal(body: MBProposalIn) -> tuple[dict, dict]:
        """What applying this release would change, per file. Returns (proposal, release)."""
        require_matching()
        require_library()
        rels = mb_targets(body)
        mbid = mb_release_id(body.release)
        try:
            release = get_release(mbid)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        tracks = release_tracks(release)
        if not tracks:
            raise HTTPException(422, "This release has no track list on MusicBrainz yet.")
        infos, metas, errors = mb_read(rels)
        heard = {p: [r for r in ids[:20] if MBID_RE.match(r)] for p, ids in body.recordings.items() if p in metas}
        pairs = pair_files(infos, tracks, {p: t for p, t in body.pairs.items() if p in metas}, heard)
        album = album_tags(release)
        if editions.prefs.original_year and (album.get("originaldate") or [""])[0]:
            album["date"] = list(album["originaldate"])  # the album's own year, not a reissue's
        wanted = set(mb_default_fields() if body.fields is None else body.fields) & set(MB_FIELDS)
        summary = summarize(release)
        files = []
        for rel in rels:
            if rel in errors:
                files.append({"path": rel, "error": errors[rel], "track": None, "changes": {}})
                continue
            meta, pairing = metas[rel], pairs[rel]
            changes, unsupported = {}, []
            if pairing.track:
                for key, new in track_tags(release, pairing.track, album).items():
                    if key not in wanted:
                        continue
                    if not is_tag_supported(meta.format or "", key):
                        unsupported.append(key)
                        continue
                    old = meta.tags.get(key, [])
                    if body.mode == "fill" and any(v.strip() for v in old):
                        continue
                    if old != new:
                        changes[key] = {"old": old, "new": new}
            target = library.resolve(rel)
            try:
                mtime = target.stat().st_mtime_ns
            except OSError:
                mtime = None
            has_art = art_info(rel, target, mtime) is not None
            files.append({
                "path": rel, "error": None,
                "track": pairing.track.to_dict() if pairing.track else None,
                "confidence": pairing.confidence, "notes": pairing.notes,
                "duration": meta.duration, "title": (meta.tags.get("title") or [""])[0],
                "changes": changes, "unsupported": unsupported, "has_art": has_art,
                "cover": bool(pairing.track) and summary["has_cover"] is not False
                         and (body.cover == "all" or (body.cover == "missing" and not has_art)),
            })
        labels = {f.key: f.label for f in FIELDS}
        groups = [
            {"id": gid, "label": label, "default": not set(keys) <= MB_DEFAULT_OFF,
             "fields": [{"key": k, "label": labels.get(k) or MB_ID_LABELS.get(k, k)} for k in keys]}
            for gid, label, keys in MB_FIELD_GROUPS
        ]
        return {
            "release": summary,
            "tracks": [t.to_dict() for t in tracks],
            "files": files,
            "groups": groups,
            "fields": sorted(wanted),
            "mode": body.mode, "cover": body.cover,
        }, release

    @app.post("/api/musicbrainz/preview")
    def mb_preview(body: MBProposalIn) -> dict:
        """Pair the files with a release's tracks and show what would change. Writes nothing."""
        return mb_proposal(body)[0]

    cover_cache: OrderedDict[tuple[str, int | None], bytes | None] = OrderedDict()
    cover_lock = threading.Lock()

    def fetch_cover(mbid: str, size: int | None) -> bytes | None:
        key = (mbid, size)
        with cover_lock:
            if key in cover_cache:
                cover_cache.move_to_end(key)
                return cover_cache[key]
        kind = "release"
        if mbid.startswith("rg:"):
            kind, mbid = "release-group", mbid[3:]
        if is_catalog_id(mbid):  # Deezer / iTunes: their own cover (one size, fetched by the server)
            url = catalogs.cover(mbid)
            data = download_art(url) if url else None
        else:
            data = download_art(cover_url(mbid, size, kind=kind))
        if data is not None and sniff_image_type(data) not in ("image/jpeg", "image/png"):
            data = None  # only real JPEG/PNG covers are used (and served to the page)
        if size and size <= 500:  # only small thumbnails are kept (the candidate list)
            with cover_lock:
                cover_cache[key] = data
                while len(cover_cache) > 48:
                    cover_cache.popitem(last=False)
        return data

    cover_fallbacks: OrderedDict[tuple[str, int], bytes | None] = OrderedDict()

    def release_cover_fallback(mbid: str, size: int) -> bytes | None:
        """No cover for this exact release (new releases often have none yet): the album's other
        editions usually share it, and Deezer / iTunes (when they're on) often have it."""
        key = (mbid, size)
        with cover_lock:
            if key in cover_fallbacks:
                return cover_fallbacks[key]
        data = None
        try:
            release = mb.release(mbid)
        except (ProviderError, LookupError, HTTPException):
            release = None
        if release:
            group = (release.get("release-group") or {}).get("id")
            if group and MBID_RE.match(group):
                data = fetch_cover("rg:" + group, size)
            if data is None and catalogs.available():
                s = summarize(release)
                url = catalogs.find_cover(s.get("title") or "", s.get("artist") or "")
                found = download_art(url) if url else None
                if found is not None and sniff_image_type(found) in ("image/jpeg", "image/png"):
                    data = found
        with cover_lock:
            cover_fallbacks[key] = data
            while len(cover_fallbacks) > 48:
                cover_fallbacks.popitem(last=False)
        return data

    @app.get("/api/musicbrainz/cover/{mbid}", responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}})
    def mb_cover(mbid: str, size: int = Query(250, description="250 or 500 pixels"),
                 kind: Literal["release", "release-group"] = "release"):
        """A release's (or release group's) front cover from the Cover Art Archive, fetched
        by the server (so the page never loads anything from another site)."""
        catalog = is_catalog_id(mbid) and catalog_raw_ok(mbid)
        if catalog:
            require_connection(mbid.split(":", 1)[0])
        else:
            require_connection("musicbrainz")
        if not (MBID_RE.match(mbid) or catalog) or size not in (250, 500):
            raise HTTPException(422, "Not a release ID or thumbnail size")
        try:
            data = fetch_cover(("rg:" if kind == "release-group" else "") + mbid, size)
            if data is None and kind == "release" and not catalog:
                data = release_cover_fallback(mbid, size)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        if data is None:
            raise HTTPException(404, "No cover art for this release")
        return Response(data, media_type=sniff_image_type(data), headers={"Cache-Control": "private, max-age=86400"})

    @app.post("/api/musicbrainz/apply")
    def mb_apply(body: MBProposalIn) -> dict:
        """Write the release's tags (and cover) to the paired files: one activity
        entry, undoable as a whole."""
        proposal, release = mb_proposal(body)
        summary = proposal["release"]
        art, art_error = None, None
        if any(f.get("cover") for f in proposal["files"]):
            try:
                art = fetch_cover(summary["id"], 1200) or (None if is_catalog_id(summary["id"]) else fetch_cover(summary["id"], None))
            except ProviderError as exc:
                art_error = str(exc)
            if art is None and not is_catalog_id(summary["id"]) and catalogs.available():
                try:  # the Cover Art Archive has none: Deezer / iTunes often do
                    url = catalogs.find_cover(summary["title"], summary["artist"])
                    found = download_art(url) if url else None
                    if found is not None and sniff_image_type(found) in ("image/jpeg", "image/png"):
                        art, art_error = found, None
                except ProviderError:
                    pass
            if art is None and art_error is None:
                art_error = "No cover was found for this release"
        tag_undo, art_undo = {}, {}

        def write(f: dict) -> dict | None:
            """One file: its tags and (when asked) the cover, in a single safe write."""
            rel = f["path"]
            if f["error"]:
                return {"path": rel, "ok": False, "error": f["error"]}
            set_art = bool(f["cover"] and art)
            if not f["changes"] and not set_art:
                return None
            changes = {k: c["new"] for k, c in f["changes"].items()}
            try:
                target = library.resolve(rel)
                old = engine.read_artwork(target) if set_art else None
                if set_art:
                    meta, new = engine.update_tags_and_artwork(target, changes, art, batch=wb)
                else:
                    meta, new = engine.update_tags(target, changes, batch=wb), None
            except (MetadataError, LibraryPathError, OSError) as exc:
                return {"path": rel, "ok": False, "error": library.message(exc), "tags": 0, "cover": False}
            if f["changes"]:
                tag_undo[rel] = {"before": {k: c["old"] for k, c in f["changes"].items()},
                                 "after": {k: meta.tags.get(k, []) for k in f["changes"]}}
            if set_art:
                try:
                    before, after = art_store.save(old.data if old else None), art_store.save(new.data if new else None)
                    if before != after:
                        art_undo[rel] = {"before": before, "after": after}
                except OSError:
                    pass  # couldn't keep a copy: the cover part just won't be undoable
            return {"path": rel, "ok": True, "error": None, "tags": len(f["changes"]), "cover": set_art}

        with engine.batch() as wb:  # each folder is flushed once, at the end
            files = proposal["files"]
            if len(files) > 4:  # most of a safe write is waiting for the disk: a few at once
                with ThreadPoolExecutor(max_workers=4, thread_name_prefix="codetta-write") as pool:
                    results = [r for r in pool.map(write, files) if r is not None]
            else:
                results = [r for r in map(write, files) if r is not None]
        parts = [p for p in ({"type": "tags", "files": tag_undo}, {"type": "art", "files": art_undo}) if p["files"]]
        undo = parts[0] if len(parts) == 1 else {"type": "multi", "parts": parts} if parts else None
        if results:
            _log_musicbrainz(activity, summary, proposal["files"], results, bool(art_undo), undo)
        # Every file that changed, including one whose tags saved but cover didn't.
        lib_index.mark_dirty({r["path"] for r in results if r["ok"]} | set(tag_undo) | set(art_undo))
        return {
            "release": summary,
            "results": results,
            "updated": sum(r["ok"] for r in results),
            "failed": sum(not r["ok"] for r in results),
            "cover_error": art_error,
        }

    shared.share(
        catalogs=catalogs, mb_apply=mb_apply, mb_identify=mb_identify, mb_preview=mb_preview,
        mb_read=mb_read, mb_search=mb_search, most_common=most_common,
    )
