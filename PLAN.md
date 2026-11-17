# Codetta: Granular Master Development Plan

## Phase 1: Core Metadata Engine & Unit Tests
- [x] **Task 1.1:** Set up directory tree (`src/codetta/core`, `src/codetta/web`, `src/codetta/cli`, `tests`, `config`), `.venv`, `.gitignore`, and `pyproject.toml` (`mutagen`, `fastapi`, `uvicorn`, `pytest`), then install dependencies.
- [x] **Task 1.2:** Build `src/codetta/core/engine.py` with `MetadataEngine.load_metadata()` to safely read tags from FLAC, MP3, M4A/AAC, OGG Vorbis, and Opus. Generate tiny sample audio files in `tests/fixtures/` (via `ffmpeg`) and write read tests in `tests/test_engine.py`.
- [x] **Task 1.3:** Build `MetadataEngine.update_tags()` to write modified tags back to audio files without corrupting them (write to a temp copy, then swap it in). Add write/round-trip tests for every format.
- [x] **Task 1.4:** Build `src/codetta/core/presets.py` to handle JSON-based Tag Loadouts (pre-saved batch tag templates), stored in `config/`. Add tests in `tests/test_presets.py`.
- [x] **Task 1.5:** Add failure-case tests in `tests/test_safety.py` (corrupt/truncated/empty/mislabelled files, read-only files and folders, unsupported formats, unicode tags and filenames, cover art preservation, symlinks and hard links, disk-full and interrupted writes) proving that files are never damaged when something goes wrong.

## Phase 2: Web App & GUI
- [x] **Task 2.1:** FastAPI entry point `src/codetta/web/app.py`: settings from env (`CODETTA_MUSIC_DIR`, `CODETTA_CONFIG_DIR`), path safety (no access outside the music folder), serves the UI at `/`.
- [x] **Task 2.2:** Library API: `GET /api/browse` (one folder at a time, so huge libraries stay fast; skips hidden `.codetta-*` temp files), `GET /api/track`, `PATCH /api/tracks` (same changes to one or many files), `GET /api/fields` (tag vocabulary for the editor).
- [x] **Task 2.3:** Loadouts API: list/create/edit/delete, and apply to selected files or a folder with a dry-run preview.
- [x] **Task 2.4:** UI shell: self-hosted Inter font, light/dark/system theme, mobile-first responsive layout (iPhone safe areas, no zoom-on-focus), works the same in Safari/WebKit, Chromium, and Firefox. Plain HTML/CSS/JS, no build step, no CDNs.
- [x] **Task 2.5:** Library browser: breadcrumb navigation, folder list, track list with multi-select and filter.
- [x] **Task 2.6:** Tag editor panel: single and batch edits, Navidrome fields grouped (Basics, Credits, Release, More), multi-value tags, custom tags, shows "multiple values" for mixed selections.
- [x] **Task 2.7:** Loadouts UI: apply to selection or folder with a preview (fill vs. overwrite) before writing; create/edit/delete loadouts.
- [x] **Task 2.8:** API tests in `tests/test_api.py`; manual check on desktop and iPhone.
- [x] **Task 2.9:** Album art: rounded square at the top of the editor (preview, or "+ Add album art"); upload/replace/remove for one or many tracks, JPEG/PNG, drag-and-drop on desktop, photo picker on iPhone. Same safe temp-copy write as tags (`src/codetta/core/artwork.py`).
- [x] **Task 2.10:** Activity log pinned to the bottom of the editor: every change (edits, art, loadouts) with old → new values and errors, saved to `activity.jsonl` in the config folder, live-updating across devices.
- [x] **Task 2.11:** Remember visited folders so navigating back is instant (refreshed quietly in the background), and restore scroll position.
- [x] **Task 2.12:** Editor toolbar: "Save" (this track/selection) and "Save to folder" (the changed fields to every track in the folder, with a warning for per-track fields like Title); copy checked tags and paste them onto other tracks or a whole folder; wider panel.
- [x] **Task 2.13:** Filter the current folder by tag value (e.g. Label = Independent), shown as removable chips. Hints for non-standard dates ("Use 2026-10-23") and comma-separated multi-value fields ("Split into 3").
- [x] **Task 2.15:** Smart suggestions: album-level fields (album, artist, genre, date, label, credits…) offer values from other tracks in the same folder in a dropdown; Track suggests the file's position ("2/6"). Picking fills the field without saving. Save buttons count changed fields, and hovering shows exactly what will change (old → new). Later: MusicBrainz as a second suggestion source.
- [x] **Task 2.16:** Fluid transitions: direction-aware folder navigation, editor slide-in (full-height sheet on phones), dialogs scale in/out with a fading backdrop, suggestion and changes popovers, rising selection bar and toasts, album art fade-in, theme crossfade. All quick (120–340 ms) and switched off with the system's Reduce Motion setting.

