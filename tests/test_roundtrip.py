"""Generated round trips: random tags (any script, emoji, long and short) are saved to every
format and must read back exactly, and saving one tag must leave everything else alone.

Hypothesis makes the examples and, when one fails, shrinks it to the smallest tags that
still fail, so a failure here reads like a bug report."""
import re
import shutil

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from codetta.core.engine import MetadataEngine
from codetta.core.tagmap import ID3_FORMATS, is_tag_supported
from tests.conftest import FIXTURES_DIR, SAMPLE_FILES

engine = MetadataEngine()
RUNS = settings(max_examples=60, deadline=None, derandomize=True,
                suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])

# Printable text from every script, emoji and combining marks included. Control characters
# and lone surrogates can't be stored as text in any tag format, and edges are trimmed when
# typed in the app, so values here are what a person can actually save.
TEXT = st.text(st.characters(exclude_categories=("Cs", "Cc", "Zl", "Zp")), min_size=1, max_size=80) \
    .map(str.strip).filter(bool)
LONG = st.text(st.characters(exclude_categories=("Cs", "Cc", "Zl", "Zp")), min_size=200, max_size=3000) \
    .map(str.strip).filter(bool)
SINGLE = ["title", "album", "albumartist", "composer"]
MULTI = ["artist", "genre"]


# ID3 can't store a genre that is only a number: it *is* a genre code there (see test_safety.py).
GENRE_CODE = re.compile(r"\(?(\d+|RX|CR)\)?")


def values_for(f: str, key: str):
    if key == "genre" and f in ID3_FORMATS:
        return TEXT.filter(lambda v: not GENRE_CODE.fullmatch(v))
    return TEXT


def fmt(name: str) -> str:
    return engine.load_metadata(FIXTURES_DIR / name).format


def copy(tmp_path, name):
    """A fresh copy for each example, always at the same path, so a run stays tiny on disk."""
    dest = tmp_path / name
    shutil.copy2(FIXTURES_DIR / name, dest)
    for leftover in tmp_path.glob(".codetta-*"):  # a failed write's temp file, if any
        leftover.unlink()
    return dest


def expected_after(before: dict, changes: dict) -> dict:
    out = {k: list(v) for k, v in before.items()}
    for k, v in changes.items():
        out[k] = [v] if isinstance(v, str) else list(v)
    return out


@pytest.mark.parametrize("name", SAMPLE_FILES)
@RUNS
@given(data=st.data())
def test_any_text_reads_back_exactly(tmp_path, name, data):
    f = fmt(name)
    keys = [k for k in SINGLE if is_tag_supported(f, k)]
    changes = {k: data.draw(TEXT, label=k) for k in keys}
    path = copy(tmp_path, name)
    before = engine.load_metadata(path).tags
    after = engine.update_tags(path, changes).tags
    assert after == expected_after(before, changes)
    assert engine.load_metadata(path).tags == after  # and again from disk


@pytest.mark.parametrize("name", SAMPLE_FILES)
@RUNS
@given(data=st.data())
def test_several_artists_and_genres_stay_separate(tmp_path, name, data):
    f = fmt(name)
    keys = [k for k in MULTI if is_tag_supported(f, k)]
    changes = {k: data.draw(st.lists(values_for(f, k), min_size=1, max_size=4, unique=True), label=k) for k in keys}
    path = copy(tmp_path, name)
    before = engine.load_metadata(path).tags
    after = engine.update_tags(path, changes).tags
    assert after == expected_after(before, changes)


@pytest.mark.parametrize("name", SAMPLE_FILES)
@RUNS
@given(value=LONG)
def test_long_values_survive(tmp_path, name, value):
    key = "comment" if is_tag_supported(fmt(name), "comment") else "title"
    path = copy(tmp_path, name)
    assert engine.update_tags(path, {key: value}).tags[key] == [value]


@pytest.mark.parametrize("name", SAMPLE_FILES)
@RUNS
@given(data=st.data())
def test_saving_one_tag_leaves_everything_else_alone(tmp_path, name, data):
    path = copy(tmp_path, name)
    before = engine.load_metadata(path)
    art = engine.read_artwork(path)
    key = data.draw(st.sampled_from(SINGLE + MULTI), label="key")
    if not is_tag_supported(before.format, key):
        return
    value = data.draw(values_for(before.format, key), label="value")
    after = engine.update_tags(path, {key: value})
    for k in set(before.tags) | set(after.tags):
        if k != key:
            assert after.tags.get(k) == before.tags.get(k), f"{k} changed when only {key} was saved"
    for attr in ("duration", "sample_rate", "channels"):
        assert getattr(after, attr) == getattr(before, attr), f"{attr} changed"
    new_art = engine.read_artwork(path)
    assert (new_art.data if new_art else None) == (art.data if art else None), "the cover changed"


@pytest.mark.parametrize("name", SAMPLE_FILES)
@RUNS
@given(data=st.data())
def test_removing_a_tag_removes_only_that_tag(tmp_path, name, data):
    path = copy(tmp_path, name)
    before = engine.load_metadata(path).tags
    present = sorted(k for k in before if k in SINGLE + MULTI)
    if not present:
        return
    key = data.draw(st.sampled_from(present), label="key")
    after = engine.update_tags(path, {key: None}).tags
    assert key not in after
    assert {k: v for k, v in after.items()} == {k: v for k, v in before.items() if k != key}
