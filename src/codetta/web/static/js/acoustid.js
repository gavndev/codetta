// AcoustID: connecting the person's own AcoustID account, which identifying by sound needs from 2027.
// Settings → Connections → AcoustID, and a setup step while it isn't connected.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { toast } from "./state.js";
import { connectionOn, finishStep, setupLogo, stepCount } from "./setup.js";

let data = null;
let poll = null;

// Why Codetta isn't connected any more (the server says which).
const OUTCOMES = {
  declined: "You declined Codetta on acoustid.org, so it isn't connected.",
  expired: "The code wasn't used in time. Connect again to get a new one.",
  revoked: "Codetta was disconnected from your AcoustID account on acoustid.org.",
  unknown: "AcoustID no longer knows Codetta's key. Connect again.",
};

export async function loadAcoustID() {
  if (!connectionOn("acoustid")) { data = null; return null; }
  try { data = await api("GET", "/api/acoustid"); } catch { data = null; }
  return data;
}

// acoustid.org sends the person back here after they approve (or decline): Codetta opens this box.
const returnUrl = () => `${location.origin}${location.pathname}?acoustid=back`;

/** Back from acoustid.org? Open Settings at the AcoustID box (true), instead of What's new. */
export function backFromAcoustID() {
  const q = new URLSearchParams(location.search);
  if (!q.has("acoustid")) return false;
  q.delete("acoustid");
  history.replaceState(history.state, "", `${location.pathname}${q.toString() ? `?${q}` : ""}${location.hash}`);
  import("./settings.js").then((m) => m.openSettings("connections", "acoustid-box"));
  return true;
}

/** Start linking: AcoustID gives a code, the person approves Codetta on acoustid.org. */
async function connect(redraw) {
  // Opened now, while it still counts as the click (browsers block a window opened after a wait).
  const win = window.open("", "_blank");
  try {
    data = await api("POST", "/api/acoustid/connect", { return_url: returnUrl() });
    if (win) { win.opener = null; win.location.href = data.link.url; }
  } catch (err) {
    win?.close();
    toast(err.message, "error");
  }
  redraw();
}

async function forget(redraw, message) {
  try { data = await api("PUT", "/api/acoustid", { key: "" }); if (message) toast(message); }
  catch (err) { toast(err.message, "error"); }
  redraw();
}

/** While a link waits, ask Codetta every few seconds (it asks AcoustID) until it's approved or gone. */
function watch(box, redraw, onApproved) {
  clearTimeout(poll);
  if (data?.state !== "pending") return;
  poll = setTimeout(async () => {
    if (!box.isConnected) return;
    try { data = await api("GET", "/api/acoustid"); } catch { /* try again */ }
    if (data?.state === "pending") { watch(box, redraw, onApproved); return; }
    if (data?.state === "approved") { toast("AcoustID connected", "success"); onApproved?.(); }
    redraw();
  }, 4000);
}

function pasteForm(redraw) {
  const input = h("input", { type: "password", name: "acoustid-key", autocomplete: "off", maxlength: "100",
    placeholder: "Your AcoustID API key", "aria-label": "AcoustID API key" });
  const form = h("form", { class: "acoustid-paste" },
    h("label", { class: "field" }, h("span", { class: "field-label" }, "API key"), input),
    h("p", { class: "hint" }, "Sign in at acoustid.org and copy the API key from your account page. Codetta keeps it on this server and never shows it again."),
    h("div", { class: "inbox-settings-actions" }, h("button", { class: "btn", type: "submit" }, "Save and test")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!input.value.trim()) return;
    const go = $("[type=submit]", form);
    go.disabled = true;
    try { data = await api("PUT", "/api/acoustid", { key: input.value.trim() }); toast("AcoustID connected", "success"); redraw(); }
    catch (err) { toast(err.message, "error"); go.disabled = false; }
  });
  return h("details", { class: "acoustid-more" }, h("summary", {}, "Or paste a key from acoustid.org"), form);
}

/** What the box shows: connected, waiting for approval, or how to connect. */
function body(redraw, { setup = false } = {}) {
  const d = data;
  if (d?.state === "approved") {
    return [
      h("p", { class: "sk-ok" }, icon("check"), "Connected to your AcoustID account"),
      d.locked ? h("p", { class: "conn-lock" }, "Set on the server by CODETTA_ACOUSTID_USER_KEY.")
        : h("p", { class: "hint" }, "You can disconnect here, or any time at acoustid.org/my-keys."),
      d.locked || setup ? null : h("div", { class: "inbox-settings-actions" },
        h("button", { class: "btn", type: "button", onclick: () => forget(redraw, "AcoustID disconnected") }, "Disconnect")),
    ];
  }
  if (d?.state === "pending") {
    return [
      h("p", { class: "acoustid-lead" }, "Approve Codetta on acoustid.org. Sign in there with MusicBrainz, Google or just an email address."),
      h("div", { class: "inbox-settings-actions acoustid-actions" },
        h("button", { class: "btn", type: "button", onclick: () => forget(redraw) }, "Cancel"),
        h("a", { class: "btn primary", href: d.link.url, target: "_blank", rel: "noopener noreferrer" }, "Open acoustid.org")),
      h("p", { class: "hint" }, "On another device? Go to acoustid.org/link and enter this code:", " ", h("code", { class: "acoustid-code" }, d.link.code)),
      h("p", { class: "acoustid-wait", role: "status" }, "Waiting for you to approve…"),
    ];
  }
  return [
    d?.outcome ? h("div", { class: "error-box" }, OUTCOMES[d.outcome] || OUTCOMES.unknown) : null,
    // The setup step already says this above the box.
    setup ? null : h("p", { class: "hint" }, "From January 1, 2027, AcoustID needs your own free AcoustID account to identify music. Connect it once: you sign in at acoustid.org and approve Codetta, nothing to copy."),
    setup ? null : h("div", { class: "inbox-settings-actions" },
      h("button", { class: "btn primary", type: "button", onclick: () => connect(redraw) }, "Connect AcoustID")),
    pasteForm(redraw),
  ];
}

