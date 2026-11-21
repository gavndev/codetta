// The tag editor: fields, raw tags, copy & paste, suggestions, hints, lyrics and album art.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { t as tr } from "./i18n.js";
import { $, ask, h, icon, playOut, setKids } from "./dom.js";
import { api } from "./api.js";
import {
  baseName, els, first, fmtDuration, fmtLabel, plural, relativeToFolder, state, toast,
} from "./state.js";
import {
  folderCache, index, isSearch, replaceTrack, searchQuery, trackByPath, updateRowStates,
} from "./browse.js";
import { folderCovers, renderTracks } from "./tools.js";
import { refreshActivity, renderActivity } from "./activity.js";
import { canvasToBlob, decodeImage, showAuth } from "./account.js";

// ---- Editor -----------------------------------------------------------------------------------------

function editorTracks() {
  return (state.editor?.paths || []).map(trackByPath).filter(Boolean);
}

export function isDirty() {
  return pendingCount(state.editor) > 0;
}

export async function confirmDiscard() {
  if (!isDirty()) return true;
  return ask({
    title: "Discard unsaved changes?",
    message: "Your edits haven't been saved yet.",
    confirmLabel: "Discard", cancelLabel: "Keep editing", danger: true,
  });
}

export async function openEditor(paths) {
  if (state.editor && !(await confirmDiscard())) return;
  const tracks = paths.map(trackByPath).filter((t) => t && !t.error);
  if (!tracks.length) { toast("None of these files can be read", "error"); return; }
  const skipped = paths.length - tracks.length;
  state.editor = { paths: tracks.map((t) => t.path), changes: new Map(), extraKeys: [], errors: [] };
  if (skipped) state.editor.errors.push(`${plural(skipped, "file")} couldn't be read and won't be edited.`);
  els.editor.classList.remove("closing");
  els.editor.hidden = false;
  renderEditor();
  updateRowStates();
  renderActivity();
  refreshActivity();
  if (window.matchMedia("(max-width: 760px)").matches) document.body.style.overflow = "hidden";
  loadFullTags(state.editor);
}

/** Search results come from the index, which leaves out long or technical tags
 *  (lyrics, fingerprints, IDs). Read the real files before they're edited. */
async function loadFullTags(ed) {
  const partial = ed.paths.map(trackByPath).filter((t) => t?.partial).slice(0, 200);
  if (!partial.length) return;
  const queue = [...partial];
  const worker = async () => {
    for (let t = queue.shift(); t; t = queue.shift()) {
      try { replaceTrack(await api("GET", `/api/track?path=${encodeURIComponent(t.path)}`)); } catch { /* keep index data */ }
    }
  };
  await Promise.all(Array.from({ length: 6 }, worker));
  if (state.editor !== ed) return;
  const focused = document.activeElement?.id, start = document.activeElement?.selectionStart;
  renderEditor();
  const again = focused && document.getElementById(focused);
  if (again && again !== document.activeElement) {
    again.focus({ preventScroll: true });
    if (start != null && again.setSelectionRange) again.setSelectionRange(start, start);
  }
}

export function closeEditor(force = false) {
  if (!state.editor) return;
  if (!force && isDirty()) {
    confirmDiscard().then((ok) => { if (ok) closeEditor(true); });
    return;
  }
  clearPendingArt(state.editor);
  state.editor = null;
  playOut(els.editor, "closing", () => { if (!state.editor) els.editor.hidden = true; });
  document.body.style.overflow = "";
  updateRowStates();
}

/** For each tag key: the shared value across the edited tracks, or "mixed". */
function buildModel(tracks) {
  const known = state.fields.map((f) => f.key);
  const knownSet = new Set(known);
  const custom = new Set(state.editor.extraKeys);
  for (const t of tracks) for (const k of Object.keys(t.tags)) if (!knownSet.has(k)) custom.add(k);
  const model = new Map();
  for (const key of [...known, ...[...custom].sort()]) {
    const vals = tracks.map((t) => t.tags[key] || []);
    const joined = vals.map((v) => v.join("; "));
    const same = joined.every((j) => j === joined[0]);
    model.set(key, {
      value: same ? joined[0] : "",
      mixed: !same,
      present: joined.some((j) => j !== ""),
      multiValued: vals.some((v) => v.length > 1),
    });
  }
  return { model, custom: [...custom].sort() };
}

