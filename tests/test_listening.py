"""Stars, ratings, plays, playlists, the queue and bookmarks; ListenBrainz; transcoding; covers."""

import io
import json
import subprocess

import pytest
from PIL import Image

from codetta.core.covers import CoverCache, resize
from codetta.core.listenbrainz import Scrobbler
from codetta.core.listening import Listening, moves_in
from codetta.core.transcode import Transcoder

# --- Listening store ----------------------------------------------------------------------------


def test_marks_round_trip_and_snapshot_refreshes():
    store = Listening(None)
    store.star("s", ["A/1.flac"], fps={"A/1.flac": "fp1"})
    store.rate("s", "A/1.flac", 4)
    store.played("A/1.flac", when=100, also=[("a", "a-x"), ("r", "r-y")])
    store.played("A/1.flac", when=50)
    m = store.marks()
    assert m["s"]["A/1.flac"].starred and m["s"]["A/1.flac"].rating == 4
    assert m["s"]["A/1.flac"].plays == 2 and m["s"]["A/1.flac"].last_played == 100  # the latest play wins
    assert m["a"]["a-x"].plays == 1 and m["r"]["r-y"].plays == 1
    store.star("s", ["A/1.flac"], on=False)
    store.rate("s", "A/1.flac", 0)
    m = store.marks()
    assert m["s"]["A/1.flac"].starred is None and m["s"]["A/1.flac"].rating is None


def test_everything_follows_a_moved_file():
    store = Listening(None)
    store.star("s", ["Old/1.flac"])
    pid = store.create_playlist("Mix", ["Old/1.flac", "B/2.flac"])
    store.save_queue(["B/2.flac", "Old/1.flac"], 1, 5000, "Symfonium")
    store.set_bookmark("Old/1.flac", 1234)
    store.move([("Old/1.flac", "New/1.flac")])
    assert "New/1.flac" in store.marks()["s"] and "Old/1.flac" not in store.marks()["s"]
    assert store.playlist(pid).paths == ["New/1.flac", "B/2.flac"]
    assert store.queue()[0] == ["B/2.flac", "New/1.flac"]
    assert store.bookmarks()[0][0] == "New/1.flac"


def test_relink_by_fingerprint_only_when_unique():
    store = Listening(None)
    store.star("s", ["Gone/1.flac"], fps={"Gone/1.flac": "t\x1fa\x1fal\x1f200"})
    assert store.relink({"Else/x.flac"}, {}) == 0
    assert store.relink({"Here/1.flac"}, {"t\x1fa\x1fal\x1f200": "Here/1.flac"}) == 1
    assert "Here/1.flac" in store.marks()["s"]


def test_moves_in_undo_records_including_nested_ones():
    assert moves_in({"type": "moves", "moves": [["a", "b"]]}) == [("a", "b")]
    nested = {"type": "multi", "parts": [{"type": "tags", "files": {}}, {"type": "moves", "moves": [["c", "d"], ["bad"]]}]}
    assert moves_in(nested) == [("c", "d")]
    assert moves_in(None) == [] and moves_in({"type": "tags"}) == []


def test_playlist_update_add_remove_and_delete():
    store = Listening(None)
    pid = store.create_playlist("  ", ["a", "b", "c"])
    assert store.playlist(pid).name == "Playlist"
    assert store.update_playlist(pid, name="Road", comment="trip", public=True, add=["d"], remove=[0, 2])
    pl = store.playlist(pid)
    assert (pl.name, pl.comment, pl.public, pl.paths) == ("Road", "trip", True, ["b", "d"])
    assert store.replace_playlist(pid, ["z"]) and store.playlist(pid).paths == ["z"]
    assert store.delete_playlist(pid) and store.playlist(pid) is None
    assert not store.update_playlist(999)


def test_survives_a_restart(tmp_path):
    db = tmp_path / "listening.sqlite3"
    Listening(db).star("s", ["A/1.flac"])
    assert "A/1.flac" in Listening(db).marks()["s"]


# --- ListenBrainz -------------------------------------------------------------------------------


class FakeLB:
    def __init__(self, status=200):
        self.status, self.calls = status, []

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, json.loads(body) if body else None))
        if url.endswith("/validate-token"):
            return (200, b'{"valid": true, "user_name": "gav"}') if headers["Authorization"] == "Token " + "t" * 36 else (200, b'{"valid": false}')
        return self.status, b'{"status": "ok"}'


def wait_for(fn, timeout=5):
    import time
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return False


def test_listens_are_sent_with_the_token_only_while_on(tmp_path):
    fake, on = FakeLB(), {"v": False}
    s = Scrobbler(tmp_path, lambda: on["v"], post=fake, version="9.9")
    s.set_token("t" * 36)
    s.listened({"artist": "Frank Ocean", "title": "Ivy", "album": "Blond", "duration": 249}, when=1000, player="Symfonium")
    assert fake.calls == []  # connection off: nothing leaves the server
    on["v"] = True
    s.listened({"artist": "Frank Ocean", "title": "Ivy", "album": "Blond", "duration": 249, "recording_mbid": "r"}, when=1000,
               player="Symfonium")
    assert wait_for(lambda: fake.calls)
    url, headers, body = fake.calls[0]
    assert url.endswith("/submit-listens") and headers["Authorization"] == "Token " + "t" * 36
    listen = body["payload"][0]
    assert body["listen_type"] == "single" and listen["listened_at"] == 1000
    assert listen["track_metadata"]["artist_name"] == "Frank Ocean" and listen["track_metadata"]["release_name"] == "Blond"
    info = listen["track_metadata"]["additional_info"]
    assert info["media_player"] == "Symfonium" and info["duration_ms"] == 249000 and info["recording_mbid"] == "r"
    assert s.validate() == "gav"
    assert (tmp_path / "listenbrainz.json").stat().st_mode & 0o077 == 0


