"""Shared pytest fixtures."""

import shutil
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# One tagged sample per supported format.
SAMPLE_FILES = [
    "sample.flac", "sample.mp3", "sample.m4a", "sample.ogg", "sample.opus",
    # added in 0.2 (see fixtures/make_more_fixtures.py)
    "sample.wav", "sample.aiff", "sample.tta", "sample.mp2", "sample.dsf",
    "sample.wv", "sample.wma", "sample.m4b", "sample.oga", "sample.spx",
    # added in 0.9.7 (see fixtures/make_mutagen_fixtures.py)
    "sample.ape", "sample.mpc", "sample.dff",
]

# Sample rates that aren't 44.1 kHz (Opus always decodes at 48 kHz).
SAMPLE_RATES = {"sample.opus": 48000, "sample.spx": 16000, "sample.dsf": 2822400, "sample.dff": 5644800}
# The samples from mutagen's test files aren't one second of mono like the rest.
SAMPLE_DURATIONS = {"sample.ape": 3.68, "sample.mpc": 0.07, "sample.dff": 0.01}
SAMPLE_CHANNELS = {"sample.ape": 2, "sample.mpc": 2, "sample.dff": 2}

# The tags make_fixtures.sh writes into every sample file.
EXPECTED_TAGS = {
    "title": ["Test Track"],
    "artist": ["Coda Tester"],
    "album": ["Fixture Album"],
    "albumartist": ["Coda Collective"],
    "genre": ["Test"],
    "date": ["2024"],
    "tracknumber": ["3/12"],
    "discnumber": ["1/2"],
}


@pytest.fixture
def fixture_copy(tmp_path):
    """Return a function that copies a sample file into a temp folder.

    Tests always work on a copy, so the originals in tests/fixtures/ are never
    modified, even when a test writes tags.
    """

    def _copy(name: str) -> Path:
        dest = tmp_path / name
        shutil.copy2(FIXTURES_DIR / name, dest)
        return dest

    return _copy
