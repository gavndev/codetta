"""Shared pytest fixtures."""

import shutil
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# One tagged sample per supported format.
SAMPLE_FILES = ["sample.flac", "sample.mp3", "sample.m4a", "sample.ogg", "sample.opus"]

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
