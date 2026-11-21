"""The right-click / long-press menu: Rename, Move to, Delete (to Recently deleted), Get info."""

import shutil
import time

import pytest
from fastapi.testclient import TestClient

from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


@pytest.fixture
def setup(tmp_path):
    music, config = tmp_path / "music", tmp_path / "config"
    album = music / "Artist" / "Album"
    album.mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.flac", album / "01 Song.flac")
    (album / "01 Song.lrc").write_text("[00:01.00] la")
    shutil.copy2(FIXTURES_DIR / "sample.mp3", album / "02 Other.mp3")
    (music / "Elsewhere").mkdir()
    with TestClient(create_app(Settings(music_dir=music, config_dir=config, auth=False))) as c:
        yield c, music, config


def undo_latest(c):
    entry = c.get("/api/activity").json()[0]
    assert entry["can_undo"]
    return c.post(f"/api/activity/{entry['id']}/undo").json()


def test_move_a_file_with_its_lyrics_then_undo(setup):
    c, music, _ = setup
    res = c.post("/api/files/move", json={"paths": ["Artist/Album/01 Song.flac"], "to": "Elsewhere"}).json()
    assert res["moved"] == 1 and res["failed"] == 0
    assert (music / "Elsewhere" / "01 Song.flac").exists() and (music / "Elsewhere" / "01 Song.lrc").exists()
    assert not (music / "Artist" / "Album" / "01 Song.flac").exists()
    undo_latest(c)
    assert (music / "Artist" / "Album" / "01 Song.flac").exists() and (music / "Artist" / "Album" / "01 Song.lrc").exists()


def test_move_a_folder_and_never_into_itself(setup):
    c, music, _ = setup
    assert c.post("/api/files/move", json={"paths": ["Artist"], "to": "Artist/Album"}).status_code == 422
    res = c.post("/api/files/move", json={"paths": ["Artist/Album"], "to": "Elsewhere"}).json()
    assert res["moved"] == 3  # both songs and the lyrics file
    assert (music / "Elsewhere" / "Album" / "02 Other.mp3").exists() and not (music / "Artist" / "Album").exists()


def test_move_never_overwrites(setup):
    c, music, _ = setup
    (music / "Elsewhere" / "02 Other.mp3").write_bytes(b"different")
    res = c.post("/api/files/move", json={"paths": ["Artist/Album/02 Other.mp3"], "to": "Elsewhere"}).json()
    assert res["failed"] == 1 and (music / "Elsewhere" / "02 Other.mp3").read_bytes() == b"different"


def test_rename_keeps_the_extension_and_the_lyrics_follow(setup):
    c, music, _ = setup
    res = c.post("/api/files/rename", json={"path": "Artist/Album/01 Song.flac", "name": "01 Better Name"}).json()
    assert res["path"] == "Artist/Album/01 Better Name.flac"
    assert (music / "Artist" / "Album" / "01 Better Name.lrc").exists()
    shutil.copy2(FIXTURES_DIR / "sample.flac", music / "Artist" / "Album" / "03 Taken.flac")
    assert c.post("/api/files/rename", json={"path": "Artist/Album/01 Better Name.flac", "name": "03 Taken"}).status_code == 409
    undo_latest(c)
    assert (music / "Artist" / "Album" / "01 Song.flac").exists()


def test_delete_goes_to_recently_deleted_and_can_be_undone(setup):
    c, music, config = setup
    res = c.post("/api/files/delete", json={"paths": ["Artist/Album"]}).json()
    assert res["moved"] == 3 and not (music / "Artist" / "Album").exists()
    kept = list((config / "deleted").rglob("*.flac"))
    assert len(kept) == 1 and kept[0].name == "01 Song.flac"  # nothing is erased, just set aside
    entry = c.get("/api/activity").json()[0]
    assert entry["kind"] == "delete" and "Recently deleted" in entry["message"]
    undo_latest(c)
    assert (music / "Artist" / "Album" / "01 Song.flac").exists() and (music / "Artist" / "Album" / "01 Song.lrc").exists()


def test_paths_outside_the_library_are_refused(setup):
    c, _, _ = setup
    for body in ({"paths": ["../x"]}, {"paths": ["@deleted/x"]}, {"paths": [""]}):
        assert c.post("/api/files/delete", json=body).status_code in (400, 422)
    assert c.post("/api/files/move", json={"paths": ["Artist"], "to": "@deleted"}).status_code == 404


