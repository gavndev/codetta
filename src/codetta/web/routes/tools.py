"""Plugins, actions, find & replace and renaming folders."""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import HTTPException

from codetta.core.engine import MetadataError
from codetta.core.library import LibraryPathError, audio_files
from codetta.core.organize import Move, apply_moves, safe_name
from codetta.core.plugins import ActionError, PluginManager
from codetta.web.common import (
    MAX_PATHS_PER_REQUEST,
    REPLACE_FIELDS,
    ActionRunIn,
    FolderNewIn,
    FolderRenameIn,
    PluginToggleIn,
    ReplaceIn,
    _unique,
)


def register(app, shared) -> None:
    activity = shared.activity
    art_cache = shared.art_cache
    engine = shared.engine
    lib_index = shared.lib_index
    library = shared.library
    require_library = shared.require_library
    settings = shared.settings
    apply_per_file = shared.later("apply_per_file")  # defined in routes/activity.py

    plugins = PluginManager(settings.config_dir)

    @app.get("/api/plugins")
    def list_plugins() -> dict:
        """Installed plugins (built-in ones, and folders in <config>/plugins), and their actions."""
        with plugins.lock:
            return {"folder": str(plugins.dir), "plugins": [p.public() for p in plugins.plugins.values()],
                    "actions": [{"id": a.id, "label": a.label, "description": a.description, "fields": list(a.fields),
                                 "plugin": a.plugin} for a in plugins.actions.values()]}

    @app.put("/api/plugins/{plugin_id}")
    def toggle_plugin(plugin_id: str, body: PluginToggleIn) -> dict:
        """Turn a plugin on (its code is imported) or off."""
        try:
            info = plugins.set_enabled(plugin_id, body.enabled)
        except KeyError:
            raise HTTPException(404, "There's no plugin with that id (built-in ones are always on).") from None
        except OSError as exc:
            raise HTTPException(500, f"Could not save to the config folder: {exc}") from exc
        if info.error and body.enabled:
            raise HTTPException(422, f"{info.name} couldn't load: {info.error}")
        return list_plugins()

    @app.post("/api/actions/{action_id}/run")
    def run_action(action_id: str, body: ActionRunIn) -> dict:
        """Run an action (built-in or from a plugin) on tracks. ``dry_run`` (the default) shows
        what would change; otherwise it writes, as one undoable activity entry."""
        require_library()
        if action_id not in plugins.actions:
            raise HTTPException(404, "That action isn't available (is its plugin turned on?).")
        targets = _unique(body.paths) if body.paths else (
            audio_files(library, body.folder.strip("/"), False, MAX_PATHS_PER_REQUEST) if body.folder is not None else [])
        if not targets:
            raise HTTPException(422, "Choose some tracks or a folder.")
        plan, preview, unreadable = {}, [], 0
        for rel in targets:
            try:
                tags = engine.load_metadata(library.resolve(rel)).tags
            except (MetadataError, LibraryPathError, OSError):
                unreadable += 1
                continue
            try:
                changes = plugins.run_action(action_id, tags)
            except ActionError as exc:
                raise HTTPException(422, str(exc)) from exc
            if changes:
                plan[rel] = changes
                if len(preview) < 200:
                    preview.append({"path": rel, "changes": [{"key": k, "old": "; ".join(tags.get(k, [])),
                                                              "new": "; ".join(v or [])} for k, v in changes.items()]})
        out = {"tracks": len(targets), "changing": len(plan), "unreadable": unreadable, "preview": preview}
        if body.dry_run or not plan:
            return out
        label = plugins.actions[action_id].label
        done, failed = apply_per_file(plan, f"{label}: {len(plan)} track{'s' if len(plan) != 1 else ''}")
        return {**out, "changed": len(done), "failed": len(failed), "errors": failed[:20]}

    @app.post("/api/tracks/replace")
    def replace_in_tags(body: ReplaceIn) -> dict:
        """Find & replace in the tags of many tracks (these files, or a folder's). ``dry_run`` (the
        default) only shows what would change; otherwise it writes, as one undoable activity entry."""
        require_library()
        targets = _unique(body.paths) if body.paths else (
            audio_files(library, body.folder.strip("/"), False, MAX_PATHS_PER_REQUEST) if body.folder is not None else [])
        if not targets:
            raise HTTPException(422, "Choose some tracks or a folder.")
        try:
            pattern = re.compile(body.find if body.regex else re.escape(body.find), 0 if body.match_case else re.IGNORECASE)
            if body.regex:
                pattern.sub(body.replace, "")  # a bad \1 reference fails here, not half-way through
        except re.error as exc:
            raise HTTPException(422, f"That pattern doesn't work: {exc}") from exc
        fields = [f.lower() for f in body.fields] if body.fields else list(REPLACE_FIELDS)
        swap = (lambda m: m.expand(body.replace)) if body.regex else (lambda m: body.replace)
        plan: dict[str, dict] = {}
        preview, unreadable = [], 0
        for rel in targets:
            try:
                tags = engine.load_metadata(library.resolve(rel)).tags
            except (MetadataError, LibraryPathError, OSError):
                unreadable += 1
                continue
            changes, shown = {}, []
            for key in fields:
                old = tags.get(key) or []
                new = [pattern.sub(swap, v) for v in old]
                if new != old:
                    changes[key] = [v for v in new if v.strip()] or None
                    shown.append({"key": key, "old": "; ".join(old), "new": "; ".join(v for v in new if v.strip())})
            if changes:
                plan[rel] = changes
                if len(preview) < 200:
                    preview.append({"path": rel, "changes": shown})
        out = {"tracks": len(targets), "changing": len(plan), "unreadable": unreadable, "preview": preview}
        if body.dry_run or not plan:
            return out
        what = f"“{body.find}” → “{body.replace}”" if body.replace else f"removed “{body.find}”"
        done, failed = apply_per_file(plan, f"Find & replace: {what} in {len(plan)} track{'s' if len(plan) != 1 else ''}")
        return {**out, "changed": len(done), "failed": len(failed), "errors": failed[:20]}

    @app.post("/api/folders/new")
    def new_folder(body: FolderNewIn) -> dict:
        """Make an empty folder (undo removes it again while it's still empty)."""
        require_library()
        parent = body.parent.strip().strip("/")
        if parent.startswith("@"):
            raise HTTPException(422, "Choose a folder inside your music folder.")
        if not library.resolve(parent).is_dir():
            raise HTTPException(404, "That folder isn't there any more.")
        if not body.name.strip().strip("."):
            raise HTTPException(422, "Give the folder a name.")
        name = safe_name(body.name)
        rel = f"{parent}/{name}" if parent else name
        target = library.resolve(rel)
        if os.path.lexists(target):
            raise HTTPException(409, f"There's already something called “{name}” here.")
        try:
            target.mkdir()
        except OSError as exc:
            raise HTTPException(500, f"Couldn't make the folder: {exc.strerror or exc}") from exc
        activity.add("organize", f"Made a new folder “{name}”", files=[rel],
                     changes=[{"key": "folder", "old": "", "new": rel}],
                     undo={"type": "folder", "path": rel, "made": True})
        return {"path": rel}

    @app.post("/api/folders/rename")
    def rename_folder(body: FolderRenameIn) -> dict:
        """Rename a folder (each file is moved like Organize does: nothing overwritten, one undo)."""
        require_library()
        folder = body.path.strip().strip("/")
        if not folder or folder.startswith("@"):
            raise HTTPException(422, "Choose a folder inside your music folder.")
        src = library.resolve(folder)
        if not src.is_dir():
            raise HTTPException(404, "That folder isn't there any more.")
        if not body.name.strip().strip("."):
            raise HTTPException(422, "Give the folder a name.")
        name = safe_name(body.name)
        parent = folder.rsplit("/", 1)[0] if "/" in folder else ""
        dest = f"{parent}/{name}" if parent else name
        if dest == folder:
            return {"path": folder, "moved": 0, "failed": 0}
        target = library.resolve(dest)
        if target.exists() and not (dest.casefold() == folder.casefold() and target.samefile(src)):
            raise HTTPException(409, f"There's already a folder called “{name}” there.")
        moves = []
        for dirpath, _, names in os.walk(src):
            for n in sorted(names):
                rel = library.relative(Path(dirpath) / n)
                moves.append(Move(rel, dest + rel[len(folder):], "move"))
        if dest.casefold() == folder.casefold():  # only the case changes: go via a temporary name
            tmp = f"{dest}.codetta-rename"
            first = apply_moves(library.resolve, [Move(m.src, tmp + m.src[len(folder):], "move") for m in moves])
            moves = [Move(tmp + m.src[len(folder):], m.dst, "move") for m in moves]
            results = apply_moves(library.resolve, moves)
            pairs = [(a, d) for r1, r2 in zip(first, results) if r1.ok and r2.ok
                     for (a, _), (_, d) in zip(r1.moved, r2.moved)]
        else:
            results = apply_moves(library.resolve, moves)
            pairs = [pair for r in results if r.ok for pair in r.moved]
        failed = [r for r in results if not r.ok]
        for dirpath, _, _ in sorted(os.walk(src), key=lambda x: -len(x[0])):  # tidy what's left (empty folders)
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
        if pairs:
            activity.add("organize", f"Renamed folder “{folder.rsplit('/', 1)[-1]}” to “{name}”", ok=not failed,
                         files=[b for _, b in pairs], changes=[{"key": "folder", "old": folder, "new": dest}],
                         errors=[{"path": r.src, "error": r.error or ""} for r in failed],
                         undo={"type": "moves", "moves": [list(p) for p in pairs]})
        lib_index.mark_dirty([p for pair in pairs for p in pair])
        art_cache.clear()
        return {"path": dest, "moved": len(pairs), "failed": len(failed)}

    shared.share(rename_folder=rename_folder)
