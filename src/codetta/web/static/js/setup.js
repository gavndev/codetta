// Connections, the first-run setup and What's new.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, h, openDialog, setKids } from "./dom.js";
import { api } from "./api.js";
import { state, toast } from "./state.js";
import { renderSlskdSettings, renderSlskdStep } from "./search.js";
import { loadLidarr, renderLidarrSettings, renderLidarrStep } from "./lidarr.js";
import { loadAudioMuse, renderAudioMuseSettings, renderAutoplayStep } from "./autoplay.js";
import { renderSubsonicSettings } from "./subsonic.js";
import { loadListenBrainz, renderListenBrainzSettings } from "./listenbrainz.js";
import { loadDiscogs, renderDiscogsSettings } from "./discogs.js";
import { backFromAcoustID, loadAcoustID, renderAcoustIDSettings, renderAcoustIDStep } from "./acoustid.js";
import { loadServer, renderListenStep, renderServerSettings } from "./mediaserver.js";
import { renderFolderHead } from "./tools.js";
import { renderEditor } from "./editor.js";
import { loadSlskd, refreshInboxBadge, sk } from "./inbox.js";
import { careChoices, previewFullCare, setHealthEnabled } from "./library.js";
import { pollNotifications } from "./notifications.js";
import { refreshUpdate } from "./account.js";

// ---- Connections: online features, all opt-in ------------------------------------------------
//
// Codetta is offline until the user turns a connection on (first-run card or
// Settings → Connections). An env var on the server can lock a switch.

const NEEDS_SETUP = new Set(["slskd", "lidarr", "mediaserver", "audiomuse", "discogs"]);

export async function loadConnections() {
  try { state.connections = await api("GET", "/api/connections"); } catch { state.connections = null; }
  return state.connections;
}

export const connectionOn = (id) => !!state.connections?.connections.find((c) => c.id === id)?.enabled;

/** Tell the rest of the UI what's on now (buttons appear or disappear). */
export function applyConnections() {
  if (connectionOn("slskd") && !sk.data) loadSlskd().then(() => renderFolderHead());
  if (state.status) {
    state.status.lyrics_lookup = connectionOn("lyrics");
    state.status.musicbrainz = connectionOn("musicbrainz");
    state.status.matching = ["musicbrainz", "deezer", "itunes", "discogs"].some(connectionOn);
  }
  renderFolderHead();
  if (state.editor) renderEditor();
}

function connectionRow(c, checked, onchange) {
  const input = h("input", { type: "checkbox", role: "switch", checked, disabled: !!c.locked_by });
  input.dataset.id = c.id;
  if (onchange) input.addEventListener("change", () => onchange(c, input));
  return h("label", { class: `switch-row conn-row${c.locked_by ? " locked" : ""}` },
    h("span", { class: "switch-text" },
      h("span", { class: "switch-title" }, c.name),
      h("span", { class: "switch-sub" }, c.summary),
      h("span", { class: "conn-sends" }, h("b", {}, "Sends: "), c.sends, h("span", { class: "conn-hosts" }, ` → ${c.hosts.join(", ")}`)),
      c.locked_by ? h("span", { class: "conn-lock" }, `Set on the server by ${c.locked_by}.`) : null,
      c.unavailable ? h("span", { class: "conn-lock" }, c.unavailable) : null),
    input);
}

function showWelcome() {
  const conn = state.connections;
  const list = $("#welcome-list");
  // Pre-ticked when "online" is chosen; the user can untick any of them.
  // Only what's simply on or off. Connections that need an address, a login or a key (slskd, Lidarr,
  // AudioMuse-AI, your music server, Discogs) are set up, and switched on, in their own steps or in Settings.
  setKids(list, conn.connections.filter((c) => !NEEDS_SETUP.has(c.id)).map((c) => connectionRow(c, c.locked_by ? c.enabled : true)),
    h("p", { class: "hint welcome-later" }, "Soulseek, Lidarr, AudioMuse-AI and your music server have their own steps next. Discogs needs a token: add it in Settings → Connections."));
  for (const r of document.querySelectorAll('input[name="welcome-mode"]')) r.checked = false;
  list.hidden = true;
  $("#welcome-go").disabled = true;
  $("#welcome-go").textContent = "Continue";
  $("#welcome-error").hidden = true;
  $("#welcome").hidden = false;
}