export function renderEditor() {
  const ed = state.editor;
  const tracks = editorTracks();
  if (!ed || !tracks.length) { closeEditor(true); return; }
  const { model, custom } = buildModel(tracks);
  ed.model = model;

  // Header
  if (tracks.length === 1) {
    const t = tracks[0];
    els.editorTitle.textContent = first(t, "title") || t.name;
    const byline = [(t.tags.artist || []).join(", "), first(t, "album")].filter(Boolean).join(" — ");
    els.editorTitle.translate = false; // the track's own title and artist: never translated
    els.editorSub.translate = !byline && !first(t, "title");
    els.editorSub.textContent = byline || (first(t, "title") ? relativeToFolder(t.path) : "No tags yet");
  } else {
    els.editorTitle.translate = els.editorSub.translate = true;
    els.editorTitle.textContent = `Editing ${tracks.length} tracks`;
    els.editorSub.textContent = "Only the fields you change are saved";
  }

  const parts = [artEl(tracks)];

  // File info
  if (tracks.length === 1) {
    const t = tracks[0];
    parts.push(h("div", { class: "file-info" },
      h("span", { class: "badge" }, fmtLabel(t.format)),
      t.duration != null && h("span", { class: "num" }, fmtDuration(t.duration)),
      t.bitrate && h("span", { class: "num" }, `${Math.round(t.bitrate / 1000)} kbps`),
      t.sample_rate && h("span", { class: "num" }, `${(t.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz`),
      t.channels && h("span", {}, t.channels === 1 ? "Mono" : t.channels === 2 ? "Stereo" : `${t.channels} ch`),
      h("span", { class: "path" }, t.path)));
  } else {
    const formats = [...new Set(tracks.map((t) => fmtLabel(t.format)))].join(", ");
    parts.push(h("div", { class: "file-info" }, h("span", {}, `${tracks.length} files · ${formats}`)));
  }

  for (const msg of ed.errors) parts.push(h("div", { class: "error-box", role: "alert" }, msg));

  // Field groups
  const groups = new Map();
  for (const f of state.fields) {
    if (!groups.has(f.group)) groups.set(f.group, []);
    groups.get(f.group).push(f);
  }
  if (custom.length) {
    groups.set("Custom", custom.map((key) => ({ key, label: key, group: "Custom", multi: false })));
  }

  for (const [name, fields] of groups) {
    const filled = fields.filter((f) => model.get(f.key)?.present).length;
    const changed = fields.some((f) => ed.changes.has(f.key));
    const details = h("details", { class: "group", open: name === "Basics" || name === "Custom" || filled > 0 || changed },
      h("summary", {}, h("span", {}, name, filled ? h("span", { class: "count" }, `${filled} set`) : null)));
    if (name === "Basics") {
      // Pair up short fields on wide screens.
      const byKey = Object.fromEntries(fields.map((f) => [f.key, f]));
      const used = new Set();
      for (const f of fields) {
        if (used.has(f.key)) continue;
        const pair = { tracknumber: "discnumber", date: "genre" }[f.key];
        if (pair && byKey[pair]) {
          details.append(h("div", { class: "row-2" }, fieldEl(byKey[f.key], model), fieldEl(byKey[pair], model)));
          used.add(pair);
        } else {
          details.append(fieldEl(f, model));
        }
        used.add(f.key);
      }
    } else {
      for (const f of fields) details.append(fieldEl(f, model));
    }
    parts.push(details);
  }

  parts.push(addTagEl(model));
  if (state.advanced && tracks.length === 1) parts.push(rawTagsEl(tracks[0]));
  setKids(els.editorForm, parts);
  renderToolbar();
  updateSaveButton();
}

// ---- Advanced mode: raw tags ----------------------------------------------------------------------

const rawCache = new Map(); // "path|mtime" -> /api/track/raw response
let rawOpen = false; // keep the section open while moving between tracks

function rawTagsEl(track) {
  const list = h("div", { class: "raw-list" });
  const details = h("details", { class: "group raw-group", open: rawOpen },
    h("summary", {}, h("span", {}, "Raw tags", h("span", { class: "count" }, "as stored in the file"))), list);
  const key = `${track.path}|${track.mtime}`;
  const show = (data) => {
    setKids(list,
      h("p", { class: "raw-system" }, data.system),
      data.entries.length ? data.entries.map((e) => h("div", { class: `raw-row raw-${e.kind}` },
        h("code", { class: "raw-name", dir: "ltr" }, e.name),
        h("span", { class: "raw-value", dir: "auto" }, e.value,
          e.length ? h("span", { class: "raw-more" }, ` (${e.length.toLocaleString()} characters)`) : null)))
        : h("p", { class: "hint" }, "This file has no tags."));
  };
  const load = async () => {
    if (rawCache.has(key)) { show(rawCache.get(key)); return; }
    setKids(list, h("p", { class: "loading" }, "Reading the file…"));
    try {
      const data = await api("GET", `/api/track/raw?path=${encodeURIComponent(track.path)}`);
      if (rawCache.size > 200) rawCache.clear();
      rawCache.set(key, data);
      show(data);
    } catch (err) {
      setKids(list, h("p", { class: "error-box" }, err.message));
    }
  };
  details.addEventListener("toggle", () => { rawOpen = details.open; if (details.open) load(); });
  if (rawOpen) load();
  return details;
}

export function setAdvanced(on) {
  state.advanced = on;
  try { localStorage.setItem("codetta-advanced", on ? "1" : "0"); } catch { /* per-browser preference only */ }
  if (state.editor) renderEditor();
  syncLogTile();
}

// Advanced mode: next to each field, how this file really stores it ("TPE1", "©ART", "ARTIST").
const tagNameCache = new Map(); // format -> {key: name | null}, or a pending promise

function editorFormat() {
  const formats = new Set((state.editor?.paths || []).map((p) => trackByPath(p)?.format).filter(Boolean));
  return formats.size === 1 ? [...formats][0] : null; // several formats at once: names would differ
}

function nativeTag(key) {
  if (!state.advanced) return null;
  const format = editorFormat();
  if (!format) return null;
  const names = tagNameCache.get(format);
  if (!names) {
    tagNameCache.set(format, api("GET", `/api/tagnames?format=${encodeURIComponent(format)}`)
      .then((r) => { tagNameCache.set(format, r.names); if (state.editor && editorFormat() === format) renderEditor(); })
      .catch(() => tagNameCache.delete(format)));
    return null;
  }
  if (names instanceof Promise) return null;
  if (!(key in names)) return null; // a tag Codetta has no fixed name for (custom): shown as typed
  const name = names[key];
  return name
    ? h("code", { class: "native-name", title: `Stored in this ${format.toUpperCase()} file as ${name}` }, name)
    : h("code", { class: "native-name none", title: `${format.toUpperCase()} files can't store this field` }, `not in ${format.toUpperCase()}`);
}

// Advanced mode: Codetta's own server log (what `docker logs` shows), live, at the bottom of Account.
const serverLog = { last: 0, timer: null };

export function syncLogTile() {
  const tile = $("#log-tile");
  if (!tile) return;
  tile.hidden = !state.advanced;
  if (!state.advanced) { tile.open = false; stopLogPolling(); }
}

export function stopLogPolling() {
  clearTimeout(serverLog.timer);
  serverLog.timer = null;
}

