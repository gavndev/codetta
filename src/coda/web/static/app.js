// Coda UI — plain JavaScript, no framework, no build step.
//
// Talks to the JSON API in coda/web/app.py. The current folder lives in the
// URL hash (#/Artist/Album), so the back button and refresh work.

// ---- Tiny DOM helpers ----------------------------------------------------------

const $ = (sel, root = document) => root.querySelector(sel);

/** Create an element: h("div", {class: "x", onclick: fn}, child, "text", ...) */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (["value", "checked", "disabled", "indeterminate", "open"].includes(k)) el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

/** Like el.replaceChildren(...), but skips null/false (which would render as "null"). */
function setKids(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
}

// ---- Motion helpers ------------------------------------------------------------------

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Play an exit animation (CSS class ``cls``), then call ``done``. Instant with reduced motion. */
function playOut(el, cls, done) {
  if (reducedMotion() || el.hidden) { done(); return; }
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    el.classList.remove(cls);
    done();
  };
  el.classList.add(cls);
  el.addEventListener("animationend", finish, { once: true });
  setTimeout(finish, 400); // safety net if the animation doesn't run
}

/** Restart an entrance animation class on an element. */
function replay(el, cls) {
  el.classList.remove("nav-forward", "nav-back", "nav-fade");
  void el.offsetWidth; // force reflow so the animation starts again
  el.classList.add(cls);
}

function closeDialog(dialog) {
  if (!dialog.open || dialog.classList.contains("closing")) return;
  dialog.cancelClose = false;
  playOut(dialog, "closing", () => { if (!dialog.cancelClose) dialog.close(); });
}

function openDialog(dialog) {
  if (dialog.open) {
    // Reopened while its close animation was still playing: keep it open.
    dialog.cancelClose = true;
    dialog.classList.remove("closing");
    return;
  }
  dialog.showModal();
}

const ICONS = {
  folder: '<svg viewBox="0 0 20 20"><path d="M2.5 5.5a1.5 1.5 0 0 1 1.5-1.5h3.6l1.8 2H16a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 16 16H4a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  close: '<svg viewBox="0 0 20 20"><path d="m5 5 10 10M15 5 5 15"/></svg>',
  clear: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="m7.5 7.5 5 5m0-5-5 5"/></svg>',
  sun: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="3.5"/><path d="M10 2v2m0 12v2M2 10h2m12 0h2M4.3 4.3l1.4 1.4m8.6 8.6 1.4 1.4M4.3 15.7l1.4-1.4m8.6-8.6 1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 20 20"><path d="M16 12.5A6.5 6.5 0 0 1 7.5 4a6.5 6.5 0 1 0 8.5 8.5z"/></svg>',
  auto: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="M10 3a7 7 0 0 1 0 14z" fill="currentColor" stroke="none"/></svg>',
  plus: '<svg viewBox="0 0 20 20"><path d="M10 4v12M4 10h12"/></svg>',
  copy: '<svg viewBox="0 0 20 20"><rect x="7" y="7" width="9.5" height="9.5" rx="2"/><path d="M13 7V5a1.5 1.5 0 0 0-1.5-1.5h-6A1.5 1.5 0 0 0 4 5v6A1.5 1.5 0 0 0 5.5 12.5H7"/></svg>',
  spark: '<svg viewBox="0 0 20 20"><path d="M10 3.5 11.4 8.6 16.5 10l-5.1 1.4L10 16.5l-1.4-5.1L3.5 10l5.1-1.4z"/></svg>',
  paste: '<svg viewBox="0 0 20 20"><rect x="4.5" y="4" width="11" height="13" rx="2"/><path d="M8 4V3h4v1"/><path d="M7.5 9h5M7.5 12h3"/></svg>',
};

function icon(name) {
  const t = document.createElement("template");
  t.innerHTML = ICONS[name].trim();
  const svg = t.content.firstChild;
  svg.setAttribute("aria-hidden", "true");
  return svg;
}

// ---- API -----------------------------------------------------------------------------

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const d = data && data.detail;
    const msg = typeof d === "string" ? d
      : Array.isArray(d) ? d.map((e) => e.msg).join("; ")
      : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}

// ---- State -------------------------------------------------------------------------------

const state = {
  path: "",
  folder: null,           // last /api/browse response
  fields: [],             // known tags, in display order
  fieldMap: new Map(),
  placeholders: [],
  loadouts: [],
  selected: new Set(),    // selected track paths
  lastClicked: null,      // for shift-click ranges
  filter: "",
  editor: null,           // { paths, changes: Map, extraKeys: [], errors: [] }
  rows: new Map(),        // track path -> { row, checkbox }
  tagFilters: [],         // [{ key, value }] — value "" means "has no value"
  clipboard: loadClipboard(), // copied tags: { tags: {key: [values]}, from }
  loadToken: 0,
};

