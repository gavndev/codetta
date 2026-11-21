// Library health, Tidy up and Organize.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, closeDialog, h, icon, openDialog, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, plural, state, toast } from "./state.js";
import { folderCache, loadFolder, navigate, renderSelectionBar } from "./browse.js";
import { setBang } from "./search.js";
import { folderCovers } from "./tools.js";
import { confirmDiscard } from "./editor.js";
import { refreshActivity } from "./activity.js";
import { connectionOn } from "./setup.js";
import { openMusicBrainzFor } from "./musicbrainz.js";
import { skReady } from "./inbox.js";

// ---- Library health -----------------------------------------------------------------------------------
//
// A card on the Library page ("23 things to look at"), opening a sheet with
// every issue the checks found, one-tap fixes where they're obvious, and a
// switch for each check.

const health = { summary: null, at: 0, data: null, filter: "all", view: "issues", busy: false };
const HEALTH_ICON = { splits: "rows", tracks: "disc", covers: "note", tags: "alert" };

export async function updateHealthSlot(force = false) {
  updateCareSlot();
  const slot = $("#health-slot");
  const atRoot = state.folder && !state.folder.search && state.path === "";
  if (!atRoot) { slot.hidden = true; return; }
  if (force || !health.summary || Date.now() - health.at > 30000) {
    try { health.summary = await api("GET", "/api/library-health/summary"); health.at = Date.now(); } catch { slot.hidden = true; return; }
  }
  const s = health.summary;
  if (s.enabled === false) { slot.hidden = true; return; }
  const sub = s.indexing && !s.count ? "Reading your library…"
    : s.count ? `${plural(s.count, "thing")} to look at` : "All good";
  setKids(slot, h("button", { class: `health-card${s.count ? " has-issues" : ""}`, type: "button", onclick: () => openHealth() },
    h("span", { class: "health-card-icon" }, icon("pulse")),
    h("span", { class: "health-card-text" }, h("strong", {}, "Library health"), h("span", {}, sub)),
    s.count ? h("span", { class: "health-card-count" }, String(s.count > 999 ? "999+" : s.count)) : null,
    icon("chevron")));
  slot.hidden = false;
}

// ---- Tidy up (internally "library care"): tagging and organizing the existing library, gradually ---------------------------

const CARE_MODES = [
  { mode: "off", title: "Leave my files alone", short: "Off", sub: "Codetta won't change anything on its own." },
  { mode: "tags", title: "Fix tags only", short: "Fixing tags", sub: "Codetta looks up each album and fixes its tags (names, artists, years, covers). File names and folders stay the same." },
  { mode: "full", title: "Fix tags, names and folders", short: "Fixing tags, names and folders", sub: "Codetta fixes the tags, then renames the files and puts each album in a tidy folder." },
];
let care = null;
const careMode = (m) => CARE_MODES.find((x) => x.mode === m) || CARE_MODES[0];
const clock = (t) => new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

async function loadCare() {
  try { care = await api("GET", "/api/library-care"); } catch { care = null; }
  const sub = $("#care-sub");
  if (sub && care) sub.textContent = careMode(care.mode).short;
  return care;
}

/** Where Tidy up is, in a few plain words. */
function careStatus(c) {
  const of = `${c.done} of ${plural(c.total, "album")}`;
  if (c.paused) return { text: `Paused · ${of} checked`, busy: false };
  if (c.finished && c.done >= c.total) return { text: `Finished · all ${plural(c.total, "album")} checked`, busy: false };
  if (c.running) return { text: `Working · ${of} checked`, busy: true };
  return { text: `Getting ready · ${of} checked`, busy: true };
}

function careBar(c) {
  const pct = c.total ? Math.round((c.done / c.total) * 100) : 0;
  const bar = h("div", { class: "care-bar", role: "progressbar", "aria-label": "Tidy up progress",
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct) }, h("span", {}));
  bar.firstChild.style.width = `${Math.max(c.done ? 2 : 0, pct)}%`;
  return bar;
}

