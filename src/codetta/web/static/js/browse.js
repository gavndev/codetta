// Routing, browsing folders, the tag filter and selection.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, closeDialog, h, icon, openDialog, playOut, replay, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, first, plural, state, toast } from "./state.js";
import { updateSpot } from "./theme.js";
import { bang, filterPlaceholder, roll, selectButtons, showMbLoading, syncRoll } from "./search.js";
import { openToolsMenu, renderFolderHead, renderFolders, renderTracks } from "./tools.js";
import { closeEditor, confirmDiscard, fieldLabel, listParts, renderEditor } from "./editor.js";
import { connectionOn } from "./setup.js";
import { openMusicBrainz } from "./musicbrainz.js";

// ---- Routing ------------------------------------------------------------------------------------

// Library-wide search is shown like a folder whose "path" is SEARCH + the query.
// Real paths can never contain a NUL character (the server refuses them), so the
// two can't collide. Its URL is "#?q=genre%3A%20rap".
export const SEARCH = "\0";
const isSearchKey = (key) => typeof key === "string" && key.startsWith(SEARCH);
// MusicBrainz pages (the !mb bang) are "paths" too: MBX + "search:<q>" | "artist:<id>" | "rg:<id>".
// URLs: "#mb?q=…", "#mb/artist/<id>", "#mb/rg/<id>".
export const MBX = "\x01";
const isMbKey = (key) => typeof key === "string" && key.startsWith(MBX);
export const mbKey = (key) => { const [kind, ...rest] = key.slice(1).split(":"); return { kind, value: rest.join(":") }; };
export const isSearch = () => isSearchKey(state.path);
export const searchQuery = (key = state.path) => (isSearchKey(key) ? key.slice(1) : "");

