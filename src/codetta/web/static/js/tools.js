// Batch tools: find & replace in tags, rename a folder, actions.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, closeDialog, coverRatio, drawInBatches, fitCover, h, icon, openDialog, replay, setKids } from "./dom.js";
import { api } from "./api.js";
import { changeLine, els, first, fmtDuration, fmtLabel, isSpecialPath, plural, runtime, state, toast, trackNo } from "./state.js";
import {
  discInfo, fold, folderCache, hashFor, loadFolder, mbFindButton, navigate, renderSearchHead,
  renderSelectionBar, selectAll, toggleSelect, updateRowStates, visibleTracks,
} from "./browse.js";
import { iconButton, renderMbBody, renderMbHead, selectButtons, skFindButton } from "./search.js";
import { canPlay, openTrack, syncPlayer, togglePlay } from "./player.js";
import { artUrlFor, fieldLabel } from "./editor.js";
import { refreshActivity } from "./activity.js";
import { openApply } from "./presets.js";
import { skReady } from "./inbox.js";
import { openOrganize, updateHealthSlot } from "./library.js";
import { openReplayGain, replayGainReady } from "./replaygain.js";
import { openFromNames } from "./fromnames.js";
import { openTracklist } from "./tracklist.js";
import { openCoverExport } from "./coverexport.js";
import { artistButton, artistHead } from "./artists.js";
import { renderYoursBody, renderYoursLibrary, reorderGrip, yoursHead, yoursView } from "./yours.js";
import { openCoverView } from "./coverview.js";

/** The album's cover at its own shape: square, taller (an obi, a cassette J-card) or wider (a long sleeve).
 *  A tap shows it full size. */
function albumCover(t, title = "") {
  const src = artUrlFor(t);
  const img = h("img", { class: "album-cover", src, alt: "", decoding: "async" });
  img.style.setProperty("--ar", String(coverRatio(t.art)));
  let size = t.art?.width && t.art?.height ? `${t.art.width} × ${t.art.height}` : "";
  if (!t.art?.width) {
    img.addEventListener("load", () => {
      img.style.setProperty("--ar", String(coverRatio({ width: img.naturalWidth, height: img.naturalHeight })));
      size = `${img.naturalWidth} × ${img.naturalHeight}`;
    }, { once: true });
  }
  return h("button", { class: "album-cover-btn", type: "button", "aria-label": "Show the album art full size", title: "Show full size",
    onclick: () => openCoverView(src, { title, caption: size }) }, img);
}

/** A folder at the top of the library that holds albums: an artist's folder. */
const isArtistFolder = (f) => !f.search && !f.mb && !f.yours && f.path && !f.path.includes("/") && !isSpecialPath(f.path)
  && f.folders.length > 0 && f.tracks.length <= 2;

// ---- Batch tools: find & replace in tags, rename a folder, actions -----------------------------------

/** The folder page's batch tools (icon buttons on computers, a "…" menu on phones). */
function folderTools(f) {
  const target = (f.search || f.yours) ? { paths: f.tracks.map((t) => t.path).slice(0, 1000) } : { folder: state.path };
  const label = (f.search || f.yours) ? plural(Math.min(f.tracks.length, 1000), f.yours ? "song" : "result") : "this folder";
  return [
    (f.tracks.length || f.folders.length) && !(f.search || f.yours) && !f.mb ? { icon: "layers", label: "Organize", run: openOrganize, primary: true,
      title: "Rename and move files into folders from their tags (you see everything first)" } : null,
    f.tracks.length ? { icon: "replace", label: "Find & replace", run: () => openReplace(target, label), primary: true, group: "Fix tags",
      title: "Find & replace in the tags of these tracks (you see every change first)" } : null,
    replayGainReady() && (f.tracks.length || (f.folders.length && !(f.search || f.yours) && !f.mb)) && !f.mb
      ? { icon: "volume", label: "ReplayGain", group: "Fix tags", run: () => openReplayGain((f.search || f.yours) ? target : { folder: state.path }, label),
        title: "Even out the volume: measure loudness and write ReplayGain tags (you see every value first)" } : null,
    f.tracks.length ? { icon: "tag", label: "Tags from file names", group: "Fix tags", run: () => openFromNames(target, label),
      title: "Fill in tags from file and folder names with a pattern (you see every change first)" } : null,
    f.tracks.length && !(f.search || f.yours) ? { icon: "paste", label: "Paste a tracklist", group: "Fix tags", run: () => openTracklist({ folder: state.path }, label),
      title: "Titles and numbers from a tracklist you paste (Discogs, Bandcamp, Wikipedia…), paired with the files" } : null,
    (f.tracks.length || f.folders.length) && !(f.search || f.yours) && !f.mb
      ? { icon: "folder", label: "Save covers as files", group: "Folder", run: () => openCoverExport({ folder: state.path }, label),
        title: "Save each album's embedded cover as cover.jpg in its folder, for players that look for one" } : null,
    f.tracks.length ? { icon: "wand", label: "Actions", group: "Fix tags", run: () => openActions(target, label),
      title: "Clean up titles, Title Case and trim spaces (you see every change first)" } : null,
    f.tracks.length && !f.mb ? { icon: "trash", label: "Wipe all tags", group: "Danger", danger: true, run: () => wipeTags(target),
      title: "Remove every tag from these tracks (asks twice; Activity can undo it)" } : null,
    state.path && !(f.search || f.yours) && !f.mb ? { icon: "rename", label: "Rename folder", group: "Folder", run: renameFolder, title: "Rename this folder" } : null,
    !(f.search || f.yours) && !f.mb ? { icon: "plus", label: "New folder", group: "Folder", run: newFolderHere, title: "Make a new folder in here" } : null,
    state.path && !(f.search || f.yours) && !f.mb && !isSpecialPath(state.path) && (f.tracks.length || f.folders.length)
      ? { icon: "download", label: "Download as .zip", group: "Folder", run: () => downloadZip(state.path), title: "Download this folder as a .zip file" } : null,
  ].filter(Boolean).sort((a, b) => GROUPS.indexOf(a.group) - GROUPS.indexOf(b.group));
}
const GROUPS = [undefined, "Fix tags", "Folder", "Danger"]; // menu order: ungrouped (Organize) first

