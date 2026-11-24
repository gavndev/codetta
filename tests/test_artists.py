"""Tapping an artist name: which artists a credit names, judged by what the library has."""

import shutil

from fastapi.testclient import TestClient

from codetta.core.artists import pieces, resolve
from codetta.core.engine import MetadataEngine
from codetta.web.app import Settings, create_app
from tests.conftest import FIXTURES_DIR
from tests.test_musicbrainz import PASSWORD

KNOWN = {"Michael McDonald", "Metro Boomin", "Future", "Yung Lean", "Tyler, The Creator", "Simon & Garfunkel",
         "Earth, Wind & Fire", "Xzibit"}
FOLDERS = {"justice": "Justice", "various artists": "Various Artists", "travis scott": "Travis Scott"}


BANDS = {"Simon & Garfunkel", "Tyler, The Creator", "Earth, Wind & Fire"}  # on several albums each


def count(n, known=KNOWN):
    return (3 if n in BANDS else 1) if n in known else 0


def names(*credits):
    return [a["name"] for a in resolve(credits, count, FOLDERS)]


def test_collaborations_split_into_the_artists_the_library_has():
    assert names("Justice & Michael McDonald") == ["Justice", "Michael McDonald"]
    assert names("Yung Lean, Metro Boomin & Future") == ["Yung Lean", "Metro Boomin", "Future"]
    assert names("Travis Scott feat. Future") == ["Travis Scott", "Future"]
    assert names("Metro Boomin x Future") == ["Metro Boomin", "Future"]


def test_names_with_separators_inside_stay_whole():
    assert names("Tyler, The Creator") == ["Tyler, The Creator"]
    assert names("Simon & Garfunkel") == ["Simon & Garfunkel"]
    assert names("Earth, Wind & Fire feat. Future") == ["Earth, Wind & Fire", "Future"]
    assert names("Xzibit") == ["Xzibit"]  # the x in a name isn't a separator


def test_every_name_is_listed_and_folders_win():
    found = resolve(["justice & Nobody"], lambda n: 0, FOLDERS)
    # The folder's own spelling; a name the library has nothing of its own for is still listed.
    assert found == [{"name": "Justice", "folder": "Justice", "own": True}, {"name": "Nobody", "folder": None, "own": False}]
    assert names("Grand Theft Auto VI & Various Artists") == ["Grand Theft Auto VI", "Various Artists"]
    assert names("Nobody Known") == ["Nobody Known"]


def test_a_collaborations_own_credit_doesnt_hide_its_artists():
    # The song's artist tag is the whole credit, so the library "knows" it as a value.
    known = KNOWN | {"Justice & Michael McDonald", "Juvenile feat. Big Tymers & B.G.", "Juvenile", "Ann & Bob"}
    found = [a["name"] for a in resolve(["Justice & Michael McDonald", "Juvenile feat. Big Tymers & B.G.", "Ann & Bob"],
                                        lambda n: count(n, known), FOLDERS)]
    # "Ann & Bob" is on one song only: a one-off collaboration, so both names are offered.
    assert found == ["Justice", "Michael McDonald", "Juvenile", "Big Tymers", "B.G.", "Ann", "Bob"]


def test_several_credits_and_no_repeats():
    assert names("Future", "Metro Boomin & Future", "Yung Lean") == ["Future", "Metro Boomin", "Yung Lean"]


def test_pieces():
    c = "A, B & C feat. D"
    assert [c[a:b] for a, b in pieces(c)] == ["A", "B", "C", "D"]


def test_route(tmp_path):
    music = tmp_path / "music"
    engine = MetadataEngine()
    for folder, artist in (("Justice/Cross", "Justice"), ("Various Artists/GTA", "Justice & Michael McDonald"),
                           ("Michael McDonald/If That's What It Takes", "Michael McDonald")):
        (music / folder).mkdir(parents=True)
        f = music / folder / "01.flac"
        shutil.copy(FIXTURES_DIR / "sample.flac", f)
        engine.update_tags(f, {"artist": artist, "title": "x"})
    (music / "Michael McDonald").rename(music / "Mike")  # no folder named after him: found by his tags
    app = create_app(Settings(music_dir=music, config_dir=tmp_path / "config"))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
        for _ in range(100):
            if c.get("/api/search?q=artist: michael").json().get("tracks"):
                break
            import time
            time.sleep(0.05)
        r = c.get("/api/artists", params={"credit": ["Justice & Michael McDonald"]}).json()
    assert r["artists"] == [{"name": "Justice", "folder": "Justice", "own": True},
                            {"name": "Michael McDonald", "folder": None, "own": True}]
    # (Michael McDonald is known from his own album's tags; his folder is called "Mike".)


