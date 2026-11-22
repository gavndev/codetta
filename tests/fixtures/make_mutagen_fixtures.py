"""Samples for Monkey's Audio (.ape), Musepack (.mpc) and DSDIFF (.dff).

ffmpeg can't create these formats, so the audio comes from mutagen's own test files
(https://github.com/quodlibet/mutagen, GPL-2.0-or-later): mac-399.ape, click.mpc and
5644800-2ch-s01-silence.dff, each a fraction of a second long. The usual test tags are then
written in each format's own way (APEv2 items, ID3 frames), not through Codetta.

    pip download --no-deps --no-binary :all: mutagen -d /tmp/m && tar xzf /tmp/m/mutagen-*.tar.gz -C /tmp/m
    .venv/bin/python tests/fixtures/make_mutagen_fixtures.py /tmp/m/mutagen-*/tests/data
"""

import shutil
import sys
from pathlib import Path

from mutagen.apev2 import APEv2
from mutagen.dsdiff import DSDIFF
from mutagen.id3 import TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK

HERE = Path(__file__).parent
T = {"title": "Test Track", "artist": "Coda Tester", "album": "Fixture Album", "albumartist": "Coda Collective",
     "genre": "Test", "date": "2024", "track": "3/12", "disc": "1/2"}
SOURCES = {"sample.ape": "mac-399.ape", "sample.mpc": "click.mpc", "sample.dff": "5644800-2ch-s01-silence.dff"}

data = Path(sys.argv[1])
for name, src in SOURCES.items():
    shutil.copyfile(data / src, HERE / name)

for name in ("sample.ape", "sample.mpc"):
    ape = APEv2()
    ape.update({"Title": T["title"], "Artist": T["artist"], "Album": T["album"], "Album Artist": T["albumartist"],
                "Genre": T["genre"], "Year": T["date"], "Track": T["track"], "Disc": T["disc"]})
    ape.save(HERE / name)

dff = DSDIFF(HERE / "sample.dff")
dff.add_tags()
for frame in (TIT2(encoding=3, text=T["title"]), TPE1(encoding=3, text=T["artist"]), TALB(encoding=3, text=T["album"]),
              TPE2(encoding=3, text=T["albumartist"]), TCON(encoding=3, text=T["genre"]), TDRC(encoding=3, text=T["date"]),
              TRCK(encoding=3, text=T["track"]), TPOS(encoding=3, text=T["disc"])):
    dff.tags.add(frame)
dff.save()

for f in SOURCES:
    print(f"{f:12} {(HERE / f).stat().st_size:>7} bytes")
