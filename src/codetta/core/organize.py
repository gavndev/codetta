"""Organize: rename and move files into folders from their tags.

A *pattern* describes where a file belongs, relative to the music folder:

    {albumartist|artist}/{album}[ ({year})]/{disctrack} {title}

- ``{name}`` is a tag (or one of the extras below); ``{a|b}`` uses the first
  one that has a value.
- ``[...]`` is optional: it disappears when a tag inside it is empty, so
  ``{album}[ ({year})]`` gives "Abbey Road (1969)" or just "Abbey Road".
- ``/`` starts a new folder. The file extension is added automatically.

Extras: ``{track}`` ("01"), ``{disc}`` ("2"), ``{disctrack}`` ("01", or
"2-01" on multi-disc albums), ``{year}``, ``{ext}``/``{format}``, ``{filename}``
(the current name, without extension).

Nothing here touches a file until ``apply_moves``; ``plan_moves`` only works
out where everything would go, and why something can't move. Moves never
overwrite: a name that's already taken is reported as a conflict. Undo records
every move (see ``undo_moves``).
"""

from __future__ import annotations

import contextlib
import errno
import os
import re
import secrets
import shutil
import threading
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from codetta.core.engine import SUPPORTED_EXTENSIONS, file_lock

PRESETS: tuple[tuple[str, str], ...] = (
    ("Artist / Album (Year) / 01 Title", "{albumartist|artist}/{album}[ ({year})]/{disctrack} {title}"),
    ("Artist / Album / 01 - Title", "{albumartist|artist}/{album}/{disctrack} - {title}"),
    ("Artist / Year - Album / 01. Title", "{albumartist|artist}/[{year} - ]{album}/{disctrack}. {title}"),
    ("Artist / Album / Artist - Title", "{albumartist|artist}/{album}/{disctrack} {artist} - {title}"),
)
DEFAULT_PATTERN = PRESETS[0][1]
MAX_PATTERN = 300
MAX_COMPONENT_BYTES = 200  # most filesystems allow 255 bytes per name; leave room for " (2)"
# Values used when a pattern's tag is empty, so a file never lands in "/".
FALLBACKS = {"albumartist": "Unknown Artist", "artist": "Unknown Artist", "album": "Unknown Album"}
SIDECAR_SUFFIXES = (".lrc",)  # follow their audio file when renamed
# Stand-ins that aren't real names (MusicBrainz's "[unknown]", tags some rippers write): a pattern
# treats them as empty, so a file is never named "[unknown]" or filed under "Unknown".
PLACEHOLDERS = frozenset({"[unknown]", "[untitled]", "[no artist]", "unknown", "unknown artist", "unknown album",
                          "untitled", "no title", "<unknown>", "?"})
_TOKEN = re.compile(r"\{([^{}]*)\}")
_OPTIONAL = re.compile(r"\[([^\[\]]*)\]")
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


class PatternError(ValueError):
    """The pattern can't be used (empty, unbalanced, or would leave the library)."""


def check_pattern(pattern: str) -> str:
    pattern = (pattern or "").strip().strip("/")
    if not pattern:
        raise PatternError("Choose a pattern first.")
    if len(pattern) > MAX_PATTERN:
        raise PatternError(f"The pattern is too long (max {MAX_PATTERN} characters).")
    if pattern.count("{") != pattern.count("}") or pattern.count("[") != pattern.count("]"):
        raise PatternError("Every { needs a } and every [ needs a ].")
    if "\\" in pattern:
        raise PatternError("Use / to separate folders.")
    last = pattern.rsplit("/", 1)[-1]
    if not _TOKEN.search(last):
        raise PatternError("The file name part (after the last /) needs at least one tag, like {title}.")
    return pattern


def safe_name(text: str, limit: int = MAX_COMPONENT_BYTES) -> str:
    """One folder or file name that works on Linux, SMB shares, Windows and macOS."""
    text = unicodedata.normalize("NFC", text)
    text = " ".join(text.split())  # tabs, newlines, runs of spaces
    text = _UNSAFE.sub("_", text)
    text = text.strip().rstrip(".").strip()  # Windows drops trailing dots and spaces
    if text.startswith("."):
        text = "_" + text[1:]  # never a hidden file
    if text.startswith("@"):
        # "@inbox" / "@replaced" are Codetta's own folder shortcuts: a tag (say, from a
        # downloaded file) must never steer files there. A full-width ＠ looks the same.
        text = "\uff20" + text[1:]
    raw = text.encode("utf-8")
    if len(raw) > limit:
        text = raw[:limit].decode("utf-8", "ignore").rstrip(" .")
    return text or "_"


