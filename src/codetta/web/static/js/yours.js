// Your music: favourites, most and recently played, and playlists, shown like folders so playing,
// selecting and editing work as everywhere else. The same stars, plays and playlists your music apps
// see (kept by the server in listening.sqlite3); nothing here changes your files.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, plural, state, toast } from "./state.js";
import { YOURS, folderCache, hashFor, loadFolder, navigate } from "./browse.js";
import { openToolsMenu, renderFolderHead, renderTracks } from "./tools.js";

export const yoursKey = (view = "", id = "") => YOURS + (view === "playlist" ? `playlist:${id}` : view);
const parse = (key) => { const [view, id] = key.slice(1).split(":"); return { view: view || "", id: Number(id) || 0 }; };
const crumbs = () => [{ name: "Library", path: "" }, { name: "Your music", path: YOURS }]; // a function: YOURS isn't there yet while modules load

/** The folder-shaped answer browse.js shows for a Your music "path". */
export async function fetchYours(path) {
  const { view, id } = parse(path);
  if (!view) {
    const d = await api("GET", "/api/yours");
    yours.summary = d;
    return { path, name: "Your music", breadcrumbs: crumbs(), folders: [], tracks: [], skipped: 0, yours: { view: "", ...d } };
  }
  const d = await api("GET", `/api/yours?view=${encodeURIComponent(view)}${view === "playlist" ? `&id=${id}` : ""}`);
  return { path, name: d.name, breadcrumbs: [...crumbs(), { name: d.name, path }], folders: [], tracks: d.tracks, skipped: 0,
    yours: { view, id, plays: d.plays, starred: d.starred } };
}

export const yours = { summary: null };

async function summary() {
  if (!yours.summary) {
    try { yours.summary = await api("GET", "/api/yours"); } catch { yours.summary = { starred: 0, played: 0, playlists: [] }; }
  }
  return yours.summary;
}

/** Something changed: forget what's cached, and redraw if Your music is on screen. */
function changed(d) {
  if (d && d.playlists) yours.summary = d;
  for (const key of [...folderCache.keys()]) if (key.startsWith(YOURS)) folderCache.delete(key);
  if (state.path.startsWith(YOURS)) loadFolder(state.path, { keepScroll: true });
}

// ---- The head and the overview ---------------------------------------------------------------------

export function yoursHead(f) {
  const y = f.yours;
  if (!y.view) {
    return h("div", { class: "yours-head" },
      h("h1", {}, "Your music"),
      h("p", {}, "Favourites, plays and playlists, shared with your music apps."));
  }
  const n = f.tracks.length;
  const tools = [];
  if (y.view === "playlist") {
    if (ro.id !== y.id) ro.on = false; // another playlist: reordering starts off
    const filtered = !!state.filter || state.tagFilters.length > 0;
    tools.push(h("button", { class: `btn${ro.on ? " primary" : ""}`, type: "button", disabled: n < 2 || (filtered && !ro.on),
      title: filtered ? "Clear the search box and tag filter to reorder" : "Drag songs into a new order",
      onclick: () => { ro.on = !ro.on; ro.id = y.id; renderFolderHead(); renderTracks(); } }, icon("grip"), ro.on ? "Done" : "Reorder"));
    tools.push(h("button", { class: "btn", type: "button", onclick: () => renamePlaylist(y.id, f.name) }, icon("rename"), "Rename"),
      h("button", { class: "btn danger", type: "button", onclick: () => deletePlaylist(y.id, f.name) }, icon("trash"), "Delete"));
  }
  return h("div", { class: "yours-head" },
    h("h1", { dir: "auto" }, f.name),
    h("p", {}, n ? plural(n, "song") : y.view === "starred" ? "No favourites yet. Select songs and use Add to… → Favourites."
      : y.view === "playlist" ? "This playlist is empty. Select songs anywhere and use Add to…" : "Nothing played yet."),
    tools.length ? h("div", { class: "yours-tools" }, tools) : null);
}

/** The overview: three lists, then every playlist with the cover of its first song. */
export function renderYoursBody(f) {
  const y = f.yours;
  const tile = (view, label, ico, sub) => h("a", { class: "yours-tile", href: hashFor(yoursKey(view)), "data-path": yoursKey(view) },
    h("span", { class: "yours-ico", "data-kind": view }, icon(ico)), h("span", { class: "folder-text" },
      h("span", { class: "folder-name" }, label), h("span", { class: "folder-meta" }, sub)));
  setKids(els.folders,
    h("div", { class: "yours-tiles" },
      tile("starred", "Favourites", "heart", plural(y.starred, "song")),
      tile("most", "Most played", "pulse", y.played ? "Your top 100" : "Nothing yet"),
      tile("recent", "Recently played", "undo", y.played ? "The last 100" : "Nothing yet")),
    h("div", { class: "yours-pl-head" }, h("h2", {}, "Playlists"),
      h("button", { class: "btn small", type: "button", onclick: () => newPlaylist([]) }, icon("plus"), "New playlist")),
    y.playlists.length ? h("div", { class: "yours-playlists" }, y.playlists.map((p) => h("a", {
      class: "folder yours-pl", href: hashFor(yoursKey("playlist", p.id)), "data-path": yoursKey("playlist", p.id) },
    h("span", { class: "folder-cover" }, p.first
      ? h("img", { src: `/api/art?path=${encodeURIComponent(p.first)}`, alt: "", loading: "lazy", decoding: "async",
        onerror: (e) => e.currentTarget.replaceWith(icon("note")) }) : icon("note")),
    h("span", { class: "folder-text" }, h("span", { class: "folder-name", dir: "auto" }, p.name),
      h("span", { class: "folder-meta" }, plural(p.tracks, "song"))))))
      : h("p", { class: "hint yours-empty" }, "No playlists yet. Make one here, or in any music app connected to Codetta."));
}

