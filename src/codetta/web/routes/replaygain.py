"""ReplayGain: measure tracks' loudness and write the tags players use to even out the volume."""

from __future__ import annotations

import math
import posixpath

from fastapi import HTTPException

from codetta.core.engine import MetadataError
from codetta.core.inbox import DISC_FOLDER
from codetta.core.library import LibraryPathError, TooManyFilesError, audio_files
from codetta.core.loudness import Measured, album, gain_text, tag_changes
from codetta.web.common import MAX_PATHS_PER_REQUEST, ReplayGainIn, _unique


def album_of(rel: str) -> str:
    """The album folder a track belongs to: its folder, or the one above a disc folder ("CD2")."""
    folder = posixpath.dirname(rel)
    if DISC_FOLDER.match(posixpath.basename(folder)):
        folder = posixpath.dirname(folder)
    return folder


def register(app, shared) -> None:
    engine = shared.engine
    library = shared.library
    meter = shared.meter
    require_library = shared.require_library
    apply_per_file = shared.later("apply_per_file")  # routes/activity.py

    @app.post("/api/replaygain")
    def replaygain(body: ReplayGainIn) -> dict:
        """Measure loudness (EBU R128, ReplayGain 2.0) and show the gain each track gets. ``dry_run``
        (the default) only measures; otherwise it writes the tags, as one undoable activity entry.
        Album mode treats each album folder (disc folders included) as one album."""
        require_library()
        if not meter.available:
            raise HTTPException(409, "ReplayGain needs ffmpeg, which isn't installed on this server "
                                     "(it's included in the Docker image).")
        try:
            targets = _unique(body.paths) if body.paths else (
                audio_files(library, body.folder.strip("/"), True, MAX_PATHS_PER_REQUEST) if body.folder is not None else [])
        except TooManyFilesError as exc:
            raise HTTPException(422, str(exc)) from exc
        except LibraryPathError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not targets:
            raise HTTPException(422, "Choose some tracks or a folder.")
        files = {}
        for rel in targets:
            if rel.startswith("@"):
                raise HTTPException(422, "Choose files or folders inside your music folder.")
            files[rel] = library.resolve(rel)
        results = meter.measure_many(list(files.values()))

        groups: dict[str, list[str]] = {}
        for rel in targets:
            groups.setdefault(album_of(rel) if body.mode == "album" else rel, []).append(rel)

        plan: dict[str, dict] = {}
        albums_out, failed = [], []
        for key, rels in groups.items():
            ok = {rel: r for rel in rels if isinstance(r := results[files[rel]], Measured)}
            for rel in rels:
                if rel not in ok:
                    failed.append({"path": rel, "error": str(results[files[rel]])})
            if not ok:
                continue
            whole = album(ok.values()) if body.mode == "album" else None
            tracks_out = []
            for rel, m in ok.items():
                try:
                    fmt = engine.load_metadata(files[rel]).format
                except (MetadataError, OSError) as exc:
                    failed.append({"path": rel, "error": library.message(exc)})
                    continue
                plan[rel] = tag_changes(fmt, m, whole)
                tracks_out.append({"path": rel, "loudness": _round(m.loudness), "gain": gain_text(m.loudness),
                                   "peak": round(m.peak, 6)})
            albums_out.append({"folder": key if body.mode == "album" else posixpath.dirname(key),
                               "loudness": _round(whole.loudness) if whole else None,
                               "gain": gain_text(whole.loudness) if whole else None, "tracks": tracks_out})
        out = {"mode": body.mode, "tracks": len(targets), "measured": len(plan), "failed": failed[:50],
               "albums": albums_out[:200]}
        if body.dry_run or not plan:
            return out
        done, errors = apply_per_file(plan, f"ReplayGain: {len(plan)} track{'s' if len(plan) != 1 else ''}"
                                            + (f" in {len(albums_out)} album{'s' if len(albums_out) != 1 else ''}"
                                               if body.mode == "album" else ""))
        return {**out, "changed": len(done), "write_failed": len(errors), "errors": errors[:20]}


def _round(x: float) -> float | None:
    return None if math.isinf(x) else round(x, 2)