def _first(tags: dict[str, list[str]], key: str) -> str:
    for v in tags.get(key, []):
        if v.strip():
            return v.strip()
    return ""


def _number(value: str) -> int | None:
    m = re.match(r"^\s*(\d+)", value or "")
    return int(m.group(1)) if m else None


def _total(value: str) -> int | None:
    m = re.match(r"^\s*\d+\s*/\s*(\d+)", value or "")
    return int(m.group(1)) if m else None


@dataclass
class Source:
    """One audio file and what the pattern needs to know about it."""

    rel: str
    tags: dict[str, list[str]]
    format: str = ""

    def value(self, key: str, multi_disc: bool) -> str:
        key = key.strip().lower()
        stem, ext = os.path.splitext(self.rel.rsplit("/", 1)[-1])
        if key == "track":
            n = _number(_first(self.tags, "tracknumber"))
            return f"{n:02d}" if n is not None else ""
        if key == "disc":
            n = _number(_first(self.tags, "discnumber"))
            return str(n) if n is not None else ""
        if key == "disctrack":
            track = self.value("track", multi_disc)
            disc = self.value("disc", multi_disc)
            if not track:
                return ""
            return f"{disc}-{track}" if multi_disc and disc else track
        if key == "year":
            m = re.match(r"^\s*(\d{4})", _first(self.tags, "date") or _first(self.tags, "originaldate"))
            return m.group(1) if m else ""
        if key == "originalyear":
            m = re.match(r"^\s*(\d{4})", _first(self.tags, "originaldate"))
            return m.group(1) if m else ""
        if key in ("ext", "format"):
            return ext.lstrip(".").lower()
        if key == "filename":
            return stem
        value = _first(self.tags, key)
        return "" if value.strip().casefold() in PLACEHOLDERS else value

    def placeable(self) -> bool:
        """Does it have an artist or an album to be filed under? (Not just placeholders.)"""
        return any(self.value(k, False) for k in ("albumartist", "artist", "album"))


def _token_value(src: Source, expr: str, multi_disc: bool) -> str:
    for alt in expr.split("|"):
        v = src.value(alt, multi_disc)
        if v:
            return v
    return ""


def render(pattern: str, src: Source, multi_disc: bool = False) -> str:
    """The library-relative path ``src`` would get (extension included)."""
    pattern = check_pattern(pattern)

    def optional(m: re.Match) -> str:
        part = m.group(1)
        tokens = _TOKEN.findall(part)
        if any(not _token_value(src, t, multi_disc) for t in tokens):
            return ""
        return part

    components = _OPTIONAL.sub(optional, pattern).split("/")
    ext = os.path.splitext(src.rel)[1].lower()
    # No title: the file keeps its own name (in its new folder) instead of "03 03 - old name".
    keep_name = "title" in [t.split("|")[0].strip().lower() for t in _TOKEN.findall(components[-1])] \
        and not _token_value(src, "title", multi_disc)
    expanded_parts = []
    for component in components:
        def fill(m: re.Match) -> str:
            expr = m.group(1)
            v = _token_value(src, expr, multi_disc)
            if not v:
                first_key = expr.split("|")[0].strip().lower()
                v = FALLBACKS.get(first_key, "")
                if not v and first_key == "title":
                    v = src.value("filename", multi_disc)
            return v.replace("/", "_").replace("\\", "_")

        expanded_parts.append(_TOKEN.sub(fill, component))
    if keep_name:
        expanded_parts[-1] = src.value("filename", multi_disc)
    folders = [safe_name(p) for p in expanded_parts[:-1] if p.strip()]
    name = safe_name(expanded_parts[-1], MAX_COMPONENT_BYTES - len(ext.encode()))
    return "/".join([*folders, name + ext])


def album_key(src: Source) -> tuple[str, str]:
    return (_first(src.tags, "albumartist") or _first(src.tags, "artist")).casefold(), _first(src.tags, "album").casefold()


def multi_disc_albums(sources: Iterable[Source]) -> set[tuple[str, str]]:
    """Albums (by album artist + album) that span more than one disc."""
    out = set()
    for s in sources:
        disc = _first(s.tags, "discnumber")
        if (_number(disc) or 1) > 1 or (_total(disc) or 1) > 1:
            out.add(album_key(s))
    return out