const sizeText = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);

function clickDownload(href, name) {
  const a = h("a", { href, download: name || "", hidden: true });
  document.body.append(a);
  a.click();
  a.remove();
}

/** Download one track as it is. */
export function downloadFile(path) {
  clickDownload(`/api/files/download?path=${encodeURIComponent(path)}`, path.split("/").pop());
}

/** Download a selection: one track as it is, several as one .zip (lyrics files come along). */
export async function downloadSelection(paths) {
  if (paths.length === 1) { downloadFile(paths[0]); return; }
  try {
    const d = await api("POST", "/api/files/zip", { paths });
    clickDownload(d.url, d.name);
    toast(`Zipping ${plural(d.files, "file")} (${sizeText(d.size)}). It downloads as it's made.`, "success");
  } catch (err) { toast(err.message, "error"); }
}

/** Download a folder as a .zip. The server streams it, so the browser's own download shows the progress. */
export async function downloadZip(path) {
  let info;
  try { info = await api("GET", `/api/files/info?path=${encodeURIComponent(path)}`); } catch (err) { toast(err.message, "error"); return; }
  if (!info.files) { toast("That folder is empty, so there's nothing to zip up.", "error"); return; }
  clickDownload(`/api/folders/zip?path=${encodeURIComponent(path)}`, `${info.name || "Music"}.zip`);
  toast(`Zipping “${info.name}” (${plural(info.files, "file")}, ${sizeText(info.size)}). It downloads as it's made.`, "success");
}

/** Wipe all tags: asked twice, centre stage, because it leaves the tracks with nothing. */
async function wipeTags(target) {
  let info;
  try { info = await api("POST", "/api/tags/wipe", { ...target, dry_run: true }); } catch (err) { toast(err.message, "error"); return; }
  if (!info.changing) { toast(info.tracks ? "These tracks have no tags to wipe." : "There are no tracks here.", "success"); return; }
  const n = plural(info.changing, "track");
  if (!await ask({ title: "Wipe all tags?", cls: "confirm-center", danger: true, confirmLabel: "Continue",
    message: `Every tag on ${n} is removed: titles, artists, album, track numbers, genres, lyrics and MusicBrainz IDs. The audio and the cover stay.`,
    details: info.tracks > info.changing ? h("p", { class: "hint" }, `Tracks here that already have no tags: ${info.tracks - info.changing}.`) : null })) return;
  if (!await ask({ title: "Are you sure?", cls: "confirm-center wipe-final-step", danger: true, confirmLabel: `Wipe ${n}`,
    details: h("div", { class: "wipe-final" },
      h("span", { class: "wipe-ico", "aria-hidden": "true" }, icon("trash")),
      h("p", {}, `${n} will have no title, artist or album. Music apps will show them as unknown until you tag them again.`),
      h("p", { class: "hint" }, "You can undo this from Activity.")) })) return;
  try {
    const r = await api("POST", "/api/tags/wipe", { ...target, dry_run: false });
    toast(r.failed ? `Wiped ${plural(r.changed, "track")}, ${r.failed} couldn't be changed` : `Wiped the tags from ${plural(r.changed, "track")}`, r.failed ? "error" : "success");
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    loadFolder(state.path, { keepScroll: true });
  } catch (err) { toast(err.message, "error"); }
}

export function openToolsMenu(anchor, tools) {
  // Tools that name a group get a small heading above the first of them ("Fix tags", "Folder").
  const menu = h("div", { class: "tools-menu", role: "menu" }, tools.flatMap((t, i) => [
    t.group && t.group !== tools[i - 1]?.group ? h("div", { class: "tools-head", role: "presentation" }, t.group) : null,
    h("button", { class: `tools-item${t.danger ? " danger" : ""}`, type: "button", role: "menuitem", title: t.title || null,
      onclick: () => { menu.remove(); t.run(); } }, icon(t.icon), t.label)]));
  popMenu(anchor, menu);
}