async function updateCareSlot() {
  const slot = $("#care-slot");
  await loadCare();
  if (!care || care.mode === "off" || state.path !== "" || state.folder?.search) { slot.hidden = true; return; }
  const st = careStatus(care);
  const need = care.counts.review + care.counts.error;
  setKids(slot, h("button", { class: `health-card care-card${need ? " has-issues" : ""}`, type: "button", onclick: openCare },
    h("span", { class: "health-card-icon" }, icon("layers")),
    h("span", { class: "health-card-text" }, h("strong", {}, "Tidy up"), h("span", {}, st.text),
      st.busy || care.paused ? careBar(care) : null),
    need ? h("span", { class: "health-card-count", title: "Need you" }, String(need)) : null,
    icon("chevron")));
  slot.hidden = false;
  clearTimeout(updateCareSlot.t);
  // Every few seconds while it works; once a minute otherwise (new albums can start it again).
  updateCareSlot.t = setTimeout(() => { if (!$("#care-slot").hidden && !document.hidden) updateCareSlot(); }, st.busy ? 5000 : 60000);
}

export function careChoices(current) {
  let chosen = current;
  const box = h("fieldset", { class: "choices" }, CARE_MODES.map((m) => h("label", { class: "choice" },
    h("input", { type: "radio", name: "care-mode", value: m.mode, checked: m.mode === current, onchange: () => { chosen = m.mode; } }),
    h("span", { class: "choice-body" }, h("span", { class: "choice-title" }, m.title), h("span", { class: "choice-sub" }, m.sub)))));
  return { box, value: () => chosen };
}

/** Before names and folders change for the first time: show a few albums' before → after, and ask. */
export async function previewFullCare() {
  let d;
  try { d = await api("GET", "/api/library-care/preview?albums=3"); } catch (err) { toast(err.message, "error"); return false; }
  const name = (p) => p.split("/").slice(-3).join(" / ");
  const list = d.albums.length ? h("div", { class: "care-preview" }, d.albums.map((a) => h("div", { class: "care-preview-album" },
    h("strong", { dir: "auto" }, a.folder.split("/").pop() || a.folder),
    a.examples.map((x) => h("div", { class: "care-preview-move" },
      h("span", { class: "from", dir: "auto" }, name(x.from)), h("span", { class: "arrow", "aria-hidden": "true" }, "↓"),
      h("span", { class: "to", dir: "auto" }, name(x.to)))),
    a.moving > a.examples.length ? h("span", { class: "hint" }, `and ${plural(a.moving - a.examples.length, "more song")}`) : null)))
    : h("p", { class: "hint" }, "Your files already follow your folder pattern, so only tags will change for now.");
  return ask({ title: "Here's how it will look", confirmLabel: "Start", cancelLabel: "Not yet", details: list,
    message: "A few of your albums, renamed with your folder pattern (Organize settings). Codetta checks each album online first and only moves the ones it's sure about. Every change can be undone in Activity." });
}

export async function chooseCare() {
  await loadCare();
  const pick = careChoices(care?.mode || "off");
  const ok = await ask({ title: "Tidy up", details: pick.box, confirmLabel: "Save",
    message: "Codetta goes through your music one album at a time. It only changes an album when it's sure it found the right one, and you can undo anything in Activity." });
  if (!ok) return;
  if (pick.value() === "full" && care?.mode !== "full" && !(await previewFullCare())) return;
  try { care = await api("PUT", "/api/library-care", { mode: pick.value(), paused: false }); toast("Saved", "success"); } catch (err) { toast(err.message, "error"); }
  updateCareSlot();
}