def load_pattern(file: Path) -> str:
    """The pattern saved in the config folder, or the default."""
    import json

    try:
        pattern = json.loads(file.read_text("utf-8")).get("pattern")
        return check_pattern(pattern) if isinstance(pattern, str) else DEFAULT_PATTERN
    except (OSError, ValueError, AttributeError):
        return DEFAULT_PATTERN


def save_pattern(file: Path, pattern: str) -> None:
    import json
    import tempfile

    pattern = check_pattern(pattern)
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".organize-", dir=file.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pattern": pattern}, f, indent=2)
    os.replace(tmp, file)



Root = Path | Callable[[str], Path]  # the music folder, or a resolver that also knows "@inbox/..."


def _at(root: Root, rel: str) -> Path:
    if callable(root):
        return root(rel)
    return root / rel if rel else root


def _is_top(folder: str) -> bool:
    """The music folder itself, or a root alias like "@inbox": never removed."""
    return folder == "" or ("/" not in folder and folder.startswith("@"))

_NUMBERING = re.compile(r"^\s*\d{1,3}(?:[-.]\d{1,3})?(?:\s*[-.]\s*|\s+|_)")  # "02 ", "1-02 ", "02. ", "02 - "


def _song_key(stem: str) -> str:
    return " ".join(_NUMBERING.sub("", stem).casefold().split())


def _same_song_there(dst_path: Path, seen: dict[Path, dict[str, str]]) -> str | None:
    """A file already in ``dst_path``'s folder that is the same song in another format ("02 Dreams.flac"
    for "02 Dreams.mp3", or "1-02 Dreams.flac" with other numbering). Same-format files are never
    counted: two tracks can share a title ("Interlude")."""
    folder = dst_path.parent
    if folder not in seen:
        found: dict[str, str] = {}
        try:
            for e in os.scandir(folder):
                ext = os.path.splitext(e.name)[1].lower()
                if ext in SUPPORTED_EXTENSIONS and e.is_file():
                    found.setdefault(f"{_song_key(os.path.splitext(e.name)[0])}\0{ext}", e.name)
        except OSError:
            pass
        seen[folder] = found
    key, ext = _song_key(dst_path.stem), dst_path.suffix.lower()
    if not key:
        return None
    return next((name for k, name in seen[folder].items() if k.split("\0")[0] == key and k.split("\0")[1] != ext), None)


# --- Planning -------------------------------------------------------------------------------


@dataclass
class Move:
    src: str
    dst: str
    status: str  # "move", "same" (already there), "conflict", "error"
    reason: str = ""
    companions: list[tuple[str, str]] = field(default_factory=list)  # (src, dst) carried along

    def to_dict(self) -> dict:
        return {"src": self.src, "dst": self.dst, "status": self.status, "reason": self.reason,
                "companions": [{"src": a, "dst": b} for a, b in self.companions]}


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _has_audio(folder: Path, limit: int = 2000) -> bool:
    seen = 0
    for _dirpath, _dirs, files in os.walk(folder):
        for f in files:
            seen += 1
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS or seen > limit:
                return True
    return False


