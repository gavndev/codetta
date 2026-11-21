"""Codetta's benchmark: times every heavy path on a synthetic library, in-process.

    python tools/bench.py [--tracks 20000] [--dir /path/on/the/disk/to/test] [--keep]

It builds a library of small tagged files (artists x albums x 10 tracks, plus one big
"Downloads" folder), then measures the first scan, browsing, search, batch tag edits,
Organize, Library health, importing, the inbox, single big-file saves, page start-up
requests, memory, and how many MusicBrainz requests a match costs (through a counting
fake, so nothing goes online). Use --dir to test a particular disk (a Raspberry Pi's
USB drive, a NAS share). Numbers are printed as a table; nothing is changed outside --dir.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from codetta.core.engine import MetadataEngine  # noqa: E402
from codetta.web.app import Settings, create_app  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
GENRES = ["Rock", "Hip-Hop", "Electronic", "Jazz", "Folk", "Pop", "R&B", "Classical", "Ambient", "Soul"]
rows: list[tuple[str, str, str]] = []


def timed(label, fn, note="", runs=1):
    times = []
    out = None
    for _ in range(runs):
        t = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t)
    best = min(times) if runs > 1 else times[0]
    rows.append((label, f"{best * 1000:,.0f} ms" if best < 10 else f"{best:,.1f} s", note))
    print(f"  {label:<46} {rows[-1][1]:>10}  {note}", flush=True)
    return out


def album_path(a: int) -> str:
    return f"Artist {a // 5:04d}/Album {a % 5} ({1990 + a % 30})"


def track_path(a: int, t: int) -> str:
    return f"{album_path(a)}/{t:02d} Song {t}{'.flac' if a % 2 == 0 else '.mp3'}"


def build_library(music: Path, tracks: int) -> int:
    """artists x 5 albums x 10 tracks, alternating FLAC and MP3 albums, plus Downloads/ with 1,000 loose files."""
    engine = MetadataEngine()
    flac, mp3 = (FIX / "sample.flac").read_bytes(), (FIX / "sample.mp3").read_bytes()
    albums = max(1, tracks // 10)
    made = 0
    for a in range(albums):
        artist, n = f"Artist {a // 5:04d}", a % 5
        folder = music / album_path(a)
        folder.mkdir(parents=True, exist_ok=True)
        ext, data = (".flac", flac) if a % 2 == 0 else (".mp3", mp3)
        for t in range(1, 11):
            p = folder / f"{t:02d} Song {t}{ext}"
            p.write_bytes(data)
            engine.update_tags(p, {"title": f"Song {t} of album {a}", "artist": artist, "albumartist": artist,
                                   "album": f"Album {n}", "date": str(1990 + a % 30), "genre": GENRES[a % len(GENRES)],
                                   "tracknumber": str(t), "discnumber": "1"})
            made += 1
    dl = music / "Downloads"
    dl.mkdir(exist_ok=True)
    for i in range(1000):
        (dl / f"track_{i:04d}.mp3").write_bytes(mp3)
        made += 1
    return made


def wait(c, pred, timeout=900):
    end = time.time() + timeout
    while not pred():
        if time.time() > end:
            raise TimeoutError("waited too long")
        time.sleep(0.05)


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tracks", type=int, default=20000)
    ap.add_argument("--dir", type=Path, default=None, help="where to build the library (default: a temp folder)")
    ap.add_argument("--keep", action="store_true", help="keep the library afterwards")
    args = ap.parse_args()
    base = Path(tempfile.mkdtemp(prefix="codetta-bench-", dir=args.dir))
    music, config = base / "music", base / "config"
    music.mkdir()
    print(f"Codetta benchmark in {base}")
    try:
        n = timed("build the library (not Codetta)", lambda: build_library(music, args.tracks), f"{args.tracks:,} tracks + 1,000 loose")

        from tests.test_musicbrainz import FakeMB  # a counting stand-in for MusicBrainz
        fake = FakeMB()
        app = create_app(Settings(music_dir=music, config_dir=config, auth=False), fetch_mb=fake, fetch_art=lambda url: None)
        with TestClient(app) as c:
            idx = app.state.index
            timed("first scan (search index)", lambda: wait(c, lambda: idx.status().ready), f"{n:,} files, {os.cpu_count()} CPUs")
            timed("rescan, nothing changed", lambda: (idx.mark_dirty([""]), time.sleep(0.2), wait(c, lambda: idx.status().ready)))

            # --- Browsing ---------------------------------------------------------------------
            album = album_path(0)
            timed("open the library root", lambda: c.get("/api/browse", params={"path": ""}).raise_for_status(), "", runs=3)
            timed("open an album, first time", lambda: c.get("/api/browse", params={"path": album_path(6)}).raise_for_status())
            timed("open an album again", lambda: c.get("/api/browse", params={"path": album_path(6)}).raise_for_status(), "", runs=3)
            timed("open a 1,000-file folder", lambda: c.get("/api/browse", params={"path": "Downloads"}).raise_for_status())

            # --- Search -----------------------------------------------------------------------
            for q in ["genre: rock", "artist: artist 0042", "song 7", "year: 1999 genre: jazz", "zzz-nothing"]:
                timed(f"search “{q}”", lambda q=q: c.get("/api/search", params={"q": q}).raise_for_status(), "", runs=3)
            timed("search ideas", lambda: c.get("/api/search/ideas").raise_for_status())

            # --- Writing tags -----------------------------------------------------------------
            paths = [track_path(a, t) for a in range(0, 100, 2) for t in range(1, 11)][:500]
            timed("batch edit: genre on 500 files", lambda: c.patch("/api/tracks", json={"paths": paths, "changes": {"genre": "Bench"}}).raise_for_status())
            timed("undo that edit", lambda: c.post(f"/api/activity/{c.get('/api/activity').json()[0]['id']}/undo").raise_for_status())

            big = music / "big.flac"
            shutil.copy2(FIX / "sample.flac", big)
            with open(big, "ab") as f:  # 40 MB of real (not sparse) data, like a long hi-res track
                for _ in range(40):
                    f.write(os.urandom(1024 * 1024))
            eng = MetadataEngine()
            try:
                timed("save one tag on a 40 MB file", lambda: eng.update_tags(big, {"comment": str(time.time())}), "copy, verify, swap", runs=3)
            except Exception as exc:  # noqa: BLE001 - a padded file may not be valid FLAC on every mutagen
                rows.append(("save one tag on a 40 MB file", "skipped", str(exc)[:40]))
            big.unlink(missing_ok=True)

            # --- Organize and health ----------------------------------------------------------
            timed("Organize preview of 50 albums", lambda: c.post("/api/organize/preview", json={"paths": paths}).raise_for_status())
            c.put("/api/library-health/settings", json={"enabled": True, "disabled": []})
            timed("Library health, first look", lambda: c.get("/api/library-health").raise_for_status())
            timed("Library health, again", lambda: c.get("/api/library-health").raise_for_status(), "", runs=3)

            # --- Importing --------------------------------------------------------------------
            data = (FIX / "sample.flac").read_bytes()
            batch = "20261121000000-bnch"

            def upload(k=200):
                out = []
                for i in range(k):
                    r = c.put("/api/import", params={"batch": batch, "path": f"Bench Import/{i:03d}.flac"}, content=data)
                    out.append(r.json()["path"])
                return out

            done = timed("import: upload 200 files", upload)
            timed("import: finish (log + Organize)", lambda: c.post("/api/import/done", json={"batch": batch, "paths": done}).raise_for_status())
            big_body = os.urandom(8 * 1024 * 1024) * 8  # 64 MB, streamed
            timed("import: one 64 MB file", lambda: c.put("/api/import", params={"batch": batch, "path": "big.bin"}, content=big_body).raise_for_status())

            # --- Inbox ------------------------------------------------------------------------
            c.put("/api/connections", json={"enabled": {"musicbrainz": False}})
            timed("inbox: set up on 1,000 loose files", lambda: c.put("/api/inbox/settings", json={"folder": "Downloads"}).raise_for_status())
            timed("inbox: open again (re-reads the folder)", lambda: c.get("/api/inbox").raise_for_status(), "", runs=3)

            # --- MusicBrainz: requests per match ----------------------------------------------
            c.put("/api/connections", json={"enabled": {"musicbrainz": True}})
            fake.urls.clear()
            c.post("/api/musicbrainz/search", json={"folder": album})
            searched = len(fake.urls)
            fake.urls.clear()
            from tests.test_musicbrainz import REL
            c.post("/api/musicbrainz/preview", json={"folder": album, "release": REL})
            c.post("/api/musicbrainz/preview", json={"folder": album, "release": REL})
            rows.append(("MusicBrainz requests: find an album", str(searched), "1 request a second on musicbrainz.org"))
            rows.append(("MusicBrainz requests: review it twice", str(len(fake.urls)), "the second should come from the cache"))
            print(f"  {'MusicBrainz requests: find / review x2':<46} {searched:>5} / {len(fake.urls)}")

            # --- The page ---------------------------------------------------------------------
            html = c.get("/").text
            static = ROOT / "src" / "codetta" / "web" / "static"
            modules = 1 + len(list((static / "js").glob("*.js")))
            total = sum((static / p).stat().st_size for p in ["app.js", "app.css", "theme.js"]) + \
                sum(p.stat().st_size for p in (static / "js").glob("*.js"))
            preloaded = html.count('rel="modulepreload"')
            rows.append(("page start-up: script files", str(modules), f"{preloaded} preloaded; {total / 1024:,.0f} KB before gzip"))
            print(f"  {'page start-up: script files':<46} {modules:>10}  {preloaded} preloaded")

            rows.append(("memory (peak, this process)", f"{rss_mb():,.0f} MB", "includes the benchmark itself"))
            print(f"  {'memory (peak)':<46} {rss_mb():>7,.0f} MB")
    finally:
        if not args.keep:
            shutil.rmtree(base, ignore_errors=True)
    out = Path(os.environ.get("BENCH_JSON", "")) if os.environ.get("BENCH_JSON") else None
    if out:
        out.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