export async function pollLog() {
  stopLogPolling();
  const tile = $("#log-tile");
  if (!tile?.open || !$("#account-dialog").open) return;
  try {
    const r = await api("GET", `/api/logs?after=${serverLog.last}`);
    const list = $("#log-lines");
    const stick = list.scrollTop + list.clientHeight >= list.scrollHeight - 8; // follow new lines unless you scrolled up
    for (const line of r.lines) {
      const t = new Date(line.time * 1000);
      list.append(h("div", { class: `log-line ${line.level}` },
        h("span", { class: "log-time" }, t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })),
        h("span", { class: "log-level" }, line.level === "warning" ? "warn" : line.level),
        h("span", { class: "log-msg" }, line.message)));
    }
    while (list.childElementCount > 500) list.firstElementChild.remove();
    serverLog.last = r.last;
    $("#log-empty").hidden = list.childElementCount > 0;
    if (stick) list.scrollTop = list.scrollHeight;
  } catch { /* signed out or offline: try again on the next tick */ }
  serverLog.timer = setTimeout(pollLog, 2000);
}

// ---- Editor toolbar: copy & paste tags ---------------------------------------------------------

export function loadClipboard() {
  try { return JSON.parse(localStorage.getItem("codetta-clipboard")) || null; } catch { return null; }
}

function saveClipboard(clip) {
  state.clipboard = clip;
  try {
    if (clip) localStorage.setItem("codetta-clipboard", JSON.stringify(clip));
    else localStorage.removeItem("codetta-clipboard");
  } catch { /* private mode: clipboard just won't survive a reload */ }
}

export function fieldLabel(key) {
  if (key === "__art") return "Album art";
  return state.fieldMap.get(key)?.label || key;
}

/** The value a field currently shows (pending edit, or what's saved), as a list. */
function currentValues(key) {
  const ed = state.editor;
  const m = ed.model.get(key);
  const c = ed.changes.get(key);
  if (c) return c.remove ? [] : splitValue(key, c.value);
  if (!m || m.mixed || !m.present) return [];
  return splitValue(key, m.value);
}

function splitValue(key, text) {
  const value = text.trim();
  if (!value) return [];
  if (key === "lyrics") return [value]; // lyrics often contain ";", never split them
  const split = state.fieldMap.get(key)?.multi || state.editor?.model.get(key)?.multiValued;
  return split ? value.split(";").map((v) => v.trim()).filter(Boolean) : [value];
}

export function renderToolbar() {
  const ed = state.editor;
  const clip = state.clipboard;
  const clipKeys = clip ? Object.keys(clip.tags) : [];
  if (ed.copyMode) {
    const n = ed.copyKeys.size;
    setKids(els.toolbarLeft,
      h("button", { class: "btn small primary", type: "button", disabled: n === 0, onclick: finishCopy }, n ? `Copy ${n}` : "Copy"),
      h("button", { class: "btn small", type: "button", onclick: selectAllCopy }, "All"),
      h("button", { class: "btn small", type: "button", onclick: () => { ed.copyMode = false; renderEditor(); } }, "Cancel"));
  } else {
    setKids(els.toolbarLeft,
      h("button", { class: "btn small", type: "button", title: "Pick tags to copy, then paste them onto other tracks", onclick: startCopy }, icon("copy"), "Copy"),
      clipKeys.length ? h("span", { class: "paste-group" },
        h("button", {
          class: "btn small", type: "button", onclick: pasteTags,
          title: `Paste ${clipKeys.map(fieldLabel).join(", ")}${clip.from ? ` (from ${clip.from})` : ""}`,
        }, icon("paste"), `Paste ${clipKeys.length}`),
        h("button", { class: "icon-btn small", type: "button", "aria-label": "Clear copied tags", title: "Clear copied tags",
          onclick: () => { saveClipboard(null); renderToolbar(); } }, icon("close"))) : null);
  }
}

function startCopy() {
  const ed = state.editor;
  ed.copyMode = true;
  ed.copyKeys = new Set();
  renderEditor();
}

function selectAllCopy() {
  const ed = state.editor;
  for (const key of ed.model.keys()) if (currentValues(key).length) ed.copyKeys.add(key);
  renderEditor();
}

function finishCopy() {
  const ed = state.editor;
  const tags = {};
  for (const key of ed.copyKeys) {
    const values = currentValues(key);
    if (values.length) tags[key] = values;
  }
  const tracks = editorTracks();
  const from = tracks.length === 1 ? (first(tracks[0], "title") || tracks[0].name) : `${tracks.length} tracks`;
  saveClipboard({ tags, from });
  ed.copyMode = false;
  renderEditor();
  const keys = Object.keys(tags);
  toast(`Copied ${keys.map(fieldLabel).join(", ")}`, "success");
}

function pasteTags() {
  const ed = state.editor;
  const clip = state.clipboard;
  if (!ed || !clip) return;
  let n = 0;
  for (const [key, values] of Object.entries(clip.tags)) {
    if (!ed.model.has(key) && !ed.extraKeys.includes(key)) ed.extraKeys.push(key);
    const m = ed.model.get(key);
    const text = values.join("; ");
    if (m && !m.mixed && m.value === text) { ed.changes.delete(key); continue; } // already the same
    ed.changes.set(key, { value: text, remove: false });
    n++;
  }
  renderEditor();
  toast(n ? `Pasted ${plural(n, "tag")}. Review, then Save or Save to folder.` : "These tracks already have those values.");
}

// ---- Smart suggestions from the folder ----------------------------------------------------------------

// Tags that are usually the same across an album, so other tracks in the
// folder are good suggestions. Per-track tags (title, isrc, comment...) are left out.
const SMART_KEYS = new Set([
  "artist", "album", "albumartist", "discnumber", "date", "genre",
  "artists", "albumartists", "composer", "lyricist", "producer", "engineer", "mixer", "djmixer", "arranger", "conductor",
  "releasetype", "releasestatus", "label", "catalognumber", "barcode", "media", "originaldate", "releasecountry",
  "discsubtitle", "compilation", "mood", "language", "copyright", "grouping",
]);