export function welcomeModeChanged() {
  const mode = $('input[name="welcome-mode"]:checked')?.value;
  $("#welcome-list").hidden = mode !== "online";
  $("#welcome-go").disabled = !mode;
  $("#welcome-go").textContent = mode === "online" ? "Turn on and continue" : "Stay offline";
}

export async function submitWelcome(e) {
  e.preventDefault();
  const mode = $('input[name="welcome-mode"]:checked')?.value;
  if (!mode) return;
  const enabled = {};
  for (const input of $("#welcome-list").querySelectorAll("input[data-id]")) {
    if (!input.disabled) enabled[input.dataset.id] = mode === "online" && input.checked;
  }
  const go = $("#welcome-go");
  go.disabled = true;
  try {
    state.connections = await api("PUT", "/api/connections", { enabled });
    applyConnections();
    if (connectionOn("updates")) refreshUpdate();
    toast(state.connections.offline
      ? "Codetta will stay offline. You can change this in Settings → Connections."
      : "Online features are on. Change them any time in Settings → Connections.", "success");
    nextSetupStep();
  } catch (err) {
    $("#welcome-error").textContent = err.message;
    $("#welcome-error").hidden = false;
    go.disabled = false;
  }
}

export function renderConnections() {
  const conn = state.connections;
  const intro = $("#conn-intro");
  if (!conn) {
    intro.textContent = "Couldn't load the connection settings.";
    $("#conn-list").replaceChildren();
    return;
  }
  intro.textContent = conn.offline_locked
    ? "This server is set to stay offline (CODETTA_OFFLINE), so these can't be turned on."
    : "Codetta never tracks you, and stays offline unless you turn these on. Only what's listed is sent, and only to these sites.";
  loadSlskd().then(renderSlskdSettings);
  loadLidarr().then(renderLidarrSettings);
  loadAudioMuse().then(renderAudioMuseSettings);
  renderSubsonicSettings();
  loadListenBrainz().then(renderListenBrainzSettings);
  loadDiscogs().then(renderDiscogsSettings);
  loadAcoustID().then(renderAcoustIDSettings);
  loadServer().then(renderServerSettings);
  // Each switch sits in its place in Settings (data-conn), right above its own setup box. One
  // without a place yet (a new connection) goes in the card at the end of Connections.
  const extras = [];
  for (const [c, row] of conn.connections.map((c) => [c, connectionRow(c, c.enabled, onSwitch)])) {
    const slot = document.querySelector(`#settings-dialog [data-conn="${c.id}"]`);
    if (!slot) { extras.push(row); continue; }
    slot.querySelector(":scope > .conn-row")?.remove();
    slot.prepend(row);
  }
  setKids($("#conn-list"), extras);
}

async function onSwitch(item, input) {
  input.disabled = true;
  try {
    state.connections = await api("PUT", "/api/connections", { enabled: { [item.id]: input.checked } });
    applyConnections();
    if (item.id === "slskd") { await loadSlskd(); renderSlskdSettings(); }
    if (item.id === "lidarr") { await loadLidarr(); renderLidarrSettings(); }
    if (item.id === "audiomuse") { await loadAudioMuse(); renderAudioMuseSettings(); }
    if (item.id === "listenbrainz") { await loadListenBrainz(); renderListenBrainzSettings(); }
    if (item.id === "discogs") { await loadDiscogs(); renderDiscogsSettings(); }
    if (item.id === "acoustid") { await loadAcoustID(); renderAcoustIDSettings(); }
    if (item.id === "mediaserver") { await loadServer(); renderServerSettings(); }
    if (item.id === "updates") refreshUpdate();
  } catch (err) {
    input.checked = !input.checked;
    toast(err.message, "error");
  } finally {
    input.disabled = !!item.locked_by;
  }
}

