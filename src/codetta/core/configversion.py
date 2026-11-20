"""One version number for the whole config folder, and the steps that bring an
older folder up to date.

Codetta keeps its settings in a dozen small files (presets, connections, the
activity log, the inbox, ...). Rather than give each file its own format number,
``config-version.json`` records which layout the folder as a whole is in. When a
release changes a file's layout, it adds one step to ``STEPS`` and bumps
``CURRENT``. On startup, ``upgrade()``:

- stamps a brand-new (empty) folder with ``CURRENT`` and does nothing else;
- treats a folder with files but no stamp as version 0 (every install before 0.9.1);
- copies the settings files into ``backups/`` before running any step, runs the
  steps in order, and stamps the new version after each one, so a crash halfway
  resumes where it stopped;
- if a step fails, puts the backed-up files back and raises ``ConfigUpgradeError``,
  because running on half-upgraded settings is worse than not starting;
- never touches a folder stamped by a newer Codetta (someone went back a version):
  it reports ``newer`` so the app can warn, and leaves every file as it is.

Each step must be safe to run twice (a crash can stop one before its stamp)."""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("codetta.config")

FILE = "config-version.json"
BACKUPS = "backups"
KEEP_BACKUPS = 3
# Big or rebuildable things that don't belong in a settings backup.
_SKIP = {FILE, BACKUPS, "undo-art", "avatars", "replaced", "deleted", "library-index.sqlite3",
         "library-index.sqlite3-wal", "library-index.sqlite3-shm"}


class ConfigUpgradeError(RuntimeError):
    """A step failed; the folder was put back the way it was."""


def _presets_folder(config_dir: Path) -> None:
    """Tag Presets used to be called Tag Loadouts, kept in config/loadouts/."""
    old, new = config_dir / "loadouts", config_dir / "presets"
    if old.is_dir() and not new.exists():
        old.rename(new)
        log.info("Moved your Tag Presets from %s to %s", old, new)


# STEPS[n] takes the folder from version n - 1 to version n.
STEPS: dict[int, Callable[[Path], None]] = {
    1: _presets_folder,
}
CURRENT = max(STEPS)


@dataclass
class Result:
    status: str          # "fresh", "current", "upgraded", "newer" or "readonly"
    version: int         # the folder's version afterwards
    previous: int        # the version it started at
    backup: Path | None = None


def read_version(config_dir: Path) -> int | None:
    """The folder's version, 0 for an unstamped folder that has settings, None for an empty one."""
    try:
        data = json.loads((config_dir / FILE).read_text(encoding="utf-8"))
        return int(data["version"])
    except FileNotFoundError:
        pass
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # A damaged stamp: assume the oldest layout. Every step is safe to rerun.
        log.warning("Couldn't read %s (%s); checking every settings upgrade again", config_dir / FILE, exc)
        return 0
    try:
        has_files = any(p.name not in _SKIP for p in config_dir.iterdir())
    except OSError:
        has_files = False
    return 0 if has_files else None


def _stamp(config_dir: Path, version: int, app_version: str) -> None:
    payload = json.dumps({"version": version, "written_by": app_version}, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=config_dir, prefix=".config-version-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, config_dir / FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _settings_files(config_dir: Path) -> list[Path]:
    return sorted(p for p in config_dir.iterdir() if p.name not in _SKIP and not p.name.startswith("."))


def _backup(config_dir: Path, previous: int, app_version: str) -> Path:
    root = config_dir / BACKUPS
    dest = root / f"config-v{previous}-before-{app_version}-{time.strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while dest.exists():
        n += 1
        dest = dest.with_name(f"{dest.name.rsplit('~', 1)[0]}~{n}")
    dest.mkdir(parents=True)
    for p in _settings_files(config_dir):
        if p.is_dir():
            shutil.copytree(p, dest / p.name, symlinks=True)
        else:
            shutil.copy2(p, dest / p.name)  # keeps 0600 on auth.json
    old = sorted((d for d in root.iterdir() if d.is_dir() and d.name.startswith("config-v")),
                 key=lambda d: d.stat().st_mtime)
    for d in old[:-KEEP_BACKUPS]:
        shutil.rmtree(d, ignore_errors=True)
    return dest


def _restore(config_dir: Path, backup: Path) -> None:
    saved = {p.name for p in backup.iterdir()}
    for p in _settings_files(config_dir):
        if p.name not in saved:  # made by the failed step
            shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    for p in backup.iterdir():
        target = config_dir / p.name
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            target.unlink()
        if p.is_dir():
            shutil.copytree(p, target, symlinks=True)
        else:
            shutil.copy2(p, target)


def upgrade(config_dir: Path, app_version: str, steps: dict[int, Callable[[Path], None]] | None = None) -> Result:
    """Bring ``config_dir`` up to the current layout (see the module docstring)."""
    steps = STEPS if steps is None else steps
    current = max(steps) if steps else 0
    found = read_version(config_dir)
    try:
        if found is None:
            config_dir.mkdir(parents=True, exist_ok=True)
            _stamp(config_dir, current, app_version)
            return Result("fresh", current, current)
        if found > current:
            log.warning("These settings were saved by a newer Codetta (config version %s; this one knows %s). "
                        "Codetta will use them as they are and won't upgrade anything.", found, current)
            return Result("newer", found, found)
        if found == current:
            return Result("current", found, found)
        backup = _backup(config_dir, found, app_version)
    except OSError as exc:  # a read-only config folder: run as it is, like before
        log.warning("Couldn't check or stamp the config folder %s: %s", config_dir, exc)
        return Result("readonly", found or 0, found or 0)

    version = found
    for n in range(found + 1, current + 1):
        try:
            steps[n](config_dir)
            _stamp(config_dir, n, app_version)
        except Exception as exc:
            log.error("Settings upgrade step %s failed: %s. Putting your settings back from %s", n, exc, backup)
            try:
                _restore(config_dir, backup)
                if found:
                    _stamp(config_dir, found, app_version)
                else:
                    (config_dir / FILE).unlink(missing_ok=True)
            except (OSError, shutil.Error) as restore_exc:  # pragma: no cover - the backup is still there to copy by hand
                log.error("Couldn't put the settings back automatically (%s). They're saved in %s", restore_exc, backup)
            raise ConfigUpgradeError(
                f"Codetta couldn't upgrade its settings (step {n}: {exc}). Nothing was changed; "
                f"a copy of your settings is in {backup}.") from exc
        version = n
    log.info("Upgraded the settings in %s from version %s to %s (backup in %s)", config_dir, found, version, backup)
    return Result("upgraded", version, found, backup)
