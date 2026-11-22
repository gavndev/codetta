"""Build the Codetta desktop app for this computer's system (Windows, macOS or Linux).

    pip install pyinstaller pillow -e .
    python packaging/build.py            # -> packaging/dist/Codetta-<version>-<system>-<cpu>.zip (+ -Portable)

Makes two archives:

* **Codetta-…zip**: the app. Settings go in the usual app-data folder.
* **Codetta-…-Portable.zip**: the same app next to an empty "Codetta Data" folder, so
  everything stays beside it (a USB stick, a synced folder) and nothing is left on the computer.

Chromaprint's fpcalc ("Identify by sound") is downloaded and checked against the SHA-256
GitHub publishes for it, then bundled. The Docker image uses the same builds.
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = HERE / "build"
DIST = HERE / "dist"
FPCALC_VERSION = "1.6.2"
FPCALC = {  # (system, cpu) -> (download, sha256), from github.com/acoustid/chromaprint/releases
    ("linux", "x86_64"): ("linux-x86_64.tar.gz", "c968ad4a0821592a79b158fb2e1f46cbe0a22a0a1dbc0743c67d68e75d15d2bb"),
    ("linux", "arm64"): ("linux-arm64.tar.gz", "3aa1498126ed272d805bc9d081c77965c9e1e1a0891bb112c13b56ef2ad47bad"),
    ("macos", "arm64"): ("macos-universal.tar.gz", "53d9368f96017fb288d74f6ed4d928f7bbbfb2ff81e69b4ef67b6ceeb217d9b2"),
    ("macos", "x86_64"): ("macos-universal.tar.gz", "53d9368f96017fb288d74f6ed4d928f7bbbfb2ff81e69b4ef67b6ceeb217d9b2"),
    ("windows", "x86_64"): ("windows-x86_64.zip", "b74369726676670af3ab0eadff45f960cf969fdf4a87a971ba37eaf8d530e874"),
}
PORTABLE_NOTE = """Codetta, portable

Everything Codetta keeps (your account, settings, search index, undo history and
Recently deleted) lives in this folder, so the app runs from a USB stick or any
folder and leaves nothing behind on the computer. Keep it next to the app.

Your music: put it in a "Music" folder next to the app, or pick another folder
in Codetta.
"""


def system() -> tuple[str, str]:
    name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    cpu = platform.machine().lower()
    cpu = {"amd64": "x86_64", "aarch64": "arm64"}.get(cpu, cpu)
    return name, cpu


def version() -> str:
    for line in (ROOT / "pyproject.toml").read_text("utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("no version in pyproject.toml")


def fetch_fpcalc(name: str, cpu: str) -> Path | None:
    entry = FPCALC.get((name, cpu))
    if not entry:
        print(f"No fpcalc build for {name}/{cpu}: Identify by sound won't be included", file=sys.stderr)
        return None
    suffix, sha = entry
    url = f"https://github.com/acoustid/chromaprint/releases/download/v{FPCALC_VERSION}/chromaprint-fpcalc-{FPCALC_VERSION}-{suffix}"
    data = urllib.request.urlopen(url, timeout=60).read()  # noqa: S310 (a fixed https URL)
    if hashlib.sha256(data).hexdigest() != sha:
        raise SystemExit(f"fpcalc download doesn't match its published SHA-256: {url}")
    exe = "fpcalc.exe" if name == "windows" else "fpcalc"
    out = WORK / exe
    WORK.mkdir(parents=True, exist_ok=True)
    if suffix.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next(m for m in z.namelist() if m.endswith("/" + exe) or m == exe)
            out.write_bytes(z.read(member))
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            member = next(m for m in t.getmembers() if m.name.endswith("/" + exe))
            out.write_bytes(t.extractfile(member).read())
    out.chmod(0o755)
    return out


def pyinstaller(name: str, fpcalc: Path | None) -> Path:
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", "Codetta",
        "--distpath", str(WORK / "app"), "--workpath", str(WORK / "pyi"), "--specpath", str(WORK),
        "--collect-data", "codetta", "--collect-submodules", "codetta", "--collect-submodules", "uvicorn",
        "--icon", str(ROOT / "src" / "codetta" / "web" / "static" / "icons" / "codetta.png"),
        "--osx-bundle-identifier", "io.github.gavndev.codetta",
    ]
    if name in ("windows", "macos"):
        args.append("--windowed")  # an app: no terminal window
    if fpcalc:
        args += ["--add-binary", f"{fpcalc}{os.pathsep}."]
    subprocess.run([*args, str(HERE / "codetta_app.py")], check=True, cwd=ROOT)
    return WORK / "app" / ("Codetta.app" if name == "macos" else "Codetta")


def archive(folder: Path, out: Path) -> None:
    """A zip that keeps the executable bits and the macOS app's links."""
    if sys.platform == "darwin":  # ditto keeps the .app bundle exactly as built
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(folder), str(out)], check=True)
        return
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(folder.rglob("*")):
            arc = path.relative_to(folder.parent).as_posix()
            if path.is_dir():
                info = zipfile.ZipInfo(arc + "/")
                info.external_attr = (0o40755 << 16) | 0x10  # a folder anyone can open
                z.writestr(info, b"")
            else:
                z.write(path, arc)


def main() -> None:
    name, cpu = system()
    shutil.rmtree(WORK, ignore_errors=True)
    DIST.mkdir(parents=True, exist_ok=True)
    fpcalc = None if "--no-fpcalc" in sys.argv else fetch_fpcalc(name, cpu)
    app = pyinstaller(name, fpcalc)
    base = f"Codetta-{version()}-{name}-{cpu}"

    plain = WORK / "plain" / "Codetta"
    plain.mkdir(parents=True)
    if name == "macos":
        shutil.copytree(app, plain / app.name, symlinks=True)  # Codetta/Codetta.app
    else:
        shutil.copytree(app, plain, symlinks=True, dirs_exist_ok=True)  # Codetta/Codetta(.exe) + _internal
    archive(plain, DIST / f"{base}.zip")

    portable = WORK / "portable" / "Codetta"
    shutil.copytree(plain, portable, symlinks=True)
    (portable / "Codetta Data").mkdir()
    (portable / "Codetta Data" / "README.txt").write_text(PORTABLE_NOTE, "utf-8")
    archive(portable, DIST / f"{base}-Portable.zip")
    for f in sorted(DIST.glob(f"{base}*.zip")):
        print(f"{f.name}: {f.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
