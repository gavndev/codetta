"""Autoplay: which source answers, how answers become library files, and variety."""

import random
import time

from tests.test_musicbrainz import PASSWORD, album_dir  # noqa: F401 (fixture)

from codetta.core.audiomuse import AudioMuse, AudioMuseClient, AudioMuseError, AudioMuseStore
from codetta.core.autoplay import Autoplay

A1 = "11111111-1111-4111-8111-111111111111"  # the playing artist
A2 = "22222222-2222-4222-8222-222222222222"  # a similar artist
R2 = "33333333-3333-4333-8333-333333333333"  # one of A2's recordings


def lib():
    """{path: tags}: a small library of four artists."""
    out = {}
    for artist, mbid, genre in (("Juno Park", A1, "Indie Pop"), ("Mira Sol", A2, "Indie Pop"),
                                ("Ines Calder", "", "Ambient"), ("Theo Lindqvist", "", "Indie Pop")):
        for album in ("One", "Two"):
            for n in range(1, 5):
                tags = {"title": [f"{artist} {album} {n}"], "artist": [artist], "albumartist": [artist],
                        "album": [album], "genre": [genre]}
                if mbid:
                    tags["musicbrainz_artistid"] = [mbid]
                out[f"{artist}/{album}/{n:02}.flac"] = tags
    out["Mira Sol/One/01.flac"]["musicbrainz_trackid"] = [R2]
    return out


class FakeIndex:
    def __init__(self, tracks):
        self.tracks = tracks

    def paths_where(self, key, value, limit=5000):
        v = value.casefold()
        return {p for p, t in self.tracks.items() if any(x.casefold() == v for x in t.get(key, []))}

    def random_paths(self, n):
        return sorted(self.tracks)[:n]


def make(on=(), fetch=None, audiomuse=None, tracks=None):
    tracks = tracks or lib()
    return Autoplay(FakeIndex(tracks), lambda ps: {p: tracks[p] for p in ps if p in tracks}, lambda cid: cid in on,
                    fetch or (lambda url: (_ for _ in ()).throw(AssertionError(f"no network expected: {url}"))),
                    audiomuse, rnd=random.Random(1))


SEED = "Juno Park/One/01.flac"


def artist_of(p):
    return p.split("/")[0]


def test_with_every_connection_off_the_library_keeps_playing():
    r = make().next_tracks([SEED], n=6)
    assert r["source"] == "library" and r["because"] == "Juno Park"
    assert len(r["paths"]) == 6 and SEED not in r["paths"]


def test_variety_no_repeats_two_per_artist_and_never_the_same_album_twice_in_a_row():
    r = make().next_tracks([SEED], avoid={"Juno Park/Two/01.flac"}, n=8)
    paths = r["paths"]
    assert len(set(paths)) == len(paths) and "Juno Park/Two/01.flac" not in paths
    counts = {}
    for p in paths:
        counts[artist_of(p)] = counts.get(artist_of(p), 0) + 1
    assert max(counts.values()) <= 2
    albums = [p.rsplit("/", 1)[0] for p in paths]
    assert all(a != b for a, b in zip(albums, albums[1:], strict=False))


class FakeAudioMuse:
    def __init__(self, answer=None, error=None):
        self.answer, self.error = answer or [], error
        self.store = type("S", (), {"configured": True})()
        self.asked = []

    def similar(self, title, artist, n=30):
        self.asked.append((title, artist))
        if self.error:
            raise self.error
        return self.answer


def test_audiomuse_answers_are_found_in_the_library_by_title_and_artist():
    am = FakeAudioMuse([{"title": f"Ines Calder One {n}", "artist": "Ines Calder", "album": "One"} for n in (1, 2)]
                       + [{"title": f"Theo Lindqvist Two {n}", "artist": "Theo Lindqvist", "album": ""} for n in (1, 2)]
                       + [{"title": "Not In The Library", "artist": "Nobody", "album": ""}])
    r = make(on={"audiomuse"}, audiomuse=am).next_tracks([SEED], n=4)
    assert r["source"] == "audiomuse"
    assert am.asked[0] == ("Juno Park One 1", "Juno Park")
    assert sorted(r["paths"]) == ["Ines Calder/One/01.flac", "Ines Calder/One/02.flac",
                                  "Theo Lindqvist/Two/01.flac", "Theo Lindqvist/Two/02.flac"]


def test_a_failing_source_falls_through_quietly():
    am = FakeAudioMuse(error=AudioMuseError("Couldn't reach AudioMuse-AI"))
    r = make(on={"audiomuse"}, audiomuse=am).next_tracks([SEED], n=5)
    assert r["source"] == "library" and len(r["paths"]) == 5


