# Coda Development Guidelines & Context

## Project Overview
Coda is a self-hosted music metadata editor built in Python (FastAPI + Mutagen) and packaged for Docker, designed for homelab users managing local FLAC/audio libraries.

## Tech Stack & Architecture
- **Language:** Python 3.14+
- **Core Library:** `mutagen` for reading/writing audio metadata (FLAC, MP3, M4A/AAC, OGG Vorbis, Opus).
- **Tag vocabulary:** `src/coda/core/tagmap.py` gives every format the same lowercase tag names (Navidrome/OpenSubsonic set, stored the way MusicBrainz Picard does). Add new tag names there.
- **Tag Loadouts:** JSON files in `config/loadouts/`, handled by `src/coda/core/presets.py`.
- **Backend Framework:** FastAPI with Uvicorn.
- **Frontend:** Single-page web UI in `src/coda/web/static/` (plain HTML/CSS/JS, no framework, no build step, no CDNs, so it works on servers without internet). Inter font is bundled. Light/dark/system theme via CSS variables. Must work on iPhone (all iOS browsers are WebKit) as well as desktop Chromium/Firefox/Safari: 16px inputs on mobile, safe-area insets, 44px touch targets.
- **Library access:** `src/coda/core/library.py`. The API only takes paths relative to the music folder and rejects anything that escapes it. Browsing is one folder at a time so huge libraries stay fast.
- **Deployment:** Docker & Docker Compose with a mounted music volume (`/music`).

## Common Development Commands
- **Run Virtual Environment:** `source .venv/bin/activate`
- **Run FastAPI Locally:** `CODA_MUSIC_DIR=/path/to/music uvicorn coda.web.app:app --reload --port 8111` (add `--host 0.0.0.0` to open it from a phone on the same Wi-Fi). Loadouts go in `CODA_CONFIG_DIR` (default `./config`).
- **Run Tests:** `pytest`
- **Build Docker Image:** `docker compose build`
- **Run Docker Container:** `docker compose up -d`

## Coding Rules for Claude
1. **Keep it modular:** Core metadata logic lives in `src/coda/core/`. FastAPI routes live in `src/coda/web/`.
2. **Safety first:** When writing metadata changes to audio files, handle exceptions gracefully so files don't get corrupted. All writes must go through `MetadataEngine.update_tags()` (temp copy → verify → atomic swap); never write to a library file in place. Any new edge case gets a test in `tests/test_safety.py`.
3. **No over-engineering:** Use standard library features or lightweight libraries (`mutagen`, `fastapi`, `uvicorn`).
4. **Update the Plan:** As tasks are completed, check them off in `PLAN.md`.
