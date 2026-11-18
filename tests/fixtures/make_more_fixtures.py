"""Sample files for the formats added after the first five.

The audio comes from ffmpeg (1 second of silence, no metadata). The tags are
then written with each format's *own* field names (ID3 frames, APEv2 items,
ASF attributes, MP4 atoms, Vorbis comments), not through Codetta, so the tests
check that Codetta reads what other software writes. DSF is written by hand
(ffmpeg can't create it); it's a very simple container.

Run from the project root:  .venv/bin/python tests/fixtures/make_more_fixtures.py
"""

import struct
import subprocess
from pathlib import Path

from mutagen.aiff import AIFF
from mutagen.apev2 import APEv2
from mutagen.asf import ASF
from mutagen.dsf import DSF
from mutagen.id3 import TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggflac import OggFLAC
from mutagen.oggspeex import OggSpeex
from mutagen.trueaudio import TrueAudio
from mutagen.wave import WAVE

HERE = Path(__file__).parent
T = {"title": "Test Track", "artist": "Coda Tester", "album": "Fixture Album", "albumartist": "Coda Collective",
     "genre": "Test", "date": "2024", "track": "3/12", "disc": "1/2"}


def ffmpeg(name: str, *args: str, rate: str = "44100") -> Path:
    out = HERE / name
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"anullsrc=r={rate}:cl=mono", "-t", "1", "-map_metadata", "-1",
                    "-fflags", "+bitexact", *args, str(out)], check=True)
    return out


def id3(audio) -> None:
    if audio.tags is None:
        audio.add_tags()
    for frame in (TIT2(encoding=3, text=T["title"]), TPE1(encoding=3, text=T["artist"]),
                  TALB(encoding=3, text=T["album"]), TPE2(encoding=3, text=T["albumartist"]),
                  TCON(encoding=3, text=T["genre"]), TDRC(encoding=3, text=T["date"]),
                  TRCK(encoding=3, text=T["track"]), TPOS(encoding=3, text=T["disc"])):
        audio.tags.add(frame)
    audio.save()


def vorbis(audio) -> None:
    audio.tags.update({"TITLE": T["title"], "ARTIST": T["artist"], "ALBUM": T["album"],
                       "ALBUMARTIST": T["albumartist"], "GENRE": T["genre"], "DATE": T["date"],
                       "TRACKNUMBER": T["track"], "DISCNUMBER": T["disc"]})
    audio.save()


def dsf(path: Path) -> Path:
    """A valid one-second mono DSD64 file of digital silence."""
    block, channels, rate = 4096, 1, 2822400
    blocks = -(-rate // 8 // block)  # whole 4096-byte blocks covering one second
    data = b"\x69" * (block * blocks * channels)  # 0x69 is DSD silence
    fmt = struct.pack("<4sQIIIIIIQII", b"fmt ", 52, 1, 0, 1, channels, rate, 1, rate, block, 0)
    data_chunk = struct.pack("<4sQ", b"data", 12 + len(data)) + data
    total = 28 + len(fmt) + len(data_chunk)
    header = struct.pack("<4sQQQ", b"DSD ", 28, total, 0)
    path.write_bytes(header + fmt + data_chunk)
    return path


# ID3 family
id3(WAVE(ffmpeg("sample.wav", "-c:a", "pcm_s16le")))
id3(AIFF(ffmpeg("sample.aiff", "-c:a", "pcm_s16be")))
id3(TrueAudio(ffmpeg("sample.tta", "-c:a", "tta")))
id3(MP3(ffmpeg("sample.mp2", "-c:a", "mp2", "-b:a", "64k", "-f", "mp2")))
id3(DSF(dsf(HERE / "sample.dsf")))

# APEv2 (WavPack)
path = ffmpeg("sample.wv", "-c:a", "wavpack")
ape = APEv2()
ape.update({"Title": T["title"], "Artist": T["artist"], "Album": T["album"], "Album Artist": T["albumartist"],
            "Genre": T["genre"], "Year": T["date"], "Track": T["track"], "Disc": T["disc"]})
ape.save(path)

# ASF (WMA)
wma = ASF(ffmpeg("sample.wma", "-c:a", "wmav2", "-b:a", "64k"))
wma.tags.update({"Title": [T["title"]], "Author": [T["artist"]], "WM/AlbumTitle": [T["album"]],
                 "WM/AlbumArtist": [T["albumartist"]], "WM/Genre": [T["genre"]], "WM/Year": [T["date"]],
                 "WM/TrackNumber": [T["track"]], "WM/PartOfSet": [T["disc"]]})
wma.save()

# MP4 audiobook
m4b = MP4(ffmpeg("sample.m4b", "-c:a", "aac", "-b:a", "32k", "-f", "ipod"))
m4b.add_tags() if m4b.tags is None else None
m4b.tags.update({"\xa9nam": [T["title"]], "\xa9ART": [T["artist"]], "\xa9alb": [T["album"]],
                 "aART": [T["albumartist"]], "\xa9gen": [T["genre"]], "\xa9day": [T["date"]],
                 "trkn": [(3, 12)], "disk": [(1, 2)]})
m4b.save()

# Vorbis comments in Ogg: FLAC and Speex
vorbis(OggFLAC(ffmpeg("sample.oga", "-c:a", "flac", "-f", "ogg")))
vorbis(OggSpeex(ffmpeg("sample.spx", "-c:a", "libspeex", "-f", "ogg", rate="16000")))

for f in sorted(HERE.glob("sample.*")):
    print(f"{f.name:14} {f.stat().st_size:>7} bytes")