## Phase 3: Docker & Sharing
- [x] **Task 3.0:** Sign-in: first-run account setup (or `CODETTA_USERNAME`/`CODETTA_PASSWORD`), scrypt-hashed password, 30-day HttpOnly session cookies stored as hashes, lockout after repeated wrong passwords, account menu (change password signs out other devices, sign out), `python -m codetta.cli set-password` / `sign-out-all` for recovery, `CODETTA_AUTH=off` for reverse-proxy setups. Every API route except sign-in and `/api/health` requires a session.
- [x] **Task 3.1:** Multi-stage `Dockerfile` on `python:3.14-slim`, running as a non-root user with configurable `PUID`/`PGID` so edited files keep the right owner; `codetta-admin` for password resets; healthcheck. Built and smoke-tested on the home server (runs as 1000:1000 with no capabilities, healthy, read-only filesystem).
- [x] **Task 3.2:** `docker-compose.yml` with `/music` and `/config` volumes, port `8111` (8000 is taken by another service on the host), read-only container filesystem. Running on music-server at port 8111 with `/media/music` (server settings in `docker-compose.override.yml`).
- [x] **Task 3.3:** `README.md`: what Codetta is, screenshots, Docker setup, sign-in and password recovery, and HTTPS options (e.g. `tailscale serve` or a reverse proxy).

## Phase 4: Toward v0.1.0
- [x] **Task 4.1:** Folder list view by default (with counts of what's inside), grid as an option; content width capped on very wide screens.
- [x] **Task 4.2:** Version number on the sign-in screen and in the account menu; twice-daily check for new GitHub releases (`CODETTA_UPDATE_CHECK`), update dot on the account icon, release notes and copyable update commands. `CHANGELOG.md`.
- [x] **Task 4.3:** Undo (and redo) from the activity log for tag edits, album art and loadouts. Exact per-file before/after values are recorded; previous album art is kept in `config/undo-art/` (deduplicated, pruned when no longer referenced). Files changed since are skipped, never overwritten.
- [x] **Task 4.7:** Worldwide text: every script and emoji round-trips on every format (tested: Japanese, Hindi, Korean, Thai, Cantonese, Arabic, Tagalog, emoji incl. ZWJ/flags/skin tones, decomposed accents); accent- and case-insensitive search and sorting; right-to-left display; system font fallbacks for CJK, Devanagari, Thai and colour emoji; non-UTF-8 file names skipped with a note; emoji-only loadout names; no comma warnings at all. Accessibility pass to follow later.
- [ ] **Task 4.4:** Security review and code review.
- [ ] **Task 4.5:** Decide license; hide personal email in git history if wanted.
- [ ] **Task 4.6:** Publish: GitHub repo, CI (tests + image build), ready-made image, `v0.1.0` release.

## Phase 5: Rebirth (bugs and features from the review)
- [x] **Task 5.1:** Profile pictures: round photo replaces the person icon in the top bar; profile section in the account menu (change / remove; initial shown when empty). The browser crops to a square, scales to 256 px and uploads WebP (JPEG on older Safari); HEIC works wherever the browser can decode it (Safari, any iOS browser) with a clear message elsewhere. Stored per user in `config/avatars/`.
- [x] **Task 5.2:** Phones: selection circles are hidden until you tap **Select** (then tapping a track selects it; **Select all** / **Done**), like the Photos app. Desktop keeps always-visible checkboxes.

## Later (ideas, not scheduled)
- Library-wide tag search/filter, backed by a cached tag index. Folder-level filtering covers current needs.
- MusicBrainz plugin: match a file or folder to a MusicBrainz release/recording and offer its "official" metadata (titles, artists, dates, label, catalog number, MBIDs, cover art) to append to the matched tracks, previewed before writing, like loadouts. Also feeds smart suggestions.
- First-run welcome card after account creation: confirms the library was found and is writable, plus three quick tips.
