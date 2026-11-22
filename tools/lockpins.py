"""Print uv.lock's exact versions as pip constraints ("name==version", one per line).

uv.lock is the record of the dependency versions Codetta was tested with. The Docker image, the
snap and CI install through pip, so this turns the lock into something pip understands:

    python tools/lockpins.py > /tmp/pins.txt && pip install -c /tmp/pins.txt .

Update the lock with `uv lock --upgrade` (or merge Dependabot's pull request), never by hand.
Standard library only, so it runs anywhere Python 3.11+ does.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def pins(lock: dict) -> list[str]:
    out = {}
    for pkg in lock.get("package", []):
        if "editable" in pkg.get("source", {}) or "virtual" in pkg.get("source", {}):
            continue  # Codetta itself
        name, version = pkg["name"], pkg["version"]
        if out.get(name, version) != version:
            raise SystemExit(f"uv.lock has two versions of {name}; pin it in pyproject.toml")
        out[name] = version
    return [f"{n}=={v}" for n, v in sorted(out.items())]


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "uv.lock"
    print("\n".join(pins(tomllib.loads(path.read_text("utf-8")))))


if __name__ == "__main__":
    main()
