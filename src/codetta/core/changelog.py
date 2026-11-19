"""What's new: CHANGELOG.md, split into versions for the in-app popup.

The file ships next to the app (/opt/codetta/CHANGELOG.md in Docker; the
project folder in a source checkout). It's the same text as on GitHub, so it
holds nothing private, which is why the sign-in screen may show it too.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

CANDIDATES = (
    Path(__file__).resolve().parents[3] / "CHANGELOG.md",  # source checkout
    Path("/opt/codetta/CHANGELOG.md"),  # Docker image
    Path(__file__).resolve().parents[1] / "CHANGELOG.md",  # installed package (pipx, Homebrew, snap...)
)
_HEADING = re.compile(r"^##\s+(.+?)\s*$")
_VERSION = re.compile(r"^(?:Unreleased\s*\()?v?(\d+(?:\.\d+)*)\)?(?:\s*\((\d{4}-\d{2}-\d{2})\))?")


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> list[dict]:
    """[{version, date, unreleased, items: [markdown text per bullet]}], newest first."""
    for candidate in ([path] if path else CANDIDATES):
        try:
            text = candidate.read_text("utf-8")
            break
        except OSError:
            continue
    else:
        return []
    versions, current = [], None
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            title = m.group(1)
            v = _VERSION.match(title)
            current = {"title": title, "version": v.group(1) if v else title,
                       "date": (v.group(2) if v else None) or "", "unreleased": title.lower().startswith("unreleased"),
                       "items": [], "text": []}
            versions.append(current)
        elif current is not None:
            if line.startswith("- "):
                current["items"].append(line[2:].strip())
            elif line.startswith("  ") and current["items"]:
                current["items"][-1] += " " + line.strip()
            elif line.strip():
                current["text"].append(line.strip())
    return versions