const els = {
  crumbs: $("#crumbs"),
  banner: $("#banner"),
  folderHead: $("#folder-head"),
  folders: $("#folders"),
  tracks: $("#tracks"),
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

const fmtDuration = (s) => {
  if (!s && s !== 0) return "";
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, "0")}`;
};
const first = (track, key) => (track.tags[key] || [])[0] || "";
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const baseName = (path) => path.split("/").pop();

function relativeToFolder(path) {
  const prefix = state.path ? state.path + "/" : "";
  return path.startsWith(prefix) ? path.slice(prefix.length) : path;
}

// ---- Toasts --------------------------------------------------------------------------------

function toast(message, kind = "") {
  const el = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  els.toasts.append(el);
  setTimeout(() => playOut(el, "leaving", () => el.remove()), kind === "error" ? 7000 : 3500);
}

// ---- Theme -----------------------------------------------------------------------------------

const THEMES = ["system", "light", "dark"];
const THEME_LABEL = { system: "Theme: match system", light: "Theme: light", dark: "Theme: dark" };
const THEME_ICON = { system: "auto", light: "sun", dark: "moon" };

function getTheme() {
  try { return localStorage.getItem("coda-theme") || "system"; } catch { return "system"; }
}

function setTheme(theme) {
  try { localStorage.setItem("coda-theme", theme); } catch { /* private mode */ }
  // Crossfade the whole page between themes where the browser supports it.
  if (document.startViewTransition && !reducedMotion()) document.startViewTransition(() => applyTheme(theme));
  else applyTheme(theme);
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
  const btn = $("#theme-btn");
  btn.replaceChildren(icon(THEME_ICON[theme]));
  btn.title = THEME_LABEL[theme];
  btn.setAttribute("aria-label", THEME_LABEL[theme]);
  // Browser chrome / iOS status bar colour.
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
    const dark = meta.media.includes("dark");
    const color = theme === "system" ? (dark ? "#111113" : "#f5f5f7") : theme === "dark" ? "#111113" : "#f5f5f7";
    meta.content = color;
  }
}

// ---- Routing ------------------------------------------------------------------------------------

function pathFromHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  try {
    return raw.split("/").filter(Boolean).map(decodeURIComponent).join("/");
  } catch {
    return "";
  }
}

function hashFor(path) {
  return "#/" + path.split("/").filter(Boolean).map(encodeURIComponent).join("/");
}

let ignoreHashChange = false;

function onHashChange() {
  if (ignoreHashChange) { ignoreHashChange = false; return; }
  const path = pathFromHash();
  if (path === state.path && state.folder) return;
  if (!confirmDiscard()) {
    ignoreHashChange = true;
    location.hash = hashFor(state.path);
    return;
  }
  loadFolder(path);
}

// ---- Browsing --------------------------------------------------------------------------------------

// Folders you've visited are remembered, so going back is instant. Each visit
// still asks the server for fresh data in the background and only redraws if
// something actually changed (e.g. edited on another device).
const folderCache = new Map();   // folder path -> /api/browse response
const scrollMemory = new Map();  // folder path -> scroll position
const MAX_CACHED_FOLDERS = 60;

function rememberFolder(data) {
  folderCache.delete(data.path);
  folderCache.set(data.path, data);
  if (folderCache.size > MAX_CACHED_FOLDERS) folderCache.delete(folderCache.keys().next().value);
}

async function loadFolder(path, { keepScroll = false } = {}) {
  const token = ++state.loadToken;
  const navigating = !state.folder || path !== state.path;
  if (state.folder && navigating) scrollMemory.set(state.path, els.browser.scrollTop);

  const cached = navigating ? folderCache.get(path) : null;
  let loadingTimer = null;
  if (cached) {
    showFolder(cached, scrollMemory.get(path) ?? 0);
  } else if (navigating) {
    // Only show "Loading…" if the server is slow, to avoid a flash.
    loadingTimer = setTimeout(() => {
      els.folderHead.replaceChildren(h("p", { class: "loading" }, "Loading…"));
      els.folders.replaceChildren();
      els.tracks.replaceChildren();
    }, 200);
  }

  try {
    const data = await api("GET", `/api/browse?path=${encodeURIComponent(path)}`);
    clearTimeout(loadingTimer);
    if (token !== state.loadToken) return; // a newer navigation won
    const unchanged = cached && JSON.stringify(cached) === JSON.stringify(data);
    rememberFolder(unchanged ? cached : data);
    if (unchanged) return;
    const scroll = cached || keepScroll ? els.browser.scrollTop : scrollMemory.get(data.path) ?? 0;
    showFolder(data, scroll);
  } catch (err) {
    clearTimeout(loadingTimer);
    if (token !== state.loadToken) return;
    folderCache.delete(path);
    state.folder = null;
    els.folderHead.replaceChildren();
    els.tracks.replaceChildren();
    els.folders.replaceChildren(
      h("div", { class: "empty" },
        h("strong", {}, "Couldn't open this folder"),
        h("span", {}, err.message), h("br"),
        h("a", { href: "#/" }, "Back to library")),
    );
  }
}

function showFolder(data, scrollTop) {
  const sameFolder = state.folder && data.path === state.path;
  if (!sameFolder) {
    const prev = state.folder ? state.path : null;
    const deeper = prev !== null && (prev === "" ? data.path !== "" : data.path.startsWith(prev + "/"));
    const shallower = prev !== null && (data.path === "" ? prev !== "" : prev.startsWith(data.path + "/"));
    const cls = deeper ? "nav-forward" : shallower ? "nav-back" : "nav-fade";
    for (const el of [els.folderHead, els.folders, els.tracks]) replay(el, cls);
  }
  state.folder = data;
  state.path = data.path;
  if (!sameFolder) {
    state.selected.clear();
    state.lastClicked = null;
    state.filter = "";
    els.filter.value = "";
    state.tagFilters = [];
    closeEditor(true);
  } else {
    // Keep only selections that still exist.
    const paths = new Set(data.tracks.map((t) => t.path));
    for (const p of state.selected) if (!paths.has(p)) state.selected.delete(p);
    if (state.editor) renderEditor(); // show the fresh tags
  }
  document.title = data.path ? `${data.name} — Coda` : "Coda";
  renderBrowser();
  els.browser.scrollTop = scrollTop;
}

function trackByPath(path) {
  return state.folder?.tracks.find((t) => t.path === path);
}

function matchesTagFilters(track) {
  return state.tagFilters.every(({ key, value }) => {
    const values = (track.tags[key] || []).map((v) => v.toLowerCase());
    return value === "" ? values.length === 0 : values.includes(value.toLowerCase());
  });
}

function matchesFilter(track) {
  if (!matchesTagFilters(track)) return false;
  if (!state.filter) return true;
  const q = state.filter.toLowerCase();
  return [track.name, first(track, "title"), first(track, "artist"), first(track, "album")]
    .some((s) => s.toLowerCase().includes(q));
}

function visibleTracks() {
  return (state.folder?.tracks || []).filter(matchesFilter);
}

function renderBrowser() {
  renderCrumbs();
  renderFolderHead();
  renderFilterChips();
  renderFolders();
  renderTracks();
  renderSelectionBar();
}

function renderCrumbs() {
  const crumbs = state.folder?.breadcrumbs || [{ name: "Library", path: "" }];
  const parts = [];
  crumbs.forEach((c, i) => {
    if (i) parts.push(h("span", { class: "sep", "aria-hidden": "true" }, "›"));
    parts.push(h("a", {
      href: hashFor(c.path),
      "aria-current": i === crumbs.length - 1 ? "page" : null,
      title: c.name,
    }, c.name));
  });
  els.crumbs.replaceChildren(...parts);
  els.crumbs.scrollLeft = els.crumbs.scrollWidth; // show the deepest part on phones
}

function renderFolderHead() {
  const f = state.folder;
  if (!f) return;
  const counts = [];
  if (f.folders.length) counts.push(plural(f.folders.length, "folder"));
  if (f.tracks.length) counts.push(plural(f.tracks.length, "track"));
  els.folderHead.replaceChildren(
    h("div", {},
      h("h1", {}, f.path ? f.name : "Library"),
      h("p", {}, counts.join(" · ") || "Empty folder")),
    h("div", { class: "folder-actions" },
      f.tracks.length || f.folders.length ? h("button", {
        class: "btn", type: "button", onclick: () => openApply("folder"),
      }, "Apply loadout…") : null),
  );
}

function renderFolders() {
  const q = state.filter.toLowerCase();
  const folders = (state.folder?.folders || []).filter((f) => !q || f.name.toLowerCase().includes(q));
  els.folders.replaceChildren(...folders.map((f) =>
    h("a", { class: "folder", href: hashFor(f.path), title: f.name }, icon("folder"), h("span", {}, f.name))));
}

function renderTracks() {
  state.rows.clear();
  const f = state.folder;
  if (!f) return;
  const tracks = visibleTracks();

  if (!f.tracks.length) {
    els.tracks.replaceChildren();
    if (!f.folders.length) {
      els.folders.replaceChildren(h("div", { class: "empty" },
        h("strong", {}, "No audio files here"),
        "Coda shows FLAC, MP3, M4A, OGG and Opus files."));
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
    h("div", {}, "Title"),
    h("div", { class: "col-artist" }, "Artist"),
    h("div", { class: "col-album" }, "Album"),
    h("div", { class: "col-fmt" }, "Format"),
    h("div", { class: "col-dur" }, "Time"),
  );

  const rows = tracks.map((t) => {
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
      onclick: (e) => { if (!e.target.closest(".check-cell")) openTrack(t); },
      onkeydown: (e) => {
        if (e.key === "Enter") openTrack(t);
        if (e.key === " " && e.target === row) { e.preventDefault(); checkbox.click(); }
      },
    },
      h("label", { class: "check-cell", onclick: (e) => e.stopPropagation() }, checkbox),
      h("div", { class: "col-num" }, (first(t, "tracknumber").split("/")[0]) || ""),
      h("div", { class: "col-title" },
        h("span", { class: "main" }, title || h("span", { class: "untitled" }, t.name)),
        h("span", { class: "sub" }, t.error ? t.error
          : [artist, album].filter(Boolean).join(" · ") || (title ? t.name : `${(t.format || "").toUpperCase()} · No tags yet`))),
      h("div", { class: "col-artist" }, t.error ? t.error : artist),
      h("div", { class: "col-album" }, album),
      h("div", { class: "col-fmt" }, t.format ? h("span", { class: "badge" }, t.format) : ""),
      h("div", { class: "col-dur" }, fmtDuration(t.duration)),
    );
    state.rows.set(t.path, { row, checkbox });
    return row;
  });
  els.tracks.replaceChildren(head, ...rows);
  updateRowStates();
}

function openTrack(track) {
  if (track.error) { toast(`Can't read this file: ${track.error}`, "error"); return; }
  openEditor([track.path]);
}

