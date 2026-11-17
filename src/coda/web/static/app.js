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

const ICONS = {
  folder: '<svg viewBox="0 0 20 20"><path d="M2.5 5.5a1.5 1.5 0 0 1 1.5-1.5h3.6l1.8 2H16a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 16 16H4a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  close: '<svg viewBox="0 0 20 20"><path d="m5 5 10 10M15 5 5 15"/></svg>',
  clear: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="m7.5 7.5 5 5m0-5-5 5"/></svg>',
  sun: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="3.5"/><path d="M10 2v2m0 12v2M2 10h2m12 0h2M4.3 4.3l1.4 1.4m8.6 8.6 1.4 1.4M4.3 15.7l1.4-1.4m8.6-8.6 1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 20 20"><path d="M16 12.5A6.5 6.5 0 0 1 7.5 4a6.5 6.5 0 1 0 8.5 8.5z"/></svg>',
  auto: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="M10 3a7 7 0 0 1 0 14z" fill="currentColor" stroke="none"/></svg>',
  plus: '<svg viewBox="0 0 20 20"><path d="M10 4v12M4 10h12"/></svg>',
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
  setTimeout(() => el.remove(), kind === "error" ? 7000 : 3500);
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
  applyTheme(theme);
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
  state.folder = data;
  state.path = data.path;
  if (!sameFolder) {
    state.selected.clear();
    state.lastClicked = null;
    state.filter = "";
    els.filter.value = "";
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

function matchesFilter(track) {
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
    els.tracks.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "No matches"), `Nothing here matches “${state.filter}”.`));
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
  els.selBar.hidden = n === 0;
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
  els.editor.hidden = true;
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
  els.editorForm.replaceChildren(...parts);
  updateSaveButton();
}

function fieldEl(field, model) {
  const ed = state.editor;
  const key = field.key;
  const m = model.get(key) || { value: "", mixed: false, present: false, multiValued: false };
  const id = `f-${key}`;
  const change = ed.changes.get(key);
  const isLong = key === "comment";

  const flag = h("span", { class: "flag" });
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

  wrap.append(
    h("label", { class: "field-label", for: id, title: `Tag name: ${key}` }, field.label, flag),
    isLong ? input : h("div", { class: "input-wrap" }, input, clearBtn),
  );
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

function updateSaveButton() {
  const n = state.editor?.changes.size || 0;
  els.editorSave.disabled = n === 0;
  els.editorSave.textContent = n ? `Save ${n > 1 ? `(${n})` : ""}`.trim() : "Save";
}

async function saveEditor() {
  const ed = state.editor;
  if (!ed || !ed.changes.size) return;
  const changes = {};
  for (const [key, c] of ed.changes) {
    const value = c.value.trim();
    if (c.remove || !value) { changes[key] = null; continue; }
    const split = state.fieldMap.get(key)?.multi || ed.model.get(key)?.multiValued;
    changes[key] = split ? value.split(";").map((s) => s.trim()).filter(Boolean) : value;
  }

  els.editorSave.disabled = true;
  els.editorSave.textContent = "Saving…";
  try {
    const results = await api("PATCH", "/api/tracks", { paths: ed.paths, changes });
    const failed = results.filter((r) => !r.ok);
    for (const r of results) {
      if (!r.ok) continue;
      const i = state.folder.tracks.findIndex((t) => t.path === r.path);
      if (i >= 0) state.folder.tracks[i] = r.track;
    }
    if (state.editor !== ed) return; // closed meanwhile
    ed.errors = failed.map((r) => `${baseName(r.path)}: ${r.error}`);
    if (!failed.length) {
      ed.changes.clear();
      toast(results.length === 1 ? "Saved" : `Saved ${results.length} tracks`, "success");
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
  d.showModal();
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
  $("#apply-preview").replaceChildren(
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
    els.applyDialog.close();
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
  if (!els.manageDialog.open) els.manageDialog.showModal();
}

function renderManageList() {
  $("#manage-title").textContent = "Loadouts";
  const body = $("#manage-body");
  if (!state.loadouts.length) {
    body.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "No loadouts yet"), "A loadout is a saved set of tags you can apply to many tracks at once."));
  } else {
    body.replaceChildren(
      h("p", { class: "hint" }, "Saved sets of tags you can apply to tracks or whole folders. Blank values are skipped when applying."),
      h("div", { class: "loadout-list" }, state.loadouts.map((lo) =>
        h("div", { class: "loadout-card" },
          h("div", { class: "info" },
            h("div", { class: "name" }, lo.name),
            lo.description && h("div", { class: "desc" }, lo.description),
            h("div", { class: "tags" }, Object.keys(lo.tags).join(", ") || "No tags")),
          h("button", { class: "btn small", type: "button", onclick: () => renderManageForm(lo) }, "Edit")))));
  }
  $("#manage-foot").replaceChildren(
    h("button", { class: "btn", type: "button", onclick: () => renderManageForm(null) }, icon("plus"), "New loadout"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn primary", type: "button", onclick: () => els.manageDialog.close() }, "Done"));
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

  $("#manage-body").replaceChildren(
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

  $("#manage-foot").replaceChildren(
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
  els.editorSave.addEventListener("click", saveEditor);
  els.editorForm.addEventListener("submit", (e) => { e.preventDefault(); saveEditor(); });

  $("#sel-clear").addEventListener("click", () => { state.selected.clear(); updateRowStates(); renderSelectionBar(); });
  $("#sel-edit").addEventListener("click", () => openEditor([...state.selected]));
  $("#sel-loadout").addEventListener("click", () => openApply("selection"));
  $("#manage-btn").addEventListener("click", openManage);

  // Apply dialog
  const d = els.applyDialog;
  d.addEventListener("change", () => { syncApplyUi(); runPreview(); });
  $("#apply-go").addEventListener("click", doApply);

  // All dialogs: close buttons and backdrop clicks.
  for (const dialog of [els.applyDialog, els.manageDialog]) {
    dialog.addEventListener("click", (e) => {
      if (e.target.closest("[data-close]") || e.target === dialog) dialog.close();
    });
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
