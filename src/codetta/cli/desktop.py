"""Codetta as a desktop app: its own window, no server to set up, no sign-in screen.

This is what the packaged app (Windows, macOS, Linux) runs when it's double-clicked:

* **The window** is an app window of a browser the computer already has (Edge on every
  Windows 10/11 PC, or Chrome, Brave, Chromium), with its own profile, so it looks and
  behaves like an app and closing it quits Codetta. Without one, Codetta opens in the
  default browser and the Account sheet has **Quit Codetta**.
* **No sign-in screen, still private.** Codetta listens on this computer only, and each
  launch makes a fresh secret that only the window gets (``/api/auth/desktop``). Other
  programs and other people on the computer can't get in without it.
* **Portable:** with a ``Codetta Data`` folder next to the app, everything (account,
  settings, index, undo history) lives in it, so the app runs from a USB stick and leaves
  nothing behind on the computer. Otherwise it uses the usual app-data folder.

The music folder is the one given on the command line, the one picked last time
(``desktop.json``), a ``Music`` folder next to a portable app, or the user's Music folder.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from codetta.cli.run import DEFAULT_PORT, _free, default_config_dir, default_music_dir

PORTABLE_FOLDER = "Codetta Data"
log = logging.getLogger("codetta")


def app_dir() -> Path:
    """The folder the app lives in (the .exe's folder; the .app's parent folder on macOS)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        for parent in exe.parents:  # Codetta.app/Contents/MacOS/Codetta -> the folder holding Codetta.app
            if parent.suffix == ".app":
                return parent.parent
        return exe.parent
    return Path.cwd()


def portable_data(base: Path | None = None) -> Path | None:
    data = (base or app_dir()) / PORTABLE_FOLDER
    return data if data.is_dir() else None


def choose_folders(music_arg: str | None, base: Path | None = None) -> tuple[Path, Path, bool]:
    """(music folder, config folder, portable?)."""
    base = base or app_dir()
    data = portable_data(base)
    config = data / "config" if data else Path(os.environ.get("CODETTA_CONFIG_DIR") or default_config_dir())
    prefs = read_prefs(config)
    if music_arg:
        music = Path(music_arg).expanduser()
    elif prefs.get("music") and Path(prefs["music"]).is_dir():
        music = Path(prefs["music"])
    elif data:
        music = base / "Music" if (base / "Music").is_dir() else data / "Music"
    else:
        music = Path(os.environ.get("CODETTA_MUSIC_DIR") or default_music_dir())
    return music.resolve(), config, data is not None