// ---- Tag filter ---------------------------------------------------------------------------------------

function renderFilterChips() {
  const chips = state.tagFilters.map((f, i) => h("span", { class: "filter-chip" },
    h("span", {}, h("b", {}, fieldLabel(f.key)), ": ", f.value === "" ? h("i", {}, "empty") : f.value),
    h("button", {
      type: "button", class: "chip-x", "aria-label": `Remove filter ${fieldLabel(f.key)}`,
      onclick: () => { state.tagFilters.splice(i, 1); renderBrowser(); },
    }, icon("close"))));
  if (chips.length > 1) {
    chips.push(h("button", { type: "button", class: "link-btn", onclick: () => { state.tagFilters = []; renderBrowser(); } }, "Clear all"));
  }
  if (chips.length) {
    const shown = visibleTracks().length;
    chips.unshift(h("span", { class: "filter-count" }, `${shown} of ${state.folder?.tracks.length || 0}`));
  }
  setKids(els.filterChips, chips);
  els.filterChips.hidden = !chips.length;
  $("#tagfilter-btn").classList.toggle("active", state.tagFilters.length > 0);
}

/** tag key -> Map(value -> count) for tracks in this folder. */
function folderTagValues() {
  const out = new Map();
  for (const t of state.folder?.tracks || []) {
    for (const [key, values] of Object.entries(t.tags)) {
      if (!out.has(key)) out.set(key, new Map());
      for (const v of values) out.get(key).set(v, (out.get(key).get(v) || 0) + 1);
    }
  }
  return out;
}

function openTagFilter() {
  if (!state.folder?.tracks.length) { toast("There are no tracks in this folder to filter"); return; }
  const values = folderTagValues();
  const order = state.fields.map((f) => f.key);
  const keys = [...values.keys()].sort((a, b) => {
    const ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib) || a.localeCompare(b);
  });
  if (!keys.length) { toast("None of these tracks have tags yet"); return; }
  const keySel = $("#filter-key");
  setKids(keySel, keys.map((k) => h("option", { value: k }, fieldLabel(k))));
  const fillValues = () => {
    const counts = values.get(keySel.value) || new Map();
    const total = state.folder.tracks.length;
    const withTag = state.folder.tracks.filter((t) => (t.tags[keySel.value] || []).length).length;
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    setKids($("#filter-value"),
      sorted.map(([v, n]) => h("option", { value: v }, `${v} (${n})`)),
      withTag < total ? h("option", { value: "" }, `— No value — (${total - withTag})`) : null);
  };
  keySel.onchange = fillValues;
  fillValues();
  openDialog(els.filterDialog);
}

function addTagFilter() {
  const key = $("#filter-key").value;
  const value = $("#filter-value").value;
  if (!key) return;
  state.tagFilters = state.tagFilters.filter((f) => f.key !== key); // one value per tag
  state.tagFilters.push({ key, value });
  closeDialog(els.filterDialog);
  renderBrowser();
}

// ---- Selection -----------------------------------------------------------------------------------

function toggleSelect(path, checked, shift) {
  const visible = visibleTracks().map((t) => t.path);
  if (shift && state.lastClicked && visible.includes(state.lastClicked)) {
    const [a, b] = [visible.indexOf(state.lastClicked), visible.indexOf(path)].sort((x, y) => x - y);
    for (const p of visible.slice(a, b + 1)) checked ? state.selected.add(p) : state.selected.delete(p);
  } else {
    checked ? state.selected.add(path) : state.selected.delete(path);
  }
  state.lastClicked = path;
  updateRowStates();
  renderSelectionBar();
}

function selectAll(checked) {
  for (const t of visibleTracks()) checked ? state.selected.add(t.path) : state.selected.delete(t.path);
  updateRowStates();
  renderSelectionBar();
}

