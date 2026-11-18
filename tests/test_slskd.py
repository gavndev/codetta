"""Soulseek through slskd: ranking, the job flow and the API client, against a fake slskd."""

import json
import stat

import pytest

from codetta.core.slskd import (
    ARRIVED, DOWNLOADING, FAILED, FETCHED, NOTHING, SEARCHING, Soulseek, SoulseekStore, SlskdClient, SlskdError,
    SlskdSettings, block_key, check, clean_url, name_match, rank,
)


def f(name, size=1000, **kw):
    return {"filename": name, "size": size, **kw}


FLAC = [f("Music\\T-Pain\\Epiphany (2007)\\01 Bartender.flac", 30_000, bitDepth=16, sampleRate=44100),
        f("Music\\T-Pain\\Epiphany (2007)\\02 Church.flac", 30_000, bitDepth=16, sampleRate=44100)]
MP3 = [f("share/T-Pain - Epiphany/01 - Bartender.mp3", 9000, bitRate=320),
       f("share/T-Pain - Epiphany/02 - Church.mp3", 9000, bitRate=320)]


class FakeSlskd:
    """Answers like slskd's /api/v0, keeping just enough state."""

    def __init__(self, responses=None, key="secret"):
        self.key = key
        self.responses = responses if responses is not None else [
            {"username": "mp3guy", "files": MP3, "hasFreeUploadSlot": True, "uploadSpeed": 5_000_000, "queueLength": 0},
            {"username": "flacfan", "files": FLAC, "hasFreeUploadSlot": True, "uploadSpeed": 2_000_000, "queueLength": 1},
        ]
        self.searches = {}
        self.downloads = {}  # username -> list of transfers
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        if headers.get("X-API-Key") != self.key:
            return 401, b""
        path = url.split("/api/v0", 1)[1]
        data = json.loads(body) if body else None
        if path == "/application/version":
            return 200, b'"0.24.0"'
        if path == "/application":
            return 200, json.dumps({"server": {"isLoggedIn": True}}).encode()
        if path == "/shares":
            return 200, json.dumps({"local": [{"id": "1", "localPath": "/music", "files": 1200, "isExcluded": False}]}).encode()
        if path == "/options":
            return 200, json.dumps({"directories": {"downloads": "/app/downloads"}}).encode()
        if method == "POST" and path == "/searches":
            self.searches[data["id"]] = {"text": data["searchText"], "done": False}
            return 200, b"{}"
        if path.startswith("/searches/"):
            sid = path.split("/")[2]
            if path.endswith("/responses"):
                return 200, json.dumps(self.responses).encode()
            if method == "DELETE":
                return 204, b""
            s = self.searches[sid]
            return 200, json.dumps({"state": "Completed, TimedOut" if s["done"] else "InProgress",
                                    "isComplete": s["done"], "responseCount": len(self.responses)}).encode()
        if method == "POST" and path.startswith("/transfers/downloads/"):
            user = path.rsplit("/", 1)[1]
            self.downloads[user] = [{"id": f"t{i}", "filename": x["filename"], "size": x["size"],
                                     "state": "Queued, Remotely", "bytesTransferred": 0} for i, x in enumerate(data)]
            return 201, b""
        if method == "GET" and path.startswith("/transfers/downloads/"):
            user = path.rsplit("/", 1)[1]
            if user not in self.downloads:
                return 404, b""
            return 200, json.dumps({"username": user, "directories": [{"directory": "x", "files": self.downloads[user]}]}).encode()
        if method == "DELETE" and path.startswith("/transfers/downloads/"):
            return 204, b""
        return 404, b""

    def finish(self, user, state="Completed, Succeeded"):
        for t in self.downloads[user]:
            t["state"], t["bytesTransferred"] = state, t["size"]


@pytest.fixture
def setup(tmp_path):
    fake = FakeSlskd()
    store = SoulseekStore(tmp_path / "slskd.json")
    store.settings.url, store.settings.api_key = "http://slskd:5030", "secret"
    clock = [1000.0]
    notes = []
    sk = Soulseek(store, fake, notify=lambda t, b, a: notes.append(t), clock=lambda: clock[0])
    return fake, store, sk, clock, notes


def test_clean_url():
    assert clean_url(" slskd:5030/ ") == "http://slskd:5030"
    assert clean_url("https://x.example/api/v0") == "https://x.example"


def test_name_match_and_wildcards():
    assert name_match("T-Pain Bartender", "T-Pain Epiphany 01 Bartender.flac") == 1.0
    assert name_match("*-Pain Bartender", "T-Pain Epiphany 01 Bartender.flac") == 1.0
    assert name_match("*ain Bartender", "T-Pain - Bartender") == 1.0
    assert name_match("Daft Punk", "T-Pain Bartender") == 0.0