def read_prefs(config: Path) -> dict:
    try:
        data = json.loads((config / "desktop.json").read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_prefs(config: Path, **values) -> None:
    prefs = {**read_prefs(config), **values}
    try:
        (config / "desktop.json").write_text(json.dumps(prefs, indent=1), "utf-8")
    except OSError:
        pass


# --- The window -------------------------------------------------------------------------------

def _browsers() -> list[str]:
    """Browsers that can open an app window (Chromium family), most likely first for this system."""
    if sys.platform == "win32":
        roots = [os.environ.get(v) for v in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        rel = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
               r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        return [str(Path(r) / p) for p in rel for r in roots if r and (Path(r) / p).is_file()]
    if sys.platform == "darwin":
        apps = ["Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Vivaldi"]
        found = []
        for root in (Path("/Applications"), Path.home() / "Applications"):
            for a in apps:
                exe = root / f"{a}.app" / "Contents" / "MacOS" / a
                if exe.is_file():
                    found.append(str(exe))
        return found
    names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
             "brave-browser", "brave", "vivaldi"]
    return [p for p in (shutil.which(n) for n in names) if p]


def open_window(url: str, profile: Path) -> subprocess.Popen | None:
    """Codetta in an app window of its own (no tabs, no address bar). None: no suitable browser."""
    for exe in _browsers():
        try:
            profile.mkdir(parents=True, exist_ok=True)
            return subprocess.Popen(
                [exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                 "--window-size=1280,860", "--disable-features=Translate"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            continue
    return None


# --- Running it -------------------------------------------------------------------------------

def _running(config: Path) -> str | None:
    """The address of a Codetta already running from this config folder (opening the app twice
    opens another window onto it, rather than a second Codetta on the same files)."""
    try:
        info = json.loads((config / "running.json").read_text("utf-8"))
        port, token = int(info["port"]), str(info["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:  # noqa: S310 (this computer)
            if r.status != 200:
                return None
    except OSError:
        return None
    return f"http://127.0.0.1:{port}/api/auth/desktop?token={token}"


def _write_running(config: Path, port: int, token: str) -> None:
    path = config / "running.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # owner only: it holds the window's key
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"port": port, "token": token, "pid": os.getpid()}, f)
    except OSError:
        pass

def _log_to_file(config: Path) -> None:
    """A packaged app has no terminal: keep the log in the config folder for Report a problem."""
    try:
        handler = logging.FileHandler(config / "codetta.log", encoding="utf-8")
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    for name in ("codetta", "uvicorn", "uvicorn.error"):
        logging.getLogger(name).addHandler(handler)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    music_arg = next((a for a in argv if not a.startswith("-")), None)
    music, config, portable = choose_folders(music_arg)
    config.mkdir(parents=True, exist_ok=True)
    music.mkdir(parents=True, exist_ok=True)  # a fresh portable stick, or a computer without a Music folder
    if music_arg:
        save_prefs(config, music=str(music))
    _log_to_file(config)
    bundled = Path(getattr(sys, "_MEIPASS", "")) / ("fpcalc.exe" if sys.platform == "win32" else "fpcalc")
    if getattr(sys, "frozen", False) and bundled.is_file():
        os.environ.setdefault("CODETTA_FPCALC", str(bundled))  # Identify by sound, bundled with the app

    already = _running(config)
    if already:
        if open_window(already, config / "window") is None:
            webbrowser.open(already)
        return 0

    token = secrets.token_urlsafe(32)
    os.environ.update({
        "CODETTA_MUSIC_DIR": str(music), "CODETTA_CONFIG_DIR": str(config), "CODETTA_DESKTOP_TOKEN": token,
        "CODETTA_ALLOWED_HOSTS": "127.0.0.1,localhost",
    })
    port = next((p for p in range(DEFAULT_PORT, DEFAULT_PORT + 50) if _free("127.0.0.1", p)), 0)
    if not port:
        log.error("No free port between %s and %s", DEFAULT_PORT, DEFAULT_PORT + 49)
        return 2

    import uvicorn

    from codetta.web.app import app  # reads the folders above

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False,
                                           server_header=False, log_level="warning"))
    app.state.desktop_quit = lambda: setattr(server, "should_exit", True)
    thread = threading.Thread(target=server.run, name="codetta-server", daemon=True)
    thread.start()
    end = time.monotonic() + 60
    while not server.started and thread.is_alive() and time.monotonic() < end:
        time.sleep(0.05)
    if not server.started:
        log.error("Codetta didn't start (see codetta.log in %s)", config)
        return 1

    _write_running(config, port, token)
    url = f"http://127.0.0.1:{port}/api/auth/desktop?token={token}"
    print(f"Codetta is running\n  Music:  {music}\n  Data:   {config}{'  (portable)' if portable else ''}", flush=True)
    headless = os.environ.get("CODETTA_NO_WINDOW") == "1"  # builds are checked on machines without a screen
    window = None if headless else open_window(url, config / "window")
    if headless:
        pass  # runs until Quit (POST /api/desktop/quit) or Ctrl+C
    elif window is not None:
        while window.poll() is None and thread.is_alive():
            time.sleep(0.3)
        server.should_exit = True  # the window was closed: Codetta closes with it
    else:
        webbrowser.open(url)  # no app window: a browser tab, and Quit Codetta in the Account sheet
    try:
        thread.join()
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(timeout=10)
    finally:
        (config / "running.json").unlink(missing_ok=True)
    return 0