async function openCare() {
  await loadCare();
  if (!care) return;
  const st = careStatus(care);
  const n = care.counts;
  const fixed = n.tagged + n.organized;
  const need = n.review + n.error;
  const stat = (num, label, cls = "") => h("div", { class: `care-stat ${cls}` }, h("strong", {}, String(num)), h("span", {}, label));
  const when = [care.started ? `Started ${clock(care.started)}` : null,
    care.finished && care.done >= care.total ? `Finished ${clock(care.finished)}` : care.current && st.busy ? `Now: ${care.current.split("/").pop()}` : null].filter(Boolean).join(" · ");
  const list = care.review.length ? h("ul", { class: "care-review" }, care.review.map((r) => h("li", {},
    h("span", { class: "care-folder", dir: "auto" }, h("strong", {}, r.folder.split("/").pop() || r.folder), h("span", {}, r.note)),
    h("button", { class: "btn small", type: "button", onclick: () => { closeDialog($("#confirm-dialog")); navigate(r.folder); } }, "Open"),
    h("button", { class: "link-btn", type: "button", onclick: async (e) => {
      care = await api("POST", "/api/library-care/again", { folder: r.folder });
      e.target.closest("li").remove(); toast("Codetta will try it again");
    } }, "Try again"),
    h("button", { class: "link-btn", type: "button", title: "Leave this one alone: it won't be tidied or listed again", onclick: async () => {
      try { care = await api("POST", "/api/library-care/ignore", { folder: r.folder, ignore: true }); } catch (err) { toast(err.message, "error"); return; }
      closeDialog($("#confirm-dialog")); updateCareSlot(); setTimeout(openCare, 250);
      toast(`Dismissed “${r.folder.split("/").pop() || r.folder}”. It's under Dismissed if you want it back.`, "success");
    } }, "Dismiss"))))
    : null;
  const dismissAll = need > 1 ? h("button", { class: "link-btn", type: "button", onclick: async () => {
    if (!(await ask({ title: `Dismiss all ${need}?`, confirmLabel: "Dismiss all",
      message: "Tidy up will leave these albums alone and stop listing them. You can bring any of them back from Dismissed." }))) { setTimeout(openCare, 250); return; }
    try { care = await api("POST", "/api/library-care/ignore", { all: true }); } catch (err) { toast(err.message, "error"); return; }
    updateCareSlot(); setTimeout(openCare, 250); toast(`Dismissed ${plural(need, "album")}`, "success");
  } }, "Dismiss all") : null;
  const ignored = care.ignored?.length ? h("details", { class: "care-ignored" },
    h("summary", {}, `Dismissed (${care.ignored.length})`),
    h("ul", { class: "care-review" }, care.ignored.map((f) => h("li", {},
      h("span", { class: "care-folder", dir: "auto" }, h("strong", {}, f.split("/").pop() || f), f.includes("/") ? h("span", {}, f.slice(0, f.lastIndexOf("/"))) : null),
      h("button", { class: "link-btn", type: "button", onclick: async () => {
        try { care = await api("POST", "/api/library-care/ignore", { folder: f, ignore: false }); } catch (err) { toast(err.message, "error"); return; }
        closeDialog($("#confirm-dialog")); updateCareSlot(); setTimeout(openCare, 250);
        toast("Codetta will look at it again", "success");
      } }, "Show again")))))
    : null;
  const pause = h("button", { class: "btn small", type: "button", onclick: async () => {
    care = await api("PUT", "/api/library-care", { paused: !care.paused }); closeDialog($("#confirm-dialog")); updateCareSlot();
  } }, care.paused ? "Resume" : "Pause");
  const change = h("button", { class: "btn small", type: "button", onclick: () => { closeDialog($("#confirm-dialog")); setTimeout(chooseCare, 250); } }, "Change");
  const rerun = h("button", { class: "btn small", type: "button", disabled: st.busy, title: "Go through your whole library again", onclick: async () => {
    closeDialog($("#confirm-dialog"));
    const ok = await ask({ title: "Run Tidy up again?", confirmLabel: "Run again",
      message: "Codetta goes through your whole library again, from the start: albums you've fixed get another look, and new ones are included. Dismissed albums stay dismissed." });
    if (!ok) { setTimeout(openCare, 250); return; }
    try { care = await api("POST", "/api/library-care/rerun"); toast("Tidy up is going through your library again", "success"); }
    catch (err) { toast(err.message, "error"); }
    updateCareSlot();
  } }, "Run again");
  await ask({ title: "Tidy up", confirmLabel: "Done", cancelLabel: null,
    details: h("div", { class: "care-sheet" },
      h("p", { class: "care-mode" }, careMode(care.mode).title),
      h("div", { class: "care-progress" }, h("span", {}, st.text), careBar(care), when ? h("span", { class: "care-when" }, when) : null),
      h("div", { class: "care-stats" }, stat(fixed, "fixed"), stat(n.skipped, "already fine"), stat(need, "need you", need ? "warn" : "")),
      h("div", { class: "care-actions" }, pause, rerun, change),
      need ? h("div", { class: "care-need" },
        h("div", { class: "care-need-head" },
          h("h3", { class: "care-need-title" }, "Need you", h("span", { class: "care-need-count" }, String(need))), dismissAll),
        h("p", { class: "care-need-hint" }, "Codetta wasn't sure about these, so it left them alone. Open one to pick the right album, or dismiss it.")) : null,
      list, ignored) });
}