export function renderAcoustIDSettings() {
  const box = $("#acoustid-box");
  if (!box) return;
  if (!connectionOn("acoustid")) { clearTimeout(poll); box.replaceChildren(); return; }
  const draw = () => renderAcoustIDSettings();
  if (data?.state === "approved") hideNotice();
  setKids(box, h("div", { class: "sk-settings" }, h("h3", { class: "field-label sk-head" }, "Your AcoustID account"), body(draw)));
  watch(box, draw);
}

// ---- The heads-up banner (once, at the top of the app) -------------------------------------------------
// The close button hides it for this browser session (it stays closed through refreshes and comes back
// next time); "Don't remind me again" hides it for good in this browser. Connecting hides it too.
const NOTICE_NEVER = "codetta-acoustid-notice";
const NOTICE_CLOSED = "codetta-acoustid-notice-closed";

function hideNotice() {
  const bar = $("#acoustid-notice");
  if (bar) { bar.hidden = true; bar.replaceChildren(); }
}

function noticeDismissed() {
  try { if (localStorage.getItem(NOTICE_NEVER) === "never") return true; } catch { /* private mode */ }
  try { if (sessionStorage.getItem(NOTICE_CLOSED) === "1") return true; } catch { /* private mode */ }
  return false;
}

function closeNotice({ forever = false } = {}) {
  try { sessionStorage.setItem(NOTICE_CLOSED, "1"); } catch { /* private mode */ }
  if (forever) { try { localStorage.setItem(NOTICE_NEVER, "never"); } catch { /* private mode */ } }
  hideNotice();
}

/** Show the AcoustID heads-up at the top of the app, unless it's connected or was dismissed. */
export async function showAcoustIDNotice() {
  const bar = $("#acoustid-notice");
  if (!bar || noticeDismissed()) return;
  if (connectionOn("acoustid")) {
    await loadAcoustID();
    if (data?.state === "approved") return;
  }
  setKids(bar,
    h("span", { class: "notice-icon" }, icon("alert")),
    h("p", { class: "notice-text" },
      h("strong", {}, "AcoustID is changing."), " ",
      "From January 1, 2027, identifying music by sound needs your own free AcoustID account. Connect it once and it keeps working."),
    h("div", { class: "notice-actions" },
      h("button", { class: "btn notice-go", type: "button", onclick: () => {
        closeNotice();
        import("./settings.js").then((m) => m.openSettings("connections", "acoustid-box"));
      } }, "Connect AcoustID"),
      h("button", { class: "link-btn notice-never", type: "button", onclick: () => closeNotice({ forever: true }) }, "Don't remind me again")),
    h("button", { class: "icon-btn notice-close", type: "button", "aria-label": "Close", title: "Close",
      onclick: () => closeNotice() }, icon("close")));
  bar.hidden = false;
  bar.classList.add("opening");
}

/** First-run (or after an update): connect AcoustID while it's on and not connected yet. */
export async function renderAcoustIDStep(form, step) {
  await loadAcoustID();
  if (!data || data.state === "approved") { finishStep(step); return; }
  const draw = () => {
    const approved = data?.state === "approved";
    if (approved) hideNotice();
    setKids(form, setupLogo(), stepCount(),
      h("h1", {}, approved ? "AcoustID is connected" : "Connect your AcoustID account"),
      h("p", { class: "auth-sub" }, "Identify by sound asks AcoustID which songs your files are. From January 1, 2027, AcoustID needs each person's own free account for that. Connect yours once and it keeps working."),
      h("div", { class: "setup-box" }, body(draw, { setup: true })),
      approved || data?.state === "pending" ? null
        : h("button", { class: "btn primary auth-submit", type: "button", onclick: () => connect(draw) }, "Connect AcoustID"),
      approved ? h("button", { class: "btn primary auth-submit", type: "submit" }, "Continue")
        : h("button", { class: "link-btn setup-skip", type: "button", onclick: () => { clearTimeout(poll); finishStep(step); } }, "Not now"),
      h("p", { class: "auth-foot" }, "You can connect it later in Settings → Connections → AcoustID."));
    watch(form, draw);
  };
  form.onsubmit = (e) => { e.preventDefault(); finishStep(step); };
  draw();
}