// ---- First-run setup: a few plain steps, each skippable ------------------------------------------------
//
// New installs see every step after creating the account; existing installs see
// only the steps added since (once). Then "What's new".

const setup = { steps: [], index: 0, total: 0 };

export async function runSetup() {
  await loadConnections();
  let steps = [];
  try { steps = (await api("GET", "/api/onboarding")).steps; } catch { /* carry on */ }
  setup.steps = steps;
  setup.total = steps.length;
  setup.index = 0;
  nextSetupStep();
}

function nextSetupStep() {
  const step = setup.steps[setup.index++];
  if (!step) {
    $("#welcome").hidden = true;
    afterSetup();
    return;
  }
  $("#welcome").hidden = false;
  if (step === "connections") {
    $("#setup-step").hidden = true;
    $("#welcome-form").hidden = false;
    showWelcome();
  } else {
    $("#welcome-form").hidden = true;
    $("#setup-step").hidden = false;
    renderSetupStep(step);
  }
}

export const stepCount = () => (setup.total > 1 ? h("p", { class: "setup-count" }, `Step ${setup.index} of ${setup.total}`) : null);
export const setupLogo = () => h("div", { class: "auth-logo", "aria-hidden": "true" },
  h("span", { class: "wordmark" }, "codetta", h("span", { class: "spot-dot" })));

export async function finishStep(step) {
  try { await api("POST", `/api/onboarding/${step}`); } catch { /* shown again next time: harmless */ }
  nextSetupStep();
}