# --- Pictures -----------------------------------------------------------------------------------

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


def test_picture_from_the_artist_folder_first(tmp_path):
    from codetta.core.artistart import ArtistArt
    (tmp_path / "music" / "Justice").mkdir(parents=True)
    (tmp_path / "music" / "Justice" / "Artist.JPG").write_bytes(JPEG)
    art = ArtistArt(tmp_path / "music", tmp_path / "cache", lambda: True,
                    lambda u: (_ for _ in ()).throw(AssertionError("no network")), lambda u: None)
    assert art.picture("Justice", "Justice") == (JPEG, "image/jpeg")
    assert art.local("../etc") is None and art.local("a/b") is None


def test_picture_from_deezer_once_then_from_memory_and_never_a_namesake(tmp_path):
    from codetta.core.artistart import ArtistArt
    asked = []

    def fetch_json(url):
        asked.append(url)
        return {"data": [{"id": 1, "name": "Drake", "nb_fan": 40, "picture_medium": "https://cdn-images.dzcdn.net/images/artist/small/x.jpg"},
                         {"id": 2, "name": "Drake", "nb_fan": 9_000_000, "picture_medium": "https://cdn-images.dzcdn.net/images/artist/big/x.jpg"},
                         {"id": 3, "name": "Nobody", "nb_fan": 1, "picture_medium": "https://cdn-images.dzcdn.net/images/artist//250x250.jpg"}]}

    got = []
    art = ArtistArt(tmp_path / "music", tmp_path / "cache", lambda: True, fetch_json, lambda u: got.append(u) or JPEG)
    assert art.picture("Drake") == (JPEG, "image/jpeg")
    assert got == ["https://cdn-images.dzcdn.net/images/artist/big/x.jpg"]
    assert art.picture("drake") == (JPEG, "image/jpeg") and len(asked) == 1  # kept on the server
    assert art.picture("Nobody") is None  # Deezer's "no picture" stand-in
    assert art.picture("Someone Else") is None and art.picture("Someone Else") is None
    assert len(asked) == 3  # a miss is remembered too


def test_no_picture_from_deezer_while_its_connection_is_off(tmp_path):
    from codetta.core.artistart import ArtistArt
    art = ArtistArt(tmp_path / "music", tmp_path / "cache", lambda: False,
                    lambda u: (_ for _ in ()).throw(AssertionError("no network")), lambda u: None)
    assert art.picture("Drake") is None


def test_a_busy_deezer_is_not_taken_for_a_missing_picture(tmp_path):
    # Over quota, Deezer answers 200 with {"error": ...}: no week-long "no picture" marker for that.
    from codetta.core.artistart import ArtistArt
    answers = [{"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}},
               {"data": [{"id": 2, "name": "Drake", "picture_medium": "https://cdn-images.dzcdn.net/images/artist/big/x.jpg"}]}]
    art = ArtistArt(tmp_path / "music", tmp_path / "cache", lambda: True, lambda u: answers.pop(0), lambda u: JPEG)
    assert art.picture("Drake") is None
    assert not list((tmp_path / "cache").glob("*.none"))
    art._busy_until = 0  # a few minutes later
    assert art.picture("Drake") == (JPEG, "image/jpeg")  # asked again, and found


def test_a_broken_cached_picture_is_fetched_again_without_hanging(tmp_path):
    import threading

    from codetta.core.artistart import ArtistArt
    art = ArtistArt(tmp_path / "music", tmp_path / "cache", lambda: True,
                    lambda u: {"data": [{"id": 2, "name": "Drake", "picture_medium": "https://cdn-images.dzcdn.net/images/artist/big/x.jpg"}]},
                    lambda u: JPEG)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / (art._key("Drake") + ".img")).write_bytes(b"cut sh")
    result = {}
    t = threading.Thread(target=lambda: result.update(pic=art.picture("Drake")))
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "picture() hung on a broken cached file"
    assert result["pic"] == (JPEG, "image/jpeg")


def test_at_folders_are_artist_folders_too(tmp_path):
    from codetta.core.artists import top_folders
    for name in ("@Foo", "Bar", "@eaDir", ".hidden"):
        (tmp_path / name).mkdir()
    assert set(top_folders(tmp_path).values()) == {"@Foo", "Bar"}
