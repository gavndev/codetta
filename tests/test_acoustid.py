"""Identify by sound (AcoustID), with a fake fpcalc and a fake AcoustID: no network, no binary needed."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.core.acoustid import (
    BATCH,
    AcoustID,
    AcoustIDAccount,
    Fingerprint,
    Fingerprinter,
    FingerprintError,
    rank_releases,
)
from codetta.core.engine import MetadataEngine
from codetta.core.musicbrainz import FileInfo, pair_files, release_tracks
from codetta.core.providers import ProviderError
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR
from tests.test_musicbrainz import ALBUM, FOLDER, PASSWORD, REL, FakeMB

REC = {n: f"aaaaaaaa-0000-4000-8000-{n:012d}" for n in (1, 2, 3)}  # ALBUM's recordings
COMPILATION = "99999999-9999-4999-8999-999999999999"


def fake_fpcalc(argv):
    assert argv[0].endswith("fpcalc") and argv[1:4] == ["-json", "-length", "120"]
    name = argv[-1].rsplit("/", 1)[-1]
    if name.startswith("broken"):
        raise FingerprintError("Couldn't decode this file")
    return json.dumps({"duration": 1.0, "fingerprint": f"FP-{name}"})


def result(rec_ids, score=0.95, releases=(REL,)):
    return [{"id": "acoustid-x", "score": score, "recordings": [
        {"id": r, "title": "Heard", "duration": 1, "artists": [{"name": "Coda Tester"}],
         "releases": [{"id": x} for x in releases]} for r in rec_ids]}]


class FakeLink:
    """AcoustID's linking API: request_link gives a pending key; ``states`` says what link_status answers."""

    def __init__(self):
        self.calls, self.states = [], {"PASTED-KEY-1": "approved"}

    def __call__(self, url, form):
        self.calls.append((url, form))
        assert form["client"] and form["format"] == "json"
        if url.endswith("/request_link"):
            self.states.setdefault("LINKED-KEY-1", "pending")
            # The shape api.acoustid.org really answers with (2026-11-27): "link" inside "user".
            return {"status": "ok", "user": {"apikey": "LINKED-KEY-1", "link": {
                "code": "WT14-9E3S", "url": "https://acoustid.org/link?code=WT14-9E3S",
                "expires": "2999-12-01T12:15:00+00:00"}}}
        assert url.endswith("/link_status")
        return {"status": "ok", "key": {"state": self.states.get(form["user"], "unknown")}}


class FakeAcoustID:
    """Answers by the file name inside the fake fingerprint."""

    def __init__(self, by_name, error=None):
        self.by_name, self.error, self.forms = by_name, error, []

    def __call__(self, form):
        self.forms.append(form)
        if self.error:
            raise self.error
        if form.get("batch") != "1":  # like the real service: without batch=1 only the first is answered
            first = form.get("fingerprint.0", "").removeprefix("FP-")
            return {"status": "ok", "results": self.by_name.get(first, [])}
        out = []
        for key, code in form.items():
            if key.startswith("fingerprint."):
                out.append({"index": key.split(".")[1], "results": self.by_name.get(code.removeprefix("FP-"), [])})
        return {"status": "ok", "fingerprints": out}


# --- Unit ---------------------------------------------------------------------------------


def test_fingerprints_are_cached_per_file_version(tmp_path):
    f = tmp_path / "a.flac"
    f.write_bytes(b"x")
    calls = []
    fp = Fingerprinter("fpcalc", run=lambda argv: (calls.append(argv), fake_fpcalc(argv))[1])
    assert fp.one(f) == Fingerprint(1.0, "FP-a.flac")
    fp.one(f)
    assert len(calls) == 1
    f.write_bytes(b"xy")  # changed: fingerprint again
    fp.one(f)
    assert len(calls) == 2


def test_fingerprint_errors_are_per_file(tmp_path):
    for name in ("ok.flac", "broken.flac"):
        (tmp_path / name).write_bytes(b"x")
    res = Fingerprinter("fpcalc", run=fake_fpcalc).many([tmp_path / "ok.flac", tmp_path / "broken.flac"])
    assert isinstance(res[0], Fingerprint) and isinstance(res[1], FingerprintError)


