# Coda: Granular Master Development Plan

## Phase 1: Core Metadata Engine & Unit Tests
- [x] **Task 1.1:** Set up directory tree (`src/coda/core`, `src/coda/web`, `src/coda/cli`, `tests`, `config`), `.venv`, `.gitignore`, and `pyproject.toml` (`mutagen`, `fastapi`, `uvicorn`, `pytest`), then install dependencies.
- [x] **Task 1.2:** Build `src/coda/core/engine.py` with `MetadataEngine.load_metadata()` to safely read tags from FLAC, MP3, M4A/AAC, OGG Vorbis, and Opus. Generate tiny sample audio files in `tests/fixtures/` (via `ffmpeg`) and write read tests in `tests/test_engine.py`.
- [x] **Task 1.3:** Build `MetadataEngine.update_tags()` to write modified tags back to audio files without corrupting them (write to a temp copy, then swap it in). Add write/round-trip tests for every format.
- [x] **Task 1.4:** Build `src/coda/core/presets.py` to handle JSON-based Tag Loadouts (pre-saved batch tag templates), stored in `config/`. Add tests in `tests/test_presets.py`.
- [x] **Task 1.5:** Add failure-case tests in `tests/test_safety.py` (corrupt/truncated/empty/mislabelled files, read-only files and folders, unsupported formats, unicode tags and filenames, cover art preservation, symlinks and hard links, disk-full and interrupted writes) proving that files are never damaged when something goes wrong.

## Phase 2: Web App & GUI
- [x] **Task 2.1:** FastAPI entry point `src/coda/web/app.py`: settings from env (`CODA_MUSIC_DIR`, `CODA_CONFIG_DIR`), path safety (no access outside the music folder), serves the UI at `/`.
- [x] **Task 2.2:** Library API: `GET /api/browse` (one folder at a time, so huge libraries stay fast; skips hidden `.coda-*` temp files), `GET /api/track`, `PATCH /api/tracks` (same changes to one or many files), `GET /api/fields` (tag vocabulary for the editor).
- [x] **Task 2.3:** Loadouts API: list/create/edit/delete, and apply to selected files or a folder with a dry-run preview.
- [x] **Task 2.4:** UI shell: self-hosted Inter font, light/dark/system theme, mobile-first responsive layout (iPhone safe areas, no zoom-on-focus), works the same in Safari/WebKit, Chromium, and Firefox. Plain HTML/CSS/JS, no build step, no CDNs.
- [x] **Task 2.5:** Library browser: breadcrumb navigation, folder list, track list with multi-select and filter.
- [x] **Task 2.6:** Tag editor panel: single and batch edits, Navidrome fields grouped (Basics, Credits, Release, More), multi-value tags, custom tags, shows "multiple values" for mixed selections.
- [x] **Task 2.7:** Loadouts UI: apply to selection or folder with a preview (fill vs. overwrite) before writing; create/edit/delete loadouts.
- [x] **Task 2.8:** API tests in `tests/test_api.py`; manual check on desktop and iPhone.
- [x] **Task 2.9:** Album art: rounded square at the top of the editor (preview, or "+ Add album art"); upload/replace/remove for one or many tracks, JPEG/PNG, drag-and-drop on desktop, photo picker on iPhone. Same safe temp-copy write as tags (`src/coda/core/artwork.py`).
- [x] **Task 2.10:** Activity log pinned to the bottom of the editor: every change (edits, art, loadouts) with old → new values and errors, saved to `activity.jsonl` in the config folder, live-updating across devices.
- [x] **Task 2.11:** Remember visited folders so navigating back is instant (refreshed quietly in the background), and restore scroll position.
- [x] **Task 2.12:** Editor toolbar: "Save" (this track/selection) and "Save to folder" (the changed fields to every track in the folder, with a warning for per-track fields like Title); copy checked tags and paste them onto other tracks or a whole folder; wider panel.
- [x] **Task 2.13:** Filter the current folder by tag value (e.g. Label = Independent), shown as removable chips. Hints for non-standard dates ("Use 2026-10-23") and comma-separated multi-value fields ("Split into 3").
- [x] **Task 2.15:** Smart suggestions: album-level fields (album, artist, genre, date, label, credits…) offer values from other tracks in the same folder in a dropdown; Track suggests the file's position ("2/6"). Picking fills the field without saving. Save buttons count changed fields, and hovering shows exactly what will change (old → new). Later: MusicBrainz as a second suggestion source.

## Phase 3: Docker & Sharing
- [ ] **Task 3.1:** Multi-stage `Dockerfile` on `python:3.14-slim`, running as a non-root user with configurable `PUID`/`PGID` so edited files keep the right owner.
- [ ] **Task 3.2:** `docker-compose.yml` with `/music` and `/config` volumes, port `8111` (8000 is taken by another service on the host), and a healthcheck.
- [ ] **Task 3.3:** `README.md`: what Coda is, screenshots, Docker setup, and a note on access (no login yet, so keep it on your LAN or behind a reverse proxy).

## Later (ideas, not scheduled)
- Fluid UI transitions (panel slide-in, list/folder changes, dialogs).
- Library-wide tag search/filter, backed by a cached tag index. Folder-level filtering covers current needs.
- MusicBrainz lookup as a second source of smart suggestions.
