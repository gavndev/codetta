"""albums.json + covers for hero.html, from a library made by build_library.py.
Usage: python hero_data.py <work-folder>   (the folder holding music/ and covers/)."""
import json, shutil, sys
from pathlib import Path
from mutagen.flac import FLAC

work = Path(sys.argv[1]); out = work / "hero"; (out / "c").mkdir(parents=True, exist_ok=True)
ORDER = ["Rumours", "ICEMAN", "Ys", "Vespertine", "closed captions", "Blond", "Intiha", "psykotic",
         "The Real Me", "In Rainbows", "In My Mind", "Cardinal"]
albums = []
for first in sorted(work.glob("music/*/*/01 *.flac")):
    a = FLAC(first); rg = a["musicbrainz_releasegroupid"][0]
    shutil.copy(work / "covers" / f"{rg}.jpg", out / "c" / f"{rg}.jpg")
    albums.append({"t": a["album"][0], "a": a["albumartist"][0], "y": a["date"][0][:4], "c": f"c/{rg}.jpg"})
albums.sort(key=lambda x: ORDER.index(x["t"]) if x["t"] in ORDER else 99)
json.dump(albums, open(out / "albums.json", "w"), ensure_ascii=False)
print(len(albums), "albums ->", out)
