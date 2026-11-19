[← Back to the README](../../README.md)

# Listing kit

Ready-to-paste answers for listing Codetta on AlternativeTo and similar
directories. Everything here is true of the released app; keep it that way when
features change. Screenshots are in [`../screenshots/`](../screenshots), the icon
is [`src/codetta/web/static/icons/codetta.png`](../../src/codetta/web/static/icons/codetta.png)
(512 × 512; SVG beside it).

## AlternativeTo

**Name:** Codetta

**Website:** https://github.com/gavndev/codetta

**Short description** (one line):

> A private, self-hosted music library manager: fix tags, match albums on MusicBrainz, and batch edit, rename and organize files from any browser, including your phone.

**Full description:**

> Codetta looks after a local music library (FLAC, MP3, M4A, OGG, Opus, WAV, AIFF, WMA and more, 15 file types) from your browser. Run it on a home server with Docker, or on your own computer (Linux, macOS) with `pipx install codetta`, and open it on your laptop or phone.
>
> Edit tags for one track or a whole album at once, add cover art, and match albums on MusicBrainz (optionally by audio fingerprint) with a review of every change before anything is written. Batch tools include Find & replace in tags (with regex), one-tap tidy-ups like "Clean up titles" and Title Case, Tag Presets, and Organize, which renames and moves files into folders from their tags with a preview. An inbox matches and files new downloads, Library health finds missing covers, missing tags and duplicates, and search covers the whole library by tag.
>
> Every write goes through a temporary copy that is checked before it replaces the original, and every change can be undone from the activity log, even after a restart. Codetta has sign-in built in, keeps no access log, has no tracking, analytics or ads, and makes no internet connection until you switch on an online feature. It works fully offline. Plugins add your own actions. Light and dark themes follow your device. Open source under the AGPL-3.0.

**License:** Open source (AGPL-3.0)

**Pricing:** Free

**Platforms:** Self-Hosted, Linux, Mac, Docker, Online (web app), Python (PyPI: `pipx install codetta`). Add Windows once it's tested there.

**Categories / tags:** Music tag editor, Music organizer, Audio metadata, MusicBrainz, Self-hosted, Homelab, Navidrome companion.

**Alternative to:** MusicBrainz Picard, beets, Mp3tag, Metadata Remote, puddletag, Kid3, MediaMonkey (library tools), Lidarr (for tagging and filing, not downloading).

**Feature boxes** and why each is true:

| Box | Why |
|---|---|
| Open source | AGPL-3.0, on GitHub |
| Self-Hosted | Runs on your server (Docker) or your own computer |
| Docker | Official multi-arch image `ghcr.io/gavndev/codetta` (Intel/AMD + ARM) |
| Online | It's a web app, used from any browser |
| No tracking | No analytics, telemetry or tracker code; `tests/test_privacy.py` checks it; [PRIVACY.md](../../PRIVACY.md) |
| Privacy focused | Offline until you opt in, no access log, sessions keep no IP or device |
| Lightweight | ~100 MB image, ~70 MB memory (130 MB at 100,000 tracks), idle = no CPU or disk |
| Ad-free | No ads, ever |
| Dark mode | Light, dark or follow the device |
| Works offline | Everything except the opt-in online lookups (MusicBrainz, AcoustID, LRCLIB, update check) |
| Batch editing | Multi-track editor, Find & replace, Actions, Tag Presets, Save to folder |
| Batch rename files | Organize: rename and move by tag pattern, preview, one undo |
| MP3/ID3 renaming | Same, from ID3 (and every other format's) tags |
| File tagging | The core of the app |
| Lossless audio | FLAC, ALAC (M4A), WAV, AIFF, WavPack, TTA, DSD (DSF) |
| Extensible by plugins | [Plugin API](../plugins.md): actions on tracks, off until enabled |
| Support for themes | Light and dark themes. Only tick this if the site counts light/dark as themes; there are no custom themes |

**Screenshots** (upload in this order):

1. `album-light.png`: an album, booklet style
2. `editor-light.png`: the tag editor beside the album
3. `actions.png`: Actions previewing "Clean up titles"
4. `health.png`: Library health
5. `search.png`: search by tag across the library
6. `album-dark.png`: dark theme
7. `phone-album.png`, `phone-editor.png`: on a phone

## Other directories

- **selfh.st apps** (https://selfh.st/apps/): name, the short description above, GitHub link, AGPL-3.0, Docker. Icon request already open: https://github.com/selfhst/icons/discussions/1098.
- **awesome-selfhosted** (Media Management section). Their rule is a first release at least 4 months old: 0.1.0 came out on 2026-11-17, so submit from 2027-03-17. The entry line:

  ```
  - [Codetta](https://github.com/gavndev/codetta) - Web-based music library manager: tag editing, MusicBrainz matching, batch rename and organize, import inbox. ([Source Code](https://github.com/gavndev/codetta)) `AGPL-3.0` `Python/Docker`
  ```
- **r/selfhosted** post: lead with the album/editor screenshots and the phone shots, link the README, say it's alpha and AI-assisted (as the README does).
- **dashboardicons.com**: submit the three SVGs in [`../brand/dashboard-icons/`](../brand/dashboard-icons) through their web form.