export function pathFromHash(hash = location.hash) {
  if (hash.startsWith("#mb?")) {
    const q = (new URLSearchParams(hash.slice(4)).get("q") || "").trim();
    return q ? MBX + "search:" + q : "";
  }
  const m = /^#mb\/(artist|rg)\/([0-9a-f-]{36})$/i.exec(hash);
  if (m) return MBX + m[1].toLowerCase() + ":" + m[2].toLowerCase();
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

export function hashFor(path) {
  if (isSearchKey(path)) return "#?q=" + encodeURIComponent(searchQuery(path));
  if (isMbKey(path)) {
    const { kind, value } = mbKey(path);
    return kind === "search" ? "#mb?q=" + encodeURIComponent(value) : `#mb/${kind}/${value}`;
  }
  return "#/" + path.split("/").filter(Boolean).map(encodeURIComponent).join("/");
}

// Folder links are handled in-page with the History API (pushState) rather
// than by letting the browser follow "#/..." links. Same URLs, so bookmarks
// and back/forward still work, but browsers such as Brave on iOS no longer
// treat every folder tap as a page load (loading bar, reload icon).
let navTarget = null; // the folder we're currently heading to

export async function navigate(path) {
  if (path === (navTarget ?? state.path) && state.folder) return;
  if (!(await confirmDiscard())) return;
  navTarget = path;
  history.pushState({ path }, "", hashFor(path));
  loadFolder(path);
}

/** Back/forward buttons, or a hand-edited URL. */
export async function onHistoryChange() {
  const path = pathFromHash();
  if (path === (navTarget ?? state.path) && state.folder) return;
  if (!(await confirmDiscard())) {
    history.pushState({ path: state.path }, "", hashFor(state.path)); // stay put
    return;
  }
  navTarget = path;
  loadFolder(path);
}

export function folderLinkPath(event) {
  const a = event.target.closest?.('a[href^="#/"], a[href^="#?"], a[href^="#mb"]');
  if (!a || !a.closest("#app")) return null;
  return pathFromHash(a.getAttribute("href"));
}

// ---- Browsing --------------------------------------------------------------------------------------

// Folders you've visited are remembered, so going back is instant. Each visit
// still asks the server for fresh data in the background and only redraws if
// something actually changed (e.g. edited on another device).
export const folderCache = new Map();   // folder path -> /api/browse response
const scrollMemory = new Map();  // folder path -> scroll position
const MAX_CACHED_FOLDERS = 60;

function rememberFolder(data) {
  folderCache.delete(data.path);
  folderCache.set(data.path, data);
  if (folderCache.size > MAX_CACHED_FOLDERS) folderCache.delete(folderCache.keys().next().value);
}

const inflight = new Map(); // folder path -> pending /api/browse request

function fetchMb(path) {
  const { kind, value } = mbKey(path);
  const crumbs = [{ name: "Library", path: "" }];
  const wrap = (mb, name, extra = []) => ({ path, name, breadcrumbs: [...crumbs, ...extra, { name, path }],
    folders: [], tracks: [], skipped: 0, mb: { kind, ...mb } });
  if (kind === "search") {
    return api("GET", `/api/mb/search?q=${encodeURIComponent(value)}`).then((d) => wrap(d, `MusicBrainz: ${value}`));
  }
  if (kind === "artist") return api("GET", `/api/mb/artist/${value}`).then((d) => wrap(d, d.name));
  return api("GET", `/api/mb/release-group/${value}`).then((d) => wrap(d, d.title,
    d.artist_id ? [{ name: d.artist, path: MBX + "artist:" + d.artist_id }] : []));
}

function fetchFolder(path) {
  if (!inflight.has(path)) {
    const req = (isMbKey(path) ? fetchMb(path) : isSearchKey(path)
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
export function prefetchFolder(path) {
  if (isMbKey(path)) return; // MusicBrainz allows one request a second: only fetch what's opened
  if (path == null || folderCache.has(path) || inflight.has(path)) return;
  fetchFolder(path).then(rememberFolder, () => { /* ignore; the real visit will report errors */ });
}

export async function loadFolder(path, { keepScroll = false } = {}) {
  const token = ++state.loadToken;
  const navigating = !state.folder || path !== state.path;
  if (state.folder && navigating) scrollMemory.set(state.path, els.browser.scrollTop);

  const cached = navigating ? folderCache.get(path) : null;
  if (keepScroll) inflight.delete(path); // a refresh after a change: never reuse a request from before it
  let loadingTimer = null;
  if (!cached && navigating && isMbKey(path)) {
    // MusicBrainz takes a few seconds (one request a second): say so instead of a frozen page.
    showMbLoading(path);
  } else if (cached) {
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
    for (const el of [els.folderHead, els.folders, els.tracks]) {
      replay(el, cls);
      // Only the arrival animates: rows redrawn later (filtering, saving) appear without a ripple.
      clearTimeout(el.navTimer);
      el.navTimer = setTimeout(() => el.classList.remove(cls), 700);
    }
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
  document.title = data.mb ? `${data.name} — Codetta` : isSearchKey(data.path) ? `${searchQuery(data.path)} — Search — Codetta`
    : data.path ? `${data.name} — Codetta` : "Codetta";
  if (!bang.kind) els.filter.placeholder = roll.on ? "" : filterPlaceholder();
  syncRoll();
  renderBrowser();
  els.browser.scrollTop = scrollTop;
  updateSpot();
}

// Lookups by path / cover, built once per folder instead of scanning every time
// (matters for folders with thousands of tracks).
export const index = { folder: null, count: -1, byPath: new Map(), firstWithArt: new Map() };

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

export function trackByPath(path) {
  const i = folderIndex().byPath.get(path);
  return i === undefined ? undefined : state.folder.tracks[i];
}

/** Replace a track's data after a save (keeps the index valid). */
export function replaceTrack(track) {
  const i = folderIndex().byPath.get(track.path);
  if (i !== undefined) state.folder.tracks[i] = track;
}

/** Case- and accent-insensitive form for searching: "Beyoncé" -> "beyonce". */
export function fold(text) {
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
export function discInfo(f = state.folder) {
  if (!f || f.search) return null;
  if (discCache.has(f)) return discCache.get(f);
  const readable = f.tracks.filter((t) => !t.error);
  const discOf = (t) => parseInt(first(t, "discnumber"), 10);
  const info = readable.length && readable.every((t) => Number.isInteger(discOf(t))) && new Set(readable.map(discOf)).size > 1
    ? { discOf } : null;
  discCache.set(f, info);
  return info;
}

const trackNum = (t) => parseInt(first(t, "tracknumber"), 10);

/** A single-disc album in track-number order: every track numbered, no number twice. Folders
 * of loose files (all "1", or some unnumbered) keep their file-name order. */
const numberedCache = new WeakMap();
function numberedAlbum(f = state.folder) {
  if (!f || f.search || f.mb) return false;
  if (numberedCache.has(f)) return numberedCache.get(f);
  const nums = f.tracks.filter((t) => !t.error).map(trackNum);
  const yes = nums.length > 1 && nums.every(Number.isInteger) && new Set(nums).size === nums.length;
  numberedCache.set(f, yes);
  return yes;
}

export function visibleTracks() {
  const tracks = (state.folder?.tracks || []).filter(matchesFilter);
  const discs = discInfo();
  if (!discs && !numberedAlbum()) return tracks;
  // By disc, then track number (the tags, not the file names: a MusicBrainz match can renumber
  // tracks); files without numbers keep their place within the disc.
  const order = new Map(tracks.map((t, i) => [t, i]));
  const discOf = discs ? discs.discOf : () => 0;
  const key = (t) => [t.error ? Infinity : discOf(t), Number.isInteger(trackNum(t)) ? trackNum(t) : Infinity, order.get(t)];
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
      translate: i && !c.name.startsWith("Search: ") ? "no" : null, // folder names are the user's
    }, c.name));
  });
  els.crumbs.replaceChildren(...parts);
  els.crumbs.scrollLeft = els.crumbs.scrollWidth; // show the deepest part on phones
}

export function renderSearchHead(f) {
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
      selectButtons(f)),
  );
  els.tracks.classList.toggle("selecting", state.selectMode);
}