function updateRowStates() {
  const editing = new Set(state.editor?.paths || []);
  for (const [path, { row, checkbox }] of state.rows) {
    const sel = state.selected.has(path);
    checkbox.checked = sel;
    row.classList.toggle("selected", sel);
    row.classList.toggle("editing", editing.has(path));
  }
  const all = $(".track-row.head input", els.tracks);
  if (all) {
    const vis = visibleTracks();
    const n = vis.filter((t) => state.selected.has(t.path)).length;
    all.checked = n > 0 && n === vis.length;
    all.indeterminate = n > 0 && n < vis.length;
  }
}

function renderSelectionBar() {
  const n = state.selected.size;
  if (n === 0 && !els.selBar.hidden) {
    if (!els.selBar.classList.contains("leaving")) {
      playOut(els.selBar, "leaving", () => { if (state.selected.size === 0) els.selBar.hidden = true; });
    }
  } else if (n > 0) {
    els.selBar.classList.remove("leaving");
    els.selBar.hidden = false;
  }
  els.selCount.textContent = `${n} selected`;
}

// ---- Editor -----------------------------------------------------------------------------------------

function editorTracks() {
  return (state.editor?.paths || []).map(trackByPath).filter(Boolean);
}

function isDirty() {
  return !!state.editor && state.editor.changes.size > 0;
}

function confirmDiscard() {
  return !isDirty() || window.confirm("Discard your unsaved tag changes?");
}

function openEditor(paths) {
  if (state.editor && !confirmDiscard()) return;
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
}

function closeEditor(force = false) {
  if (!state.editor) return;
  if (!force && !confirmDiscard()) return;
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

function renderEditor() {
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
    els.editorSub.textContent = byline || (first(t, "title") ? relativeToFolder(t.path) : "No tags yet");
  } else {
    els.editorTitle.textContent = `Editing ${tracks.length} tracks`;
    els.editorSub.textContent = "Only the fields you change are saved";
  }

  const parts = [artEl(tracks)];

  // File info
  if (tracks.length === 1) {
    const t = tracks[0];
    parts.push(h("div", { class: "file-info" },
      h("span", { class: "badge" }, t.format),
      t.duration != null && h("span", { class: "num" }, fmtDuration(t.duration)),
      t.bitrate && h("span", { class: "num" }, `${Math.round(t.bitrate / 1000)} kbps`),
      t.sample_rate && h("span", { class: "num" }, `${(t.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz`),
      t.channels && h("span", {}, t.channels === 1 ? "Mono" : t.channels === 2 ? "Stereo" : `${t.channels} ch`),
      h("span", { class: "path" }, t.path)));
  } else {
    const formats = [...new Set(tracks.map((t) => t.format))].join(", ");
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
  setKids(els.editorForm, parts);
  renderToolbar();
  updateSaveButton();
}

// ---- Editor toolbar: copy & paste tags ---------------------------------------------------------

function loadClipboard() {
  try { return JSON.parse(localStorage.getItem("coda-clipboard")) || null; } catch { return null; }
}

function saveClipboard(clip) {
  state.clipboard = clip;
  try {
    if (clip) localStorage.setItem("coda-clipboard", JSON.stringify(clip));
    else localStorage.removeItem("coda-clipboard");
  } catch { /* private mode: clipboard just won't survive a reload */ }
}

function fieldLabel(key) {
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
  const split = state.fieldMap.get(key)?.multi || state.editor?.model.get(key)?.multiValued;
  return split ? value.split(";").map((v) => v.trim()).filter(Boolean) : [value];
}

function renderToolbar() {
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

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
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
  if (field.key === "date" || field.key === "originaldate") {
    if (DATE_OK.test(v)) return null;
    const fix = suggestDate(v);
    return { text: "Players expect dates like 2026-10-23 (or just 2026).", fix, fixLabel: fix && `Use ${fix}` };
  }
  if (field.multi && v.includes(",") && !v.includes(";")) {
    const parts = v.split(",").map((x) => x.trim()).filter(Boolean);
    if (parts.length < 2) return null;
    return {
      text: `This saves as one ${field.label.toLowerCase()}. Use ; to separate.`,
      fix: parts.join("; "), fixLabel: `Split into ${parts.length}`,
    };
  }
  return null;
}

function fieldEl(field, model) {
  const ed = state.editor;
  const key = field.key;
  const m = model.get(key) || { value: "", mixed: false, present: false, multiValued: false };
  const id = `f-${key}`;
  const change = ed.changes.get(key);
  const isLong = key === "comment";

  const flag = h("span", { class: "flag" });
  const hintEl = h("div", { class: "field-hint", hidden: true });
  const suggestBox = h("div", { class: "suggest", role: "listbox", hidden: true });
  const hasSuggestions = !isLong && folderSuggestions(key).some((sg) => sg.value !== m.value || m.mixed);
  const wrap = h("div", { class: "field", dataset: { key } });
  const input = isLong
    ? h("textarea", { id, rows: "3", spellcheck: "true" })
    : h("input", { id, type: "text", spellcheck: "false", autocapitalize: "off", inputmode: ["tracknumber", "discnumber", "bpm"].includes(key) ? "numeric" : null });
  input.value = change ? change.value : m.value;

  const basePlaceholder = m.mixed ? "Multiple values — leave to keep"
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
    class: "icon-btn clear", type: "button", "aria-label": `Clear ${field.label}`, title: "Remove this tag",
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
      flag),
    isLong ? input : h("div", { class: "input-wrap" }, input, clearBtn, suggestBox),
    hintEl,
  );
  if (!isLong) attachSuggestions(input, key, suggestBox);
  refresh();
  return wrap;
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

function folderTrackPaths() {
  return (state.folder?.tracks || []).filter((t) => !t.error).map((t) => t.path);
}

function updateSaveButton() {
  const ed = state.editor;
  const n = ed?.changes.size || 0;
  els.editorSave.disabled = n === 0;
  els.editorSave.textContent = n ? `Save ${n > 1 ? `(${n})` : ""}`.trim() : "Save";
  // "Save to folder" only makes sense if it reaches more tracks than "Save" does.
  const folderPaths = folderTrackPaths();
  const covers = ed && folderPaths.every((p) => ed.paths.includes(p));
  els.editorSaveFolder.hidden = !ed || covers;
  els.editorSaveFolder.disabled = n === 0;
  els.editorSaveFolder.textContent = n ? `Save to folder (${n})` : "Save to folder";
  renderChangesPopover(folderPaths.length);
}

