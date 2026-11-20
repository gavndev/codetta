"""Files the way other taggers leave them. Each is built here with the quirks real libraries
are full of (old ID3 versions, ID3v1 and APE tags side by side, iTunes' freeform atoms,
mixed-case Vorbis keys, several pictures, huge covers, private frames), then one field is
saved through Codetta and everything else must come out exactly as it went in."""
import shutil

import pytest
from mutagen.apev2 import APEv2
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    PCNT,
    POPM,
    PRIV,
    TALB,
    TCON,
    TIT2,
    TPE1,
    TXXX,
    UFID,
    USLT,
    WXXX,
)
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.oggvorbis import OggVorbis

from codetta.core.engine import MetadataEngine
from tests.conftest import FIXTURES_DIR

engine = MetadataEngine()
COVER = (FIXTURES_DIR / "cover.jpg").read_bytes()
BIG_COVER = COVER + b"\0" * (5 * 1024 * 1024)  # a 5 MB picture (some taggers embed full scans)


def copy(tmp_path, name):
    dest = tmp_path / name
    shutil.copy2(FIXTURES_DIR / name, dest)
    return dest


def id3_frames(path):
    """Every ID3 frame as comparable bytes, by frame key."""
    tags = ID3(path)
    return {k: repr(v) for k, v in tags.items()}


# --- MP3 -------------------------------------------------------------------------------------

def make_mp3_like_older_taggers(path):
    """ID3v2.3 (what Windows Media Player, iTunes and Mp3tag write by default) with
    MusicBrainz TXXX frames, comments in two languages, lyrics, a rating, a play count,
    private frames, a URL, a front and a back cover, plus an ID3v1 tag and an APE tag."""
    tags = ID3()
    tags.add(TIT2(encoding=1, text="Old Title"))
    tags.add(TPE1(encoding=1, text="Ünïcødé Artist"))
    tags.add(TALB(encoding=1, text="アルバム"))
    tags.add(TCON(encoding=1, text="Electronic"))
    tags.add(TXXX(encoding=1, desc="MusicBrainz Album Id", text="2c5b1a5e-0000-4000-8000-000000000001"))
    tags.add(TXXX(encoding=1, desc="CATALOGNUMBER", text="ABC-123"))
    tags.add(TXXX(encoding=1, desc="replaygain_track_gain", text="-6.20 dB"))
    tags.add(COMM(encoding=1, lang="eng", desc="", text="English comment"))
    tags.add(COMM(encoding=1, lang="deu", desc="", text="Deutscher Kommentar"))
    tags.add(COMM(encoding=1, lang="eng", desc="iTunNORM", text=" 00000A2B 00000B3C"))
    tags.add(USLT(encoding=1, lang="eng", desc="", text="Line one\nLine two"))
    tags.add(POPM(email="Windows Media Player 9 Series", rating=196, count=12))
    tags.add(PCNT(count=42))
    tags.add(PRIV(owner="WM/MediaClassPrimaryID", data=b"\x01\x02\x03\x04"))
    tags.add(UFID(owner="http://musicbrainz.org", data=b"2c5b1a5e-0000-4000-8000-000000000002"))
    tags.add(WXXX(encoding=0, desc="Bandcamp", url="https://example.invalid/album"))
    tags.add(APIC(encoding=0, mime="image/jpeg", type=3, desc="front", data=COVER))
    tags.add(APIC(encoding=0, mime="image/jpeg", type=4, desc="back", data=COVER[::-1]))
    ape = APEv2()  # foobar2000 and Mp3tag put the APE tag before the ID3v1 tag at the end
    ape["Title"] = "APE title"
    ape["Custom"] = "kept"
    ape.save(path)
    tags.save(path, v2_version=3, v1=2)  # v1=2: also write an ID3v1 tag, last in the file


def id3v1_title(path):
    from mutagen.id3 import ParseID3v1
    tail = path.read_bytes()[-128:]
    assert tail[:3] == b"TAG", "no ID3v1 tag at the end of the file"
    return str(ParseID3v1(tail)["TIT2"])


