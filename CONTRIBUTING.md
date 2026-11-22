# Contributing

Thanks for your interest! Bug reports, ideas and pull requests are all welcome. For anything big, please open an issue first so we can talk it through.
Everyone taking part agrees to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Running it locally

Codetta is a [FastAPI](https://fastapi.tiangolo.com/) app using
[mutagen](https://mutagen.readthedocs.io/) for tags, with a plain
HTML/CSS/JavaScript front end (no framework, no build step).

```sh
python3 -m venv .venv && source .venv/bin/activate
python tools/lockpins.py > /tmp/pins.txt && pip install -c /tmp/pins.txt -e ".[dev]"
pytest
CODETTA_MUSIC_DIR=~/some-test-music uvicorn codetta.web.app:app --reload --port 8111
```

`uv.lock` records the exact versions of Codetta's dependencies that the tests ran
against; the Docker image, the snap and CI all install those. If you add or change a
dependency in `pyproject.toml`, run [`uv lock`](https://docs.astral.sh/uv/) and commit
both files (a test fails if they disagree). Dependabot proposes updates monthly.

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

New to the code? [ARCHITECTURE.md](ARCHITECTURE.md) is a one-page map: where
things live, how a request flows, and the rules that keep files safe.

## Good first steps

- Issues labelled [good first issue](https://github.com/gavndev/codetta/labels/good%20first%20issue)
  are small and self-contained.
- Questions and ideas are welcome in [Discussions](https://github.com/gavndev/codetta/discussions).
- Speak another language? Improving the Spanish or adding your own needs no coding:
  see [Translating Codetta](docs/translating.md).

## Before opening a pull request

- Run `pytest` and make sure everything passes.
- If you touch a heavy path (scanning, saving, search, importing), run `python tools/bench.py` before and after. `--dir` tests a particular disk, like a Raspberry Pi's USB drive.
- Keep the front end plain HTML/CSS/JS (no build step, no CDNs).
- Any change that writes files must go through `MetadataEngine.update_tags()` / `update_artwork()` and be logged with an undo record.
- A new API route goes in the matching module in `src/codetta/web/routes/`; page code goes in the matching module in `src/codetta/web/static/js/`.
- Changing the layout of a settings file needs an upgrade step in `src/codetta/core/configversion.py`, with a test.
- Add a line to `CHANGELOG.md` under "Unreleased" for anything people will notice.