/** Values other tracks in this folder use for ``key``: [{ value, note }], most common first. */
function folderSuggestions(key) {
  const tracks = (state.folder?.tracks || []).filter((t) => !t.error);
  if (key === "tracknumber") {
    // Suggest the track's position in the folder (files are in natural name order).
    const ed = state.editor;
    if (!ed || ed.paths.length !== 1) return [];
    const i = tracks.findIndex((t) => t.path === ed.paths[0]);
    return i < 0 ? [] : [{ value: `${i + 1}/${tracks.length}`, note: "Position in folder" }];
  }
  if (!SMART_KEYS.has(key)) return [];
  const counts = new Map();
  for (const t of tracks) {
    const v = (t.tags[key] || []).join("; ");
    if (v) counts.set(v, (counts.get(v) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 6)
    .map(([value, n]) => ({ value, note: `${plural(n, "track")} in folder` }));
}

/** Attach a suggestion dropdown to an input. Picking one fills the field (doesn't save). */
function attachSuggestions(input, key, box) {
  let items = [];
  let active = -1;

  const hide = () => { box.hidden = true; active = -1; };
  const apply = (value) => {
    input.value = value;
    input.dispatchEvent(new Event("input"));
    hide();
  };
  const render = () => {
    items = folderSuggestions(key).filter((s) => s.value !== input.value);
    if (!items.length || document.activeElement !== input) { hide(); return; }
    setKids(box,
      h("div", { class: "suggest-head" }, icon("spark"), "From this folder"),
      items.map((s, i) => h("button", {
        type: "button", class: `suggest-item${i === active ? " active" : ""}`, role: "option", tabindex: "-1",
        onpointerdown: (e) => e.preventDefault(), // keep focus in the input
        onclick: () => apply(s.value),
      }, h("span", { class: "suggest-value" }, s.value), h("span", { class: "suggest-note" }, s.note))));
    const wasHidden = box.hidden;
    box.hidden = false;
    // Near the bottom of the panel the list would sit under the activity log: scroll it into view.
    if (wasHidden) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };

  input.addEventListener("focus", render);
  input.addEventListener("input", () => { if (!box.hidden || document.activeElement === input) render(); });
  input.addEventListener("blur", () => setTimeout(hide, 120));
  input.addEventListener("keydown", (e) => {
    if (box.hidden || !items.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      render();
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      apply(items[active].value);
    } else if (e.key === "Escape") {
      e.stopPropagation(); // close the dropdown, not the editor
      hide();
    }
  });
}

// ---- Editor hints: dates and comma-separated lists ------------------------------------------------

// Fields where many libraries (and Navidrome's default settings) treat a comma
// as a separator: "Hip-Hop, Trap, Rap". Codetta saves them exactly as typed and
// treats each comma-separated part as its own value when filtering.
const COMMA_LIST_KEYS = new Set(["genre", "mood"]);

/** "Hip-Hop, Trap; Rap" -> ["Hip-Hop", "Trap", "Rap"] for comma-list fields. */
export function listParts(key, values) {
  if (!COMMA_LIST_KEYS.has(key)) return values;
  return values.flatMap((v) => v.split(/[,;]/)).map((v) => v.trim()).filter(Boolean);
}

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const EMOJI = /\p{Extended_Pictographic}/u;
const LRC_LINE = /^\s*\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]/;
const DATE_OK = /^\d{4}(-\d{2}(-\d{2})?)?$/;

/** Turn "October 23, 2026" or "2026/10/23" into "2026-10-23", if unambiguous. */
function suggestDate(text) {
  const v = text.trim();
  if (!v || DATE_OK.test(v)) return null;
  const pad = (n) => String(n).padStart(2, "0");
  const valid = (y, mo, d) => y >= 1000 && y <= 9999 && mo >= 1 && mo <= 12 && (!d || (d >= 1 && d <= 31));
  let m = v.match(/^(\d{4}-\d{2}-\d{2})[T ]/); // ISO with a time
  if (m) return m[1];
  m = v.match(/^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})$/);
  if (m && valid(+m[1], +m[2], +m[3])) return `${m[1]}-${pad(m[2])}-${pad(m[3])}`;
  const month = (v.toLowerCase().match(/[a-z]{3,}/g) || []).map((w) => MONTHS.indexOf(w.slice(0, 3))).find((i) => i >= 0);
  const nums = v.match(/\d+/g) || [];
  if (month !== undefined) {
    const year = nums.find((n) => n.length === 4);
    const day = nums.find((n) => n.length <= 2);
    if (year && day && valid(+year, month + 1, +day)) return `${year}-${pad(month + 1)}-${pad(day)}`;
    if (year) return `${year}-${pad(month + 1)}`;
    return null;
  }
  m = v.match(/^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$/); // only when day/month order is clear
  if (m) {
    const [a, b, y] = [+m[1], +m[2], m[3]];
    if (a > 12 && valid(+y, b, a)) return `${y}-${pad(b)}-${pad(a)}`;
    if (b > 12 && valid(+y, a, b)) return `${y}-${pad(a)}-${pad(b)}`;
  }
  m = v.match(/\b(\d{4})\b/);
  return m && valid(+m[1], 1) && nums.length === 1 ? m[1] : null;
}