def test_missing_fpcalc_is_explained(tmp_path):
    (tmp_path / "a.flac").write_bytes(b"x")
    with pytest.raises(FingerprintError, match="isn't installed"):
        Fingerprinter(None).one(tmp_path / "a.flac")


def test_silence_and_garbage_are_rejected(tmp_path):
    (tmp_path / "a.flac").write_bytes(b"x")
    for out in ('{"duration": 1, "fingerprint": ""}', "not json", '{"duration": 0, "fingerprint": "x"}'):
        with pytest.raises(FingerprintError):
            Fingerprinter("fpcalc", run=lambda argv, out=out: out).one(tmp_path / "a.flac")


def test_lookup_batches_and_rate_limits():
    now, slept = [0.0], []
    svc = FakeAcoustID({f"{i}": result([REC[1]]) for i in range(BATCH + 5)})
    ac = AcoustID(svc, key="KEY", clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    found = ac.lookup([Fingerprint(181.4, f"FP-{i}") for i in range(BATCH + 5)])
    assert len(found) == BATCH + 5 and all(r and r[0].id == REC[1] for r in found)
    assert len(svc.forms) == 2 and slept  # two requests, a pause between them
    first = svc.forms[0]
    assert first["client"] == "KEY" and first["duration.0"] == "181" and first["meta"] == "recordings releaseids"


def test_low_scores_and_bad_ids_are_ignored():
    svc = FakeAcoustID({"a": result([REC[1]], score=0.2) + result(["../not-an-id"])})
    assert AcoustID(svc, min_interval=0).lookup([Fingerprint(1, "FP-a")]) == [[]]


def test_service_errors():
    with pytest.raises(ProviderError, match="invalid API key"):
        AcoustID(lambda form: {"status": "error", "error": {"message": "invalid API key"}}).lookup([Fingerprint(1, "x")])


def test_rank_releases_prefers_the_album_over_compilations():
    from codetta.core.acoustid import Recording
    per_file = {
        "a": [Recording(REC[1], 0.9, releases=[REL, COMPILATION])],
        "b": [Recording(REC[2], 0.9, releases=[REL])],
        "c": [Recording(REC[3], 0.9, releases=[REL])],
    }
    assert rank_releases(per_file) == [(REL, 3), (COMPILATION, 1)]


def test_pairing_by_sound_beats_wrong_numbers_and_missing_titles():
    tracks = release_tracks(ALBUM)
    files = [FileInfo("x.flac", tracknumber=1), FileInfo("y.flac"), FileInfo("z.flac", "Opening", tracknumber=1)]
    p = pair_files(files, tracks, recordings={"x.flac": [REC[3]], "y.flac": [REC[2]], "z.flac": [REC[1]]})
    assert [p[f].track.title for f in ("x.flac", "y.flac", "z.flac")] == ["Closing", "Middle", "Opening"]
    assert all(p[f].confidence == "high" for f in p)


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
def untagged_album(tmp_path):
    """The same album, but the files have no tags at all and odd names."""
    music = tmp_path / "music"
    album = music / "Coda Tester" / "Fixture Album"
    album.mkdir(parents=True)
    engine = MetadataEngine()
    for name, src in [("track_a.flac", "sample.flac"), ("track_b.mp3", "sample.mp3"), ("track_c.m4a", "sample.m4a")]:
        shutil.copy2(FIXTURES_DIR / src, album / name)
        engine.update_tags(album / name, {k: None for k in ("title", "artist", "album", "albumartist", "tracknumber",
                                                             "discnumber", "genre", "date")})
    return music


HEARD = {"track_a.flac": result([REC[3]]), "track_b.mp3": result([REC[1]]), "track_c.m4a": result([REC[2]])}


@pytest.fixture
def make_client(untagged_album, tmp_path):
    opened = []

    def make(acoustid=None, enable=("musicbrainz", "acoustid"), run=fake_fpcalc, link=None, **settings):
        svc = acoustid or FakeAcoustID(HEARD)
        link = link or FakeLink()
        app = create_app(Settings(music_dir=untagged_album, config_dir=tmp_path / "config", **settings),
                         fetch_mb=FakeMB(), fetch_art=lambda url: None, post_acoustid=svc, acoustid_api=link,
                         run_fpcalc=run)
        c = TestClient(app)
        c.__enter__()
        opened.append(c)
        if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 200:
            c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
        c.put("/api/connections", json={"enabled": {k: k in enable for k in ("musicbrainz", "acoustid")}})
        c.svc, c.link = svc, link
        return c
    yield make
    for c in opened:
        c.__exit__(None, None, None)


def test_identify_is_off_by_default(make_client):
    c = make_client(enable=("musicbrainz",))
    res = c.post("/api/musicbrainz/identify", json={"folder": FOLDER})
    assert res.status_code == 403 and "AcoustID" in res.json()["detail"]
    assert c.svc.forms == []
    c = make_client(enable=("acoustid",))  # needs MusicBrainz too
    assert c.post("/api/musicbrainz/identify", json={"folder": FOLDER}).status_code == 403


def test_identify_untagged_album_end_to_end(make_client):
    c = make_client()
    data = c.post("/api/musicbrainz/identify", json={"folder": FOLDER}).json()
    assert data["identified"] == 3 and data["total"] == 3
    assert data["candidates"][0]["id"] == REL and data["candidates"][0]["heard"] == 3
    assert data["candidates"][0]["score"] == 100
    sent = c.svc.forms[0]
    assert set(sent) == {"client", "meta", "format", "batch", "duration.0", "fingerprint.0", "duration.1", "fingerprint.1",
                         "duration.2", "fingerprint.2"}  # fingerprints and lengths only: no names, no tags

    p = c.post("/api/musicbrainz/preview", json={"folder": FOLDER, "release": REL,
                                                 "recordings": data["recordings"]}).json()
    titles = {f["path"].rsplit("/", 1)[1]: f["track"]["title"] for f in p["files"]}
    assert titles == {"track_a.flac": "Closing", "track_b.mp3": "Opening", "track_c.m4a": "Middle"}
    assert all(f["confidence"] == "high" for f in p["files"])

    res = c.post("/api/musicbrainz/apply", json={"folder": FOLDER, "release": REL, "recordings": data["recordings"],
                                                  "cover": "none"}).json()
    assert res["updated"] == 3
    t = c.get("/api/track", params={"path": f"{FOLDER}/track_a.flac"}).json()["tags"]
    assert t["title"] == ["Closing"] and t["tracknumber"] == ["3/3"] and t["musicbrainz_trackid"] == [REC[3]]


def test_unrecognised_and_unreadable_files_are_reported(make_client, untagged_album):
    shutil.copy2(FIXTURES_DIR / "sample.flac", untagged_album / FOLDER / "broken.flac")
    c = make_client(FakeAcoustID({"track_a.flac": result([REC[3]])}))
    data = c.post("/api/musicbrainz/identify", json={"folder": FOLDER}).json()
    status = {f["path"].rsplit("/", 1)[1]: f["status"] for f in data["files"]}
    assert status == {"broken.flac": "error", "track_a.flac": "identified", "track_b.mp3": "unknown",
                      "track_c.m4a": "unknown"}
    assert data["identified"] == 1


def test_missing_fpcalc_is_reported(make_client):
    c = make_client(run=None, fpcalc="/nonexistent/fpcalc")
    res = c.post("/api/musicbrainz/identify", json={"folder": FOLDER})
    assert res.status_code == 503 and "fpcalc" in res.json()["detail"]
    acoustid = next(x for x in c.get("/api/connections").json()["connections"] if x["id"] == "acoustid")
    assert "fpcalc" in acoustid["unavailable"]


def test_acoustid_errors_are_reported(make_client):
    c = make_client(FakeAcoustID({}, error=ProviderError("AcoustID answered with an error (invalid API key)")))
    res = c.post("/api/musicbrainz/identify", json={"folder": FOLDER})
    assert res.status_code == 502 and "invalid API key" in res.json()["detail"]


def test_bad_recording_ids_are_ignored(make_client):
    c = make_client()
    res = c.post("/api/musicbrainz/preview", json={"folder": FOLDER, "release": REL,
                                                   "recordings": {f"{FOLDER}/track_a.flac": ["../../etc", "x" * 50]}})
    assert res.status_code == 200


# --- The person's own AcoustID key (needed for lookups from 2027) -----------------------------


def account(tmp_path, link=None, **kw):
    from codetta.core.acoustid import AcoustIDAccount
    return AcoustIDAccount(tmp_path / "acoustid.json", link or FakeLink(), client="APP", clock=lambda: 1e6, **kw)


def test_lookup_sends_the_user_key_only_once_it_works(tmp_path):
    acc = account(tmp_path)
    svc = FakeAcoustID({"a": result([REC[1]])})
    ac = AcoustID(svc, key="APP", min_interval=0, account=acc)
    ac.lookup([Fingerprint(1, "FP-a")])
    assert "user" not in svc.forms[-1]
    acc.request_link("nas")
    ac.lookup([Fingerprint(1, "FP-a")])
    assert "user" not in svc.forms[-1]  # still waiting: AcoustID would turn it down like a wrong key
    acc.api.states["LINKED-KEY-1"] = "approved"
    acc._checked = -1e9
    assert acc.refresh() == "approved"
    ac.lookup([Fingerprint(1, "FP-a")])
    assert svc.forms[-1]["user"] == "LINKED-KEY-1" and svc.forms[-1]["client"] == "APP"


def test_needs_user_key_error_says_what_to_do():
    from codetta.core.acoustid import UserKeyNeeded
    for answer in ({"status": "error", "error": {"code": 21, "message": "user key required"}},
                   ProviderError("AcoustID answered with an error (user key required)", code=21)):
        def post(form, answer=answer):
            if isinstance(answer, Exception):
                raise answer
            return answer
        with pytest.raises(UserKeyNeeded, match="Settings → Connections → AcoustID"):
            AcoustID(post, min_interval=0).lookup([Fingerprint(1, "x")])


def test_a_key_disconnected_on_acoustid_is_forgotten(tmp_path):
    from codetta.core.acoustid import UserKeyNeeded
    link = FakeLink()
    acc = account(tmp_path, link)
    assert acc.use_key("PASTED-KEY-1") == "approved"
    link.states["PASTED-KEY-1"] = "revoked"
    ac = AcoustID(lambda form: {"status": "error", "error": {"code": 4, "message": "invalid user API key"}},
                  min_interval=0, account=acc)
    with pytest.raises(UserKeyNeeded, match="disconnected"):
        ac.lookup([Fingerprint(1, "x")])
    assert acc.state == "none" and not acc.usable_key()


def test_account_file_is_private_and_survives_a_restart(tmp_path):
    acc = account(tmp_path)
    acc.request_link("nas")
    assert (tmp_path / "acoustid.json").stat().st_mode & 0o777 == 0o600
    again = account(tmp_path)
    assert again.state == "pending" and again.out()["link"]["code"] == "WT14-9E3S"


def test_a_link_past_its_expiry_is_dropped(tmp_path):
    from datetime import UTC, datetime
    acc = account(tmp_path, now=lambda: datetime(3000, 1, 1, tzinfo=UTC))
    acc.request_link("nas")
    assert acc.refresh() == "none" and acc.outcome == "expired"


def test_env_key_locks_it(tmp_path):
    acc = account(tmp_path, env_key="ENV-KEY-123")
    assert acc.state == "approved" and acc.usable_key() == "ENV-KEY-123" and acc.out()["locked"]


def test_connecting_by_linking_through_the_api(make_client):
    c = make_client()
    assert c.get("/api/onboarding").json()["steps"].count("acoustid") == 1  # on, not connected: asked
    assert c.get("/api/acoustid").json()["state"] == "none"
    res = c.post("/api/acoustid/connect", json={"return_url": "http://gav-homeserver:8111/?acoustid=back"})
    d = res.json()
    assert res.status_code == 200 and d["state"] == "pending" and d["link"]["code"] == "WT14-9E3S"
    url, form = c.link.calls[-1]
    assert url.endswith("/request_link") and form["device"] == "gav-homeserver"
    assert form["return_url"] == "http://gav-homeserver:8111/?acoustid=back"
    assert "LINKED-KEY-1" not in res.text  # the key never goes to the page
    c.link.states["LINKED-KEY-1"] = "approved"
    from codetta.core import acoustid as mod
    old = mod.STATUS_EVERY  # checked with AcoustID at most every few seconds: no wait here
    mod.STATUS_EVERY = 0
    try:
        d = c.get("/api/acoustid").json()
    finally:
        mod.STATUS_EVERY = old
    assert d["state"] == "approved" and "LINKED-KEY-1" not in str(d)
    assert "acoustid" not in c.get("/api/onboarding").json()["steps"]
    c.post("/api/musicbrainz/identify", json={"folder": FOLDER})
    assert c.svc.forms[-1]["user"] == "LINKED-KEY-1"
    assert c.put("/api/acoustid", json={"key": ""}).json()["state"] == "none"


def test_declined_link_is_forgotten_and_explained(make_client):
    from codetta.core import acoustid as mod
    c = make_client()
    c.post("/api/acoustid/connect", json={"return_url": ""})
    c.link.states["LINKED-KEY-1"] = "declined"
    old, mod.STATUS_EVERY = mod.STATUS_EVERY, 0
    try:
        d = c.get("/api/acoustid").json()
    finally:
        mod.STATUS_EVERY = old
    assert d["state"] == "none" and d["outcome"] == "declined"


def test_pasting_a_key(make_client):
    c = make_client()
    assert c.put("/api/acoustid", json={"key": "has spaces in it"}).status_code == 422
    res = c.put("/api/acoustid", json={"key": "NOT-A-REAL-KEY"})
    assert res.status_code == 422 and c.get("/api/acoustid").json()["state"] == "none"
    d = c.put("/api/acoustid", json={"key": "PASTED-KEY-1"}).json()
    assert d["state"] == "approved" and d["how"] == "pasted"


def test_bad_return_addresses_are_refused(make_client):
    c = make_client()
    for url in ("javascript:alert(1)", "file:///etc/passwd", "http://"):
        assert c.post("/api/acoustid/connect", json={"return_url": url}).status_code == 422
    assert c.link.calls == []


def test_identify_without_a_key_offers_to_connect(make_client):
    c = make_client(FakeAcoustID({}, error=ProviderError("AcoustID answered with an error (user key required)", code=21)))
    res = c.post("/api/musicbrainz/identify", json={"folder": FOLDER})
    assert res.status_code == 428 and "Settings → Connections → AcoustID" in res.json()["detail"]


def test_setup_step_waits_until_acoustid_is_on(make_client):
    c = make_client(enable=("musicbrainz",))
    assert "acoustid" not in c.get("/api/onboarding").json()["steps"]


def test_device_name_prefers_the_address_name():
    from codetta.web.routes.acoustid import device_name
    assert device_name("http://gav-homeserver:8111/") == "gav-homeserver"
    assert device_name("http://100.64.0.3:8111/") not in ("", "100.64.0.3")


def test_request_link_also_reads_the_documented_shape(tmp_path):
    """AcoustID's docs put "link" beside "user" rather than inside it: both work."""
    def api(url, form):
        return {"status": "ok", "user": {"apikey": "DOCS-KEY-1"},
                "link": {"code": "AB12-CD34", "url": "https://acoustid.org/link?code=AB12-CD34", "expires": ""}}
    acc = AcoustIDAccount(tmp_path / "acoustid.json", api, client="app")
    acc.request_link("server")
    assert acc.state == "pending" and acc.out()["link"]["code"] == "AB12-CD34"
