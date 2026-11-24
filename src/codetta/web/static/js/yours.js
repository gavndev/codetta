// Your music: favourites, most and recently played, and playlists, shown like folders so playing,
// selecting and editing work as everywhere else. The same stars, plays and playlists your music apps
// see (kept by the server in listening.sqlite3); nothing here changes your files.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, plural, state, toast } from "./state.js";
import { YOURS, folderCache, hashFor, loadFolder, navigate } from "./browse.js";
import { openToolsMenu } from "./tools.js";

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
