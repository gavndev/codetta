"""Advanced mode: the raw tag view lists fields exactly as each format stores them."""

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.rawtags import MAX_VALUE_CHARS, read_raw
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR, SAMPLE_FILES

# How each format natively names the title field.
NATIVE_TITLE = {
    "flac": "title", "ogg": "title", "opus": "title", "oga": "TITLE", "spx": "TITLE",
    "mp3": "TIT2", "mp2": "TIT2", "wav": "TIT2", "aiff": "TIT2", "dsf": "TIT2", "tta": "TIT2",
    "m4a": "\xa9nam", "m4b": "\xa9nam", "wv": "Title", "wma": "Title",
    "ape": "Title", "mpc": "Title", "dff": "TIT2",
}


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_raw_view_shows_native_names_and_pictures(fixture_copy, name):
    engine = MetadataEngine()
    path = fixture_copy(name)
    engine.update_artwork(path, (FIXTURES_DIR / "cover.jpg").read_bytes())
    raw = read_raw(engine, path)
    by_name = {e["name"]: e for e in raw["entries"]}
    title = by_name[NATIVE_TITLE[path.suffix[1:]]]
    assert "Test Track" in title["value"] and title["kind"] == "text"
    pictures = [e for e in raw["entries"] if e["kind"] == "picture"]
    assert len(pictures) == 1 and "image/jpeg" in pictures[0]["value"]
    assert raw["system"]


def test_long_values_are_shortened_for_display(fixture_copy):
    engine = MetadataEngine()
    path = fixture_copy("sample.flac")
    engine.update_tags(path, {"lyrics": "la " * 3000})
    entry = next(e for e in read_raw(engine, path)["entries"] if e["name"].lower() == "lyrics")
    assert len(entry["value"]) == MAX_VALUE_CHARS + 1 and entry["length"] == 9000


def test_raw_api(tmp_path):
    import shutil
    (tmp_path / "music").mkdir()
    shutil.copy2(FIXTURES_DIR / "sample.mp3", tmp_path / "music" / "a.mp3")
    with TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config"))) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": "correct horse 1"})
        data = c.get("/api/track/raw", params={"path": "a.mp3"}).json()
        assert data["format"] == "mp3" and data["system"] == "ID3v2.4"
        assert c.get("/api/track/raw", params={"path": "../etc/passwd"}).status_code in (400, 404)
        c.cookies.clear()
        assert c.get("/api/track/raw", params={"path": "a.mp3"}).status_code == 401
