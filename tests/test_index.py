"""Library-wide search: query parsing, matching, the index and the API."""

import os
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.index import LibraryIndex, parse_query, sfold, word_match
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

# --- Parsing and matching -------------------------------------------------------------------


def test_parse_key_values_and_words():
    q = parse_query("Genre: Rap, Hip-Hop Artist: Drake")
    assert [(c.key, c.values) for c in q.clauses] == [("genre", ["Rap", "Hip-Hop"]), ("artist", ["Drake"])]
    assert q.words == []
    q = parse_query("night drive")
    assert q.words == ["night", "drive"] and q.clauses == []


def test_parse_labels_aliases_and_words_before_keys():
    q = parse_query("summer album artist: Aurora Lane year: 2023")
    assert q.words == ["summer"]
    assert [(c.key, c.values) for c in q.clauses] == [("albumartist", ["Aurora Lane"]), ("date", ["2023"])]


def test_unknown_keys_stay_plain_text_unless_the_tag_exists():
    q = parse_query("Re: Stacks")
    assert q.clauses == [] and q.words == ["Re:", "Stacks"]
    q = parse_query("vibe: chill", is_custom_key=lambda k: k == "vibe")
    assert [(c.key, c.values) for c in q.clauses] == [("vibe", ["chill"])]


def test_fold_and_word_matching():
    assert sfold("Beyoncé") == "beyonce" and sfold("Hip-Hop") == "hip hop" and sfold("Don't") == "dont"
    assert word_match(sfold("Hip-Hop, Trap, Rap"), sfold("rap"))
    assert not word_match(sfold("Trap"), sfold("rap"))  # "rap" must start a word
    assert word_match(sfold("Drake & Future"), sfold("drake"))
    assert word_match(sfold("Hip Hop"), sfold("hip-hop"))
    assert word_match(sfold("夜に駆ける"), sfold("駆ける"))  # no spaces in Japanese: match anywhere


# --- The index ---------------------------------------------------------------------------------


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "music"
    engine = MetadataEngine()

    def add(rel, **tags):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FIXTURES_DIR / "sample.flac", path)
        engine.update_tags(path, {k: v for k, v in tags.items()})
        return path

    add("Drake/Views/01 - Keep the Family Close.flac", title="Keep the Family Close", artist="Drake", genre="Hip-Hop, Rap")
    add("Drake/Views/02 - 9.flac", title="9", artist="Drake", genre="Rap")
    add("Trap Lord/01 - Trap Song.flac", title="Trap Song", artist="Ferg", genre="Trap")
    add("Beyoncé/Lemonade/01 - Pray You Catch Me.flac", title="Pray You Catch Me", artist="Beyoncé", genre="R&B")
    add("Misc/.hidden.flac", title="Hidden", genre="Rap")  # hidden files are skipped
    return root, add, engine


def make_index(root, tmp_path, engine):
    from codetta.web.app import _to_track_out

    def describe(path, rel):
        return _to_track_out(rel, engine.load_metadata(path)).model_dump()

    return LibraryIndex(root, tmp_path / "config" / "library-index.sqlite3", describe)


def test_musicbrainz_album_id_is_kept_for_library_health(library, tmp_path):
    # Library health counts albums "not matched on MusicBrainz yet" from the index: the album
    # ID must be there (other IDs are still left out, to keep the index small).
    root, add, engine = library
    add("Drake/Views/01 - Keep the Family Close.flac", title="Keep the Family Close", artist="Drake",
        musicbrainz_albumid="11111111-1111-4111-8111-111111111111", musicbrainz_trackid="22222222-2222-4222-8222-222222222222")
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    assert idx.paths_with_any(("musicbrainz_albumid",)) == {"Drake/Views/01 - Keep the Family Close.flac"}
    assert not idx.has_key("musicbrainz_trackid")


def titles(tracks):
    return [t["tags"]["title"][0] for t in tracks]


def test_search_by_genre_artist_and_words(library, tmp_path):
    root, _, engine = library
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    assert idx.status().files == 4 and idx.status().ready

    tracks, total = idx.search(parse_query("genre: rap"))
    assert titles(tracks) == ["Keep the Family Close", "9"] and total == 2  # not "Trap"
    tracks, _ = idx.search(parse_query("Genre: Rap, Trap"))
    assert set(titles(tracks)) == {"Keep the Family Close", "9", "Trap Song"}
    tracks, _ = idx.search(parse_query("genre: hip-hop artist: drake"))
    assert titles(tracks) == ["Keep the Family Close"]
    tracks, _ = idx.search(parse_query("beyonce"))  # accent-insensitive
    assert titles(tracks) == ["Pray You Catch Me"]
    tracks, _ = idx.search(parse_query("family close"))
    assert titles(tracks) == ["Keep the Family Close"]
    assert idx.search(parse_query("artist: nobody"))[1] == 0
    assert idx.search(parse_query(""))[1] == 0


def test_results_are_capped_but_counted(library, tmp_path):
    root, _, engine = library
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    tracks, total = idx.search(parse_query("genre: rap, trap, r&b"), limit=2)
    assert len(tracks) == 2 and total == 4


