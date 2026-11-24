// Signing in, the profile picture, the account sheet and version & updates.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, closeDialog, h, icon, openDialog, replay, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, state, toast } from "./state.js";
import { applyTheme, getTheme, THEME_ICON } from "./theme.js";
import { isSearch, loadFolder, navigate, pathFromHash, renderFilterChips } from "./browse.js";
import { bang, loadSearchIdeas, renderBangSuggestions, setBang, syncRoll } from "./search.js";
import { isPhone, renderFolderHead, renderFolders, renderTracks } from "./tools.js";
import { isDirty } from "./editor.js";
import { refreshActivity, startActivityPolling } from "./activity.js";
import {
  openNews, runSetup, submitWelcome, welcomeModeChanged,
} from "./setup.js";
import { loadSlskd, openInbox, sk } from "./inbox.js";
import { closeNotifications, openNotifications, pollNotifications, showStatus } from "./notifications.js";
import { bindEvents } from "./wiring.js";
import { openSettings } from "./settings.js";

// ---- Sign in ----------------------------------------------------------------------------------------

let authMode = "login";
export let appStarted = false;

export function showAuth(mode, message = "") {
  authMode = mode;
  const setup = mode === "setup";
  $("#auth-title").textContent = setup ? "Create your account" : "Sign in"; // the wordmark above already says Codetta
  $("#auth-sub").textContent = setup ? "Create the account that protects your music library." : message;
  $("#auth-confirm-wrap").hidden = !setup;
  $("#auth-confirm").required = setup;
  $("#auth-pass").autocomplete = setup ? "new-password" : "current-password";
  $("#auth-pass").minLength = setup ? 8 : 0;
  $("#auth-submit").textContent = setup ? "Create account" : "Sign in";
  $("#auth-foot").textContent = setup
    ? "Use at least 8 characters. You can change it later from the account menu."
    : "Forgot your password? It can be reset on the server (see “Resetting your password” in Codetta's install guide).";
  $("#auth-error").hidden = true;
  const wasHidden = $("#auth").hidden;
  $("#auth").hidden = false;
  if (wasHidden) setTimeout(() => ($("#auth-user").value ? $("#auth-pass") : $("#auth-user")).focus(), 50);
}

async function submitAuth(e) {
  e.preventDefault();
  const user = $("#auth-user").value;
  const pass = $("#auth-pass").value;
  const err = $("#auth-error");
  const fail = (msg) => {
    err.textContent = msg;
    err.hidden = false;
    replay($("#auth"), "shake");
  };
  if (authMode === "setup" && pass !== $("#auth-confirm").value) { fail("The passwords don't match."); return; }
  const btn = $("#auth-submit");
  btn.disabled = true;
  try {
    const res = await api("POST", authMode === "setup" ? "/api/auth/setup" : "/api/auth/login", { username: user, password: pass });
    state.auth = { ...(state.auth || {}), signed_in: true, username: res.username, setup_required: false };
    try { state.auth = await api("GET", "/api/auth/status"); } catch { /* keep what we have */ }
    $("#auth-pass").value = "";
    $("#auth-confirm").value = "";
    $("#auth").hidden = true;
    if (!appStarted) await startApp();
    else { loadFolder(state.path, { keepScroll: true }); refreshActivity(); }
    if (authMode === "setup") toast(`Welcome, ${res.username}! Your library is now protected.`, "success");
  } catch (error) {
    fail(error.message);
  } finally {
    btn.disabled = false;
  }
}

// ---- Profile picture ------------------------------------------------------------------------------------

const AVATAR_SIZE = 256;

function avatarUrl() {
  const v = state.auth?.avatar;
  return v ? `/api/account/avatar?v=${v}` : null;
}

