"""Tags from file names: patterns, suggestions, and writing them safely."""

import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.fromnames import PatternError, compile_pattern, suggest
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


@pytest.mark.parametrize(("pattern", "rel", "expected"), [
    ("{track} - {artist} - {title}", "Downloads/03 - Radiohead - Bodysnatchers.flac",
     {"tracknumber": "3", "artist": "Radiohead", "title": "Bodysnatchers"}),
    ("{track} - {title}", "In Rainbows/03  -  Nude.mp3", {"tracknumber": "3", "title": "Nude"}),
    ("{artist}/{album} ({year})/{track} - {title}", "Music/Radiohead/In Rainbows (2007)/01 - 15 Step.flac",
     {"artist": "Radiohead", "album": "In Rainbows", "date": "2007", "tracknumber": "1", "title": "15 Step"}),
    ("{artist} - {title}", "M.I.A. - Paper Planes (Diplo Remix).mp3", {"artist": "M.I.A.", "title": "Paper Planes (Diplo Remix)"}),
    ("{track} {skip} - {title}", "01 [HQ] - Song.mp3", {"tracknumber": "1", "title": "Song"}),
    ("{track} - {artist} - {title}", "03 - Artist - Song - Live.flac", {"tracknumber": "3", "artist": "Artist", "title": "Song - Live"}),
])
def test_patterns_read_names(pattern, rel, expected):
    assert compile_pattern(pattern).match(rel) == expected


@pytest.mark.parametrize(("pattern", "rel"), [
    ("{track} - {title}", "Album/Nude.mp3"),  # no " - "
    ("{track} - {title}", "Album/Intro - Song.flac"),  # "Intro" isn't a number
    ("{artist}/{album} ({year})/{title}", "Radiohead/In Rainbows (soon)/x.flac"),  # not a year
])
def test_names_that_dont_fit_are_left_alone(pattern, rel):
    assert compile_pattern(pattern).match(rel) is None


@pytest.mark.parametrize("bad", ["", "{nope} - {title}", "just words", "x" * 301])
def test_bad_patterns_are_explained(bad):
    with pytest.raises(PatternError):
        compile_pattern(bad)


def test_suggestions_fit_the_files():
    assert suggest(["DL/03 - Radiohead - Nude.flac", "DL/04 - Radiohead - Weird Fishes.flac"]) == "{track} - {artist} - {title}"
    assert suggest(["Radiohead/In Rainbows (2007)/01 - 15 Step.flac"]) == "{artist}/{album} ({year})/{track} - {title}"
    assert suggest(["Paper Planes.mp3"]) == "{title}"
    # "Artist - Album (Year)" folders: not "Downloads" as the artist and "Radiohead - 15 Step" as a title.
    scene = ["Downloads/Radiohead - In Rainbows (2007)/01 - Radiohead - 15 Step.flac",
             "Downloads/Radiohead - In Rainbows (2007)/02 - Radiohead - Nude.flac"]
    best = suggest(scene)
    assert compile_pattern(best).match(scene[0]) == {"artist": "Radiohead", "album": "In Rainbows", "date": "2007",
                                                     "tracknumber": "1", "title": "15 Step"}


@pytest.fixture
def client(tmp_path):
    album = tmp_path / "music" / "Radiohead" / "In Rainbows (2007)"
    album.mkdir(parents=True)
    e = MetadataEngine()
    for name, src in (("01 - 15 Step.flac", "sample.flac"), ("02 - Bodysnatchers.mp3", "sample.mp3"),
                      ("03_-_Nude.flac", "sample.flac"), ("Bonus.flac", "sample.flac")):
        shutil.copy2(FIXTURES_DIR / src, album / name)
        e.update_tags(album / name, {"title": None, "tracknumber": None, "album": None, "date": None, "artist": "Keep Me"})
    with TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config", auth=False))) as c:
        yield c


FOLDER = "Radiohead/In Rainbows (2007)"


def tags(c, name):
    return c.get("/api/track", params={"path": f"{FOLDER}/{name}"}).json()["tags"]


def test_codetta_suggests_a_pattern_and_shows_what_fits(client):
    d = client.post("/api/tags/from-names", json={"folder": FOLDER}).json()
    assert d["suggested"] and d["pattern"] == "{artist}/{album} ({year})/{track} - {title}"
    assert d["unmatched_count"] == 2 and {u.rsplit("/", 1)[1] for u in d["unmatched"]} == {"03_-_Nude.flac", "Bonus.flac"}
    assert tags(client, "01 - 15 Step.flac").get("title") is None  # a preview writes nothing


def test_existing_tags_are_kept_unless_asked(client):
    body = {"folder": FOLDER, "pattern": "{artist}/{album} ({year})/{track} - {title}"}
    d = client.post("/api/tags/from-names", json=body).json()
    keys = {ch["key"] for p in d["preview"] for ch in p["changes"]}
    assert "artist" not in keys and {"title", "album", "date", "tracknumber"} <= keys  # "Keep Me" stays
    d = client.post("/api/tags/from-names", json={**body, "keep_existing": False}).json()
    assert any(ch["key"] == "artist" and ch["new"] == "Radiohead" for p in d["preview"] for ch in p["changes"])


def test_underscores_can_count_as_spaces(client):
    body = {"paths": [f"{FOLDER}/03_-_Nude.flac"], "pattern": "{track} - {title}"}
    assert client.post("/api/tags/from-names", json=body).json()["changing"] == 0
    d = client.post("/api/tags/from-names", json={**body, "underscores": True}).json()
    assert d["changing"] == 1 and {ch["new"] for ch in d["preview"][0]["changes"]} == {"3", "Nude"}


def test_filling_in_writes_real_files_and_can_be_undone(client):
    r = client.post("/api/tags/from-names", json={"folder": FOLDER, "pattern": "{track} - {title}", "dry_run": False}).json()
    assert r["changed"] == 2
    assert tags(client, "02 - Bodysnatchers.mp3")["title"] == ["Bodysnatchers"]
    assert tags(client, "02 - Bodysnatchers.mp3")["tracknumber"] == ["2"]
    entry = client.get("/api/activity").json()[0]
    assert entry["message"] == "Tags from file names: 2 tracks"
    client.post(f"/api/activity/{entry['id']}/undo")
    assert "title" not in tags(client, "02 - Bodysnatchers.mp3")


def test_a_bad_pattern_is_refused_and_paths_stay_inside(client):
    assert client.post("/api/tags/from-names", json={"folder": FOLDER, "pattern": "{oops}"}).status_code == 422
    assert client.post("/api/tags/from-names", json={"paths": ["../x.flac"], "pattern": "{title}"}).status_code in (400, 422)