def test_rescan_picks_up_added_changed_and_removed_files(library, tmp_path):
    root, add, engine = library
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    add("New/01 - Fresh.flac", title="Fresh", genre="Rap")
    engine.update_tags(root / "Trap Lord/01 - Trap Song.flac", {"genre": ["Rap"]})
    (root / "Drake/Views/02 - 9.flac").unlink()
    idx.scan()
    tracks, _ = idx.search(parse_query("genre: rap"))
    assert set(titles(tracks)) == {"Keep the Family Close", "Trap Song", "Fresh"}


def test_mark_dirty_refreshes_before_the_next_search(library, tmp_path):
    root, _, engine = library
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    engine.update_tags(root / "Beyoncé/Lemonade/01 - Pray You Catch Me.flac", {"genre": ["Pop"]})
    idx.mark_dirty(["Beyoncé/Lemonade/01 - Pray You Catch Me.flac"])
    assert titles(idx.search(parse_query("genre: pop"))[0]) == ["Pray You Catch Me"]


def test_index_survives_restart_and_only_rereads_changed_files(library, tmp_path):
    root, _, engine = library
    make_index(root, tmp_path, engine).scan()
    reads = []
    from codetta.web.app import _to_track_out

    def counting(path, rel):
        reads.append(rel)
        return _to_track_out(rel, engine.load_metadata(path)).model_dump()

    idx = LibraryIndex(root, tmp_path / "config" / "library-index.sqlite3", counting)
    idx.scan()
    assert reads == []  # nothing changed, nothing re-read
    assert idx.search(parse_query("artist: drake"))[1] == 2


def test_unreadable_files_are_indexed_with_an_error(library, tmp_path):
    root, _, engine = library
    (root / "Broken").mkdir()
    (root / "Broken" / "bad.flac").write_bytes(b"not audio")
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    tracks, _ = idx.search(parse_query("bad"))
    assert len(tracks) == 1 and tracks[0]["error"]


def test_folder_link_loops_dont_hang_the_scan(library, tmp_path):
    root, _, engine = library
    os.symlink(root, root / "Drake" / "loop")
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    assert idx.status().files == 4


def test_unwritable_config_falls_back_to_memory(library, tmp_path):
    root, _, engine = library
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x")
    from codetta.web.app import _to_track_out
    idx = LibraryIndex(root, blocker / "index.sqlite3", lambda p, r: _to_track_out(r, engine.load_metadata(p)).model_dump())
    idx.scan()
    assert idx.search(parse_query("artist: drake"))[1] == 2


def test_background_thread_builds_and_stops(library, tmp_path):
    root, _, engine = library
    idx = make_index(root, tmp_path, engine)
    idx.start()
    deadline = time.monotonic() + 10
    while not idx.status().ready and time.monotonic() < deadline:
        time.sleep(0.05)
    idx.stop()
    assert idx.status().files == 4


# --- API -----------------------------------------------------------------------------------------