async function renderSetupStep(step) {
  const form = $("#setup-step");
  form.onsubmit = null;
  if (step === "organize") {
    let settings;
    try { settings = await api("GET", "/api/organize/settings"); } catch { finishStep(step); return; }
    const examples = await Promise.all(settings.presets.map((p) => api("POST", "/api/organize/example", { pattern: p.pattern }).catch(() => null)));
    let chosen = settings.presets.some((p) => p.pattern === settings.pattern) ? settings.pattern : settings.presets[0].pattern;
    setKids(form, setupLogo(), stepCount(),
      h("h1", {}, "How should your folders be named?"),
      h("p", { class: "auth-sub" }, "When you organize a folder, or file new music from your inbox, Codetta renames and moves the files using a pattern. Pick the one you like. You can change it any time, and nothing moves until you say so."),
      h("fieldset", { class: "choices" }, settings.presets.map((p, i) => h("label", { class: "choice" },
        h("input", { type: "radio", name: "setup-pattern", value: p.pattern, checked: p.pattern === chosen,
          onchange: () => { chosen = p.pattern; } }),
        h("span", { class: "choice-body" },
          h("span", { class: "choice-title" }, p.name),
          examples[i]?.ok ? h("code", { class: "choice-code", dir: "auto" }, examples[i].single) : null)))),
      h("button", { class: "btn primary auth-submit", type: "submit" }, "Use this pattern"),
      h("button", { class: "link-btn setup-skip", type: "button", onclick: () => finishStep(step) }, "Skip for now"));
    form.onsubmit = async (e) => {
      e.preventDefault();
      try { await api("PUT", "/api/organize/settings", { pattern: chosen }); } catch (err) { toast(err.message, "error"); return; }
      finishStep(step);
    };
  } else if (step === "library") {
    const pick = careChoices("off");
    setKids(form, setupLogo(), stepCount(),
      h("h1", {}, "Should Codetta tidy up your library?"),
      h("p", { class: "auth-sub" }, "Codetta can go through the music you already have, one album at a time, and fix it for you. It only changes an album when it's sure, and you can undo anything."),
      pick.box,
      h("button", { class: "btn primary auth-submit", type: "submit" }, "Continue"),
      h("p", { class: "auth-foot" }, "You can change this any time in Settings → Library → Tidy up."));
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (pick.value() === "full" && !(await previewFullCare())) return; // stay here to choose again
      try { await api("PUT", "/api/library-care", { mode: pick.value() }); } catch (err) { toast(err.message, "error"); return; }
      finishStep(step);
    };
  } else if (step === "health") {
    setKids(form, setupLogo(), stepCount(),
      h("h1", {}, "Check your library for problems?"),
      h("p", { class: "auth-sub" }, "Library health looks through your whole library for things worth fixing: albums your player shows split in two, missing tracks, missing covers or tags, duplicates. "
        + "A card on the Library page shows what it found, obvious fixes are one tap, and every check can be switched off. Nothing changes unless you say so."),
      h("p", { class: "auth-sub" }, "If your library is named exactly the way you want it, you can leave it off."),
      h("button", { class: "btn primary auth-submit", type: "submit" }, "Turn on Library health"),
      h("button", { class: "link-btn setup-skip", type: "button", onclick: async () => {
        try { await setHealthEnabled(false); } catch { /* it stays as it was */ }
        finishStep(step);
      } }, "Leave it off"),
      h("p", { class: "auth-foot" }, "You can change this any time in Settings."));
    form.onsubmit = async (e) => {
      e.preventDefault();
      try { await setHealthEnabled(true); } catch (err) { toast(err.message, "error"); return; }
      finishStep(step);
    };
  } else if (step === "acoustid") {
    if (!connectionOn("acoustid")) { nextSetupStep(); return; } // asked again once AcoustID is on
    await renderAcoustIDStep(form, step);
  } else if (step === "slskd") {
    await renderSlskdStep(form, step);
  } else if (step === "lidarr") {
    await renderLidarrStep(form, step);
  } else if (step === "listen") {
    await renderListenStep(form, step);
  } else if (step === "autoplay") {
    await loadAudioMuse();
    await renderAutoplayStep(form, step);
  } else if (step === "inbox") {
    let root = { folders: [] };
    let external = { available: false };
    try { root = await api("GET", "/api/browse?path="); } catch { /* no library yet */ }
    try { external = (await api("GET", "/api/inbox")).external; } catch { /* keep the default */ }
    setKids(form, setupLogo(), stepCount(),
      h("h1", {}, "Where does new music arrive?"),
      h("p", { class: "auth-sub" }, "Pick the folder your downloads or rips land in (slskd's downloads folder, for example). Codetta treats it as an inbox: it finds each new album and files it into your music folder with your folder pattern. Nothing moves until you say so (unless you allow it below)."),
      inboxSettingsFields({ folder: "", auto: false, watch: false }, root.folders, external),
      h("button", { class: "btn primary auth-submit", type: "submit", id: "setup-inbox-go", disabled: true }, "Use this folder"),
      h("button", { class: "link-btn setup-skip", type: "button", onclick: () => finishStep(step) }, "Not now"),
      h("p", { class: "auth-foot" }, "You can set this up or change it later from the Inbox button in the top bar."));
    form.onsubmit = async (e) => {
      e.preventDefault();
      try { await api("PUT", "/api/inbox/settings", readInboxFields(form)); } catch (err) { toast(err.message, "error"); return; }
      finishStep(step);
    };
  }
}

const CONFIDENCE = [
  { id: "strict", title: "Strict: 85% match or better", sub: "The fewest surprises." },
  { id: "balanced", title: "Balanced: 75% match or better", sub: "Less to review, still careful." },
  { id: "relaxed", title: "Relaxed: 65% match or better", sub: "The least to review: look through Activity now and then." },
];

/** How sure Codetta must be before it files (Inbox) or tags (Tidy up) an album on its own: one
 * setting for both, saved as soon as it changes. */