def plan_moves(root: Root, sources: list[Source], pattern: str) -> list[Move]:
    """Where each file would go. Reads nothing but names; writes nothing."""
    check_pattern(pattern)
    multi = multi_disc_albums(sources)
    moves: list[Move] = []
    claimed: dict[str, str] = {}  # destination (case-folded) -> source that takes it
    folder_songs: dict[Path, dict[str, str]] = {}  # songs already in each destination folder
    needs_names = any(t.split("|")[0].strip().lower() in ("albumartist", "artist", "album")
                      for t in _TOKEN.findall(pattern))
    for s in sources:
        if needs_names and not s.placeable():
            moves.append(Move(s.rel, s.rel, "keep", "Not enough tags to place it (no artist or album), so it stays where it is"))
            continue
        try:
            dst = render(pattern, s, album_key(s) in multi)
        except PatternError as exc:
            moves.append(Move(s.rel, s.rel, "error", str(exc)))
            continue
        src_path, dst_path = _at(root, s.rel), _at(root, dst)
        if dst == s.rel:
            moves.append(Move(s.rel, dst, "same"))
            continue
        key = dst.casefold()  # SMB and macOS shares don't tell "a" from "A"
        if key in claimed:
            moves.append(Move(s.rel, dst, "conflict", f"Same new name as {claimed[key].rsplit('/', 1)[-1]}"))
            continue
        if os.path.lexists(dst_path) and not _same_file(src_path, dst_path):
            moves.append(Move(s.rel, dst, "conflict", "A different file already has that name"))
            continue
        twin = _same_song_there(dst_path, folder_songs)
        if twin:
            # "02 Dreams.mp3" next to "02 Dreams.flac" would be the same song twice in one album.
            moves.append(Move(s.rel, dst, "conflict", f"The same song is already there as {twin}"))
            continue
        claimed[key] = s.rel
        moves.append(Move(s.rel, dst, "move"))

    taken = {m.dst.casefold() for m in moves if m.status in ("move", "same")}
    # Sidecars (song.lrc) follow their audio file.
    for m in moves:
        if m.status != "move":
            continue
        src_stem = os.path.splitext(m.src)[0]
        dst_stem = os.path.splitext(m.dst)[0]
        for suffix in SIDECAR_SUFFIXES:
            side = _at(root, src_stem + suffix)
            new = dst_stem + suffix
            if side.is_file() and not os.path.lexists(_at(root, new)) and new.casefold() not in taken:
                m.companions.append((src_stem + suffix, new))
                taken.add(new.casefold())

    # The album's other files (cover.jpg, booklet.pdf, logs, scans/) move along
    # when every audio file in their folder goes to one new folder.
    by_folder: dict[str, list[Move]] = {}
    for m in moves:
        by_folder.setdefault(m.src.rsplit("/", 1)[0] if "/" in m.src else "", []).append(m)
    sidecars = {a for m in moves for a, _ in m.companions}
    for folder, group in by_folder.items():
        dests = {m.dst.rsplit("/", 1)[0] if "/" in m.dst else "" for m in group}
        if len(dests) != 1 or any(m.status != "move" for m in group) or _is_top(folder):
            continue
        new_folder = dests.pop()
        if new_folder == folder:
            continue
        audio_here = {m.src for m in group}
        try:
            entries = list(os.scandir(_at(root, folder)))
        except OSError:
            continue
        audio_in_folder = {f"{folder}/{e.name}" for e in entries
                           if e.is_file() and Path(e.name).suffix.lower() in SUPPORTED_EXTENSIONS}
        if audio_in_folder - audio_here:
            continue  # some audio here isn't part of this move: leave the extras alone
        carrier = group[0]
        for e in sorted(entries, key=lambda e: e.name):
            rel = f"{folder}/{e.name}"
            if e.name.startswith(".") or rel in audio_here or rel in sidecars:
                continue
            if e.is_dir(follow_symlinks=False) and _has_audio(Path(e.path)):
                continue  # e.g. "CD2/": its own files move by themselves
            new = f"{new_folder}/{e.name}" if new_folder else e.name
            if os.path.lexists(_at(root, new)) or new.casefold() in taken:
                continue  # never overwrite; it just stays where it is
            carrier.companions.append((rel, new))
            taken.add(new.casefold())
    return moves


# --- Moving -----------------------------------------------------------------------------------

_move_lock = threading.Lock()  # one organize at a time: name checks and moves stay consistent


@dataclass
class MoveResult:
    src: str
    dst: str
    ok: bool
    error: str | None = None
    moved: list[tuple[str, str]] = field(default_factory=list)  # every (src, dst) actually moved


def _move_one(root: Root, src: str, dst: str) -> None:
    a, b = _at(root, src), _at(root, dst)
    if not os.path.lexists(a):
        raise FileNotFoundError("It's no longer there")
    if os.path.lexists(b) and not _same_file(a, b):
        raise FileExistsError("A different file already has that name")
    b.parent.mkdir(parents=True, exist_ok=True)
    if not a.is_dir() and not _same_file(a, b) and _link_then_unlink(a, b):
        return
    try:
        os.rename(a, b)  # same filesystem: instant, and the file itself is never rewritten
    except OSError as exc:
        if exc.errno != errno.EXDEV:  # another disk or mount (e.g. the inbox folder)
            raise
        _copy_then_remove(a, b)


def _link_then_unlink(a: Path, b: Path) -> bool:
    """Move a file without any chance of replacing one that appeared at ``b`` a moment ago
    (a plain rename would silently overwrite it). True when done; False when hard links
    aren't possible here (another disk, exFAT, some network shares), so the caller renames."""
    try:
        os.link(a, b, follow_symlinks=False)
    except FileExistsError:
        raise FileExistsError("A different file already has that name") from None
    except OSError:
        return False
    try:
        os.unlink(a)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(b)  # couldn't let go of the old name: put things back as they were
        raise
    return True