/** Hovering either Save button shows exactly what will change. */
function renderChangesPopover(folderCount) {
  const pop = $("#changes-pop");
  const ed = state.editor;
  if (!ed || !ed.changes.size) { pop.replaceChildren(); return; }
  const rows = [...ed.changes.entries()].map(([key, c]) => {
    const m = ed.model.get(key);
    const old = m?.mixed ? "various" : m?.value || "";
    return h("li", {},
      h("span", { class: "pop-key" }, fieldLabel(key)),
      h("span", { class: "pop-val" },
        old ? [h("s", {}, old), " → "] : null,
        c.remove ? h("span", { class: "pop-removed" }, "removed") : h("span", {}, c.value)));
  });
  const n = ed.paths.length;
  setKids(pop,
    h("div", { class: "pop-head" }, `${plural(ed.changes.size, "change")}`),
    h("ul", {}, rows),
    h("div", { class: "pop-foot" },
      `Save → ${n === 1 ? "this track" : `${n} selected tracks`}`,
      els.editorSaveFolder.hidden ? null : ` · Save to folder → all ${folderCount} tracks`));
}

// Tags that are normally different on every track of an album.
const PER_TRACK_KEYS = new Set(["title", "tracknumber", "isrc", "comment", "bpm"]);

function saveToFolder() {
  const ed = state.editor;
  if (!ed || !ed.changes.size) return;
  const paths = folderTrackPaths();
  const keys = [...ed.changes.keys()];
  const risky = keys.filter((k) => PER_TRACK_KEYS.has(k)).map(fieldLabel);
  const folderName = state.folder.path ? state.folder.name : "Library";
  let msg = `Save ${keys.map(fieldLabel).join(", ")} to all ${paths.length} tracks in “${folderName}”?`;
  if (risky.length) msg += `\n\nHeads up: ${risky.join(", ")} ${risky.length === 1 ? "is" : "are"} usually different on every track, so all ${paths.length} would get the same value.`;
  if (!window.confirm(msg)) return;
  saveEditor(paths);
}

async function saveEditor(targetPaths = null) {
  const ed = state.editor;
  if (!ed || !ed.changes.size) return;
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
  try {
    const results = await api("PATCH", "/api/tracks", { paths, changes });
    const failed = results.filter((r) => !r.ok);
    for (const r of results) {
      if (!r.ok) continue;
      const i = state.folder.tracks.findIndex((t) => t.path === r.path);
      if (i >= 0) state.folder.tracks[i] = r.track;
    }
    if (state.editor !== ed) return; // closed meanwhile
    ed.errors = failed.map((r) => `${baseName(r.path)}: ${r.error}`);
    ed.copyMode = false;
    if (!failed.length) {
      ed.changes.clear();
      toast(results.length === 1 ? "Saved" : targetPaths ? `Saved to all ${results.length} tracks in this folder` : `Saved ${results.length} tracks`, "success");
    } else {
      // Keep the changes so the user can fix and retry.
      const ok = results.length - failed.length;
      toast(ok ? `Saved ${ok}, ${failed.length} failed` : "Couldn't save", "error");
    }
    renderTracks();
    renderEditor();
    refreshActivity();
  } catch (err) {
    toast(err.message, "error");
    updateSaveButton();
  }
}

// ---- Album art ----------------------------------------------------------------------------------------

const ART_TYPES = ["image/jpeg", "image/png"];
const ART_MAX_BYTES = 20 * 1024 * 1024;
const artUrl = (t) => `/api/art?path=${encodeURIComponent(t.path)}&v=${t.mtime || 0}`;

function artEl(tracks) {
  const single = tracks.length === 1;
  const t = tracks[0];
  const fileInput = h("input", {
    type: "file", accept: ART_TYPES.join(","), hidden: true, "aria-hidden": "true", tabindex: "-1",
    onchange: (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) uploadArt(f); },
  });
  const pick = () => fileInput.click();
  const square = h("button", {
    class: "art-square", type: "button",
    "aria-label": single ? "Change album art" : `Set album art for ${tracks.length} tracks`,
    title: "Click or drop an image (JPEG or PNG)",
    onclick: pick,
  });
  const meta = h("div", { class: "art-meta" });
  const actions = h("div", { class: "art-actions" });

  const placeholder = (label) => {
    square.classList.remove("has-art");
    square.replaceChildren(h("span", { class: "art-empty" }, icon("plus"), h("span", {}, label)));
  };

  if (single) {
    const img = h("img", { alt: "Album art", decoding: "async", draggable: "false" });
    img.addEventListener("load", () => {
      img.classList.add("loaded");
      square.classList.add("has-art");
      meta.textContent = `${img.naturalWidth} × ${img.naturalHeight}`;
      actions.replaceChildren(
        h("button", { class: "btn small", type: "button", onclick: pick }, "Replace"),
        h("button", { class: "btn small danger", type: "button", onclick: () => removeArt() }, "Remove"));
    });
    img.addEventListener("error", () => {
      placeholder("Add album art");
      meta.textContent = "";
      actions.replaceChildren();
    });
    img.src = artUrl(t);
    square.replaceChildren(img);
  } else {
    placeholder(`Set art for ${tracks.length} tracks`);
    actions.replaceChildren(
      h("button", { class: "btn small danger", type: "button", onclick: () => removeArt() }, "Remove from all"));
  }

  // Drag and drop an image onto the square (desktop).
  square.addEventListener("dragover", (e) => { e.preventDefault(); square.classList.add("drag"); });
  square.addEventListener("dragleave", () => square.classList.remove("drag"));
  square.addEventListener("drop", (e) => {
    e.preventDefault();
    square.classList.remove("drag");
    const f = e.dataTransfer?.files?.[0];
    if (f) uploadArt(f);
  });

  return h("div", { class: "art" }, square, meta, actions, fileInput);
}

