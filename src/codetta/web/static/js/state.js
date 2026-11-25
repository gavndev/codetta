// App state, formatting helpers and toasts.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { countWord } from "./i18n.js";
import { $, h, icon, playOut } from "./dom.js";
import { loadClipboard } from "./editor.js";

// ---- State -------------------------------------------------------------------------------

export const state = {
  path: "",
  folder: null,           // last /api/browse response
  fields: [],             // known tags, in display order
  fieldMap: new Map(),
  placeholders: [],
  presets: [],
  selected: new Set(),    // selected track paths
  lastClicked: null,      // for shift-click ranges
  filter: "",
  editor: null,           // { paths, changes: Map, extraKeys: [], errors: [] }
  rows: new Map(),        // track path -> { row, checkbox }
  tagFilters: [],         // [{ key, value }] — value "" means "has no value"
  selectMode: false,      // phones: selection circles only show after tapping "Select"
  clipboard: loadClipboard(), // copied tags: { tags: {key: [values]}, from }
  advanced: (() => { try { return localStorage.getItem("codetta-advanced") === "1"; } catch { return false; } })(),
  loadToken: 0,
};

export const els = {
  crumbs: $("#crumbs"),
  banner: $("#banner"),
  folderHead: $("#folder-head"),
  folders: $("#folders"),
  foldersHead: $("#folders-head"),
  tracks: $("#tracks"),
  tracksHead: $("#tracks-head"),
  browser: $("#browser"),
  filter: $("#filter"),
  editor: $("#editor"),
  editorForm: $("#editor-form"),
  editorTitle: $("#editor-title"),
  editorSub: $("#editor-sub"),
  editorSave: $("#editor-save"),
  editorSaveFolder: $("#editor-save-folder"),
  toolbarLeft: $("#toolbar-left"),
  filterChips: $("#filter-chips"),
  filterDialog: $("#filter-dialog"),
  selBar: $("#selection-bar"),
  selCount: $("#selection-count"),
  toasts: $("#toasts"),
  applyDialog: $("#apply-dialog"),
  manageDialog: $("#manage-dialog"),
};

// ---- Formatting --------------------------------------------------------------------------

export const fmtDuration = (s) => {
  if (!s && s !== 0) return "";
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, "0")}`;
};
export const first = (track, key) => (track.tags[key] || [])[0] || "";
const FORMAT_LABELS = { wavpack: "WV", oggflac: "Ogg FLAC", speex: "SPX", wma: "WMA", ape: "APE", mpc: "MPC", dff: "DFF" };
export const fmtLabel = (format) => FORMAT_LABELS[format] || (format || "").toUpperCase();
export const runtime = (tracks) => {
  const secs = tracks.reduce((sum, t) => sum + (t.duration || 0), 0);
  return secs >= 60 ? `, ${Math.round(secs / 60)} min` : "";
};
export const trackNo = (v) => { const n = (v || "").split("/")[0].trim(); return /^\d$/.test(n) ? `0${n}` : n; };
export const plural = (n, word, many = `${word}s`) => countWord(n, word, many);

/** "3 tracks of 12 would change", in a preview's summary. One track gets its own sentence, so a
 * translation can use a singular verb ("1 pista de 12 cambiaría"). */
export function changeLine(d) {
  if (!d.changing) return `Nothing to change in ${plural(d.tracks, "track")}.`;
  return d.changing === 1 ? `1 track of ${d.tracks} would change` : `${plural(d.changing, "track")} of ${d.tracks} would change`;
}
export const baseName = (path) => path.split("/").pop();

export function relativeToFolder(path) {
  const prefix = state.path ? state.path + "/" : "";
  return path.startsWith(prefix) ? path.slice(prefix.length) : path;
}

// ---- Toasts --------------------------------------------------------------------------------

export function toast(message, kind = "") {
  // While the sign-in screen is up it already explains what's wrong.
  if (kind === "error" && !$("#auth").hidden) return;
  const el = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" },
    kind === "success" ? h("span", { class: "toast-icon", "aria-hidden": "true" }, icon("check")) : null, message);
  els.toasts.append(el);
  setTimeout(() => playOut(el, "leaving", () => el.remove()), kind === "error" ? 7000 : 3500);
}

/** Codetta's own areas ("@inbox/…", "@deleted/…"); any other folder starting with "@" is ordinary (#5). */
export const isSpecialPath = (path) => /^@(inbox|replaced|deleted)(\/|$)/.test(path || "");
