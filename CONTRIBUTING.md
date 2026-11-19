# Contributing

Thanks for your interest! Bug reports, ideas and pull requests are all welcome. For anything big, please open an issue first so we can talk it through.

## Running it locally

Codetta is a [FastAPI](https://fastapi.tiangolo.com/) app using
[mutagen](https://mutagen.readthedocs.io/) for tags, with a plain
HTML/CSS/JavaScript front end (no framework, no build step).

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
CODETTA_MUSIC_DIR=~/some-test-music uvicorn codetta.web.app:app --reload --port 8111
```

To build the Docker image yourself instead of downloading it, add this to
your `docker-compose.override.yml` and run `docker compose up -d --build`:

```yaml
services:
  codetta:
    build: .
    image: codetta:local
```

Always use a **copy** of some music while developing. Logo files and colours
are in [`docs/brand`](docs/brand).

## Before opening a pull request

- Run `pytest` and make sure everything passes.
- Keep the front end plain HTML/CSS/JS (no build step, no CDNs).
- Any change that writes files must go through `MetadataEngine.update_tags()` / `update_artwork()` and be logged with an undo record.
