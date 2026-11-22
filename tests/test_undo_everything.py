"""Every action that changes files, then Undo from Activity: each file must be exactly as it was.

One fresh album per action (several formats), set up so every action really changes something:
a step that changes nothing fails too, so this test can't pass by doing nothing. Adding a new
action that changes files? Add it to STEPS.
"""

import hashlib
import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR
from tests.test_musicbrainz import PASSWORD, png
from tests.test_tagtools import garble

FORMATS = ["sample.flac", "sample.mp3", "sample.m4a", "sample.ogg", "sample.opus", "sample.wv"]
F = "Some Artist/Some Album"
FFMPEG = shutil.which("ffmpeg")


def _files(c) -> list[str]:
    return sorted(c.files)


def _art_query(c) -> str:
    return "&".join(f"path={f}" for f in _files(c))


def _put_art(c):
    return c.put(f"/api/art?{_art_query(c)}", content=png(), headers={"Content-Type": "image/png"})


# (name, how to set the stage first or None, the request: method, url or a function of the client, body)
STEPS = [
    ("edit tags", None, ("PATCH", "/api/tracks", lambda c: {"paths": _files(c), "changes": {
        "title": "X", "genre": ["Pop", "Jazz"], "comment": None, "date": "2001"}})),
    ("add a cover", None, ("ART", None, None)),
    ("remove the cover", _put_art, ("DELETE", lambda c: f"/api/art?{_art_query(c)}", None)),
    ("find & replace", None, ("POST", "/api/tracks/replace", {"folder": F, "find": "song", "replace": "tune", "dry_run": False})),
    ("change case", None, ("POST", "/api/actions/tagtools.case/run",
                           {"folder": F, "options": {"field": "all", "style": "upper"}, "dry_run": False})),
    ("fix garbled text", None, ("POST", "/api/actions/tagtools.fix-garbled/run",
                                {"folder": F, "options": {"source": "utf8"}, "dry_run": False})),
    ("split values", None, ("POST", "/api/actions/tagtools.split/run",
                            {"folder": F, "options": {"field": "genre", "separator": ";"}, "dry_run": False})),
    ("join values", None, ("POST", "/api/actions/tagtools.join/run", {"folder": F, "dry_run": False})),
    ("remove duplicates", None, ("POST", "/api/actions/tagtools.dedupe/run", {"folder": F, "dry_run": False})),
    ("keep only essentials", None, ("POST", "/api/actions/tagtools.keep-only/run", {"folder": F, "dry_run": False})),
    ("tidy: feat.", None, ("POST", "/api/actions/tidy.feat/run", {"folder": F, "dry_run": False})),
    ("tidy: title case", None, ("POST", "/api/actions/tidy.title-case/run", {"folder": F, "dry_run": False})),
    ("tidy: clean titles", None, ("POST", "/api/actions/tidy.clean-titles/run", {"folder": F, "dry_run": False})),
    ("tidy: trim", None, ("POST", "/api/actions/tidy.trim/run", {"folder": F, "dry_run": False})),
    ("tags from file names", None, ("POST", "/api/tags/from-names", {
        "folder": F, "pattern": "{tracknumber} - {title}", "keep_existing": False, "underscores": True, "dry_run": False})),
    ("paste a tracklist", None, ("POST", "/api/tags/tracklist", {
        "folder": F, "text": "\n".join(f"{i}. Pasted {i}" for i in range(1, 7)), "dry_run": False})),
    ("save covers as files", _put_art, ("POST", "/api/covers/export", {"folder": F, "dry_run": False})),
    ("replaygain", None, ("POST", "/api/replaygain", {"folder": F, "dry_run": False})),
    ("rename a file", None, ("POST", "/api/files/rename", lambda c: {"path": _files(c)[0], "name": "renamed.flac"})),
    ("rename the folder", None, ("POST", "/api/folders/rename", {"path": F, "name": "Renamed Album"})),
    ("move files", None, ("POST", "/api/files/move", lambda c: {"paths": _files(c)[:2], "to": "Some Artist"})),
    ("delete files", None, ("POST", "/api/files/delete", lambda c: {"paths": _files(c)[:2]})),
    ("organize", None, ("POST", "/api/organize/apply", {"folder": F, "pattern": "{albumartist}/{album}/{tracknumber} {title}"})),
] + [(f"preset {name}", None, ("POST", "/api/presets/apply", {"name": name, "folder": F, "mode": "overwrite", "dry_run": False}))
     for name in ("Album Folder", "Clean", "Explicit", "Full Credits", "Single")]


@pytest.fixture
def client(tmp_path):
    music = tmp_path / "music"
    album = music / F
    album.mkdir(parents=True)
    engine = MetadataEngine()
    files = []
    for n, src in enumerate(FORMATS, 1):
        dest = album / f"0{n} - track_name {n}.{src.split('.')[1]}"
        shutil.copy2(FIXTURES_DIR / src, dest)
        engine.update_tags(dest, {
            "title": f"  song number {n} ft. Guest (Official Audio)  ", "tracknumber": str(n),
            "album": "Some Album", "albumartist": "Some Artist", "artist": garble("Beyoncé", "utf-8"),
            "genre": ["Rock; Pop", "Rock; Pop"], "comment": "keep me", "composer": ["A", "B"]})
        files.append(f"{F}/{dest.name}")
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config", ffmpeg=FFMPEG),
                     fetch_art=lambda url: png())
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        for plugin in c.get("/api/plugins").json()["plugins"]:
            c.put(f"/api/plugins/{plugin['id']}", json={"enabled": True})
        c.music, c.files, c.engine = music, files, engine
        yield c


def snapshot(c) -> dict:
    """Every file under the music folder: its tags and cover (audio), or its bytes (anything else)."""
    out = {}
    for p in sorted(c.music.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(c.music).as_posix()
        try:
            tags = c.engine.load_metadata(p).tags
            art = c.engine.read_artwork(p)
            out[rel] = (sorted((k, tuple(v)) for k, v in tags.items()), hashlib.sha256(art.data).hexdigest() if art else None)
        except Exception:  # noqa: BLE001 - not audio: compare the bytes
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.mark.parametrize(("name", "stage", "request_"), STEPS, ids=[s[0] for s in STEPS])
def test_undo_puts_every_file_back(client, name, stage, request_):
    if name == "replaygain" and not FFMPEG:
        pytest.skip("ReplayGain needs ffmpeg")
    if stage:
        stage(client)
    before = snapshot(client)
    method, url, body = request_
    if method == "ART":
        res = _put_art(client)
    else:
        url = url(client) if callable(url) else url
        res = client.request(method, url, json=body(client) if callable(body) else body)
    assert res.status_code < 400, res.text
    assert snapshot(client) != before, f"{name} changed nothing: the test data needs updating"
    entry = client.get("/api/activity", params={"limit": 1}).json()[0]
    assert entry["can_undo"], f"{name} changed files but can't be undone"
    assert client.post(f"/api/activity/{entry['id']}/undo").status_code == 200
    assert snapshot(client) == before