/** Show ``menu`` (class "tools-menu") under ``anchor``, kept on screen; a tap outside closes it. */
export function popMenu(anchor, menu) {
  document.querySelector(".tools-menu")?.remove();
  const r = anchor.getBoundingClientRect();
  menu.style.top = `${r.bottom + 8}px`;
  document.body.append(menu);
  const left = Math.min(Math.max(12, r.left), window.innerWidth - menu.offsetWidth - 12);  // stays on screen
  menu.style.left = `${left}px`;
  // No room below (the selection bar sits at the bottom of the screen): open upwards instead.
  const up = r.bottom + 8 + menu.offsetHeight > window.innerHeight - 8 && r.top - 8 - menu.offsetHeight > 8;
  if (up) menu.style.top = `${r.top - 8 - menu.offsetHeight}px`;
  // Taller than the room it has (a long menu on a phone): it scrolls instead of running off screen.
  const room = up ? r.top - 16 : window.innerHeight - (r.bottom + 8) - 12;
  if (menu.offsetHeight > room) menu.style.maxHeight = `${Math.max(160, room)}px`;
  menu.style.transformOrigin = `${up ? "bottom" : "top"} ${left > r.left - 1 ? "left" : "right"}`;
  replay(menu, "opening");
  const close = (e) => { if (!menu.contains(e.target) && e.target !== anchor) { menu.remove(); document.removeEventListener("pointerdown", close, true); } };
  setTimeout(() => document.addEventListener("pointerdown", close, true), 0);
}

const act = { target: null, label: "", data: null, chosen: null, options: {}, token: 0 };

export async function openActions(target, label) {
  act.target = target; act.label = label; act.chosen = null;
  openDialog($("#actions-dialog"));
  setKids($("#actions-body"), h("p", { class: "loading" }, "Loading…"));
  setKids($("#actions-foot"));
  try { act.data = await api("GET", "/api/plugins"); } catch (err) { setKids($("#actions-body"), h("div", { class: "error-box" }, err.message)); return; }
  renderActions();
}

