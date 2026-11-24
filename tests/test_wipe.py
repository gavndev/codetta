"""Wipe all tags: every tag goes, the audio and the cover stay, and a dry run changes nothing."""

import shutil

from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR
from tests.test_musicbrainz import PASSWORD, png

FORMATS = ["sample.flac", "sample.mp3", "sample.m4a", "sample.ogg", "sample.opus", "sample.wv"]


def _setup(tmp_path):
    album = tmp_path / "music" / "A" / "B"
    album.mkdir(parents=True)
    engine = MetadataEngine()
    for n, src in enumerate(FORMATS, 1):
        dest = album / f"{n}.{src.split('.')[1]}"
        shutil.copy2(FIXTURES_DIR / src, dest)
        engine.update_tags(dest, {"title": f"T{n}", "artist": ["X", "Y"], "album": "B", "comment": "c",
                                  "tracknumber": str(n), "musicbrainz_trackid": "abc"})
    app = create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config"), fetch_art=lambda url: png())
    return album, engine, app


def test_wipe_removes_every_tag_but_keeps_the_cover(tmp_path):
    album, engine, app = _setup(tmp_path)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        paths = "&".join(f"path=A/B/{p.name}" for p in sorted(album.iterdir()))
        assert c.put(f"/api/art?{paths}", content=png(), headers={"Content-Type": "image/png"}).status_code == 200
        dry = c.post("/api/tags/wipe", json={"folder": "A/B"}).json()
        assert dry["tracks"] == len(FORMATS) and dry["changing"] == len(FORMATS) and dry["tags"] > 0
        assert all(engine.load_metadata(p).tags for p in album.iterdir())  # a dry run writes nothing
        res = c.post("/api/tags/wipe", json={"folder": "A/B", "dry_run": False}).json()
        assert res["changed"] == len(FORMATS) and res["failed"] == 0, res
        for p in album.iterdir():
            assert engine.load_metadata(p).tags == {}, p.name
            assert engine.read_artwork(p) is not None, p.name
        assert c.post("/api/tags/wipe", json={"folder": "A/B", "dry_run": False}).json()["changing"] == 0


def test_wipe_needs_a_target(tmp_path):
    _, _, app = _setup(tmp_path)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        assert c.post("/api/tags/wipe", json={}).status_code == 422
        assert c.post("/api/tags/wipe", json={"folder": "../x", "dry_run": False}).status_code >= 400
