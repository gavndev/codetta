# How Codetta fits together

A one-page map for anyone who wants to read or change the code. For running it
locally and opening a pull request, see [CONTRIBUTING.md](CONTRIBUTING.md).

## The shape of it

```
browser ── plain HTML/CSS/JS (static/) ──► JSON API (web/routes/) ──► core logic (core/) ──► your files
                                                                         │
                                                       config folder ◄───┘  (settings, activity log, index)
```

- **One Python package**, `src/codetta`, served by FastAPI and Uvicorn.
- **No database server.** Settings are small JSON files in the config folder;
  search uses a SQLite file that can be deleted and rebuilt at any time.
- **No front-end build.** The page is plain JavaScript in native ES modules, so
  what's in the repo is exactly what the browser runs.
- **Offline by default.** Anything that talks to the internet is a
  *connection* (`core/connections.py`) that's off until the user turns it on.

## Folders

| Folder | What's in it |
|---|---|
| `src/codetta/core/` | Everything that knows about music and files, with no web code in it. Each file has a docstring saying what it's for. |
| `src/codetta/web/app.py` | `create_app()`: builds the stores and services, sign-in, the background workers' start and stop, and the security middleware. |
| `src/codetta/web/common.py` | Settings (from environment variables), request and response models, small shared helpers. |
| `src/codetta/web/routes/` | The API, one module per area (library, MusicBrainz, inbox, Tidy up, Soulseek, health, presets, ...). |
| `src/codetta/web/security.py` | Size limits, cross-site protection, the Content Security Policy and other headers. |
| `src/codetta/web/static/` | The page: `index.html`, `app.css`, `app.js` (the entry point) and `js/` (one module per area). |
| `src/codetta/cli/` | `codetta` (run it on your own computer) and `codetta-admin` (password reset and other server tasks). |
| `tests/` | Over 1,300 tests. `test_safety.py` covers damaged and unusual files, `test_security.py` and `test_attacks.py` the security layer. |
| `docker/`, `snap/`, `Dockerfile` | Packaging. Releases are built by `.github/workflows/release.yml`. |

## The rules that keep files safe

These matter more than anything else in the code base.

1. **Every write goes through `MetadataEngine`** (`core/engine.py`): copy the
   file to a temporary file, write the tags there, read them back to verify,
   then swap it in with an atomic rename. A library file is never edited in place.
2. **Every change is logged with an undo record** (`core/activity.py`,
   `core/undo.py`). If an API route changes files, it logs what it did and how
   to reverse it.
3. **Paths come in relative to the music folder** and `core/library.py`
   refuses anything that escapes it, including through symlinks.
4. **Moves never overwrite.** Organize, the inbox and imports check for a free
   name; replaced and deleted files go to "Recently deleted", not away.
5. **Search stays current.** A route that changes files calls
   `lib_index.mark_dirty(paths)`.

## A request, start to finish

Saving a new genre on one track:

1. `js/editor.js` sends `PUT /api/tracks` with the changed fields.
2. `GuardMiddleware` (`web/security.py`) checks the size, origin and host;
   the sign-in middleware in `web/app.py` checks the session.
3. `routes/tags.py` resolves the path through `Library`, asks `MetadataEngine`
   to write the tags, logs an activity entry with its undo record, and marks the
   file dirty in the search index.
4. The page updates the row and shows "Saved". The activity log can undo it.

## How the API is put together

`create_app()` makes the shared pieces (the library, the metadata engine, the
activity log, the connections, MusicBrainz, the search index, ...) and puts
them on one `Shared` object. Then each module in `web/routes/` runs
`register(app, shared)`:

```python
def register(app, shared) -> None:
    library = shared.library            # what it needs, at the top
    ...
    @app.get("/api/browse")
    def browse(path: str = ""): ...
    ...
    shared.share(track_out=track_out)   # what later areas may use, at the bottom
```

Areas register in a fixed order (`ROUTES` in `web/app.py`). An area can use what
earlier ones shared right away; to call a function from a later area it asks
for `shared.later("name")`, which looks it up when it's called.

Every route needs a signed-in session, except `/`, `/static/*`,
`/api/auth/*`, `/api/health` and `/api/changelog`. New upload endpoints need an
entry in `BODY_LIMITS` in `web/security.py`.

## Background work

Four workers run as daemon threads, started and stopped by the app's lifespan:
the **search index** (`core/index.py`), the **inbox** watcher, **Tidy up**
(`routes/care.py`, one album at a time) and **Soulseek** downloads. Each sleeps
on a `threading.Event` and wakes only when there's work, so an idle Codetta
uses no CPU and doesn't touch the disk.

## The page

`static/app.js` imports `boot()` from `js/account.js` and calls it. Everything
else is in `static/js/`:

| Module | Area |
|---|---|
| `dom.js`, `api.js`, `state.js` | DOM helpers and icons, API calls, shared state, formatting and toasts |
| `browse.js` | Routing (the URL hash), folders and albums, the tag filter, selection |
| `editor.js` | The tag editor, raw tags, copy & paste, suggestions, lyrics, album art |
| `musicbrainz.js`, `search.js` | Matching and editions; the search bar, `!mb` and search ideas |
| `inbox.js`, `library.js`, `files.js` | The inbox and Soulseek; health, Tidy up and Organize; the context menu, import and Recently deleted |
| `player.js`, `notifications.js`, `account.js`, `setup.js` | The player; the bell; sign-in and the account sheet; connections, first-run setup and What's new |
| `wiring.js` | Connects buttons, keys and gestures to what they do |

The Content Security Policy forbids inline scripts and `onclick=`-style
attributes, so all events are attached in JavaScript. Data from files is only
ever set as text, never as HTML. The page must work on iPhone (WebKit) as well
as desktop browsers: 16 px inputs on phones, safe-area insets, 44 px touch targets.

## The config folder

| File | What it holds |
|---|---|
| `config-version.json` | Which settings layout the folder is in (see below) |
| `auth.json`, `sessions.json` | The account (password hash) and sign-in sessions, readable only by Codetta |
| `connections.json` | Which online features are on |
| `activity.jsonl`, `undo-art/` | The activity log and the old covers kept for undo |
| `presets/` | Tag Presets, one JSON file each |
| `inbox.json`, `library-care.json`, `editions.json`, `health.json`, `slskd.json`, ... | Each feature's own settings and progress |
| `library-index.sqlite3` | The search index (safe to delete) |
| `deleted/`, `replaced/` | Recently deleted, kept for 30 days |
| `backups/` | Copies of the settings made before an upgrade changed them |

**Changing a settings file's layout:** add a step to `STEPS` in
`core/configversion.py`. Codetta backs up the folder, runs the steps in order and
stamps the new version. Each step must be safe to run twice, and must come with a test.

## Releases

Bump `version` in `pyproject.toml`, date the section in `CHANGELOG.md`, and push a
tag `vX.Y.Z`. The release workflow checks the tag matches, runs the tests, then
publishes the Docker image (amd64 and arm64), the GitHub release (notes from the
changelog), the PyPI package and the snap. A tag like `v0.9.2-rc.1` makes a test
build instead: a pre-release, an image tagged `beta`, and the snap's beta channel.
