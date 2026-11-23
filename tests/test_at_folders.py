"""#5: a folder in the music folder whose name starts with "@" is an ordinary folder.

Only Codetta's own areas ("@inbox", "@replaced", "@deleted") are special. A real "@" folder
used to be refused ("Unknown folder: @"), which kept the whole library from showing.
NAS system folders (Synology's "@eaDir", "#recycle") are skipped like hidden ones.
"""

import shutil

import pytest

from codetta.core.library import Library, LibraryPathError, is_special
from tests.conftest import FIXTURES_DIR


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "music"
    for folder in ("@", "@Live Sets", "Artist/Album", "@eaDir/thumbs", "#recycle"):
        (root / folder).mkdir(parents=True)
    shutil.copy(FIXTURES_DIR / "sample.flac", root / "@" / "01.flac")
    shutil.copy(FIXTURES_DIR / "sample.flac", root / "@Live Sets" / "01.flac")
    shutil.copy(FIXTURES_DIR / "sample.flac", root / "Artist/Album/01.flac")
    shutil.copy(FIXTURES_DIR / "sample.flac", root / "@eaDir/thumbs/01.flac")
    return root


def test_only_codettas_own_areas_are_special():
    assert is_special("@inbox") and is_special("@inbox/x/y.flac") and is_special("@deleted/a") and is_special("@replaced")
    assert not is_special("@") and not is_special("@/a.flac") and not is_special("@Live Sets") and not is_special("Artist/@x")


def test_real_at_folders_open_like_any_other(music, tmp_path):
    lib = Library(music, deleted=tmp_path / "deleted")
    assert lib.resolve("@/01.flac") == music / "@" / "01.flac"
    assert lib.resolve("@Live Sets") == music / "@Live Sets"
    root = lib.list_folder("")
    names = [f.rsplit("/", 1)[-1] for f in root.folders]
    assert "@" in names and "@Live Sets" in names and "Artist" in names
    assert "@eaDir" not in names and "#recycle" not in names  # NAS system folders stay out of sight
    assert lib.list_folder("@").files == ["@/01.flac"]


def test_an_area_that_isnt_set_up_is_still_refused(music):
    lib = Library(music)  # no inbox folder configured
    with pytest.raises(LibraryPathError):
        lib.resolve("@inbox/a.flac")
    with pytest.raises(LibraryPathError):
        lib.resolve("@/../../etc/passwd")


def test_the_app_shows_and_indexes_them(music, tmp_path):
    import time

    from fastapi.testclient import TestClient

    from codetta.web.app import Settings, create_app
    from tests.test_musicbrainz import PASSWORD
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        root = c.get("/api/browse", params={"path": ""})
        assert root.status_code == 200, root.text
        assert {"@", "@Live Sets"} <= {f["name"] for f in root.json()["folders"]}
        assert c.get("/api/browse", params={"path": "@"}).status_code == 200
        for _ in range(100):
            if c.get("/api/index/status").json().get("ready"):
                break
            time.sleep(0.05)
        hits = {t["path"] for t in c.get("/api/search", params={"q": "sample"}).json().get("tracks", [])}
    assert "@eaDir/thumbs/01.flac" not in hits
