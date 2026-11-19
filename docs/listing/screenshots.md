[← Listing kit](README.md)

# Remaking the screenshots

The screenshots in [`../screenshots/`](../screenshots) show a library of real albums: real tags
from MusicBrainz and covers from the Cover Art Archive, with silent audio files standing in for
the music. Nothing here is committed except the scripts in [`kit/`](kit); the albums are fetched
fresh each time (at MusicBrainz's one-request-a-second pace).

You need `ffmpeg`, the dev environment (`source .venv/bin/activate`) and
[uv](https://docs.astral.sh/uv/) for Playwright. Work in a scratch folder, `$W` below.

1. **Build the library** (12 albums plus a messy `Downloads` folder for Actions and Library health):

   ```sh
   python docs/listing/kit/build_library.py $W/music
   ```

   Then, for realism in the shots: give the three tracks shown in the editor real-sounding audio
   (two independent pink-noise channels, so FLAC reports about 1,000 kbps instead of 1 kbps), tag
   two *Rumours* tracks as "Rumours (2004 Remaster)" (a split album for Library health) and remove
   *Vespertine*'s covers. The messy `Downloads` MP3s are made the same way, with junk like
   "(Official Audio)" and "ft." in their titles.

2. **The hero** (logo, tagline, a wall of covers; light and dark):

   ```sh
   python docs/listing/kit/hero_data.py $W
   cp docs/listing/kit/hero.html src/codetta/web/static/fonts/schibsted-grotesk.woff2 \
      docs/brand/logo-light.svg docs/brand/logo-dark.svg $W/hero/
   uv run --no-project --with playwright python docs/listing/kit/shoot_hero.py $W/hero
   ```

   Save the PNGs as JPEG (quality 88) as `hero-light.jpg` / `hero-dark.jpg`: the Snap Store's
   limit is 2 MB per image.

   **The animated README header** (`docs/media/hero-{light,dark}.gif`, about 3 MB each): the
   covers drop in one by one, hold, and fade for the loop. 105 frames over 7 seconds, then a
   GIF with a palette built from whole frames (a palette from only the moving parts loses the
   teal logo square):

   ```sh
   mkdir $W/hero/f-light
   uv run --no-project --with playwright python docs/listing/kit/hero_frames.py $W/hero light 105
   ffmpeg -framerate 15 -i $W/hero/f-light/%04d.png -vf "scale=1200:-1:flags=lanczos,split[a][b];\
   [a]palettegen=max_colors=256:stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
     -loop 0 docs/media/hero-light.gif
   ```

   (A slow drift of the whole wall looks lovely but makes a 26 MB GIF: every frame is new pixels.)

3. **The app**: start Codetta on `$W/music` at port 8118 with a fresh config folder, create the
   account `alex` / `correct horse 1`, finish the setup steps (`POST /api/onboarding/<step>`) and
   turn MusicBrainz on (`PUT /api/connections`), then:

   ```sh
   uv run --no-project --with playwright python docs/listing/kit/shoot_app.py <out-folder>
   ```

   It takes 12 shots: sign-in, library (light/dark), Library health, album and editor
   (light/dark), search, Actions and the phone album and editor.