@pytest.fixture
def client(library, tmp_path):
    root, _, _ = library
    app = create_app(Settings(music_dir=root, config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": "correct horse 1"})
        app.state.index.scan()
        yield c


def test_search_api(client):
    data = client.get("/api/search", params={"q": "Genre: Rap, Hip-Hop Artist: Drake"}).json()
    assert data["search"]["total"] == 2 and data["search"]["indexing"] is False
    assert [c["label"] for c in data["search"]["clauses"]] == ["Genre", "Artist"]
    assert data["tracks"][0]["path"] == "Drake/Views/01 - Keep the Family Close.flac"
    assert data["tracks"][0]["tags"]["artist"] == ["Drake"]


def test_edits_show_up_in_search_immediately(client):
    path = "Trap Lord/01 - Trap Song.flac"
    assert client.patch("/api/tracks", json={"paths": [path], "changes": {"genre": "Drill"}}).json()[0]["ok"]
    data = client.get("/api/search", params={"q": "genre: drill"}).json()
    assert [t["path"] for t in data["tracks"]] == [path]


def test_search_input_is_bounded(client):
    assert client.get("/api/search", params={"q": "x" * 501}).status_code == 422
    assert client.get("/api/search", params={"q": "rap", "limit": 5000}).status_code == 422


def test_search_requires_sign_in(client):
    client.cookies.clear()
    assert client.get("/api/search", params={"q": "rap"}).status_code == 401


# --- Footprint ----------------------------------------------------------------------------------


def test_technical_and_long_tags_are_not_indexed_but_editor_gets_them(library, tmp_path):
    root, add, engine = library
    big = "AQAD" + "x" * 3000
    add("Big/01 - Big.flac", title="Big", artist="Somebody", acoustid_fingerprint=big,
        musicbrainz_trackid="4f0c3a8e-0000-4000-8000-000000000000", lyrics="la " * 2000)
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    tracks, _ = idx.search(parse_query("artist: somebody"))
    t = tracks[0]
    assert t["partial"] is True
    assert "acoustid_fingerprint" not in t["tags"] and "musicbrainz_trackid" not in t["tags"]
    assert "lyrics" not in t["tags"]  # too long to store; the editor reloads it from the file
    assert idx.search(parse_query("acoustid_fingerprint: aqad"))[1] == 0


def test_index_stays_small(library, tmp_path):
    root, add, engine = library
    for i in range(40):
        add(f"Many/{i:02d}.flac", title=f"Song {i}", artist="Band", acoustid_fingerprint="AQAD" + "y" * 4000,
            lyrics="words " * 800, musicbrainz_trackid=f"00000000-0000-4000-8000-{i:012d}")
    db = tmp_path / "config" / "library-index.sqlite3"
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    idx.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # 44 files with ~9 KB of tags each: the index keeps well under 1 KB per file.
    per_file = db.stat().st_size / idx.status().files
    assert per_file < 2500, per_file


def test_no_timer_rescans_only_when_asked(library, tmp_path):
    root, add, engine = library
    idx = make_index(root, tmp_path, engine)
    idx.rescan_seconds = 0
    idx.start()
    deadline = time.monotonic() + 10
    while not idx.status().ready and time.monotonic() < deadline:
        time.sleep(0.05)
    add("Later/01 - Late.flac", title="Late")
    time.sleep(0.5)
    assert idx.status().files == 4  # nothing looks at the disk on its own
    idx.request_rescan()
    deadline = time.monotonic() + 10
    while idx.status().files != 5 and time.monotonic() < deadline:
        time.sleep(0.05)
    idx.stop()
    assert idx.status().files == 5


def test_old_index_layout_is_rebuilt(library, tmp_path):
    import sqlite3
    root, _, engine = library
    db_path = tmp_path / "config" / "library-index.sqlite3"
    db_path.parent.mkdir(parents=True)
    old = sqlite3.connect(db_path)
    old.executescript("CREATE TABLE files (path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER, text TEXT, track TEXT);"
                      "CREATE TABLE tags (path TEXT, key TEXT, value TEXT); PRAGMA user_version=1;")
    old.commit(); old.close()
    idx = make_index(root, tmp_path, engine)
    idx.scan()
    assert idx.search(parse_query("artist: drake"))[1] == 2


def test_big_scan_with_helper_processes_matches_a_plain_scan(tmp_path, monkeypatch):
    """A big scan farms files out to helper processes; the index must come out identical."""
    import shutil
    from codetta.core import index as index_mod
    from codetta.core.describe import describe_file, describe_many
    from codetta.core.index import LibraryIndex
    from tests.conftest import FIXTURES_DIR
    root = tmp_path / "music"
    for i in range(120):
        d = root / f"Artist {i % 7}" / f"Album {i % 5}"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FIXTURES_DIR / ("sample.flac" if i % 2 else "sample.mp3"), d / f"{i:03d}.{'flac' if i % 2 else 'mp3'}")
    monkeypatch.setattr(index_mod, "PAR_START", 10)
    monkeypatch.setattr(index_mod, "PAR_CHUNK", 16)
    plain = LibraryIndex(root, tmp_path / "plain.sqlite3", describe_file)
    plain.scan()
    fast = LibraryIndex(root, tmp_path / "fast.sqlite3", describe_file, parallel=describe_many, workers=3)
    fast.scan()
    a = {p: t for p, t in plain.iter_tracks()}
    b = {p: t for p, t in fast.iter_tracks()}
    assert len(a) == 120 and a == b


def test_a_helper_that_dies_doesnt_lose_files(tmp_path, monkeypatch):
    import shutil
    from codetta.core import index as index_mod
    from codetta.core.describe import describe_file, describe_many
    from codetta.core.index import LibraryIndex, _Workers
    from tests.conftest import FIXTURES_DIR
    root = tmp_path / "music"; root.mkdir()
    for i in range(60):
        shutil.copy2(FIXTURES_DIR / "sample.mp3", root / f"{i:03d}.mp3")
    monkeypatch.setattr(index_mod, "PAR_START", 5)
    monkeypatch.setattr(index_mod, "PAR_CHUNK", 8)
    real_init = _Workers.__init__

    def broken(self, n, fallback):
        real_init(self, n, fallback)
        self.procs[0].kill()  # one helper is gone before it does anything
    monkeypatch.setattr(_Workers, "__init__", broken)
    idx = LibraryIndex(root, tmp_path / "i.sqlite3", describe_file, parallel=describe_many, workers=2)
    idx.scan()
    assert idx.status().files == 60


def test_stored_sort_key_orders_like_natural_sort():
    import random
    from codetta.core.index import natural_sort_text
    from codetta.core.library import natural_key
    names = ["Disc 10/01.flac", "Disc 2/01.flac", "disc 2/02.flac", "Ärzte/1.mp3", "Arzte/2.mp3", "a/10 x.mp3",
             "a/9 x.mp3", "a/x.mp3", "B/2.flac", "b/10.flac", "Zoë/1.flac", "zoe/2.flac", "007/a.mp3", "7/b.mp3",
             "東京/1.flac", "Track 100.mp3", "Track 99.mp3"]
    random.Random(1).shuffle(names)
    assert sorted(names, key=natural_sort_text) == sorted(names, key=natural_key)