async function openHealth(view = "issues") {
  health.view = view;
  openDialog($("#health-dialog"));
  if (!health.data) setKids($("#health-body"), h("p", { class: "loading" }, "Checking your library…"));
  await loadHealth();
}

async function loadHealth() {
  try {
    health.data = await api("GET", `/api/library-health?category=${encodeURIComponent(health.filter)}`);
  } catch (err) {
    setKids($("#health-body"), h("div", { class: "error-box" }, err.message));
    return;
  }
  renderHealth();
}

function afterHealthChange(data) {
  health.data = data;
  health.summary = { count: data.count, indexing: data.indexing };
  health.at = Date.now();
  updateHealthSlot();
  renderHealth();
}

async function healthFix(issue) {
  const ok = await ask({ title: `${issue.fix.label}?`, message: `${issue.fix.summary} in “${issue.album}”. Activity can undo it.`,
    confirmLabel: "Fix" });
  if (!ok) return;
  try {
    const res = await api("POST", "/api/library-health/fix", { id: issue.id });
    toast(res.failed ? `Fixed ${res.fixed}, ${res.failed} couldn't be changed` : "Fixed", res.failed ? "error" : "success");
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    afterHealthChange(res.health);
  } catch (err) { toast(err.message, "error"); }
}

async function healthIgnoreAll() {
  const d = health.data;
  const n = d.shown_total ?? d.issues.length;
  const what = health.filter === "all" ? "" : ` ${(d.categories.find((c) => c.id === health.filter)?.label || "").toLowerCase()}`;
  if (!(await ask({ title: `Ignore all ${n.toLocaleString()}${what}?`, confirmLabel: "Ignore all",
    message: "They come off the list and stop counting. You can show any of them again from Ignored." }))) return;
  try {
    afterHealthChange(await api("POST", "/api/library-health/ignore-all", { category: health.filter }));
    toast(`Ignored ${plural(n, "issue")}`, "success");
  } catch (err) { toast(err.message, "error"); }
}

async function healthIgnore(issue, ignore = true) {
  try { afterHealthChange(await api("POST", "/api/library-health/ignore", { id: issue.id, ignore })); } catch (err) { toast(err.message, "error"); }
}

