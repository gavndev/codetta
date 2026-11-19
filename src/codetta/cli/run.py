"""The ``codetta`` command: run Codetta on this computer and open it in the browser.

    codetta                      # your Music folder, at http://localhost:8111
    codetta ~/Music/FLAC         # another folder
    codetta --host 0.0.0.0       # also reachable from your phone on the same network
    codetta set-password         # create the account, or reset its password
    codetta sign-out-all         # sign out every browser

Installed with pipx, uv, Homebrew, snap, winget... Docker doesn't use this (see Dockerfile).
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8111


def default_config_dir() -> Path:
    """Where Codetta keeps its account, settings and index when it's installed as an app."""
    if os.environ.get("SNAP_USER_COMMON"):  # snap: the folder that survives updates
        return Path(os.environ["SNAP_USER_COMMON"]) / "config"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Codetta"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Codetta"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "codetta"


def default_music_dir() -> Path:
    # In a snap, HOME is the snap's own folder (~/snap/codetta/<n>): the real one is SNAP_REAL_HOME.
    home = Path(os.environ.get("SNAP_REAL_HOME") or Path.home())
    for name in ("Music", "music"):
        if (home / name).is_dir():
            return home / name
    return home / "Music"


def _free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _open_when_ready(url: str, host: str, port: int) -> None:
    probe = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    end = time.monotonic() + 60
    while time.monotonic() < end:
        try:
            with socket.create_connection((probe, port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        return
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - no browser (a server, a container): the printed address is enough
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--codetta-describe-worker"]:  # an index helper, in a packaged app
        from codetta.core.describe import _worker_main
        _worker_main()
        return 0
    if argv[:1] and argv[0] in ("set-password", "sign-out-all"):
        from codetta.cli.__main__ import main as admin
        config = os.environ.get("CODETTA_CONFIG_DIR") or str(default_config_dir())
        return admin(["--config", config, *argv])

    from codetta import __version__
    parser = argparse.ArgumentParser(
        prog="codetta", description="Codetta: a private, self-hosted music library manager. "
        "Runs on this computer and opens in your browser. Admin: codetta set-password | sign-out-all")
    parser.add_argument("music", nargs="?", help="your music folder (default: $CODETTA_MUSIC_DIR or ~/Music)")
    parser.add_argument("--port", type=int, help=f"port (default: {DEFAULT_PORT}, or the next free one)")
    parser.add_argument("--host", default=os.environ.get("CODETTA_HOST", "127.0.0.1"),
                        help="address to listen on (default: 127.0.0.1, this computer only; "
                             "0.0.0.0 to reach it from other devices on your network)")
    parser.add_argument("--config", help="config folder (default: $CODETTA_CONFIG_DIR or your user's app-data folder)")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    parser.add_argument("--version", action="version", version=f"Codetta {__version__}")
    args = parser.parse_args(argv)

    music = Path(args.music or os.environ.get("CODETTA_MUSIC_DIR") or default_music_dir()).expanduser().resolve()
    config = Path(args.config or os.environ.get("CODETTA_CONFIG_DIR") or default_config_dir()).expanduser()
    if not music.is_dir():
        print(f"codetta: there's no folder at {music}. Say which one: codetta /path/to/music", file=sys.stderr)
        return 2
    if not 0 < (args.port or DEFAULT_PORT) < 65536:
        print("codetta: the port must be between 1 and 65535", file=sys.stderr)
        return 2
    port = args.port or next((p for p in range(DEFAULT_PORT, DEFAULT_PORT + 20) if _free(args.host, p)), DEFAULT_PORT)
    if args.port and not _free(args.host, port):
        print(f"codetta: port {port} is in use (is Codetta already running?). Try --port {port + 1}", file=sys.stderr)
        return 2
    config.mkdir(parents=True, exist_ok=True)
    os.environ["CODETTA_MUSIC_DIR"] = str(music)
    os.environ["CODETTA_CONFIG_DIR"] = str(config)

    import uvicorn

    from codetta.web.app import app  # reads the folders above

    shown = "localhost" if args.host in ("127.0.0.1", "::1") else args.host
    url = f"http://{shown}:{port}"
    print(f"Codetta {__version__}\n  Music:  {music}\n  Config: {config}\n  Open:   {url}"
          + ("\n  Reachable from other devices on your network too: sign-in protects it." if args.host in ("0.0.0.0", "::") else "")
          + "\nPress Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url, args.host, port), daemon=True).start()
    # No access log and no Server header: Codetta keeps no record of who visits (see PRIVACY.md).
    uvicorn.run(app, host=args.host, port=port, access_log=False, server_header=False, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
