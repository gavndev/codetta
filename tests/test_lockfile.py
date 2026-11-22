"""uv.lock: the exact dependency versions the image, snap and CI install. It must match pyproject.toml."""

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _requirement(spec: str) -> tuple[str, str]:
    name = spec.split(";")[0].strip()
    for op in (">=", "==", "~=", "<", ">"):
        if op in name:
            n, _, v = name.partition(op)
            return n.strip().lower(), op + v.strip()
    return name.lower(), ""


def test_the_lock_matches_pyproject():
    """Changed a dependency in pyproject.toml? Run `uv lock` so the builds install it."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text("utf-8"))
    me = next(p for p in lock["package"] if p["name"] == "codetta")
    locked = {(d["name"], d.get("specifier", "")) for d in me["metadata"]["requires-dist"]}
    wanted = {_requirement(s) for s in project["dependencies"]}
    wanted |= {_requirement(s) for deps in project.get("optional-dependencies", {}).values() for s in deps}
    assert wanted == locked, "uv.lock is out of date: run `uv lock`"


def test_every_dependency_is_pinned():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "lockpins.py")], capture_output=True, text=True,
                         check=True).stdout.split()
    pinned = {line.split("==")[0] for line in out}
    assert {"fastapi", "uvicorn", "mutagen", "starlette", "pydantic"} <= pinned
    assert all("==" in line for line in out) and "codetta" not in pinned