// ---- Adding to favourites and playlists ------------------------------------------------------------

async function newPlaylist(paths) {
  const input = h("input", { type: "text", maxlength: "200", value: "", placeholder: "Road trip", autocomplete: "off" });
  setTimeout(() => input.focus(), 80);
  if (!await ask({ title: "New playlist", details: h("label", { class: "field" }, h("span", { class: "field-label" }, "Name"), input),
    confirmLabel: paths.length ? `Make it with ${plural(paths.length, "song")}` : "Make it" })) return;
  try {
    const d = await api("POST", "/api/playlists", { name: input.value.trim() || "New playlist", paths });
    toast(`Made “${input.value.trim() || "New playlist"}”`, "success");
    changed(d);
    if (!paths.length) navigate(yoursKey("playlist", d.id));
  } catch (err) { toast(err.message, "error"); }
}

async function renamePlaylist(id, name) {
  const input = h("input", { type: "text", maxlength: "200", value: name, autocomplete: "off" });
  setTimeout(() => { input.focus(); input.select(); }, 80);
  if (!await ask({ title: "Rename playlist", details: h("label", { class: "field" }, h("span", { class: "field-label" }, "Name"), input),
    confirmLabel: "Rename" }) || !input.value.trim()) return;
  try { changed(await api("PUT", `/api/playlists/${id}`, { name: input.value.trim() })); } catch (err) { toast(err.message, "error"); }
}

async function deletePlaylist(id, name) {
  if (!await ask({ title: `Delete “${name}”?`, message: "The playlist goes, in Codetta and your music apps. The songs stay in your library.",
    confirmLabel: "Delete playlist", danger: true })) return;
  try {
    changed(await api("DELETE", `/api/playlists/${id}`));
    toast(`Deleted “${name}”`);
    navigate(YOURS);
  } catch (err) { toast(err.message, "error"); }
}

/** The selection bar's "Add to…": favourites, a playlist, a new one; in a list, take songs out of it. */
export async function openAddTo(anchor) {
  const paths = [...state.selected];
  if (!paths.length) return;
  const s = await summary();
  const y = state.folder?.yours;
  const allStarred = y && (y.starred || []).length && paths.every((p) => y.starred.includes(p));
  const run = async (fn, done) => {
    try { const d = await fn(); toast(done, "success"); changed(d); } catch (err) { toast(err.message, "error"); }
  };
  openToolsMenu(anchor, [
    allStarred || y?.view === "starred"
      ? { icon: "heart", label: "Remove from favourites", run: () => run(() => api("POST", "/api/yours/star", { paths, on: false }), `Took ${plural(paths.length, "song")} out of favourites`) }
      : { icon: "heart", label: "Favourites", run: () => run(() => api("POST", "/api/yours/star", { paths, on: true }), `Added ${plural(paths.length, "song")} to favourites`) },
    y?.view === "playlist" ? { icon: "close", label: "Remove from this playlist", group: "This playlist",
      run: () => run(() => api("PUT", `/api/playlists/${y.id}`, { remove: paths }), `Took ${plural(paths.length, "song")} out`) } : null,
    ...s.playlists.filter((p) => !(y?.view === "playlist" && p.id === y.id)).map((p) => ({ icon: "note", label: p.name, group: "Playlists",
      run: () => run(() => api("PUT", `/api/playlists/${p.id}`, { add: paths }), `Added ${plural(paths.length, "song")} to “${p.name}”`) })),
    { icon: "plus", label: "New playlist…", group: "Playlists", run: () => newPlaylist(paths) },
  ].filter(Boolean));
}

// ---- The pill at the bottom of a phone's screen ------------------------------------------------------

export function syncTabbar() {
  const bar = $("#tabbar");
  if (!bar) return;
  const at = state.path.startsWith(YOURS) ? "yours" : "library";
  for (const b of bar.querySelectorAll("[data-tab]")) {
    b.classList.toggle("active", b.dataset.tab === at);
    b.setAttribute("aria-current", b.dataset.tab === at ? "page" : "false");
  }
  const count = $("#inbox-count");
  const mirror = $("#tab-inbox-count");
  if (count && mirror) { mirror.hidden = count.hidden; mirror.textContent = count.textContent; }
}

