// Artists: tapping an artist name (go to them, or pick one when the credit names several),
// their pictures next to their names, and the artist menu. See core/artists.py and core/artistart.py.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { plural, toast } from "./state.js";
import { currentLanguage } from "./i18n.js";
import { openSettings } from "./settings.js";
import { SEARCH, navigate } from "./browse.js";
import { popMenu } from "./tools.js";

const resolved = new Map(); // credits -> Promise of [{name, folder, own}]
const noPicture = new Set(); // artists the server has no picture for (initials, without asking again)

function artistsOf(credits) {
  const list = [...new Set(credits.map((c) => (c || "").trim()).filter(Boolean))];
  const key = list.join("\u001f");
  if (!list.length) return Promise.resolve([]);
  if (!resolved.has(key)) {
    const q = list.map((c) => `credit=${encodeURIComponent(c)}`).join("&");
    resolved.set(key, api("GET", `/api/artists?${q}`).then((d) => d.artists || []).catch((err) => { resolved.delete(key); throw err; }));
    if (resolved.size > 300) resolved.delete(resolved.keys().next().value);
  }
  return resolved.get(key);
}

/** Where an artist lives: their folder at the top of the library, or a search for every song they're on. */
function goTo(a) {
  if (a.folder) navigate(a.folder);
  else navigate(SEARCH + `artist: ${a.name.replace(/[,;]/g, " ").replace(/\s+/g, " ").trim()}`);
}

const initials = (name) => {
  const words = name.replace(/[^\p{L}\p{N}\s]/gu, " ").trim().split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[words.length - 1][0] : (words[0] || "?").slice(0, 2)).toUpperCase();
};
const hue = (name) => [...name].reduce((n, c) => (n * 31 + c.codePointAt(0)) % 360, 7);

/** A round artist picture; their initials on a colour of their own when there's no picture. */
export function artistAvatar(a, size = 40) {
  const box = h("span", { class: "artist-av", "aria-hidden": "true" });
  box.style.setProperty("--av", `${size}px`); // set through the CSSOM: the page's CSP refuses style attributes
  box.style.setProperty("--hue", String(hue(a.name)));
  const key = `${a.name}\u001f${a.folder || ""}`;
  const mono = () => box.replaceChildren(h("span", { class: "artist-av-ini" }, initials(a.name)));
  if (noPicture.has(key)) { mono(); return box; }
  const img = h("img", { alt: "", loading: "lazy", decoding: "async", width: String(size), height: String(size),
    src: `/api/artists/picture?name=${encodeURIComponent(a.name)}${a.folder ? `&folder=${encodeURIComponent(a.folder)}` : ""}` });
  img.addEventListener("error", () => { noPicture.add(key); mono(); });
  box.append(img);
  return box;
}

const subLine = (a) => (a.folder ? "Artist folder" : a.own ? "Songs in your library" : "Featured: songs they're on");

/** The artist menu: a picture, the name and where a tap leads, for each artist in the credit. */
function artistMenu(anchor, artists, before) {
  const menu = h("div", { class: "tools-menu artist-menu", role: "menu" }, artists.map((a) => h("button", {
    class: "artist-item", type: "button", role: "menuitem",
    onclick: () => { menu.remove(); before(); goTo(a); },
  }, artistAvatar(a, 40), h("span", { class: "artist-item-text" },
    h("span", { class: "artist-item-name", dir: "auto", translate: "no" }, a.name),
    h("span", { class: "artist-item-sub" }, subLine(a))))));
  popMenu(anchor, menu);
}

/** ``credits``: the artist values to look at (a track's artists, an album's album artist). */
export async function openArtist(anchor, credits, before = () => {}) {
  let found;
  try { found = await artistsOf(credits); } catch (err) { toast(err.message, "error"); return; }
  if (!found.length) return;
  if (found.length === 1) { before(); goTo(found[0]); return; }
  artistMenu(anchor, found, before);
}

