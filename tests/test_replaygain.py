"""ReplayGain: loudness measured the EBU R128 way, written where players read it, undoable."""

import math
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from codetta.core import loudness
from codetta.core.engine import MetadataEngine
from codetta.web.app import Settings, create_app

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg isn't installed here")


def tone(path, volume, seconds=6, codec=None):
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=440:d={seconds}", "-af", f"volume={volume}", "-ac", "2"]
    if codec:
        cmd += ["-c:a", codec]
    subprocess.run([*cmd, str(path)], check=True)
    return path


def test_gating_follows_ebu_r128():
    assert loudness.integrated([-20.0] * 10) == pytest.approx(-20.0)
    assert loudness.integrated([-20.0] * 10 + [-80.0] * 50) == pytest.approx(-20.0)  # silence doesn't count
    assert loudness.integrated([-20.0] * 10 + [-45.0] * 10) == pytest.approx(-20.0)  # nor very quiet parts
    assert math.isinf(loudness.integrated([-90.0] * 5))


def test_tags_follow_replaygain_2_and_opus_rules():
    m = loudness.Measured(-12.0, 0.98)
    whole = loudness.Measured(-11.5, 0.99)
    assert loudness.tag_changes("flac", m, whole) == {
        "replaygain_track_gain": ["-6.00 dB"], "replaygain_track_peak": ["0.980000"],
        "replaygain_album_gain": ["-6.50 dB"], "replaygain_album_peak": ["0.990000"]}
    # Opus: R128 gain relative to -23 LUFS, in 1/256 dB: (-23 - -12) * 256 = -2816
    assert loudness.tag_changes("opus", m, None) == {"r128_track_gain": ["-2816"], "r128_album_gain": None}
    # Measured on its own: old album values go (they'd describe some other grouping).
    assert loudness.tag_changes("mp3", m, None)["replaygain_album_gain"] is None


@needs_ffmpeg
def test_measurements_match_ffmpegs_own(tmp_path):
    f = tone(tmp_path / "a.flac", 0.5)
    m = loudness.Meter(FFMPEG).measure(f)
    out = subprocess.run([FFMPEG, "-nostats", "-hide_banner", "-i", str(f), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    ffmpeg_i = float(out.rsplit("I:", 1)[1].split("LUFS")[0])
    assert m.loudness == pytest.approx(ffmpeg_i, abs=0.1)
    assert 0 < m.peak < 1


@pytest.fixture
def lib(tmp_path):
    album = tmp_path / "music" / "Artist" / "Album (2020)"
    (album / "CD2").mkdir(parents=True)
    tone(album / "01 Loud.flac", 0.9)
    tone(album / "02 Quiet.mp3", 0.1)
    tone(album / "CD2" / "01 Opus.opus", 0.3, codec="libopus")
    return tmp_path / "music"


@pytest.fixture
def client(lib, tmp_path):
    with TestClient(create_app(Settings(music_dir=lib, config_dir=tmp_path / "config", auth=False))) as c:
        yield c


@needs_ffmpeg
def test_an_album_is_measured_as_one_and_written_where_players_read_it(client, lib):
    folder = "Artist/Album (2020)"
    d = client.post("/api/replaygain", json={"folder": folder}).json()
    assert d["measured"] == 3 and len(d["albums"]) == 1 and d["albums"][0]["folder"] == folder  # CD2 joins its album
    gains = {t["path"].rsplit("/", 1)[1]: float(t["gain"].split()[0]) for t in d["albums"][0]["tracks"]}
    assert gains["02 Quiet.mp3"] > gains["01 Loud.flac"] + 15  # the quiet one gets turned up
    before = MetadataEngine().load_metadata(lib / folder / "01 Loud.flac").tags
    assert "replaygain_track_gain" not in before  # the preview wrote nothing
    r = client.post("/api/replaygain", json={"folder": folder, "dry_run": False}).json()
    assert r["changed"] == 3
    e = MetadataEngine()
    flac = e.load_metadata(lib / folder / "01 Loud.flac").tags
    assert flac["replaygain_album_gain"] == [d["albums"][0]["gain"]] and flac["replaygain_track_peak"]
    mp3 = e.load_metadata(lib / folder / "02 Quiet.mp3").tags
    assert mp3["replaygain_album_gain"] == flac["replaygain_album_gain"]
    from mutagen.id3 import ID3
    assert "TXXX:REPLAYGAIN_TRACK_GAIN" in ID3(lib / folder / "02 Quiet.mp3")  # where Navidrome reads it, not RVA2
    opus = e.load_metadata(lib / folder / "CD2" / "01 Opus.opus").tags
    assert int(opus["r128_track_gain"][0]) and "replaygain_track_gain" not in opus


@needs_ffmpeg
def test_it_can_be_undone(client, lib):
    client.post("/api/replaygain", json={"folder": "Artist", "dry_run": False})
    entry = client.get("/api/activity").json()[0]
    assert entry["message"].startswith("ReplayGain: 3 tracks")
    assert client.post(f"/api/activity/{entry['id']}/undo").status_code == 200
    assert "replaygain_track_gain" not in MetadataEngine().load_metadata(lib / "Artist/Album (2020)/01 Loud.flac").tags


@needs_ffmpeg
def test_track_mode_leaves_out_album_values(client, lib):
    r = client.post("/api/replaygain", json={"paths": ["Artist/Album (2020)/01 Loud.flac"], "mode": "track", "dry_run": False}).json()
    tags = MetadataEngine().load_metadata(lib / "Artist/Album (2020)/01 Loud.flac").tags
    assert r["changed"] == 1 and "replaygain_track_gain" in tags and "replaygain_album_gain" not in tags


def test_without_ffmpeg_it_says_so(lib, tmp_path):
    with TestClient(create_app(Settings(music_dir=lib, config_dir=tmp_path / "c2", auth=False, ffmpeg="/nope/ffmpeg"))) as c:
        assert c.get("/api/status").json()["replaygain"] is False
        r = c.post("/api/replaygain", json={"folder": "Artist"})
        assert r.status_code == 409 and "ffmpeg" in r.json()["detail"]


def test_paths_stay_in_the_library(client):
    assert client.post("/api/replaygain", json={"paths": ["../x.flac"]}).status_code in (400, 409, 422)