function renderActions() {
  const d = act.data;
  const byPlugin = new Map();
  for (const a of d.actions) { if (!byPlugin.has(a.plugin)) byPlugin.set(a.plugin, []); byPlugin.get(a.plugin).push(a); }
  const name = (pid) => d.plugins.find((p) => p.id === pid)?.name || pid;
  setKids($("#actions-body"),
    h("p", { class: "mb-lead" }, `On ${act.label}. Pick one to see what it would change; nothing is written until you say so.`),
    [...byPlugin].map(([pid, list]) => h("section", { class: "act-group" },
      h("h3", { class: "mbx-h" }, name(pid)),
      h("div", { class: "act-list" }, list.map((a) => h("button", { class: `act-item${act.chosen === a.id ? " on" : ""}`, type: "button",
        onclick: () => chooseAction(a.id) },
        h("strong", {}, a.label), a.description ? h("span", {}, a.description) : null))))),
    h("div", { class: "act-options", id: "act-options" }, actionOptions()),
    h("div", { class: "rep-preview", id: "act-preview" }, null));
  setKids($("#actions-foot"), h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", id: "act-apply", disabled: true, onclick: applyAction }, "Apply"));
}

/** Dropdowns for the chosen action's choices (case, which tags, separator...). */
function actionOptions() {
  const a = act.data?.actions.find((x) => x.id === act.chosen);
  if (!a?.options?.length) return null;
  return a.options.map((o) => {
    const sel = h("select", { name: `act-${o.id}` }, o.choices.map(([v, label]) =>
      h("option", { value: v, selected: (act.options[o.id] ?? o.choices[0][0]) === v }, label)));
    sel.addEventListener("change", () => { act.options[o.id] = sel.value; previewAction(); });
    return h("label", { class: "field" }, h("span", { class: "field-label" }, o.label), sel);
  });
}

async function chooseAction(id) {
  if (act.chosen !== id) act.options = {};
  act.chosen = id;
  renderActions();
  previewAction();
}

async function previewAction() {
  const id = act.chosen;
  const box = $("#act-preview");
  const go = $("#act-apply");
  const token = ++act.token;
  setKids(box, h("p", { class: "hint mbx-wait" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Looking…"));
  try {
    const d = await api("POST", `/api/actions/${encodeURIComponent(id)}/run`, { ...act.target, options: act.options, dry_run: true });
    if (token !== act.token) return;
    go.disabled = !d.changing;
    go.textContent = d.changing ? `Apply to ${plural(d.changing, "track")}` : "Apply";
    setKids(box,
      h("p", { class: "rep-count" }, changeLine(d)),
      d.preview.length ? h("ul", { class: "rep-list" }, d.preview.map((p) => h("li", {},
        h("span", { class: "rep-file", dir: "auto" }, p.path.split("/").pop()),
        p.changes.map((ch) => h("span", { class: "rep-change" }, h("b", {}, fieldLabel(ch.key)), " ",
          h("del", { dir: "auto" }, ch.old), " → ", h("ins", { dir: "auto" }, ch.new || "(empty)")))))) : null,
      d.changing > d.preview.length ? h("p", { class: "hint" }, `…and ${d.changing - d.preview.length} more`) : null);
  } catch (err) {
    if (token !== act.token) return;
    setKids(box, h("p", { class: "field-error" }, err.message));
  }
}

async function applyAction() {
  const go = $("#act-apply");
  go.disabled = true; go.textContent = "Applying…";
  try {
    const d = await api("POST", `/api/actions/${encodeURIComponent(act.chosen)}/run`, { ...act.target, options: act.options, dry_run: false });
    closeDialog($("#actions-dialog"));
    toast(d.failed ? `Changed ${d.changed}, ${d.failed} couldn't be changed` : `Changed ${plural(d.changed, "track")}`, d.failed ? "error" : "success");
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    loadFolder(state.path, { keepScroll: true });
  } catch (err) { toast(err.message, "error"); go.disabled = false; go.textContent = "Apply"; }
}

const rep = { target: null, label: "", timer: null, token: 0, data: null };
const REPLACE_FIELD_CHOICES = [["", "All text fields"], ["title", "Title"], ["artist", "Artist"], ["album", "Album"],
  ["albumartist", "Album artist"], ["genre", "Genre"], ["comment", "Comment"]];

export function openReplace(target, label) {
  rep.target = target; rep.label = label; rep.data = null;
  const f = {};
  f.find = h("input", { type: "text", placeholder: "Find, e.g. (Official Audio)", maxlength: "200", dir: "auto", spellcheck: "false", autocomplete: "off" });
  f.replace = h("input", { type: "text", placeholder: "Replace with (leave empty to remove it)", maxlength: "500", dir: "auto", spellcheck: "false", autocomplete: "off" });
  f.field = h("select", {}, REPLACE_FIELD_CHOICES.map(([v, l]) => h("option", { value: v }, l)));
  f.case = h("input", { type: "checkbox" });
  f.regex = h("input", { type: "checkbox" });
  rep.fields = f;
  for (const el of [f.find, f.replace, f.field, f.case, f.regex]) el.addEventListener("input", () => replacePreviewSoon());
  for (const el of [f.field, f.case, f.regex]) el.addEventListener("change", () => replacePreviewSoon());
  setKids($("#replace-body"),
    h("p", { class: "mb-lead" }, `In the tags of ${label}. You see every change before anything is written, and Activity can undo it.`),
    h("div", { class: "rep-grid" },
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Find"), f.find),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Replace with"), f.replace),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "In"), f.field)),
    h("div", { class: "rep-options" },
      h("label", { class: "rep-check" }, f.case, "Match case"),
      h("label", { class: "rep-check", title: "Regular expression: \\d+ for numbers, (…) and \\1 to keep parts" }, f.regex, "Pattern (regex)")),
    h("div", { class: "rep-preview", id: "rep-preview" }, h("p", { class: "hint" }, "Type what to find to see the changes.")));
  setKids($("#replace-foot"), h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", id: "rep-apply", disabled: true, onclick: applyReplace }, "Replace"));
  openDialog($("#replace-dialog"));
  f.find.focus();
}

function replaceBody(dryRun) {
  const f = rep.fields;
  return { ...rep.target, find: f.find.value, replace: f.replace.value, fields: f.field.value ? [f.field.value] : null,
    match_case: f.case.checked, regex: f.regex.checked, dry_run: dryRun };
}

function replacePreviewSoon() {
  clearTimeout(rep.timer);
  rep.timer = setTimeout(replacePreview, 300);
}

async function replacePreview() {
  const box = $("#rep-preview");
  const go = $("#rep-apply");
  if (!rep.fields.find.value) { setKids(box, h("p", { class: "hint" }, "Type what to find to see the changes.")); go.disabled = true; return; }
  const token = ++rep.token;
  setKids(box, h("p", { class: "hint mbx-wait" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Looking…"));
  try {
    const d = await api("POST", "/api/tracks/replace", replaceBody(true));
    if (token !== rep.token) return;
    rep.data = d;
    go.disabled = !d.changing;
    go.textContent = d.changing ? `Replace in ${plural(d.changing, "track")}` : "Replace";
    setKids(box,
      h("p", { class: "rep-count" }, changeLine(d)),
      d.preview.length ? h("ul", { class: "rep-list" }, d.preview.map((p) => h("li", {},
        h("span", { class: "rep-file", dir: "auto" }, p.path.split("/").pop()),
        p.changes.map((ch) => h("span", { class: "rep-change" }, h("b", {}, fieldLabel(ch.key)), " ",
          h("del", { dir: "auto" }, ch.old), " → ", h("ins", { dir: "auto" }, ch.new || "(empty)")))))) : null,
      d.changing > d.preview.length ? h("p", { class: "hint" }, `…and ${d.changing - d.preview.length} more`) : null);
  } catch (err) {
    if (token !== rep.token) return;
    go.disabled = true;
    setKids(box, h("p", { class: "field-error" }, err.message));
  }
}

async function applyReplace() {
  const go = $("#rep-apply");
  go.disabled = true; go.textContent = "Replacing…";
  try {
    const d = await api("POST", "/api/tracks/replace", replaceBody(false));
    closeDialog($("#replace-dialog"));
    toast(d.failed ? `Changed ${d.changed}, ${d.failed} couldn't be changed` : `Changed ${plural(d.changed, "track")}`, d.failed ? "error" : "success");
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    loadFolder(state.path, { keepScroll: true });
  } catch (err) { toast(err.message, "error"); go.disabled = false; go.textContent = "Replace"; }
}

/** Make a folder inside ``parent`` (asks for its name). Returns its path, or null. */
export async function makeFolder(parent, name) {
  try {
    const r = await api("POST", "/api/folders/new", { parent, name });
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    return r.path;
  } catch (err) { toast(err.message, "error"); return null; }
}

async function newFolderHere() {
  const input = h("input", { type: "text", maxlength: "255", dir: "auto", spellcheck: "false", autocomplete: "off", class: "rename-input",
    placeholder: "Folder name" });
  setTimeout(() => input.focus(), 80);
  const where = state.path ? `“${state.path.split("/").pop()}”` : "your library";
  const ok = await ask({ title: "New folder", message: `A new, empty folder in ${where}. Activity can undo it while it's still empty.`,
    details: h("label", { class: "field" }, h("span", { class: "field-label" }, "Name"), input), confirmLabel: "Make folder" });
  const name = input.value.trim();
  if (!ok || !name) return;
  const path = await makeFolder(state.path, name);
  if (path) { toast(`Made “${path.split("/").pop()}”`, "success"); navigate(path); }
}

async function renameFolder() {
  const current = state.path.split("/").pop();
  const input = h("input", { type: "text", value: current, maxlength: "255", dir: "auto", spellcheck: "false", autocomplete: "off", class: "rename-input" });
  setTimeout(() => { input.focus(); input.select(); }, 80);
  const ok = await ask({ title: "Rename folder", message: "Every file moves with it. Nothing is overwritten, and Activity can undo it.",
    details: h("label", { class: "field" }, h("span", { class: "field-label" }, "New name"), input), confirmLabel: "Rename" });
  const name = input.value.trim();
  if (!ok || !name || name === current) return;
  try {
    const r = await api("POST", "/api/folders/rename", { path: state.path, name });
    toast(r.failed ? `Moved ${r.moved}, ${r.failed} couldn't move` : `Renamed to “${r.path.split("/").pop()}”`, r.failed ? "error" : "success");
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    navigate(r.path);
  } catch (err) { toast(err.message, "error"); }
}

export function renderFolderHead() {
  const f = state.folder;
  if (!f) return;
  updateHealthSlot(); // only on the Library page itself
  if (f.yours) {
    els.folderHead.replaceChildren(yoursHead(f), ...!f.tracks.length ? [] : [h("div", { class: "folder-actions" },
      ...folderTools(f).filter((t) => t.primary).map((t) => iconButton(t.icon, t.label, t.run, { title: t.title, cls: "tool-desktop tool-labelled" })),
      folderTools(f).length ? iconButton("more", "More", (e) => openToolsMenu(e.currentTarget, folderTools(f).filter((t) => !t.primary)),
        { title: "More tools for these songs", cls: "tool-desktop tool-labelled" }) : null,
      folderTools(f).length ? iconButton("more", "More", (e) => openToolsMenu(e.currentTarget, folderTools(f)), { cls: "tool-more" }) : null,
      selectButtons(f))]);
    els.tracks.classList.toggle("selecting", state.selectMode);
    return;
  }
  if (f.search) { renderSearchHead(f); return; }
  if (f.mb) { renderMbHead(f); return; }
  const counts = [];
  if (f.folders.length) counts.push(plural(f.folders.length, "folder"));
  if (f.tracks.length) counts.push(plural(f.tracks.length, "track"));
  const skippedNote = f.skipped ? h("span", {
    class: "skipped-note",
    title: "These names aren't valid UTF-8 text (often from old Windows zips), so Codetta can't show them. Renaming them fixes it.",
  }, ` · ${plural(f.skipped, "item")} with unreadable names hidden`) : null;
  const coverTrack = f.tracks.find((t) => t.art && !t.error);
  const common = (key) => {
    const values = new Set(f.tracks.filter((t) => !t.error).map((t) => first(t, key).trim()).filter(Boolean));
    return values.size === 1 ? [...values][0] : "";
  };
  // Every genre the album shares, however the file separates them (separate values,
  // ";", "," or "|"), shown in one chip as "Trap, Hip-Hop, New Jazz".
  const genres = (() => {
    const listOf = (t) => {
      const seen = new Map();
      for (const g of (t.tags.genre || []).flatMap((v) => v.split(/[;,|]/))) {
        const name = g.trim();
        if (name && !seen.has(name.toLowerCase())) seen.set(name.toLowerCase(), name);
      }
      return [...seen.values()].join(", ");
    };
    const set = new Set(f.tracks.filter((t) => !t.error).map(listOf).filter(Boolean));
    return set.size === 1 ? [...set][0] : "";
  })();
  const canMatch = f.tracks.length && state.status?.matching;
  const canSoulseek = f.tracks.length && skReady() && !isSpecialPath(state.path);
  const heading = coverTrack
    // A folder of tracks with a cover reads as the album's booklet spread.
    ? h("div", { class: "album-head" },
      albumCover(coverTrack, common("album") || f.name),
      h("div", {},
        h("h1", { dir: "auto" }, common("album") || f.name),
        h("p", { class: "album-meta" },
          [common("albumartist") || common("artist"), common("date").slice(0, 4)].filter(Boolean).flatMap((v, i) => [i ? " · " : "",
            v === (common("albumartist") || common("artist")) && i === 0 ? h("b", {}, artistButton(v, [v], { pictures: true })) : h("b", { dir: "auto" }, v)]),
          counts.length ? [common("albumartist") || common("artist") || common("date") ? " · " : "",
            h("span", { class: "nowrap" }, `${counts.join(" · ")}${runtime(f.tracks)}`)] : "", skippedNote),
        genres || canMatch || canSoulseek ? h("div", { class: "album-chips" },
          genres ? h("span", { class: "spot-chip", dir: "auto" }, genres) : null,
          canMatch ? mbFindButton("beside-genre") : null,
          canSoulseek ? skFindButton("beside-genre") : null) : null))
    : isArtistFolder(f) ? artistHead(f, counts)
    : h("div", {},
      h("h1", { translate: f.path ? "no" : null }, f.path ? f.name : "Library"),
      h("p", {}, counts.join(" · ") || (f.skipped ? "" : "Empty folder"), skippedNote));
  els.folderHead.replaceChildren(
    heading,
    h("div", { class: "folder-actions" },
      // Phones (and folders without a cover): first in the action row, on the left.
      canMatch ? mbFindButton(coverTrack ? "in-actions phone-only" : "in-actions") : null,
      canSoulseek ? skFindButton(coverTrack ? "in-actions phone-only" : "in-actions") : null,
      f.tracks.length || f.folders.length ? iconButton("preset", "Apply preset", () => openApply("folder"),
        { title: "Apply a Tag Preset to this folder (you see every change first)", cls: "tool-labelled" }) : null,
      // Computers: the most-used tools as labelled buttons, the rest in a "More" menu. Phones: one "…" menu.
      ...folderTools(f).filter((t) => t.primary).map((t) => iconButton(t.icon, t.label, t.run, { title: t.title, cls: "tool-desktop tool-labelled" })),
      folderTools(f).some((t) => !t.primary) ? iconButton("more", "More", (e) => openToolsMenu(e.currentTarget, folderTools(f).filter((t) => !t.primary)),
        { title: "More tools for this folder", cls: "tool-desktop tool-labelled" }) : null,
      folderTools(f).length ? iconButton("more", "More", (e) => openToolsMenu(e.currentTarget, folderTools(f)), { cls: "tool-more" }) : null,
      // Phones: selecting is a mode, like the Photos app.
      selectButtons(f)),
  );
  els.tracks.classList.toggle("selecting", state.selectMode);
}

export const isPhone = () => window.matchMedia("(max-width: 760px)").matches;

export function setSelectMode(on) {
  state.selectMode = on;
  if (!on) {
    state.selected.clear();
    state.lastClicked = null;
    updateRowStates();
    renderSelectionBar();
  }
  renderFolderHead();
}

export function allVisibleSelected() {
  const vis = visibleTracks();
  return vis.length > 0 && vis.every((t) => state.selected.has(t.path));
}

export function toggleSelectAllVisible() {
  selectAll(!allVisibleSelected());
}

// Folders show as a list by default (clean with hundreds of artists), or as a grid.
export function folderView() {
  try { return localStorage.getItem("codetta-folder-view") === "grid" ? "grid" : "list"; } catch { return "list"; }
}

export function setFolderView(view) {
  try { localStorage.setItem("codetta-folder-view", view); } catch { /* ignore */ }
  renderFolders();
}

/** What a folder's subfolders are: albums (they hold songs), artists (at the top, they hold albums), or folders. */
function foldersTitle(f) {
  const subs = f.folders;
  if (subs.length && subs.every((s) => s.tracks > 0 && !s.folders)) return "Albums";
  if (!f.path && subs.filter((s) => s.folders > 0).length * 2 > subs.length) return "Artists";
  return "Folders";
}

/** A section's title line: its name and how many on the left, anything else (the grid/list buttons) on the right. */
function sectionHead(box, title, count, ...end) {
  box.hidden = false;
  box.replaceChildren(h("h2", {}, title), h("span", { class: "sec-count" }, count), h("span", { class: "spacer" }), ...end);
}

function folderToggle() {
  return h("div", { class: "view-toggle", role: "group", "aria-label": "Folder view" },
    ["grid", "list"].map((v) => h("button", {
      type: "button", class: "icon-btn", title: v === "list" ? "List" : "Grid",
      "aria-label": v === "list" ? "Show folders as a list" : "Show folders as a grid",
      "aria-pressed": String(folderView() === v),
      onclick: () => setFolderView(v),
    }, icon(v === "list" ? "rows" : "grid"))));
}

function folderSummary(f) {
  if (f.folders == null) return "";
  const parts = [];
  if (f.folders) parts.push(plural(f.folders, "folder"));
  if (f.tracks) parts.push(plural(f.tracks, "track"));
  return parts.join(" · ") || "Empty";
}

export function renderFolders() {
  els.foldersHead.hidden = true;
  els.folders.classList.toggle("mbx-host", !!state.folder?.mb);
  if (state.folder?.mb) { renderMbBody(state.folder); return; }
  const overview = !!state.folder?.yours && !state.folder.yours.view;
  els.folders.classList.toggle("yours-host", overview);
  if (overview) { els.folders.classList.remove("as-list"); renderYoursBody(state.folder); return; }
  const yv = state.folder?.yours?.view;
  const shelf = yv === "albums" || (yv === "songs" && yoursView("songs") === "grid");
  els.folders.classList.toggle("yours-lib", shelf);
  if (!shelf) els.folders.classList.remove("yours-grid", "yours-list");
  if (shelf) { els.folders.classList.remove("as-list"); renderYoursLibrary(state.folder); return; }
  const q = fold(state.filter);
  const folders = (state.folder?.folders || []).filter((f) => !q || fold(f.name).includes(q));
  const list = folderView() === "list";
  els.folders.classList.toggle("as-list", list);
  const f = state.folder;
  if (f && !f.search && folders.length) {
    const title = foldersTitle(f);
    sectionHead(els.foldersHead, title, plural(folders.length, title === "Albums" ? "album" : title === "Artists" ? "artist" : "folder"), folderToggle());
  }
  drawInBatches(els.folders, folders, (f) => list
    ? h("a", { class: "folder", href: hashFor(f.path), title: f.name, "data-path": f.path },
      icon("folder"), h("span", { class: "folder-name", translate: "no" }, f.name),
      h("span", { class: "folder-meta" }, folderSummary(f)), icon("chevron"))
    : h("a", { class: "folder", href: hashFor(f.path), title: f.name, "data-path": f.path },
      h("span", { class: "folder-cover" }, folderCoverImg(f.path) || icon("folder")),
      h("span", { class: "folder-text" }, h("span", { class: "folder-name", translate: "no" }, f.name),
        h("span", { class: "folder-meta" }, folderSummary(f)))));
  if (!list) loadFolderCovers(folders.map((f) => f.path));
}

// Grid view: each folder shows the cover of a track inside it (found in the search index).
export const folderCovers = new Map(); // folder path -> {path, hash} | null (none found)

function folderCoverImg(folder) {
  const c = folderCovers.get(folder);
  return c ? fitCover(h("img", { src: `/api/art?path=${encodeURIComponent(c.path)}&v=${c.hash}`, alt: "", loading: "lazy", decoding: "async",
    onerror: (e) => e.currentTarget.replaceWith(icon("folder")) })) : null;
}

async function loadFolderCovers(paths) {
  const todo = paths.filter((p) => !folderCovers.has(p) && !isSpecialPath(p));
  for (let i = 0; i < todo.length; i += 200) {
    const chunk = todo.slice(i, i + 200);
    let found = {};
    try { found = (await api("POST", "/api/folder-covers", { paths: chunk })).covers; } catch { return; }
    for (const p of chunk) {
      folderCovers.set(p, found[p] || null);
      const img = found[p] && folderCoverImg(p);
      const slot = img && els.folders.querySelector(`.folder[data-path="${CSS.escape(p)}"] .folder-cover`);
      if (slot) slot.replaceChildren(img);
    }
  }
}

export function renderTracks() {
  state.rows.clear();
  const f = state.folder;
  els.tracksHead.hidden = true;
  if (!f) return;
  if (f.mb) { els.tracks.replaceChildren(); return; }
  if (f.yours && !f.tracks.length) { els.tracks.replaceChildren(); return; } // the head says what's empty
  if (f.yours?.view === "songs" && yoursView("songs") === "grid") { els.tracks.replaceChildren(); return; } // drawn as cards
  const tracks = visibleTracks();
  if (!f.search && !f.mb && !f.yours && tracks.length) sectionHead(els.tracksHead, "Tracks", plural(tracks.length, "track"));

  if (!f.tracks.length && f.search) {
    els.tracks.replaceChildren();
    els.folders.replaceChildren(h("div", { class: "empty" },
      h("strong", {}, "Nothing found"),
      h("span", {}, "Try fewer words, or search a tag: "),
      h("code", {}, "genre: rap, hip-hop"), " · ", h("code", {}, "artist: drake"), " · ", h("code", {}, "year: 2024")));
    return;
  }
  if (!f.tracks.length) {
    els.tracks.replaceChildren();
    if (!f.folders.length) {
      els.folders.replaceChildren(h("div", { class: "empty" },
        h("strong", {}, "No audio files here"),
        "Codetta shows FLAC, MP3, M4A, OGG, Opus, WAV, AIFF, WMA, WavPack, DSF and more."));
    }
    return;
  }
  if (!tracks.length) {
    els.tracks.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "No matches"),
      state.filter ? `Nothing here matches “${state.filter}”` : "No tracks in this folder match the tag filter.",
      state.tagFilters.length && state.filter ? " with the tag filter." : state.filter ? "." : ""));
    return;
  }

  const allSelected = tracks.every((t) => state.selected.has(t.path));
  const someSelected = tracks.some((t) => state.selected.has(t.path));
  const head = h("div", { class: "track-row head", role: "row" },
    h("label", { class: "check-cell", title: "Select all" },
      h("input", {
        type: "checkbox", "aria-label": "Select all tracks",
        checked: allSelected, indeterminate: someSelected && !allSelected,
        onchange: (e) => selectAll(e.target.checked),
      })),
    h("div", { class: "col-num" }, "#"),
    h("div", { class: "col-art", "aria-hidden": "true" }),
    h("div", {}, "Title"),
    h("div", { class: "col-artist" }, "Artist"),
    h("div", { class: "col-album" }, "Album"),
    h("div", { class: "col-fmt" }, "Format"),
    h("div", { class: "col-dur" }, "Time"),
    h("div", { class: "col-play" }),
  );
  const discs = discInfo();
  els.tracks.classList.toggle("multi-disc", !!discs);

  // A folder that is one album reads like a booklet: no column repeats a value
  // every row shares (album, album artist, format, cover).
  const readable = f.tracks.filter((t) => !t.error);
  const sameAll = (fn) => readable.length > 1 && readable.every((t) => fn(t) === fn(readable[0]));
  const artistOf = (t) => (t.tags.artist || []).join(", ");
  const oneAlbum = !f.search && sameAll((t) => first(t, "album")) && first(readable[0], "album") !== ""
    && sameAll((t) => t.art?.hash || "");
  const albumArtist = oneAlbum ? first(readable[0], "albumartist") || (sameAll(artistOf) ? artistOf(readable[0]) : "") : "";
  const sameArtist = oneAlbum && albumArtist !== "" && readable.every((t) => artistOf(t) === albumArtist);
  const oneFormat = !f.search && sameAll((t) => t.format || "");
  els.tracks.classList.toggle("one-album", oneAlbum);
  els.tracks.classList.toggle("same-artist", sameArtist);
  els.tracks.classList.toggle("one-format", oneFormat);
  const col = (show, width) => (show ? [width] : []);
  const cols = (withAlbum) => ["44px", "40px", ...col(!oneAlbum, "48px"), "minmax(0, 2.2fr)", ...col(!sameArtist, "minmax(0, 1.4fr)"),
    ...col(!oneAlbum && withAlbum, "minmax(0, 1.4fr)"), ...col(!oneFormat, "76px"), "60px", "56px"].join(" ");
  els.tracks.style.setProperty("--cols", cols(true));
  els.tracks.style.setProperty("--cols-mid", cols(false));

  // What to draw, in order: disc separators and tracks (built lazily, a batch at a time).
  const items = [];
  let lastDisc = null;
  for (const t of tracks) {
    const disc = discs && !t.error ? discs.discOf(t) : null;
    if (discs && disc !== lastDisc && disc !== null) {
      items.push({ discHead: disc, t });
      lastDisc = disc;
    }
    items.push({ t, disc });
  }
  const build = (it) => {
    if (it.discHead != null) {
      const subtitle = first(it.t, "discsubtitle");
      return h("div", { class: "disc-head", role: "row", dataset: { disc: String(it.discHead) } },
        h("span", { class: "disc-spin" }, icon("disc")),
        h("span", { class: "disc-name" }, `Disc ${it.discHead}`),
        subtitle ? h("span", { class: "disc-sub", dir: "auto" }, subtitle) : null);
    }
    return trackRow(it.t, { oneAlbum, albumArtist, disc: it.disc });
  };
  drawInBatches(els.tracks, items, build, { head: [head], done: () => { updateRowStates(); syncPlayer(); } });
  updateRowStates();
  syncPlayer();
}

/** The line under a track's title: its artist (with their pictures on phones) and album. */
function subLine(t, { artist, album, title, oneAlbum, albumArtist }) {
  const text = t.error ? t.error
    : oneAlbum ? (artist && artist !== albumArtist ? artist : "")
      : [artist, album].filter(Boolean).join(" · ") || (title ? t.name : `${fmtLabel(t.format)} · No tags yet`);
  const sub = h("span", { class: "sub", translate: t.error || !(artist || album || title) ? null : "no" }, h("span", { class: "sub-text" }, text));
  return sub;
}

/** In Your music lists, a song's place in the list (1, 2, 3…) instead of its album track number. */
function yoursPosition(t) {
  const f = state.folder;
  if (!f?.yours) return null;
  if (!f.positions) f.positions = new Map(f.tracks.map((x, i) => [x, String(i + 1)]));
  return f.positions.get(t) ?? null;
}

function trackRow(t, { oneAlbum, albumArtist, disc }) {
  const title = first(t, "title");
  const artist = (t.tags.artist || []).join(", ");
  const album = first(t, "album");
  const checkbox = h("input", {
    type: "checkbox",
    "aria-label": `Select ${title || t.name}`,
    checked: state.selected.has(t.path),
    onclick: (e) => { e.stopPropagation(); toggleSelect(t.path, e.target.checked, e.shiftKey); },
  });
  const row = h("div", {
    class: `track-row${t.error ? " has-error" : ""}`,
    tabindex: "0",
    role: "row",
    dataset: { path: t.path },
    onclick: (e) => {
      if (e.target.closest(".check-cell")) return;
      if (state.selectMode && isPhone()) toggleSelect(t.path, !state.selected.has(t.path), false);
      else openTrack(t);
    },
    onkeydown: (e) => {
      if (e.key === "Enter" && e.target === row) openTrack(t);
      if (e.key === " " && e.target === row) { e.preventDefault(); checkbox.click(); }
    },
  },
    h("label", { class: "check-cell", onclick: (e) => e.stopPropagation() }, checkbox),
    h("div", { class: "col-num" }, yoursPosition(t) ?? (disc != null
      // Multi-disc: pointing at a row shows "2/01" (disc/track).
      ? [h("span", { class: "num-track" }, trackNo(first(t, "tracknumber"))),
        h("span", { class: "num-disc" }, `${disc}/${trackNo(first(t, "tracknumber"))}`)]
      : trackNo(first(t, "tracknumber")))),
    h("div", { class: "col-art" }, t.art
      ? h("img", { src: artUrlFor(t), alt: "", loading: "lazy", decoding: "async", width: "40", height: "40" })
      : h("span", { class: "art-none", title: "No album art" }, icon("note"))),
    h("div", { class: "col-title" },
      h("span", { class: "main", translate: "no" }, title || h("span", { class: "untitled" }, t.name)),
      subLine(t, { artist, album, title, oneAlbum, albumArtist }),
      title ? h("span", { class: "fname", translate: "no", dir: "auto" }, t.name) : null), // the file itself, at a glance
    h("div", { class: "col-artist", translate: t.error ? null : "no" }, t.error ? t.error : artist ? artistButton(artist, t.tags.artist || []) : ""),
    h("div", { class: "col-album", translate: "no" }, album),
    h("div", { class: "col-fmt" }, t.format ? h("span", { class: "badge" }, fmtLabel(t.format)) : ""),
    h("div", { class: "col-dur" }, fmtDuration(t.duration)),
    h("div", { class: "col-play" }, reorderGrip(t) || (!t.error && canPlay(t.format) ? h("button", {
      class: "play-btn", type: "button", "aria-label": `Play ${title || t.name}`,
      onclick: (e) => { e.stopPropagation(); togglePlay(t); },
    }, icon("play"), h("span", { class: "play-label" }, "Play")) : null)),
  );
  state.rows.set(t.path, { row, checkbox, track: t });
  return row;
}