export function setupYours() {
  $("#tab-library").addEventListener("click", () => navigate(""));
  $("#tab-yours").addEventListener("click", () => navigate(YOURS));
  $("#yours-btn").addEventListener("click", () => navigate(YOURS));
  $("#tab-inbox").addEventListener("click", () => $("#inbox-btn").click());
  $("#sel-add").addEventListener("click", (e) => openAddTo(e.currentTarget));
  // The inbox count lives on the top bar's button; the pill shows the same number.
  const count = $("#inbox-count");
  if (count) new MutationObserver(syncTabbar).observe(count, { attributes: true, childList: true, characterData: true, subtree: true });
  syncTabbar();
}

// ---- Reordering a playlist: drag a song by its grip (mouse or finger), or use the arrow keys -----------

const ro = { on: false, id: 0 };

export const reordering = () => ro.on && state.folder?.yours?.view === "playlist" && state.folder.yours.id === ro.id
  && !state.filter && !state.tagFilters.length;

const songRows = () => [...els.tracks.querySelectorAll(".track-row:not(.head)")];

/** The grip that takes the play button's place while reordering (null otherwise). */
export function reorderGrip(t) {
  if (!reordering()) return null;
  const grip = h("button", { class: "reorder-grip", type: "button", "aria-label": `Move “${t.tags?.title?.[0] || t.name}”`,
    title: "Drag to move it (or use the arrow keys)" }, icon("grip"));
  grip.addEventListener("pointerdown", (e) => startDrag(e, grip));
  grip.addEventListener("click", (e) => e.stopPropagation());
  grip.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault(); e.stopPropagation();
    const from = songRows().indexOf(grip.closest(".track-row"));
    const to = from + (e.key === "ArrowUp" ? -1 : 1);
    if (from < 0 || to < 0 || to >= state.folder.tracks.length) return;
    commit(from, to, true);
  });
  return grip;
}

function startDrag(e, grip) {
  if (e.button !== 0) return;
  e.preventDefault();
  const row = grip.closest(".track-row");
  const rows = songRows();
  const from = rows.indexOf(row);
  if (from < 0) return;
  const rects = rows.map((r) => r.getBoundingClientRect()); // where everything was when the drag began
  const mids = rects.map((r) => r.top + r.height / 2);
  const step = rows.length > 1 ? rects[1].top - rects[0].top : rects[from].height; // rows are all one height
  const scroller = els.browser;
  const scroll0 = scroller.scrollTop;
  const y0 = e.clientY;
  let y = y0, to = from, frame = 0;
  row.classList.add("dragging");
  els.tracks.classList.add("drag-active");
  grip.setPointerCapture(e.pointerId);
  const update = () => {
    const dy = y - y0 + (scroller.scrollTop - scroll0);
    row.style.setProperty("transform", `translateY(${dy}px)`);
    const mid = mids[from] + dy;
    to = from;
    for (let i = 0; i < rows.length; i++) {
      if (i < from && mid < mids[i]) to = Math.min(to, i);
      if (i > from && mid > mids[i]) to = Math.max(to, i);
    }
    rows.forEach((r, i) => {
      if (i === from) return;
      const shift = from < to && i > from && i <= to ? -step : from > to && i >= to && i < from ? step : 0;
      r.style.setProperty("transform", shift ? `translateY(${shift}px)` : "");
    });
  };
  // Near the top or bottom of the list: scroll, faster the closer the finger gets to the edge.
  const edge = () => {
    const box = scroller.getBoundingClientRect();
    const zone = 80;
    const top = Math.max(box.top, 0) + zone, bottom = Math.min(box.bottom, window.innerHeight) - zone - 60;
    const v = y < top ? -(top - y) / 5 : y > bottom ? (y - bottom) / 5 : 0;
    if (v) { scroller.scrollTop += v; update(); }
    frame = requestAnimationFrame(edge);
  };
  frame = requestAnimationFrame(edge);
  const move = (ev) => { y = ev.clientY; update(); };
  const end = () => {
    cancelAnimationFrame(frame);
    grip.removeEventListener("pointermove", move);
    grip.removeEventListener("pointerup", end);
    grip.removeEventListener("pointercancel", end);
    for (const r of rows) r.style.removeProperty("transform");
    row.classList.remove("dragging");
    els.tracks.classList.remove("drag-active");
    if (to !== from) commit(from, to, false);
  };
  grip.addEventListener("pointermove", move);
  grip.addEventListener("pointerup", end);
  grip.addEventListener("pointercancel", end);
}

/** Move song ``from`` to place ``to``: on screen at once, then saved (the same order music apps see). */
async function commit(from, to, keyboard) {
  const f = state.folder;
  const tracks = f.tracks;
  const [moved] = tracks.splice(from, 1);
  tracks.splice(to, 0, moved);
  f.positions = null; // the numbers follow
  renderTracks();
  if (keyboard) songRows()[to]?.querySelector(".reorder-grip")?.focus();
  try {
    const d = await api("PUT", `/api/playlists/${f.yours.id}`, { order: tracks.map((t) => t.path) });
    yours.summary = d;
    for (const key of [...folderCache.keys()]) if (key.startsWith(YOURS) && key !== state.path) folderCache.delete(key);
  } catch (err) {
    toast(err.message, "error");
    changed(); // show the playlist as it really is now
  }
}
