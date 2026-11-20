"""Organize: rename and move files from their tags."""
from __future__ import annotations

from fastapi import HTTPException

from codetta.core.engine import MetadataError
from codetta.core.library import LibraryPathError, TooManyFilesError, audio_files
from codetta.core.organize import (
    DEFAULT_PATTERN,
    Move,
    PatternError,
    Source,
    apply_moves,
    check_pattern,
    load_pattern,
    plan_moves,
    render,
    save_pattern,
)
from codetta.core.organize import (
    PRESETS as ORGANIZE_PRESETS,
)
from codetta.web.common import MAX_ORGANIZE, OrganizeIn, PatternIn, _name, _unique


def register(app, shared) -> None:
    activity = shared.activity
    art_cache = shared.art_cache
    engine = shared.engine
    lib_index = shared.lib_index
    library = shared.library
    require_library = shared.require_library
    settings = shared.settings

    pattern_file = settings.config_dir / "organize.json"

    def organize_plan(body: OrganizeIn) -> tuple[str, list[Move]]:
        require_library()
        try:
            pattern = check_pattern(body.pattern) if body.pattern is not None else load_pattern(pattern_file)
        except PatternError as exc:
            raise HTTPException(422, str(exc)) from exc
        if body.folder is not None:
            try:
                rels = audio_files(library, body.folder, body.recursive, MAX_ORGANIZE)
            except TooManyFilesError as exc:
                raise HTTPException(422, str(exc)) from exc
        else:
            rels = _unique(body.paths)
        sources, errors = [], []
        for rel in rels:
            try:
                meta = engine.load_metadata(library.resolve(rel))
                sources.append(Source(rel, meta.tags, meta.format or ""))
            except (MetadataError, LibraryPathError, OSError) as exc:
                errors.append(Move(rel, rel, "error", str(exc)))
        return pattern, plan_moves(library.resolve, sources, pattern) + errors

    @app.get("/api/organize/settings")
    def organize_settings() -> dict:
        return {"pattern": load_pattern(pattern_file), "default": DEFAULT_PATTERN,
                "presets": [{"name": n, "pattern": p} for n, p in ORGANIZE_PRESETS]}

    @app.put("/api/organize/settings")
    def save_organize_settings(body: PatternIn) -> dict:
        try:
            save_pattern(pattern_file, body.pattern)
        except PatternError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        return organize_settings()

    @app.post("/api/organize/example")
    def organize_example(body: PatternIn) -> dict:
        """What the pattern makes of a sample track (for the live example while typing)."""
        try:
            check_pattern(body.pattern)
        except PatternError as exc:
            return {"ok": False, "error": str(exc)}
        sample = Source("Some Folder/track.flac", {
            "albumartist": ["Kōsei Mori"], "artist": ["Kōsei Mori"], "album": ["Northern Signal"],
            "title": ["Harbour Lights"], "tracknumber": ["3/10"], "discnumber": ["2/2"], "date": ["2021-04-09"],
            "genre": ["Ambient"], "label": ["Low Orbit Records"],
        }, "flac")
        return {"ok": True, "single": render(body.pattern, sample, False), "multi": render(body.pattern, sample, True)}

    @app.post("/api/organize/preview")
    def organize_preview(body: OrganizeIn) -> dict:
        """Where each file would go. Nothing is moved."""
        pattern, moves = organize_plan(body)
        counts = {k: sum(m.status == k for m in moves) for k in ("move", "same", "keep", "conflict", "error")}
        return {"pattern": pattern, "counts": counts, "extras": sum(len(m.companions) for m in moves),
                "moves": [m.to_dict() for m in moves]}

    @app.post("/api/organize/apply")
    def organize_apply(body: OrganizeIn) -> dict:
        """Rename and move the files (and their extras). One undoable activity entry."""
        pattern, moves = organize_plan(body)
        results = apply_moves(library.resolve, moves)
        moved = [pair for r in results if r.ok for pair in r.moved]
        ok = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        if results:
            target = _name(ok[0].dst) if len(ok) == 1 else f"{len(ok)} tracks"
            message = (f"Organized {target}" if not failed else
                       f"Organized {len(ok)} of {len(results)} tracks" if ok else "Couldn't organize the tracks")
            activity.add(
                "organize", message, ok=not failed,
                files=[r.dst for r in ok] + [r.src for r in failed],
                changes=[{"key": "location", "old": ok[0].src, "new": ok[0].dst}] if len(ok) == 1 else
                        [{"key": "pattern", "old": "", "new": pattern}],
                errors=[{"path": r.src, "error": r.error or ""} for r in failed],
                undo={"type": "moves", "moves": [list(p) for p in moved]} if moved else None,
            )
        lib_index.mark_dirty([p for pair in moved for p in pair if not p.startswith("@")])  # the index covers the library only
        art_cache.clear()
        return {
            "moved": len(ok), "failed": len(failed), "extras": len(moved) - len(ok),
            "results": [{"src": r.src, "dst": r.dst, "ok": r.ok, "error": r.error} for r in results],
            # Not attempted: the name is taken (maybe a duplicate) or the file couldn't be read.
            "held": [{"src": m.src, "dst": m.dst, "status": m.status, "reason": m.reason} for m in moves if m.status in ("conflict", "error", "keep")],
        }

    shared.share(organize_apply=organize_apply, organize_preview=organize_preview, pattern_file=pattern_file)
