"""Tests for profile pictures."""

import pytest
from fastapi.testclient import TestClient

from codetta.core.avatar import AvatarError, AvatarStore, detect_image_type
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR

JPEG = (FIXTURES_DIR / "cover.jpg").read_bytes()
PNG = (FIXTURES_DIR / "cover.png").read_bytes()
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24  # minimal WebP header


@pytest.mark.parametrize(("data", "mime"), [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp"),
                                            (b"GIF89a....", None), (b"<svg/>", None), (b"", None)])
def test_detect_image_type(data, mime):
    assert detect_image_type(data) == mime


def test_store_save_replace_delete(tmp_path):
    store = AvatarStore(tmp_path / "avatars")
    assert store.get("gavin") is None and store.version("gavin") is None
    store.save("gavin", JPEG)
    assert store.get("gavin") == (JPEG, "image/jpeg")
    store.save("Gavin", WEBP)  # usernames aren't case-sensitive
    assert store.get("gavin") == (WEBP, "image/webp")
    assert len(list((tmp_path / "avatars").iterdir())) == 1  # old JPEG replaced, not left behind
    assert store.delete("gavin") and store.get("gavin") is None


@pytest.mark.parametrize("name", ["ガビン", "गेविन", "🎧 dj"])
def test_store_any_username(tmp_path, name):
    store = AvatarStore(tmp_path)
    store.save(name, PNG)
    assert store.get(name)[0] == PNG


@pytest.mark.parametrize("data", [b"", b"GIF89a....", b"\xff\xd8\xff" + b"\x00" * (3 * 1024 * 1024)])
def test_store_rejects_bad_uploads(tmp_path, data):
    with pytest.raises(AvatarError):
        AvatarStore(tmp_path).save("gavin", data)


@pytest.fixture
def client(tmp_path):
    (tmp_path / "music").mkdir()
    with TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config"))) as c:
        c.post("/api/auth/setup", json={"username": "gavin", "password": "correct horse 1"})
        yield c


def test_avatar_api_lifecycle(client):
    assert client.get("/api/auth/status").json()["avatar"] is None
    assert client.get("/api/account/avatar").status_code == 404

    res = client.put("/api/account/avatar", content=WEBP, headers={"Content-Type": "image/webp"})
    assert res.status_code == 200
    version = res.json()["avatar"]
    assert client.get("/api/auth/status").json()["avatar"] == version

    pic = client.get("/api/account/avatar", params={"v": version})
    assert pic.content == WEBP and pic.headers["content-type"] == "image/webp"
    assert "immutable" in pic.headers["cache-control"]

    assert client.delete("/api/account/avatar").json() == {"avatar": None}
    assert client.get("/api/account/avatar").status_code == 404


def test_avatar_rejects_non_images(client):
    res = client.put("/api/account/avatar", content=b"GIF89a....", headers={"Content-Type": "image/gif"})
    assert res.status_code == 422
    assert "JPEG, PNG or WebP" in res.json()["detail"]


def test_avatar_is_private(client):
    client.put("/api/account/avatar", content=PNG, headers={"Content-Type": "image/png"})
    client.cookies.clear()
    assert client.get("/api/account/avatar").status_code == 401
    assert client.put("/api/account/avatar", content=PNG).status_code == 401
    assert client.get("/api/auth/status").json()["avatar"] is None  # not revealed before sign-in
