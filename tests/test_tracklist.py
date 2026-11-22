"""Paste a tracklist: reading what people paste, pairing it with files, and writing it safely."""

import shutil

import pytest
from fastapi.testclient import TestClient

from codetta.core.engine import MetadataEngine
from codetta.core.tracklist import pair, parse
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR


def rows(text, **kw):
    return [(t.disc, t.number, t.artist, t.title, t.seconds) for t in parse(text, **kw).tracks]


@pytest.mark.parametrize(("text", "expected"), [
    ("1. 15 Step (3:58)\n2. Bodysnatchers (4:02)", [(None, 1, None, "15 Step", 238), (None, 2, None, "Bodysnatchers", 242)]),
    ("1.\tParanoid Android\t06:23", [(None, 1, None, "Paranoid Android", 383)]),  # Bandcamp
    ('No.\tTitle\tWriter(s)\tLength\n1.\t"Airbag"\tRadiohead\t4:44\nTotal length:\t53:21',  # Wikipedia
     [(None, 1, None, "Airbag", 284)]),
    ('1. "Love Lockdown" (featuring Kid Cudi)\t4:30', [(None, 1, None, "Love Lockdown (featuring Kid Cudi)", 270)]),
    ("A1\t–Daft Punk\tGive Life Back To Music\t4:34\nB1\t–Daft Punk\tGiorgio By Moroder\t9:04",  # Discogs vinyl
     [(None, 1, "Daft Punk", "Give Life Back To Music", 274), (None, 2, "Daft Punk", "Giorgio By Moroder", 544)]),
    ("Disc 1\n1. Intro\nDisc 2\n1. Outro", [(1, 1, None, "Intro", None), (2, 1, None, "Outro", None)]),
    ("1-01 Intro 2:01\n2-01 Outro 4:00", [(1, 1, None, "Intro", 121), (2, 1, None, "Outro", 240)]),
    ("1) First\n2 - Second\n03 Third", [(None, 1, None, "First", None), (None, 2, None, "Second", None), (None, 3, None, "Third", None)]),
    ("Airbag\n7 Rings\nKarma Police", [(None, None, None, "Airbag", None), (None, None, None, "7 Rings", None),
                                       (None, None, None, "Karma Police", None)]),  # titles, not numbers
    ("1. 7 Rings\n2. 22", [(None, 1, None, "7 Rings", None), (None, 2, None, "22", None)]),
    ("Speak to Me\nBreathe\nTime", [(None, None, None, "Speak to Me", None), (None, None, None, "Breathe", None),
                                     (None, None, None, "Time", None)]),  # a song called "Time" isn't a header
    ("Tracklist:\nNo.\tTitle\tLength\n1.\tAirbag\t4:44", [(None, 1, None, "Airbag", 284)]),
    ("Disco Inferno\nCD2: Bonus\nSide B\nSideways", [(None, None, None, "Disco Inferno", None),
                                                   (2, None, None, "Sideways", None)]),  # "Disco" isn't disc O
    ("Total Eclipse of the Heart\nTotal length: 4:30", [(None, None, None, "Total Eclipse of the Heart", None)]),
])
def test_what_people_paste_is_read(text, expected):
    assert rows(text) == expected


def test_artist_first_is_worked_out_and_can_be_overridden():
    same = "1. Radiohead - Airbag\n2. Radiohead - Paranoid Android\n3. Radiohead - Lucky"
    assert parse(same).artist_first and rows(same)[0][2:4] == ("Radiohead", "Airbag")
    remix = "1. Paper Planes - Diplo Remix\n2. Boyz\n3. Jimmy"
    assert not parse(remix).artist_first and rows(remix)[0][3] == "Paper Planes - Diplo Remix"
    assert rows(same, artist_first=False)[0][3] == "Radiohead - Airbag"


def test_pairing_by_number_in_order_and_across_discs():
    tracks = parse("1. One 3:00\n2. Two 3:00\n3. Three 3:00").tracks
    by_number = pair([("b.flac", None, 2, 180.0), ("a.flac", None, 1, 181.0)], tracks)
    assert [(p.path, p.track.title) for p in by_number] == [("b.flac", "Two"), ("a.flac", "One")]
    in_order = pair([("x.flac", None, None, None), ("y.flac", None, None, None)], parse("Alpha\nBeta").tracks)
    assert [p.track.title for p in in_order] == ["Alpha", "Beta"]
    discs = parse("Disc 1\n1. A\nDisc 2\n1. B").tracks
    assert [p.track.title for p in pair([("d2.flac", 2, 1, None), ("d1.flac", 1, 1, None)], discs)] == ["B", "A"]
    off = pair([("a.flac", None, 1, 300.0)], parse("1. One 3:00").tracks)
    assert off[0].warning.startswith("Lengths differ")


@pytest.fixture
def client(tmp_path):
    album = tmp_path / "music" / "OK Computer"
    album.mkdir(parents=True)
    e = MetadataEngine()
    for n, src in ((1, "sample.flac"), (2, "sample.mp3"), (3, "sample.flac")):
        name = f"track{n}.{src.rsplit('.', 1)[1]}"
        shutil.copy2(FIXTURES_DIR / src, album / name)
        e.update_tags(album / name, {"title": f"Track {n}", "tracknumber": str(n), "artist": "Radiohead"})
    with TestClient(create_app(Settings(music_dir=tmp_path / "music", config_dir=tmp_path / "config", auth=False))) as c:
        yield c


PASTE = "1.\t\"Airbag\"\tRadiohead\t4:44\n2.\t\"Paranoid Android\"\tRadiohead\t6:23\n3.\t\"Subterranean Homesick Alien\"\tRadiohead\t4:27"


def title(c, name):
    return c.get("/api/track", params={"path": f"OK Computer/{name}"}).json()["tags"]["title"]


def test_a_pasted_tracklist_is_previewed_then_written_and_undone(client):
    d = client.post("/api/tags/tracklist", json={"folder": "OK Computer", "text": PASTE}).json()
    assert d["lines"] == 3 and d["tracks"] == 3 and d["changing"] == 3
    assert [p["changes"][0]["new"] for p in d["preview"]] == ["Airbag", "Paranoid Android", "Subterranean Homesick Alien"]
    assert d["warnings"] == 3  # the sample files are a second long: the lengths don't match, and it says so
    assert title(client, "track2.mp3") == ["Track 2"]  # a preview writes nothing
    r = client.post("/api/tags/tracklist", json={"folder": "OK Computer", "text": PASTE, "dry_run": False}).json()
    assert r["changed"] == 3 and title(client, "track2.mp3") == ["Paranoid Android"]
    entry = client.get("/api/activity").json()[0]
    assert entry["message"] == "Tracklist: 3 tracks"
    client.post(f"/api/activity/{entry['id']}/undo")
    assert title(client, "track2.mp3") == ["Track 2"]


def test_a_shorter_tracklist_leaves_the_rest_alone(client):
    d = client.post("/api/tags/tracklist", json={"folder": "OK Computer", "text": "1. Airbag\n2. Paranoid Android"}).json()
    assert d["lines"] == 2 and d["changing"] == 2
    assert d["preview"][2]["warning"] == "No line for this file" and not d["preview"][2]["changes"]


def test_nothing_usable_is_explained_and_paths_stay_inside(client):
    assert client.post("/api/tags/tracklist", json={"folder": "OK Computer", "text": "\n\nTotal length: 53:21\n"}).status_code == 422
    assert client.post("/api/tags/tracklist", json={"paths": ["../x.flac"], "text": "1. A"}).status_code in (400, 422)