def test_get_info_for_a_file_and_a_folder(setup):
    c, _, _ = setup
    f = c.get("/api/files/info", params={"path": "Artist/Album/01 Song.flac"}).json()
    assert f["kind"] == "file" and f["format"] == "flac" and f["size"] > 0 and f["sample_rate"] == 44100
    assert f["tag_kind"] == "Vorbis comments" and f["bits_per_sample"]
    m = c.get("/api/files/info", params={"path": "Artist/Album/02 Other.mp3"}).json()
    assert m["tag_kind"].startswith("ID3v2")
    d = c.get("/api/files/info", params={"path": "Artist"}).json()
    assert d["kind"] == "folder" and d["audio"] == 2 and d["files"] == 3 and d["folders"] == 1


def test_folder_picker_lists_only_folders(setup):
    c, _, _ = setup
    assert c.get("/api/folders").json()["folders"] == [{"name": "Artist", "path": "Artist"}, {"name": "Elsewhere", "path": "Elsewhere"}]
    assert c.get("/api/folders", params={"path": "Artist"}).json()["folders"] == [{"name": "Album", "path": "Artist/Album"}]


def test_the_menu_routes_need_sign_in(tmp_path):
    with TestClient(create_app(Settings(music_dir=tmp_path, config_dir=tmp_path / "c"))) as c:
        for method, url in [("post", "/api/files/move"), ("post", "/api/files/rename"), ("post", "/api/files/delete"),
                            ("get", "/api/files/info?path=x"), ("get", "/api/folders")]:
            assert getattr(c, method)(url, json={}).status_code == 401 if method == "post" else c.get(url).status_code == 401


# --- Advanced mode -------------------------------------------------------------------------------


def test_in_file_tag_names_per_format(setup):
    c, _, _ = setup
    mp3 = c.get("/api/tagnames", params={"format": "mp3"}).json()["names"]
    assert mp3["artist"] == "TPE1" and mp3["albumartist"] == "TPE2" and mp3["itunesadvisory"] == "TXXX:ITUNESADVISORY"
    assert mp3["producer"] == "TIPL" and mp3["originaldate"] == "TDOR"
    m4a = c.get("/api/tagnames", params={"format": "m4a"}).json()["names"]
    assert m4a["artist"] == "©ART" and m4a["itunesadvisory"] == "rtng" and m4a["compilation"] == "cpil"
    assert c.get("/api/tagnames", params={"format": "flac"}).json()["names"]["albumartist"] == "ALBUMARTIST"
    assert set(c.get("/api/tagnames", params={"format": "nope"}).json()["names"].values()) == {None}


def test_get_info_has_the_power_user_details(setup):
    c, music, _ = setup
    f = c.get("/api/files/info", params={"path": "Artist/Album/01 Song.flac"}).json()
    assert f["encoder"] and f["fields_supported"] == f["fields_total"] and f["fields_unsupported"] == []
    assert f["on_disk"] == str(music / "Artist" / "Album" / "01 Song.flac")


def test_server_log_is_private_masks_secrets_and_never_lists_visitors(setup, tmp_path):
    import logging
    c, _, _ = setup
    logging.getLogger("codetta").warning("talking to slskd with api_key=SUPERSECRET and Bearer abc.def")
    logging.getLogger("uvicorn.access").info('100.64.0.7:5000 - "GET / HTTP/1.1" 200')
    lines = c.get("/api/logs").json()["lines"]
    text = "\n".join(l["message"] for l in lines)
    assert "api_key=•••" in text and "SUPERSECRET" not in text and "abc.def" not in text
    assert "100.64.0.7" not in text  # access lines are never kept
    after = lines[-1]["id"]
    logging.getLogger("codetta").info("one more line")
    newer = c.get("/api/logs", params={"after": after}).json()["lines"]
    assert "one more line" in [l["message"] for l in newer]  # background jobs may log at the same moment
    assert all(l["id"] > after for l in newer)  # nothing already seen comes again
    with TestClient(create_app(Settings(music_dir=tmp_path, config_dir=tmp_path / "c2"))) as anon:
        assert anon.get("/api/logs").status_code == 401 and anon.get("/api/tagnames?format=mp3").status_code == 401


