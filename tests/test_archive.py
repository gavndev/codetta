"""Zip up a folder: what goes in, what stays out, and that the archive opens everywhere."""

import io
import os
import shutil
import subprocess
import zipfile

import pytest
from fastapi.testclient import TestClient

from codetta.core.archive import folder_files, zip_stream
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


@pytest.fixture
def music(tmp_path):
    album = tmp_path / "music" / "Sigur Rós" / "Ágætis byrjun (1999)"
    (album / "CD2").mkdir(parents=True)
    shutil.copy2(FIXTURES_DIR / "sample.flac", album / "01 - Intro.flac")
    shutil.copy2(FIXTURES_DIR / "sample.mp3", album / "CD2" / "01 - Svefn-g-englar.mp3")
    (album / "cover.jpg").write_bytes((FIXTURES_DIR / "cover.jpg").read_bytes())
    (album / ".DS_Store").write_bytes(b"junk")
    (tmp_path / "secret.txt").write_text("not in the library")
    os.symlink(tmp_path / "secret.txt", album / "sneaky.txt")
    (tmp_path / "music" / "Empty").mkdir()
    return tmp_path / "music"


@pytest.fixture
def client(music, tmp_path):
    with TestClient(create_app(Settings(music_dir=music, config_dir=tmp_path / "config", auth=False))) as c:
        yield c


def test_a_folder_downloads_as_a_zip_with_everything_in_it(client, music):
    r = client.get("/api/folders/zip", params={"path": "Sigur Rós/Ágætis byrjun (1999)"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "filename*=UTF-8''%C3%81g%C3%A6tis%20byrjun%20%281999%29.zip" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.testzip() is None
    base = "Ágætis byrjun (1999)"
    assert z.namelist() == [f"{base}/01 - Intro.flac", f"{base}/cover.jpg", f"{base}/CD2/01 - Svefn-g-englar.mp3"]
    album = music / "Sigur Rós" / base
    assert z.read(f"{base}/01 - Intro.flac") == (album / "01 - Intro.flac").read_bytes()
    assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())  # music is compressed already
    assert r.headers["x-codetta-zip-files"] == "3"


def test_links_and_hidden_files_stay_out(client):
    r = client.get("/api/folders/zip", params={"path": "Sigur Rós"})
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert not any("sneaky" in n or ".DS_Store" in n for n in names)
    assert b"not in the library" not in r.content


def test_unzip_tools_open_it(client, tmp_path):
    if not shutil.which("unzip"):
        pytest.skip("no unzip here")
    f = tmp_path / "a.zip"
    f.write_bytes(client.get("/api/folders/zip", params={"path": "Sigur Rós"}).content)
    assert subprocess.run(["unzip", "-tq", str(f)], capture_output=True).returncode == 0


@pytest.mark.parametrize(("path", "status"), [("", 422), ("Empty", 422), ("Nope", 404), ("../..", 400),
                                              ("Sigur Rós/Ágætis byrjun (1999)/01 - Intro.flac", 404)])
def test_odd_requests_are_refused(client, path, status):
    assert client.get("/api/folders/zip", params={"path": path}).status_code == status


def test_big_files_switch_to_zip64(tmp_path, monkeypatch):
    import codetta.core.archive as archive

    monkeypatch.setattr(archive, "ZIP64_LIMIT", 10)  # treat anything over 10 bytes as huge
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.bin").write_bytes(os.urandom(5000))
    data = b"".join(zip_stream(folder_files(tmp_path / "a"), chunk=1000))
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None and z.read("a/x.bin") == (tmp_path / "a" / "x.bin").read_bytes()


# --- One file, or a selection of tracks ------------------------------------------------------------

ALBUM = "Sigur Rós/Ágætis byrjun (1999)"


def test_one_track_downloads_as_it_is(client, music):
    r = client.get("/api/files/download", params={"path": f"{ALBUM}/01 - Intro.flac"})
    assert r.status_code == 200 and r.content == (music / ALBUM / "01 - Intro.flac").read_bytes()
    assert r.headers["content-disposition"].startswith("attachment;") and "01%20-%20Intro.flac" in r.headers["content-disposition"]


@pytest.mark.parametrize(("path", "status"), [(ALBUM, 404), (f"{ALBUM}/nope.flac", 404), (f"{ALBUM}/sneaky.txt", 404),
                                              ("../secret.txt", 400), ("", 422)])
def test_odd_single_downloads_are_refused(client, path, status):
    assert client.get("/api/files/download", params={"path": path}).status_code in (status, 422)


def test_selected_tracks_zip_up_with_their_lyrics(client, music):
    (music / ALBUM / "01 - Intro.lrc").write_text("[00:01.00] hi")
    r = client.post("/api/files/zip", json={"paths": [f"{ALBUM}/01 - Intro.flac", f"{ALBUM}/CD2/01 - Svefn-g-englar.mp3"]})
    d = r.json()
    assert r.status_code == 200 and d["name"] == "Ágætis byrjun (1999).zip" and d["files"] == 3
    z = zipfile.ZipFile(io.BytesIO(client.get(d["url"]).content))
    base = "Ágætis byrjun (1999)"
    assert sorted(z.namelist()) == sorted([f"{base}/01 - Intro.flac", f"{base}/01 - Intro.lrc", f"{base}/CD2/01 - Svefn-g-englar.mp3"])
    assert z.testzip() is None


def test_a_selection_across_folders_keeps_its_folders(client, music):
    (music / "Other").mkdir()
    shutil.copy2(FIXTURES_DIR / "sample.flac", music / "Other" / "x.flac")
    d = client.post("/api/files/zip", json={"paths": [f"{ALBUM}/01 - Intro.flac", "Other", f"{ALBUM}/cover.jpg"]}).json()
    names = zipfile.ZipFile(io.BytesIO(client.get(d["url"]).content)).namelist()
    assert d["name"] == "Codetta.zip"
    assert sorted(names) == sorted([f"Codetta/{ALBUM}/01 - Intro.flac", f"Codetta/{ALBUM}/cover.jpg", "Codetta/Other/x.flac"])


def test_zip_links_expire_and_cant_be_guessed(client, monkeypatch):
    import codetta.core.archive as archive

    d = client.post("/api/files/zip", json={"paths": [f"{ALBUM}/01 - Intro.flac"]}).json()
    assert client.get("/api/files/zip/not-a-real-token").status_code == 404
    monkeypatch.setattr(archive, "TOKEN_SECONDS", -1)
    d2 = client.post("/api/files/zip", json={"paths": [f"{ALBUM}/01 - Intro.flac"]}).json()
    assert client.get(d2["url"]).status_code == 404
    assert client.get(d["url"]).status_code == 200


def test_a_selection_cant_leave_the_library(client):
    assert client.post("/api/files/zip", json={"paths": ["../secret.txt"]}).status_code in (400, 422)
    assert client.post("/api/files/zip", json={"paths": ["@inbox/x.flac"]}).status_code == 422
