// Codetta UI — plain JavaScript, no framework, no build step.
//
// Talks to the JSON API in codetta/web/app.py. The current folder lives in the
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
  el.classList.remove("nav-forward", "nav-back", "nav-fade", cls);
  void el.offsetWidth; // force reflow so the animation starts again
  el.classList.add(cls);
}

/**
 * Codetta's own confirmation sheet. Resolves true (confirmed) or false.
 * ask({ title, message, details, confirmLabel, cancelLabel, danger })
 */
function ask({ title, message = "", details = null, confirmLabel = "OK", cancelLabel = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    const d = $("#confirm-dialog");
    const ok = $("#confirm-ok");
    const cancel = $("#confirm-cancel");
    $("#confirm-title").textContent = title;
    setKids($("#confirm-body"), message ? h("p", { class: "confirm-msg" }, message) : null, details);
    ok.textContent = confirmLabel;
    ok.className = `btn ${danger ? "danger-fill" : "primary"}`;
    cancel.textContent = cancelLabel;
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeDialog(d);
      resolve(value);
    };
    ok.onclick = () => finish(true);
    cancel.onclick = () => finish(false);
    d.oncancel = (e) => { e.preventDefault(); finish(false); }; // Escape
    d.onclick = (e) => { if (e.target === d) finish(false); }; // backdrop
    openDialog(d);
    setTimeout(() => (danger ? cancel : ok).focus(), 60); // safe default for destructive actions
  });
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
  chevron: '<svg viewBox="0 0 20 20"><path d="m8 5 5 5-5 5"/></svg>',
  rows: '<svg viewBox="0 0 20 20"><path d="M4 5.5h12M4 10h12M4 14.5h12"/></svg>',
  grid: '<svg viewBox="0 0 20 20"><rect x="3.5" y="3.5" width="5" height="5" rx="1"/><rect x="11.5" y="3.5" width="5" height="5" rx="1"/><rect x="3.5" y="11.5" width="5" height="5" rx="1"/><rect x="11.5" y="11.5" width="5" height="5" rx="1"/></svg>',
  note: '<svg viewBox="0 0 20 20"><path d="M8 15.5V5l8-1.5v10"/><circle cx="6" cy="15.5" r="2"/><circle cx="14" cy="13.5" r="2"/></svg>',
  search: '<svg viewBox="0 0 20 20"><circle cx="8.5" cy="8.5" r="5.5"/><path d="m13 13 4 4"/></svg>',
  check: '<svg viewBox="0 0 20 20"><path d="m5 10.5 3.2 3.2L15 7"/></svg>',
  alert: '<svg viewBox="0 0 20 20"><path d="M10 5v6.5M10 15v.01"/></svg>',
  user: '<svg viewBox="0 0 20 20"><circle cx="10" cy="7" r="3.2"/><path d="M3.8 16.5a6.2 6.2 0 0 1 12.4 0"/></svg>',
  undo: '<svg viewBox="0 0 20 20"><path d="M7.5 5 4 8.5 7.5 12"/><path d="M4.5 8.5h7a4.5 4.5 0 0 1 0 9H9"/></svg>',
  spark: '<svg viewBox="0 0 20 20"><path d="M10 3.5 11.4 8.6 16.5 10l-5.1 1.4L10 16.5l-1.4-5.1L3.5 10l5.1-1.4z"/></svg>',
  // A disc (drawn for Codetta): rim, label ring, spindle hole and two shine arcs.
  disc: '<svg class="disc-icon" viewBox="0 0 20 20"><circle cx="10" cy="10" r="7.5"/><circle cx="10" cy="10" r="2.6"/><circle cx="10" cy="10" r=".6" fill="currentColor" stroke="none"/><path d="M5.4 8.05A5 5 0 0 1 7.97 5.43"/><path d="M14.6 11.95a5 5 0 0 1-2.57 2.62"/></svg>',
  play: '<svg viewBox="0 0 20 20"><path d="M7 5.2v9.6a.6.6 0 0 0 .9.5l7.6-4.8a.6.6 0 0 0 0-1L7.9 4.7a.6.6 0 0 0-.9.5z" fill="currentColor" stroke="none"/></svg>',
  pause: '<svg viewBox="0 0 20 20"><rect x="5.5" y="4.5" width="3" height="11" rx="1" fill="currentColor" stroke="none"/><rect x="11.5" y="4.5" width="3" height="11" rx="1" fill="currentColor" stroke="none"/></svg>',
  // MusicBrainz's two-tone mark (drawn here: the page loads nothing from other sites).
  musicbrainz: '<svg class="mb-logo" viewBox="0 0 32 32"><path class="mb-l" d="M15.3 3.2 5.5 8.8v14.4l9.8 5.6z"/><path class="mb-r" d="M16.7 3.2l9.8 5.6v14.4l-9.8 5.6z"/><path class="mb-cut" d="M11.5 11.2c-1.8 0-3.2 1.4-3.2 3.2 0 1.2.7 2.3 1.7 2.8-.2.5-.3 1-.3 1.6 0 2.1 1.7 3.8 3.8 3.8h1.8V11.2z"/><path class="mb-cut" d="M20.5 11.2c1.8 0 3.2 1.4 3.2 3.2 0 1.2-.7 2.3-1.7 2.8.2.5.3 1 .3 1.6 0 2.1-1.7 3.8-3.8 3.8h-1.8V11.2z"/></svg>',
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
  if (res.status === 401 && !url.startsWith("/api/auth/")) {
    showAuth("login", "Your session ended. Sign in again to carry on where you left off.");
    throw new Error("Sign in required");
  }
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
  selectMode: false,      // phones: selection circles only show after tapping "Select"
  clipboard: loadClipboard(), // copied tags: { tags: {key: [values]}, from }
  advanced: (() => { try { return localStorage.getItem("codetta-advanced") === "1"; } catch { return false; } })(),
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
const FORMAT_LABELS = { wavpack: "WV", oggflac: "Ogg FLAC", speex: "SPX", wma: "WMA" };
const fmtLabel = (format) => FORMAT_LABELS[format] || (format || "").toUpperCase();
const runtime = (tracks) => {
  const secs = tracks.reduce((sum, t) => sum + (t.duration || 0), 0);
  return secs >= 60 ? `, ${Math.round(secs / 60)} min` : "";
};
const trackNo = (v) => { const n = (v || "").split("/")[0].trim(); return /^\d$/.test(n) ? `0${n}` : n; };
const plural = (n, word, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;
const baseName = (path) => path.split("/").pop();

function relativeToFolder(path) {
  const prefix = state.path ? state.path + "/" : "";
  return path.startsWith(prefix) ? path.slice(prefix.length) : path;
}

// ---- Toasts --------------------------------------------------------------------------------

function toast(message, kind = "") {
  // While the sign-in screen is up it already explains what's wrong.
  if (kind === "error" && !$("#auth").hidden) return;
  const el = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" },
    kind === "success" ? h("span", { class: "toast-icon", "aria-hidden": "true" }, icon("check")) : null, message);
  els.toasts.append(el);
  setTimeout(() => playOut(el, "leaving", () => el.remove()), kind === "error" ? 7000 : 3500);
}

// ---- Theme -----------------------------------------------------------------------------------

const THEMES = ["system", "light", "dark"];
const THEME_LABEL = { system: "Theme: match system", light: "Theme: light", dark: "Theme: dark" };
const THEME_ICON = { system: "auto", light: "sun", dark: "moon" };

function getTheme() {
  try { return localStorage.getItem("codetta-theme") || "system"; } catch { return "system"; }
}

function setTheme(theme) {
  try { localStorage.setItem("codetta-theme", theme); } catch { /* private mode */ }
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
    const color = theme === "system" ? (dark ? "#131418" : "#f7f8f8") : theme === "dark" ? "#131418" : "#f7f8f8";
    meta.content = color;
  }
  requestAnimationFrame(refitSpot); // the spot colour is fitted to the background's contrast
}

// ---- Spot colour: each album borrows one colour from its cover -------------------------------

const spotCache = new Map(); // cover hash -> [r, g, b] or null (a grey or unreadable cover)
let spotRgb = null; // the current cover's raw colour

const luminance = ([r, g, b]) => {
  const c = [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };

function rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h / 6, s, l];
}
function hslToRgb([h, s, l]) {
  if (!s) return [l, l, l].map((v) => Math.round(v * 255));
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
  return [f(h + 1 / 3), f(h), f(h - 1 / 3)].map((v) => Math.round(v * 255));
}

/** The cover's most characteristic colour: the strongest saturated hue, or null for grey covers. */
function coverColour(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => {
      try {
        const n = 32, c = document.createElement("canvas");
        c.width = c.height = n;
        const ctx = c.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0, n, n);
        const px = ctx.getImageData(0, 0, n, n).data;
        const bins = Array.from({ length: 24 }, () => ({ w: 0, r: 0, g: 0, b: 0 }));
        for (let i = 0; i < px.length; i += 4) {
          const rgb = [px[i], px[i + 1], px[i + 2]];
          const [h, s, l] = rgbToHsl(rgb);
          if (l < 0.12 || l > 0.92 || s < 0.2) continue;
          const bin = bins[Math.floor(h * 24) % 24], w = s * s;
          bin.w += w; bin.r += rgb[0] * w; bin.g += rgb[1] * w; bin.b += rgb[2] * w;
        }
        const best = bins.reduce((a, b) => (b.w > a.w ? b : a));
        resolve(best.w < 6 ? null : [best.r, best.g, best.b].map((v) => Math.round(v / best.w)));
      } catch { resolve(null); }
    };
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

/** Fit a colour to the current background: saturated enough to read as colour,
 *  dark (or light) enough for 4.5:1 text contrast. */
function fitSpot(rgb) {
  const bg = (getComputedStyle(document.body).backgroundColor.match(/\d+/g) || [247, 248, 248]).slice(0, 3).map(Number);
  const dark = luminance(bg) < 0.2;
  let [h, s, l] = rgbToHsl(rgb);
  s = Math.min(0.85, Math.max(0.5, s));
  l = dark ? Math.max(l, 0.55) : Math.min(l, 0.45);
  for (let i = 0; i < 40 && contrast(hslToRgb([h, s, l]), bg) < 4.6; i++) l += dark ? 0.02 : -0.02;
  const [r, g, b] = hslToRgb([h, s, Math.min(0.95, Math.max(0.05, l))]);
  return `rgb(${r} ${g} ${b})`;
}

function refitSpot() {
  const root = document.documentElement;
  if (spotRgb) root.style.setProperty("--spot", fitSpot(spotRgb));
  else root.style.removeProperty("--spot"); // back to the house colour
}

/** Take the spot colour from the open folder's cover (or go back to the house colour). */
async function updateSpot() {
  const f = state.folder;
  const cover = !f?.search && f?.tracks.find((t) => t.art);
  if (!cover) { spotRgb = null; refitSpot(); return; }
  const key = cover.art.hash;
  if (!spotCache.has(key)) {
    const rgb = await coverColour(artUrlFor(cover));
    if (spotCache.size > 300) spotCache.clear();
    spotCache.set(key, rgb);
  }
  if (state.folder !== f) return; // moved on while the cover loaded
  spotRgb = spotCache.get(key);
  refitSpot();
}

// ---- Routing ------------------------------------------------------------------------------------

// Library-wide search is shown like a folder whose "path" is SEARCH + the query.
// Real paths can never contain a NUL character (the server refuses them), so the
// two can't collide. Its URL is "#?q=genre%3A%20rap".
const SEARCH = "\0";
const isSearchKey = (key) => typeof key === "string" && key.startsWith(SEARCH);
const isSearch = () => isSearchKey(state.path);
const searchQuery = (key = state.path) => (isSearchKey(key) ? key.slice(1) : "");

