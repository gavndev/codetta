"""Speed and storage savings: each one must leave what the user sees unchanged."""

import shutil
import time

from fastapi.testclient import TestClient

from codetta.core.organize import prune_replaced
from codetta.core.slskd import IMPORTED, SoulseekStore
from codetta.web.app import Settings, create_app
from codetta.web.security import gzip_worthy
from tests.conftest import FIXTURES_DIR


def client_for(tmp_path):
    music = tmp_path / "music"
    (music / "Album").mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.flac", music / "Album" / "01.flac")
    return TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config", auth=False))), music


def test_text_is_gzipped_media_is_not(tmp_path):
    c, _ = client_for(tmp_path)
    with c:
        js = c.get("/static/app.js", headers={"Accept-Encoding": "gzip"})
        assert js.headers.get("content-encoding") == "gzip" and "accept-encoding" in js.headers.get("vary", "").lower()
        assert "function h(" in js.text  # still the same file once unpacked
        assert c.get("/", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding") == "gzip"
        # Audio stays byte-exact so seeking (range requests) keeps working.
        part = c.get("/api/stream", params={"path": "Album/01.flac"},
                     headers={"Accept-Encoding": "gzip", "Range": "bytes=0-99"})
        assert part.status_code == 206 and len(part.content) == 100 and "content-encoding" not in part.headers
        # Security headers still on compressed answers.
        assert js.headers.get("x-content-type-options") == "nosniff"
    assert not gzip_worthy("/static/fonts/schibsted-grotesk.woff2") and not gzip_worthy("/api/art")
    assert gzip_worthy("/api/browse") and gzip_worthy("/static/app.css")


def test_folder_reopens_from_memory_but_sees_every_change(tmp_path):
    c, music = client_for(tmp_path)
    with c:
        first = c.get("/api/browse", params={"path": "Album"}).json()["tracks"][0]
        assert c.get("/api/browse", params={"path": "Album"}).json()["tracks"][0] == first
        # A save through Codetta shows up straight away...
        c.patch("/api/tracks", json={"paths": ["Album/01.flac"], "changes": {"title": "Renamed"}})
        assert c.get("/api/browse", params={"path": "Album"}).json()["tracks"][0]["tags"]["title"] == ["Renamed"]
        # ...and so does a change made by another program, even within the same second.
        from codetta.core.engine import MetadataEngine
        MetadataEngine().update_tags(music / "Album" / "01.flac", {"title": "Outside"})
        assert c.get("/api/browse", params={"path": "Album"}).json()["tracks"][0]["tags"]["title"] == ["Outside"]


def test_download_progress_is_written_now_and_then(tmp_path):
    store = SoulseekStore(tmp_path / "slskd.json")
    job = store.add_job("x")
    before = store.file.stat().st_mtime_ns
    time.sleep(0.01)
    store.update(job, quiet=True, progress=0.5)
    assert store.file.stat().st_mtime_ns == before  # progress alone: not yet
    assert job.progress == 0.5  # but the page sees it at once
    store.update(job, status="arrived")
    assert SoulseekStore(store.file).jobs[job.id].status == "arrived"  # status changes: always


def test_finished_requests_drop_their_file_lists(tmp_path):
    store = SoulseekStore(tmp_path / "slskd.json")
    job = store.add_job("x")
    files = [{"filename": f"a\\\\{i:02}.flac", "size": 1, "bitRate": None} for i in range(200)]
    store.update(job, candidates=[{"username": "u", "folder": "a", "name": "a", "files": files, "tracks": 200,
                                   "size": 200, "quality": "FLAC", "lossless": True, "free_slot": True, "speed": 1,
                                   "queue": 0, "score": 1}], pick=0)
    big = store.file.stat().st_size
    store.update(job, status=IMPORTED)
    assert store.file.stat().st_size < big / 4
    assert store.jobs[job.id].candidates[0]["tracks"] == 200  # the summary stays


def test_replaced_albums_are_kept_30_days(tmp_path):
    rep = tmp_path / "replaced"
    old = rep / "20200101-120000" / "Artist" / "Album"
    new = rep / time.strftime("%Y%m%d-%H%M%S") / "Artist" / "Album"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "01.flac").write_bytes(b"x")
    (rep / "notes").mkdir()  # not one of ours: never touched
    assert prune_replaced(rep) == 1
    assert not old.exists() and new.exists() and (rep / "notes").exists()
    assert prune_replaced(tmp_path / "missing") == 0


def test_app_code_is_always_revalidated(tmp_path):
    c, _ = client_for(tmp_path)
    with c:
        r = c.get("/static/app.js")
        assert r.headers.get("cache-control") == "no-cache" and r.headers.get("etag")
        assert c.get("/static/app.js", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