def test_failed_listens_are_kept_and_sent_later(tmp_path):
    fake = FakeLB(status=503)
    s = Scrobbler(tmp_path, lambda: True, post=fake)
    s.set_token("t" * 36)
    s.listened({"artist": "A", "title": "One"}, when=1)
    assert wait_for(lambda: s.pending() == 1)
    fake.status = 200
    s.listened({"artist": "A", "title": "Two"}, when=2)
    assert wait_for(lambda: s.pending() == 0)
    assert any(c[2] and c[2]["listen_type"] == "import" and c[2]["payload"][0]["track_metadata"]["track_name"] == "One"
               for c in fake.calls)


def test_the_env_token_is_locked(tmp_path):
    s = Scrobbler(tmp_path, lambda: True, env_token="e" * 36, post=FakeLB())
    s.set_token("other")
    assert s.token == "e" * 36 and s.locked


# --- Transcoding --------------------------------------------------------------------------------


def transcoder(encoders=("aac", "libmp3lame", "libopus")):
    t = Transcoder("/usr/bin/ffmpeg")
    t._encoders = set(encoders)
    return t


def test_when_to_convert():
    t = transcoder()
    assert t.plan("raw", 128, "flac", 1000) is None
    assert t.plan(None, 0, "flac", 1000) is None  # nothing asked: the original
    assert t.plan("mp3", 0, "mp3", 320) is None  # already that format, no cap
    p = t.plan(None, 128, "flac", 1000)
    assert (p.fmt, p.kbps, p.content_type) == ("mp3", 128, "audio/mpeg")
    assert t.plan(None, 320, "mp3", 256) is None  # under the cap
    p = t.plan("opus", 0, "flac", 1000)
    assert (p.fmt, p.kbps) == ("opus", 128)
    assert t.plan("opus", 999, "flac", 1000).kbps == 256  # Opus tops out
    assert t.plan("flv", 96, "flac", 1000).fmt == "mp3"  # a format we can't make: decided by bitrate
    assert t.plan(None, 128, "flac", 1000, default="aac").fmt == "aac"


def test_a_missing_encoder_falls_back_or_sends_the_original():
    assert transcoder(("aac",)).plan("mp3", 128, "flac", 1000).fmt == "aac"
    assert transcoder(()).plan("mp3", 128, "flac", 1000) is None


def test_stream_runs_ffmpeg_and_always_cleans_up(tmp_path):
    calls = []

    class Proc:
        def __init__(self, args, **kw):
            calls.append(args)
            self.stdout = io.BytesIO(b"x" * 200_000)
            self.killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

    t = Transcoder("/usr/bin/ffmpeg", popen=Proc, max_jobs=1)
    t._encoders = {"libmp3lame"}
    plan = t.plan("mp3", 128, "flac", 1000)
    chunks = t.stream(tmp_path / "a.flac", plan, offset=30)
    first = next(chunks)
    assert len(first) == 64 * 1024
    args = calls[0]
    assert args[args.index("-ss") + 1] == "30.000" and args[args.index("-c:a") + 1] == "libmp3lame"
    assert args[args.index("-b:a") + 1] == "128k" and args[-1] == "pipe:1"
    assert t.stream(tmp_path / "b.flac", plan) is None  # the only slot is busy: send the original
    chunks.close()  # the app hung up
    assert t.stream(tmp_path / "b.flac", plan) is not None  # the slot came back


@pytest.mark.skipif(subprocess.run(["sh", "-c", "command -v ffmpeg"], capture_output=True).returncode != 0, reason="no ffmpeg")
def test_real_ffmpeg_converts_a_fixture():
    from tests.conftest import FIXTURES_DIR
    t = Transcoder("ffmpeg")
    fmt = next((f for f in ("mp3", "aac", "opus") if f in t.formats()), None)
    if fmt is None:
        pytest.skip("this ffmpeg has no audio encoders")
    data = b"".join(t.stream(FIXTURES_DIR / "sample.flac", t.plan(fmt, 128, "flac", 1000)))
    assert len(data) > 100


# --- Covers -------------------------------------------------------------------------------------


def jpeg(w, h):
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(out, "JPEG")
    return out.getvalue()


def test_covers_are_resized_cached_and_never_enlarged(tmp_path):
    big = jpeg(1200, 900)
    cache = CoverCache(tmp_path / "cache")
    small, resized = cache.get(big, "A/1.flac\x1f1", 150)
    assert resized and Image.open(io.BytesIO(small)).size == (150, 113)
    assert len(list((tmp_path / "cache").glob("*.jpg"))) == 1
    again, resized = cache.get(big, "A/1.flac\x1f1", 150)
    assert resized and again == small
    assert cache.get(big, "k", None) == (big, False)
    assert cache.get(big, "k", 5000) == (big, False)  # bigger than any thumbnail: the original
    tiny = jpeg(100, 100)
    assert cache.get(tiny, "t", 150) == (tiny, False)  # never enlarged


def test_garbage_and_bombs_are_left_alone():
    assert resize(b"not an image", 100) is None
    out = io.BytesIO()
    Image.new("1", (9000, 9000)).save(out, "PNG")  # 81 MP: over the decode limit
    assert resize(out.getvalue(), 100) is None


def test_the_cache_stays_within_its_budget(tmp_path):
    cache = CoverCache(tmp_path / "cache", max_bytes=1)
    for i in range(3):
        cache.get(jpeg(800, 800), f"k{i}", 200)
    cache.prune()
    assert len(list((tmp_path / "cache").glob("*.jpg"))) <= 1
