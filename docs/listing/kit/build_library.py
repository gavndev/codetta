"""A real-world demo library: real tags and covers from MusicBrainz / Cover Art Archive, silent audio."""
import json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from mutagen.flac import FLAC, Picture

"""Usage: python build_library.py <work>/music (covers and a MusicBrainz cache go beside it)."""
OUT = Path(sys.argv[1]); COVERS = OUT.parent / "covers"; CACHE = OUT.parent / "mbcache"
for d in (OUT, COVERS, CACHE): d.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Codetta-screenshots/0.8 ( https://github.com/gavndev/codetta )", "Accept": "application/json"}

def fetch(url, raw=False):
    key = CACHE / re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:]
    if key.exists(): return key.read_bytes() if raw else json.loads(key.read_text())
    for i in range(6):
        time.sleep(1.3 + i * 2)
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read(); break
        except urllib.error.HTTPError as e:
            if e.code not in (502, 503): raise
    key.write_bytes(data)
    return data if raw else json.loads(data)

RGS = {  # release groups (verified by search)
    "9bb5f1fe-1a20-44bc-a800-e37795ad2520": None, "ecd03234-2323-4e1d-b367-780c9dba7778": None,
    "b0c04158-9592-4946-bdcf-9cfe4a41da8c": None, "34009a25-def9-4e37-b3be-803b154902c0": None,
    "34315f68-08a5-3637-8da7-deaad8f45514": None, "c475971c-c6a2-4e90-b24b-fb9f2f39227f": None,
    "d5964d4c-a16b-4e47-b81b-e36b1ef99f0c": None,
}
SEARCH = [("Pharrell", "In My Mind"), ("Frank Ocean", "Blonde"), ("Björk", "Vespertine"),
          ("Radiohead", "In Rainbows"), ("Fleetwood Mac", "Rumours")]
for artist, title in SEARCH:
    q = urllib.parse.quote(f'releasegroup:"{title}" AND artist:"{artist}" AND primarytype:album')
    rg = fetch(f"https://musicbrainz.org/ws/2/release-group/?query={q}&limit=1&fmt=json")["release-groups"][0]
    print("found", rg["title"], "-", rg["artist-credit"][0]["name"], rg["id"]); RGS[rg["id"]] = None

def credit(ac): return "".join(a["name"] + a.get("joinphrase", "") for a in ac)
def safe(s): return re.sub(r'[\\/:*?"<>|]', "_", s).strip()

summary = []
for rgid in RGS:
    rels = fetch(f"https://musicbrainz.org/ws/2/release?release-group={rgid}&status=official&inc=media&limit=100&fmt=json")["releases"]
    rels = [r for r in rels if r.get("cover-art-archive", {}).get("front")] or rels
    rels.sort(key=lambda r: (sum(m.get("track-count", 0) for m in r.get("media", [])), not any(m.get("format") == "Digital Media" for m in r.get("media", [])), r.get("date") or "9999"))
    rid = rels[0]["id"]
    rel = fetch(f"https://musicbrainz.org/ws/2/release/{rid}?inc=recordings+artist-credits+labels+release-groups+genres&fmt=json")
    rg = rel["release-group"]
    rgfull = fetch(f"https://musicbrainz.org/ws/2/release-group/{rgid}?inc=genres&fmt=json")
    genres = sorted(rgfull.get("genres") or rel.get("genres") or [], key=lambda g: -g.get("count", 0))
    genre = genres[0]["name"].title() if genres else ""
    albumartist = credit(rel["artist-credit"]); year = (rg.get("first-release-date") or rel.get("date") or "")[:4]
    cover = COVERS / f"{rgid}.jpg"
    if not cover.exists():
        try: cover.write_bytes(fetch(f"https://coverartarchive.org/release/{rid}/front-1200", raw=True))
        except Exception as e: print("no cover", rel["title"], e)
    small = COVERS / f"{rgid}-600.jpg"
    if cover.exists() and not small.exists():
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", cover, "-vf", "scale=600:-1", "-q:v", "3", small], check=True)
    folder = OUT / safe(albumartist.split(" & ")[0]) / safe(f"{rel['title']} ({year})")
    folder.mkdir(parents=True, exist_ok=True)
    label = (rel.get("label-info") or [{}])[0]
    discs = len(rel["media"])
    for m in rel["media"]:
        for t in m["tracks"]:
            n = t["position"]; ms = t.get("length") or t["recording"].get("length") or 180000
            name = f"{m['position']}-{n:02d} {safe(t['title'])}.flac" if discs > 1 else f"{n:02d} {safe(t['title'])}.flac"
            f = folder / name
            if not f.exists():
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                                "-t", f"{ms / 1000:.2f}", "-c:a", "flac", "-sample_fmt", "s16", f], check=True)
            a = FLAC(f); a.delete(); a.clear_pictures()
            tags = {"title": t["title"], "artist": credit(t["artist-credit"]), "album": rel["title"], "albumartist": albumartist,
                    "date": rg.get("first-release-date") or rel.get("date") or year, "originaldate": rg.get("first-release-date") or "", "tracknumber": str(n),
                    "tracktotal": str(len(m["tracks"])), "discnumber": str(m["position"]), "disctotal": str(discs),
                    "genre": genre, "label": (label.get("label") or {}).get("name", ""), "catalognumber": label.get("catalog-number") or "",
                    "releasetype": (rg.get("primary-type") or "").lower(), "releasecountry": rel.get("country") or "",
                    "musicbrainz_albumid": rid, "musicbrainz_releasegroupid": rgid, "musicbrainz_trackid": t["recording"]["id"],
                    "musicbrainz_releasetrackid": t["id"], "musicbrainz_albumartistid": rel["artist-credit"][0]["artist"]["id"],
                    "musicbrainz_artistid": t["artist-credit"][0]["artist"]["id"], "barcode": rel.get("barcode") or ""}
            for k, v in tags.items():
                if v: a[k] = v
            if small.exists():
                p = Picture(); p.type = 3; p.mime = "image/jpeg"; p.data = small.read_bytes(); p.width = p.height = 600; p.depth = 24
                a.add_picture(p)
            a.save()
    summary.append((albumartist, rel["title"], year, genre, sum(len(m["tracks"]) for m in rel["media"]), str(folder.relative_to(OUT))))
    print("built", summary[-1])
json.dump(summary, open(OUT.parent / "albums.json", "w"), ensure_ascii=False, indent=1)