function pathFromHash(hash = location.hash) {
  if (hash.startsWith("#?")) {
    const q = (new URLSearchParams(hash.slice(2)).get("q") || "").trim();
    return q ? SEARCH + q : "";
  }
  const raw = hash.replace(/^#\/?/, "");
  try {
    return raw.split("/").filter(Boolean).map(decodeURIComponent).join("/");
  } catch {
    return "";
  }
}

function hashFor(path) {
  if (isSearchKey(path)) return "#?q=" + encodeURIComponent(searchQuery(path));
  return "#/" + path.split("/").filter(Boolean).map(encodeURIComponent).join("/");
}

// Folder links are handled in-page with the History API (pushState) rather
// than by letting the browser follow "#/..." links. Same URLs, so bookmarks
// and back/forward still work, but browsers such as Brave on iOS no longer
// treat every folder tap as a page load (loading bar, reload icon).
let navTarget = null; // the folder we're currently heading to

async function navigate(path) {
  if (path === (navTarget ?? state.path) && state.folder) return;
  if (!(await confirmDiscard())) return;
  navTarget = path;
  history.pushState({ path }, "", hashFor(path));
  loadFolder(path);
}

/** Back/forward buttons, or a hand-edited URL. */
async function onHistoryChange() {
  const path = pathFromHash();
  if (path === (navTarget ?? state.path) && state.folder) return;
  if (!(await confirmDiscard())) {
    history.pushState({ path: state.path }, "", hashFor(state.path)); // stay put
    return;
  }
  navTarget = path;
  loadFolder(path);
}

function folderLinkPath(event) {
  const a = event.target.closest?.('a[href^="#/"], a[href^="#?"]');
  if (!a || !a.closest("#app")) return null;
  return pathFromHash(a.getAttribute("href"));
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

const inflight = new Map(); // folder path -> pending /api/browse request

function fetchFolder(path) {
  if (!inflight.has(path)) {
    const req = (isSearchKey(path)
      ? api("GET", `/api/search?q=${encodeURIComponent(searchQuery(path))}`).then((data) => ({
        ...data, path, name: "Search",
        breadcrumbs: [{ name: "Library", path: "" }, { name: `Search: ${searchQuery(path)}`, path }],
      }))
      : api("GET", `/api/browse?path=${encodeURIComponent(path)}`))
      .finally(() => setTimeout(() => inflight.delete(path), 1500));
    inflight.set(path, req);
  }
  return inflight.get(path);
}

/** Start loading a folder as soon as a finger touches its link (or the mouse hovers it). */
function prefetchFolder(path) {
  if (path == null || folderCache.has(path) || inflight.has(path)) return;
  fetchFolder(path).then(rememberFolder, () => { /* ignore; the real visit will report errors */ });
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
    // Keep the current folder on screen (dimmed) until the new one arrives,
    // instead of blanking the page. Only dim if the server is slow.
    if (state.folder) {
      loadingTimer = setTimeout(() => els.browser.classList.add("is-loading"), 150);
    } else {
      els.folderHead.replaceChildren(h("p", { class: "loading" }, "Loading…"));
    }
  }

  try {
    const data = await fetchFolder(path);
    clearTimeout(loadingTimer);
    els.browser.classList.remove("is-loading");
    if (token !== state.loadToken) return; // a newer navigation won
    const unchanged = cached && JSON.stringify(cached) === JSON.stringify(data);
    rememberFolder(unchanged ? cached : data);
    if (unchanged) return;
    const scroll = cached || keepScroll ? els.browser.scrollTop : scrollMemory.get(data.path) ?? 0;
    showFolder(data, scroll);
  } catch (err) {
    clearTimeout(loadingTimer);
    els.browser.classList.remove("is-loading");
    if (token !== state.loadToken) return;
    navTarget = null;
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
  if (navTarget === data.path) navTarget = null;
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
    if (document.activeElement !== els.filter || !isSearchKey(data.path)) els.filter.value = searchQuery(data.path);
    state.tagFilters = [];
    state.selectMode = false;
    closeEditor(true);
  } else {
    // Keep only selections that still exist.
    const paths = new Set(data.tracks.map((t) => t.path));
    for (const p of state.selected) if (!paths.has(p)) state.selected.delete(p);
    if (state.editor) renderEditor(); // show the fresh tags
  }
  document.title = isSearchKey(data.path) ? `${searchQuery(data.path)} — Search — Codetta`
    : data.path ? `${data.name} — Codetta` : "Codetta";
  els.filter.placeholder = isSearchKey(data.path) ? "Search library" : isPhone() ? "Filter" : "Filter this folder";
  renderBrowser();
  els.browser.scrollTop = scrollTop;
  updateSpot();
}

// Lookups by path / cover, built once per folder instead of scanning every time
// (matters for folders with thousands of tracks).
const index = { folder: null, count: -1, byPath: new Map(), firstWithArt: new Map() };

function folderIndex() {
  const f = state.folder;
  if (index.folder !== f || index.count !== (f?.tracks.length ?? -1)) {
    index.folder = f;
    index.count = f?.tracks.length ?? -1;
    index.byPath = new Map();
    for (const [i, t] of (f?.tracks || []).entries()) index.byPath.set(t.path, i);
  }
  return index;
}

function trackByPath(path) {
  const i = folderIndex().byPath.get(path);
  return i === undefined ? undefined : state.folder.tracks[i];
}

/** Replace a track's data after a save (keeps the index valid). */
function replaceTrack(track) {
  const i = folderIndex().byPath.get(track.path);
  if (i !== undefined) state.folder.tracks[i] = track;
}

/** Case- and accent-insensitive form for searching: "Beyoncé" -> "beyonce". */
function fold(text) {
  return String(text).normalize("NFKD").replace(/\p{M}+/gu, "").toLowerCase();
}

function matchesTagFilters(track) {
  return state.tagFilters.every(({ key, value }) => {
    const values = listParts(key, track.tags[key] || []).map(fold);
    return value === "" ? values.length === 0 : values.includes(fold(value));
  });
}

function matchesFilter(track) {
  if (!matchesTagFilters(track)) return false;
  if (!state.filter) return true;
  const q = fold(state.filter);
  // Folded once per track version, not on every keystroke.
  track._search ??= fold([track.name, first(track, "title"), ...(track.tags.artist || []),
    first(track, "album"), first(track, "albumartist")].join("\n"));
  return track._search.includes(q);
}

/** Multi-disc album: every track has a disc number and there are at least two. */
const discCache = new WeakMap();
function discInfo(f = state.folder) {
  if (!f || f.search) return null;
  if (discCache.has(f)) return discCache.get(f);
  const readable = f.tracks.filter((t) => !t.error);
  const discOf = (t) => parseInt(first(t, "discnumber"), 10);
  const info = readable.length && readable.every((t) => Number.isInteger(discOf(t))) && new Set(readable.map(discOf)).size > 1
    ? { discOf } : null;
  discCache.set(f, info);
  return info;
}

function visibleTracks() {
  const tracks = (state.folder?.tracks || []).filter(matchesFilter);
  const discs = discInfo();
  if (!discs) return tracks;
  // Group by disc, then track number; files without numbers keep their place within the disc.
  const order = new Map(tracks.map((t, i) => [t, i]));
  const num = (t) => parseInt(first(t, "tracknumber"), 10);
  const key = (t) => [t.error ? Infinity : discs.discOf(t), Number.isInteger(num(t)) ? num(t) : Infinity, order.get(t)];
  return [...tracks].sort((a, b) => {
    const [x, y] = [key(a), key(b)];
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
  });
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

function renderSearchHead(f) {
  const s = f.search;
  const parts = s.clauses.map((c) => h("span", { class: "query-chip" },
    h("b", {}, c.label), ": ", c.values.join(" or ")));
  if (s.words.length) parts.push(h("span", { class: "query-chip" }, `“${s.words.join(" ")}”`));
  const notes = [];
  if (s.total > f.tracks.length) notes.push(`Showing the first ${f.tracks.length.toLocaleString()}. Add more to the search to narrow it down.`);
  if (s.indexing) notes.push(`Still reading your library (${s.indexed.toLocaleString()} files so far), so some tracks may be missing.`);
  els.folderHead.replaceChildren(
    h("div", {},
      h("h1", {}, "Search"),
      h("p", {}, s.total ? `${plural(s.total, "track")} across your library` : "No tracks match"),
      parts.length ? h("div", { class: "query-chips" }, parts) : null,
      ...notes.map((n) => h("p", { class: "search-note" }, n))),
    h("div", { class: "folder-actions" },
      f.tracks.length && state.selectMode ? h("button", {
        class: "btn phone-only", type: "button", onclick: toggleSelectAllVisible,
      }, allVisibleSelected() ? "Deselect all" : "Select all") : null,
      f.tracks.length ? h("button", {
        class: `btn phone-only${state.selectMode ? " primary" : ""}`, type: "button",
        "aria-pressed": String(state.selectMode), onclick: () => setSelectMode(!state.selectMode),
      }, state.selectMode ? "Done" : "Select") : null),
  );
  els.tracks.classList.toggle("selecting", state.selectMode);
}

/** "Find in MusicBrainz" ("Find" on phones), shown when the MusicBrainz connection is on. */
function mbFindButton(where) {
  return h("button", {
    class: `mb-find ${where}`, type: "button", onclick: openMusicBrainz,
    "aria-label": "Find in MusicBrainz", title: "Find this album on MusicBrainz and review its tags before writing them",
  }, h("span", { class: "mb-find-inner" }, icon("musicbrainz"),
    h("span", { class: "mb-find-long" }, "Find in MusicBrainz"), h("span", { class: "mb-find-short" }, "Find")));
}

function renderFolderHead() {
  const f = state.folder;
  if (!f) return;
  if (f.search) { renderSearchHead(f); return; }
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
  const canMatch = f.tracks.length && state.status?.musicbrainz;
  const heading = coverTrack
    // A folder of tracks with a cover reads as the album's booklet spread.
    ? h("div", { class: "album-head" },
      h("img", { class: "album-cover", src: artUrlFor(coverTrack), alt: "", decoding: "async", width: "168", height: "168" }),
      h("div", {},
        h("h1", { dir: "auto" }, common("album") || f.name),
        h("p", { class: "album-meta" },
          [common("albumartist") || common("artist"), common("date").slice(0, 4)].filter(Boolean).flatMap((v, i) => [i ? " · " : "", h("b", { dir: "auto" }, v)]),
          counts.length ? [common("albumartist") || common("artist") || common("date") ? " · " : "",
            h("span", { class: "nowrap" }, `${counts.join(" · ")}${runtime(f.tracks)}`)] : "", skippedNote),
        genres || canMatch ? h("div", { class: "album-chips" },
          genres ? h("span", { class: "spot-chip", dir: "auto" }, genres) : null,
          canMatch ? mbFindButton("beside-genre") : null) : null))
    : h("div", {},
      h("h1", {}, f.path ? f.name : "Library"),
      h("p", {}, counts.join(" · ") || (f.skipped ? "" : "Empty folder"), skippedNote));
  els.folderHead.replaceChildren(
    heading,
    h("div", { class: "folder-actions" },
      f.folders.length ? h("div", { class: "view-toggle", role: "group", "aria-label": "Folder view" },
        ["list", "grid"].map((v) => h("button", {
          type: "button", class: "icon-btn", title: v === "list" ? "List" : "Grid",
          "aria-label": v === "list" ? "Show folders as a list" : "Show folders as a grid",
          "aria-pressed": String(folderView() === v),
          onclick: () => setFolderView(v),
        }, icon(v === "list" ? "rows" : "grid")))) : null,
      // Phones (and folders without a cover): first in the action row, on the left.
      canMatch ? mbFindButton(coverTrack ? "in-actions phone-only" : "in-actions") : null,
      f.tracks.length || f.folders.length ? h("button", {
        class: "btn", type: "button", onclick: () => openApply("folder"),
      }, "Apply loadout…") : null,
      (f.tracks.length || f.folders.length) && !f.search ? h("button", {
        class: "btn", type: "button", onclick: openOrganize,
        title: "Rename and move files into folders from their tags (you see everything first)",
      }, "Organize…") : null,
      // Phones: selecting is a mode, like the Photos app.
      f.tracks.length && state.selectMode ? h("button", {
        class: "btn phone-only", type: "button", onclick: toggleSelectAllVisible,
      }, allVisibleSelected() ? "Deselect all" : "Select all") : null,
      f.tracks.length ? h("button", {
        class: `btn phone-only${state.selectMode ? " primary" : ""}`, type: "button",
        "aria-pressed": String(state.selectMode), onclick: () => setSelectMode(!state.selectMode),
      }, state.selectMode ? "Done" : "Select") : null),
  );
  els.tracks.classList.toggle("selecting", state.selectMode);
}

const isPhone = () => window.matchMedia("(max-width: 760px)").matches;

function setSelectMode(on) {
  state.selectMode = on;
  if (!on) {
    state.selected.clear();
    state.lastClicked = null;
    updateRowStates();
    renderSelectionBar();
  }
  renderFolderHead();
}

function allVisibleSelected() {
  const vis = visibleTracks();
  return vis.length > 0 && vis.every((t) => state.selected.has(t.path));
}

function toggleSelectAllVisible() {
  selectAll(!allVisibleSelected());
}

// Folders show as a list by default (clean with hundreds of artists), or as a grid.
function folderView() {
  try { return localStorage.getItem("codetta-folder-view") === "grid" ? "grid" : "list"; } catch { return "list"; }
}

function setFolderView(view) {
  try { localStorage.setItem("codetta-folder-view", view); } catch { /* ignore */ }
  renderFolderHead();
  renderFolders();
}

function folderSummary(f) {
  if (f.folders == null) return "";
  const parts = [];
  if (f.folders) parts.push(plural(f.folders, "folder"));
  if (f.tracks) parts.push(plural(f.tracks, "track"));
  return parts.join(" · ") || "Empty";
}

function renderFolders() {
  const q = fold(state.filter);
  const folders = (state.folder?.folders || []).filter((f) => !q || fold(f.name).includes(q));
  const list = folderView() === "list";
  els.folders.classList.toggle("as-list", list);
  els.folders.replaceChildren(...folders.map((f) =>
    h("a", { class: "folder", href: hashFor(f.path), title: f.name },
      icon("folder"),
      h("span", { class: "folder-name" }, f.name),
      list ? h("span", { class: "folder-meta" }, folderSummary(f)) : null,
      list ? icon("chevron") : null)));
}

function renderTracks() {
  state.rows.clear();
  const f = state.folder;
  if (!f) return;
  const tracks = visibleTracks();

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

  const out = [];
  let lastDisc = null;
  for (const t of tracks) {
    const disc = discs && !t.error ? discs.discOf(t) : null;
    if (discs && disc !== lastDisc && disc !== null) {
      const subtitle = first(t, "discsubtitle");
      out.push(h("div", { class: "disc-head", role: "row", dataset: { disc: String(disc) } },
        h("span", { class: "disc-spin" }, icon("disc")),
        h("span", { class: "disc-name" }, `Disc ${disc}`),
        subtitle ? h("span", { class: "disc-sub", dir: "auto" }, subtitle) : null));
      lastDisc = disc;
    }
    out.push(trackRow(t, { oneAlbum, albumArtist, disc }));
  }
  els.tracks.replaceChildren(head, ...out);
  updateRowStates();
  syncPlayer();
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
    h("div", { class: "col-num" }, disc != null
      // Multi-disc: pointing at a row shows "2/01" (disc/track).
      ? [h("span", { class: "num-track" }, trackNo(first(t, "tracknumber"))),
        h("span", { class: "num-disc" }, `${disc}/${trackNo(first(t, "tracknumber"))}`)]
      : trackNo(first(t, "tracknumber"))),
    h("div", { class: "col-art" }, t.art
      ? h("img", { src: artUrlFor(t), alt: "", loading: "lazy", decoding: "async", width: "40", height: "40" })
      : h("span", { class: "art-none", title: "No album art" }, icon("note"))),
    h("div", { class: "col-title" },
      h("span", { class: "main" }, title || h("span", { class: "untitled" }, t.name)),
      h("span", { class: "sub" }, t.error ? t.error
        : oneAlbum ? (artist && artist !== albumArtist ? artist : "")
        : [artist, album].filter(Boolean).join(" · ") || (title ? t.name : `${fmtLabel(t.format)} · No tags yet`))),
    h("div", { class: "col-artist" }, t.error ? t.error : artist),
    h("div", { class: "col-album" }, album),
    h("div", { class: "col-fmt" }, t.format ? h("span", { class: "badge" }, fmtLabel(t.format)) : ""),
    h("div", { class: "col-dur" }, fmtDuration(t.duration)),
    h("div", { class: "col-play" }, !t.error && canPlay(t.format) ? h("button", {
      class: "play-btn", type: "button", "aria-label": `Play ${title || t.name}`,
      onclick: (e) => { e.stopPropagation(); togglePlay(t); },
    }, icon("play"), h("span", { class: "play-label" }, "Play")) : null),
  );
  state.rows.set(t.path, { row, checkbox, track: t });
  return row;
}

// ---- Player: a quick listen, straight from the file -------------------------------------------
//
// One shared <audio>, streaming /api/stream (the server sends the file as-is
// and supports seeking). Formats the browser can't decode get no button.

const STREAM_TYPES = {
  flac: "audio/flac", mp3: "audio/mpeg", mp2: "audio/mpeg", m4a: "audio/mp4", wav: "audio/wav", aiff: "audio/aiff",
  ogg: 'audio/ogg; codecs="vorbis"', opus: 'audio/ogg; codecs="opus"', oggflac: 'audio/ogg; codecs="flac"',
};
const playable = new Map();
function canPlay(format) {
  if (!playable.has(format)) {
    const type = STREAM_TYPES[format];
    playable.set(format, !!type && document.createElement("audio").canPlayType(type) !== "");
  }
  return playable.get(format);
}

const player = { audio: null, path: null, folder: null, track: null, seeking: false };

function playerAudio() {
  if (player.audio) return player.audio;
  const a = new Audio();
  a.preload = "none";
  for (const ev of ["play", "pause", "ended", "emptied"]) a.addEventListener(ev, syncPlayer);
  a.addEventListener("timeupdate", npProgress);
  a.addEventListener("loadedmetadata", npProgress);
  a.addEventListener("ended", stopPlayer);
  a.addEventListener("error", () => {
    if (!player.path) return;
    toast("This browser can't play that file.", "error");
    stopPlayer();
  });
  player.audio = a;
  return a;
}

async function togglePlay(t) {
  const a = playerAudio();
  if (player.path === t.path) {
    if (a.paused) a.play().catch(() => {}); else a.pause();
    return;
  }
  player.path = t.path;
  player.folder = state.path;
  player.track = t;
  a.src = `/api/stream?path=${encodeURIComponent(t.path)}`;
  if ("mediaSession" in navigator) { // lock screen / headphone controls
    navigator.mediaSession.metadata = new MediaMetadata({
      title: first(t, "title") || t.name, artist: (t.tags.artist || []).join(", "), album: first(t, "album"),
      artwork: t.art ? [{ src: artUrlFor(t), sizes: "512x512" }] : [],
    });
    navigator.mediaSession.setActionHandler("play", () => a.play());
    navigator.mediaSession.setActionHandler("pause", () => a.pause());
    navigator.mediaSession.setActionHandler("seekto", (d) => { if (d.seekTime != null) a.currentTime = d.seekTime; });
  }
  try {
    await a.play();
  } catch (err) {
    if (err.name !== "AbortError") { toast("This browser can't play that file.", "error"); stopPlayer(); }
  }
  syncPlayer();
}

function stopPlayer() {
  if (!player.audio) return;
  player.audio.pause();
  player.audio.removeAttribute("src");
  player.audio.load();
  player.path = null;
  player.track = null;
  syncPlayer();
}

/** Reflect what's playing on the rows (button, progress line, spinning disc). */
function syncPlayer() {
  const playing = player.audio && !player.audio.paused && !player.audio.ended;
  let disc = null;
  for (const [path, { row, track }] of state.rows) {
    const current = path === player.path;
    row.classList.toggle("is-current", current);
    row.classList.toggle("playing", current && !!playing);
    if (current) disc = discInfo()?.discOf(track) ?? null;
    const btn = $(".play-btn", row);
    if (!btn) continue;
    const on = current && playing;
    btn.replaceChildren(icon(on ? "pause" : "play"), h("span", { class: "play-label" }, on ? "Pause" : "Play"));
    btn.setAttribute("aria-label", `${on ? "Pause" : "Play"} ${first(track, "title") || track.name}`);
  }
  for (const head of els.tracks.querySelectorAll(".disc-head")) {
    head.classList.toggle("spinning", !!playing && head.dataset.disc === String(disc) && player.folder === state.path);
  }
  npRender(!!playing);
}

// ---- Now playing: a pill that grows out of a circle at the bottom centre ----------------------------

const np = { built: false, els: {} };

function npBuild() {
  if (np.built) return;
  const box = $("#now-playing");
  const e = np.els;
  e.art = h("span", { class: "np-art", "aria-hidden": "true" });
  e.title = h("span", { class: "np-title", dir: "auto" });
  e.artist = h("span", { class: "np-artist", dir: "auto" });
  e.info = h("button", { class: "np-info", type: "button", title: "Go to this album",
    onclick: () => { if (player.folder != null) navigate(player.folder); } }, e.title, e.artist);
  e.time = h("span", { class: "np-time" });
  e.play = h("button", { class: "np-play", type: "button", onclick: () => player.track && togglePlay(player.track) });
  e.close = h("button", { class: "np-close", type: "button", "aria-label": "Stop", title: "Stop", onclick: stopPlayer }, icon("close"));
  e.seek = h("input", { class: "np-seek", type: "range", min: "0", max: "1000", value: "0", step: "1", "aria-label": "Position in the track" });
  e.seek.addEventListener("input", () => {
    player.seeking = true;
    const a = player.audio;
    if (a?.duration) e.time.textContent = `${fmtDuration((e.seek.value / 1000) * a.duration)} / ${fmtDuration(a.duration)}`;
  });
  e.seek.addEventListener("change", () => {
    const a = player.audio;
    if (a?.duration) a.currentTime = (e.seek.value / 1000) * a.duration;
    player.seeking = false;
  });
  box.replaceChildren(h("div", { class: "np-inner" }, e.art, e.info, e.time, e.play, e.close), e.seek);
  box.setAttribute("role", "region");
  box.setAttribute("aria-label", "Now playing");
  np.built = true;
}

function npRender(playing) {
  const box = $("#now-playing");
  const t = player.track;
  if (!t) {
    if (!box.hidden && !box.classList.contains("np-leave")) playOut(box, "np-leave", () => { box.hidden = true; });
    return;
  }
  npBuild();
  const e = np.els;
  e.title.textContent = first(t, "title") || t.name;
  e.artist.textContent = (t.tags.artist || []).join(", ") || first(t, "album");
  setKids(e.art, t.art ? h("img", { src: artUrlFor(t), alt: "" }) : icon("note"));
  setKids(e.play, icon(playing ? "pause" : "play"));
  e.play.setAttribute("aria-label", playing ? "Pause" : "Play");
  box.classList.toggle("is-playing", playing);
  if (box.hidden) {
    box.classList.remove("np-leave");
    box.hidden = false;
    replay(box, "np-enter");
  }
  npProgress();
}

function npProgress() {
  const a = player.audio;
  if (!np.built || !a || player.seeking) return;
  const d = a.duration;
  np.els.seek.value = d ? String(Math.round((a.currentTime / d) * 1000)) : "0";
  np.els.seek.style.setProperty("--pos", d ? `${(a.currentTime / d) * 100}%` : "0%");
  np.els.time.textContent = d ? `${fmtDuration(a.currentTime)} / ${fmtDuration(d)}` : "";
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
  if (state.filter && !isSearch()) {
    chips.push(h("button", {
      type: "button", class: "search-all", onclick: () => navigate(SEARCH + state.filter),
    }, icon("search"), h("span", {}, "Search whole library for ", h("b", {}, `“${state.filter}”`)), h("kbd", {}, "↵")));
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
      for (const v of new Set(listParts(key, values))) out.get(key).set(v, (out.get(key).get(v) || 0) + 1);
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
  if (state.selectMode) renderFolderHead();
}

// ---- Editor -----------------------------------------------------------------------------------------

function editorTracks() {
  return (state.editor?.paths || []).map(trackByPath).filter(Boolean);
}

function isDirty() {
  return pendingCount(state.editor) > 0;
}

async function confirmDiscard() {
  if (!isDirty()) return true;
  return ask({
    title: "Discard unsaved changes?",
    message: "Your edits haven't been saved yet.",
    confirmLabel: "Discard", cancelLabel: "Keep editing", danger: true,
  });
}

async function openEditor(paths) {
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

function closeEditor(force = false) {
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

function setAdvanced(on) {
  state.advanced = on;
  try { localStorage.setItem("codetta-advanced", on ? "1" : "0"); } catch { /* per-browser preference only */ }
  if (state.editor) renderEditor();
}

// ---- Editor toolbar: copy & paste tags ---------------------------------------------------------

function loadClipboard() {
  try { return JSON.parse(localStorage.getItem("codetta-clipboard")) || null; } catch { return null; }
}

function saveClipboard(clip) {
  state.clipboard = clip;
  try {
    if (clip) localStorage.setItem("codetta-clipboard", JSON.stringify(clip));
    else localStorage.removeItem("codetta-clipboard");
  } catch { /* private mode: clipboard just won't survive a reload */ }
}

function fieldLabel(key) {
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

// Fields where many libraries (and Navidrome's default settings) treat a comma
// as a separator: "Hip-Hop, Trap, Rap". Codetta saves them exactly as typed and
// treats each comma-separated part as its own value when filtering.
const COMMA_LIST_KEYS = new Set(["genre", "mood"]);

/** "Hip-Hop, Trap; Rap" -> ["Hip-Hop", "Trap", "Rap"] for comma-list fields. */
function listParts(key, values) {
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

function folderTrackPaths() {
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

async function saveToFolder() {
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

async function saveEditor(targetPaths = null) {
  const ed = state.editor;
  if (!pendingCount(ed)) return;
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
function artUrlFor(t) {
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

// ---- Activity log ---------------------------------------------------------------------------------------

const activity = { entries: [], lastId: 0, timer: null, open: null };

function activityOpenPref() {
  try {
    const v = localStorage.getItem("codetta-activity-open");
    if (v !== null) return v === "1";
  } catch { /* ignore */ }
  return !window.matchMedia("(max-width: 760px)").matches; // open on desktop, closed on phones
}

async function refreshActivity() {
  try {
    const sinceId = activity.lastId;
    let fresh = await api("GET", `/api/activity?limit=50&after_id=${sinceId}`);
    fresh = fresh.filter((e) => e.id > activity.lastId); // another refresh may have got these already
    if (sinceId > 0 && fresh.some((e) => e.undoes != null)) { await reloadActivity(); return; }
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
    return h("li", { class: `act ${e.ok ? "ok" : "err"}${related ? " related" : ""}${newIds.has(e.id) ? " new" : ""}${e.undone ? " undone" : ""}` },
      h("span", { class: "act-icon", role: "img", "aria-label": e.ok ? "Succeeded" : "Failed" }, icon(e.ok ? "check" : "alert")),
      h("div", { class: "act-main" },
        h("div", { class: "act-msg" }, e.message),
        e.changes.slice(0, 6).map((c) => h("div", { class: "act-change" },
          h("span", { class: "act-key" }, c.key),
          c.old && c.old !== c.new ? [h("span", { class: "act-old" }, c.old), " → "] : null,
          c.new ? h("span", { class: "act-new" }, c.new) : h("span", { class: "act-removed" }, "removed"))),
        e.changes.length > 6 ? h("div", { class: "act-change" }, `+${e.changes.length - 6} more`) : null,
        e.errors.slice(0, 3).map((x) => h("div", { class: "act-err" }, `${x.path.split("/").pop()}: ${x.error}`)),
        e.can_undo || e.undone ? h("div", { class: "act-actions" },
          e.can_undo
            ? h("button", { class: "link-btn act-undo", type: "button", onclick: () => undoEntry(e) },
                icon("undo"), e.kind === "undo" && !e.redo ? "Redo" : "Undo")
            : h("span", { class: "act-undone" }, "Undone")) : null),
      h("time", { datetime: e.time }, fmtTime(e.time)));
  }));
}

async function reloadActivity() {
  activity.entries = [];
  activity.lastId = 0;
  await refreshActivity();
}

async function undoEntry(e) {
  const verb = e.kind === "undo" && !e.redo ? "Redo" : "Undo";
  if (e.file_count > 1 && !(await ask({
    title: `${verb} this change?`,
    message: `“${e.message}” touched ${e.file_count} files. Files that were changed again since are left as they are.`,
    confirmLabel: `${verb} ${e.file_count} files`,
  }))) return;
  if (isDirty() && !(await ask({
    title: "Refresh the editor?",
    message: "This updates files you're editing, so their fields will reload. Your unsaved edits are kept.",
    confirmLabel: "Continue",
  }))) return;
  try {
    const res = await api("POST", `/api/activity/${e.id}/undo`);
    if (!res.undone) {
      toast(res.results.find((r) => r.error)?.error || "Nothing could be undone", "error");
    } else if (res.skipped || res.failed) {
      const left = res.skipped + res.failed;
      toast(`${res.message}. ${plural(left, "file")} left as ${left === 1 ? "it is" : "they are"} (changed since or unreadable).`);
    } else {
      toast(res.message, "success");
    }
  } catch (err) {
    toast(err.message, "error");
  }
  await reloadActivity();
  folderCache.clear(); // other folders may hold stale tags now
  await loadFolder(state.path, { keepScroll: true });
}

function startActivityPolling() {
  clearInterval(activity.timer);
  // Picks up changes made from other devices too. Paused while the tab is hidden.
  activity.timer = setInterval(() => {
    if (document.visibilityState === "visible" && state.editor && $("#auth").hidden) refreshActivity();
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
  else if (isSearch()) body.paths = folderTrackPaths().slice(0, 1000); // "All results"
  else { body.folder = state.path; body.recursive = $("#apply-recursive").checked; }
  return { body, target };
}

async function openApply(target) {
  if (!(await confirmDiscard())) return;
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
  $("#apply-target-all").textContent = isSearch() ? `All ${plural(folderTrackPaths().length, "result")}` : "This folder";
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

// ---- Connections: online features, all opt-in ------------------------------------------------
//
// Codetta is offline until the user turns a connection on (first-run card or
// Account → Connections). An env var on the server can lock a switch.

async function loadConnections() {
  try { state.connections = await api("GET", "/api/connections"); } catch { state.connections = null; }
  return state.connections;
}

const connectionOn = (id) => !!state.connections?.connections.find((c) => c.id === id)?.enabled;

/** Tell the rest of the UI what's on now (buttons appear or disappear). */
function applyConnections() {
  if (state.status) {
    state.status.lyrics_lookup = connectionOn("lyrics");
    state.status.musicbrainz = connectionOn("musicbrainz");
  }
  renderFolderHead();
  if (state.editor) renderEditor();
}

function connectionRow(c, checked, onchange) {
  const input = h("input", { type: "checkbox", role: "switch", checked, disabled: !!c.locked_by });
  input.dataset.id = c.id;
  if (onchange) input.addEventListener("change", () => onchange(c, input));
  return h("label", { class: `switch-row conn-row${c.locked_by ? " locked" : ""}` },
    h("span", { class: "switch-text" },
      h("span", { class: "switch-title" }, c.name),
      h("span", { class: "switch-sub" }, c.summary),
      h("span", { class: "conn-sends" }, h("b", {}, "Sends: "), c.sends, h("span", { class: "conn-hosts" }, ` → ${c.hosts.join(", ")}`)),
      c.locked_by ? h("span", { class: "conn-lock" }, `Set on the server by ${c.locked_by}.`) : null,
      c.unavailable ? h("span", { class: "conn-lock" }, c.unavailable) : null),
    input);
}

function showWelcome() {
  const conn = state.connections;
  const list = $("#welcome-list");
  // Pre-ticked when "online" is chosen; the user can untick any of them.
  setKids(list, conn.connections.map((c) => connectionRow(c, c.locked_by ? c.enabled : true)));
  for (const r of document.querySelectorAll('input[name="welcome-mode"]')) r.checked = false;
  list.hidden = true;
  $("#welcome-go").disabled = true;
  $("#welcome-go").textContent = "Continue";
  $("#welcome-error").hidden = true;
  $("#welcome").hidden = false;
}

function welcomeModeChanged() {
  const mode = $('input[name="welcome-mode"]:checked')?.value;
  $("#welcome-list").hidden = mode !== "online";
  $("#welcome-go").disabled = !mode;
  $("#welcome-go").textContent = mode === "online" ? "Turn on and continue" : "Stay offline";
}

async function submitWelcome(e) {
  e.preventDefault();
  const mode = $('input[name="welcome-mode"]:checked')?.value;
  if (!mode) return;
  const enabled = {};
  for (const input of $("#welcome-list").querySelectorAll("input[data-id]")) {
    if (!input.disabled) enabled[input.dataset.id] = mode === "online" && input.checked;
  }
  const go = $("#welcome-go");
  go.disabled = true;
  try {
    state.connections = await api("PUT", "/api/connections", { enabled });
    applyConnections();
    if (connectionOn("updates")) refreshUpdate();
    toast(state.connections.offline
      ? "Codetta will stay offline. You can change this in Account → Connections."
      : "Online features are on. Change them any time in Account → Connections.", "success");
    nextSetupStep();
  } catch (err) {
    $("#welcome-error").textContent = err.message;
    $("#welcome-error").hidden = false;
    go.disabled = false;
  }
}

const connOpenPref = () => { try { return localStorage.getItem("codetta-connections-open") === "1"; } catch { return false; } };

/** Open or close the Connections section (remembered per browser). */
function setConnectionsOpen(open) {
  $("#conn-toggle").setAttribute("aria-expanded", String(open));
  $("#conn-body").hidden = !open;
  $(".connections").classList.toggle("open", open);
  try { localStorage.setItem("codetta-connections-open", open ? "1" : "0"); } catch { /* private mode */ }
}

function renderConnections() {
  const conn = state.connections;
  const on = conn ? conn.connections.filter((c) => c.enabled).map((c) => c.name.split(":")[0]) : [];
  $("#conn-summary").textContent = !conn ? "" : on.length ? `On: ${on.join(", ")}` : "Offline: nothing is sent anywhere";
  setConnectionsOpen(connOpenPref());
  const intro = $("#conn-intro");
  if (!conn) {
    intro.textContent = "Couldn't load the connection settings.";
    $("#conn-list").replaceChildren();
    return;
  }
  intro.textContent = conn.offline_locked
    ? "This server is set to stay offline (CODETTA_OFFLINE), so these can't be turned on."
    : "Codetta is offline unless you turn these on. Only what's listed is sent, and only to these sites.";
  setKids($("#conn-list"), conn.connections.map((c) => connectionRow(c, c.enabled, async (item, input) => {
    input.disabled = true;
    try {
      state.connections = await api("PUT", "/api/connections", { enabled: { [item.id]: input.checked } });
      const names = state.connections.connections.filter((c) => c.enabled).map((c) => c.name.split(":")[0]);
      $("#conn-summary").textContent = names.length ? `On: ${names.join(", ")}` : "Offline: nothing is sent anywhere";
      applyConnections();
      if (item.id === "updates") refreshUpdate();
    } catch (err) {
      input.checked = !input.checked;
      toast(err.message, "error");
    } finally {
      input.disabled = !!item.locked_by;
    }
  })));
}

// ---- Match on MusicBrainz ---------------------------------------------------------------------------
//
// Two steps in one sheet: pick the release (search results, or a pasted link),
// then review what changes per file before anything is written.

const mb = {
  target: null, // { body: {folder} | {paths}, label }
  query: { album: "", artist: "", link: "" },
  results: null, // /api/musicbrainz/search response
  error: null,
  busy: false,
  release: null, // chosen release id
  proposal: null, // /api/musicbrainz/preview response
  pairs: {}, // path -> track id ("" = leave this file alone), only the user's own picks
  recordings: {}, // path -> recording IDs heard by Identify by sound
  sound: null, // the last /api/musicbrainz/identify summary
  fields: null, // Set of tag names, or null for the server's default set
  mode: "overwrite",
  cover: "missing",
  openGroups: new Set(),
  openFiles: new Set(),
  token: 0,
  timer: null,
};

function mbTarget() {
  const n = state.selected.size;
  if (n) return { body: { paths: [...state.selected] }, label: plural(n, "selected track") };
  if (isSearch()) return { body: { paths: folderTrackPaths().slice(0, 1000) }, label: plural(Math.min(folderTrackPaths().length, 1000), "result") };
  return { body: { folder: state.path }, label: "this folder" };
}

async function openMusicBrainz() {
  if (!(await confirmDiscard())) return;
  openMusicBrainzFor(mbTarget());
}

/** Open the match dialog for any set of files; ``release`` jumps straight to its review. */
function openMusicBrainzFor(target, { release = null, recordings = {}, onWritten = null } = {}) {
  Object.assign(mb, {
    target, query: { album: "", artist: "", link: "" }, results: null, error: null,
    release: null, proposal: null, pairs: {}, fields: null, mode: "overwrite", cover: "missing",
    openGroups: new Set(), openFiles: new Set(), recordings: recordings || {}, sound: null, onWritten,
  });
  openDialog($("#mb-dialog"));
  if (release) mbPick(release);
  else mbSearch({});
}

async function mbSearch(extra) {
  const token = ++mb.token;
  mb.busy = true;
  mb.error = null;
  mb.release = null;
  renderMbSearch();
  try {
    const res = await api("POST", "/api/musicbrainz/search", { ...mb.target.body, ...extra });
    if (token !== mb.token) return;
    mb.results = res;
    if (!extra.release) Object.assign(mb.query, { album: res.query.album, artist: res.query.artist });
    // A pasted link names exactly one release: go straight to the review.
    if (extra.release && res.candidates.length === 1) { mbPick(res.candidates[0].id); return; }
  } catch (err) {
    if (token !== mb.token) return;
    mb.error = err.message;
  }
  mb.busy = false;
  renderMbSearch();
}

/** Identify by sound: fingerprint the files on the server, ask AcoustID what they are. */
async function mbIdentify() {
  const token = ++mb.token;
  mb.busy = "sound";
  mb.error = null;
  renderMbSearch();
  try {
    const res = await api("POST", "/api/musicbrainz/identify", mb.target.body);
    if (token !== mb.token) return;
    mb.results = res;
    mb.recordings = res.recordings;
    mb.sound = { identified: res.identified, total: res.total, files: res.files };
  } catch (err) {
    if (token !== mb.token) return;
    mb.error = err.message;
  }
  mb.busy = false;
  renderMbSearch();
}

function mbThumb(id, size = 250) {
  const empty = () => h("span", { class: "mb-thumb mb-noart", "aria-hidden": "true" }, icon("note"));
  if (!id) return empty();
  const img = h("img", { class: "mb-thumb", src: `/api/musicbrainz/cover/${id}?size=${size}`, alt: "", loading: "lazy", decoding: "async", width: "56", height: "56" });
  img.addEventListener("error", () => img.replaceWith(empty()), { once: true });
  return img;
}

const mbYear = (date) => (date || "").slice(0, 4);

function mbMeta(c) {
  return [mbYear(c.date), c.country, c.formats, c.track_count ? plural(c.track_count, "track") : "", c.labels[0], c.type]
    .filter(Boolean).join(" · ");
}

function renderMbSearch() {
  const body = $("#mb-body");
  const album = h("input", { type: "text", value: mb.query.album, dir: "auto", autocomplete: "off", spellcheck: "false", "aria-label": "Album" });
  const artist = h("input", { type: "text", value: mb.query.artist, dir: "auto", autocomplete: "off", spellcheck: "false", "aria-label": "Artist" });
  const link = h("input", { type: "text", value: mb.query.link, autocomplete: "off", spellcheck: "false", inputmode: "url",
    placeholder: "https://musicbrainz.org/release/…", "aria-label": "MusicBrainz release link" });
  for (const [input, key] of [[album, "album"], [artist, "artist"], [link, "link"]]) {
    input.addEventListener("input", () => { mb.query[key] = input.value; });
  }
  const search = (e) => {
    e.preventDefault();
    mbSearch({ album: album.value.trim(), artist: artist.value.trim() });
  };
  const useLink = (e) => {
    e.preventDefault();
    if (link.value.trim()) mbSearch({ release: link.value.trim() });
  };
  const res = mb.results;
  let list;
  if (mb.busy === "sound") list = h("p", { class: "loading" }, "Listening to your tracks, then asking AcoustID… (a few seconds per track)");
  else if (mb.busy) list = h("p", { class: "loading" }, "Asking MusicBrainz…");
  else if (mb.error) list = h("div", { class: "error-box" }, mb.error);
  else if (res && !res.candidates.length) {
    list = h("p", { class: "mb-empty" }, res.query.album || res.query.artist
      ? "No releases found. Try fewer words, or paste the release link from musicbrainz.org."
      : connectionOn("acoustid")
        ? "These tracks have no album or artist yet. Type what to search for, or identify them by sound."
        : "These tracks have no album or artist yet. Type what to search for above.");
  } else if (res) {
    list = h("div", { class: "mb-cands", role: "list" }, res.candidates.map((c) => h("button", {
      type: "button", class: "mb-cand", role: "listitem", onclick: () => mbPick(c.id),
    },
      mbThumb(c.id),
      h("span", { class: "mb-cand-main" },
        h("span", { class: "mb-cand-title", dir: "auto" }, c.title, c.disambiguation ? h("span", { class: "mb-dis" }, ` (${c.disambiguation})`) : null),
        h("span", { class: "mb-cand-artist", dir: "auto" }, c.artist),
        h("span", { class: "mb-cand-meta" }, mbMeta(c)),
        c.heard != null ? h("span", { class: "mb-heard" }, `${c.heard} of your ${plural(res.total, "track")} ${c.heard === 1 ? "is" : "are"} on it`) : null,
        c.current ? h("span", { class: "mb-current" }, h("span", { class: "badge" }, "Your files use this release")) : null),
      h("span", { class: "mb-cand-side" },
        h("span", { class: `mb-score ${c.score >= 85 ? "good" : c.score >= 60 ? "ok" : "low"}`, title: "How well this release fits these files" }, `${c.score}%`),
        h("span", { class: "mb-chev" }, icon("chevron"))))));
  }
  const sound = mb.sound;
  const unknown = sound ? sound.files.filter((f) => f.status !== "identified") : [];
  const soundBox = connectionOn("acoustid") ? h("div", { class: "mb-sound" },
    h("div", { class: "mb-sound-text" },
      h("strong", {}, "Identify by sound"),
      h("span", {}, sound
        ? `Recognised ${sound.identified} of ${plural(sound.total, "track")}.${unknown.length ? ` Not recognised: ${unknown.slice(0, 3).map((f) => relativeToFolder(f.path)).join(", ")}${unknown.length > 3 ? ` +${unknown.length - 3} more` : ""}.` : ""}`
        : "Works even on untagged files. Codetta fingerprints each track here and sends only that code to AcoustID.")),
    h("button", { class: "btn", type: "button", disabled: !!mb.busy, "aria-busy": String(mb.busy === "sound"), onclick: mbIdentify },
      mb.busy === "sound" ? "Listening…" : sound ? "Listen again" : "Listen")) : null;
  setKids(body,
    h("p", { class: "mb-lead" }, `Find the release for ${mb.target.label}. Pick the exact edition (year, country, format), then review every change before it's written.`),
    soundBox,
    h("form", { class: "mb-search", onsubmit: search },
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Album"), album),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Artist"), artist),
      h("button", { class: "btn", type: "submit", disabled: mb.busy }, icon("search"), "Search")),
    h("form", { class: "mb-link", onsubmit: useLink },
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Or paste a release link"), link),
      h("button", { class: "btn", type: "submit", disabled: mb.busy }, "Use link")),
    list);
  setKids($("#mb-foot"),
    h("span", { class: "mb-credit" }, "Data from ", h("a", { href: "https://musicbrainz.org", target: "_blank", rel: "noopener noreferrer" }, "MusicBrainz")),
    h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"));
}

function mbPick(id) {
  mb.release = id;
  mb.proposal = null;
  mb.pairs = {};
  mb.fields = null;
  mb.openFiles = new Set();
  mb.error = null;
  mbPreview(0);
}

function mbBody(extra = {}) {
  return {
    ...mb.target.body, release: mb.release, mode: mb.mode, cover: mb.cover,
    pairs: Object.fromEntries(Object.entries(mb.pairs).map(([p, t]) => [p, t || null])),
    recordings: mb.recordings,
    fields: mb.fields ? [...mb.fields] : null,
    ...extra,
  };
}

function mbPreview(delay = 200) {
  clearTimeout(mb.timer);
  mb.busy = true;
  if (!mb.proposal) renderMbReview();
  else $("#mb-go")?.setAttribute("disabled", "");
  mb.timer = setTimeout(async () => {
    const token = ++mb.token;
    try {
      const p = await api("POST", "/api/musicbrainz/preview", mbBody());
      if (token !== mb.token) return;
      mb.proposal = p;
      mb.error = null;
      if (!mb.fields) mb.fields = new Set(p.fields);
    } catch (err) {
      if (token !== mb.token) return;
      mb.error = err.message;
    }
    mb.busy = false;
    renderMbReview();
  }, delay);
}

function mbValue(values) {
  return values.length ? values.join("; ") : "";
}

function renderMbReview() {
  const body = $("#mb-body");
  const p = mb.proposal;
  const back = h("button", { class: "btn", type: "button", onclick: () => { mb.release = null; mb.busy = false; renderMbSearch(); } }, "Back");
  if (!p) {
    setKids(body, mb.error ? h("div", { class: "error-box" }, mb.error) : h("p", { class: "loading" }, "Reading the release from MusicBrainz…"));
    setKids($("#mb-foot"), back, h("span", { class: "spacer" }), h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"));
    return;
  }
  const scroll = body.scrollTop;
  const r = p.release;
  const labels = new Map(p.groups.flatMap((g) => g.fields.map((f) => [f.key, f.label])));

  // Fields to include, by group.
  const groups = h("div", { class: "mb-groups" }, p.groups.map((g) => {
    const keys = g.fields.map((f) => f.key);
    const on = keys.filter((k) => mb.fields.has(k)).length;
    const all = h("input", { type: "checkbox", checked: on === keys.length, indeterminate: on > 0 && on < keys.length });
    all.addEventListener("change", () => {
      for (const k of keys) all.checked ? mb.fields.add(k) : mb.fields.delete(k);
      mbPreview();
      renderMbReview();
    });
    const open = mb.openGroups.has(g.id);
    return h("div", { class: `mb-group${open ? " open" : ""}` },
      h("div", { class: "mb-group-row" },
        h("label", { class: "check" }, all, h("span", { class: "mb-group-name" }, g.label)),
        keys.length > 1 ? h("button", {
          class: "link-btn mb-group-more", type: "button", "aria-expanded": String(open),
          onclick: () => { open ? mb.openGroups.delete(g.id) : mb.openGroups.add(g.id); renderMbReview(); },
        }, on === keys.length ? "All" : `${on} of ${keys.length}`, icon("chevron")) : null),
      open ? h("div", { class: "mb-group-fields" }, g.fields.map((f) => {
        const box = h("input", { type: "checkbox", checked: mb.fields.has(f.key) });
        box.addEventListener("change", () => {
          box.checked ? mb.fields.add(f.key) : mb.fields.delete(f.key);
          mbPreview();
          renderMbReview();
        });
        return h("label", { class: "check" }, box, f.label);
      })) : null);
  }));

  const segmented = (name, value, options, onpick, disabled = false) => h("div", { class: "segmented" },
    options.map(([v, label]) => {
      const input = h("input", { type: "radio", name, value: v, checked: value === v, disabled });
      input.addEventListener("change", () => { onpick(v); mbPreview(); });
      return h("label", {}, input, h("span", {}, label));
    }));

  // Files and what changes in each.
  const used = new Set(p.files.map((f) => f.track?.id).filter(Boolean));
  const multiDisc = new Set(p.tracks.map((t) => t.disc)).size > 1;
  const trackLabel = (t) => `${multiDisc ? `${t.disc}-` : ""}${t.number || t.position}. ${t.title}${t.length ? ` (${fmtDuration(t.length)})` : ""}`;
  const changing = p.files.filter((f) => !f.error && f.track && (Object.keys(f.changes).length || f.cover));
  const tagTotal = changing.reduce((n, f) => n + Object.keys(f.changes).length, 0);
  const covers = changing.filter((f) => f.cover).length;
  const check = p.files.filter((f) => f.confidence === "check" || (!f.track && !f.error)).length;
  const files = p.files.map((f) => {
    const name = relativeToFolder(f.path);
    if (f.error) return h("div", { class: "mb-file error" }, h("div", { class: "mb-file-name" }, name), h("div", { class: "note" }, f.error));
    const select = h("select", { "aria-label": `Track for ${name}` },
      h("option", { value: "" }, "Leave this file alone"),
      p.tracks.map((t) => h("option", { value: t.id, selected: f.track?.id === t.id },
        `${trackLabel(t)}${used.has(t.id) && f.track?.id !== t.id ? "  · used" : ""}`)));
    select.addEventListener("change", () => { mb.pairs[f.path] = select.value; mbPreview(0); });
    const keys = Object.keys(f.changes);
    const state_ = !f.track ? "skip" : f.confidence === "check" ? "check" : "ok";
    const diff = keys.length || f.cover ? h("details", { class: "mb-diff", open: mb.openFiles.has(f.path) },
      h("summary", {}, [keys.length ? plural(keys.length, "tag") : "", f.cover ? "cover art" : ""].filter(Boolean).join(" + ")),
      h("div", { class: "mb-diff-list" },
        keys.map((k) => h("div", { class: "mb-diff-row" },
          h("span", { class: "mb-diff-key" }, labels.get(k) || k),
          h("span", { class: "mb-diff-val", dir: "auto" },
            f.changes[k].old.length ? [h("span", { class: "mb-old" }, mbValue(f.changes[k].old)), " → "] : null,
            h("span", { class: "mb-new" }, mbValue(f.changes[k].new))))),
        f.cover ? h("div", { class: "mb-diff-row" }, h("span", { class: "mb-diff-key" }, "Cover art"),
          h("span", { class: "mb-diff-val" }, f.has_art ? "Replace with the release's front cover" : "Add the release's front cover")) : null)) : null;
    if (diff) diff.addEventListener("toggle", () => { diff.open ? mb.openFiles.add(f.path) : mb.openFiles.delete(f.path); });
    return h("div", { class: `mb-file ${state_}` },
      h("div", { class: "mb-file-head" },
        h("span", { class: "mb-file-icon", role: "img", "aria-label": state_ === "ok" ? "Matched" : state_ === "check" ? "Check this match" : "Not matched" },
          icon(state_ === "ok" ? "check" : "alert")),
        h("span", { class: "mb-file-name", title: f.path }, name),
        select),
      f.notes?.length && state_ !== "ok" ? h("div", { class: "note" }, f.notes.join(" · ")) : null,
      f.unsupported?.length ? h("div", { class: "note" }, `This format can't store: ${f.unsupported.map((k) => labels.get(k) || k).join(", ")}`) : null,
      diff || (f.track ? h("div", { class: "note" }, "Already matches") : null));
  });
  const spare = p.tracks.filter((t) => !used.has(t.id)).length;

  const summary = [];
  if (changing.length) summary.push(`${plural(changing.length, "track")} will change (${plural(tagTotal, "tag")}${covers ? `, cover on ${covers}` : ""}).`);
  else summary.push("Nothing to change with these settings.");
  if (check) summary.push(`${plural(check, "file")} to check.`);
  if (spare) summary.push(`${plural(spare, "track")} on this release ${spare === 1 ? "has" : "have"} no file here.`);

  setKids(body,
    h("div", { class: "mb-release" },
      mbThumb(r.id),
      h("div", { class: "mb-release-main" },
        h("div", { class: "mb-cand-title", dir: "auto" }, r.title, r.disambiguation ? h("span", { class: "mb-dis" }, ` (${r.disambiguation})`) : null),
        h("div", { class: "mb-cand-artist", dir: "auto" }, r.artist),
        h("div", { class: "mb-cand-meta" }, mbMeta(r)),
        h("div", { class: "mb-release-links" },
          h("button", { class: "link-btn", type: "button", onclick: () => { mb.release = null; mb.busy = false; renderMbSearch(); } }, "Choose another release"),
          h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, "View on MusicBrainz")))),
    mb.error ? h("div", { class: "error-box" }, mb.error) : null,
    h("div", { class: "field" }, h("span", { class: "field-label" }, "Include"), groups),
    h("div", { class: "mb-options" },
      h("fieldset", { class: "field" }, h("legend", { class: "field-label" }, "Existing values"),
        segmented("mb-mode", mb.mode, [["overwrite", "Replace"], ["fill", "Only fill empty"]], (v) => { mb.mode = v; })),
      h("fieldset", { class: "field" }, h("legend", { class: "field-label" }, "Cover art"),
        segmented("mb-cover", r.has_cover === false ? "none" : mb.cover,
          [["missing", "Where missing"], ["all", "Replace all"], ["none", "Leave"]], (v) => { mb.cover = v; }, r.has_cover === false),
        r.has_cover === false ? h("p", { class: "hint" }, "This release has no cover art on the Cover Art Archive.") : null)),
    h("p", { class: "preview-summary", "aria-live": "polite" }, summary.join(" ")),
    h("div", { class: "mb-files" }, files));
  body.scrollTop = scroll;

  setKids($("#mb-foot"),
    back,
    h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", id: "mb-go", disabled: mb.busy || !changing.length, onclick: mbApply },
      changing.length ? `Write to ${plural(changing.length, "track")}` : "Write"));
}

async function mbApply() {
  const go = $("#mb-go");
  go.disabled = true;
  go.textContent = "Writing…";
  try {
    const res = await api("POST", "/api/musicbrainz/apply", mbBody());
    closeDialog($("#mb-dialog"));
    const failed = res.results.filter((r) => !r.ok);
    if (failed.length) toast(`Tagged ${plural(res.updated, "track")}; ${failed.length} failed: ${failed[0].error}`, "error");
    else toast(`Tagged ${plural(res.updated, "track")} from MusicBrainz. Undo is in the activity log.`, "success");
    if (res.cover_error) toast(`Cover art wasn't added: ${res.cover_error}`, "error");
    if (mb.onWritten) { const done = mb.onWritten; mb.onWritten = null; done(mb.release); }
    refreshActivity();
    folderCache.clear();
    await loadFolder(state.path, { keepScroll: true });
  } catch (err) {
    toast(err.message, "error");
    mbPreview(0);
  }
}

// ---- First-run setup: a few plain steps, each skippable ------------------------------------------------
//
// New installs see every step after creating the account; existing installs see
// only the steps added since (once). Then "What's new".

const setup = { steps: [], index: 0, total: 0 };

async function runSetup() {
  await loadConnections();
  let steps = [];
  try { steps = (await api("GET", "/api/onboarding")).steps; } catch { /* carry on */ }
  setup.steps = steps;
  setup.total = steps.length;
  setup.index = 0;
  nextSetupStep();
}

function nextSetupStep() {
  const step = setup.steps[setup.index++];
  if (!step) {
    $("#welcome").hidden = true;
    afterSetup();
    return;
  }
  $("#welcome").hidden = false;
  if (step === "connections") {
    $("#setup-step").hidden = true;
    $("#welcome-form").hidden = false;
    showWelcome();
  } else {
    $("#welcome-form").hidden = true;
    $("#setup-step").hidden = false;
    renderSetupStep(step);
  }
}

const stepCount = () => (setup.total > 1 ? h("p", { class: "setup-count" }, `Step ${setup.index} of ${setup.total}`) : null);
const setupLogo = () => h("div", { class: "auth-logo", "aria-hidden": "true" },
  h("span", { class: "wordmark" }, "codetta", h("span", { class: "spot-dot" })));

async function finishStep(step) {
  try { await api("POST", `/api/onboarding/${step}`); } catch { /* shown again next time: harmless */ }
  nextSetupStep();
}

async function renderSetupStep(step) {
  const form = $("#setup-step");
  form.onsubmit = null;
  if (step === "organize") {
    let settings;
    try { settings = await api("GET", "/api/organize/settings"); } catch { finishStep(step); return; }
    const examples = await Promise.all(settings.presets.map((p) => api("POST", "/api/organize/example", { pattern: p.pattern }).catch(() => null)));
    let chosen = settings.presets.some((p) => p.pattern === settings.pattern) ? settings.pattern : settings.presets[0].pattern;
    setKids(form, setupLogo(), stepCount(),
      h("h1", {}, "How should your folders be named?"),
      h("p", { class: "auth-sub" }, "When you organize a folder, or file new music from your inbox, Codetta renames and moves the files using a pattern. Pick the one you like. You can change it any time, and nothing moves until you say so."),
      h("fieldset", { class: "choices" }, settings.presets.map((p, i) => h("label", { class: "choice" },
        h("input", { type: "radio", name: "setup-pattern", value: p.pattern, checked: p.pattern === chosen,
          onchange: () => { chosen = p.pattern; } }),
        h("span", { class: "choice-body" },
          h("span", { class: "choice-title" }, p.name),
          examples[i]?.ok ? h("code", { class: "choice-code", dir: "auto" }, examples[i].single) : null)))),
      h("button", { class: "btn primary auth-submit", type: "submit" }, "Use this pattern"),
      h("button", { class: "link-btn setup-skip", type: "button", onclick: () => finishStep(step) }, "Skip for now"));
    form.onsubmit = async (e) => {
      e.preventDefault();
      try { await api("PUT", "/api/organize/settings", { pattern: chosen }); } catch (err) { toast(err.message, "error"); return; }
      finishStep(step);
    };
  } else if (step === "inbox") {
    let root = { folders: [] };
    try { root = await api("GET", "/api/browse?path="); } catch { /* no library yet */ }
    setKids(form, setupLogo(), stepCount(),
      h("h1", {}, "Where does new music arrive?"),
      h("p", { class: "auth-sub" }, "Pick the folder your downloads or rips land in. Codetta treats it as an inbox: it finds each new album, and files it into your library with your folder pattern. Nothing moves until you say so (unless you allow it below)."),
      inboxSettingsFields({ folder: "", auto: false, watch: false }, root.folders),
      h("button", { class: "btn primary auth-submit", type: "submit", id: "setup-inbox-go", disabled: true }, "Use this folder"),
      h("button", { class: "link-btn setup-skip", type: "button", onclick: () => finishStep(step) }, "Not now"),
      h("p", { class: "auth-foot" }, "You can set this up or change it later from the Inbox button in the top bar."));
    form.onsubmit = async (e) => {
      e.preventDefault();
      try { await api("PUT", "/api/inbox/settings", readInboxFields(form)); } catch (err) { toast(err.message, "error"); return; }
      $("#inbox-btn").hidden = false;
      finishStep(step);
    };
  }
}

/** The inbox's settings fields (used in setup and in the Inbox screen). */
function inboxSettingsFields(s, folders) {
  const select = h("select", { name: "inbox-folder", "aria-label": "Inbox folder" },
    h("option", { value: "" }, folders.length ? "Choose a folder…" : "No folders in your library yet"),
    folders.map((f) => h("option", { value: f.path, selected: f.path === s.folder }, f.name)));
  select.addEventListener("change", () => {
    const go = select.form?.querySelector("[type=submit]");
    if (go) go.disabled = !select.value;
  });
  return h("div", { class: "inbox-fields" },
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Inbox folder"), select),
    !connectionOn("musicbrainz") ? h("p", { class: "hint" }, "Online lookups are off, so albums are filed by their own tags. Turn on MusicBrainz in Account → Connections to match them automatically.") : null,
    h("label", { class: "switch-row" },
      h("span", { class: "switch-text" },
        h("span", { class: "switch-title" }, "File confident matches automatically"),
        h("span", { class: "switch-sub" }, "When every track lines up with a MusicBrainz release, tag and file it without asking. Everything else waits for you.")),
      h("input", { type: "checkbox", role: "switch", name: "inbox-auto", checked: s.auto })),
    h("label", { class: "switch-row" },
      h("span", { class: "switch-text" },
        h("span", { class: "switch-title" }, "Check for new music every 15 minutes"),
        h("span", { class: "switch-sub" }, "Off: Codetta only looks when you open the Inbox (so idle disks can sleep).")),
      h("input", { type: "checkbox", role: "switch", name: "inbox-watch", checked: s.watch })));
}

function readInboxFields(root) {
  return {
    folder: $('[name="inbox-folder"]', root).value,
    auto: $('[name="inbox-auto"]', root).checked,
    watch: $('[name="inbox-watch"]', root).checked,
    organize: true,
  };
}

function afterSetup() {
  refreshInboxBadge();
  let seen = null;
  try { seen = localStorage.getItem("codetta-seen-version"); } catch { /* private mode */ }
  if (seen !== state.auth?.version) openNews({ latestOnly: true });
}

// ---- What's new (the changelog) ---------------------------------------------------------------------

let newsData = null;

/** Changelog text -> nodes: **bold**, `code` and https links; everything else stays plain text. */
function mdInline(text) {
  const out = [];
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) out.push(h("strong", {}, m[1]));
    else if (m[2]) out.push(h("code", {}, m[2]));
    else out.push(h("a", { href: m[4], target: "_blank", rel: "noopener noreferrer" }, m[3]));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

async function openNews({ latestOnly = false } = {}) {
  try { newsData = newsData || await api("GET", "/api/changelog"); } catch (err) { toast(err.message, "error"); return; }
  const versions = newsData.versions;
  const section = (v) => h("section", { class: "news-version" },
    h("h3", {}, v.unreleased ? `Coming in ${v.version}` : `Version ${v.version}`,
      v.date ? h("span", { class: "news-date" }, new Date(`${v.date}T12:00:00`).toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" })) : null),
    h("ul", {}, v.items.map((item) => h("li", {}, mdInline(item)))));
  const body = $("#news-body");
  const renderAll = () => setKids(body, versions.map(section));
  if (!versions.length) setKids(body, h("p", { class: "hint" }, "The changelog isn't available on this server."));
  else if (latestOnly && versions.length > 1) {
    setKids(body, section(versions[0]),
      h("button", { class: "link-btn news-more", type: "button", onclick: renderAll }, "Show earlier versions"));
  } else renderAll();
  try { localStorage.setItem("codetta-seen-version", newsData.current); } catch { /* private mode */ }
  openDialog($("#news-dialog"));
}

// ---- Inbox: new music waiting to be filed -------------------------------------------------------------

const inboxState = { data: null, timer: null, settingsOpen: false };
const INBOX_LABELS = {
  waiting: "Waiting", matching: "Looking up…", ready: "Ready to file", review: "Needs a look", nomatch: "Not found",
  local: "Files by its tags", filed: "Filed", skipped: "Skipped", error: "Problem",
};
const inboxPending = (d) => (d?.groups || []).filter((g) => !["filed", "skipped"].includes(g.status)).length;

async function refreshInboxBadge(data = null) {
  try { data = data || await api("GET", "/api/inbox"); } catch { return; }
  inboxState.data = data;
  const n = inboxPending(data);
  $("#inbox-btn").hidden = !data.settings.folder;
  $("#inbox-count").hidden = !n;
  $("#inbox-count").textContent = n > 99 ? "99+" : String(n);
}

async function openInbox() {
  openDialog($("#inbox-dialog"));
  setKids($("#inbox-body"), h("p", { class: "loading" }, "Looking in your inbox…"));
  setKids($("#inbox-foot"));
  await loadInbox();
}

async function loadInbox() {
  clearTimeout(inboxState.timer);
  try {
    inboxState.data = await api("GET", "/api/inbox");
  } catch (err) {
    setKids($("#inbox-body"), h("div", { class: "error-box" }, err.message));
    return;
  }
  renderInbox();
  // Keep it fresh while lookups run and the sheet is open.
  if (inboxState.data.running && $("#inbox-dialog").open) inboxState.timer = setTimeout(loadInbox, 1500);
}

async function inboxAction(url, body, done) {
  try {
    const res = await api("POST", url, body);
    inboxState.data = res.inbox || res;
    if (done) done(res);
    renderInbox();
    folderCache.clear();
    refreshActivity();
    if (inboxState.data.running) inboxState.timer = setTimeout(loadInbox, 1500);
  } catch (err) {
    toast(err.message, "error");
  }
}

function reviewInboxGroup(g) {
  closeDialog($("#inbox-dialog"));
  openMusicBrainzFor({ body: { paths: g.paths }, label: `“${g.title || g.key.split("/").pop()}”` }, {
    release: g.release?.id, recordings: g.recordings,
    onWritten: (release) => inboxAction("/api/inbox/accept", { key: g.key, release }, (res) => {
      toast(res.moved_to ? `Filed in ${res.moved_to}` : "Tagged", res.status === "filed" ? "success" : "error");
    }),
  });
}

function renderInbox() {
  const d = inboxState.data;
  const body = $("#inbox-body");
  refreshInboxBadge(d);
  if (!d.settings.folder || !d.folder_exists || inboxState.settingsOpen) {
    api("GET", "/api/browse?path=").catch(() => ({ folders: [] })).then((root) => {
      const form = h("form", { class: "inbox-settings" },
        h("p", { class: "mb-lead" }, d.settings.folder && !d.folder_exists
          ? `The inbox folder “${d.settings.folder}” isn't there any more. Choose another.`
          : "Pick the folder new music lands in (downloads, rips). Codetta finds each album and files it into your library with your folder pattern."),
        inboxSettingsFields(d.settings, root.folders),
        h("div", { class: "inbox-settings-actions" },
          d.settings.folder && d.folder_exists ? h("button", { class: "btn", type: "button", onclick: () => { inboxState.settingsOpen = false; renderInbox(); } }, "Cancel") : null,
          h("button", { class: "btn primary", type: "submit", disabled: !d.settings.folder }, "Save")));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          inboxState.data = await api("PUT", "/api/inbox/settings", readInboxFields(form));
          inboxState.settingsOpen = false;
          renderInbox();
          if (inboxState.data.running) inboxState.timer = setTimeout(loadInbox, 1500);
        } catch (err) { toast(err.message, "error"); }
      });
      setKids(body, form);
      setKids($("#inbox-foot"), h("span", { class: "spacer" }), h("button", { class: "btn", type: "button", "data-close": true }, "Close"));
    });
    return;
  }
  const ready = d.groups.filter((g) => g.status === "ready");
  const pending = inboxPending(d);
  const item = (g) => {
    const name = g.title || g.key.split("/").pop();
    const actions = [];
    const btn = (label, onclick, primary = false) => h("button", { class: `btn small${primary ? " primary" : ""}`, type: "button", onclick }, label);
    const accept = () => inboxAction("/api/inbox/accept", { key: g.key }, (res) =>
      toast(res.status === "filed" ? `Filed in ${res.moved_to || "your library"}` : res.note, res.status === "filed" ? "success" : "error"));
    if (g.status === "ready") actions.push(btn("File", accept, true), btn("Review", () => reviewInboxGroup(g)));
    else if (g.status === "review") actions.push(btn("Review", () => reviewInboxGroup(g), true), btn("File with this match", accept));
    else if (g.status === "nomatch") actions.push(btn("Search", () => reviewInboxGroup(g), true), btn("File by its tags", accept));
    else if (g.status === "local") actions.push(btn("File", accept, true));
    else if (g.status === "error") actions.push(btn("Try again", () => inboxAction("/api/inbox/rematch", { key: g.key })), d.online ? btn("Review", () => reviewInboxGroup(g)) : null);
    else if (g.status === "skipped") actions.push(btn("Look again", () => inboxAction("/api/inbox/rematch", { key: g.key })));
    else if (g.status === "filed" && g.dest) actions.push(btn("Open", () => { closeDialog($("#inbox-dialog")); navigate(g.dest); }));
    if (["ready", "review", "nomatch", "local", "error"].includes(g.status)) {
      actions.push(h("button", { class: "link-btn inbox-skip", type: "button", onclick: () => inboxAction("/api/inbox/skip", { key: g.key }) }, "Skip"));
    }
    const rel = g.release;
    return h("div", { class: `inbox-item ${g.status}` },
      rel?.id && d.online ? mbThumb(rel.id) : h("span", { class: "mb-thumb mb-noart", "aria-hidden": "true" }, icon("note")),
      h("div", { class: "inbox-main" },
        h("div", { class: "inbox-title", dir: "auto" }, name, g.artist ? h("span", { class: "inbox-artist" }, ` · ${g.artist}`) : null),
        h("div", { class: "mb-cand-meta" }, [rel ? mbMeta(rel) : "", `${plural(g.files, "file")} in ${g.key}`].filter(Boolean).join(" · ")),
        h("div", { class: "inbox-status" },
          h("span", { class: `inbox-chip ${g.status}` }, INBOX_LABELS[g.status] || g.status, g.score != null && g.status !== "filed" ? ` · ${g.score}%` : ""),
          g.note ? h("span", { class: "inbox-note" }, g.note) : null)),
      h("div", { class: "inbox-actions" }, actions));
  };
  setKids(body,
    h("div", { class: "inbox-head" },
      h("p", { class: "mb-lead" }, d.groups.length
        ? `${pending ? plural(pending, "album") + " waiting" : "All caught up"} in “${d.settings.folder}”.${d.settings.auto ? " Confident matches are filed automatically." : ""}`
        : `Nothing new in “${d.settings.folder}”. Drop an album folder in there and open the Inbox again.`),
      h("button", { class: "link-btn", type: "button", onclick: () => { inboxState.settingsOpen = true; renderInbox(); } }, "Settings")),
    d.groups.length ? h("div", { class: "inbox-list" }, d.groups.map(item)) : null);
  setKids($("#inbox-foot"),
    h("button", { class: "btn", type: "button", onclick: loadInbox }, "Check again"),
    h("span", { class: "spacer" }),
    ready.length ? h("button", { class: "btn primary", type: "button", onclick: () => inboxAction("/api/inbox/accept-ready", {}, (res) =>
      toast(`Filed ${plural(res.filed, "album")}${res.filed < res.total ? ` (${res.total - res.filed} need a look)` : ""}`, "success")) },
      `File ${plural(ready.length, "confident match", "confident matches")}`) : h("button", { class: "btn", type: "button", "data-close": true }, "Close"));
}

// ---- Organize: rename and move files from a pattern -------------------------------------------------

const org = { settings: null, pattern: "", recursive: false, remember: true, preview: null, error: null, token: 0, timer: null, exTimer: null, example: null };
const ORG_TOKENS = [
  ["Album artist", "{albumartist|artist}"], ["Artist", "{artist}"], ["Album", "{album}"], ["Year", "[ ({year})]"],
  ["Disc-track", "{disctrack}"], ["Track", "{track}"], ["Title", "{title}"], ["Genre", "{genre}"], ["Folder", "/"],
];

function orgTarget() {
  const n = state.selected.size;
  if (n) return { body: { paths: [...state.selected] }, label: plural(n, "selected track"), folder: false };
  return { body: { folder: state.path, recursive: org.recursive }, label: state.path ? "this folder" : "your whole library", folder: true };
}

async function openOrganize() {
  if (!(await confirmDiscard())) return;
  try {
    org.settings = await api("GET", "/api/organize/settings");
  } catch (err) { toast(err.message, "error"); return; }
  org.pattern = org.settings.pattern;
  org.recursive = !state.folder?.tracks.length; // a folder of folders: include them
  org.preview = null;
  org.error = null;
  renderOrganize();
  openDialog($("#organize-dialog"));
  orgExample();
  orgPreview(0);
}

function orgExample() {
  clearTimeout(org.exTimer);
  org.exTimer = setTimeout(async () => {
    try { org.example = await api("POST", "/api/organize/example", { pattern: org.pattern }); } catch { org.example = null; }
    const box = $("#org-example");
    if (!box) return;
    const ex = org.example;
    setKids(box, !ex ? null : ex.ok
      ? [h("span", { class: "org-ex-label" }, "Example"), h("code", { dir: "auto" }, ex.single),
        h("code", { dir: "auto" }, ex.multi), h("span", { class: "hint" }, "Second line: a multi-disc album")]
      : h("span", { class: "org-ex-error" }, ex.error));
  }, 120);
}

function orgPreview(delay = 300) {
  clearTimeout(org.timer);
  const go = $("#org-go");
  if (go) go.disabled = true;
  org.timer = setTimeout(async () => {
    const token = ++org.token;
    try {
      const res = await api("POST", "/api/organize/preview", { ...orgTarget().body, pattern: org.pattern });
      if (token !== org.token) return;
      org.preview = res;
      org.error = null;
    } catch (err) {
      if (token !== org.token) return;
      org.preview = null;
      org.error = err.message;
    }
    renderOrganizePreview();
  }, delay);
}

function renderOrganize() {
  const target = orgTarget();
  const input = h("input", { type: "text", id: "org-pattern", value: org.pattern, spellcheck: "false", autocomplete: "off",
    autocapitalize: "off", "aria-label": "Pattern", class: "org-pattern" });
  input.addEventListener("input", () => { org.pattern = input.value; orgExample(); orgPreview(); });
  const insert = (text) => {
    const [a, b] = [input.selectionStart ?? input.value.length, input.selectionEnd ?? input.value.length];
    input.setRangeText(text, a, b, "end");
    input.focus();
    input.dispatchEvent(new Event("input"));
  };
  const presets = h("select", { "aria-label": "Start from a preset" },
    h("option", { value: "" }, "Presets…"),
    org.settings.presets.map((p) => h("option", { value: p.pattern }, p.name)));
  presets.addEventListener("change", () => {
    if (!presets.value) return;
    input.value = org.pattern = presets.value;
    presets.value = "";
    orgExample();
    orgPreview(0);
  });
  setKids($("#organize-body"),
    h("p", { class: "mb-lead" }, `Rename and move the audio files in ${target.label} into folders from their tags. You'll see every move first, nothing is ever overwritten, and it can all be undone.`),
    h("div", { class: "field" },
      h("span", { class: "field-label" }, "Pattern"),
      h("div", { class: "org-pattern-row" }, input, presets),
      h("div", { class: "org-tokens", role: "group", "aria-label": "Insert" },
        ORG_TOKENS.map(([label, text]) => h("button", { type: "button", class: "chip-btn", onclick: () => insert(text) }, label))),
      h("p", { class: "hint org-help" }, "{tag} inserts a tag · {a|b} uses the first that has a value · [ … ] disappears when a tag in it is empty · / starts a folder. The extension is added for you."),
      h("div", { class: "org-example", id: "org-example", "aria-live": "polite" })),
    target.folder && state.folder?.folders.length ? h("label", { class: "check" },
      h("input", { type: "checkbox", checked: org.recursive, onchange: (e) => { org.recursive = e.target.checked; orgPreview(0); } }),
      " Include subfolders") : null,
    h("label", { class: "check" },
      h("input", { type: "checkbox", checked: org.remember, onchange: (e) => { org.remember = e.target.checked; } }),
      " Remember this pattern"),
    h("div", { class: "preview", id: "org-preview", "aria-live": "polite" }, h("p", { class: "loading" }, "Working out where everything goes…")));
  setKids($("#organize-foot"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", id: "org-go", disabled: true, onclick: orgApply }, "Move"));
}

function renderOrganizePreview() {
  const box = $("#org-preview");
  const go = $("#org-go");
  if (!box) return;
  if (org.error) {
    setKids(box, h("div", { class: "error-box" }, org.error));
    go.disabled = true;
    return;
  }
  const p = org.preview;
  const c = p.counts;
  const moving = p.moves.filter((m) => m.status === "move");
  const problems = p.moves.filter((m) => m.status === "conflict" || m.status === "error");
  const summary = [];
  if (moving.length) summary.push(`${plural(moving.length, "file")} will move${p.extras ? `, plus ${plural(p.extras, "other file")} that come${p.extras === 1 ? "s" : ""} along (cover, lyrics, booklet…)` : ""}.`);
  else summary.push(c.same ? "Everything is already where this pattern puts it." : "Nothing to move.");
  if (c.same && moving.length) summary.push(`${plural(c.same, "file")} already in place.`);
  if (problems.length) summary.push(`${plural(problems.length, "file")} can't move (see below).`);
  const unknown = moving.filter((m) => /(^|\/)Unknown (Artist|Album)\//.test(m.dst)).length;
  const warn = unknown ? h("p", { class: "org-warn" }, `${plural(unknown, "file")} ${unknown === 1 ? "has" : "have"} no artist or album tag, so ${unknown === 1 ? "it" : "they"} would go to “Unknown Artist” / “Unknown Album”. Tag ${unknown === 1 ? "it" : "them"} first (Find in MusicBrainz can help), or move them anyway.`) : null;
  const row = (m) => h("div", { class: `org-move ${m.status}` },
    h("div", { class: "org-from", dir: "auto" }, m.src),
    h("div", { class: "org-to", dir: "auto" }, m.status === "error" ? "" : ["→ ", m.dst]),
    m.reason ? h("div", { class: "note" }, m.reason) : null,
    m.companions.length ? h("div", { class: "note" }, `+ ${m.companions.map((x) => x.src.split("/").pop()).join(", ")}`) : null);
  const shown = [...problems, ...moving].slice(0, 300);
  setKids(box,
    h("p", { class: "preview-summary" }, summary.join(" ")),
    warn,
    shown.length ? h("div", { class: "org-list" }, shown.map(row)) : null,
    shown.length < problems.length + moving.length ? h("p", { class: "hint" }, `…and ${problems.length + moving.length - shown.length} more`) : null);
  go.disabled = !moving.length;
  go.textContent = moving.length ? `Move ${plural(moving.length, "file")}` : "Move";
}

async function orgApply() {
  const go = $("#org-go");
  go.disabled = true;
  go.textContent = "Moving…";
  try {
    if (org.remember && org.pattern !== org.settings.pattern) {
      try { await api("PUT", "/api/organize/settings", { pattern: org.pattern }); } catch { /* still organize */ }
    }
    const res = await api("POST", "/api/organize/apply", { ...orgTarget().body, pattern: org.pattern });
    closeDialog($("#organize-dialog"));
    const failed = res.results.filter((r) => !r.ok);
    if (failed.length) toast(`Moved ${plural(res.moved, "file")}; ${failed.length} couldn't move: ${failed[0].error}`, "error");
    else toast(`Organized ${plural(res.moved, "file")}. Undo is in the activity log.`, "success");
    state.selected.clear();
    renderSelectionBar();
    folderCache.clear();
    refreshActivity();
    // If this folder was emptied by the move, go to where the music went.
    const first = res.results.find((r) => r.ok);
    try {
      await api("GET", `/api/browse?path=${encodeURIComponent(state.path)}`);
      await loadFolder(state.path, { keepScroll: true });
    } catch {
      navigate(first ? first.dst.split("/").slice(0, -1).join("/") : "");
    }
  } catch (err) {
    toast(err.message, "error");
    orgPreview(0);
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
    if (!(await ask({ title: `Delete “${loadout.name}”?`, message: "This loadout will be deleted. This can't be undone.",
      confirmLabel: "Delete", danger: true }))) return;
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
  state.status = status;
  if (!status.music_dir_found) {
    els.banner.replaceChildren(
      h("strong", {}, "Music folder not found"),
      "Codetta is looking for your music at ", h("code", {}, status.music_dir), ". ",
      "Set ", h("code", {}, "CODETTA_MUSIC_DIR"), " to your library, or mount it at ", h("code", {}, "/music"), " in Docker.");
    els.banner.hidden = false;
  } else if (!status.music_dir_writable) {
    els.banner.replaceChildren(
      h("strong", {}, "Read-only library"),
      "Codetta can read your music but can't save changes. Check the folder's permissions (or remove ", h("code", {}, ":ro"), " from the Docker volume).");
    els.banner.hidden = false;
  }
}

// ---- Wiring -------------------------------------------------------------------------------------------------------

function bindEvents() {
  window.addEventListener("popstate", onHistoryChange);
  window.addEventListener("hashchange", onHistoryChange); // hand-typed URLs
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const path = folderLinkPath(e);
    if (path == null) return;
    e.preventDefault();
    navigate(path);
  });
  document.addEventListener("pointerdown", (e) => prefetchFolder(folderLinkPath(e)), { passive: true });
  document.addEventListener("pointerover", (e) => { if (e.pointerType === "mouse") prefetchFolder(folderLinkPath(e)); }, { passive: true });
  window.addEventListener("beforeunload", (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });

  $("#theme-btn").addEventListener("click", () => {
    const next = THEMES[(THEMES.indexOf(getTheme()) + 1) % THEMES.length];
    setTheme(next);
    toast(THEME_LABEL[next]);
  });

  let filterTimer = null;
  els.filter.addEventListener("input", () => {
    clearTimeout(filterTimer); // redraw once typing pauses, not on every keystroke
    if (isSearch()) {
      // While searching, the box *is* the search: re-run it as you type.
      filterTimer = setTimeout(() => {
        const q = els.filter.value.trim();
        if (!q || q === searchQuery()) return;
        history.replaceState({ path: SEARCH + q }, "", hashFor(SEARCH + q));
        loadFolder(SEARCH + q);
      }, 350);
      return;
    }
    filterTimer = setTimeout(() => {
      state.filter = els.filter.value.trim();
      renderFolders();
      renderTracks();
      renderFilterChips();
    }, 120);
  });
  els.filter.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const q = els.filter.value.trim();
    if (q && !isSearch()) { e.preventDefault(); clearTimeout(filterTimer); navigate(SEARCH + q); }
  });
  els.filter.addEventListener("search", () => { // the ✕ in the search box
    if (isSearch() && !els.filter.value) navigate("");
  });

  $("#editor-close").addEventListener("click", () => closeEditor());
  $("#activity-toggle").addEventListener("click", () => {
    activity.open = !activity.open;
    try { localStorage.setItem("codetta-activity-open", activity.open ? "1" : "0"); } catch { /* ignore */ }
    renderActivity();
  });
  els.editorSave.addEventListener("click", () => saveEditor());
  els.editorSaveFolder.addEventListener("click", saveToFolder);
  $("#tagfilter-btn").addEventListener("click", openTagFilter);
  $("#filter-add").addEventListener("click", addTagFilter);
  $("#filter-search").addEventListener("click", () => {
    const key = $("#filter-key").value, value = $("#filter-value").value;
    if (!key || !value) { toast("Pick a value to search for"); return; }
    closeDialog(els.filterDialog);
    navigate(`${SEARCH}${fieldLabel(key)}: ${value}`);
  });
  els.editorForm.addEventListener("submit", (e) => { e.preventDefault(); saveEditor(); });
  // Keep "Copy tags" / "Paste" in sync when tags are copied in another tab.
  window.addEventListener("storage", (e) => {
    if (e.key === "codetta-clipboard") { state.clipboard = loadClipboard(); if (state.editor) renderToolbar(); }
  });

  $("#sel-clear").addEventListener("click", () => { state.selected.clear(); updateRowStates(); renderSelectionBar(); });
  $("#sel-edit").addEventListener("click", () => openEditor([...state.selected]));
  $("#sel-loadout").addEventListener("click", () => openApply("selection"));
  $("#manage-btn").addEventListener("click", openManage);
  const adv = $("#advanced-toggle");
  adv.checked = state.advanced;
  adv.addEventListener("change", () => { setAdvanced(adv.checked); toast(adv.checked ? "Advanced mode on" : "Advanced mode off"); });

  // Apply dialog
  const d = els.applyDialog;
  d.addEventListener("change", () => { syncApplyUi(); runPreview(); });
  $("#apply-go").addEventListener("click", doApply);

  // All dialogs: close buttons and backdrop clicks.
  for (const dialog of [els.applyDialog, els.manageDialog, els.filterDialog, $("#mb-dialog"), $("#organize-dialog"), $("#inbox-dialog"), $("#news-dialog")]) {
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

// ---- Sign in ----------------------------------------------------------------------------------------

let authMode = "login";
let appStarted = false;

function showAuth(mode, message = "") {
  authMode = mode;
  const setup = mode === "setup";
  $("#auth-title").textContent = setup ? "Create your account" : "Sign in"; // the wordmark above already says Codetta
  $("#auth-sub").textContent = setup ? "Create the account that protects your music library." : message;
  $("#auth-confirm-wrap").hidden = !setup;
  $("#auth-confirm").required = setup;
  $("#auth-pass").autocomplete = setup ? "new-password" : "current-password";
  $("#auth-pass").minLength = setup ? 8 : 0;
  $("#auth-submit").textContent = setup ? "Create account" : "Sign in";
  $("#auth-foot").textContent = setup
    ? "Use at least 8 characters. You can change it later from the account menu."
    : "Forgot your password? It can be reset on the server (see “Resetting your password” in Codetta's install guide).";
  $("#auth-error").hidden = true;
  const wasHidden = $("#auth").hidden;
  $("#auth").hidden = false;
  if (wasHidden) setTimeout(() => ($("#auth-user").value ? $("#auth-pass") : $("#auth-user")).focus(), 50);
}

async function submitAuth(e) {
  e.preventDefault();
  const user = $("#auth-user").value;
  const pass = $("#auth-pass").value;
  const err = $("#auth-error");
  const fail = (msg) => {
    err.textContent = msg;
    err.hidden = false;
    replay($("#auth"), "shake");
  };
  if (authMode === "setup" && pass !== $("#auth-confirm").value) { fail("The passwords don't match."); return; }
  const btn = $("#auth-submit");
  btn.disabled = true;
  try {
    const res = await api("POST", authMode === "setup" ? "/api/auth/setup" : "/api/auth/login", { username: user, password: pass });
    state.auth = { ...(state.auth || {}), signed_in: true, username: res.username, setup_required: false };
    try { state.auth = await api("GET", "/api/auth/status"); } catch { /* keep what we have */ }
    $("#auth-pass").value = "";
    $("#auth-confirm").value = "";
    $("#auth").hidden = true;
    if (!appStarted) await startApp();
    else { loadFolder(state.path, { keepScroll: true }); refreshActivity(); }
    if (authMode === "setup") toast(`Welcome, ${res.username}! Your library is now protected.`, "success");
  } catch (error) {
    fail(error.message);
  } finally {
    btn.disabled = false;
  }
}

// ---- Profile picture ------------------------------------------------------------------------------------

const AVATAR_SIZE = 256;

function avatarUrl() {
  const v = state.auth?.avatar;
  return v ? `/api/account/avatar?v=${v}` : null;
}

function renderAvatar() {
  const url = avatarUrl();
  const btn = $("#account-btn");
  btn.classList.toggle("has-avatar", !!url);
  setKids(btn, url ? h("img", { class: "avatar-img", src: url, alt: "" }) : icon("user"));
  const name = state.auth?.username || "";
  setKids($("#profile-avatar"), url
    ? h("img", { src: url, alt: "" })
    : h("span", { class: "avatar-initial", "aria-hidden": "true" }, (Array.from(name)[0] || "?").toUpperCase()));
  $("#avatar-remove").hidden = !url;
}

/** Decode any image the browser can read (HEIC works in Safari / on iPhone). */
async function decodeImage(file) {
  if (window.createImageBitmap) {
    try { return await createImageBitmap(file, { imageOrientation: "from-image" }); } catch { /* try <img> */ }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

/** Crop to a centred square, scale to 256px and upload as WebP (or JPEG). */
async function uploadAvatar(file) {
  const looksHeic = /image\/hei[cf]/i.test(file.type) || /\.(heic|heif)$/i.test(file.name);
  if (file.size > 60 * 1024 * 1024) { toast("That image is too large", "error"); return; }
  let image;
  try {
    image = await decodeImage(file);
  } catch {
    toast(looksHeic
      ? "This browser can't open HEIC photos. Save it as JPEG first, or use Safari (or any browser on an iPhone)."
      : "That file isn't an image Codetta can open. Try JPEG, PNG or WebP.", "error");
    return;
  }
  const w = image.width || image.naturalWidth, h0 = image.height || image.naturalHeight;
  const side = Math.min(w, h0);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = AVATAR_SIZE;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(image, (w - side) / 2, (h0 - side) / 2, side, side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
  let blob = await canvasToBlob(canvas, "image/webp", 0.9);
  if (!blob || blob.type !== "image/webp") blob = await canvasToBlob(canvas, "image/jpeg", 0.9); // older Safari
  try {
    const res = await fetch("/api/account/avatar", { method: "PUT", body: blob, headers: { "Content-Type": blob.type } });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error((data && data.detail) || `Upload failed (${res.status})`);
    state.auth.avatar = data.avatar;
    renderAvatar();
    toast("Profile picture updated", "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function removeAvatar() {
  try {
    await api("DELETE", "/api/account/avatar");
    state.auth.avatar = null;
    renderAvatar();
    toast("Profile picture removed", "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

function openAccount() {
  renderAvatar();
  renderAbout();
  if (!state.update) refreshUpdate();
  renderConnections();
  loadConnections().then(renderConnections); // pick up changes from other devices
  const a = state.auth || {};
  // With sign-in off (behind a proxy that handles it) this is just Settings.
  const signedIn = !!a.auth_enabled;
  $("#account-title").textContent = signedIn ? "Account" : "Settings";
  $(".profile").hidden = !signedIn;
  $("#sign-out").hidden = !signedIn;
  $("#account-name").textContent = a.username || "";
  $("#pw-username").value = a.username || "";
  $("#password-form").hidden = !signedIn || !!a.managed_by_env;
  $("#pw-env-note").hidden = !signedIn || !a.managed_by_env;
  $("#pw-error").hidden = true;
  openDialog($("#account-dialog"));
}

async function changePassword(e) {
  e.preventDefault();
  const err = $("#pw-error");
  const next = $("#pw-new").value;
  if (next !== $("#pw-confirm").value) { err.textContent = "The new passwords don't match."; err.hidden = false; return; }
  try {
    await api("POST", "/api/auth/password", { current_password: $("#pw-current").value, new_password: next });
    for (const id of ["#pw-current", "#pw-new", "#pw-confirm"]) $(id).value = "";
    closeDialog($("#account-dialog"));
    toast("Password changed. Your other devices were signed out.", "success");
  } catch (error) {
    err.textContent = error.message;
    err.hidden = false;
  }
}

async function signOut() {
  if (isDirty() && !(await ask({ title: "Sign out?", message: "Your unsaved tag changes will be lost.",
    confirmLabel: "Sign out", danger: true }))) return;
  try { await api("POST", "/api/auth/logout"); } catch { /* signing out anyway */ }
  state.editor = null; // already confirmed; don't ask again on unload
  location.reload(); // fresh start: the page comes back on the sign-in screen
}

async function boot() {
  applyTheme(getTheme());
  bindEvents();
  $("#auth-form").addEventListener("submit", submitAuth);
  $("#welcome-form").addEventListener("submit", submitWelcome);
  $("#conn-toggle").addEventListener("click", () => setConnectionsOpen($("#conn-body").hidden));
  $("#inbox-btn").addEventListener("click", openInbox);
  document.addEventListener("click", (e) => { if (e.target.closest("[data-news]")) openNews(); });
  for (const r of document.querySelectorAll('input[name="welcome-mode"]')) r.addEventListener("change", welcomeModeChanged);
  $("#account-btn").addEventListener("click", openAccount);
  $("#password-form").addEventListener("submit", changePassword);
  $("#sign-out").addEventListener("click", signOut);
  $("#check-updates").addEventListener("click", () => refreshUpdate(true));
  const pickAvatar = () => $("#avatar-file").click();
  $("#profile-avatar").addEventListener("click", pickAvatar);
  $("#avatar-change").addEventListener("click", pickAvatar);
  $("#avatar-remove").addEventListener("click", removeAvatar);
  $("#avatar-file").addEventListener("change", (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (f) uploadAvatar(f);
  });
  const accountDialog = $("#account-dialog");
  accountDialog.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]") || e.target === accountDialog) closeDialog(accountDialog);
  });
  accountDialog.addEventListener("cancel", (e) => { e.preventDefault(); closeDialog(accountDialog); });

  try {
    state.auth = await api("GET", "/api/auth/status");
  } catch (err) {
    toast(`Can't reach the Codetta server: ${err.message}`, "error");
    return;
  }
  showVersion(state.auth.version);
  if (state.auth.auth_enabled && !state.auth.signed_in) {
    showAuth(state.auth.setup_required ? "setup" : "login");
    return;
  }
  await startApp();
}

// ---- Version & updates -------------------------------------------------------------------------------

function showVersion(version) {
  if (!version) return;
  for (const el of document.querySelectorAll("[data-version]")) el.textContent = `v${version}`;
  $(".brand").title = `Codetta v${version}`;
  $("#about-version").textContent = `v${version}`;
}

async function refreshUpdate(force = false) {
  const btn = $("#check-updates");
  if (force) { btn.disabled = true; btn.textContent = "Checking…"; }
  try {
    state.update = await api("GET", `/api/update${force ? "?force=true" : ""}`);
  } catch {
    /* offline or signed out: try again later */
  } finally {
    btn.disabled = false;
    btn.textContent = "Check for updates";
  }
  const available = !!state.update?.update_available;
  $("#account-btn").classList.toggle("has-update", available);
  $("#account-btn").title = available ? `Account · Codetta ${state.update.latest} is available` : "Account";
  renderAbout();
}

const UPDATE_STEPS = "cd /path/to/codetta\ndocker compose pull\ndocker compose up -d";

function renderAbout() {
  const u = state.update;
  const status = $("#update-status");
  const box = $("#update-box");
  box.hidden = true;
  const checked = u?.checked_at ? ` (checked ${new Date(u.checked_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })})` : "";
  $("#check-updates").hidden = !!u && !u.enabled;
  if (!u) {
    status.textContent = "";
  } else if (!u.enabled) {
    status.textContent = "Update checks are off. Turn on “Update check” under Connections to hear about new versions.";
  } else if (u.error) {
    status.textContent = `Couldn't check for updates: ${u.error}.`;
  } else if (u.note) {
    status.textContent = `${u.note}${checked}.`;
  } else if (u.update_available) {
    setKids(status, h("b", {}, `Version ${u.latest} is available.`), " ",
      u.release_url ? h("a", { href: u.release_url, target: "_blank", rel: "noopener" }, "What's new") : null);
    const notes = (u.notes || "").trim();
    setKids(box,
      notes ? h("div", { class: "release-notes" }, notes) : null,
      h("p", { class: "hint", style: "margin:0 0 6px" }, "To update, run this on your server (use your Codetta folder's path):"),
      h("pre", { class: "update-steps" }, UPDATE_STEPS),
      h("button", { class: "btn small", type: "button", onclick: () => copyText(UPDATE_STEPS) }, icon("copy"), "Copy commands"),
      h("p", { class: "hint", style: "margin:8px 0 0" }, "Your account, loadouts and activity log are kept."));
    box.hidden = false;
  } else {
    status.textContent = `You're up to date${checked}.`;
  }
}

/** Copy text; works over plain http too (navigator.clipboard needs https). */
async function copyText(text) {
  try {
    if (window.isSecureContext && navigator.clipboard) await navigator.clipboard.writeText(text);
    else {
      const area = h("textarea", { style: "position:fixed;opacity:0", readonly: true });
      area.value = text;
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    toast("Copied", "success");
  } catch {
    toast("Couldn't copy. Select the text and copy it instead.", "error");
  }
}

async function startApp() {
  appStarted = true;
  $("#app").hidden = false;
  $("#account-btn").hidden = false; // with sign-in off it opens Settings (connections, advanced mode)
  if (!state.auth?.auth_enabled) { $("#account-btn").title = "Settings"; $("#account-btn").setAttribute("aria-label", "Settings"); }
  renderAvatar();
  try {
    const [status, fields] = await Promise.all([api("GET", "/api/status"), api("GET", "/api/fields")]);
    state.fields = fields.fields;
    state.fieldMap = new Map(fields.fields.map((f) => [f.key, f]));
    state.placeholders = fields.placeholders;
    $("#tag-keys").replaceChildren(...fields.fields.map((f) => h("option", { value: f.key }, f.label)));
    showStatus(status);
  } catch (err) {
    toast(`Can't reach the Codetta server: ${err.message}`, "error");
  }
  // First run (or first start after an update that adds a setup step).
  runSetup();
  await loadFolder(pathFromHash());
  refreshActivity();
  startActivityPolling();
  // Check for a new release in the background (and twice a day if left open),
  // only if the user turned the update check on.
  setTimeout(() => refreshUpdate(), 1500);
  setInterval(() => refreshUpdate(), 12 * 3600 * 1000);
}

boot();