function healthItem(issue, ignored = false) {
  const check = health.data.checks.find((c) => c.id === issue.check);
  const btn = (label, onclick, primary = false) => h("button", { class: `btn small${primary ? " primary" : ""}`, type: "button", onclick }, label);
  const open = (folder) => { closeDialog($("#health-dialog")); navigate(folder); };
  const actions = [];
  if (!ignored) {
    if (issue.fix) actions.push(btn(issue.fix.label, () => healthFix(issue), true));
    actions.push(btn("Open", () => open(issue.folder), !issue.fix));
    if (issue.actions.includes("musicbrainz") && connectionOn("musicbrainz")) {
      actions.push(btn("Find in MusicBrainz", () => {
        closeDialog($("#health-dialog"));
        openMusicBrainzFor({ body: { folder: issue.folder }, label: `“${issue.album}”` }, { onWritten: () => { health.at = 0; updateHealthSlot(true); } });
      }));
    }
    if (issue.actions.includes("slskd") && skReady()) {
      actions.push(btn("Find in slskd", () => {
        closeDialog($("#health-dialog"));
        els.filter.value = [issue.artist, issue.album].filter(Boolean).join(" ");
        setBang(true, issue.folder);
        els.filter.focus();
      }));
    }
    actions.push(h("button", { class: "link-btn inbox-skip", type: "button", onclick: () => healthIgnore(issue) }, "Ignore"));
  } else {
    actions.push(btn("Show again", () => healthIgnore(issue, false)));
  }
  const detail = issue.folders
    ? h("div", { class: "health-folders" }, issue.folders.map((f) => h("button", { class: "link-btn", type: "button", dir: "auto", onclick: () => open(f) }, f)))
    : issue.detail.length ? h("details", { class: "sk-files" }, h("summary", {}, "Details"),
      h("ul", {}, issue.detail.map((d) => h("li", { dir: "auto" }, d)), issue.more ? h("li", {}, `and ${issue.more} more`) : null)) : null;
  return h("div", { class: `inbox-item health-item ${issue.category}` },
    h("span", { class: "mb-thumb mb-noart health-thumb", "aria-hidden": "true" }, icon(HEALTH_ICON[issue.category] || "alert")),
    h("div", { class: "inbox-main" },
      h("div", { class: "inbox-title", dir: "auto" }, issue.album, issue.artist ? h("span", { class: "inbox-artist" }, ` · ${issue.artist}`) : null),
      h("div", { class: "mb-cand-meta", dir: "auto" }, issue.folder || "Library"),
      h("div", { class: "inbox-status" },
        h("span", { class: "inbox-chip review" }, check?.label || issue.check),
        h("span", { class: "inbox-note" }, issue.message)),
      detail),
    h("div", { class: "inbox-actions" }, actions));
}

/** Switch the whole of Library health on or off (Account, the Checks view, setup). */
export async function setHealthEnabled(on) {
  const data = await api("PUT", "/api/library-health/settings", { enabled: on });
  health.data = data;
  health.summary = { enabled: on, count: data.count, indexing: data.indexing };
  health.at = Date.now();
  const toggle = $("#health-toggle");
  if (toggle) toggle.checked = on;
  updateHealthSlot();
  return data;
}

function healthMasterSwitch() {
  const input = h("input", { type: "checkbox", role: "switch", checked: true });
  input.addEventListener("change", async () => {
    input.disabled = true;
    try {
      await setHealthEnabled(input.checked);
      closeDialog($("#health-dialog"));
      toast("Library health is off. Switch it back on in Account.");
    } catch (err) { input.checked = !input.checked; toast(err.message, "error"); input.disabled = false; }
  });
  return h("label", { class: "switch-row health-master" },
    h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, "Library health"),
      h("span", { class: "switch-sub" }, "Off: no card on the Library page and nothing is checked. Handy if your library is named exactly the way you want it.")),
    input);
}

function renderHealthSettings() {
  const d = health.data;
  return h("div", { class: "health-settings" },
    healthMasterSwitch(),
    h("p", { class: "mb-lead" }, "Choose what Library health looks for. Switched-off checks are skipped; you can switch them back on any time."),
    d.categories.map((cat) => h("section", { class: "health-cat" },
      h("h3", { class: "field-label" }, cat.label),
      d.checks.filter((c) => c.category === cat.id).map((c) => {
        const input = h("input", { type: "checkbox", role: "switch", checked: c.enabled });
        input.addEventListener("change", async () => {
          const disabled = d.checks.filter((x) => (x.id === c.id ? !input.checked : !x.enabled)).map((x) => x.id);
          input.disabled = true;
          try { afterHealthChange(await api("PUT", "/api/library-health/settings", { disabled })); }
          catch (err) { input.checked = !input.checked; toast(err.message, "error"); }
        });
        return h("label", { class: "switch-row" },
          h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, c.label), h("span", { class: "switch-sub" }, c.about)),
          input);
      }))));
}