/** A small tip under a field, with an optional one-tap fix. */
function fieldHint(field, value) {
  const v = value.trim();
  if (!v) return null;
  if (field.key === "lyrics") {
    const all = v.split("\n").filter((l) => l.trim());
    const synced = all.filter((l) => LRC_LINE.test(l)).length;
    return { text: synced >= Math.max(2, all.length / 2) ? `Synced lyrics (LRC) · ${plural(synced, "timed line")}` : `Plain lyrics · ${plural(all.length, "line")}`, info: true };
  }
  if (field.key === "date" || field.key === "originaldate") {
    if (DATE_OK.test(v)) return null;
    const fix = suggestDate(v);
    return { text: "Players expect dates like 2026-10-23 (or just 2026).", fix, fixLabel: fix && `Use ${fix}` };
  }
  // Commas are never flagged: they're part of names ("Tyler, The Creator")
  // and a common genre separator. Emoji save fine; this is only a heads-up.
  if (EMOJI.test(v)) {
    return { text: "Contains emoji. Most players show them, but some older devices and car stereos may not." };
  }
  return null;
}

function fieldEl(field, model) {
  const ed = state.editor;
  const key = field.key;
  const m = model.get(key) || { value: "", mixed: false, present: false, multiValued: false };
  const id = `f-${key}`;
  const change = ed.changes.get(key);
  const isLong = key === "comment" || key === "lyrics";

  const flag = h("span", { class: "flag" });
  const hintEl = h("div", { class: "field-hint", hidden: true });
  const suggestBox = h("div", { class: "suggest", role: "listbox", hidden: true });
  const hasSuggestions = !isLong && folderSuggestions(key).some((sg) => sg.value !== m.value || m.mixed);
  const wrap = h("div", { class: "field", dataset: { key } });
  const input = isLong
    ? h("textarea", { id, rows: key === "lyrics" ? "10" : "3", dir: "auto", spellcheck: "true", class: key === "lyrics" ? "lyrics-input" : null })
    : h("input", { id, type: "text", dir: "auto", spellcheck: "false", autocapitalize: "off", inputmode: ["tracknumber", "discnumber", "bpm"].includes(key) ? "numeric" : null });
  input.value = change ? change.value : m.value;

  const basePlaceholder = m.mixed ? "Multiple values — leave to keep"
    : COMMA_LIST_KEYS.has(key) ? "Separate with , or ;"
    : (field.multi || m.multiValued) ? "Use ; for several" : "";

  const refresh = () => {
    const c = ed.changes.get(key);
    wrap.classList.toggle("is-mixed", m.mixed && !c);
    wrap.classList.toggle("is-changed", !!c && !c.remove);
    wrap.classList.toggle("is-removed", !!c && c.remove);
    flag.className = `flag ${c ? (c.remove ? "removed" : "changed") : ""}`;
    flag.textContent = c ? (c.remove ? (tracksCount() > 1 ? "Remove from all" : "Will be removed") : "Changed") : "";
    input.placeholder = c && c.remove ? "Will be removed" : basePlaceholder;
    clearBtn.hidden = c ? c.remove : !m.present;
    const hint = fieldHint(field, input.value);
    hintEl.hidden = !hint;
    hintEl.classList.toggle("is-info", !!hint?.info); // facts, not warnings: shown in grey
    if (hint) {
      setKids(hintEl, h("span", {}, hint.text), hint.fix ? h("button", {
        class: "link-btn", type: "button",
        onclick: () => { input.value = hint.fix; input.dispatchEvent(new Event("input")); input.focus(); },
      }, hint.fixLabel) : null);
    }
    updateSaveButton();
  };

  input.addEventListener("input", () => {
    const v = input.value;
    if (v === "") {
      if (!m.mixed && m.present) ed.changes.set(key, { value: "", remove: true });
      else ed.changes.delete(key);
    } else if (!m.mixed && v === m.value) {
      ed.changes.delete(key);
    } else {
      ed.changes.set(key, { value: v, remove: false });
    }
    refresh();
  });

  const clearBtn = h("button", {
    class: "icon-btn clear", type: "button", "aria-label": `Clear ${tr(field.label)}`, title: "Remove this tag",
    onclick: () => {
      input.value = "";
      if (m.present) ed.changes.set(key, { value: "", remove: true });
      else ed.changes.delete(key);
      refresh();
      input.focus();
    },
  }, icon("clear"));

  let copyBox = null;
  if (ed.copyMode) {
    const copyable = currentValues(key).length > 0;
    copyBox = h("input", {
      type: "checkbox", class: "copy-box", "aria-label": `Copy ${field.label}`,
      checked: ed.copyKeys.has(key), disabled: !copyable,
      title: copyable ? `Copy ${field.label}` : (m.mixed ? "Values differ between tracks" : "Nothing to copy"),
      onchange: (e) => { e.target.checked ? ed.copyKeys.add(key) : ed.copyKeys.delete(key); renderToolbar(); },
    });
    wrap.classList.add("copyable");
  }
  wrap.append(
    h("label", { class: "field-label", for: copyBox ? null : id, title: `Tag name: ${key}` }, copyBox, field.label,
      hasSuggestions ? h("span", { class: "spark", title: "Suggestions from this folder — click into the field" }, icon("spark")) : null,
      flag, nativeTag(key)),
    isLong ? input : h("div", { class: "input-wrap" }, input, clearBtn, suggestBox),
    hintEl,
  );
  if (!isLong) attachSuggestions(input, key, suggestBox);
  if (key === "lyrics" && ed.paths.length === 1 && state.status?.lyrics_lookup) wrap.append(lyricsLookupEl(ed.paths[0], input));
  refresh();
  return wrap;
}

// ---- Lyrics lookup (LRCLIB) ----------------------------------------------------------------------

