// The search bar: exploring MusicBrainz (!mb), bangs and rolling search ideas.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, closeDialog, h, icon, openDialog, playOut, replay, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, first, plural, state, toast } from "./state.js";
import {
  folderCache, hashFor, isSearch, loadFolder, mbKey, MBX, navigate, renderFilterChips,
} from "./browse.js";
import {
  allVisibleSelected, folderCovers, renderFolderHead, renderFolders, renderTracks, setSelectMode,
  toggleSelectAllVisible,
} from "./tools.js";
import { refreshActivity } from "./activity.js";
import {
  applyConnections, connectionOn, finishStep, setConnectionsOpen, setupLogo, stepCount,
} from "./setup.js";
import { mbMeta, mbThumb, openMusicBrainzFor } from "./musicbrainz.js";
import {
  etaText, loadSlskd, progressBar, refreshInboxBadge, sk, SK_ACTIVE, SK_LABELS, skReady, skSize,
} from "./inbox.js";
import { openAccount } from "./account.js";

// ---- Explore MusicBrainz (the !mb bang): search results, artists, releases ---------------------------

const mbLink = (key, ...kids) => h("a", { href: hashFor(MBX + key) }, ...kids);
const mbGroupCover = (id) => {
  const img = h("img", { class: "mbx-cover", src: `/api/musicbrainz/cover/${id}?size=250&kind=release-group`, alt: "",
    loading: "lazy", decoding: "async", width: "160", height: "160" });
  img.addEventListener("error", () => img.replaceWith(h("span", { class: "mbx-cover mbx-noart", "aria-hidden": "true" }, icon("note"))), { once: true });
  return img;
};
const mbGroupKind = (g) => [g.type, ...(g.secondary || [])].filter(Boolean).join(" · ");
const fmtLen = (s) => (s == null ? "" : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`);
const lifeText = (a) => (a.begin || a.end ? `${a.begin || "?"}${a.ended || a.end ? `–${a.end || "?"}` : "–"}` : "");

function mbOwnedBadge(folder) {
  return folder == null ? null : h("a", { class: "mbx-owned", href: hashFor(folder), title: `In your library: ${folder}` }, icon("check"), "In your library");
}

function mbGroupCard(g, showArtist = true) {
  return h("div", { class: "mbx-card" },
    mbLink(`rg:${g.id}`, mbGroupCover(g.id)),
    h("div", { class: "mbx-card-text" },
      mbLink(`rg:${g.id}`, h("strong", { dir: "auto" }, g.title)),
      showArtist && g.artist ? h("span", { dir: "auto" }, g.artist_id ? mbLink(`artist:${g.artist_id}`, g.artist) : g.artist) : null,
      h("span", { class: "mbx-meta" }, [g.year, mbGroupKind(g)].filter(Boolean).join(" · ")),
      mbOwnedBadge(g.in_library)));
}

function mbArtistRow(a) {
  return h("a", { class: "mbx-artist", href: hashFor(MBX + "artist:" + a.id) },
    h("span", { class: "mbx-avatar", "aria-hidden": "true" }, (a.name || "?").slice(0, 1).toUpperCase()),
    h("span", { class: "mbx-artist-text" },
      h("strong", { dir: "auto" }, a.name, a.disambiguation ? h("span", { class: "mbx-dis" }, ` (${a.disambiguation})`) : null),
      h("span", { class: "mbx-meta" }, [a.type, a.area || a.country, lifeText(a)].filter(Boolean).join(" · "))),
    icon("chevron"));
}

export function showMbLoading(path) {
  const { kind, value } = mbKey(path);
  const what = kind === "search" ? `Looking up “${value}” on MusicBrainz` : kind === "artist" ? "Loading the artist from MusicBrainz" : "Loading the release from MusicBrainz";
  els.browser.classList.remove("is-loading");
  $("#health-slot").hidden = true;
  setKids(els.folderHead, h("div", { class: "mbx-loading" },
    h("h1", { dir: "auto" }, kind === "search" ? value : "\u00a0"),
    h("p", { class: "mbx-wait" }, h("span", { class: "spinner", "aria-hidden": "true" }), `${what}…`),
    h("p", { class: "mbx-source" }, "MusicBrainz answers one request a second, so this can take a few seconds.")));
  els.folders.classList.add("mbx-host");
  setKids(els.folders, h("div", { class: "mbx-grid mbx-skeleton", "aria-hidden": "true" },
    Array.from({ length: 6 }, () => h("div", { class: "mbx-card" }, h("span", { class: "mbx-cover sk-shimmer" }),
      h("span", { class: "sk-line sk-shimmer" }), h("span", { class: "sk-line short sk-shimmer" })))));
  els.tracks.replaceChildren();
}

export function renderMbHead(f) {
  const d = f.mb;
  const source = h("p", { class: "mbx-source" }, icon("musicbrainz"), "From MusicBrainz, the open music encyclopedia");
  if (d.kind === "search") {
    setKids(els.folderHead, h("div", {}, h("h1", {}, d.query),
      h("p", {}, `${plural(d.artists.length, "artist")} and ${plural(d.releases.length, "release")} on MusicBrainz`), source));
  } else if (d.kind === "artist") {
    setKids(els.folderHead, h("div", {},
      h("h1", { dir: "auto" }, d.name),
      h("p", { class: "album-meta" }, [d.type, d.area || d.country, lifeText(d), d.disambiguation].filter(Boolean).join(" · ")),
      d.genres.length ? h("div", { class: "album-chips" }, h("span", { class: "spot-chip" }, d.genres.join(", "))) : null,
      d.links.length ? h("div", { class: "mbx-links" }, d.links.map((l) =>
        h("a", { href: l.url, target: "_blank", rel: "noopener noreferrer" }, l.label))) : null,
      source),
    h("div", { class: "folder-actions" },
      h("a", { class: "btn", href: `https://musicbrainz.org/artist/${d.id}`, target: "_blank", rel: "noopener noreferrer" }, "View on MusicBrainz")));
  } else {
    const r = d.release;
    setKids(els.folderHead,
      h("div", { class: "album-head" },
        (() => { const c = mbGroupCover(d.id); c.classList.add("album-cover"); return c; })(),
        h("div", {},
          h("h1", { dir: "auto" }, d.title),
          h("p", { class: "album-meta" },
            d.artist_id ? mbLink(`artist:${d.artist_id}`, h("b", { dir: "auto" }, d.artist)) : h("b", {}, d.artist),
            [d.year, mbGroupKind(d), r?.label, r?.catno, r?.format].filter(Boolean).map((x) => ` · ${x}`).join("")),
          h("div", { class: "album-chips" },
            d.genres.length ? h("span", { class: "spot-chip" }, d.genres.join(", ")) : null,
            mbOwnedBadge(d.in_library)),
          d.editions > 1 ? h("p", { class: "mbx-source" }, `Showing the first official edition of ${d.editions}.`) : null)),
      h("div", { class: "folder-actions" },
        d.in_library != null ? h("button", { class: "btn primary", type: "button", onclick: () => navigate(d.in_library) }, "Open in library") : null,
        skReady() ? h("button", { class: "mb-find sk-find in-actions", type: "button", onclick: () => {
          els.filter.value = [d.artist, d.title].filter(Boolean).join(" ");
          setBang("slskd", d.in_library || "");
          els.filter.focus();
        } }, h("span", { class: "mb-find-inner" }, icon("slskd"), h("span", { class: "mb-find-long" }, "Find in slskd"), h("span", { class: "mb-find-short" }, "Find"))) : null,
        h("a", { class: "btn", href: `https://musicbrainz.org/release-group/${d.id}`, target: "_blank", rel: "noopener noreferrer" }, "View on MusicBrainz")));
  }
  els.tracks.classList.remove("selecting");
}