export function confidenceChooser(where) {
  const usedBy = { inbox: "Also used by Tidy up.", care: "Also used by the inbox.", settings: "Used by the inbox's automatic filing and by Tidy up." }[where] || "";
  const select = h("select", { "aria-label": "How sure Codetta must be" }, CONFIDENCE.map((c) => h("option", { value: c.id }, c.title)));
  const hint = h("span", { class: "hint" });
  const explain = () => {
    const c = CONFIDENCE.find((x) => x.id === select.value) || CONFIDENCE[0];
    hint.textContent = `${c.sub} Every track still has to line up with the album, and anything Codetta does can be undone in Activity. ${usedBy}`;
  };
  select.disabled = true;
  explain();
  api("GET", "/api/matching").then((d) => { select.value = d.confidence; explain(); }).catch(() => {}).finally(() => { select.disabled = false; });
  select.addEventListener("change", async () => {
    explain();
    try { await api("PUT", "/api/matching", { confidence: select.value }); toast("Saved", "success"); }
    catch (err) { toast(err.message, "error"); }
  });
  return h("label", { class: "field" }, h("span", { class: "field-label" }, "How sure Codetta must be"), select, hint);
}

export const inboxLabel = (folder) => (folder === "@inbox" ? "your downloads folder" : folder.replace(/^@inbox\//, "Downloads/"));

/** The inbox's settings fields (used in setup and in the Inbox screen). */
export function inboxSettingsFields(s, folders, external = { available: false }) {
  const chosen = s.folder || (external.available ? "@inbox" : "");
  const select = h("select", { name: "inbox-folder", "aria-label": "Inbox folder" },
    !external.available ? h("option", { value: "" }, "Choose a folder…") : null,
    external.available ? h("option", { value: "@inbox", selected: chosen === "@inbox" }, `Your downloads folder (${external.path || "/inbox"}) · recommended`) : null,
    folders.length ? h("optgroup", { label: "Or a folder inside your music folder" },
      folders.map((f) => h("option", { value: f.path, selected: f.path === chosen }, f.name))) : null);
  // Found or not: so you know where to send new music, and when something's mounted wrong.
  const status = h("p", { class: "inbox-found", role: "status" });
  const showStatus = () => {
    const v = select.value;
    if (!v) { status.hidden = true; return; }
    const ok = v === "@inbox" ? external.available : folders.some((f) => f.path === v);
    status.hidden = false;
    status.className = `inbox-found ${ok ? "ok" : "bad"}`;
    status.textContent = ok
      ? `Found: Codetta can see this folder. Send new music to ${v === "@inbox" ? (external.path || "/inbox") : `${v} in your music folder`}.`
      : v === "@inbox" ? "Not found: Codetta can't see your downloads folder. Check that it's mounted at /inbox, then restart Codetta."
        : "Not found: this folder isn't in your music folder any more. Pick another one.";
  };
  const sync = () => {
    const go = select.form?.querySelector("[type=submit]");
    if (go) go.disabled = !select.value;
    showStatus();
  };
  select.addEventListener("change", sync);
  queueMicrotask(sync);
  return h("div", { class: "inbox-fields" },
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Inbox folder"), select),
    status,
    !external.available ? h("div", { class: "inbox-mount-help" },
      h("strong", {}, "Downloads somewhere else (like slskd's)?"),
      h("span", {}, "Add that folder to Codetta's Docker volumes as /inbox, then restart Codetta:"),
      h("pre", {}, "volumes:\n  - /path/to/downloads:/inbox"),
      h("span", {}, "It'll then show up here as your downloads folder. (Without Docker: set CODETTA_INBOX_DIR.)")) : null,
    !connectionOn("musicbrainz") ? h("p", { class: "hint" }, "Online lookups are off, so albums are filed by their own tags. Turn on MusicBrainz in Settings → Connections to match them automatically.") : null,
    h("label", { class: "switch-row" },
      h("span", { class: "switch-text" },
        h("span", { class: "switch-title" }, "File confident matches automatically"),
        h("span", { class: "switch-sub" }, "When every track lines up with a MusicBrainz release, tag and file it without asking. Everything else waits for you.")),
      h("input", { type: "checkbox", role: "switch", name: "inbox-auto", checked: s.auto })),
    confidenceChooser("inbox"),
    h("label", { class: "switch-row" },
      h("span", { class: "switch-text" },
        h("span", { class: "switch-title" }, "Check for new music every 15 minutes"),
        h("span", { class: "switch-sub" }, "Off: Codetta only looks when you open the Inbox (so idle disks can sleep).")),
      h("input", { type: "checkbox", role: "switch", name: "inbox-watch", checked: s.watch })),
    h("label", { class: "switch-row" },
      h("span", { class: "switch-text" },
        h("span", { class: "switch-title" }, "Move filed albums into your library"),
        h("span", { class: "switch-sub" }, "Renamed and put in folders with your folder pattern. Off: albums are tagged but stay in the inbox folder.")),
      h("input", { type: "checkbox", role: "switch", name: "inbox-organize", checked: s.organize !== false })));
}

export function readInboxFields(root) {
  return {
    folder: $('[name="inbox-folder"]', root).value,
    auto: $('[name="inbox-auto"]', root).checked,
    watch: $('[name="inbox-watch"]', root).checked,
    organize: $('[name="inbox-organize"]', root)?.checked ?? true,
  };
}

function afterSetup() {
  refreshInboxBadge();
  pollNotifications();
  let seen = null;
  try { seen = localStorage.getItem("codetta-seen-version"); } catch { /* private mode */ }
  if (backFromAcoustID()) return; // just approved (or declined) Codetta on acoustid.org
  if (seen !== state.auth?.version) openNews({ latestOnly: true });
}

// ---- What's new (the changelog) ---------------------------------------------------------------------

let newsData = null;

const REPO_FILE_URL = "https://github.com/gavndev/codetta/blob/main/";

/** Changelog text -> nodes: **bold**, `code` and links; everything else stays plain text. Links are
 * https, or a file in Codetta's repository ("docs/install.md#…"), which opens on GitHub. */
function mdInline(text) {
  const out = [];
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https:\/\/[^)\s]+|[A-Za-z0-9_][A-Za-z0-9_./-]*(?:#[A-Za-z0-9_-]+)?)\)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) out.push(h("strong", {}, m[1]));
    else if (m[2]) out.push(h("code", {}, m[2]));
    else out.push(h("a", { href: m[4].startsWith("https://") ? m[4] : REPO_FILE_URL + m[4], target: "_blank", rel: "noopener noreferrer" }, m[3]));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

export async function openNews({ latestOnly = false } = {}) {
  try { newsData = newsData || await api("GET", "/api/changelog"); } catch (err) { toast(err.message, "error"); return; }
  const versions = newsData.versions;
  const section = (v) => h("section", { class: "news-version" },
    h("h3", {}, v.unreleased ? (/\d/.test(v.version) ? `Coming in ${v.version}` : "Coming next") : `Version ${v.version}`,
      v.date ? h("span", { class: "news-date" }, new Date(`${v.date}T12:00:00`).toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" })) : null),
    h("ul", {}, v.items.map((item) => h("li", {}, mdInline(item)))));
  const body = $("#news-body");
  const renderAll = () => setKids(body, versions.map(section));
  if (!versions.length) setKids(body, h("p", { class: "hint" }, "The changelog isn't available on this server."));
  else if (latestOnly && versions.length > 1) {
    setKids(body, section(versions[0]),
      h("button", { class: "link-btn news-more", type: "button", onclick: renderAll }, "Show earlier versions"));
  } else renderAll();
  try { localStorage.setItem("codetta-seen-version", newsData.current); } catch { /* private mode */ }
  openDialog($("#news-dialog"));
}
