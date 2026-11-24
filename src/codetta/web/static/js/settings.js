// Settings: every setting in one place. Sections down the left on a computer, a list you tap into
// on a phone, and a search box that finds any setting by name.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, closeDialog, h, icon, openDialog, setKids } from "./dom.js";
import { state, toast } from "./state.js";
import { t as tr } from "./i18n.js";
import { getTheme, setTheme } from "./theme.js";
import { isPhone, folderView, setFolderView } from "./tools.js";
import { setAdvanced, stopLogPolling } from "./editor.js";
import { autoplayOn, setAutoplay } from "./player.js";
import { syncAccountSettings, syncAccountTiles } from "./account.js";
import { confidenceChooser, loadConnections, renderConnections } from "./setup.js";
import { careSettings, healthSettings, patternSettings } from "./library.js";
import { editionSettings } from "./musicbrainz.js";
import { inboxSettings } from "./inbox.js";

const SECTIONS = [
  { id: "general", title: "General", icon: "gear", sub: "Theme, language, your account" },
  { id: "library", title: "Library", icon: "folder", sub: "File names, Tidy up, editions, health" },
  { id: "inbox", title: "Inbox", icon: "inbox", sub: "Where new music lands, automatic filing" },
  { id: "listening", title: "Listening", icon: "autoplay", sub: "Autoplay, folder view, ListenBrainz" },
  { id: "apps", title: "Music apps & server", icon: "note", sub: "Subsonic apps like Symfonium, and your Navidrome, Jellyfin or Plex" },
  { id: "connections", title: "Connections", icon: "spark", sub: "Tags, covers, lyrics and downloads from online" },
  { id: "about", title: "About", icon: "info", sub: "Version, updates, help" },
];
const sectionOf = (id) => SECTIONS.find((s) => s.id === id);

const set = { current: null, depth: 0, drawn: new Set() };
const dialog = () => $("#settings-dialog");

// ---- Small pieces ----------------------------------------------------------------------------------

const browserOnly = () => h("span", { class: "set-badge", title: tr("Saved in this browser only, so each device can differ") }, "This browser");

function row(title, sub, control, { keys = "", local = false } = {}) {
  return h("div", { class: "switch-row set-row", "data-keys": keys },
    h("span", { class: "switch-text" },
      h("span", { class: "switch-title" }, title, local ? browserOnly() : null),
      sub ? h("span", { class: "switch-sub" }, sub) : null),
    control);
}

function segmented(name, options, value, onPick) {
  const box = h("div", { class: "segmented set-seg", role: "radiogroup", "aria-label": name });
  const draw = (v) => setKids(box, options.map(([id, label]) => h("button", {
    type: "button", role: "radio", "aria-checked": String(id === v), class: id === v ? "active" : "",
    onclick: () => { draw(id); onPick(id); } }, label)));
  draw(value);
  return box;
}

function toggle(on, onChange) {
  const input = h("input", { type: "checkbox", role: "switch", checked: on });
  input.addEventListener("change", () => onChange(input.checked));
  return input;
}

// ---- What each section draws (the rest is markup in index.html, filled by its own module) -------------

function drawGeneral() {
  setKids($("#set-general"),
    row("Theme", "Automatic follows your device's light or dark mode.",
      segmented("Theme", [["system", "Automatic"], ["light", "Light"], ["dark", "Dark"]], getTheme(),
        (v) => { setTheme(v); syncAccountTiles(); }), { keys: "theme dark light mode appearance", local: true }),
    row("Advanced", "Shows how each tag is stored in the file, and the server log (under About).",
      toggle(state.advanced, (on) => { setAdvanced(on); syncAccountTiles(); toast(on ? "Advanced mode on" : "Advanced mode off"); }),
      { keys: "advanced raw tags native names log debug", local: true }));
  syncAccountSettings();
}

async function fill(sel, build) {
  const box = $(sel);
  setKids(box, h("p", { class: "loading set-pad" }, "Loading…"));
  const el = await build();
  setKids(box, el);
}

function drawLibrary() {
  return Promise.all([
    fill("#set-pattern", patternSettings),
    fill("#set-care", careSettings),
    fill("#set-confidence", () => h("div", { class: "set-pad" }, confidenceChooser("settings"))),
    fill("#set-editions", editionSettings),
    fill("#set-health", healthSettings),
  ]);
}

function drawListening() {
  setKids($("#set-listening"),
    row("Autoplay", "When your queue ends, similar songs keep playing. Codetta finds them with AudioMuse-AI or ListenBrainz (below) or Deezer (in Connections), whichever is on.",
      toggle(autoplayOn(), setAutoplay), { keys: "autoplay similar radio keep playing queue", local: true }),
    row("Folders", "How folders are shown when you browse your library.",
      segmented("Folders", [["list", "List"], ["grid", "Grid"]], folderView(), setFolderView),
      { keys: "view list grid folders layout", local: true }));
}

const DRAW = {
  general: drawGeneral,
  library: drawLibrary,
  inbox: () => fill("#set-inbox", inboxSettings),
  listening: drawListening,
};

async function draw(id) {
  if (set.drawn.has(id) || !DRAW[id]) return;
  set.drawn.add(id);
  await DRAW[id]();
}

// ---- Showing a section --------------------------------------------------------------------------------

function renderNav() {
  setKids($("#set-nav-list"), SECTIONS.map((s) => h("button", {
    type: "button", class: "set-nav-item", role: "listitem", "data-section": s.id,
    "aria-current": set.current === s.id ? "page" : null, onclick: () => go(s.id) },
  h("span", { class: "set-nav-ico", "aria-hidden": "true" }, icon(s.icon)),
  h("span", { class: "set-nav-text" }, h("span", { class: "set-nav-title" }, s.title), h("span", { class: "set-nav-sub" }, s.sub)),
  icon("chevron"))));
}

