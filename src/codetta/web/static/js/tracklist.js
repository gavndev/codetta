// Paste a tracklist: titles (and numbers, discs, artists) from text copied from Discogs, Bandcamp,
// Wikipedia or a .txt, paired with an album's files. Part of Codetta's page; app.js is the entry point.

import { $, closeDialog, h, openDialog, setKids } from "./dom.js";
import { api } from "./api.js";
import { changeLine, plural, state, toast } from "./state.js";
import { folderCache, loadFolder } from "./browse.js";
import { refreshActivity } from "./activity.js";
import { fieldLabel } from "./editor.js";
import { t as tr } from "./i18n.js";

const tl = { target: null, label: "", timer: null, token: 0, artist: null, el: {} };

export function openTracklist(target, label) {
  tl.target = target; tl.label = tr(label); tl.artist = null;
  const el = tl.el;
  el.text = h("textarea", { rows: "9", class: "tl-text", spellcheck: "false", "aria-label": "Tracklist",
    placeholder: "1. Airbag 4:44\n2. Paranoid Android 6:23\n3. Subterranean Homesick Alien 4:27" });
  el.artist = h("input", { type: "checkbox" });
  el.numbers = h("input", { type: "checkbox", checked: true });
  el.text.addEventListener("input", () => previewSoon());
  el.artist.addEventListener("change", () => { tl.artist = el.artist.checked; previewSoon(0); });
  el.numbers.addEventListener("change", () => previewSoon(0));
  setKids($("#tl-body"),
    h("p", { class: "mb-lead" }, `Paste the tracklist of ${tl.label}, one track per line, from Discogs, Bandcamp, Wikipedia or anywhere. Codetta pairs each line with a file and shows every change before anything is written.`),
    el.text,
    h("div", { class: "rep-options" },
      h("label", { class: "rep-check" }, el.artist, "Lines start with the artist (Artist – Title)"),
      h("label", { class: "rep-check" }, el.numbers, "Set track numbers too")),
    h("div", { class: "rep-preview", id: "tl-preview" }, h("p", { class: "hint" }, "Paste a tracklist to see how it pairs with the files.")));
  setKids($("#tl-foot"), h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", id: "tl-apply", disabled: true, onclick: apply }, "Write titles"));
  openDialog($("#tl-dialog"));
  el.text.focus();
}

function body(dry) {
  return { ...tl.target, text: tl.el.text.value, artist_first: tl.artist, numbers: tl.el.numbers.checked, dry_run: dry };
}

function previewSoon(wait = 350) {
  clearTimeout(tl.timer);
  tl.timer = setTimeout(preview, wait);
}

const name = (p) => p.split("/").pop();

async function preview() {
  const box = $("#tl-preview");
  const go = $("#tl-apply");
  const token = ++tl.token;
  if (!tl.el.text.value.trim()) {
    go.disabled = true;
    setKids(box, h("p", { class: "hint" }, "Paste a tracklist to see how it pairs with the files."));
    return;
  }
  setKids(box, h("p", { class: "hint mbx-wait" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Looking…"));
  try {
    const d = await api("POST", "/api/tags/tracklist", body(true));
    if (token !== tl.token) return;
    if (tl.artist === null) tl.el.artist.checked = d.artist_first; // what Codetta worked out, until you choose
    go.disabled = !d.changing;
    go.textContent = d.changing ? `Write ${plural(d.changing, "track")}` : "Write titles";
    const mismatch = d.lines !== d.tracks;
    setKids(box,
      h("p", { class: "rep-count" }, changeLine(d)),
      mismatch ? h("p", { class: "field-error" }, `The tracklist has ${plural(d.lines, "line")} and the folder has ${plural(d.tracks, "track")}. Check the pairs below before writing.`) : null,
      d.warnings ? h("p", { class: "field-error" }, `${plural(d.warnings, "pair")} with very different lengths: probably not the same song.`) : null,
      h("ul", { class: "rep-list" }, d.preview.map((p) => h("li", { class: p.warning ? "tl-warn" : null },
        h("span", { class: "rep-file", dir: "auto" }, name(p.path)),
        p.line ? h("span", { class: "tl-line", dir: "auto" }, p.line) : null,
        p.changes.map((ch) => h("span", { class: "rep-change" }, h("b", {}, fieldLabel(ch.key)), " ",
          ch.old ? [h("del", { dir: "auto" }, ch.old), " → "] : null, h("ins", { dir: "auto" }, ch.new))),
        p.warning ? h("span", { class: "field-error" }, p.warning) : null))),
      d.leftover.length ? h("p", { class: "hint" }, `Lines without a file: ${d.leftover.slice(0, 5).join(" · ")}${d.leftover.length > 5 ? "…" : ""}`) : null);
  } catch (err) {
    if (token !== tl.token) return;
    go.disabled = true;
    setKids(box, h("p", { class: "field-error" }, err.message));
  }
}

async function apply() {
  const go = $("#tl-apply");
  go.disabled = true; go.textContent = "Writing…";
  try {
    const d = await api("POST", "/api/tags/tracklist", body(false));
    closeDialog($("#tl-dialog"));
    toast(d.failed ? `Changed ${d.changed}, ${d.failed} couldn't be changed` : `Wrote ${plural(d.changed, "track")}. Undo is in Activity.`,
      d.failed ? "error" : "success");
    folderCache.clear();
    refreshActivity();
    loadFolder(state.path, { keepScroll: true });
  } catch (err) {
    toast(err.message, "error");
    go.disabled = false; go.textContent = "Write titles";
  }
}
