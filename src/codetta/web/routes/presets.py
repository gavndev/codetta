"""Tag Presets."""
from __future__ import annotations

from fastapi import HTTPException

from codetta.core.presets import Preset, apply_preset, apply_preset_to_folder, slugify
from codetta.web.common import (
    ApplyIn,
    ApplyResultOut,
    PresetIn,
    PresetOut,
    _exists,
    _log_preset,
    _to_preset_out,
    _unique,
)


def register(app, shared) -> None:
    activity = shared.activity
    engine = shared.engine
    lib_index = shared.lib_index
    library = shared.library
    require_library = shared.require_library
    result_out = shared.result_out
    store = shared.store

    @app.get("/api/presets", response_model=list[PresetOut])
    def list_presets():
        return [_to_preset_out(lo) for lo in store.list()]

    @app.post("/api/presets", response_model=PresetOut)
    def save_preset(body: PresetIn):
        """Create a preset, or edit one (pass ``previous_name`` when editing)."""
        preset = Preset(name=body.name, tags=body.tags, description=body.description)
        editing = body.previous_name is not None
        renamed = editing and slugify(body.previous_name) != preset.slug
        if (not editing or renamed) and _exists(store, preset.name):
            raise HTTPException(409, f"A preset named '{preset.name}' already exists")
        try:
            store.save(preset)
        except OSError as exc:
            raise HTTPException(500, f"Could not save preset: {exc}") from exc
        if renamed and _exists(store, body.previous_name):
            store.delete(body.previous_name)
        return _to_preset_out(preset)

    @app.delete("/api/presets/{name}", status_code=204)
    def delete_preset(name: str):
        store.delete(name)

    @app.post("/api/presets/apply", response_model=list[ApplyResultOut])
    def apply(body: ApplyIn):
        """Apply a preset to files or a folder. ``dry_run`` (default) only previews."""
        require_library()
        preset = store.get(body.name)
        if body.folder is not None:
            results = apply_preset_to_folder(
                engine,
                preset,
                library.resolve(body.folder),
                mode=body.mode,
                recursive=body.recursive,
                dry_run=body.dry_run,
            )
        elif body.paths:
            paths = [library.resolve(p) for p in _unique(body.paths)]
            results = apply_preset(engine, preset, paths, mode=body.mode, dry_run=body.dry_run)
        else:
            raise HTTPException(400, "Choose some files or a folder to apply the preset to")
        out = [result_out(r) for r in results]
        if not body.dry_run:
            undo_files = {
                library.relative(r.path): {"before": r.previous, "after": r.applied}
                for r in results if not r.error and r.applied
            }
            _log_preset(activity, preset.name, body.mode, out,
                         undo={"type": "tags", "files": undo_files} if undo_files else None)
            lib_index.mark_dirty(o.path for o in out if not o.error and o.applied)
        return out
