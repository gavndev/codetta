# Coda: Granular Master Development Plan

## Phase 1: Core Metadata Engine & Unit Tests
- [x] **Task 1.1:** Set up directory tree (`src/coda/core`, `src/coda/web`, `src/coda/cli`, `tests`, `config`), `.venv`, `.gitignore`, and `pyproject.toml` (`mutagen`, `fastapi`, `uvicorn`, `pytest`), then install dependencies.
- [x] **Task 1.2:** Build `src/coda/core/engine.py` with `MetadataEngine.load_metadata()` to safely read tags from FLAC, MP3, M4A/AAC, OGG Vorbis, and Opus. Generate tiny sample audio files in `tests/fixtures/` (via `ffmpeg`) and write read tests in `tests/test_engine.py`.
- [x] **Task 1.3:** Build `MetadataEngine.update_tags()` to write modified tags back to audio files without corrupting them (write to a temp copy, then swap it in). Add write/round-trip tests for every format.
- [x] **Task 1.4:** Build `src/coda/core/presets.py` to handle JSON-based Tag Loadouts (pre-saved batch tag templates), stored in `config/`. Add tests in `tests/test_presets.py`.
- [ ] **Task 1.5:** Add failure-case tests (corrupt files, read-only files, unsupported formats, unicode tags) proving that files are never damaged when something goes wrong.

## Phase 2: FastAPI Backend & Homelab Dockerization
- [ ] **Task 2.1:** Create FastAPI application entry point in `src/coda/web/app.py`.
- [ ] **Task 2.2:** Build API endpoint `/api/scan` that recursively scans the mounted `/music` directory (skipping hidden `.coda-*` temp files left by an interrupted write).
- [ ] **Task 2.3:** Build API endpoint `/api/metadata` (GET to fetch tags, POST to update them). Try it out by hand at `http://localhost:8111/docs`.
- [ ] **Task 2.4:** Build `/api/loadouts` endpoints: list/create/edit/delete loadouts, and apply one to selected files or a folder (with a dry-run preview of what will change).
- [ ] **Task 2.5:** Create a multi-stage `Dockerfile` optimized for `python:3.14-slim`.
- [ ] **Task 2.6:** Create `docker-compose.yml` configured with a local music volume mapping and port `8111` (8000 is taken by another service on the host).

## Phase 3: Web UI Frontend & Batch Tools
- [ ] **Task 3.1:** Create a clean single-page Tailwind CSS layout served at root (`/`) by FastAPI.
- [ ] **Task 3.2:** Build the file browser table component to list scanned audio tracks.
- [ ] **Task 3.3:** Build the side-by-side metadata editor panel for single-file and batch edits.
- [ ] **Task 3.4:** Implement the "Apply Tag Loadout" button for selected tracks or a whole folder, showing a preview (fill vs. overwrite) before writing.
- [ ] **Task 3.5:** Build a loadout editor to create, edit, and delete loadouts from the UI.
