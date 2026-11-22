"""Entry point of the packaged Codetta app (PyInstaller).

Double-clicked, it's the desktop app (codetta.cli.desktop): its own window, no sign-in screen,
portable when a "Codetta Data" folder sits next to it. The `codetta` command's admin and helper
modes still work: `Codetta set-password`, `Codetta --cli ~/Music` (the plain server), and the
index helpers it starts itself (--codetta-describe-worker).
"""

import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    args = sys.argv[1:]
    from codetta.cli.desktop import choose_folders

    if args[:1] in (["--codetta-describe-worker"], ["set-password"], ["sign-out-all"], ["--version"], ["--cli"]):
        if args[:1] in (["set-password"], ["sign-out-all"]):
            os.environ.setdefault("CODETTA_CONFIG_DIR", str(choose_folders(None)[1]))  # the portable folder, if any
        from codetta.cli.run import main as run
        sys.exit(run([a for a in args if a != "--cli"]))
    from codetta.cli.desktop import main as desktop
    sys.exit(desktop(args))