def test_mp3_from_an_older_tagger_keeps_every_other_frame(tmp_path):
    path = copy(tmp_path, "sample.mp3")
    make_mp3_like_older_taggers(path)
    before = id3_frames(path)
    ape_before = dict(APEv2(path))
    assert id3v1_title(path) == "Old Title"

    engine.update_tags(path, {"title": "New Title"})

    after = id3_frames(path)
    assert ID3(path)["TIT2"].text == ["New Title"]
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed <= {"TIT2"}, f"frames changed besides the title: {sorted(changed - {'TIT2'})}"
    assert {str(k): str(v) for k, v in APEv2(path).items()} == {str(k): str(v) for k, v in ape_before.items()}
    assert id3v1_title(path) == "New Title"  # old car stereos read this one
    assert engine.load_metadata(path).duration is not None  # still a playable MP3


def test_mp3_with_a_5mb_cover_saves_and_keeps_it(tmp_path):
    path = copy(tmp_path, "sample.mp3")
    tags = ID3(path)
    tags.delall("APIC")
    tags.add(APIC(encoding=0, mime="image/jpeg", type=3, desc="", data=BIG_COVER))
    tags.save(path)
    engine.update_tags(path, {"artist": ["A", "B"]})
    assert ID3(path).getall("APIC")[0].data == BIG_COVER
    assert engine.load_metadata(path).tags["artist"] == ["A", "B"]


# --- FLAC ------------------------------------------------------------------------------------

def make_flac_like_other_taggers(path):
    """Mixed-case keys (foobar2000 writes UPPER, some taggers Mixed), custom keys, the same key
    twice, an empty value, no padding at all, and three pictures."""
    f = FLAC(path)
    f.clear()
    f.clear_pictures()
    f["TITLE"] = "Old Title"
    f["Artist"] = ["First", "Second"]
    f["album"] = "Albém"
    f["MUSICBRAINZ_ALBUMID"] = "2c5b1a5e-0000-4000-8000-000000000003"
    f["CUSTOM_FIELD"] = "custom value"
    f["COMMENT"] = ["one", "two"]
    f["REPLAYGAIN_TRACK_GAIN"] = "-6.20 dB"
    f["EMPTY"] = ""
    for kind, data in ((3, COVER), (4, COVER[::-1]), (8, COVER + b"x")):
        pic = Picture()
        pic.type, pic.mime, pic.data = kind, "image/jpeg", data
        f.add_picture(pic)
    f.save(padding=lambda info: 0)


def flac_state(path):
    f = FLAC(path)
    comments = sorted((k.lower(), v) for k, v in f.tags) if f.tags else []
    pics = [(p.type, p.mime, p.data) for p in f.pictures]
    return comments, pics, f.info.md5_signature, f.info.total_samples


def test_flac_from_other_taggers_keeps_keys_pictures_and_audio(tmp_path):
    path = copy(tmp_path, "sample.flac")
    make_flac_like_other_taggers(path)
    comments, pics, md5, samples = flac_state(path)

    engine.update_tags(path, {"title": "New Title"})

    comments2, pics2, md5_2, samples2 = flac_state(path)
    assert [c for c in comments2 if c[0] != "title"] == [c for c in comments if c[0] != "title"]
    assert ("title", "New Title") in comments2
    assert pics2 == pics
    assert (md5_2, samples2) == (md5, samples)  # the audio itself is untouched


def test_flac_with_a_5mb_cover_saves_and_keeps_it(tmp_path):
    path = copy(tmp_path, "sample.flac")
    f = FLAC(path)
    f.clear_pictures()
    pic = Picture()
    pic.type, pic.mime, pic.data = 3, "image/jpeg", BIG_COVER
    f.add_picture(pic)
    f.save()
    engine.update_tags(path, {"genre": "Ambient"})
    assert FLAC(path).pictures[0].data == BIG_COVER


# --- M4A -------------------------------------------------------------------------------------