/** "Find in MusicBrainz" ("Find" on phones), shown when the MusicBrainz connection is on. */
/** Find in MusicBrainz, with a chevron for Deezer and iTunes when they're on (a split button). */
export function mbFindButton(where) {
  const mbOn = connectionOn("musicbrainz");
  const others = [["deezer", "Find in Deezer"], ["itunes", "Find in iTunes"]].filter(([s]) => connectionOn(s));
  const main = h("button", {
    class: "mb-find-inner", type: "button", onclick: () => openMusicBrainz(),
    "aria-label": mbOn ? "Find in MusicBrainz" : "Find album details",
    title: mbOn ? "Find this album on MusicBrainz and review its tags before writing them" : "Find this album's details and review them before writing",
  }, icon("musicbrainz"),
  h("span", { class: "mb-find-long" }, mbOn ? "Find in MusicBrainz" : "Find album details"), h("span", { class: "mb-find-short" }, "Find"));
  const more = others.length ? h("button", {
    class: "mb-find-more", type: "button", "aria-label": "Find somewhere else", "aria-haspopup": "menu", title: "Find in Deezer or iTunes instead",
    onclick: (e) => openToolsMenu(e.currentTarget, [
      mbOn ? { icon: "musicbrainz", label: "Find in MusicBrainz", run: () => openMusicBrainz() } : null,
      ...others.map(([s, label]) => ({ icon: s, label, run: () => openMusicBrainz({ source: s }) })),
    ].filter(Boolean)),
  }, icon("chevron")) : null;
  return h("span", { class: `mb-find ${where}${more ? " split" : ""}` }, main, more);
}

// ---- Tag filter ---------------------------------------------------------------------------------------

export function renderFilterChips() {
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

export function openTagFilter() {
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

export function addTagFilter() {
  const key = $("#filter-key").value;
  const value = $("#filter-value").value;
  if (!key) return;
  state.tagFilters = state.tagFilters.filter((f) => f.key !== key); // one value per tag
  state.tagFilters.push({ key, value });
  closeDialog(els.filterDialog);
  renderBrowser();
}

// ---- Selection -----------------------------------------------------------------------------------

export function toggleSelect(path, checked, shift) {
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

export function selectAll(checked) {
  for (const t of visibleTracks()) checked ? state.selected.add(t.path) : state.selected.delete(t.path);
  updateRowStates();
  renderSelectionBar();
}

export function updateRowStates() {
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

export function renderSelectionBar() {
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