function renderHealth() {
  const d = health.data;
  const body = $("#health-body");
  const close = h("button", { class: "btn", type: "button", "data-close": true }, "Close");
  const tab = (view, label) => h("button", { class: `btn small${health.view === view ? " primary" : ""}`, type: "button",
    "aria-pressed": String(health.view === view), onclick: () => { health.view = health.view === view ? "issues" : view; renderHealth(); } }, label);
  setKids($("#health-foot"),
    tab("settings", "Checks"),
    d.ignored_total || health.view === "ignored" ? tab("ignored", `Ignored (${(d.ignored_total ?? d.ignored.length).toLocaleString()})`) : null,
    h("span", { class: "spacer" }), close);
  if (health.view === "settings") { setKids(body, renderHealthSettings()); return; }
  if (health.view === "ignored") {
    setKids(body, h("p", { class: "mb-lead" }, d.ignored.length ? "Issues you chose to ignore. Show one again to put it back on the list." : "Nothing ignored."),
      d.ignored.length ? h("div", { class: "inbox-list" }, d.ignored.map((i) => healthItem(i, true))) : null);
    return;
  }
  // The server sends a page of issues for the chosen kind; "Show more" asks for the next.
  const shown = d.issues;
  const chip = (id, label, count) => h("button", { class: `health-chip${health.filter === id ? " on" : ""}`, type: "button",
    "aria-pressed": String(health.filter === id), onclick: () => { health.filter = id; loadHealth(); } }, label, h("span", {}, String(count)));
  const more = shown.length < (d.shown_total ?? shown.length)
    ? h("button", { class: "btn health-more", type: "button", onclick: async (e) => {
      const b = e.currentTarget; b.disabled = true; b.textContent = "Loading…";
      try {
        const have = health.data.issues.length; // counted now: Show more can be pressed again and again
        const next = await api("GET", `/api/library-health?category=${encodeURIComponent(health.filter)}&offset=${have}`);
        health.data.issues = health.data.issues.concat(next.issues);
        const list = $("#health-body .health-list");
        if (list) {
          list.append(...next.issues.map((i) => healthItem(i)));
          const left = d.shown_total - health.data.issues.length;
          if (left > 0) { b.disabled = false; b.textContent = `Show more (${left.toLocaleString()} left)`; } else b.remove();
        } else renderHealth();
      } catch (err) { toast(err.message, "error"); b.disabled = false; b.textContent = "Show more"; }
    } }, `Show more (${(d.shown_total - shown.length).toLocaleString()} left)`) : null;
  setKids(body,
    h("p", { class: "mb-lead" },
      d.indexing ? "Codetta is still reading your library, so this list may grow. " : "",
      d.count ? `${plural(d.count, "thing")} to look at across ${plural(d.albums, "album")}.`
        : `Nothing to fix across ${plural(d.albums, "album")}. Your library looks healthy.`,
      d.unmatched ? ` ${plural(d.unmatched, "album")} ${d.unmatched === 1 ? "isn't" : "aren't"} matched on MusicBrainz yet (Find in MusicBrainz on an album does it).` : ""),
    d.count ? h("div", { class: "health-chips", role: "group", "aria-label": "Show" },
      chip("all", "All", d.count),
      d.categories.filter((c) => c.count).map((c) => chip(c.id, c.label, c.count))) : null,
    (d.shown_total ?? shown.length) > 1 ? h("div", { class: "health-bulk" }, h("button", { class: "link-btn", type: "button", onclick: healthIgnoreAll },
      health.filter === "all" ? "Ignore all" : `Ignore all ${(d.categories.find((c) => c.id === health.filter)?.label || "").toLowerCase()}`)) : null,
    shown.length ? h("div", { class: "inbox-list health-list" }, shown.map((i) => healthItem(i))) : null,
    more);
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

export async function openOrganize() {
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
  const patterns = h("select", { "aria-label": "Start from a pattern" },
    h("option", { value: "" }, "Patterns…"),
    org.settings.presets.map((p) => h("option", { value: p.pattern }, p.name)));
  patterns.addEventListener("change", () => {
    if (!patterns.value) return;
    input.value = org.pattern = patterns.value;
    patterns.value = "";
    orgExample();
    orgPreview(0);
  });
  setKids($("#organize-body"),
    h("p", { class: "mb-lead" }, `Rename and move the audio files in ${target.label} into folders from their tags. You'll see every move first, nothing is ever overwritten, and it can all be undone.`),
    h("div", { class: "field" },
      h("span", { class: "field-label" }, "Pattern"),
      h("div", { class: "org-pattern-row" }, input, patterns),
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
  const kept = p.moves.filter((m) => m.status === "keep");
  const byLidarr = p.moves.filter((m) => m.status === "lidarr");
  const summary = [];
  if (moving.length) summary.push(`${plural(moving.length, "file")} will move${p.extras ? `, plus ${plural(p.extras, "other file")} that come${p.extras === 1 ? "s" : ""} along (cover, lyrics, booklet…)` : ""}.`);
  else summary.push(c.same ? "Everything is already where this pattern puts it." : "Nothing to move.");
  if (c.same && moving.length) summary.push(`${plural(c.same, "file")} already in place.`);
  if (problems.length) summary.push(`${plural(problems.length, "file")} can't move (see below).`);
  if (kept.length) summary.push(`${plural(kept.length, "file")} ${kept.length === 1 ? "stays" : "stay"} where ${kept.length === 1 ? "it is" : "they are"}: not enough tags to place ${kept.length === 1 ? "it" : "them"} (find ${kept.length === 1 ? "its" : "their"} details first).`);
  if (byLidarr.length) summary.push(`${plural(byLidarr.length, "file")} ${byLidarr.length === 1 ? "stays" : "stay"} where ${byLidarr.length === 1 ? "it is" : "they are"}: Lidarr names the files in its folders (Account → Connections → Lidarr).`);
  const unknown = moving.filter((m) => /(^|\/)Unknown (Artist|Album)\//.test(m.dst)).length;
  const warn = unknown ? h("p", { class: "org-warn" }, `${plural(unknown, "file")} ${unknown === 1 ? "has" : "have"} no artist or album tag, so ${unknown === 1 ? "it" : "they"} would go to “Unknown Artist” / “Unknown Album”. Tag ${unknown === 1 ? "it" : "them"} first (Find in MusicBrainz can help), or move them anyway.`) : null;
  const row = (m) => h("div", { class: `org-move ${m.status}` },
    h("div", { class: "org-from", dir: "auto" }, m.src),
    h("div", { class: "org-to", dir: "auto" }, ["error", "keep", "lidarr"].includes(m.status) ? "" : ["→ ", m.dst]),
    m.reason ? h("div", { class: "note" }, m.reason) : null,
    m.companions.length ? h("div", { class: "note" }, `+ ${m.companions.map((x) => x.src.split("/").pop()).join(", ")}`) : null);
  const shown = [...problems, ...kept, ...byLidarr, ...moving].slice(0, 300);
  setKids(box,
    h("p", { class: "preview-summary" }, summary.join(" ")),
    warn,
    shown.length ? h("div", { class: "org-list" }, shown.map(row)) : null,
    shown.length < problems.length + kept.length + moving.length ? h("p", { class: "hint" }, `…and ${problems.length + kept.length + moving.length - shown.length} more`) : null);
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
    folderCache.clear(); folderCovers.clear();
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
