# Changelog

All notable changes to Codetta. Versions follow [Semantic Versioning](https://semver.org/).

## 0.6.1 (2026-11-18)

- **Fixed:** on phones, the notifications panel and pop-ups ran off the left edge of the screen (the bell moved in from the edge with 0.6.0's new top bar). They now always stay on screen, and are a little more compact on phones.

## 0.6.0 (2026-11-18)

- **Soulseek through slskd** (Level Up #3): a new connection for people who run [slskd](https://github.com/slskd/slskd). Type `!slskd` in the search bar and it becomes a **slskd** chip: what you type next is searched on Soulseek (`*` works as a wildcard for filtered names, like `*-Pain`). Or press **Find in slskd** on an album to fill the search bar with its artist and album, ready to edit. Codetta picks the best copy (lossless first by default, then free upload slots, queue and speed), downloads it into your inbox, moves on to the next copy if one fails or stalls, and asks before it joins your library: **Import**, **Blocklist & try next**, or **Choose another**. A download from an album's button replaces that album (the old copy is kept so Activity can undo it). Turn off *Review each download* to let exact MusicBrainz matches file themselves. Set it up in the new setup step or **Account → Connections**; Codetta warns you if slskd isn't sharing a folder, since Soulseek users often refuse people who share nothing. `CODETTA_SLSKD`, `CODETTA_SLSKD_URL`, `CODETTA_SLSKD_API_KEY`.
- **A roomier top bar on phones:** the tools sit beside the logo and the search bar gets its own full-width row, with a **Cancel** button that slides in while you use it (like iOS). On computers the search bar widens while you use it.
- The Inbox's **Soulseek** and **Settings** are proper buttons now.
- **Download progress:** an album that's still arriving in the inbox shows a progress bar with how many files are in and roughly how long the rest will take (from slskd, for anything downloading there, started from Codetta or not). Soulseek downloads in the Soulseek sheet show the time left too.
- **README:** rewritten for what Codetta is now: find, import, match, fix and file your music, with an updated comparison table and FAQ.

## 0.5.0 (2026-11-18)

- **Import inbox** (Level Up #2): pick the folder new music lands in (downloads, rips). Codetta groups it into albums (disc folders join their album; loose tracks are one item each), finds each on MusicBrainz (by tags, then by sound if AcoustID is on), and files it into your library: MusicBrainz tags + your Organize pattern, each an undoable activity entry. Confident matches show "Ready to file" (or file themselves if you allow it); the rest wait for a review in the familiar match dialog. Albums already in your library are never overwritten. Inbox button in the top bar with a count; optional check every 15 minutes (off by default so idle disks can sleep). The inbox can be a folder outside your music folder: mount your downloads (e.g. slskd's) at `/inbox` (or set `CODETTA_INBOX_DIR`); files are copied across, checked, then removed from the downloads folder. Albums that are still arriving wait until their files have been still for 2 minutes.
- **Easier setup:** after creating your account, a few short steps: online features, how your folders should be named, and where new music arrives. Each is skippable and changeable later. Existing installs see only the new steps, once.
- **What's new:** this changelog in the app. It pops up once after setup and after each update, and there's a "What's new" link in the footer, in Account, and on the sign-in screen.
- **Now playing:** a pill grows out of a circle at the bottom of the screen while a track plays: cover (turning like a record), title, artist, time, play/pause, stop, and a thin line you can drag to seek. Music keeps playing while you browse; tap the title to jump back to its album.
- **Notifications:** a bell next to your account picture. Things Codetta does in the background (the inbox finished looking things up, an album filed itself, a new version is out) pop out of the bell for a few seconds, and the bell keeps the list. Tap one to go straight there.
- **Fixed:** an album's genre chip only showed the first genre when genres were separated with ";". It now lists every genre, separated by commas, however the file separates them (";", ",", "|" or separate values).

- **Organize** (Level Up #1): rename and move files into folders from their tags with a pattern like `{albumartist|artist}/{album}[ ({year})]/{disctrack} {title}`. Presets, one-tap tag buttons and a live example; a preview of every move before anything happens. Names are made safe for any filesystem or network share, nothing is ever overwritten (conflicts are listed instead), lyrics files and the album's cover, booklet and scans move along, and emptied folders are tidied away. One undoable entry in the activity log. Files without artist/album tags are flagged before they'd land in "Unknown Artist".

- **Play a track** from the list: a play button at the end of every row (it grows to "Play" when you point at it). Plays the file straight from your server, with seeking and lock-screen/headphone controls. Nothing is converted or cached; formats your browser can't play (WMA, DSF, WavPack…) get no button.
- **Multi-disc albums** read like a streaming service: a "Disc 2" line (with the disc subtitle) between discs, tracks grouped by disc, and pointing at a row shows "2/01". The disc icon spins when you point at it, and slowly while that disc is playing.

## 0.4.1 (2026-11-18)

- The dashboard icons (`/static/icons/`) are now included in the Docker image (0.4.0 left them out).

## 0.4.0 (2026-11-18)

- **Offline unless you opt in.** Online features are now *connections*, all off until you choose. After creating your account (or on first start after upgrading) a welcome card asks: stay offline, or turn on online features, with a switch for each one saying exactly what it sends and where. Change them any time in **Account → Connections**. `CODETTA_MUSICBRAINZ`, `CODETTA_LYRICS_LOOKUP` and `CODETTA_UPDATE_CHECK` (`on`/`off`) lock a switch from your compose file; `CODETTA_OFFLINE=on` blocks them all.
- **Changed:** Find lyrics and the update check used to be on by default. They're now off until you turn them on (the welcome card offers this once).
- **Match on MusicBrainz:** find the release for an album folder (or selected tracks) by its tags or a pasted musicbrainz.org link, compare editions (year, country, format, label, catalog number, track count, match score), then review a per-file preview before writing. Files are paired with tracks by disc/track number, then title and length, and any pairing can be changed. Choose the fields (titles, credits from recording and work relationships, release details, sort names, MusicBrainz IDs and ISRCs, genres), replace or only fill empty tags, and add cover art from the Cover Art Archive. One activity entry, undoable as a whole (tags and cover together). Respects MusicBrainz's one-request-a-second limit; `CODETTA_MUSICBRAINZ_URL` points it at your own mirror.
- **Identify by sound (AcoustID):** a new connection that recognises tracks by their audio, even untagged ones. In the match dialog, **Listen** fingerprints each file on your server with Chromaprint's `fpcalc` and sends only those codes and track lengths to AcoustID. Releases holding most of your tracks are offered first ("9 of your 10 tracks are on it"), and files pair with their exact recordings. The Docker image now includes Chromaprint's official static `fpcalc` (about 9 MB, checksum-verified). `CODETTA_ACOUSTID`, `CODETTA_ACOUSTID_KEY`, `CODETTA_FPCALC`.
- MusicBrainz IDs (release, release group, recording, release track, artist, album artist, work) and `script` are stored the way Picard writes them in every format, including M4A and WMA.
- **Find in MusicBrainz** button on album pages, beside the genre (phones: "Find", first in the action row), with a MusicBrainz-coloured edge that shifts and glows on hover.
- **Dashboard icons:** the Codetta icon in full colour, light (for dark dashboards) and dark (for light dashboards), as SVG, PNG and WebP, served at `/static/icons/` so Homepage, Homarr or Dashy can point straight at them.
- Account → Connections opens and closes (the closed row says what's on), and the sound lookup button reads **Listen** → **Listening…** while it works.
- With sign-in turned off, the account button now opens Settings, so connections and Advanced mode stay reachable.

## 0.3.1 (2026-11-18)

- The browser tab and home-screen icon now update to the new logo right away (they were being kept from the browser's cache).

## 0.3.0 (2026-11-18)

- A new look, "liner notes": Codetta now reads like the credits pages of a CD or LP booklet. New lowercase wordmark and icon, the Schibsted Grotesk typeface (bundled), booklet-white and booklet-black themes, and ink rules and hairlines instead of boxes.
- Each album lends Codetta a colour picked from its cover (adjusted for readable contrast), used for the active track, changed fields, section heads and the logo's square, crossfading as you move between albums.
- Album folders open as a booklet spread: large cover, album title, artist, year, track count and total runtime, and a genre chip. Columns that would repeat the same value on every row (album, artist, format, cover) are left out; phones show track numbers.
- The editor reads like a credits sheet: labels beside values on hairlines, with the field box appearing when you point at or edit it.
- Sign-in is a clean title page; the folder grid is a contents page; phones show one back link instead of a cramped breadcrumb.
- Accessibility: text on coloured fills switches to dark in dark mode for readable contrast; checkmarks are drawn icons.

## 0.2.0 (2026-11-17)

- 10 more formats: WAV, AIFF, DSF (DSD), TrueAudio, MP2, WavPack, WMA, M4B audiobooks, Ogg FLAC and Speex, with album art and every editor field on each. Codetta now handles 15 file types.
- Sort names (title, artist, album, album artist, composer) and classical fields (work, movement, movement number and count, show movement) plus subtitle, stored where Picard puts them in every format.
- Advanced mode (account menu): a Raw tags section in the editor lists every stored field exactly as the file has it (ID3 frames, MP4 atoms, Vorbis comments, APEv2 items, WMA attributes, pictures). Read-only.
- Lyrics: plain or synced (LRC) in a roomy editor box with a "Synced lyrics · 42 timed lines" hint; stored where players look (Vorbis LYRICS, ID3 USLT, MP4 ©lyr, APE Lyrics, WM/Lyrics). Long values are shortened in the activity log (undo still restores the full text).
- Find lyrics: looks the track up on LRCLIB (only when you press it, sending artist, title, album and length), shows a preview, and offers synced or plain lyrics as an unsaved change. `CODETTA_LYRICS_LOOKUP=off` hides it. First of Codetta's online providers (MusicBrainz and Last.fm will follow the same pattern).

## 0.1.1 (2026-11-17)

- README rewritten as a short landing page; details moved to `docs/` (install, configuration, features, FAQ), plus `SECURITY.md` and `CONTRIBUTING.md`.
- README: an honest comparison with MusicBrainz Picard, beets and Metadata Remote.
- A quiet footer on the sign-in screen and under the track list: GitHub link · Made with ♥︎ · version.

## 0.1.0 (2026-11-17)

First release.

- Edit tags on FLAC, MP3, M4A, OGG Vorbis and Opus files, one track or many at once.
- Navidrome / OpenSubsonic tag set (credits, mood, label, release type, multiple artists…), stored the way MusicBrainz Picard does.
- Save to folder, copy & paste tags, smart suggestions from the folder, and hints for dates and multi-value fields.
- Album art: add, replace or remove embedded covers as part of a save, for one track, a selection or the whole folder; thumbnails on every track row.
- Tag Loadouts with placeholders and a preview before writing.
- Filter a folder by tag; folders as a list (default) or grid.
- Works with any language: every script and emoji round-trips exactly; accent-insensitive search; right-to-left names display correctly; sorting ignores case and accents; file names that aren't valid UTF-8 are skipped with a note instead of breaking the folder; emoji get a gentle tip, never a block; commas in names (e.g. "Tyler, The Creator") are never flagged.
- Comma-separated genres and moods ("Hip-Hop, Trap, Rap", as Navidrome splits them by default) are saved as typed and filter by each part.
- Activity log of every change, with old and new values, and undo/redo straight from the log (files edited again since are left alone).
- Safe writes: temporary copy, verify, atomic swap; symlinks, hard links, permissions and cover art preserved.
- Sign-in with hashed passwords, 30-day sessions, lockout and password reset from the server.
- Profile pictures: a round photo of your choice in the top bar and account menu (JPEG, PNG, WebP, GIF, AVIF, and HEIC on iPhone/Safari).
- Version shown on the sign-in screen and account menu, with a check for new releases.
- Large folders stay fast: a 2,000-track folder opens in under a second and filters in a quarter of a second; a shared album cover downloads once.
- Simultaneous saves to the same file (two devices, a double-tap) can no longer lose an edit.
- Security hardening: strict Content Security Policy and security headers, cross-site request protection, request size limits, album art only ever served as an image, stronger password hashing (upgraded automatically at sign-in), optional `CODETTA_ALLOWED_HOSTS`.
- Search your whole library by tag: `genre: rap, hip-hop`, `artist: drake`, `year: 2024`, or plain words. Commas mean "or", and matching is word-aware ("rap" doesn't find "Trap") and accent-insensitive. Results can be selected and edited like a folder. Backed by a small index in the config folder that updates in the background and right after every edit.
- Ready-made Docker image for Intel/AMD and ARM servers: `ghcr.io/gavndev/codetta`. Install with one compose file, update with `docker compose pull`.
- The container runs as your user, with a health check and read-only filesystem.
- Small footprint: a ~100 MB image (Alpine), ~70 MB of memory, a search index of about 2 KB per track, and no background disk activity when idle (the library is re-checked when you search, at most every 15 minutes), so hard drives can spin down. No per-request access log filling up Docker's logs.
- First-run setup only works from home networks, Tailscale or the server itself (`CODETTA_ALLOW_PUBLIC_SETUP` to override), so nobody on the internet can claim a fresh install.
- Requests are bounded (at most 1,000 files and 100,000 characters per tag value), and a file listed twice in one request is edited once. Big Save to folder jobs are sent in batches automatically.
- On desktop, the selection bar and notifications no longer cover the editor's activity log when the editor is open.
- On phones, value suggestions for half-width fields (Genre, Disc) are wide enough to read.