export function renderMbBody(f) {
  const d = f.mb;
  els.folders.classList.remove("as-list");
  if (d.kind === "search") {
    setKids(els.folders, h("div", { class: "mbx" },
      d.artists.length ? h("section", {}, h("h2", { class: "mbx-h" }, "Artists"), h("div", { class: "mbx-artists" }, d.artists.map(mbArtistRow))) : null,
      d.releases.length ? h("section", {}, h("h2", { class: "mbx-h" }, "Releases"), h("div", { class: "mbx-grid" }, d.releases.map((g) => mbGroupCard(g)))) : null,
      !d.artists.length && !d.releases.length ? h("div", { class: "empty" }, h("strong", {}, "Nothing on MusicBrainz"), h("span", {}, "Try fewer or different words.")) : null));
  } else if (d.kind === "artist") {
    const sections = [["Albums", (g) => g.type === "Album" && !g.secondary.length], ["EPs", (g) => g.type === "EP" && !g.secondary.length],
      ["Singles", (g) => g.type === "Single" && !g.secondary.length], ["Compilations, live and more", (g) => g.secondary.length > 0]];
    const owned = d.groups.filter((g) => g.in_library != null).length;
    setKids(els.folders, h("div", { class: "mbx" },
      owned ? h("p", { class: "mbx-source" }, `You have ${owned} of these in your library.`) : null,
      sections.map(([title, test]) => {
        const items = d.groups.filter(test);
        return items.length ? h("section", {}, h("h2", { class: "mbx-h" }, title, h("span", {}, ` ${items.length}`)),
          h("div", { class: "mbx-grid" }, items.map((g) => mbGroupCard(g, false)))) : null;
      }),
      !d.groups.length ? h("div", { class: "empty" }, h("strong", {}, "No albums, EPs or singles listed"), h("span", {}, "MusicBrainz may not have them yet.")) : null));
  } else {
    const tracks = d.release?.tracks || [];
    const multi = tracks.some((t) => t.discs > 1);
    let disc = 0;
    setKids(els.folders, h("div", { class: "mbx" },
      tracks.length ? h("ol", { class: "mbx-tracks" }, tracks.flatMap((t) => {
        const head = multi && t.disc !== disc ? h("li", { class: "mbx-disc" }, `Disc ${t.disc}`) : null;
        disc = t.disc;
        return [head, h("li", { class: "mbx-track" },
          h("span", { class: "mbx-n" }, t.number),
          h("span", { class: "mbx-t", dir: "auto" }, t.title, t.artist && t.artist !== d.artist ? h("span", { class: "mbx-dis" }, ` · ${t.artist}`) : null),
          h("span", { class: "mbx-len" }, fmtLen(t.length)))];
      })) : h("div", { class: "empty" }, h("strong", {}, "No tracklist on MusicBrainz yet"))));
  }
}

/** A button that's just an icon until you point at it (or tab to it): then its name slides out.
 *  Touch screens keep the icon; its name is still read out and shown as a tooltip. */
export function iconButton(name, label, onclick, { title = label, cls = "", pressed = null } = {}) {
  return h("button", { class: `btn icon-expand ${cls}`, type: "button", onclick, title, "aria-label": label,
    "aria-pressed": pressed == null ? null : String(pressed) },
  icon(name), h("span", { class: "icon-expand-label", "aria-hidden": "true" }, label));
}

export function selectButtons(f) {
  if (!f.tracks.length) return [];
  return [
    state.selectMode ? iconButton("selectall", allVisibleSelected() ? "Deselect all" : "Select all", toggleSelectAllVisible,
      { cls: "phone-only" }) : null,
    iconButton("select", state.selectMode ? "Done" : "Select", () => setSelectMode(!state.selectMode),
      { cls: `phone-only${state.selectMode ? " primary" : ""}`, pressed: state.selectMode }),
  ];
}

// ---- Bangs: "!mb", "!slskd" in the search bar ------------------------------------------------------
//
// Typing a bang turns it into a chip; what you type next goes to that service
// instead of your library. Each bang is offered only while its connection is on.

export const bang = { kind: null, upgrade: "", hinted: new Set() };
export const BANGS = {
  mb: {
    names: ["mb", "musicbrainz"], label: "MusicBrainz", icon: "musicbrainz", about: "Artists and releases on MusicBrainz",
    placeholder: "Search MusicBrainz: artists, albums", available: () => connectionOn("musicbrainz"),
    missing: "MusicBrainz isn't on. Turn it on in Account → Connections.",
    run: (q) => {
      const query = q.trim();
      if (!query) return;
      if (!enoughText(query)) { toast("Type at least two letters or numbers to search MusicBrainz.", "error"); return; }
      els.filter.value = ""; setBang(false); els.filter.blur(); navigate(MBX + "search:" + query); },
  },
  slskd: {
    names: ["slskd", "soulseek"], label: "slskd", icon: "slskd", about: "Look for music on Soulseek",
    placeholder: "Search Soulseek (* is a wildcard)", available: () => skReady(),
    missing: "Soulseek isn't connected. Set it up in Account → Connections.",
    run: (q) => skSearch(q),
  },
};
const BANG_RE = /^!([a-z]+)(?=\s|$)/i; // the chip appears as soon as the bang's name is typed
const bangKind = (name) => Object.keys(BANGS).find((k) => BANGS[k].names.includes(name.toLowerCase())) || null;

export function filterPlaceholder() {
  if (bang.kind) return BANGS[bang.kind].placeholder;
  return isSearch() ? "Search library" : "Search anything";
}

/** Turn a bang's chip on (by kind) or off (null/false). ``true`` means slskd (Find in slskd). */
export function setBang(kind, upgrade = "") {
  if (kind === true) kind = "slskd";
  bang.kind = kind || null;
  bang.upgrade = bang.kind ? upgrade : "";
  const chip = $("#bang-chip");
  chip.hidden = !bang.kind;
  if (bang.kind) {
    const b = BANGS[bang.kind];
    chip.className = `bang-chip bang-${bang.kind}`;
    chip.replaceChildren(icon(b.icon), b.label);
    chip.setAttribute("aria-label", `${b.about} is on. Tap to turn it off`);
  }
  $(".topbar .search").classList.toggle("banged", !!bang.kind);
  if (bang.kind) $("#search-wrap").classList.add("active");
  els.filter.placeholder = filterPlaceholder();
  els.filter.setAttribute("enterkeyhint", bang.kind ? "search" : "enter");
  syncRoll();
  renderBangSuggestions();
}

/** Typing "!mb" or "!slskd" in the search bar: true if a bang was taken. */
export function takeBang() {
  const m = BANG_RE.exec(els.filter.value);
  if (bang.kind || !m) return false;
  const kind = bangKind(m[1]);
  if (!kind) return false;
  if (!BANGS[kind].available()) {
    if (!bang.hinted.has(kind)) toast(BANGS[kind].missing);
    bang.hinted.add(kind);
    return false;
  }
  els.filter.value = els.filter.value.slice(m[0].length).trimStart();
  setBang(kind);
  if (state.filter) { state.filter = ""; renderFolders(); renderTracks(); renderFilterChips(); }
  return true;
}

/** Under the search bar: the bangs you can use (on focus, or while typing "!..."). */
export function renderBangSuggestions() {
  const box = $("#bang-suggest");
  const value = els.filter.value;
  const focused = document.activeElement === els.filter;
  const typed = value.startsWith("!") ? value.slice(1).toLowerCase() : null;
  const items = Object.entries(BANGS).filter(([, b]) => b.available())
    .filter(([, b]) => typed === null || b.names.some((n) => n.startsWith(typed)));
  const library = value === "" ? librarySuggestions() : [];
  const show = focused && !bang.kind && (items.length || library.length) && (value === "" || typed !== null);
  if (!show) {
    if (!box.hidden && !box.classList.contains("closing")) playOut(box, "closing", () => { box.hidden = true; });
    return;
  }
  setKids(box, items.length ? h("p", { class: "bang-suggest-head" }, "Search elsewhere") : null,
    items.map(([kind, b]) => h("button", { class: "bang-suggest-item", type: "button", role: "option",
      onpointerdown: (e) => e.preventDefault(), // keep the keyboard open
      onclick: () => { els.filter.value = els.filter.value.startsWith("!") ? "" : els.filter.value; setBang(kind); els.filter.focus(); } },
    h("span", { class: `bang-chip bang-${kind}` }, icon(b.icon), b.label),
    h("span", { class: "bang-suggest-about" }, b.about),
    h("kbd", {}, `!${b.names[0]}`))),
    library.length ? h("p", { class: "bang-suggest-head" }, "Search your library") : null,
    library.map((s) => h("button", { class: "bang-suggest-item lib-suggest-item", type: "button", role: "option",
      onpointerdown: (e) => e.preventDefault(), // keep the keyboard open
      onclick: () => { els.filter.value = s.insert; els.filter.focus(); renderBangSuggestions(); } },
    h("span", { class: "lib-suggest-icon" }, icon(s.icon)),
    h("span", { class: "lib-suggest-label" }, s.label),
    s.example ? h("span", { class: "lib-suggest-example", dir: "auto" }, s.example) : null)));
  if (box.hidden) { box.classList.remove("closing"); box.hidden = false; replay(box, "opening"); }
}

// ---- Search ideas: real names from the library, rolling through the idle search bar ------------------

export const roll = { ideas: null, list: [], i: 0, timer: null, on: false };
const shuffle = (a) => { a = [...a]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

export async function loadSearchIdeas() {
  try { roll.ideas = await api("GET", "/api/search/ideas"); } catch { return; }
  const d = roll.ideas;
  const pools = [
    shuffle(d.genre || []).map((v) => `Search genre: ${v.toLowerCase()}`),
    shuffle(d.artist || []).map((v) => `Search ${v}`),
    shuffle(d.mood || []).map((v) => `Search mood: ${v.toLowerCase()}`),
    shuffle(d.album || []).map((v) => `Search album: ${v}`),
  ].filter((p) => p.length);
  const list = [];
  for (let n = 0; pools.some((p) => p.length); n++) {
    const pool = pools[n % pools.length];
    if (pool.length) list.push(pool.shift());
    if (list.length % 5 === 4) list.push("Search anything"); // back home now and then
  }
  roll.list = list;
  roll.i = 0;
  syncRoll();
}

/** "Search your library" suggestions: what you can type, with a real example from your music. */
function librarySuggestions() {
  const d = roll.ideas || {};
  const pick = (a) => (a && a.length ? a[0] : "");
  const tag = pick(d.genre) ? ["genre", pick(d.genre).toLowerCase()] : pick(d.mood) ? ["mood", pick(d.mood).toLowerCase()] : ["year", ""];
  return [
    { label: "Search artist", icon: "user", insert: "artist: ", example: pick(d.artist) && `artist: ${pick(d.artist)}` },
    { label: "Search album", icon: "disc", insert: "album: ", example: pick(d.album) && `album: ${pick(d.album)}` },
    { label: "Search tag", icon: "tag", insert: `${tag[0]}: `, example: tag[1] && `${tag[0]}: ${tag[1]}` },
  ];
}

const rollIdle = () => roll.list.length && !els.filter.value && document.activeElement !== els.filter && !bang.kind
  && !document.hidden && filterPlaceholder() === "Search anything";

function rollShow(text, animate) {
  const box = $("#search-roll");
  const line = h("span", { class: `roll-line${animate ? " in" : ""}` }, h("span", {}, text));
  const old = [...box.children];
  for (const o of old) { o.classList.remove("in"); o.classList.add("out"); setTimeout(() => o.remove(), 600); }
  box.append(line);
  if (!animate) for (const o of old) o.remove();
}

/** Start or stop the rolling examples: only while the search bar is empty and not in use. */
export function syncRoll() {
  const box = $("#search-roll");
  if (!box) return;
  if (!rollIdle()) {
    clearTimeout(roll.timer);
    if (roll.on) { roll.on = false; box.hidden = true; box.replaceChildren(); }
    if (!bang.kind) els.filter.placeholder = filterPlaceholder();
    return;
  }
  if (roll.on) return;
  roll.on = true;
  box.style.font = getComputedStyle(els.filter).font; // the same type as the real placeholder
  els.filter.placeholder = "";
  box.hidden = false;
  rollShow("Search anything", false);
  const next = () => {
    if (!rollIdle()) { syncRoll(); return; }
    rollShow(roll.list[roll.i++ % roll.list.length], true);
    roll.timer = setTimeout(next, 3200);
  };
  clearTimeout(roll.timer);
  roll.timer = setTimeout(next, 2600);
}

const enoughText = (q) => [...q].filter((c) => /[\p{L}\p{N}]/u.test(c)).length >= 2;

async function skSearch(query, upgrade = bang.upgrade) {
  query = query.trim();
  if (!query) return;
  if (!enoughText(query)) { toast("Type at least two letters or numbers to search Soulseek.", "error"); return; }
  const chip = $("#bang-chip");
  chip.classList.add("busy");
  for (const b of document.querySelectorAll(".sk-search button[type=submit]")) { b.disabled = true; b.textContent = "Asking…"; }
  try {
    const res = await api("POST", "/api/slskd/search", { query, upgrade });
    sk.data = res;
    els.filter.value = "";
    setBang(false);
    els.filter.blur();
    toast(`Asking Soulseek for “${query}”…`, "success");
    openSoulseek(res.job.id);
  } catch (err) {
    toast(err.message, "error");
  } finally {
    chip.classList.remove("busy");
    for (const b of document.querySelectorAll(".sk-search button[type=submit]")) { b.disabled = false; b.textContent = "Search"; }
  }
}

/** The album's search words: its album artist + album tags, else the parent and folder names. */
function albumQuery() {
  const ok = (state.folder?.tracks || []).filter((t) => !t.error);
  const common = (key) => {
    const v = new Set(ok.map((t) => first(t, key).trim()).filter(Boolean));
    return v.size === 1 ? [...v][0] : "";
  };
  const artist = common("albumartist") || common("artist");
  const album = common("album");
  if (album) return [artist, album].filter(Boolean).join(" ");
  return (state.path || "").split("/").filter(Boolean).slice(-2).join(" ");
}

/** Find in slskd: fills the search bar (chip + words) so the search can be edited before it's sent. */
function findInSlskd() {
  els.filter.value = albumQuery();
  setBang(true, state.path);
  els.filter.focus();
  els.filter.select();
}

export function skFindButton(where) {
  return h("button", {
    class: `mb-find sk-find ${where}`, type: "button", onclick: findInSlskd,
    "aria-label": "Find in slskd", title: "Look for a better copy of this album on Soulseek. You can edit the search before it's sent.",
  }, h("span", { class: "mb-find-inner" }, icon("slskd"),
    h("span", { class: "mb-find-long" }, "Find in slskd"), h("span", { class: "mb-find-short" }, "Find")));
}

export async function openSoulseek(focus = null) {
  sk.focus = focus;
  sk.picking = null;
  openDialog($("#soulseek-dialog"));
  if (!sk.data) setKids($("#soulseek-body"), h("p", { class: "loading" }, "Loading…"));
  await refreshSoulseek();
}

async function refreshSoulseek() {
  clearTimeout(sk.timer);
  try {
    sk.data = await api("GET", "/api/slskd");
  } catch (err) {
    setKids($("#soulseek-body"), h("div", { class: "error-box" }, err.message));
    return;
  }
  if (!$("#soulseek-dialog").open) return;
  renderSoulseek();
  const busy = sk.data.jobs.some((j) => SK_ACTIVE.includes(j.status)
    || (j.status === "arrived" && (!j.inbox || ["waiting", "matching", "downloading"].includes(j.inbox.status))));
  if (busy) sk.timer = setTimeout(refreshSoulseek, 2000);
}

async function skAction(method, url, body, done) {
  try {
    const res = await api(method, url, body);
    sk.data = res;
    if (done) done(res);
    if ($("#soulseek-dialog").open) renderSoulseek();
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    refreshInboxBadge();
    clearTimeout(sk.timer);
    sk.timer = setTimeout(refreshSoulseek, 1500);
  } catch (err) {
    toast(err.message, "error");
  }
}

const skFiled = (res) => toast(res.status === "filed" ? `Filed in ${res.moved_to || "your library"}` : res.note,
  res.status === "filed" ? "success" : "error");

async function skImport(j) {
  if (j.upgrade && !await ask({
    title: "Replace the album?",
    message: `The copy in ${j.upgrade} is moved out of your library and kept for 30 days in Codetta's config folder (Activity can undo it until then), and this download takes its place.`,
    confirmLabel: "Replace",
  })) return;
  skAction("POST", `/api/slskd/jobs/${j.id}/import`, {}, (res) => { skFiled(res); if (res.moved_to) loadFolder(state.path); });
}

function skReviewTags(j) {
  const g = j.inbox;
  closeDialog($("#soulseek-dialog"));
  openMusicBrainzFor({ body: { paths: g.paths }, label: `“${g.title || j.query}”` }, {
    release: g.release?.id, recordings: g.recordings,
    onWritten: (release) => skAction("POST", `/api/slskd/jobs/${j.id}/import`, { release }, skFiled),
  });
}

function shareWarning() {
  return h("div", { class: "sk-warn", role: "note" },
    h("strong", {}, "Share a folder in slskd"),
    h("span", {}, "Soulseek is give-and-take. Many users won't send files to someone who shares nothing, and some ban them. "
      + "In slskd, add a folder under shares → directories (your music folder, read-only, is the usual choice) and rescan. "
      + "Codetta works without it, but downloads will often stall or be refused."));
}

function skCheckView(c, d) {
  if (!c) return null;
  if (!c.ok) return h("div", { class: "error-box" }, c.error);
  return h("div", { class: "sk-check" },
    h("p", { class: "sk-ok" }, icon("check"), `Connected to slskd ${c.version}`,
      c.logged_in === false ? " · not signed in to Soulseek yet (check slskd's soulseek username and password)" : ""),
    c.shared_folders ? h("p", { class: "hint" }, `Sharing ${plural(c.shared_folders, "folder")} (${c.shared_files.toLocaleString()} files). Thanks for giving back.`)
      : shareWarning(),
    h("p", { class: "hint" }, c.downloads_dir ? `slskd saves downloads to ${c.downloads_dir}. ` : "",
      d?.inbox?.folder === "@inbox"
        ? "Codetta's inbox is your downloads folder, so they arrive there. Make sure it's the same folder (mounted at /inbox)."
        : "Mount slskd's downloads folder into Codetta at /inbox and choose it as the inbox (Inbox button), so downloads arrive there."));
}

/** The slskd connection fields (Account → Connections and the setup step). */
function slskdFields(d) {
  const st = d?.settings || { review: true, lossless_only: false, min_bitrate: 320 };
  const locked = d?.locked || {};
  const sw = (name, title, sub, checked) => h("label", { class: "switch-row" },
    h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, title), h("span", { class: "switch-sub" }, sub)),
    h("input", { type: "checkbox", role: "switch", name, checked }));
  return h("div", { class: "sk-fields" },
    h("label", { class: "field" }, h("span", { class: "field-label" }, "slskd address"),
      h("input", { name: "sk-url", type: "text", inputmode: "url", placeholder: "http://slskd:5030", value: d?.url || "", maxlength: "500",
        disabled: locked.url, autocomplete: "off", spellcheck: "false", autocapitalize: "off" })),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "API key"),
      h("input", { name: "sk-key", type: "password", disabled: locked.api_key, autocomplete: "off",
        placeholder: d?.has_key ? "Saved (type a new one to change it)" : "One of the api_keys in slskd's settings", maxlength: "500" })),
    locked.url || locked.api_key ? h("p", { class: "conn-lock" }, "Set on the server by CODETTA_SLSKD_URL / CODETTA_SLSKD_API_KEY.") : null,
    h("p", { class: "hint" }, "Add a key in slskd's settings under ", h("code", {}, "web → authentication → api_keys"),
      " (16+ characters), then paste it here. Codetta keeps it on this server and never shows it again."),
    h("p", { class: "field-error sk-field-error", role: "alert", hidden: true }),
    sw("sk-choose", "Pick the source first", "See who's sharing it (free slot, queue, speed) and every file before anything downloads. Off: the best source downloads by itself, which is quicker, but a source can be mislabeled.", st.choose !== false),
    sw("sk-review", "Review each download", "Codetta asks before a download joins your library. Off: downloads that match MusicBrainz exactly are filed by themselves.", st.review),
    sw("sk-lossless", "Lossless only", "Never download lossy files. Off: lossless first, otherwise the best MP3/AAC (at least the bitrate below).", st.lossless_only),
    h("label", { class: "field sk-bitrate" }, h("span", { class: "field-label" }, "Lowest bitrate for lossy files"),
      h("select", { name: "sk-bitrate" }, [128, 192, 256, 320].map((b) => h("option", { value: b, selected: b === st.min_bitrate }, `${b} kbps`)))),
    h("div", { class: "sk-check-slot" }, skCheckView(d?.check, d)));
}

function slskdFieldError(root) {
  const url = $('[name="sk-url"]', root).value.trim();
  const key = $('[name="sk-key"]', root).value.trim();
  if (url) {
    let u = null;
    try { u = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : `http://${url}`); } catch { /* below */ }
    if (!u || !/^https?:$/.test(u.protocol) || !u.hostname || u.username || /\s/.test(url)) {
      return "slskd's address should look like http://slskd:5030 or http://192.168.1.50:5030";
    }
  } else if (!$('[name="sk-url"]', root).disabled) return "Add slskd's address, like http://slskd:5030";
  if (key && (key.length < 8 || /\s/.test(key))) return "That doesn't look like an slskd API key (at least 8 characters, no spaces).";
  return "";
}

function readSlskdFields(root) {
  const problem = slskdFieldError(root);
  const out = $(".sk-field-error", root);
  if (out) { out.textContent = problem; out.hidden = !problem; }
  if (problem) throw new Error(problem);
  const key = $('[name="sk-key"]', root).value.trim();
  return {
    url: $('[name="sk-url"]', root).value.trim(), api_key: key || null,
    review: $('[name="sk-review"]', root).checked, lossless_only: $('[name="sk-lossless"]', root).checked,
    choose: $('[name="sk-choose"]', root).checked,
    min_bitrate: Number($('[name="sk-bitrate"]', root).value), search_seconds: sk.data?.settings?.search_seconds || 20,
  };
}

/** Save (and test) the connection; shows the result in place. */
async function saveSlskd(root) {
  sk.data = await api("PUT", "/api/slskd/settings", readSlskdFields(root));
  $('[name="sk-key"]', root).value = "";
  if (sk.data.has_key) $('[name="sk-key"]', root).placeholder = "Saved (type a new one to change it)";
  setKids($(".sk-check-slot", root), skCheckView(sk.data.check, sk.data));
  renderFolderHead();
  return sk.data;
}

export function renderSlskdSettings() {
  const box = $("#slskd-box");
  if (!connectionOn("slskd")) { box.replaceChildren(); return; }
  const form = h("form", { class: "sk-settings" },
    h("h3", { class: "field-label sk-head" }, icon("slskd"), "Soulseek (slskd)"),
    slskdFields(sk.data),
    h("div", { class: "inbox-settings-actions" },
      h("button", { class: "btn primary", type: "submit" }, "Save and test")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    go.disabled = true;
    try {
      const d = await saveSlskd(form);
      toast(d.check?.ok ? "slskd connected" : "Saved, but slskd didn't answer", d.check?.ok ? "success" : "error");
    } catch (err) { toast(err.message, "error"); } finally { go.disabled = false; }
  });
  box.replaceChildren(form);
}

export async function renderSlskdStep(form, step) {
  const d = await loadSlskd();
  let warned = false;
  setKids(form, setupLogo(), stepCount(),
    h("h1", {}, "Do you use Soulseek?"),
    h("p", { class: "auth-sub" }, "If you run slskd, Codetta can find music on Soulseek for you: type !slskd in the search bar, or tap Find in slskd on an album. "
      + "The best copy is downloaded into your inbox, and you decide whether it joins your library."),
    h("div", { class: "sk-warn soft" }, h("strong", {}, "You'll need a shared folder"),
      h("span", {}, "Soulseek users often refuse people who share nothing. In slskd, share a folder (your music, read-only) before you start.")),
    slskdFields(d),
    h("button", { class: "btn primary auth-submit", type: "submit" }, "Connect slskd"),
    h("button", { class: "link-btn setup-skip", type: "button", onclick: () => finishStep(step) }, "I don't use slskd"),
    h("p", { class: "auth-foot" }, "You can connect it later in Account → Connections."));
  form.onsubmit = async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    if (warned) { finishStep(step); return; }
    go.disabled = true;
    try {
      state.connections = await api("PUT", "/api/connections", { enabled: { slskd: true } });
      applyConnections();
      const res = await saveSlskd(form);
      if (!res.check?.ok) { go.disabled = false; return; }
      if (!res.check.shared_folders) {
        warned = true;
        go.textContent = "Continue anyway";
        go.disabled = false;
        return;
      }
      toast("slskd connected", "success");
      finishStep(step);
    } catch (err) {
      toast(err.message, "error");
      go.disabled = false;
    }
  };
}

const skSpeed = (bps) => (bps >= 1e6 ? `${(bps / 1e6).toFixed(1)} MB/s` : bps >= 1e3 ? `${Math.round(bps / 1e3)} KB/s` : null);

function skCandidates(j) {
  const choosing = j.status === "choosing";
  return h("ol", { class: `sk-cands${choosing ? " choosing" : ""}` }, j.candidates.slice(0, choosing ? 8 : 25).map((c) => {
    const here = c.index === j.current?.index;
    return h("li", { class: here ? "current" : "" },
      h("span", { class: "sk-cand-text" },
        h("strong", { dir: "auto" }, c.name),
        h("span", {}, [c.quality, plural(c.tracks, "track"), skSize(c.size), c.username,
          c.free_slot ? "free slot" : `${c.queue} queued`, choosing ? skSpeed(c.speed) : null].filter(Boolean).join(" · ")),
        choosing && c.files?.length ? h("details", { class: "sk-files" }, h("summary", {}, `Files (${c.files.length})`),
          h("ol", {}, c.files.map((n) => h("li", { dir: "auto" }, n)))) : null),
      here ? h("span", { class: "inbox-note" }, "This one")
        : h("button", { class: "btn small", type: "button", onclick: () => skAction("POST", `/api/slskd/jobs/${j.id}/pick`, { index: c.index },
          () => { sk.picking = null; toast(`Downloading ${c.name}…`); }) }, c.tried ? "Try again" : "Download"));
  }));
}

function skItem(j) {
  const c = j.current;
  const g = j.inbox;
  const url = (p) => `/api/slskd/jobs/${j.id}/${p}`;
  const btn = (label, onclick, primary = false) => h("button", { class: `btn small${primary ? " primary" : ""}`, type: "button", onclick }, label);
  const link = (label, onclick) => h("button", { class: "link-btn inbox-skip", type: "button", onclick }, label);
  const reviewable = j.status === "arrived" && g && ["ready", "review", "nomatch", "local", "error"].includes(g.status);
  let chip = SK_LABELS[j.status] || j.status;
  let chipClass = j.status === "arrived" ? "matching" : j.status === "imported" ? "filed" : ["nothing", "failed"].includes(j.status) ? "error" : j.status;
  const actions = [];
  if (reviewable) {
    chip = j.upgrade ? "Ready to replace" : "Have a look";
    chipClass = "review";
    actions.push(btn(j.upgrade ? "Replace album" : "Import", () => skImport(j), true),
      btn("Blocklist & try next", () => skAction("POST", url("next"), { block: true }, () => toast("Blocklisted. Trying the next one…"))),
      btn("Check tags", () => skReviewTags(j)));
  }
  if (SK_ACTIVE.includes(j.status)) actions.push(btn("Cancel", () => skAction("POST", url("cancel"))));
  if (["nothing", "failed", "cancelled"].includes(j.status)) actions.push(btn("Search again", () => skSearch(j.query, j.upgrade), true));
  if (j.status === "imported" && g?.dest) actions.push(btn("Open", () => { closeDialog($("#soulseek-dialog")); navigate(g.dest); }, true));
  if (j.candidates.length > 1 && ["downloading", "arrived", "failed"].includes(j.status)) {
    actions.push(link(sk.picking === j.id ? "Hide the others" : `Choose another (${j.candidates.length - 1})`,
      () => { sk.picking = sk.picking === j.id ? null : j.id; renderSoulseek(); }));
  }
  if (["imported", "nothing", "failed", "cancelled"].includes(j.status)) actions.push(link("Remove", () => skAction("DELETE", `/api/slskd/jobs/${j.id}`)));
  const bar = j.status === "downloading" && j.progress > 0 ? progressBar(j.progress, etaText(j.eta)) : null;
  return h("div", { class: `inbox-item sk-item ${j.status}`, "data-job": j.id },
    reviewable && g.release?.id && sk.data.enabled && connectionOn("musicbrainz") ? mbThumb(g.release.id)
      : h("span", { class: "mb-thumb mb-noart sk-thumb", "aria-hidden": "true" }, icon("slskd")),
    h("div", { class: "inbox-main" },
      h("div", { class: "inbox-title", dir: "auto" }, reviewable && g.title ? g.title : c?.name || j.query,
        reviewable && g.artist ? h("span", { class: "inbox-artist" }, ` · ${g.artist}`) : null),
      h("div", { class: "mb-cand-meta" }, c ? [c.quality, plural(c.tracks, "track"), skSize(c.size), `from ${c.username}`].join(" · ") : `“${j.query}”`,
        j.upgrade ? ` · replaces ${j.upgrade}` : ""),
      reviewable && g.release ? h("div", { class: "mb-cand-meta" }, `MusicBrainz: ${mbMeta(g.release)}${g.score != null ? ` · ${g.score}% match` : ""}`) : null,
      bar,
      h("div", { class: "inbox-status" },
        h("span", { class: `inbox-chip ${chipClass}` }, SK_ACTIVE.includes(j.status) || chipClass === "matching"
          ? h("span", { class: "live-dot", "aria-hidden": "true" }) : null, chip),
        j.note ? h("span", { class: "inbox-note" }, j.note) : null),
      reviewable && c ? h("details", { class: "sk-files" }, h("summary", {}, `What came: ${plural(c.files.length, "file")}`),
        h("ol", {}, c.files.map((n) => h("li", { dir: "auto" }, n)))) : null,
      sk.picking === j.id || j.status === "choosing" ? skCandidates(j) : null),
    h("div", { class: "inbox-actions" }, actions));
}

function renderSoulseek() {
  const d = sk.data;
  const body = $("#soulseek-body");
  const close = h("button", { class: "btn", type: "button", "data-close": true }, "Close");
  if (!d.enabled || !d.configured) {
    setKids(body,
      h("p", { class: "mb-lead" }, "Connect your slskd to find music on Soulseek. It's in Account → Connections → Soulseek (slskd)."),
      h("button", { class: "btn primary", type: "button", onclick: () => {
        closeDialog($("#soulseek-dialog")); openAccount(); setConnectionsOpen(true);
      } }, "Open Connections"));
    setKids($("#soulseek-foot"), h("span", { class: "spacer" }), close);
    return;
  }
  const form = h("form", { class: "sk-search" },
    h("span", { class: "bang-chip" }, icon("slskd"), "slskd"),
    h("input", { type: "search", name: "q", placeholder: "Artist and album (* is a wildcard)", "aria-label": "Search Soulseek", maxlength: "300",
      autocomplete: "off", spellcheck: "false", enterkeyhint: "search" }),
    h("button", { class: "btn primary", type: "submit" }, "Search"));
  form.addEventListener("submit", (e) => { e.preventDefault(); skSearch(form.q.value, ""); });
  setKids(body,
    !d.inbox.folder ? h("p", { class: "org-warn" }, "Set up the inbox first: Soulseek downloads arrive there (Inbox button in the top bar).") : null,
    d.check?.ok && !d.check.shared_folders ? shareWarning() : null,
    form,
    d.jobs.length ? h("div", { class: "inbox-list sk-list" }, d.jobs.map(skItem))
      : h("p", { class: "hint" }, "Type !slskd in the search bar (or use Find in slskd on an album). Codetta picks the best copy, downloads it into your inbox, and asks you before it joins your library."));
  setKids($("#soulseek-foot"),
    d.blocked ? h("button", { class: "link-btn", type: "button", onclick: async () => {
      if (await ask({ title: "Clear the blocklist?", message: `${plural(d.blocked, "folder")} you turned down can be offered again.`, confirmLabel: "Clear" })) {
        skAction("DELETE", "/api/slskd/blocklist");
      }
    } }, `Clear blocklist (${d.blocked})`) : null,
    h("span", { class: "spacer" }), close);
  if (sk.focus) {
    const el = body.querySelector(`[data-job="${CSS.escape(sk.focus)}"]`);
    if (el) { el.classList.add("focus"); el.scrollIntoView({ block: "nearest" }); }
    sk.focus = null;
  }
}