def test_listenbrainz_by_recording_id_then_artist_id_skipping_the_playing_artist():
    asked = []

    def fetch(url):
        asked.append(url)
        return {A1: [{"recording_mbid": "99999999-9999-4999-8999-999999999999", "similar_artist_mbid": A1,
                      "similar_artist_name": "Juno Park"}],
                A2: [{"recording_mbid": R2, "similar_artist_mbid": A2, "similar_artist_name": "Mira Sol"}],
                "44444444-4444-4444-8444-444444444444": [{"recording_mbid": "55555555-5555-4555-8555-555555555555",
                                                          "similar_artist_name": "Theo Lindqvist"}]}

    r = make(on={"listenbrainz"}, fetch=fetch).next_tracks([SEED], n=3)
    assert r["source"] == "listenbrainz"
    assert asked and f"/lb-radio/artist/{A1}?" in asked[0]
    assert "Mira Sol/One/01.flac" in r["paths"]  # the recording ListenBrainz named
    assert not any(artist_of(p) == "Juno Park" for p in r["paths"])
    assert any(artist_of(p) == "Theo Lindqvist" for p in r["paths"])  # by name: no IDs in those tags


def test_listenbrainz_needs_a_musicbrainz_artist_id():
    seed = "Ines Calder/One/01.flac"  # no MusicBrainz IDs
    r = make(on={"listenbrainz"}).next_tracks([seed], n=3)  # fetch would fail the test if called
    assert r["source"] == "library"


def test_deezer_related_artists_by_name_and_answers_are_remembered():
    asked = []

    def fetch(url):
        asked.append(url)
        if "/search/artist" in url:  # a namesake with few fans comes first
            return {"data": [{"id": 6, "name": "Juno Park", "nb_fan": 40}, {"id": 7, "name": "Juno Park", "nb_fan": 90000}]}
        assert "/artist/7/related" in url
        return {"data": [{"id": 8, "name": "Mira Sol"}, {"id": 9, "name": "Ines Calder"}]}

    ap = make(on={"deezer"}, fetch=fetch)
    r = ap.next_tracks([SEED], n=4)
    assert r["source"] == "deezer"
    assert {artist_of(p) for p in r["paths"]} == {"Mira Sol", "Ines Calder"}
    ap.next_tracks([SEED], n=4)
    assert len(asked) == 2  # the second time came from memory


def test_no_seeds_still_plays_something():
    r = make(on={"audiomuse", "listenbrainz", "deezer"}).next_tracks([], n=3)
    assert r["source"] == "library" and len(r["paths"]) == 3


# --- AudioMuse-AI client ------------------------------------------------------------------------

def test_audiomuse_client_sends_the_token_and_reads_similar_tracks():
    seen = {}

    def request(method, url, headers, body):
        seen.update(method=method, url=url, headers=headers)
        return 200, b'[{"item_id": "x", "title": "Coastline", "author": "Mira Sol", "album": "unknown", "distance": 0.1}]'

    out = AudioMuseClient("audiomuse:8000/", "secret-token", request).similar("Harbour Song", "Oda Saar", 5)
    assert out == [{"title": "Coastline", "artist": "Mira Sol", "album": ""}]
    assert seen["url"].startswith("http://audiomuse:8000/api/similar_tracks?title=Harbour+Song&artist=Oda+Saar&n=5")
    assert seen["headers"]["Authorization"] == "Bearer secret-token"


def test_audiomuse_turned_down_token_reads_plainly(tmp_path):
    store = AudioMuseStore(tmp_path / "audiomuse.json")
    store.settings.url = "http://audiomuse:8000"
    am = AudioMuse(store, lambda: True, request=lambda *a: (401, b'{"error": "Unauthorized"}'))
    am.check()
    assert "turned down the token" in am.last_error


def test_audiomuse_settings_file_is_private(tmp_path):
    store = AudioMuseStore(tmp_path / "audiomuse.json")
    store.settings.url, store.settings.token = "http://am:8000", "t0ken"
    store.save()
    assert (tmp_path / "audiomuse.json").stat().st_mode & 0o077 == 0
    again = AudioMuseStore(tmp_path / "audiomuse.json")
    assert again.url == "http://am:8000" and again.token == "t0ken"


# --- The route ----------------------------------------------------------------------------------

def test_route_plays_on_from_the_library_and_ignores_paths_outside_it(album_dir, tmp_path):  # noqa: F811
    from fastapi.testclient import TestClient

    from codetta.web.app import Settings, create_app
    app = create_app(Settings(music_dir=album_dir, config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        for _ in range(100):  # the index scans in the background: wait for it
            if c.get("/api/search?q=opening").json().get("tracks"):
                break
            time.sleep(0.05)
        r = c.post("/api/autoplay/next", json={"seeds": ["../../etc/passwd", "Coda Tester/Fixture Album/01.flac"],
                                               "avoid": ["Coda Tester/Fixture Album/02.mp3"], "n": 5}).json()
    paths = [t["path"] for t in r["tracks"]]
    assert r["source"] == "library" and r["source_name"] == "your library"
    assert paths == ["Coda Tester/Fixture Album/03.m4a"]


def test_a_source_with_only_a_few_songs_is_topped_up_by_the_next():
    am = FakeAudioMuse([{"title": "Ines Calder One 1", "artist": "Ines Calder", "album": "One"}])
    r = make(on={"audiomuse"}, audiomuse=am).next_tracks([SEED], n=5)
    assert r["source"] == "audiomuse" and len(r["paths"]) == 5
    assert "Ines Calder/One/01.flac" in r["paths"]
