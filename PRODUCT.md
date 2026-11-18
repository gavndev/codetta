# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Home-server ("homelab") owners who keep their own music library on their own
server and listen through Navidrome or another OpenSubsonic/Jellyfin/Plex-style
player. They care about a tidy library (right titles, artists, albums, covers,
credits) and want granular control over it, without moving files around.

They use Codetta on **desktop and phone equally**: long batch sessions cleaning
up albums at a computer, and quick fixes from the phone (often over Tailscale,
from the couch, right after a download). Neither screen is secondary.

The maintainer is one of these users; Codetta started as his hobby project.

## Product Purpose

A self-hosted web app that runs next to the music on the server and lets you
fix tags and album art from any browser: one track, a selection, a whole folder
or search results across the whole library. Changes are written safely to the
files themselves, and music apps pick them up on their next scan.

Success: a messy download or album becomes correctly tagged in a minute,
from whichever device is at hand, with full confidence nothing gets damaged.

## Positioning

- Runs on your own server, used from any browser, designed for the phone as
  much as the desktop (Picard and beets are desktop/terminal tools).
- Safe by design: every write goes to a temporary copy, is verified, then
  atomically swapped in; undo/redo from the activity log survives restarts;
  Codetta never renames, moves or deletes files.
- Built around what Navidrome actually shows (credits, mood, label, release
  type, multiple artists, sort and classical fields, lyrics), stored where
  MusicBrainz Picard puts them.
- Private and offline: no CDNs, no tracking, bundled fonts. Outside requests
  are only the optional update check and "Find lyrics" when pressed.

## Operating Context

- Deployed with Docker on a home server (Intel/AMD or ARM, including
  Raspberry Pi 4 class hardware); reached on the home network or over
  Tailscale; sometimes behind a reverse proxy with HTTPS.
- Libraries from a few hundred to tens of thousands of tracks; one folder is
  loaded at a time, search uses a background index.
- Typical sessions: fix a loose download (presets), clean up an album (Save to
  folder), add covers, fetch lyrics, check results in the music player after a
  rescan. Sign-in screen first on each new device.
- Used in Safari on iPhone (all iOS browsers are WebKit, including Brave),
  and desktop Chromium, Firefox and Safari; light and dark themes follow the
  device.

## Capabilities and Constraints

- Edits tags and embedded art on 15 file types (FLAC, MP3, M4A/M4B, Ogg Vorbis,
  Opus, Ogg FLAC, Speex, WAV, AIFF, DSF, TrueAudio, MP2, WavPack, WMA).
- Features: batch editing, Save to folder, smart suggestions, copy & paste tags,
  Tag Presets with preview, tag filter, library-wide tag search, activity log
  with undo/redo, lyrics (plain and synced, Find lyrics via LRCLIB), sort and
  classical fields, Advanced mode raw tag view, profile picture, sign-in.
- Technical: FastAPI backend; front end is plain HTML/CSS/JavaScript with no
  framework, no build step and no CDNs; fonts and icons must be bundled and
  under a licence that allows redistribution (e.g. SIL OFL).
- Strict Content Security Policy: no inline scripts or event-handler
  attributes.
- Mobile: 16px inputs (no zoom on focus), safe-area insets, 44px touch targets.
- Light, dark and system themes; motion must respect reduced-motion settings.
- One account per instance; alpha software (v0.2.0).

## Brand Commitments

- Name: **Codetta** (binding).
- Voice: plain, friendly and precise; says what will happen ("Save to 5
  tracks"), no jargon (binding).
- The small footer: GitHub link · Made with ♥︎ · version (binding).
- Free to change: the logo (the current coda-sign mark is not binding), colours,
  typeface and the whole visual language.
- The project is openly AI-assisted; the README says so.

## Evidence on Hand

- Real product, running; demo library of made-up artists and generated covers
  for screenshots and GIFs (build scripts in the maintainer's scratch tools,
  library in `~/.cache/codetta-media`).
- Docs: `README.md`, `docs/` (install, configuration, features, FAQ),
  `CHANGELOG.md`, `SECURITY.md`.
- Comparison with MusicBrainz Picard, beets and Metadata Remote in the README.
- No users counted, no testimonials, no press, no logos of others. Never invent
  them.

## Product Principles

1. Never put the user's files at risk; confidence is part of the experience.
2. Equal care for phone and desktop; the quick fix and the long session.
3. Show exactly what will change before anything is written.
4. Respect the homelab: light on resources, private, offline, self-contained.
5. Speak plainly; the music and the user's library are the subject, not the app.

## Accessibility & Inclusion

WCAG 2.2 AA: readable contrast in light and dark themes, full keyboard use,
visible focus, screen-reader labels, reduced motion respected, 44px touch
targets on phones. Text in any script (CJK, Devanagari, Thai, Arabic and other
right-to-left scripts, emoji) displays correctly.
