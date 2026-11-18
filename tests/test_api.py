"""Tests for the web API (codetta.web.app)."""

import hashlib
import shutil

import mutagen
import pytest
from fastapi.testclient import TestClient

from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


USER, PASSWORD = "tester", "correct horse battery"


def signed_in(client):
    """Create the account on first use (or sign in), as the UI does."""
    if client.get("/api/auth/status").json()["setup_required"]:
        res = client.post("/api/auth/setup", json={"username": USER, "password": PASSWORD})
    else:
        res = client.post("/api/auth/login", json={"username": USER, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return client


@pytest.fixture
def music(tmp_path):
    """A small library:

    music/
      Loose Track.mp3            (tagged)
      Artist/
        Album/
          01 - Intro.flac        (tagged)
          2 - Groove.mp3         (untagged)
          10 - Outro.m4a         (untagged)
          cover.jpg, .codetta-tmp.flac, .hidden.flac   (ignored)
        Broken/
          bad.flac               (garbage)
    """
    root = tmp_path / "music"
    album = root / "Artist" / "Album"
    album.mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.mp3", root / "Loose Track.mp3")
    shutil.copy2(FIXTURES_DIR / "sample.flac", album / "01 - Intro.flac")
    for src, name in [("sample.mp3", "2 - Groove.mp3"), ("sample.m4a", "10 - Outro.m4a")]:
        shutil.copy2(FIXTURES_DIR / src, album / name)
        mutagen.File(album / name).delete()
    (album / "cover.jpg").write_bytes(b"jpeg")
    (album / ".codetta-tmp.flac").write_bytes(b"x")
    shutil.copy2(FIXTURES_DIR / "sample.flac", album / ".hidden.flac")
    broken = root / "Artist" / "Broken"
    broken.mkdir()
    (broken / "bad.flac").write_bytes(b"not audio" * 50)
    return root


@pytest.fixture
def client(music, tmp_path):
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"))
    with TestClient(app) as c:  # "with" runs startup (installs default presets)
        yield signed_in(c)


# --- Status, fields, UI ----------------------------------------------------------------


def test_status(client, music):
    data = client.get("/api/status").json()
    assert data["music_dir"] == str(music)
    assert data["music_dir_found"] is True
    assert data["music_dir_writable"] is True


def test_fields(client):
    data = client.get("/api/fields").json()
    keys = [f["key"] for f in data["fields"]]
    assert keys[:3] == ["title", "artist", "album"]
    assert {"mood", "engineer", "releasetype"} <= set(keys)
    assert "filename_title" in data["placeholders"]


def test_ui_is_served(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "<title>Codetta</title>" in page.text
    for asset in ["/static/app.css", "/static/app.js", "/static/icon.svg", "/static/fonts/schibsted-grotesk.woff2"]:
        assert client.get(asset).status_code == 200, asset


def test_api_docs_page(client):
    assert client.get("/docs").status_code == 200


# --- Browse ---------------------------------------------------------------------------------


def test_browse_root(client):
    data = client.get("/api/browse").json()
    assert data["path"] == ""
    assert data["breadcrumbs"] == [{"name": "Library", "path": ""}]
    # "Artist" holds two folders (Album, Broken) and no audio files directly.
    assert data["folders"] == [{"name": "Artist", "path": "Artist", "folders": 2, "tracks": 0}]
    assert [t["name"] for t in data["tracks"]] == ["Loose Track.mp3"]
    assert data["tracks"][0]["tags"]["title"] == ["Test Track"]


def test_browse_album_lists_audio_in_natural_order(client):
    data = client.get("/api/browse", params={"path": "Artist/Album"}).json()
    assert data["name"] == "Album"
    assert [c["name"] for c in data["breadcrumbs"]] == ["Library", "Artist", "Album"]
    assert [t["name"] for t in data["tracks"]] == ["01 - Intro.flac", "2 - Groove.mp3", "10 - Outro.m4a"]
    assert data["tracks"][0]["path"] == "Artist/Album/01 - Intro.flac"
    assert data["tracks"][0]["format"] == "flac"
    assert data["tracks"][1]["tags"] == {}


@pytest.mark.parametrize("path", ["/Artist/Album/", "Artist//Album", "Artist/./Album"])
def test_browse_tolerates_harmless_variations(client, path):
    data = client.get("/api/browse", params={"path": path}).json()
    assert data["path"] == "Artist/Album"


def test_unreadable_file_is_listed_with_an_error(client):
    data = client.get("/api/browse", params={"path": "Artist/Broken"}).json()
    [track] = data["tracks"]
    assert track["name"] == "bad.flac"
    assert track["error"]
    assert track["format"] is None


@pytest.mark.parametrize("path", ["..", "../..", "Artist/../..", "Artist/../../etc", "a\\b", "x\x00y"])
def test_browse_rejects_escaping_paths(client, path):
    assert client.get("/api/browse", params={"path": path}).status_code == 400


def test_browse_missing_folder(client):
    assert client.get("/api/browse", params={"path": "Nope"}).status_code == 404


def test_missing_music_folder_explains_itself(tmp_path):
    app = create_app(Settings(music_dir=tmp_path / "nowhere", config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        signed_in(c)
        assert c.get("/api/status").json()["music_dir_found"] is False
        res = c.get("/api/browse")
        assert res.status_code == 503
        assert "CODETTA_MUSIC_DIR" in res.json()["detail"]


# --- Track read & update ------------------------------------------------------------------------


def test_get_track(client):
    data = client.get("/api/track", params={"path": "Artist/Album/01 - Intro.flac"}).json()
    assert data["tags"]["artist"] == ["Coda Tester"]
    assert data["duration"] == pytest.approx(1.0, abs=0.1)


def test_get_track_errors(client):
    assert client.get("/api/track", params={"path": "../secret.flac"}).status_code == 400
    assert client.get("/api/track", params={"path": "missing.flac"}).status_code == 404
    assert client.get("/api/track", params={"path": "Artist/Broken/bad.flac"}).status_code == 422


def test_update_single_track(client, music):
    res = client.patch("/api/tracks", json={
        "paths": ["Loose Track.mp3"],
        "changes": {"title": "Night Drive", "artist": ["A", "B"], "genre": None},
    })
    assert res.status_code == 200
    [result] = res.json()
    assert result["ok"] is True
    assert result["track"]["tags"]["title"] == ["Night Drive"]
    assert result["track"]["tags"]["artist"] == ["A", "B"]
    assert "genre" not in result["track"]["tags"]
    # Really written to disk:
    assert mutagen.File(music / "Loose Track.mp3", easy=True)["title"] == ["Night Drive"]


def test_batch_update(client):
    paths = ["Artist/Album/2 - Groove.mp3", "Artist/Album/10 - Outro.m4a"]
    res = client.patch("/api/tracks", json={"paths": paths, "changes": {"album": "Midnight", "mood": "Chill"}})
    results = res.json()
    assert [r["ok"] for r in results] == [True, True]
    assert all(r["track"]["tags"]["album"] == ["Midnight"] for r in results)
    assert all(r["track"]["tags"]["mood"] == ["Chill"] for r in results)


def test_batch_update_reports_per_file_failures(client, music):
    before = sha256(music / "Loose Track.mp3")
    res = client.patch("/api/tracks", json={
        "paths": ["Artist/Album/01 - Intro.flac", "Loose Track.mp3", "../escape.mp3", "gone.flac"],
        "changes": {"my_custom_tag": "x"},  # fine on FLAC, not allowed on MP3
    })
    results = res.json()
    assert [r["ok"] for r in results] == [True, False, False, False]
    assert "Invalid tag" in results[1]["error"]
    assert sha256(music / "Loose Track.mp3") == before


def test_update_requires_paths(client):
    assert client.patch("/api/tracks", json={"paths": [], "changes": {}}).status_code == 422


# --- Presets ------------------------------------------------------------------------------------


def test_default_presets_installed_on_startup(client):
    names = [lo["name"] for lo in client.get("/api/presets").json()]
    assert names == ["Album Folder", "Full Credits", "Single"]


def test_create_edit_rename_delete_preset(client):
    res = client.post("/api/presets", json={"name": "Lo-Fi", "tags": {"genre": "Lo-Fi", "mood": ["Chill", "Calm"]}})
    assert res.status_code == 200
    assert res.json()["tags"] == {"genre": ["Lo-Fi"], "mood": ["Chill", "Calm"]}

    # Creating it again is refused (avoids silently overwriting).
    assert client.post("/api/presets", json={"name": "lo-fi", "tags": {}}).status_code == 409

    # Editing in place is fine.
    res = client.post("/api/presets", json={"name": "Lo-Fi", "tags": {"genre": "Jazz"}, "previous_name": "Lo-Fi"})
    assert res.json()["tags"] == {"genre": ["Jazz"]}

    # Renaming.
    res = client.post("/api/presets", json={"name": "Jazz Vibes", "tags": {"genre": "Jazz"}, "previous_name": "Lo-Fi"})
    assert res.status_code == 200
    names = [lo["name"] for lo in client.get("/api/presets").json()]
    assert "Jazz Vibes" in names and "Lo-Fi" not in names

    # Renaming onto an existing preset is refused.
    res = client.post("/api/presets", json={"name": "Single", "tags": {}, "previous_name": "Jazz Vibes"})
    assert res.status_code == 409

    assert client.delete("/api/presets/Jazz Vibes").status_code == 204
    assert client.delete("/api/presets/Jazz Vibes").status_code == 404


def test_invalid_preset_is_rejected(client):
    res = client.post("/api/presets", json={"name": "Bad", "tags": {"title": "{nope}"}})
    assert res.status_code == 422
    assert "unknown placeholder" in res.json()["detail"]
    assert client.post("/api/presets", json={"name": "   ", "tags": {}}).status_code == 422


def test_apply_preview_does_not_write(client, music):
    path = music / "Artist" / "Album" / "2 - Groove.mp3"
    before = sha256(path)
    res = client.post("/api/presets/apply", json={"name": "Album Folder", "folder": "Artist/Album"})
    results = res.json()
    assert [r["path"] for r in results] == [
        "Artist/Album/01 - Intro.flac", "Artist/Album/2 - Groove.mp3", "Artist/Album/10 - Outro.m4a",
    ]
    groove = results[1]
    assert groove["applied"]["title"] == ["Groove"]
    assert groove["applied"]["tracknumber"] == ["2/3"]
    assert groove["applied"]["album"] == ["Album"]
    assert "title" in results[0]["kept_existing"]  # fill mode keeps "Test Track"
    assert sha256(path) == before


def test_apply_to_folder_writes(client):
    res = client.post("/api/presets/apply", json={"name": "Album Folder", "folder": "Artist/Album", "dry_run": False})
    assert all(r["error"] is None for r in res.json())
    tracks = client.get("/api/browse", params={"path": "Artist/Album"}).json()["tracks"]
    assert [t["tags"]["tracknumber"] for t in tracks] == [["3/12"], ["2/3"], ["3/3"]]  # first kept its own
    assert [t["tags"]["title"] for t in tracks] == [["Test Track"], ["Groove"], ["Outro"]]


def test_apply_overwrite_mode(client):
    client.post("/api/presets/apply", json={
        "name": "Album Folder", "folder": "Artist/Album", "mode": "overwrite", "dry_run": False,
    })
    tracks = client.get("/api/browse", params={"path": "Artist/Album"}).json()["tracks"]
    assert tracks[0]["tags"]["title"] == ["Intro"]
    assert tracks[0]["tags"]["tracknumber"] == ["1/3"]


def test_apply_to_selected_files(client):
    res = client.post("/api/presets/apply", json={
        "name": "Single", "paths": ["Artist/Album/10 - Outro.m4a"], "dry_run": False,
    })
    [result] = res.json()
    assert result["applied"]["releasetype"] == ["single"]
    track = client.get("/api/track", params={"path": "Artist/Album/10 - Outro.m4a"}).json()
    assert track["tags"]["album"] == ["Outro"]


def test_apply_recursive(client):
    res = client.post("/api/presets/apply", json={"name": "Album Folder", "folder": "Artist", "recursive": True})
    results = res.json()
    paths = [r["path"] for r in results]
    assert "Artist/Album/2 - Groove.mp3" in paths
    assert any(r["error"] for r in results if r["path"] == "Artist/Broken/bad.flac")


def test_apply_errors(client):
    assert client.post("/api/presets/apply", json={"name": "Nope", "folder": ""}).status_code == 404
    assert client.post("/api/presets/apply", json={"name": "Single"}).status_code == 400
    assert client.post("/api/presets/apply", json={"name": "Single", "folder": "../.."}).status_code == 400
    assert client.post("/api/presets/apply", json={"name": "Single", "paths": ["../x.mp3"]}).status_code == 400
    assert client.post("/api/presets/apply", json={"name": "Single", "folder": "Nope"}).status_code == 404


# --- Album art & activity ---------------------------------------------------------------------

JPEG = (FIXTURES_DIR / "cover.jpg").read_bytes()
PNG = (FIXTURES_DIR / "cover.png").read_bytes()


def test_art_lifecycle(client):
    path = "Artist/Album/01 - Intro.flac"
    assert client.get("/api/art", params={"path": path}).status_code == 404
    mtime_before = client.get("/api/track", params={"path": path}).json()["mtime"]

    res = client.put("/api/art", params={"path": path}, content=JPEG, headers={"Content-Type": "image/jpeg"})
    [result] = res.json()
    assert result["ok"] is True
    assert result["track"]["mtime"] != mtime_before  # lets the UI refresh its cached image

    art = client.get("/api/art", params={"path": path})
    assert art.status_code == 200
    assert art.headers["content-type"] == "image/jpeg"
    assert art.content == JPEG

    [result] = client.delete("/api/art", params={"path": path}).json()
    assert result["ok"] is True
    assert client.get("/api/art", params={"path": path}).status_code == 404


def test_art_batch_with_failures(client):
    paths = ["Artist/Album/2 - Groove.mp3", "Artist/Album/10 - Outro.m4a", "Artist/Broken/bad.flac", "../x.flac"]
    res = client.put("/api/art", params={"path": paths}, content=PNG, headers={"Content-Type": "image/png"})
    assert [r["ok"] for r in res.json()] == [True, True, False, False]
    for p in paths[:2]:
        assert client.get("/api/art", params={"path": p}).content == PNG


def test_art_rejects_non_images(client):
    res = client.put("/api/art", params={"path": "Loose Track.mp3"}, content=b"GIF89a", headers={"Content-Type": "image/gif"})
    [result] = res.json()
    assert result["ok"] is False
    assert "JPEG or PNG" in result["error"]


def test_art_path_safety(client):
    assert client.get("/api/art", params={"path": "../../etc/passwd"}).status_code == 400


def test_activity_records_changes(client):
    assert client.get("/api/activity").json() == []
    client.patch("/api/tracks", json={"paths": ["Loose Track.mp3"], "changes": {"title": "Night Drive"}})
    client.put("/api/art", params={"path": "Loose Track.mp3"}, content=JPEG, headers={"Content-Type": "image/jpeg"})
    client.post("/api/presets/apply", json={"name": "Single", "paths": ["Artist/Album/2 - Groove.mp3"], "dry_run": False})
    client.post("/api/presets/apply", json={"name": "Single", "paths": ["Artist/Album/2 - Groove.mp3"]})  # preview: not logged

    log = client.get("/api/activity").json()
    assert [e["kind"] for e in log] == ["preset", "art", "edit"]
    edit = log[2]
    assert edit["ok"] is True
    assert edit["message"] == "Edited title on Loose Track.mp3"
    assert edit["changes"] == [{"key": "title", "old": "Test Track", "new": "Night Drive"}]
    assert log[1]["message"].startswith("Added album art on Loose Track.mp3 (64×48 JPEG")
    assert "Single" in log[0]["message"]

    newer = client.get("/api/activity", params={"after_id": edit["id"]}).json()
    assert [e["kind"] for e in newer] == ["preset", "art"]


def test_activity_records_failures(client):
    client.patch("/api/tracks", json={"paths": ["Loose Track.mp3"], "changes": {"made_up": "x"}})
    [entry] = client.get("/api/activity").json()
    assert entry["ok"] is False
    assert entry["errors"][0]["path"] == "Loose Track.mp3"


def test_activity_persists_in_config_dir(music, tmp_path):
    config = tmp_path / "config"
    settings = Settings(music_dir=music, config_dir=config)
    with TestClient(create_app(settings)) as c:
        signed_in(c)
        c.patch("/api/tracks", json={"paths": ["Loose Track.mp3"], "changes": {"genre": "Jazz"}})
    with TestClient(create_app(settings)) as c:
        signed_in(c)
        assert c.get("/api/activity").json()[0]["message"] == "Edited genre on Loose Track.mp3"


def test_folder_counts_ignore_hidden_and_non_audio(client):
    data = client.get("/api/browse", params={"path": "Artist"}).json()
    album = next(f for f in data["folders"] if f["name"] == "Album")
    # 3 audio files; cover.jpg, .codetta-tmp.flac and .hidden.flac are not counted
    assert (album["folders"], album["tracks"]) == (0, 3)


def test_browse_reports_skipped_names_and_survives_them(client, music):
    import os
    shutil.copy2(FIXTURES_DIR / "sample.flac", music / os.fsdecode(b"bad \xff name.flac"))
    data = client.get("/api/browse").json()
    assert data["skipped"] == 1
    assert [t["name"] for t in data["tracks"]] == ["Loose Track.mp3"]


def test_tracks_report_art_fingerprints(client):
    paths = ["Artist/Album/01 - Intro.flac", "Artist/Album/2 - Groove.mp3"]
    client.put("/api/art", params={"path": paths}, content=JPEG, headers={"Content-Type": "image/jpeg"})
    tracks = {t["name"]: t for t in client.get("/api/browse", params={"path": "Artist/Album"}).json()["tracks"]}
    a, b = tracks["01 - Intro.flac"]["art"], tracks["2 - Groove.mp3"]["art"]
    assert a == b and (a["width"], a["height"]) == (64, 48)  # same cover -> same fingerprint
    assert tracks["10 - Outro.m4a"]["art"] is None


def test_player_lyrics_from_tag_or_lrc_file(tmp_path):
    import shutil
    from codetta.core.engine import MetadataEngine
    from codetta.web.app import Settings, create_app
    from fastapi.testclient import TestClient
    from tests.conftest import FIXTURES_DIR
    music = tmp_path / "music"; music.mkdir()
    for n in ("a.flac", "b.flac", "c.flac"):
        shutil.copy2(FIXTURES_DIR / "sample.flac", music / n)
    MetadataEngine().update_tags(music / "a.flac", {"lyrics": "[00:01.00] Hello\n[00:05.50] World"})
    (music / "b.lrc").write_text("[00:02.00] From a file\n[00:04.00] Second line", "utf-8")
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "cfg", auth=False))) as c:
        a = c.get("/api/lyrics", params={"path": "a.flac"}).json()
        assert a["source"] == "tag" and a["synced"] and "Hello" in a["lyrics"]
        b = c.get("/api/lyrics", params={"path": "b.flac"}).json()
        assert b["source"] == "file" and b["synced"] and "From a file" in b["lyrics"]
        assert c.get("/api/lyrics", params={"path": "c.flac"}).json() == {"lyrics": "", "source": None, "synced": False}
        assert c.get("/api/lyrics", params={"path": "../etc/passwd"}).status_code == 400