async function changeArt(method, body, contentType) {
  const ed = state.editor;
  if (!ed) return;
  const square = $(".art-square", els.editorForm);
  square?.classList.add("busy");
  const query = ed.paths.map((p) => `path=${encodeURIComponent(p)}`).join("&");
  try {
    const res = await fetch(`/api/art?${query}`, {
      method, body, headers: contentType ? { "Content-Type": contentType } : {},
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error((data && typeof data.detail === "string" && data.detail) || `Request failed (${res.status})`);
    const failed = data.filter((r) => !r.ok);
    for (const r of data) {
      if (!r.ok) continue;
      const i = state.folder.tracks.findIndex((t) => t.path === r.path);
      if (i >= 0) state.folder.tracks[i] = r.track;
    }
    if (failed.length) toast(failed.length === data.length ? failed[0].error : `${failed.length} of ${data.length} failed: ${failed[0].error}`, "error");
    else toast(method === "PUT" ? "Album art saved" : "Album art removed", "success");
    if (state.editor === ed) renderEditor();
  } catch (err) {
    toast(err.message, "error");
    square?.classList.remove("busy");
  }
  refreshActivity();
}

function uploadArt(file) {
  if (!ART_TYPES.includes(file.type)) { toast("Album art must be a JPEG or PNG image", "error"); return; }
  if (file.size > ART_MAX_BYTES) { toast("That image is too large (max 20 MB)", "error"); return; }
  changeArt("PUT", file, file.type);
}

function removeArt() {
  const n = state.editor?.paths.length || 0;
  if (!window.confirm(n > 1 ? `Remove album art from ${n} tracks?` : "Remove the album art from this track?")) return;
  changeArt("DELETE");
}

// ---- Activity log ---------------------------------------------------------------------------------------

const activity = { entries: [], lastId: 0, timer: null, open: null };

function activityOpenPref() {
  try {
    const v = localStorage.getItem("coda-activity-open");
    if (v !== null) return v === "1";
  } catch { /* ignore */ }
  return !window.matchMedia("(max-width: 760px)").matches; // open on desktop, closed on phones
}

async function refreshActivity() {
  try {
    const sinceId = activity.lastId;
    let fresh = await api("GET", `/api/activity?limit=50&after_id=${sinceId}`);
    fresh = fresh.filter((e) => e.id > activity.lastId); // another refresh may have got these already
    if (!fresh.length && activity.entries.length) return;
    const isFirstLoad = activity.lastId === 0 && !activity.entries.length;
    activity.entries = [...fresh, ...activity.entries].slice(0, 50);
    if (fresh.length) activity.lastId = Math.max(activity.lastId, fresh[0].id);
    renderActivity(isFirstLoad ? new Set() : new Set(fresh.map((e) => e.id)));
  } catch { /* offline for a moment: try again on the next tick */ }
}

function fmtTime(iso) {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function renderActivity(newIds = new Set()) {
  if (activity.open === null) activity.open = activityOpenPref();
  const list = $("#activity-list");
  const toggle = $("#activity-toggle");
  toggle.setAttribute("aria-expanded", String(activity.open));
  list.hidden = !activity.open;
  $("#activity").classList.toggle("open", activity.open);

  const latest = activity.entries[0];
  $("#activity-dot").className = `activity-dot ${latest ? (latest.ok ? "ok" : "err") : ""}`;
  $("#activity-latest").textContent = activity.open ? "Activity" : latest ? latest.message : "Activity";
  $("#activity-latest-time").textContent = !activity.open && latest ? fmtTime(latest.time) : "";

  const editing = new Set(state.editor?.paths || []);
  if (!activity.entries.length) {
    list.replaceChildren(h("li", { class: "act-empty" }, "Changes you make will show up here."));
    return;
  }
  list.replaceChildren(...activity.entries.map((e) => {
    const related = e.files.some((f) => editing.has(f));
    return h("li", { class: `act ${e.ok ? "ok" : "err"}${related ? " related" : ""}${newIds.has(e.id) ? " new" : ""}` },
      h("span", { class: "act-icon", "aria-label": e.ok ? "Succeeded" : "Failed" }, e.ok ? "✓" : "!"),
      h("div", { class: "act-main" },
        h("div", { class: "act-msg" }, e.message),
        e.changes.slice(0, 6).map((c) => h("div", { class: "act-change" },
          h("span", { class: "act-key" }, c.key),
          c.old && c.old !== c.new ? [h("span", { class: "act-old" }, c.old), " → "] : null,
          c.new ? h("span", { class: "act-new" }, c.new) : h("span", { class: "act-removed" }, "removed"))),
        e.changes.length > 6 ? h("div", { class: "act-change" }, `+${e.changes.length - 6} more`) : null,
        e.errors.slice(0, 3).map((x) => h("div", { class: "act-err" }, `${x.path.split("/").pop()}: ${x.error}`))),
      h("time", { datetime: e.time }, fmtTime(e.time)));
  }));
}

function startActivityPolling() {
  clearInterval(activity.timer);
  // Picks up changes made from other devices too. Paused while the tab is hidden.
  activity.timer = setInterval(() => {
    if (document.visibilityState === "visible" && state.editor) refreshActivity();
  }, 4000);
}

// ---- Loadouts: apply -----------------------------------------------------------------------------------

async function refreshLoadouts() {
  state.loadouts = await api("GET", "/api/loadouts");
}

let previewTimer = null;
let previewToken = 0;

function applyOptions() {
  const d = els.applyDialog;
  const target = $('input[name="target"]:checked', d)?.value || "folder";
  const body = {
    name: $("#apply-loadout").value,
    mode: $('input[name="mode"]:checked', d).value,
  };
  if (target === "selection") body.paths = [...state.selected];
  else { body.folder = state.path; body.recursive = $("#apply-recursive").checked; }
  return { body, target };
}

async function openApply(target) {
  if (!confirmDiscard()) return;
  try { await refreshLoadouts(); } catch (err) { toast(err.message, "error"); return; }
  if (!state.loadouts.length) {
    toast("You don't have any loadouts yet. Create one first.");
    openManage();
    return;
  }
  const d = els.applyDialog;
  const select = $("#apply-loadout");
  const previous = select.value;
  select.replaceChildren(...state.loadouts.map((lo) => h("option", { value: lo.name }, lo.name)));
  if (state.loadouts.some((lo) => lo.name === previous)) select.value = previous;

  const n = state.selected.size;
  const selRadio = $('input[name="target"][value="selection"]', d);
  selRadio.disabled = n === 0;
  $("#apply-target-sel").textContent = n ? `${plural(n, "selected track")}` : "Selected tracks";
  $(`input[name="target"][value="${target === "selection" && n ? "selection" : "folder"}"]`, d).checked = true;
  $("#apply-recursive").checked = false;
  syncApplyUi();
  openDialog(d);
  runPreview();
}

function syncApplyUi() {
  const { target } = applyOptions();
  $("#apply-recursive-wrap").hidden = target !== "folder" || !(state.folder?.folders.length);
  const lo = state.loadouts.find((l) => l.name === $("#apply-loadout").value);
  $("#apply-desc").textContent = lo?.description || "";
}

function runPreview() {
  clearTimeout(previewTimer);
  const go = $("#apply-go");
  go.disabled = true;
  $("#apply-preview").replaceChildren(h("p", { class: "loading" }, "Checking what will change…"));
  previewTimer = setTimeout(async () => {
    const token = ++previewToken;
    const { body } = applyOptions();
    try {
      const results = await api("POST", "/api/loadouts/apply", { ...body, dry_run: true });
      if (token !== previewToken) return;
      renderPreview(results);
    } catch (err) {
      if (token !== previewToken) return;
      $("#apply-preview").replaceChildren(h("div", { class: "error-box" }, err.message));
    }
  }, 150);
}

function renderPreview(results) {
  const changing = results.filter((r) => !r.error && Object.keys(r.applied).length);
  const errors = results.filter((r) => r.error);
  const unchanged = results.length - changing.length - errors.length;
  const tagCount = changing.reduce((n, r) => n + Object.keys(r.applied).length, 0);

  const go = $("#apply-go");
  go.disabled = !changing.length;
  go.textContent = changing.length ? `Apply to ${plural(changing.length, "file")}` : "Apply";

  const summary = [];
  if (!results.length) summary.push("There are no audio files to apply this to.");
  else if (changing.length) summary.push(`${plural(tagCount, "tag")} will be set across ${plural(changing.length, "file")}.`);
  else summary.push("Nothing to change — these files already match.");
  if (unchanged && changing.length) summary.push(`${plural(unchanged, "file")} already up to date.`);
  if (errors.length) summary.push(`${plural(errors.length, "file")} can't be read.`);

  const shown = [...errors, ...changing].slice(0, 200);
  const items = shown.map((r) => {
    const notes = [];
    if (r.kept_existing.length) notes.push(`Kept existing: ${r.kept_existing.join(", ")}`);
    if (r.unsupported.length) notes.push(`Not supported by this format: ${r.unsupported.join(", ")}`);
    return h("div", { class: `preview-item${r.error ? " error" : ""}` },
      h("div", { class: "name" }, relativeToFolder(r.path)),
      r.error ? h("div", { class: "note" }, r.error)
        : h("div", { class: "changes" }, Object.entries(r.applied).flatMap(([k, v], i) =>
          [i ? ", " : "", h("b", {}, k), ` → ${v.join("; ")}`])),
      notes.map((n) => h("div", { class: "note" }, n)));
  });
  setKids($("#apply-preview"),
    h("p", { class: "preview-summary" }, summary.join(" ")),
    items.length ? h("div", { class: "preview-list" }, items) : null,
    shown.length < changing.length + errors.length ? h("p", { class: "hint" }, `…and ${changing.length + errors.length - shown.length} more`) : null,
  );
}

async function doApply() {
  const go = $("#apply-go");
  go.disabled = true;
  go.textContent = "Applying…";
  const { body } = applyOptions();
  try {
    const results = await api("POST", "/api/loadouts/apply", { ...body, dry_run: false });
    const failed = results.filter((r) => r.error);
    const changed = results.filter((r) => !r.error && Object.keys(r.applied).length);
    closeDialog(els.applyDialog);
    if (failed.length) toast(`Updated ${plural(changed.length, "file")}; ${failed.length} failed: ${failed[0].error}`, "error");
    else toast(`Updated ${plural(changed.length, "file")}`, "success");
    refreshActivity();
    await loadFolder(state.path, { keepScroll: true });
  } catch (err) {
    toast(err.message, "error");
    runPreview();
  }
}

// ---- Loadouts: manage -----------------------------------------------------------------------------------

async function openManage() {
  try { await refreshLoadouts(); } catch (err) { toast(err.message, "error"); return; }
  renderManageList();
  if (!els.manageDialog.open || els.manageDialog.classList.contains("closing")) openDialog(els.manageDialog);
}

function renderManageList() {
  $("#manage-title").textContent = "Loadouts";
  const body = $("#manage-body");
  if (!state.loadouts.length) {
    body.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "No loadouts yet"), "A loadout is a saved set of tags you can apply to many tracks at once."));
  } else {
    setKids(body,
      h("p", { class: "hint" }, "Saved sets of tags you can apply to tracks or whole folders. Blank values are skipped when applying."),
      h("div", { class: "loadout-list" }, state.loadouts.map((lo) =>
        h("div", { class: "loadout-card" },
          h("div", { class: "info" },
            h("div", { class: "name" }, lo.name),
            lo.description && h("div", { class: "desc" }, lo.description),
            h("div", { class: "tags" }, Object.keys(lo.tags).join(", ") || "No tags")),
          h("button", { class: "btn small", type: "button", onclick: () => renderManageForm(lo) }, "Edit")))));
  }
  setKids($("#manage-foot"),
    h("button", { class: "btn", type: "button", onclick: () => renderManageForm(null) }, icon("plus"), "New loadout"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn primary", type: "button", onclick: () => closeDialog(els.manageDialog) }, "Done"));
}

function renderManageForm(loadout) {
  $("#manage-title").textContent = loadout ? "Edit loadout" : "New loadout";
  const nameInput = h("input", { type: "text", value: loadout?.name || "", placeholder: "e.g. SoundCloud single", "aria-label": "Loadout name" });
  const descInput = h("input", { type: "text", value: loadout?.description || "", placeholder: "What it's for (optional)", "aria-label": "Description" });
  const rowsEl = h("div", { class: "tag-rows" });
  let lastValueInput = null;

  const addRow = (key = "", value = "") => {
    const k = h("input", { type: "text", value: key, placeholder: "Tag", list: "tag-keys", "aria-label": "Tag name", autocapitalize: "off", spellcheck: "false" });
    const v = h("input", { type: "text", value, placeholder: "Value (blank = fill in later)", "aria-label": "Tag value" });
    v.addEventListener("focus", () => { lastValueInput = v; });
    const row = h("div", { class: "add-tag" }, k, v,
      h("button", { class: "icon-btn", type: "button", "aria-label": "Remove tag", onclick: () => row.remove() }, icon("close")));
    rowsEl.append(row);
    return k;
  };

  const entries = loadout ? Object.entries(loadout.tags) : [["title", ["{filename_title}"]], ["artist", [""]], ["album", [""]], ["genre", [""]]];
  for (const [k, v] of entries) addRow(k, v.join("; "));

  const chips = state.placeholders.map((p) => h("button", {
    class: "chip", type: "button", title: "Insert into the last value you edited",
    onclick: () => {
      const target = lastValueInput && lastValueInput.isConnected ? lastValueInput : null;
      if (!target) { toast("Click into a value first, then pick a placeholder"); return; }
      const pos = target.selectionStart ?? target.value.length;
      target.value = target.value.slice(0, pos) + `{${p}}` + target.value.slice(target.selectionEnd ?? pos);
      target.focus();
    },
  }, `{${p}}`));

  const errorBox = h("div", { class: "error-box", hidden: true });

  setKids($("#manage-body"),
    errorBox,
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Name"), nameInput),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Description"), descInput),
    h("div", { class: "field" },
      h("span", { class: "field-label" }, "Tags"),
      rowsEl,
      h("button", { class: "btn small", type: "button", onclick: () => addRow().focus() }, icon("plus"), "Add tag")),
    h("div", { class: "field" },
      h("span", { class: "field-label" }, "Placeholders"),
      h("p", { class: "hint", style: "margin:0 0 6px" }, "Filled in per file. Separate multiple values with ;"),
      h("div", {}, chips),
      h("p", { class: "hint", style: "margin:4px 0 0" },
        h("code", {}, "{filename_title}"), " “01 - My Song” → “My Song” · ",
        h("code", {}, "{folder}"), " folder name · ",
        h("code", {}, "{track}/{tracktotal}"), " 1/12, 2/12…")),
  );

  const save = async () => {
    const tags = {};
    for (const row of rowsEl.children) {
      const [k, v] = row.querySelectorAll("input");
      const key = k.value.trim().toLowerCase();
      if (!key) continue;
      const raw = v.value.trim();
      tags[key] = state.fieldMap.get(key)?.multi && raw.includes(";")
        ? raw.split(";").map((s) => s.trim()).filter(Boolean)
        : raw;
    }
    try {
      await api("POST", "/api/loadouts", {
        name: nameInput.value, description: descInput.value, tags,
        previous_name: loadout ? loadout.name : null,
      });
      toast(`Saved “${nameInput.value.trim()}”`, "success");
      await refreshLoadouts();
      renderManageList();
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.hidden = false;
      errorBox.scrollIntoView({ block: "nearest" });
    }
  };

  const del = async () => {
    if (!window.confirm(`Delete the loadout “${loadout.name}”? This can't be undone.`)) return;
    try {
      await api("DELETE", `/api/loadouts/${encodeURIComponent(loadout.name)}`);
      toast(`Deleted “${loadout.name}”`, "success");
      await refreshLoadouts();
      renderManageList();
    } catch (err) { toast(err.message, "error"); }
  };

  setKids($("#manage-foot"),
    loadout && h("button", { class: "btn danger", type: "button", onclick: del }, "Delete"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", onclick: renderManageList }, "Cancel"),
    h("button", { class: "btn primary", type: "button", onclick: save }, "Save"));
  nameInput.focus();
}

// ---- Status banner -------------------------------------------------------------------------------------------

function showStatus(status) {
  if (!status.music_dir_found) {
    els.banner.replaceChildren(
      h("strong", {}, "Music folder not found"),
      "Coda is looking for your music at ", h("code", {}, status.music_dir), ". ",
      "Set ", h("code", {}, "CODA_MUSIC_DIR"), " to your library, or mount it at ", h("code", {}, "/music"), " in Docker.");
    els.banner.hidden = false;
  } else if (!status.music_dir_writable) {
    els.banner.replaceChildren(
      h("strong", {}, "Read-only library"),
      "Coda can read your music but can't save changes. Check the folder's permissions (or remove ", h("code", {}, ":ro"), " from the Docker volume).");
    els.banner.hidden = false;
  }
}

// ---- Wiring -------------------------------------------------------------------------------------------------------

function bindEvents() {
  window.addEventListener("hashchange", onHashChange);
  window.addEventListener("beforeunload", (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });

  $("#theme-btn").addEventListener("click", () => {
    const next = THEMES[(THEMES.indexOf(getTheme()) + 1) % THEMES.length];
    setTheme(next);
    toast(THEME_LABEL[next]);
  });

  els.filter.addEventListener("input", () => {
    state.filter = els.filter.value.trim();
    renderFolders();
    renderTracks();
  });

  $("#editor-close").addEventListener("click", () => closeEditor());
  $("#activity-toggle").addEventListener("click", () => {
    activity.open = !activity.open;
    try { localStorage.setItem("coda-activity-open", activity.open ? "1" : "0"); } catch { /* ignore */ }
    renderActivity();
  });
  els.editorSave.addEventListener("click", () => saveEditor());
  els.editorSaveFolder.addEventListener("click", saveToFolder);
  $("#tagfilter-btn").addEventListener("click", openTagFilter);
  $("#filter-add").addEventListener("click", addTagFilter);
  els.editorForm.addEventListener("submit", (e) => { e.preventDefault(); saveEditor(); });
  // Keep "Copy tags" / "Paste" in sync when tags are copied in another tab.
  window.addEventListener("storage", (e) => {
    if (e.key === "coda-clipboard") { state.clipboard = loadClipboard(); if (state.editor) renderToolbar(); }
  });

  $("#sel-clear").addEventListener("click", () => { state.selected.clear(); updateRowStates(); renderSelectionBar(); });
  $("#sel-edit").addEventListener("click", () => openEditor([...state.selected]));
  $("#sel-loadout").addEventListener("click", () => openApply("selection"));
  $("#manage-btn").addEventListener("click", openManage);

  // Apply dialog
  const d = els.applyDialog;
  d.addEventListener("change", () => { syncApplyUi(); runPreview(); });
  $("#apply-go").addEventListener("click", doApply);

  // All dialogs: close buttons and backdrop clicks.
  for (const dialog of [els.applyDialog, els.manageDialog, els.filterDialog]) {
    dialog.addEventListener("click", (e) => {
      if (e.target.closest("[data-close]") || e.target === dialog) closeDialog(dialog);
    });
    // Escape: animate out instead of vanishing.
    dialog.addEventListener("cancel", (e) => { e.preventDefault(); closeDialog(dialog); });
  }

  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "s" && state.editor) {
      e.preventDefault();
      saveEditor();
    } else if (e.key === "Escape" && state.editor && !document.querySelector("dialog[open]")) {
      closeEditor();
    } else if (e.key === "/" && !e.target.closest("input, textarea, select")) {
      e.preventDefault();
      els.filter.focus();
    }
  });
}

async function boot() {
  applyTheme(getTheme());
  bindEvents();
  try {
    const [status, fields] = await Promise.all([api("GET", "/api/status"), api("GET", "/api/fields")]);
    state.fields = fields.fields;
    state.fieldMap = new Map(fields.fields.map((f) => [f.key, f]));
    state.placeholders = fields.placeholders;
    $("#tag-keys").replaceChildren(...fields.fields.map((f) => h("option", { value: f.key }, f.label)));
    showStatus(status);
  } catch (err) {
    toast(`Can't reach the Coda server: ${err.message}`, "error");
  }
  await loadFolder(pathFromHash());
  refreshActivity();
  startActivityPolling();
}

boot();
