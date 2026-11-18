# Codetta Development Guidelines & Context

## Project Overview
Codetta is a self-hosted music metadata editor built in Python (FastAPI + Mutagen) and packaged for Docker, designed for homelab users managing local FLAC/audio libraries.

## Tech Stack & Architecture
- **Language:** Python 3.14+
- **Core Library:** `mutagen` for reading/writing audio metadata (FLAC, MP3, M4A/AAC, OGG Vorbis, Opus).
- **Tag vocabulary:** `src/codetta/core/tagmap.py` gives every format the same lowercase tag names (Navidrome/OpenSubsonic set, stored the way MusicBrainz Picard does). Add new tag names there.
- **Tag Loadouts:** JSON files in `config/loadouts/`, handled by `src/codetta/core/presets.py`.
- **Album art:** `src/codetta/core/artwork.py` (per-format picture handling); writes go through `MetadataEngine.update_artwork()`.
- **Security layer:** `src/codetta/web/security.py` (size limits, cross-site protection, CSP/security headers). The page must not use inline scripts or event-handler attributes (the CSP forbids them); new upload endpoints need an entry in `BODY_LIMITS`. Any security fix gets a test in `tests/test_security.py`.
- **Sign-in:** `src/codetta/core/auth.py` (account, sessions, rate limiting) + middleware in `src/codetta/web/app.py`. Every new API route is private by default; only `/`, `/static/*`, `/api/auth/*`, `/api/health` and `/api/changelog` (the public CHANGELOG.md) are public. Account files (`auth.json`, `sessions.json`) live in the config folder and must never be committed.
- **Activity log:** `src/codetta/core/activity.py`, stored as `activity.jsonl` in the config folder. Every API action that changes files must log an entry, with an `undo` record (see `src/codetta/core/undo.py`) so it can be reversed.
- **Backend Framework:** FastAPI with Uvicorn.
- **Frontend:** Single-page web UI in `src/codetta/web/static/` (plain HTML/CSS/JS, no framework, no build step, no CDNs, so it works on servers without internet). Inter font is bundled. Light/dark/system theme via CSS variables. Must work on iPhone (all iOS browsers are WebKit) as well as desktop Chromium/Firefox/Safari: 16px inputs on mobile, safe-area insets, 44px touch targets.
- **Search index:** `src/codetta/core/index.py` (SQLite `library-index.sqlite3` in the config folder, background thread). Any new route that changes files must call `lib_index.mark_dirty(paths)` so search stays current.
- **Library access:** `src/codetta/core/library.py`. The API only takes paths relative to the music folder and rejects anything that escapes it. Browsing is one folder at a time so huge libraries stay fast.
- **CI / releases:** `.github/workflows/ci.yml` (tests + image smoke test) and `release.yml` (tag `vX.Y.Z` → multi-arch image `ghcr.io/gavndev/codetta` + GitHub release from `CHANGELOG.md`). Bump `version` in `pyproject.toml` before tagging.
- **Deployment:** `Dockerfile` + `docker-compose.yml`; container runs as `PUID:PGID` via `docker/entrypoint.sh` (never root), volumes `/music` and `/config`. Admin commands inside the container go through `codetta-admin` so files stay owned by `PUID`.

## Common Development Commands
- **Run Virtual Environment:** `source .venv/bin/activate`
- **Run FastAPI Locally:** `CODETTA_MUSIC_DIR=/path/to/music uvicorn codetta.web.app:app --reload --port 8111` (add `--host 0.0.0.0` to open it from a phone on the same Wi-Fi). Loadouts go in `CODETTA_CONFIG_DIR` (default `./config`).
- **Run Tests:** `pytest`
- **Build Docker Image:** `docker compose build`
- **Run Docker Container:** `docker compose up -d`

## Coding Rules for Claude
1. **Keep it modular:** Core metadata logic lives in `src/codetta/core/`. FastAPI routes live in `src/codetta/web/`.
2. **Safety first:** When writing metadata changes to audio files, handle exceptions gracefully so files don't get corrupted. All writes must go through `MetadataEngine.update_tags()` (temp copy → verify → atomic swap); never write to a library file in place. Any new edge case gets a test in `tests/test_safety.py`.
3. **No over-engineering:** Use standard library features or lightweight libraries (`mutagen`, `fastapi`, `uvicorn`).
4. **Update the Plan:** As tasks are completed, check them off in `PLAN.md`.
5. **Introduce features:** a core feature that needs a choice gets a first-run setup step (`core/onboarding.py`, shown once to existing installs too), and every user-visible change gets a `CHANGELOG.md` line (it feeds the in-app "What's new").
