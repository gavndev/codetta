"""Match album tags: stray tracks take the album's album-wide tags; per-song tags never move."""

import shutil

from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.matchtags import changes_for, is_track_key, shared_album_tags
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR
from tests.test_musicbrainz import PASSWORD, png


def test_per_song_tags_are_never_copied():
    for key in ("title", "artist", "tracknumber", "discnumber", "isrc", "lyrics", "musicbrainz_trackid",
                "replaygain_track_gain", "unsyncedlyrics", "acoustid_fingerprint"):
        assert is_track_key(key), key
    for key in ("album", "albumartist", "date", "genre", "musicbrainz_albumid", "label", "media"):
        assert not is_track_key(key), key


def test_shared_tags_are_what_most_tracks_use():
    tracks = [{"album": ["A"], "date": ["2020"], "title": ["x"]},
              {"album": ["A"], "date": ["2020"], "label": ["L"]},
              {"album": ["A (Deluxe)"], "date": ["2020"]}]
    assert shared_album_tags(tracks) == {"album": ["A"], "date": ["2020"]}  # label: only 1 of 3


def test_changes_copy_and_remove_only_album_tags():
    tags = {"album": ["B"], "title": ["Song"], "label": ["Odd"], "isrc": ["X"]}
    ref = {"album": ["A"], "date": ["2020"]}
    assert changes_for(tags, ref, remove_extra=True) == {"album": ["A"], "date": ["2020"], "label": None}
    assert changes_for(tags, ref, remove_extra=False) == {"album": ["A"], "date": ["2020"]}


def _client(tmp_path):
    album = tmp_path / "music" / "Future" / "The Real Me"
    album.mkdir(parents=True)
    engine = MetadataEngine()
    for n, src in enumerate(["sample.flac", "sample.mp3", "sample.m4a", "sample.ogg", "sample.opus"], 1):
        dest = album / f"{n:02d}.{src.split('.')[1]}"
        shutil.copy2(FIXTURES_DIR / src, dest)
        engine.update_tags(dest, {"title": f"Song {n}", "artist": "Future", "tracknumber": str(n), "album": "The Real Me",
                                  "albumartist": "Future", "date": "2025", "musicbrainz_albumid": "rel-1"})
    stray = album / "05.opus"
    engine.update_tags(stray, {"albumartist": "Future feat. Someone", "date": "2025-01-01", "musicbrainz_albumid": None,
                               "label": "Bootleg", "discnumber": "2"})
    app = create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config"), fetch_art=lambda url: png())
    return album, engine, app


def test_match_from_the_folder(tmp_path):
    album, engine, app = _client(tmp_path)
    rel = "Future/The Real Me/05.opus"
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        dry = c.post("/api/tags/match", json={"paths": [rel]}).json()
        assert dry["changing"] == 1 and dry["source"] == "The Real Me"
        keys = {ch["key"] for ch in dry["preview"][0]["changes"]}
        assert keys == {"albumartist", "date", "musicbrainz_albumid", "label"}
        assert engine.load_metadata(album / "05.opus").tags["albumartist"] == ["Future feat. Someone"]  # dry run
        res = c.post("/api/tags/match", json={"paths": [rel], "dry_run": False}).json()
        assert res["changed"] == 1, res
        tags = engine.load_metadata(album / "05.opus").tags
        assert tags["albumartist"] == ["Future"] and tags["date"] == ["2025"] and tags["musicbrainz_albumid"] == ["rel-1"]
        assert "label" not in tags
        assert tags["title"] == ["Song 5"] and tags["tracknumber"] == ["5"] and tags["discnumber"] == ["2"]  # per song: kept


def test_match_one_track_and_keep_extras(tmp_path):
    album, engine, app = _client(tmp_path)
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        res = c.post("/api/tags/match", json={"paths": ["Future/The Real Me/05.opus"], "track": "Future/The Real Me/01.flac",
                                              "remove_extra": False, "dry_run": False}).json()
        assert res["changed"] == 1 and res["source"] == "01.flac"
        assert engine.load_metadata(album / "05.opus").tags["label"] == ["Bootleg"]
        bad = c.post("/api/tags/match", json={"paths": ["Future/The Real Me/05.opus"], "track": "Future/The Real Me/05.opus"})
        assert bad.status_code == 422
        assert c.post("/api/tags/match", json={"paths": ["Future/The Real Me/05.opus"], "track": "../x"}).status_code == 422