def test_raw_view_handles_m4a_compilations_and_mp3_credits(tmp_path):
    from codetta.core.engine import MetadataEngine, _open_raw
    from codetta.core.rawtags import raw_tags
    engine = MetadataEngine()
    shutil.copy2(FIXTURES_DIR / "sample.m4a", tmp_path / "a.m4a")
    engine.update_tags(tmp_path / "a.m4a", {"compilation": "1"})
    audio, fmt = _open_raw(tmp_path / "a.m4a")
    assert ("cpil", "True") in {(e["name"], e["value"]) for e in raw_tags(audio, fmt)[1]}  # used to crash
    shutil.copy2(FIXTURES_DIR / "sample.mp3", tmp_path / "b.mp3")
    engine.update_tags(tmp_path / "b.mp3", {"producer": "Pat"})
    audio, fmt = _open_raw(tmp_path / "b.mp3")
    assert {e["name"]: e["value"] for e in raw_tags(audio, fmt)[1]}["TIPL"] == "producer: Pat"


# --- Import ---------------------------------------------------------------------------------------


def test_import_into_the_library_is_organized_and_undoable(setup):
    c, music, config = setup
    data = (FIXTURES_DIR / "sample.flac").read_bytes()  # tagged "Coda Collective / Fixture Album"
    r = c.put("/api/import", params={"batch": "test-0001", "path": "My Album/03 Track.flac"}, content=data).json()
    assert r["audio"] and r["path"].startswith("Imported/Import test-0001/")
    note = c.put("/api/import", params={"batch": "test-0001", "path": "My Album/notes.txt"}, content=b"hi").json()
    assert note["audio"] is False  # not music: still imported (the page warns first)
    done = c.post("/api/import/done", json={"batch": "test-0001", "paths": [r["path"], note["path"]]}).json()
    assert done["where"] == "library" and done["organized"] == 1
    placed = list((music / "Coda Collective").rglob("*.flac"))
    assert len(placed) == 1
    entry = next(e for e in c.get("/api/activity").json() if e["kind"] == "import")
    assert entry["can_undo"] and "Imported 2 files" in entry["message"]


def test_import_lands_in_the_inbox_when_there_is_one(setup):
    c, music, config = setup
    (music / "Downloads").mkdir()
    c.put("/api/inbox/settings", json={"folder": "Downloads"})
    r = c.put("/api/import", params={"batch": "test-0002", "path": "song.flac"}, content=(FIXTURES_DIR / "sample.flac").read_bytes()).json()
    assert r["path"] == "Downloads/Import test-0002/song.flac"
    done = c.post("/api/import/done", json={"batch": "test-0002", "paths": [r["path"]]}).json()
    assert done["where"] == "inbox"
    undo_latest(c)  # undo: the import goes to Recently deleted
    assert not (music / "Downloads" / "Import test-0002" / "song.flac").exists()
    assert list((config / "deleted").rglob("song.flac"))


# --- Recently deleted ------------------------------------------------------------------------------


def test_recently_deleted_lists_and_puts_back(setup):
    c, music, config = setup
    c.post("/api/files/delete", json={"paths": ["Artist/Album/02 Other.mp3"]})
    d = c.get("/api/deleted").json()
    assert d["files"] == 1 and d["items"][0]["what"] == "Artist/Album/02 Other.mp3" and d["items"][0]["expires"] > d["items"][0]["deleted"]
    r = c.post("/api/deleted/restore", json={"ids": [d["items"][0]["id"]]}).json()
    assert r["moved"] == 1 and r["files"] == 0 and (music / "Artist" / "Album" / "02 Other.mp3").exists()


def test_putting_back_never_overwrites(setup):
    c, music, config = setup
    c.post("/api/files/delete", json={"paths": ["Artist/Album/02 Other.mp3"]})
    (music / "Artist" / "Album" / "02 Other.mp3").write_bytes(b"newer")
    bid = c.get("/api/deleted").json()["items"][0]["id"]
    r = c.post("/api/deleted/restore", json={"ids": [bid]}).json()
    assert r["failed"] == 1 and (music / "Artist" / "Album" / "02 Other.mp3").read_bytes() == b"newer"


def test_search_ideas_come_from_the_library(setup):
    c, music, config = setup
    end = time.time() + 10
    while c.get("/api/library-health/summary").json()["indexing"]:
        assert time.time() < end
        time.sleep(0.05)
    ideas = c.get("/api/search/ideas").json()
    assert set(ideas) == {"artist", "album", "genre", "mood"}
    assert all(isinstance(v, list) for v in ideas.values())
    assert ideas["artist"] or ideas["album"]  # the test library has tagged tracks