/** "Find lyrics": asks LRCLIB (only when pressed) and offers the result as a pending change. */
function lyricsLookupEl(path, input) {
  const panel = h("div", { class: "lyrics-found", hidden: true, "aria-live": "polite" });
  const button = h("button", { type: "button", class: "btn small" }, icon("search"), "Find lyrics");
  const use = (text) => {
    input.value = text;
    input.dispatchEvent(new Event("input", { bubbles: true })); // becomes a normal, unsaved change
    panel.hidden = true;
    toast("Lyrics added. Review them, then Save.");
  };
  button.addEventListener("click", async () => {
    button.disabled = true;
    const label = button.lastChild;
    label.textContent = "Searching…";
    try {
      const res = await api("GET", `/api/lyrics/lookup?path=${encodeURIComponent(path)}`);
      const r = res.result;
      if (!res.found) {
        setKids(panel, h("p", { class: "hint" }, "No lyrics found on LRCLIB for this track."));
      } else if (r.instrumental && !r.synced && !r.plain) {
        setKids(panel, h("p", { class: "hint" }, "LRCLIB lists this track as instrumental."));
      } else {
        const text = r.synced || r.plain;
        const lines = text.split("\n");
        setKids(panel,
          h("div", { class: "lyrics-found-head" },
            h("strong", {}, r.synced ? "Synced lyrics found" : "Lyrics found"),
            h("span", {}, ` on ${r.provider} · ${[r.artist, r.title].filter(Boolean).join(" — ")}${r.duration ? ` · ${fmtDuration(r.duration)}` : ""}`)),
          h("pre", { class: "lyrics-preview", dir: "auto" }, lines.slice(0, 8).join("\n") + (lines.length > 8 ? `\n… ${lines.length - 8} more lines` : "")),
          h("div", { class: "lyrics-found-actions" },
            r.synced ? h("button", { type: "button", class: "btn small primary", onclick: () => use(r.synced) }, "Use synced") : null,
            r.plain ? h("button", { type: "button", class: `btn small${r.synced ? "" : " primary"}`, onclick: () => use(r.plain) }, r.synced ? "Use plain" : "Use these lyrics") : null,
            h("button", { type: "button", class: "btn small", onclick: () => { panel.hidden = true; } }, "Dismiss")));
      }
      panel.hidden = false;
    } catch (err) {
      toast(err.message, "error");
    } finally {
      button.disabled = false;
      label.textContent = "Find lyrics";
    }
  });
  return h("div", { class: "lyrics-lookup" },
    h("div", { class: "lyrics-lookup-row" }, button, h("span", { class: "hint" }, "Looks up this track on lrclib.net")),
    panel);
}

function tracksCount() {
  return state.editor?.paths.length || 0;
}

function addTagEl(model) {
  const keyInput = h("input", { type: "text", placeholder: "Tag name", list: "tag-keys", "aria-label": "New tag name", autocapitalize: "off", spellcheck: "false" });
  const valueInput = h("input", { type: "text", placeholder: "Value", "aria-label": "New tag value" });
  const add = () => {
    const key = keyInput.value.trim().toLowerCase();
    if (!key) { keyInput.focus(); return; }
    if (key.includes("=") || /[^\x20-\x7d]/.test(key)) { toast("Tag names can only use plain letters, numbers and symbols (no “=”)", "error"); return; }
    const ed = state.editor;
    if (!model.has(key) && !ed.extraKeys.includes(key)) ed.extraKeys.push(key);
    if (valueInput.value) ed.changes.set(key, { value: valueInput.value, remove: false });
    renderEditor();
    const target = document.getElementById(`f-${key}`);
    if (target) {
      target.closest("details").open = true;
      target.focus();
      target.scrollIntoView({ block: "center" });
    }
  };
  for (const inp of [keyInput, valueInput]) {
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
  }
  return h("details", { class: "group" },
    h("summary", {}, "Add a tag"),
    h("p", { class: "hint" }, "Any name works on FLAC, OGG and Opus. MP3 and M4A only accept the tags listed above."),
    h("div", { class: "add-tag" }, keyInput, valueInput, h("button", { class: "btn", type: "button", onclick: add }, "Add")));
}

export function folderTrackPaths() {
  return (state.folder?.tracks || []).filter((t) => !t.error).map((t) => t.path);
}

function updateSaveButton() {
  const ed = state.editor;
  const n = pendingCount(ed);
  els.editorSave.disabled = n === 0;
  els.editorSave.textContent = n ? `Save ${n > 1 ? `(${n})` : ""}`.trim() : "Save";
  // "Save to folder" only makes sense if it reaches more tracks than "Save" does.
  const folderPaths = folderTrackPaths();
  const covers = ed && folderPaths.every((p) => ed.paths.includes(p));
  els.editorSaveFolder.hidden = !ed || covers;
  els.editorSaveFolder.disabled = n === 0;
  const where = isSearch() ? "Save to all results" : "Save to folder";
  els.editorSaveFolder.textContent = n ? `${where} (${n})` : where;
  renderChangesPopover(folderPaths.length);
}

/** The pending edits as "Field  old → new" rows. */
function changeList() {
  const ed = state.editor;
  const rows = [...ed.changes.entries()].map(([key, c]) => {
    const m = ed.model.get(key);
    const old = m?.mixed ? "various" : m?.value || "";
    return h("li", {},
      h("span", { class: "pop-key" }, fieldLabel(key)),
      h("span", { class: "pop-val" },
        old ? [h("s", {}, old), " → "] : null,
        c.remove ? h("span", { class: "pop-removed" }, "removed") : h("span", {}, c.value)));
  });
  if (ed.art) {
    rows.unshift(h("li", {},
      h("span", { class: "pop-key" }, "Album art"),
      h("span", { class: "pop-val" }, ed.art.action === "remove"
        ? h("span", { class: "pop-removed" }, "removed")
        : h("span", { class: "pop-art" }, h("img", { src: ed.art.url, alt: "" }), `new image (${ed.art.width} × ${ed.art.height})`))));
  }
  return h("ul", { class: "change-list" }, rows);
}

