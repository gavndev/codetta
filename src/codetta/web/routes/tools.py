"""Plugins, actions, find & replace and renaming folders."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from fastapi import HTTPException

from codetta.core.library import is_special
from codetta.core.engine import MetadataError
from codetta.core.fromnames import PatternError, compile_pattern, suggest
from codetta.core.tracklist import pair, parse
from codetta.core.library import LibraryPathError, audio_files
from codetta.core.matchtags import TRACK_KEYS, album_tags, changes_for, shared_album_tags
from codetta.core.organize import Move, apply_moves, safe_name
from codetta.core.plugins import ActionError, PluginManager
from codetta.web.common import (
    MAX_PATHS_PER_REQUEST,
    REPLACE_FIELDS,
    ActionRunIn,
    FolderNewIn,
    CoverExportIn,
    FromNamesIn,
    TracklistIn,
    MatchTagsIn,
    WipeIn,
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
    art_store = shared.art_store

    plugins = PluginManager(settings.config_dir)

    @app.get("/api/plugins")
    def list_plugins() -> dict:
        """The built-in plugins and their actions (people's own plugins are paused for now)."""
        with plugins.lock:
            return {"folder": str(plugins.dir), "plugins": [p.public() for p in plugins.plugins.values()],
                    "actions": [{"id": a.id, "label": a.label, "description": a.description, "fields": list(a.fields),
                                 "plugin": a.plugin, "options": [o.public() for o in a.options]}
                                for a in plugins.actions.values()]}

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
                changes = plugins.run_action(action_id, tags, body.options)
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

    @app.post("/api/tags/from-names")
    def tags_from_names(body: FromNamesIn) -> dict:
        """Fill tags from file and folder names with a pattern ("{track} - {artist} - {title}"). With no
        pattern, Codetta suggests the one that fits these files best. ``dry_run`` (the default) only
        shows what would change; otherwise it writes, as one undoable activity entry."""
        require_library()
        targets = _unique(body.paths) if body.paths else (
            audio_files(library, body.folder.strip("/"), False, MAX_PATHS_PER_REQUEST) if body.folder is not None else [])
        if not targets:
            raise HTTPException(422, "Choose some tracks or a folder.")
        for rel in targets:
            if is_special(rel):
                raise HTTPException(422, "Choose files or folders inside your music folder.")
            try:
                library.resolve(rel)
            except LibraryPathError as exc:
                raise HTTPException(400, str(exc)) from exc
        underscores = body.underscores
        if underscores is None:  # names like "microphone_verse_2018_4_17" use "_" for spaces; "01 - Song" don't
            stems = [rel.rsplit("/", 1)[-1].rsplit(".", 1)[0] for rel in targets]
            underscores = sum(s.count("_") > s.count(" ") for s in stems) * 2 > len(stems)
        names = [rel.replace("_", " ") if underscores else rel for rel in targets]
        text = body.pattern.strip() or suggest(names) or "{title}"
        try:
            pattern = compile_pattern(text)
        except PatternError as exc:
            raise HTTPException(422, str(exc)) from exc
        plan: dict[str, dict] = {}
        preview, unmatched, misses, unreadable = [], [], 0, 0
        for rel, name in zip(targets, names, strict=True):
            found = pattern.match(name)
            if found is None:
                misses += 1
                if len(unmatched) < 50:
                    unmatched.append(rel)
                continue
            try:
                tags = engine.load_metadata(library.resolve(rel)).tags
            except (MetadataError, LibraryPathError, OSError):
                unreadable += 1
                continue
            changes, shown = {}, []
            for key, value in found.items():
                old = tags.get(key) or []
                if old == [value] or (body.keep_existing and any(v.strip() for v in old)):
                    continue
                changes[key] = [value]
                shown.append({"key": key, "old": "; ".join(old), "new": value})
            if changes:
                plan[rel] = changes
                if len(preview) < 200:
                    preview.append({"path": rel, "changes": shown})
        out = {"pattern": text, "suggested": not body.pattern.strip(), "underscores": underscores, "tracks": len(targets),
               "matched": len(targets) - misses, "unmatched": unmatched, "unmatched_count": misses, "changing": len(plan), "unreadable": unreadable, "preview": preview}
        if body.dry_run or not plan:
            return out
        done, failed = apply_per_file(plan, f"Tags from file names: {len(plan)} track{'s' if len(plan) != 1 else ''}")
        return {**out, "changed": len(done), "failed": len(failed), "errors": failed[:20]}

    def _number(values) -> int | None:
        m = re.match(r"\s*(\d+)", (values or [""])[0])
        return int(m.group(1)) if m else None

    @app.post("/api/tags/tracklist")
    def tags_from_tracklist(body: TracklistIn) -> dict:
        """Titles (and numbers, discs, artists) from a pasted tracklist, paired with these files by
        number or in order. ``dry_run`` (the default) only shows the pairing; otherwise it writes, as one
        undoable activity entry."""
        require_library()
        targets = _unique(body.paths) if body.paths else (
            audio_files(library, body.folder.strip("/"), True, MAX_PATHS_PER_REQUEST) if body.folder is not None else [])
        if not targets:
            raise HTTPException(422, "Choose some tracks or a folder.")
        parsed = parse(body.text, body.artist_first)
        if not parsed.tracks:
            raise HTTPException(422, "Codetta couldn't find any tracks in that text. Paste one track per line.")
        files, loaded = [], {}
        for rel in targets:
            if is_special(rel):
                raise HTTPException(422, "Choose files or folders inside your music folder.")
            try:
                meta = engine.load_metadata(library.resolve(rel))
            except LibraryPathError as exc:
                raise HTTPException(400, str(exc)) from exc
            except (MetadataError, OSError):
                continue
            loaded[rel] = meta.tags
            files.append((rel, _number(meta.tags.get("discnumber")), _number(meta.tags.get("tracknumber")), meta.duration))
        # Unnumbered files go in the order they're listed (by disc, number, then name), like a player would.
        files.sort(key=lambda f: (f[1] or 1, f[2] or 10_000, f[0]))
        pairs = pair(files, parsed.tracks)
        plan: dict[str, dict] = {}
        preview = []
        used = set()
        for i, p in enumerate(pairs):
            if p.track is None:
                preview.append({"path": p.path, "line": None, "changes": [], "warning": "No line for this file"})
                continue
            used.add(id(p.track))
            tags = loaded[p.path]
            want = {"title": p.track.title}
            if body.numbers:
                want["tracknumber"] = str(p.track.number or i + 1)
                if p.track.disc:
                    want["discnumber"] = str(p.track.disc)
            if p.track.artist:
                want["artist"] = p.track.artist
            changes, shown = {}, []
            for key, value in want.items():
                old = tags.get(key) or []
                if key in ("tracknumber", "discnumber") and _number(old) == int(value):
                    continue
                if old != [value]:
                    changes[key] = [value]
                    shown.append({"key": key, "old": "; ".join(old), "new": value})
            if changes:
                plan[p.path] = changes
            preview.append({"path": p.path, "line": p.track.line, "changes": shown, "warning": p.warning})
        leftover = [t.line for t in parsed.tracks if id(t) not in used]
        out = {"tracks": len(files), "lines": len(parsed.tracks), "artist_first": parsed.artist_first,
               "changing": len(plan), "preview": preview[:300], "leftover": leftover[:50],
               "warnings": sum(1 for p in pairs if p.warning)}
        if body.dry_run or not plan:
            return out
        done, failed = apply_per_file(plan, f"Tracklist: {len(plan)} track{'s' if len(plan) != 1 else ''}")
        return {**out, "changed": len(done), "failed": len(failed), "errors": failed[:20]}

    @app.post("/api/covers/export")
    def export_covers(body: CoverExportIn) -> dict:
        """Save each album's embedded cover as cover.jpg (or folder.jpg / front.jpg) in its folder, for
        players that look for a file. Disc folders count as part of their album. An image file of that
        name already there is kept unless ``replace``. ``dry_run`` (the default) only shows the plan;
        otherwise it writes, as one undoable activity entry."""
        from codetta.web.routes.replaygain import album_of
        require_library()
        targets = _unique(body.paths) if body.paths else (
            audio_files(library, body.folder.strip("/"), True, MAX_PATHS_PER_REQUEST) if body.folder is not None else [])
        if not targets:
            raise HTTPException(422, "Choose some tracks or a folder.")
        albums: dict[str, list[str]] = {}
        for rel in targets:
            if is_special(rel):
                raise HTTPException(422, "Choose files or folders inside your music folder.")
            try:
                library.resolve(rel)
            except LibraryPathError as exc:
                raise HTTPException(400, str(exc)) from exc
            albums.setdefault(album_of(rel), []).append(rel)
        plan, preview = [], []
        for folder, rels in albums.items():
            art = None
            for rel in rels[:50]:  # the first track with a cover
                try:
                    art = engine.read_artwork(library.resolve(rel))
                except (MetadataError, OSError):
                    art = None
                if art:
                    break
            row = {"folder": folder, "tracks": len(rels)}
            if not art:
                preview.append({**row, "status": "no_cover"})
                continue
            name = body.name + (".png" if art.mime == "image/png" else ".jpg")
            target_rel = f"{folder}/{name}" if folder else name
            target = library.resolve(target_rel)
            try:
                same = sorted(e.name for e in target.parent.iterdir()
                              if e.is_file() and e.stem.lower() == body.name and e.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
            except OSError:
                same = []
            info = {**row, "file": name, "width": art.width, "height": art.height, "size": len(art.data)}
            if target.is_file() and target.read_bytes() == art.data:
                preview.append({**info, "status": "same"})
                continue
            if same and not body.replace:
                preview.append({**info, "status": "exists", "existing": same[0]})
                continue
            status = "replace" if target.exists() else "write"
            preview.append({**info, "status": status})
            plan.append((target_rel, target, art.data, rels))
        counts = {s: sum(1 for p in preview if p["status"] == s) for s in ("write", "replace", "exists", "same", "no_cover")}
        out = {"albums": len(albums), "counts": counts, "writing": len(plan), "preview": preview[:300]}
        if body.dry_run or not plan:
            return out
        undo_files, errors, touched = {}, [], []
        for target_rel, target, data, rels in plan:
            try:
                before = art_store.save(target.read_bytes()) if target.is_file() else None
                fd, tmp = tempfile.mkstemp(prefix=".codetta-", dir=target.parent)
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(data)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, target)
                except BaseException:
                    Path(tmp).unlink(missing_ok=True)
                    raise
                os.chmod(target, 0o644)
                undo_files[target_rel] = {"before": before, "after": art_store.save(data)}
                touched += rels[:1]
            except OSError as exc:
                errors.append({"path": target_rel, "error": exc.strerror or str(exc)})
        if undo_files:
            n = len(undo_files)
            activity.add("art", ("Exported covers: 1 album" if n == 1 else f"Exported covers: {n} albums"), ok=not errors,
                         files=list(undo_files), errors=errors[:20], undo={"type": "files", "files": undo_files},
                         changes=[{"key": "cover", "old": "", "new": rel} for rel in list(undo_files)[:50]])
            lib_index.mark_dirty(touched)  # Lidarr and the music server hear about it
        return {**out, "written": len(undo_files), "failed": len(errors), "errors": errors[:20]}

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

    @app.post("/api/tags/match")
    def match_album_tags(body: MatchTagsIn) -> dict:
        """Match album tags: copy every album-wide tag (not title, track artist, numbers, lyrics,
        song IDs...) from one track, or from what a folder's other tracks share, onto these
        tracks, so music players group them as one album. ``dry_run`` (the default) only shows
        what would change; otherwise it writes, as one undoable activity entry."""
        require_library()
        targets = _unique(body.paths)
        chosen = set(targets)

        def read(rel: str) -> dict[str, list[str]]:
            return engine.load_metadata(library.resolve(rel)).tags

        try:
            if body.track:
                if body.track in chosen:
                    raise HTTPException(422, "Pick a track that isn't one of the ones being changed.")
                reference = album_tags(read(body.track))
                source = body.track.rsplit("/", 1)[-1]
            else:
                folder = (body.folder if body.folder is not None else targets[0].rpartition("/")[0]).strip("/")
                others = [rel for rel in audio_files(library, folder, False, MAX_PATHS_PER_REQUEST) if rel not in chosen]
                if not others:
                    raise HTTPException(422, "There are no other tracks in that folder to match.")
                tags = []
                for rel in others:
                    try:
                        tags.append(read(rel))
                    except (MetadataError, LibraryPathError, OSError):
                        continue
                reference = shared_album_tags(tags)
                source = folder.rsplit("/", 1)[-1] or "Library"
        except (MetadataError, LibraryPathError, OSError) as exc:
            raise HTTPException(422, library.message(exc)) from exc
        if not reference:
            raise HTTPException(422, "The tracks to match have no album tags to copy.")
        plan: dict[str, dict] = {}
        preview, unreadable = [], 0
        for rel in targets:
            try:
                tags = read(rel)
            except (MetadataError, LibraryPathError, OSError):
                unreadable += 1
                continue
            changes = changes_for(tags, reference, body.remove_extra)
            if changes:
                plan[rel] = changes
                if len(preview) < 200:
                    preview.append({"path": rel, "changes": [
                        {"key": k, "old": "; ".join(tags.get(k) or []), "new": "; ".join(v or [])} for k, v in sorted(changes.items())]})
        out = {"tracks": len(targets), "changing": len(plan), "unreadable": unreadable, "preview": preview,
               "reference": reference, "source": source, "kept": sorted(TRACK_KEYS)}
        if body.dry_run or not plan:
            return out
        n = len(plan)
        done, failed = apply_per_file(plan, f"Matched album tags to “{source}”: {n} track{'s' if n != 1 else ''}")
        return {**out, "changed": len(done), "failed": len(failed), "errors": failed[:20]}

    @app.post("/api/tags/wipe")
    def wipe_tags(body: WipeIn) -> dict:
        """Remove every tag from these tracks (or a folder's), leaving the audio and the cover.
        ``dry_run`` (the default) only counts; otherwise it writes, as one undoable activity entry."""
        require_library()
        targets = _unique(body.paths) if body.paths else (
            audio_files(library, body.folder.strip("/"), False, MAX_PATHS_PER_REQUEST) if body.folder is not None else [])
        if not targets:
            raise HTTPException(422, "Choose some tracks or a folder.")
        plan: dict[str, dict] = {}
        unreadable = 0
        for rel in targets:
            try:
                tags = engine.load_metadata(library.resolve(rel)).tags
            except (MetadataError, LibraryPathError, OSError):
                unreadable += 1
                continue
            if tags:
                plan[rel] = dict.fromkeys(tags)
        out = {"tracks": len(targets), "changing": len(plan), "unreadable": unreadable,
               "tags": sum(len(c) for c in plan.values())}
        if body.dry_run or not plan:
            return out
        done, failed = apply_per_file(plan, f"Wiped all tags from {len(plan)} track{'s' if len(plan) != 1 else ''}")
        return {**out, "changed": len(done), "failed": len(failed), "errors": failed[:20]}

    @app.post("/api/folders/new")
    def new_folder(body: FolderNewIn) -> dict:
        """Make an empty folder (undo removes it again while it's still empty)."""
        require_library()
        parent = body.parent.strip().strip("/")
        if is_special(parent):
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
        if not folder or is_special(folder):
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
