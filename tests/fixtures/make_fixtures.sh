#!/usr/bin/env bash
# Regenerates the tiny sample audio files used by the test suite.
# Each file is ~1 second of silence carrying the same known set of tags.
# Requires ffmpeg (with libmp3lame, libvorbis, libopus). Run from anywhere:
#   bash tests/fixtures/make_fixtures.sh
set -euo pipefail
cd "$(dirname "$0")"

SRC=(-f lavfi -i "anullsrc=r=44100:cl=mono" -t 1)
TAGS=(
  -metadata title="Test Track"
  -metadata artist="Coda Tester"
  -metadata album="Fixture Album"
  -metadata album_artist="Coda Collective"
  -metadata genre="Test"
  -metadata date="2024"
  -metadata track="3/12"
  -metadata disc="1/2"
)
FF=(ffmpeg -hide_banner -loglevel error -y)

"${FF[@]}" "${SRC[@]}" "${TAGS[@]}" -c:a flac sample.flac
"${FF[@]}" "${SRC[@]}" "${TAGS[@]}" -c:a libmp3lame -b:a 32k -id3v2_version 4 sample.mp3
"${FF[@]}" "${SRC[@]}" "${TAGS[@]}" -c:a aac -b:a 32k sample.m4a
"${FF[@]}" "${SRC[@]}" "${TAGS[@]}" -c:a libvorbis -q:a 0 sample.ogg
"${FF[@]}" "${SRC[@]}" "${TAGS[@]}" -c:a libopus -b:a 16k sample.opus

# A file with no tags at all, to check the "empty" case.
"${FF[@]}" "${SRC[@]}" -map_metadata -1 -fflags +bitexact -c:a flac untagged.flac

ls -la sample.* untagged.flac

# Tiny cover images for album art tests.
"${FF[@]}" -f lavfi -i "color=c=0x3b8cff:s=64x48" -frames:v 1 -q:v 5 cover.jpg
"${FF[@]}" -f lavfi -i "color=c=0xff6b3b:s=32x32" -frames:v 1 cover.png

# WAV, AIFF, DSF, TrueAudio, MP2, WavPack, WMA, M4B, Ogg FLAC and Speex:
# .venv/bin/python tests/fixtures/make_more_fixtures.py