/** Hovering either Save button (with a mouse) shows exactly what will change. */
function renderChangesPopover(folderCount) {
  const pop = $("#changes-pop");
  const ed = state.editor;
  if (!pendingCount(ed)) { pop.replaceChildren(); return; }
  const n = ed.paths.length;
  setKids(pop,
    h("div", { class: "pop-head" }, `${plural(pendingCount(ed), "change")}`),
    changeList(),
    h("div", { class: "pop-foot" },
      `Save → ${n === 1 ? "this track" : `${n} selected tracks`}`,
      els.editorSaveFolder.hidden ? null : ` · Save to folder → all ${folderCount} tracks`));
}

// Tags that are normally different on every track of an album.
const PER_TRACK_KEYS = new Set(["title", "tracknumber", "isrc", "comment", "bpm", "lyrics"]);

export async function saveToFolder() {
  const ed = state.editor;
  if (!pendingCount(ed)) return;
  const paths = folderTrackPaths();
  const keys = [...(ed.art ? ["__art"] : []), ...ed.changes.keys()];
  const risky = keys.filter((k) => PER_TRACK_KEYS.has(k)).map(fieldLabel);
  const folderName = isSearch() ? `results for ${searchQuery()}` : state.folder.path ? state.folder.name : "Library";
  const ok = await ask({
    title: `Save to all ${paths.length} tracks?`,
    message: keys.length === 1 ? `In “${folderName}”, only this field changes:` : `In “${folderName}”, only these ${keys.length} fields change:`,
    details: [
      changeList(),
      risky.length ? h("div", { class: "confirm-warning" },
        `${risky.join(", ")} ${risky.length === 1 ? "is" : "are"} usually different on every track, so all ${paths.length} would get the same value.`) : null,
      h("p", { class: "hint", style: "margin:10px 0 0" }, "You can undo this from the activity log."),
    ],
    confirmLabel: `Save to ${paths.length} tracks`,
  });
  if (ok) saveEditor(paths);
}

export async function saveEditor(targetPaths = null) {
  const ed = state.editor;
  if (!pendingCount(ed) || ed.saving) return; // a second Ctrl+S mid-save would write everything twice
  ed.saving = true;
  try { await saveEditorNow(ed, targetPaths); } finally { ed.saving = false; }
}

async function saveEditorNow(ed, targetPaths) {
  const paths = targetPaths || ed.paths;
  const changes = {};
  for (const [key, c] of ed.changes) {
    const value = c.value.trim();
    if (c.remove || !value) { changes[key] = null; continue; }
    const split = state.fieldMap.get(key)?.multi || ed.model.get(key)?.multiValued;
    changes[key] = split ? value.split(";").map((s) => s.trim()).filter(Boolean) : value;
  }

  els.editorSave.disabled = true;
  els.editorSaveFolder.disabled = true;
  (targetPaths ? els.editorSaveFolder : els.editorSave).textContent = "Saving…";
  const failures = [];
  let saved = 0;
  const apply = (results) => {
    for (const r of results) {
      if (!r.ok) { failures.push(`${baseName(r.path)}: ${r.error}`); continue; }
      replaceTrack(r.track);
    }
    saved = Math.max(saved, results.length);
    return results.every((r) => r.ok);
  };
  try {
    if (ed.changes.size) {
      let allOk = true;
      for (let i = 0; i < paths.length; i += 500) { // big folders go in batches (server max 1000)
        allOk = apply(await api("PATCH", "/api/tracks", { paths: paths.slice(i, i + 500), changes })) && allOk;
      }
      if (allOk) ed.changes.clear();
    }
    if (ed.art) {
      if (apply(await sendArt(paths, ed.art))) clearPendingArt(ed);
    }
  } catch (err) {
    toast(err.message, "error");
    updateSaveButton();
    return;
  }
  // Other folders the page remembers (a search, the album's parent in the grid) still hold the
  // old tags and covers: forget them, so going back shows what's on disk now.
  for (const key of [...folderCache.keys()]) if (key !== state.path) folderCache.delete(key);
  folderCovers.clear();
  if (state.editor !== ed) return; // closed meanwhile
  ed.errors = failures;
  ed.copyMode = false;
  if (!failures.length) {
    toast(saved === 1 ? "Saved" : targetPaths ? `Saved to all ${saved} tracks in this folder` : `Saved ${saved} tracks`, "success");
  } else {
    toast(`${plural(failures.length, "file")} couldn't be saved`, "error"); // pending edits are kept for a retry
  }
  renderTracks();
  renderEditor();
  refreshActivity();
}

// ---- Album art ----------------------------------------------------------------------------------------
//
// Picking or removing art is a *pending* change, like a tag edit: nothing is
// written until Save (this track / selection) or Save to folder (every track).

const ART_KEEP_AS_IS = ["image/jpeg", "image/png"]; // others are converted to JPEG
const ART_MAX_BYTES = 20 * 1024 * 1024;
const ART_MAX_SIDE = 3000;

/** One URL per distinct cover, so a whole album's art downloads once. */
export function artUrlFor(t) {
  if (!t?.art) return null;
  const firsts = index.firstWithArt;
  let path = firsts.get(t.art.hash);
  if (path === undefined || !trackByPath(path) || trackByPath(path).art?.hash !== t.art.hash) {
    // (Re)build the cover -> first track map in one pass.
    firsts.clear();
    for (const x of state.folder?.tracks || []) if (x.art && !firsts.has(x.art.hash)) firsts.set(x.art.hash, x.path);
    path = firsts.get(t.art.hash) || t.path;
  }
  return `/api/art?path=${encodeURIComponent(path)}&v=${t.art.hash}`;
}

function pendingCount(ed) {
  return ed ? ed.changes.size + (ed.art ? 1 : 0) : 0;
}

function clearPendingArt(ed) {
  if (ed?.art?.url) URL.revokeObjectURL(ed.art.url);
  if (ed) ed.art = null;
}