/** Put the credit's artist pictures (overlapping, up to 3) at the start of ``el``. */
function addArtistPictures(el, credits, size = 22) {
  artistsOf(credits).then((list) => {
    if (list.length) el.prepend(h("span", { class: "artist-stack", "aria-hidden": "true" }, list.slice(0, 3).map((a) => artistAvatar(a, size))));
  }).catch(() => {});
  return el;
}

/** An artist name that can be tapped; ``pictures``: their pictures beside the name (a size in px). */
export function artistButton(text, credits, { cls = "", before, pictures = 0 } = {}) {
  const btn = h("button", {
    class: `artist-link ${cls}`.trim(), type: "button", dir: "auto", translate: "no",
    title: "Go to this artist",
    onclick: (e) => { e.stopPropagation(); openArtist(e.currentTarget, credits, before); },
  }, h("span", { class: "artist-link-text" }, text));
  if (pictures) addArtistPictures(btn, credits, pictures === true ? 22 : pictures);
  return btn;
}

// ---- An artist's folder: their picture, a bio and similar artists (a little like Last.fm) -------------

const infoCache = new Map(); // folder + language -> the /api/artists/info answer (or a Promise of it)

function artistInfo(folder) {
  const key = `${folder}\u001f${currentLanguage()}`;
  if (!infoCache.has(key)) {
    const p = api("GET", `/api/artists/info?folder=${encodeURIComponent(folder)}&lang=${encodeURIComponent(currentLanguage())}`)
      .then((d) => { infoCache.set(key, d); return d; })
      .catch(() => { infoCache.delete(key); return null; });
    infoCache.set(key, p);
    if (infoCache.size > 200) infoCache.delete(infoCache.keys().next().value);
  }
  return infoCache.get(key);
}

/** The head of an artist's folder (a folder at the top of the library that holds albums). */
export function artistHead(f, counts) {
  const folder = f.path;
  const slot = h("div", { class: "artist-extra" });
  const fill = (d) => {
    if (!d) { setKids(slot); return; }
    const bio = d.bio ? h("div", { class: "artist-bio" },
      h("p", { class: "artist-bio-text", dir: "auto", lang: d.bio.lang }, d.bio.text),
      h("p", { class: "artist-bio-foot" },
        h("button", { class: "link-btn artist-bio-more", type: "button", onclick: (e) => {
          const open = slot.classList.toggle("bio-open");
          e.currentTarget.textContent = open ? "Less" : "More";
        } }, "More"),
        " · ", h("a", { href: d.bio.url, target: "_blank", rel: "noopener noreferrer" }, "From Wikipedia"))) : null;
    const similar = d.similar?.length ? h("div", { class: "artist-similar" },
      h("span", { class: "artist-similar-label" }, "Similar artists"),
      h("div", { class: "artist-similar-list" }, d.similar.slice(0, 10).map((a) => h("button", {
        class: `artist-chip${a.folder ? " here" : ""}`, type: "button", onclick: () => goTo(a),
        title: a.folder ? "In your library" : "Songs they're on in your library",
      }, artistAvatar(a, 24), h("span", { dir: "auto" }, a.name))))) : null;
    const hint = !d.can?.bio && !d.can?.similar ? h("button", { class: "link-btn artist-hint", type: "button",
      onclick: () => openSettings("connections") }, icon("spark"), "Add a bio and similar artists (Settings → Connections)") : null;
    setKids(slot, bio, similar, hint);
  };
  const known = infoCache.get(`${folder}\u001f${currentLanguage()}`);
  if (known && !(known instanceof Promise)) fill(known);
  else artistInfo(folder).then((d) => { if (slot.isConnected || !known) fill(d); });
  return h("div", { class: "album-head artist-head" },
    artistAvatar({ name: f.name, folder }, 168),
    h("div", { class: "artist-title" },
      h("h1", { dir: "auto", translate: "no" }, f.name),
      h("p", { class: "album-meta" }, counts.join(" · ") || plural(f.folders.length, "folder"))),
    slot);
}
