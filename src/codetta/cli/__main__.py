"""Codetta admin commands, run on the server.

    python -m codetta.cli set-password       # create the account or reset its password
    python -m codetta.cli sign-out-all       # sign out every browser

In Docker:
    docker exec -it codetta codetta-admin set-password

Uses CODETTA_CONFIG_DIR (default ./config) like the web app, or --config DIR.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from codetta.core.auth import AccountStore, AuthError, SessionStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m codetta.cli", description="Codetta admin commands")
    parser.add_argument("--config", default=os.environ.get("CODETTA_CONFIG_DIR") or os.environ.get("CODA_CONFIG_DIR") or "config",
                        help="config folder (default: $CODETTA_CONFIG_DIR or ./config)")
    sub = parser.add_subparsers(dest="command", required=True)
    sp = sub.add_parser("set-password", help="create the account, or reset its password")
    sp.add_argument("--username", help="username (default: keep the current one)")
    sub.add_parser("sign-out-all", help="sign out every signed-in browser")
    args = parser.parse_args(argv)

    config = Path(args.config).expanduser()
    accounts = AccountStore(config / "auth.json")
    sessions = SessionStore(config / "sessions.json")

    if args.command == "sign-out-all":
        sessions.revoke_all()
        print("Signed out every browser.")
        return 0

    current = accounts.get()
    username = args.username or (current.username if current else None) or input("Username: ").strip()
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords didn't match. Nothing was changed.", file=sys.stderr)
        return 1
    try:
        accounts.set_password(username, password)
    except AuthError as exc:
        print(exc, file=sys.stderr)
        return 1
    sessions.revoke_all()
    print(f"Password set for {username!r}. All browsers were signed out; sign in again with the new password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