function artEl(tracks) {
  const ed = state.editor;
  const single = tracks.length === 1;
  const hashes = new Set(tracks.map((t) => t.art?.hash || ""));
  const mixed = hashes.size > 1;
  const shared = !mixed ? tracks[0].art : null;
  const pending = ed.art;

  const fileInput = h("input", {
    type: "file", accept: "image/*,.heic,.heif", hidden: true, "aria-hidden": "true", tabindex: "-1",
    onchange: (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) stageArt(f); },
  });
  const pick = () => fileInput.click();
  const square = h("button", {
    class: "art-square", type: "button",
    "aria-label": single ? "Change album art" : `Set album art for ${tracks.length} tracks`,
    title: "Click or drop an image", onclick: pick,
  });
  const meta = h("div", { class: "art-meta" });
  const actions = h("div", { class: "art-actions" });
  const btn = (label, onclick, cls = "") => h("button", { class: `btn small ${cls}`, type: "button", onclick }, label);
  const showImage = (src, onLoaded) => {
    const img = h("img", { alt: "Album art", decoding: "async", draggable: "false" });
    img.addEventListener("load", () => { img.classList.add("loaded"); square.classList.add("has-art"); onLoaded?.(img); });
    img.src = src;
    square.replaceChildren(img);
  };
  const placeholder = (label) => {
    square.classList.remove("has-art");
    square.replaceChildren(h("span", { class: "art-empty" }, icon("plus"), h("span", {}, label)));
  };

  if (pending?.action === "set") {
    showImage(pending.url);
    square.classList.add("pending");
    square.append(h("span", { class: "art-badge" }, "Not saved"));
    meta.textContent = `${pending.width} × ${pending.height} · not saved yet`;
    actions.append(btn("Replace", pick), btn("Revert", revertArt));
  } else if (pending?.action === "remove") {
    placeholder(single ? "Will be removed" : `Will be removed from ${tracks.length} tracks`);
    square.classList.add("removing");
    meta.textContent = "Not saved yet";
    actions.append(btn("Revert", revertArt));
  } else if (shared) {
    showImage(artUrlFor(tracks[0]));
    meta.textContent = `${shared.width ?? "?"} × ${shared.height ?? "?"}${single ? "" : ` · same on all ${tracks.length}`}`;
    actions.append(btn("Replace", pick), btn(single ? "Remove" : "Remove from all", stageRemoveArt, "danger"));
  } else if (mixed) {
    placeholder(`Different art on ${tracks.length} tracks`);
    actions.append(btn("Replace all", pick), btn("Remove from all", stageRemoveArt, "danger"));
  } else {
    placeholder(single ? "Add album art" : `Add art to ${tracks.length} tracks`);
  }

  // Drag and drop an image onto the square (desktop).
  square.addEventListener("dragover", (e) => { e.preventDefault(); square.classList.add("drag"); });
  square.addEventListener("dragleave", () => square.classList.remove("drag"));
  square.addEventListener("drop", (e) => {
    e.preventDefault();
    square.classList.remove("drag");
    const f = e.dataTransfer?.files?.[0];
    if (f) stageArt(f);
  });

  return h("div", { class: "art" }, square, meta, actions, fileInput);
}

/** Prepare a picked image as pending art. JPEG/PNG are kept as-is; anything
 *  else the browser can open (HEIC on Safari/iPhone, WebP, AVIF, GIF…) is
 *  converted to a high-quality JPEG. */
async function stageArt(file) {
  const ed = state.editor;
  if (!ed) return;
  const looksHeic = /image\/hei[cf]/i.test(file.type) || /\.(heic|heif)$/i.test(file.name);
  let image;
  try {
    image = await decodeImage(file);
  } catch {
    toast(looksHeic
      ? "This browser can't open HEIC photos. Save it as JPEG first, or use Safari (or any browser on an iPhone)."
      : "That file isn't an image Codetta can open.", "error");
    return;
  }
  let width = image.width || image.naturalWidth;
  let height = image.height || image.naturalHeight;
  let blob = file;
  if (!ART_KEEP_AS_IS.includes(file.type)) {
    const scale = Math.min(1, ART_MAX_SIDE / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    blob = await canvasToBlob(canvas, "image/jpeg", 0.92);
    width = canvas.width;
    height = canvas.height;
  }
  if (!blob || blob.size > ART_MAX_BYTES) { toast("That image is too large (max 20 MB)", "error"); return; }
  if (state.editor !== ed) return;
  clearPendingArt(ed);
  ed.art = { action: "set", blob, url: URL.createObjectURL(blob), width, height, mime: blob.type };
  renderEditor();
}

function stageRemoveArt() {
  const ed = state.editor;
  if (!ed) return;
  clearPendingArt(ed);
  ed.art = { action: "remove" };
  renderEditor();
}

function revertArt() {
  clearPendingArt(state.editor);
  renderEditor();
}

/** Write pending art to ``paths`` (in batches); returns the per-file results. */
async function sendArt(paths, art) {
  const MAX_QUERY = 6000; // characters; well under common proxy limits (nginx: 8 KB)
  const batches = [];
  let batch = [], size = 0;
  for (const p of paths) {
    const part = `path=${encodeURIComponent(p)}`;
    if (batch.length && (size + part.length + 1 > MAX_QUERY || batch.length >= 500)) { batches.push(batch); batch = []; size = 0; }
    batch.push(part);
    size += part.length + 1;
  }
  if (batch.length) batches.push(batch);
  const results = [];
  for (const b of batches) results.push(...(await sendArtBatch(b.join("&"), art)));
  return results;
}

async function sendArtBatch(query, art) {
  const setting = art.action === "set";
  const res = await fetch(`/api/art?${query}`, {
    method: setting ? "PUT" : "DELETE",
    body: setting ? art.blob : undefined,
    headers: setting ? { "Content-Type": art.mime } : {},
  });
  if (res.status === 401) {
    showAuth("login", "Your session ended. Sign in again to carry on where you left off.");
    throw new Error("Sign in required");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error((data && typeof data.detail === "string" && data.detail) || `Request failed (${res.status})`);
  return data;
}