def test_a_long_imported_name_keeps_its_extension(setup):
    """Long names are shortened before the extension, so the file is still music."""
    from codetta.core.importer import clean_parts
    parts = clean_parts("Album/" + "a" * 300 + ".flac")
    assert parts[-1].endswith(".flac") and len(parts[-1].encode()) <= 255
    assert clean_parts(".hidden.flac")[-1] == "_hidden.flac"
    assert clean_parts("README")[-1] == "README"
    c, music, _ = setup
    data = (FIXTURES_DIR / "sample.flac").read_bytes()
    r = c.put("/api/import", params={"batch": "test-0002", "path": "Ü" * 150 + ".flac"}, content=data).json()
    assert r["audio"] is True and r["path"].endswith(".flac")


def test_import_says_why_files_stayed(setup):
    """A copy of something already in the library stays put (never overwritten), and the answer
    says so, rather than blaming missing tags."""
    c, music, _ = setup
    data = (FIXTURES_DIR / "sample.flac").read_bytes()
    first = c.put("/api/import", params={"batch": "test-0003", "path": "a.flac"}, content=data).json()
    assert c.post("/api/import/done", json={"batch": "test-0003", "paths": [first["path"]]}).json()["organized"] == 1
    again = c.put("/api/import", params={"batch": "test-0004", "path": "a.flac"}, content=data).json()
    untagged = c.put("/api/import", params={"batch": "test-0004", "path": "b.flac"},
                     content=(FIXTURES_DIR / "untagged.flac").read_bytes()).json()
    done = c.post("/api/import/done", json={"batch": "test-0004", "paths": [again["path"], untagged["path"]]}).json()
    assert done["stayed"] == 2 and done["stayed_taken"] == 1 and done["stayed_untagged"] == 1


@pytest.mark.parametrize("name", [" ", ".", "..", " . "])
def test_a_blank_name_is_refused_not_turned_into_an_underscore(setup, name):
    c, music, _ = setup
    r = c.post("/api/folders/rename", json={"path": "Artist/Album", "name": name})
    assert r.status_code == 422 and "name" in r.json()["detail"]
    r = c.post("/api/files/rename", json={"path": "Artist/Album/01 Song.flac", "name": name})
    assert r.status_code == 422
    assert (music / "Artist" / "Album" / "01 Song.flac").is_file()


def test_report_a_problem_has_what_a_bug_report_needs(setup):
    c, _, _ = setup
    r = c.get("/api/report").json()
    assert set(r) >= {"version", "install", "python", "system", "connections", "tracks", "tidy_up", "log"}
    assert r["install"] in {"snap", "Docker", "pipx", "pip", "source checkout"}
    assert isinstance(r["connections"], list) and isinstance(r["log"], list)


def test_new_folder_then_undo_and_redo(setup):
    c, music, _ = setup
    r = c.post("/api/folders/new", json={"parent": "Artist", "name": "  Live Recordings  "})
    assert r.status_code == 200 and r.json()["path"] == "Artist/Live Recordings"
    assert (music / "Artist" / "Live Recordings").is_dir()
    assert c.post("/api/folders/new", json={"parent": "", "name": "Elsewhere"}).status_code == 409  # already there
    assert c.post("/api/folders/new", json={"parent": "", "name": " . "}).status_code == 422
    assert c.post("/api/folders/new", json={"parent": "@inbox", "name": "x"}).status_code == 422
    assert c.post("/api/folders/new", json={"parent": "Nope", "name": "x"}).status_code == 404
    assert c.post("/api/folders/new", json={"parent": "../..", "name": "x"}).status_code in (400, 404, 422)
    assert c.post("/api/folders/new", json={"parent": "", "name": "a/../../b"}).json()["path"] == "a_.._.._b"  # one name, inside
    entry = next(e for e in c.get("/api/activity").json() if "Live Recordings" in e["message"])
    assert entry["can_undo"]
    assert c.post(f"/api/activity/{entry['id']}/undo").json()["undone"] == 1
    assert not (music / "Artist" / "Live Recordings").exists()
    redo = c.get("/api/activity").json()[0]
    assert c.post(f"/api/activity/{redo['id']}/undo").json()["undone"] == 1  # redo makes it again
    assert (music / "Artist" / "Live Recordings").is_dir()


def test_undoing_a_new_folder_never_removes_what_was_put_in_it(setup):
    c, music, _ = setup
    c.post("/api/folders/new", json={"parent": "", "name": "Keep"})
    (music / "Keep" / "song.flac").write_bytes(b"something")
    entry = next(e for e in c.get("/api/activity").json() if "Keep" in e["message"])
    r = c.post(f"/api/activity/{entry['id']}/undo").json()
    assert r["undone"] == 0 and r["skipped"] == 1
    assert (music / "Keep" / "song.flac").read_bytes() == b"something"
