# Changelog

All notable changes to Codetta. Versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

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