function flash(el) {
  if (!el) return;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  el.classList.remove("set-flash");
  void el.offsetWidth;
  el.classList.add("set-flash");
  setTimeout(() => el.classList.remove("set-flash"), 1800);
}

async function showSection(id, target = null) {
  set.current = id;
  const d = dialog();
  d.classList.toggle("in-section", !!id);
  $("#set-results").hidden = true;
  for (const sec of d.querySelectorAll(".set-section")) sec.hidden = sec.dataset.section !== id;
  $("#set-title").textContent = id ? tr(sectionOf(id).title) : "";
  for (const b of $("#set-nav-list").children) b.setAttribute("aria-current", b.dataset.section === id ? "page" : "false");
  if (!id) return;
  $("#set-body").scrollTop = 0;
  await draw(id);
  if (target) flash(typeof target === "string" ? $(`#${target}`) : target);
}

/** Open a section: on a phone it's a step you can go Back from. */
function go(id, target = null) {
  if (isPhone() && set.current !== id) {
    history.pushState({ settings: id }, "");
    set.depth += 1;
  }
  $("#set-search").value = "";
  showSection(id, target);
}

/** Open Settings, at a section (and a setting in it) if given. Closes whatever dialog is open first. */
export async function openSettings(section = null, target = null) {
  const d = dialog();
  const others = [...document.querySelectorAll("dialog[open]")].filter((x) => x !== d);
  if (others.length) {
    others.forEach(closeDialog);
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!d.open) {
    set.drawn.clear();
    set.current = null;
    set.depth = 0;
    $("#set-search").value = "";
    renderNav();
    renderConnections();
    loadConnections().then(renderConnections); // pick up changes from other devices
    openDialog(d);
    history.pushState({ settings: "root" }, "");
    set.depth = 1;
  }
  const id = section || (isPhone() ? null : set.current || "general");
  if (id && isPhone() && set.current !== id) {
    history.pushState({ settings: id }, "");
    set.depth += 1;
  }
  await showSection(id, target);
}

export function closeSettings() {
  if (set.depth > 0) { history.go(-set.depth); return; } // the popstate below closes it
  closeDialog(dialog());
}

function onPop() {
  const d = dialog();
  if (!d.open) return;
  const where = history.state?.settings;
  if (!where) { set.depth = 0; stopLogPolling(); closeDialog(d); return; }
  set.depth = Math.max(0, set.depth - 1);
  showSection(where === "root" ? (isPhone() ? null : set.current || "general") : where);
}

// ---- Search ----------------------------------------------------------------------------------------------

async function search(q) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const results = $("#set-results");
  const d = dialog();
  if (!words.length) { showSection(set.current || (isPhone() ? null : "general")); return; }
  await Promise.all(SECTIONS.map((s) => draw(s.id)));
  const found = [];
  for (const sec of d.querySelectorAll(".set-section")) {
    const cands = [...sec.querySelectorAll("[data-keys], .switch-row, .conn-row, label.field")]
      .filter((el) => !el.closest("[hidden]:not(.set-section)") && el.textContent.trim());
    const hit = cands.filter((el) => {
      const text = `${el.textContent} ${el.dataset.keys || ""}`.toLowerCase();
      return words.every((w) => text.includes(w));
    });
    for (const el of hit) {
      if (hit.some((o) => o !== el && el.contains(o))) continue; // the most specific match only
      found.push({ section: sec.dataset.section, el });
    }
  }
  const titleOf = (el) => {
    const head = el.dataset.keys && el.previousElementSibling?.matches("h3.set-group") ? el.previousElementSibling : null;
    if (head) return head.textContent;
    const own = el.querySelector(".switch-title, .field-label, .conn-name");
    if (own) return own.textContent.replace(tr("This browser"), "").trim();
    let prev = el.previousElementSibling;
    while (prev && !prev.matches("h3.set-group")) prev = prev.previousElementSibling;
    return prev?.textContent || tr(sectionOf(el.closest(".set-section").dataset.section).title);
  };
  for (const sec of d.querySelectorAll(".set-section")) sec.hidden = true;
  d.classList.add("in-section");
  $("#set-title").textContent = tr("Search");
  results.hidden = false;
  setKids(results, found.length ? h("div", { class: "set-card" }, found.slice(0, 30).map((f) => h("button", {
    type: "button", class: "set-result", onclick: () => { $("#set-search").value = ""; go(f.section, f.el); } },
  h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, titleOf(f.el)),
    h("span", { class: "switch-sub" }, tr(sectionOf(f.section).title))), icon("chevron"))))
    : h("p", { class: "hint set-lead" }, `Nothing in Settings matches “${q}”.`));
}

// ---- Wiring ---------------------------------------------------------------------------------------------

export function setupSettings() {
  const d = dialog();
  d.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]") || e.target === d) closeSettings();
  });
  d.addEventListener("cancel", (e) => { e.preventDefault(); closeSettings(); });
  d.addEventListener("close", stopLogPolling);
  window.addEventListener("popstate", onPop);
  $("#set-back").addEventListener("click", () => {
    if (set.depth > 1) history.back();
    else showSection(null);
  });
  let timer = null;
  $("#set-search").addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => search(e.target.value.trim()), 120); });
  $("#open-settings").addEventListener("click", () => openSettings());
  $("#cc-update").addEventListener("click", () => openSettings("about"));
}