def make_m4a_like_itunes(path):
    """iTunes' freeform ----:com.apple.iTunes atoms (MusicBrainz IDs, iTunNORM, iTunSMPB),
    compilation and tempo flags, a rating, two covers and a sort name."""
    m = MP4(path)
    m.clear()
    m["\xa9nam"] = ["Old Title"]
    m["\xa9ART"] = ["Artist"]
    m["soar"] = ["Artist, The"]
    m["cpil"] = True
    m["tmpo"] = [120]
    m["rtng"] = [4]
    m["----:com.apple.iTunes:MusicBrainz Album Id"] = [MP4FreeForm(b"2c5b1a5e-0000-4000-8000-000000000004")]
    m["----:com.apple.iTunes:iTunNORM"] = [MP4FreeForm(b" 00000A2B 00000B3C")]
    m["----:com.apple.iTunes:iTunSMPB"] = [MP4FreeForm(b" 00000000 00000840 000001C0")]
    m["covr"] = [MP4Cover(COVER, imageformat=MP4Cover.FORMAT_JPEG),
                 MP4Cover(COVER[::-1], imageformat=MP4Cover.FORMAT_JPEG)]
    m.save()


def m4a_state(path):
    m = MP4(path)
    return {k: repr(v) for k, v in m.tags.items()}, m.info.length


def test_m4a_from_itunes_keeps_freeform_atoms_and_covers(tmp_path):
    path = copy(tmp_path, "sample.m4a")
    make_m4a_like_itunes(path)
    tags, length = m4a_state(path)

    engine.update_tags(path, {"title": "New Title"})

    tags2, length2 = m4a_state(path)
    assert MP4(path)["\xa9nam"] == ["New Title"]
    changed = {k for k in set(tags) | set(tags2) if tags.get(k) != tags2.get(k)}
    assert changed <= {"\xa9nam"}, f"atoms changed besides the title: {sorted(changed - {'©nam'})}"
    assert length2 == length


# --- Ogg Vorbis --------------------------------------------------------------------------------

def test_ogg_with_a_big_embedded_picture_saves_and_keeps_it(tmp_path):
    import base64
    path = copy(tmp_path, "sample.ogg")
    pic = Picture()
    pic.type, pic.mime, pic.data = 3, "image/jpeg", BIG_COVER
    o = OggVorbis(path)
    o["METADATA_BLOCK_PICTURE"] = [base64.b64encode(pic.write()).decode("ascii")]
    o["Custom_Key"] = "kept"
    o.save()
    before = sorted((k.lower(), v) for k, v in OggVorbis(path).tags)

    engine.update_tags(path, {"album": "New Album"})

    after = sorted((k.lower(), v) for k, v in OggVorbis(path).tags)
    assert [x for x in after if x[0] != "album"] == [x for x in before if x[0] != "album"]
    assert ("album", "New Album") in after


# --- Every format: odd text ----------------------------------------------------------------

ODD_TEXT = [
    "مرحبا بالعالم",              # Arabic, right to left
    "שלום",                        # Hebrew
    "東京事変 – 群青日和",          # Japanese, with an en dash
    "Ναι",                         # Greek
    "été",            # combining accents (not precomposed)
    "👩‍🎤🎸🔥",                     # emoji with a zero-width joiner
    "AC/DC",                       # a slash (some formats once used / between artists)
    "Artist; Other",               # a semicolon
    "Tab\tinside",                 # a tab
    "x" * 2000,                    # very long
]


@pytest.mark.parametrize("name", ["sample.flac", "sample.mp3", "sample.m4a", "sample.ogg", "sample.opus",
                                  "sample.wma", "sample.wv", "sample.aiff", "sample.dsf"])
@pytest.mark.parametrize("text", ODD_TEXT, ids=range(len(ODD_TEXT)))
def test_odd_text_saves_exactly(tmp_path, name, text):
    path = copy(tmp_path, name)
    assert engine.update_tags(path, {"title": text, "artist": [text, "Second"]}).tags["title"] == [text]
    meta = engine.load_metadata(path)
    assert meta.tags["title"] == [text] and meta.tags["artist"] == [text, "Second"]
