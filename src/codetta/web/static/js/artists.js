// Tapping an artist name: go to that artist, or pick one when the credit names several
// ("Justice & Michael McDonald"). Only artists the library has are offered (see core/artists.py).
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { h } from "./dom.js";
import { api } from "./api.js";
import { toast } from "./state.js";
import { SEARCH, navigate } from "./browse.js";
import { openToolsMenu } from "./tools.js";

/** Where an artist lives: their folder at the top of the library, or a search for their songs. */
function goTo(a) {
  if (a.folder) navigate(a.folder);
  else navigate(SEARCH + `artist: ${a.name.replace(/[,;]/g, " ").replace(/\s+/g, " ").trim()}`);
}

/** ``credits``: the artist values to look at (a track's artists, an album's album artist). */
export async function openArtist(anchor, credits, before = () => {}) {
  const list = [...new Set(credits.map((c) => (c || "").trim()).filter(Boolean))];
  if (!list.length) return;
  let found = [];
  try {
    const q = list.map((c) => `credit=${encodeURIComponent(c)}`).join("&");
    found = (await api("GET", `/api/artists?${q}`)).artists || [];
  } catch (err) { toast(err.message, "error"); return; }
  if (!found.length) { toast(`No artist from “${list.join(", ")}” has a folder or songs of their own in your library.`); return; }
  if (found.length === 1) { before(); goTo(found[0]); return; }
  openToolsMenu(anchor, found.map((a) => ({
    icon: a.folder ? "folder" : "user", label: a.name, run: () => { before(); goTo(a); },
  })));
}

/** An artist name that can be tapped. */
export function artistButton(text, credits, { cls = "", before } = {}) {
  return h("button", {
    class: `artist-link ${cls}`.trim(), type: "button", dir: "auto", translate: "no",
    title: "Go to this artist",
    onclick: (e) => { e.stopPropagation(); openArtist(e.currentTarget, credits, before); },
  }, text);
}