def test_rank_prefers_lossless_and_drops_blocklisted():
    resp = FakeSlskd().responses
    cands = rank(resp, "T-Pain Epiphany", SlskdSettings(), set())
    assert [c["username"] for c in cands] == ["flacfan", "mp3guy"]
    assert cands[0]["lossless"] and cands[0]["quality"].startswith("FLAC 16-bit/44.1 kHz")
    blocked = {block_key("flacfan", "Music\\T-Pain\\Epiphany (2007)")}
    assert [c["username"] for c in rank(resp, "T-Pain Epiphany", SlskdSettings(), blocked)] == ["mp3guy"]
    assert [c["username"] for c in rank(resp, "T-Pain Epiphany", SlskdSettings(lossless_only=True), set())] == ["flacfan"]
    assert rank(resp, "Something Else Entirely", SlskdSettings(), set()) == []


def test_rank_skips_low_bitrate_and_locked_files():
    resp = [{"username": "u", "files": [f("a/T-Pain/01 Bartender.mp3", bitRate=128)]},
            {"username": "v", "files": [f("b/T-Pain/01 Bartender.mp3", bitRate=320, isLocked=True)]}]
    cands = rank(resp, "T-Pain Bartender", SlskdSettings(), set())
    assert len(cands) == 1 and cands[0]["score"] < rank(
        [{"username": "u", "files": [f("a/T-Pain/01 Bartender.mp3", bitRate=320)]}], "T-Pain Bartender", SlskdSettings(), set()
    )[0]["score"]


def test_check_reports_shares_and_downloads(setup):
    fake, store, sk, *_ = setup
    out = check(sk.client())
    assert out["ok"] and out["version"] == "0.24.0" and out["shared_folders"] == 1 and out["shared_files"] == 1200
    assert out["downloads_dir"] == "/app/downloads" and out["logged_in"] is True
    bad = check(SlskdClient("http://slskd:5030", "wrong", fake))
    assert not bad["ok"] and "API key" in bad["error"]


def test_full_flow_search_download_arrive(setup):
    fake, store, sk, clock, notes = setup
    job = sk.search("T-Pain Epiphany")
    assert job.status == SEARCHING and fake.searches[job.id]["text"] == "T-Pain Epiphany"
    sk.tick(lambda j: None)
    assert job.status == SEARCHING  # still listening
    fake.searches[job.id]["done"] = True
    sk.tick(lambda j: None)
    assert job.status == DOWNLOADING and job.current["username"] == "flacfan"
    assert "flacfan" in fake.downloads
    fake.finish("flacfan")
    sk.tick(lambda j: None)
    assert job.status == FETCHED
    sk.tick(lambda j: "@inbox/Epiphany (2007)")
    assert job.status == ARRIVED and job.inbox_key == "@inbox/Epiphany (2007)"
    # Saved, and readable by its owner only (it holds the API key).
    mode = stat.S_IMODE(store.file.stat().st_mode)
    assert mode == 0o600
    again = SoulseekStore(store.file)
    assert again.jobs[job.id].status == ARRIVED and again.settings.api_key == "secret"


def test_failed_download_moves_to_next_candidate(setup):
    fake, store, sk, clock, notes = setup
    job = sk.search("T-Pain Epiphany")
    fake.searches[job.id]["done"] = True
    sk.tick(lambda j: None)
    fake.finish("flacfan", "Completed, Rejected")
    sk.tick(lambda j: None)
    assert job.status == DOWNLOADING and job.current["username"] == "mp3guy"
    fake.finish("mp3guy", "Completed, Errored")
    sk.tick(lambda j: None)
    assert job.status == FAILED and notes and "couldn't get" in notes[-1]


def test_stalled_queue_gives_way(setup):
    fake, store, sk, clock, notes = setup
    job = sk.search("T-Pain Epiphany")
    fake.searches[job.id]["done"] = True
    sk.tick(lambda j: None)
    clock[0] += 60
    sk.tick(lambda j: None)
    assert job.current["username"] == "flacfan" and "queue" in job.note
    clock[0] += 16 * 60
    sk.tick(lambda j: None)
    assert job.current["username"] == "mp3guy"


def test_nothing_found(setup):
    fake, store, sk, clock, notes = setup
    fake.responses = []
    job = sk.search("zzzz")
    fake.searches[job.id]["done"] = True
    sk.tick(lambda j: None)
    assert job.status == NOTHING and notes


def test_never_reaches_inbox(setup):
    fake, store, sk, clock, notes = setup
    job = sk.search("T-Pain Epiphany")
    fake.searches[job.id]["done"] = True
    sk.tick(lambda j: None)
    fake.finish("flacfan")
    sk.tick(lambda j: None)
    clock[0] += 11 * 60
    sk.tick(lambda j: None)
    assert job.status == FAILED and "/inbox" in job.note


def test_empty_query_and_unconfigured(tmp_path):
    sk = Soulseek(SoulseekStore(tmp_path / "s.json"), FakeSlskd())
    with pytest.raises(SlskdError, match="Connect"):
        sk.search("T-Pain")
    sk.store.settings.url, sk.store.settings.api_key = "http://x", "secret"
    with pytest.raises(SlskdError, match="Type what"):
        sk.search("  * ")


def test_env_overrides_saved_settings(tmp_path):
    store = SoulseekStore(tmp_path / "s.json", env_url="slskd:5030", env_key="k")
    assert store.url == "http://slskd:5030" and store.api_key == "k" and store.configured
