"""Check a built desktop app really works: unzip the portable archive, start it without a window,
sign in the way its window does, browse, search, stream, then Quit.

    python packaging/smoke.py packaging/dist/Codetta-<version>-<system>-<cpu>-Portable.zip
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample.flac"


def fail(msg: str, log: Path | None = None) -> None:
    if log and log.exists():
        print(log.read_text("utf-8", "replace")[-4000:])
    raise SystemExit(f"SMOKE TEST FAILED: {msg}")


def main(archive: str) -> None:
    work = Path(tempfile.mkdtemp(prefix="codetta-smoke-"))
    if sys.platform == "darwin":
        subprocess.run(["ditto", "-x", "-k", archive, str(work)], check=True)
    else:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                z.extract(info, work)
                mode = info.external_attr >> 16
                if mode:
                    os.chmod(work / info.filename, mode)
    root = work / "Codetta"
    exe = {"win32": root / "Codetta.exe", "darwin": root / "Codetta.app" / "Contents" / "MacOS" / "Codetta"}.get(
        sys.platform, root / "Codetta")
    if not exe.is_file():
        fail(f"no app at {exe}")
    album = root / "Music" / "Smoke Test" / "Album"
    album.mkdir(parents=True)
    for n in range(1, 4):
        shutil.copy2(FIXTURE, album / f"0{n} - Track.flac")
    data = root / "Codetta Data" / "config"
    out = work / "app.log"
    proc = subprocess.Popen([str(exe)], cwd=root, env={**os.environ, "CODETTA_NO_WINDOW": "1"},
                            stdout=out.open("w"), stderr=subprocess.STDOUT)
    try:
        end = time.monotonic() + 120
        while not (data / "running.json").exists():
            if proc.poll() is not None or time.monotonic() > end:
                fail("the app didn't start", out)
            time.sleep(0.5)
        info = json.loads((data / "running.json").read_text())
        base = f"http://127.0.0.1:{info['port']}"
        jar = http.cookiejar.CookieJar()
        web = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        web.addheaders = [("Sec-Fetch-Site", "same-origin")]

        def get(path: str, method: str = "GET") -> bytes:
            req = urllib.request.Request(base + path, method=method, data=b"" if method == "POST" else None)
            with web.open(req, timeout=30) as r:
                return r.read()

        get(f"/api/auth/desktop?token={info['token']}")
        status = json.loads(get("/api/auth/status"))
        assert status["signed_in"] and status["desktop"], status
        assert b"codetta" in get("/").lower()
        assert json.loads(get("/api/browse?path=Smoke%20Test/Album"))["tracks"], "no tracks"
        for _ in range(60):  # the search index fills in the background
            if json.loads(get("/api/search?q=Track")).get("tracks"):
                break
            time.sleep(0.5)
        else:
            fail("search found nothing", out)
        assert len(get("/api/stream?path=Smoke%20Test/Album/01%20-%20Track.flac")) > 1000
        bundled = list(exe.parent.parent.rglob("fpcalc*")) if sys.platform == "darwin" else list(root.rglob("fpcalc*"))
        print("fpcalc bundled:", [p.name for p in bundled] or "no")
        get("/api/desktop/quit", "POST")
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            fail("the app didn't quit", out)
        if (data / "running.json").exists():
            fail("running.json was left behind", out)
        print(f"smoke test passed: {exe.name}, signed in as {status['username']}, quit cleanly")
    finally:
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1])