export function renderAvatar() {
  const url = avatarUrl();
  const btn = $("#account-btn");
  btn.classList.toggle("has-avatar", !!url);
  setKids(btn, url ? h("img", { class: "avatar-img", src: url, alt: "" }) : icon("user"));
  const name = state.auth?.username || "";
  setKids($("#profile-avatar"), url
    ? h("img", { src: url, alt: "" })
    : h("span", { class: "avatar-initial", "aria-hidden": "true" }, (Array.from(name)[0] || "?").toUpperCase()));
  $("#avatar-remove").hidden = !url;
  setKids($("#cc-avatar"), url ? h("img", { src: url, alt: "" })
    : h("span", { class: "avatar-initial" }, (Array.from(name)[0] || "?").toUpperCase()));
}

/** Decode any image the browser can read (HEIC works in Safari / on iPhone). */
export async function decodeImage(file) {
  if (window.createImageBitmap) {
    try { return await createImageBitmap(file, { imageOrientation: "from-image" }); } catch { /* try <img> */ }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

/** Crop to a centred square, scale to 256px and upload as WebP (or JPEG). */
async function uploadAvatar(file) {
  const looksHeic = /image\/hei[cf]/i.test(file.type) || /\.(heic|heif)$/i.test(file.name);
  if (file.size > 60 * 1024 * 1024) { toast("That image is too large", "error"); return; }
  let image;
  try {
    image = await decodeImage(file);
  } catch {
    toast(looksHeic
      ? "This browser can't open HEIC photos. Save it as JPEG first, or use Safari (or any browser on an iPhone)."
      : "That file isn't an image Codetta can open. Try JPEG, PNG or WebP.", "error");
    return;
  }
  const w = image.width || image.naturalWidth, h0 = image.height || image.naturalHeight;
  const side = Math.min(w, h0);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = AVATAR_SIZE;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(image, (w - side) / 2, (h0 - side) / 2, side, side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
  let blob = await canvasToBlob(canvas, "image/webp", 0.9);
  if (!blob || blob.type !== "image/webp") blob = await canvasToBlob(canvas, "image/jpeg", 0.9); // older Safari
  try {
    const res = await fetch("/api/account/avatar", { method: "PUT", body: blob, headers: { "Content-Type": blob.type } });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error((data && data.detail) || `Upload failed (${res.status})`);
    state.auth.avatar = data.avatar;
    renderAvatar();
    toast("Profile picture updated", "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function removeAvatar() {
  try {
    await api("DELETE", "/api/account/avatar");
    state.auth.avatar = null;
    renderAvatar();
    toast("Profile picture removed", "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

// ---- Account: a Control Center that grows out of your profile picture -------------------------------

/** Put the panel under the profile picture and aim its grow animation at the picture's centre. */
export function placeAccount() {
  const d = $("#account-dialog");
  const r = $("#account-btn").getBoundingClientRect();
  const phone = isPhone();
  const gutter = phone ? 8 : 12;
  const width = phone ? window.innerWidth - 2 * gutter : Math.min(420, window.innerWidth - 2 * gutter);
  const right = phone ? gutter : Math.max(gutter, window.innerWidth - r.right);
  const top = Math.round(r.bottom + 10);
  const left = window.innerWidth - right - width;
  d.style.setProperty("--cc-top", `${top}px`);
  d.style.setProperty("--cc-right", `${right}px`);
  d.style.setProperty("--cc-width", `${width}px`);
  d.style.setProperty("--cc-ox", `${Math.round(r.left + r.width / 2 - left)}px`);
  d.style.setProperty("--cc-oy", `${Math.round(r.top + r.height / 2 - top)}px`);
}

export function syncAccountTiles() {
  const theme = getTheme();
  setKids($("#cc-theme-icon"), icon(THEME_ICON[theme]));
  $("#cc-theme-state").textContent = { system: "Automatic", light: "Light", dark: "Dark" }[theme];
  if (!$("#cc-health-icon").firstChild) $("#cc-health-icon").append(icon("pulse"));
  if (!$("#cc-advanced-icon").firstChild) $("#cc-advanced-icon").append(icon("code"));
  if (!$("#cc-settings-icon").firstChild) $("#cc-settings-icon").append(icon("gear"));
  $("#advanced-toggle").checked = state.advanced;
}

export function setPasswordOpen(open) {
  $("#pw-toggle").setAttribute("aria-expanded", String(open));
  $("#password-form").hidden = !open;
  $("#pw-tile").classList.toggle("open", open);
  if (open) setTimeout(() => $("#pw-current").focus(), 50);
}

/** The account fields in Settings → General (shown only with sign-in on, never in the desktop app). */
export function syncAccountSettings() {
  const a = state.auth || {};
  const signedIn = !!a.auth_enabled;
  $("#set-account-title").hidden = $("#set-account-card").hidden = !signedIn;
  $("#account-name").textContent = a.username || "";
  $("#pw-username").value = a.username || "";
  $("#pw-tile").hidden = !signedIn || !!a.desktop;
  $("#pw-toggle").hidden = !!a.managed_by_env;
  setPasswordOpen(false);
  $("#pw-env-note").hidden = !signedIn || !a.managed_by_env;
  $("#pw-error").hidden = true;
  renderAvatar();
  renderAbout();
  if (!state.update) refreshUpdate();
}

export function openAccount() {
  const a = state.auth || {};
  // With sign-in off (behind a proxy that handles it) there's no account: straight to Settings.
  if (!a.auth_enabled) { openSettings(); return; }
  renderAvatar();
  api("GET", "/api/library-health/summary").then((s) => { $("#health-toggle").checked = s.enabled !== false; }).catch(() => {});
  // The desktop app signs its own window in: no signing out (there'd be no password to sign back
  // in with), and Quit Codetta instead, for when it opened in a browser tab.
  $("#sign-out").hidden = !!a.desktop;
  $("#quit-app").hidden = !a.desktop;
  $("#cc-name").textContent = a.username || "";
  const u = state.update;
  $("#cc-update-row").hidden = !u?.update_available;
  if (u?.update_available) $("#cc-update-title").textContent = `Codetta ${u.latest} is available`;
  syncAccountTiles();
  placeAccount();
  openDialog($("#account-dialog"));
}

async function changePassword(e) {
  e.preventDefault();
  const err = $("#pw-error");
  const next = $("#pw-new").value;
  if (next !== $("#pw-confirm").value) { err.textContent = "The new passwords don't match."; err.hidden = false; return; }
  try {
    await api("POST", "/api/auth/password", { current_password: $("#pw-current").value, new_password: next });
    for (const id of ["#pw-current", "#pw-new", "#pw-confirm"]) $(id).value = "";
    setPasswordOpen(false);
    toast("Password changed. Your other devices were signed out.", "success");
  } catch (error) {
    err.textContent = error.message;
    err.hidden = false;
  }
}

async function signOut() {
  if (isDirty() && !(await ask({ title: "Sign out?", message: "Your unsaved tag changes will be lost.",
    confirmLabel: "Sign out", danger: true }))) return;
  try { await api("POST", "/api/auth/logout"); } catch { /* signing out anyway */ }
  state.editor = null; // already confirmed; don't ask again on unload
  location.reload(); // fresh start: the page comes back on the sign-in screen
}

export async function boot() {
  applyTheme(getTheme());
  bindEvents();
  $("#auth-form").addEventListener("submit", submitAuth);
  $("#welcome-form").addEventListener("submit", submitWelcome);
  $("#inbox-btn").addEventListener("click", openInbox);
  // The search bar widens while you use it; on phones a Cancel button slides in (like iOS).
  const wrap = $("#search-wrap");
  let blurTimer = null;
  wrap.addEventListener("focusin", () => { clearTimeout(blurTimer); wrap.classList.add("active"); syncRoll(); renderBangSuggestions(); });
  wrap.addEventListener("focusout", () => {
    blurTimer = setTimeout(() => {
      renderBangSuggestions();
      syncRoll();
      if (!wrap.contains(document.activeElement) && !bang.kind && !els.filter.value) wrap.classList.remove("active");
    }, 120);
  });
  $("#search-cancel").addEventListener("pointerdown", (e) => e.preventDefault()); // keep the keyboard until the tap lands
  $("#search-cancel").addEventListener("click", () => {
    els.filter.value = "";
    setBang(false);
    if (isSearch()) navigate("");
    else if (state.filter) { state.filter = ""; renderFolders(); renderTracks(); renderFilterChips(); }
    els.filter.blur();
    wrap.classList.remove("active");
  });
  $("#bang-chip").addEventListener("click", (e) => { e.preventDefault(); setBang(false); els.filter.focus(); });
  $("#soulseek-dialog").addEventListener("close", () => clearTimeout(sk.timer));
  $("#notif-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    if ($("#notif-panel").hidden) openNotifications(); else closeNotifications();
  });
  document.addEventListener("click", (e) => {
    if (!$("#notif-panel").hidden && !e.target.closest("#notif-panel, #notif-btn")) closeNotifications();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNotifications(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && appStarted) pollNotifications(); });
  document.addEventListener("click", (e) => { if (e.target.closest("[data-news]")) openNews(); });
  for (const r of document.querySelectorAll('input[name="welcome-mode"]')) r.addEventListener("change", welcomeModeChanged);
  $("#account-btn").addEventListener("click", openAccount);
  $("#password-form").addEventListener("submit", changePassword);
  $("#sign-out").addEventListener("click", signOut);
  $("#quit-app").addEventListener("click", async () => {
    if (isDirty() && !(await ask({ title: "Quit Codetta?", message: "Your unsaved tag changes will be lost.",
      confirmLabel: "Quit", danger: true }))) return;
    try { await api("POST", "/api/desktop/quit"); } catch { /* it may stop before answering */ }
    document.body.replaceChildren(h("main", { class: "quit-note" }, h("h1", {}, "Codetta has closed"),
      h("p", {}, "You can close this tab. Open Codetta again whenever you like.")));
  });
  $("#check-updates").addEventListener("click", () => refreshUpdate(true));
  const pickAvatar = () => $("#avatar-file").click();
  $("#profile-avatar").addEventListener("click", pickAvatar);
  $("#avatar-change").addEventListener("click", pickAvatar);
  $("#avatar-remove").addEventListener("click", removeAvatar);
  $("#avatar-file").addEventListener("change", (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (f) uploadAvatar(f);
  });
  const accountDialog = $("#account-dialog");
  accountDialog.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]") || e.target === accountDialog) closeDialog(accountDialog);
  });
  accountDialog.addEventListener("cancel", (e) => { e.preventDefault(); closeDialog(accountDialog); });

  try {
    state.auth = await api("GET", "/api/auth/status");
  } catch (err) {
    toast(`Can't reach the Codetta server: ${err.message}`, "error");
    return;
  }
  showVersion(state.auth.version);
  if (state.auth.auth_enabled && !state.auth.signed_in) {
    showAuth(state.auth.setup_required ? "setup" : "login");
    return;
  }
  await startApp();
}

// ---- Version & updates -------------------------------------------------------------------------------

function showVersion(version) {
  if (!version) return;
  for (const el of document.querySelectorAll("[data-version]")) el.textContent = `v${version}`;
  $(".brand").title = `Codetta v${version}`;
  $("#about-version").textContent = `v${version}`;
}

export async function refreshUpdate(force = false) {
  const btn = $("#check-updates");
  if (force) { btn.disabled = true; btn.textContent = "Checking…"; }
  try {
    state.update = await api("GET", `/api/update${force ? "?force=true" : ""}`);
  } catch {
    /* offline or signed out: try again later */
  } finally {
    btn.disabled = false;
    btn.textContent = "Check for updates";
  }
  const available = !!state.update?.update_available;
  $("#account-btn").classList.toggle("has-update", available);
  $("#account-btn").title = available ? `Account · Codetta ${state.update.latest} is available` : "Account";
  renderAbout();
}

const UPDATE_STEPS = "cd /path/to/codetta\ndocker compose pull\ndocker compose up -d";

export function renderAbout() {
  const u = state.update;
  const status = $("#update-status");
  const box = $("#update-box");
  box.hidden = true;
  const checked = u?.checked_at ? ` (checked ${new Date(u.checked_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })})` : "";
  $("#check-updates").hidden = !!u && !u.enabled;
  if (!u) {
    status.textContent = "";
  } else if (!u.enabled) {
    status.textContent = "Update checks are off. Turn on “Update check” under Connections to hear about new versions.";
  } else if (u.error) {
    status.textContent = `Couldn't check for updates: ${u.error}.`;
  } else if (u.note) {
    status.textContent = `${u.note}${checked}.`;
  } else if (u.update_available) {
    setKids(status, h("b", {}, `Version ${u.latest} is available.`), " ",
      u.release_url ? h("a", { href: u.release_url, target: "_blank", rel: "noopener" }, "What's new") : null);
    const notes = (u.notes || "").trim();
    setKids(box,
      notes ? h("div", { class: "release-notes" }, notes) : null,
      h("p", { class: "hint", style: "margin:0 0 6px" }, "To update, run this on your server (use your Codetta folder's path):"),
      h("pre", { class: "update-steps" }, UPDATE_STEPS),
      h("button", { class: "btn small", type: "button", onclick: () => copyText(UPDATE_STEPS) }, icon("copy"), "Copy commands"),
      h("p", { class: "hint", style: "margin:8px 0 0" }, "Your account, presets and activity log are kept."));
    box.hidden = false;
  } else {
    status.textContent = `You're up to date${checked}.`;
  }
}

/** Copy text; works over plain http too (navigator.clipboard needs https). */
export async function copyText(text) {
  try {
    if (window.isSecureContext && navigator.clipboard) await navigator.clipboard.writeText(text);
    else {
      const area = h("textarea", { style: "position:fixed;opacity:0", readonly: true });
      area.value = text;
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    toast("Copied", "success");
  } catch {
    toast("Couldn't copy. Select the text and copy it instead.", "error");
  }
}

async function startApp() {
  appStarted = true;
  loadSearchIdeas();
  document.addEventListener("visibilitychange", syncRoll);
  $("#app").hidden = false;
  $("#account-btn").hidden = false; // with sign-in off it opens Settings (connections, advanced mode)
  if (!state.auth?.auth_enabled) { $("#account-btn").title = "Settings"; $("#account-btn").setAttribute("aria-label", "Settings"); }
  renderAvatar();
  try {
    const [status, fields] = await Promise.all([api("GET", "/api/status"), api("GET", "/api/fields")]);
    state.fields = fields.fields;
    state.fieldMap = new Map(fields.fields.map((f) => [f.key, f]));
    state.placeholders = fields.placeholders;
    state.trackKeys = fields.track_keys || [];
    $("#tag-keys").replaceChildren(...fields.fields.map((f) => h("option", { value: f.key }, f.label)));
    showStatus(status);
    loadSlskd().then(() => renderFolderHead());
  } catch (err) {
    toast(`Can't reach the Codetta server: ${err.message}`, "error");
  }
  // First run (or first start after an update that adds a setup step).
  runSetup();
  await loadFolder(pathFromHash());
  refreshActivity();
  startActivityPolling();
  // Check for a new release in the background (and twice a day if left open),
  // only if the user turned the update check on.
  setTimeout(() => refreshUpdate(), 1500);
  setInterval(() => refreshUpdate(), 12 * 3600 * 1000);
}
