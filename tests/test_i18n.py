"""Translations: every catalog is complete, keeps names and numbers in place, and is offered in the page."""

import json
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "src" / "codetta" / "web" / "static"
CATALOGS = sorted((STATIC / "i18n").glob("*.json"))
PLACEHOLDER = re.compile(r"\{[A-Za-z0-9_]+\}")


def test_there_is_at_least_one_catalog():
    assert CATALOGS


@pytest.mark.parametrize("path", CATALOGS, ids=lambda p: p.stem)
def test_catalogs_are_complete_and_keep_placeholders(path):
    cat = json.loads(path.read_text("utf-8"))
    assert cat["meta"]["name"]
    strings = cat["strings"]
    assert len(strings) > 1000
    for english, translated in strings.items():
        assert translated, f"{path.name}: not translated: {english!r}"
        assert sorted(PLACEHOLDER.findall(english)) == sorted(PLACEHOLDER.findall(translated)), \
            f"{path.name}: names/numbers changed in {english!r} -> {translated!r}"
    for word, forms in cat.get("words", {}).items():
        assert isinstance(forms, list) and len(forms) == 2 and all(forms), word


@pytest.mark.parametrize("path", CATALOGS, ids=lambda p: p.stem)
def test_every_catalog_is_offered_in_the_language_picker(path):
    src = (STATIC / "js" / "i18n.js").read_text("utf-8")
    languages = re.search(r"export const LANGUAGES = \{([^}]*)\}", src).group(1)
    assert re.search(rf"\b{path.stem}:", languages), f"{path.stem} isn't in LANGUAGES in js/i18n.js"


def test_the_users_music_is_never_translated():
    # dir="auto" marks titles, artists and folder names; h() turns it into translate="no".
    dom = (STATIC / "js" / "dom.js").read_text("utf-8")
    assert 'attrs?.dir === "auto"' in dom and '"translate", "no"' in dom