def _copy_then_remove(a: Path, b: Path) -> None:
    """Move across disks: copy to a temporary name next to the target, check
    it, give it its real name, and only then delete the original."""
    # A short temporary name: the real one may already be at the 255-byte limit.
    tmp = b.with_name(f".codetta-move-{os.getpid()}-{secrets.token_hex(4)}{b.suffix[:16]}")
    try:
        if a.is_dir() and not a.is_symlink():
            shutil.copytree(a, tmp, symlinks=True)
            if sum(1 for _ in tmp.rglob("*")) != sum(1 for _ in a.rglob("*")):
                raise OSError("The copy came out incomplete")
        else:
            shutil.copy2(a, tmp, follow_symlinks=False)
            if tmp.stat().st_size != a.stat().st_size:
                raise OSError("The copy came out the wrong size")
        if os.path.lexists(b):
            raise FileExistsError("A different file already has that name")
        os.rename(tmp, b)
    except BaseException:
        if tmp.is_dir() and not tmp.is_symlink():
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            tmp.unlink(missing_ok=True)
        raise
    if a.is_dir() and not a.is_symlink():
        shutil.rmtree(a)
    else:
        a.unlink()


def remove_empty_dirs(root: Root, folders: Iterable[str]) -> None:
    """Remove folders a move left empty (and their empty parents), never the
    music folder or the inbox folder themselves."""
    for folder in sorted(set(folders), key=lambda f: -f.count("/")):
        while not _is_top(folder):
            try:
                _at(root, folder).rmdir()  # only succeeds when empty
            except OSError:
                break
            folder = folder.rsplit("/", 1)[0] if "/" in folder else ""


def apply_moves(root: Root, moves: list[Move]) -> list[MoveResult]:
    """Do the planned moves. Each file is moved on its own; one failure doesn't stop the rest."""
    results = []
    left: list[str] = []
    with _move_lock:
        for m in moves:
            if m.status != "move":
                continue
            r = MoveResult(m.src, m.dst, ok=False)
            try:
                with file_lock(_at(root, m.src)):  # never while that file is being saved
                    _move_one(root, m.src, m.dst)
                r.ok = True
                r.moved.append((m.src, m.dst))
                left.append(m.src.rsplit("/", 1)[0] if "/" in m.src else "")
            except OSError as exc:
                r.error = exc.strerror if getattr(exc, "strerror", None) else str(exc)
            if r.ok:
                for a, b in m.companions:
                    try:
                        _move_one(root, a, b)
                        r.moved.append((a, b))
                        left.append(a.rsplit("/", 1)[0] if "/" in a else "")
                    except OSError:
                        pass  # an extra that can't move stays where it is
            results.append(r)
        remove_empty_dirs(root, left)
    return results


def undo_moves(root: Root, moves: list[list[str]]) -> tuple[list[tuple[str, str, bool, str | None]], list[list[str]]]:
    """Move files back. Returns ([(original src, dst, ok, error)], moves done in reverse)."""
    report, reverse, left = [], [], []
    with _move_lock:
        for src, dst in reversed(moves):  # companions first, then their audio file, in reverse order
            try:
                if not os.path.lexists(_at(root, dst)):
                    raise FileNotFoundError("Moved or deleted since, so it was left alone")
                if os.path.lexists(_at(root, src)):
                    raise FileExistsError("Something else now has the old name, so it was left alone")
                with file_lock(_at(root, dst)):
                    _move_one(root, dst, src)
                reverse.append([dst, src])
                left.append(dst.rsplit("/", 1)[0] if "/" in dst else "")
                report.append((src, dst, True, None))
            except OSError as exc:
                report.append((src, dst, False, str(exc) if not getattr(exc, "strerror", None) else exc.strerror))
        remove_empty_dirs(root, left)
    reverse.reverse()
    return report, reverse



REPLACED_DAYS = 30  # like "Recently Deleted": an album an upgrade replaced is kept this long


def prune_replaced(folder: Path, days: int = REPLACED_DAYS, now: float | None = None) -> int:
    """Delete albums set aside by upgrades ("replaced/<YYYYmmdd-HHMMSS>/...") once
    they're older than ``days``. Only ever touches folders named like that. Returns
    how many were removed."""
    import shutil
    import time as _time
    from datetime import datetime as _dt

    now = _time.time() if now is None else now
    removed = 0
    try:
        entries = list(folder.iterdir())
    except OSError:
        return 0
    for entry in entries:
        try:
            when = _dt.strptime(entry.name, "%Y%m%d-%H%M%S").timestamp()
        except ValueError:
            continue  # not one of ours
        if entry.is_dir() and not entry.is_symlink() and now - when > days * 86400:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed
