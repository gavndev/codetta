// ---- Under an album: albums like it -------------------------------------------------------------------
//
// First the library's own (more by the artist, then albums by similar artists and in the same genre),
// then, past a divider, albums the library doesn't have (Deezer), each with Find in slskd. The second
// part is only asked for when it scrolls into view.

import { $, fitCover, h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, state } from "./state.js";
import { hashFor, isSearchKey } from "./browse.js";
import { setBang } from "./search.js";
import { skReady } from "./inbox.js";
import { openSettings } from "./settings.js";

const cache = new Map(); // folder -> { like, elsewhere } answers (or Promises of them)
let shownFor = null;
let watcher = null;

const isAlbum = (f) => !!f && !!f.path && f.tracks.length > 0 && !f.mb && !f.yours && !f.search && !isSearchKey(f.path);

function ask(folder, kind) {
  const key = `${kind}\u001f${folder}`;
  if (!cache.has(key)) {
    const p = api("GET", `/api/albums/${kind}?folder=${encodeURIComponent(folder)}`)
      .then((d) => { cache.set(key, d); return d; })
      .catch(() => { cache.delete(key); return null; });
    cache.set(key, p);
    if (cache.size > 80) cache.delete(cache.keys().next().value);
  }
  return Promise.resolve(cache.get(key));
}

/** Forget what was found (after tags change, the library's albums may have too). */
export function forgetAlbumsLike() { cache.clear(); shownFor = null; }

const meta = (a) => [a.artist, a.year].filter(Boolean).join(" · ");

function libraryCard(a) {
  const cover = h("span", { class: "am-cover" });
  if (a.cover) {
    const img = fitCover(h("img", { src: `/api/art?path=${encodeURIComponent(a.cover.path)}&v=${a.cover.hash}`, alt: "",
      loading: "lazy", decoding: "async" }));
    img.addEventListener("error", () => img.replaceWith(icon("note")), { once: true });
    cover.append(img);
  } else cover.append(icon("note"));
  return h("a", { class: "am-card", href: hashFor(a.folder), title: a.title },
    cover,
    h("span", { class: "am-title", dir: "auto", translate: "no" }, a.title),
    h("span", { class: "am-meta", dir: "auto", translate: "no" }, meta(a)));
}

function findIn(a) {
  els.filter.value = [a.artist, a.title].filter(Boolean).join(" ");
  setBang("slskd");
  els.filter.focus();
  els.filter.select();
}

function elsewhereCard(a) {
  const img = h("img", { src: `/api/musicbrainz/cover/${encodeURIComponent(a.id)}?size=250`, alt: "", loading: "lazy", decoding: "async" });
  img.addEventListener("error", () => img.replaceWith(icon("note")), { once: true });
  const raw = a.id.split(":")[1];
  return h("div", { class: "am-card away" },
    h("a", { class: "am-cover", href: `https://www.deezer.com/album/${raw}`, target: "_blank", rel: "noopener noreferrer",
      title: "Open on Deezer" }, fitCover(img)),
    h("span", { class: "am-title", dir: "auto", translate: "no" }, a.title),
    h("span", { class: "am-meta", dir: "auto", translate: "no" }, meta(a)),
    skReady() ? h("button", { class: "am-find", type: "button", onclick: () => findIn(a),
      title: "Look for this album on Soulseek. You can edit the search before it's sent." }, icon("slskd"), "Find in slskd") : null);
}

const row = (title, cards) => cards.length ? h("div", { class: "am-group" },
  h("h2", { class: "am-head", dir: "auto" }, title),
  h("div", { class: "am-row" }, cards)) : null;

/** Fill (or clear) the space under the album's tracks. */
export function renderAlbumsLike() {
  const box = $("#album-more");
  const f = state.folder;
  if (!isAlbum(f) || state.filter || state.tagFilters.length) {
    box.hidden = true; setKids(box); shownFor = null; watcher?.disconnect();
    return;
  }
  if (shownFor === f.path && box.childElementCount) { box.hidden = false; return; }
  shownFor = f.path;
  watcher?.disconnect();
  setKids(box);
  box.hidden = true;
  const folder = f.path;
  ask(folder, "like").then((d) => {
    if (shownFor !== folder) return;
    const away = h("div", { class: "am-away" });
    const mine = d ? [
      row(d.artist ? `More by ${d.artist}` : "More by this artist", d.more.map(libraryCard)),
      row("You might also like", d.like.map(libraryCard)),
    ].filter(Boolean) : [];
    setKids(box, ...mine, away);
    box.hidden = false;
    // Albums the library doesn't have: asked for once the divider is close to being seen.
    watcher = new IntersectionObserver((seen) => {
      if (!seen.some((e) => e.isIntersecting)) return;
      watcher.disconnect();
      ask(folder, "elsewhere").then((e) => {
        if (shownFor !== folder || !e) return;
        if (!e.can) {
          setKids(away, h("hr", { class: "am-rule" }),
            h("button", { class: "link-btn am-hint", type: "button", onclick: () => openSettings("connections") },
              icon("spark"), "See albums you don't have yet: turn on Deezer in Settings → Connections"));
          return;
        }
        const more = e.albums.filter((a) => a.why === "artist").map(elsewhereCard);
        const like = e.albums.filter((a) => a.why === "similar").map(elsewhereCard);
        if (!more.length && !like.length) { setKids(away); return; }
        setKids(away, h("hr", { class: "am-rule" }),
          h("p", { class: "am-away-label" }, "Not in your library"),
          row(d?.artist ? `More by ${d.artist}` : "More by this artist", more),
          row("Similar albums", like));
      });
    }, { rootMargin: "400px" });
    watcher.observe(away);
  });
}
