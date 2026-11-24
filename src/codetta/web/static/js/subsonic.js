// Music apps: the Subsonic / OpenSubsonic API (Account → Connections and a setup step).
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, h, setKids } from "./dom.js";
import { api } from "./api.js";
import { toast } from "./state.js";
import { finishStep, setupLogo, stepCount } from "./setup.js";

const APPS = "Symfonium, Narjo, Arpeggi, Feishin, DSub, Substreamer, Eclipse and other Subsonic apps";

function copyField(label, value, secret = false) {
  const input = h("input", { type: secret ? "password" : "text", value, readonly: true, spellcheck: "false", autocapitalize: "off",
    "aria-label": label, onfocus: (e) => e.target.select() });
  const row = h("div", { class: "ss-copy" }, input);
  if (secret) {
    row.append(h("button", { class: "btn small", type: "button", onclick: (e) => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      e.currentTarget.textContent = show ? "Hide" : "Show";
    } }, "Show"));
  }
  row.append(h("button", { class: "btn small", type: "button", onclick: async () => {
    try { await navigator.clipboard.writeText(value); toast("Copied", "success"); } catch { input.type = "text"; input.select(); toast("Select it and copy it"); }
  } }, "Copy"));
  return h("label", { class: "field" }, h("span", { class: "field-label" }, label), row);
}

const ago = (t) => {
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 3600 ? "just now" : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
};

/** Converting songs for mobile data, when apps ask (only offered when the encoders are there). */
function conversion(d) {
  if (!d.formats?.length) {
    return h("p", { class: "hint" }, "Converting songs for mobile data needs ffmpeg with MP3, Opus or AAC encoding (the Docker image and the snap have it). Apps get the original files.");
  }
  const toggle = h("input", { type: "checkbox", role: "switch", checked: d.transcode });
  const pick = h("select", { "aria-label": "Format when an app only asks for a lower bitrate" },
    d.formats.map((f) => h("option", { value: f, selected: f === d.format }, { mp3: "MP3", opus: "Opus", aac: "AAC" }[f] || f)));
  const save = async () => {
    try { render(await api("PUT", "/api/subsonic", { enabled: true, transcode: toggle.checked, format: pick.value })); }
    catch (err) { toast(err.message, "error"); }
  };
  toggle.addEventListener("change", save);
  pick.addEventListener("change", save);
  return h("div", { class: "sk-fields" },
    h("label", { class: "switch-row" },
      h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, "Smaller files on mobile data"),
        h("span", { class: "switch-sub" }, "When an app asks for a lower quality (set in the app, often for mobile data), Codetta converts the song as it plays. Off: apps always get the original.")),
      toggle),
    d.transcode ? h("label", { class: "field" }, h("span", { class: "field-label" }, "Convert to"), pick) : null);
}

function connected(d) {
  if (!d.clients?.length) return h("p", { class: "hint" }, "No app has connected yet.");
  return h("p", { class: "hint" }, "Connected recently: ", d.clients.slice(0, 6).map((c, i) =>
    [i ? ", " : "", h("b", { translate: "no" }, c.name), ` (${ago(c.last_seen)})`]));
}

function details(d) {
  return h("div", { class: "sk-fields" },
    h("p", { class: "hint" }, `In your app, add a Subsonic (or Navidrome) server with these details:`),
    copyField("Server address", location.origin),
    copyField("Username", d.username || "codetta"),
    copyField("App password", d.password, true),
    h("p", { class: "hint" }, "This password only works in music apps, never for signing in to Codetta. Apps can browse, search and play your library, but can't change anything."),
    h("button", { class: "link-btn", type: "button", onclick: async () => {
      try { render(await api("POST", "/api/subsonic/password")); toast("New app password: sign in again in your apps", "success"); }
      catch (err) { toast(err.message, "error"); }
    } }, "Make a new password (signs every app out)"),
    connected(d),
    conversion(d),
    h("p", { class: "hint" }, "Stars, ratings, play counts, playlists and your play queue from the apps are kept in Codetta and shared by all of them."));
}

function render(d) {
  const box = $("#subsonic-box");
  if (!box) return;
  const toggle = h("input", { type: "checkbox", role: "switch", checked: d.enabled });
  toggle.addEventListener("change", async () => {
    toggle.disabled = true;
    try { render(await api("PUT", "/api/subsonic", { enabled: toggle.checked })); }
    catch (err) { toggle.checked = !toggle.checked; toast(err.message, "error"); }
    finally { toggle.disabled = false; }
  });
  setKids(box, h("div", { class: "sk-settings" },
    h("h3", { class: "field-label sk-head" }, "Music apps"),
    h("label", { class: "switch-row" },
      h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, "Listen in your music apps"),
        h("span", { class: "switch-sub" }, `Play your library in ${APPS}, over the Subsonic API. Already run Navidrome? You don't need this.`)),
      toggle),
    d.enabled ? details(d) : null));
}

export async function renderSubsonicSettings() {
  try { render(await api("GET", "/api/subsonic")); } catch { /* signed out: nothing to show */ }
}

/** Setup: switch it on (and show how to connect), or skip. */
export async function renderSubsonicStep(form, step) {
  setKids(form, setupLogo(), stepCount(),
    h("h1", {}, "Listen in your music apps?"),
    h("p", { class: "auth-sub" }, `Codetta can serve your library to ${APPS}: browse, search and play from your phone or desktop. `
      + "It's off unless you turn it on, apps sign in with their own password, and they can't change your files. Already run Navidrome? You can skip this."),
    h("button", { class: "btn primary auth-submit", type: "submit" }, "Turn it on"),
    h("button", { class: "link-btn setup-skip", type: "button", onclick: () => finishStep(step) }, "Not now"),
    h("p", { class: "auth-foot" }, "You can change this later in Account → Connections."));
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const d = await api("PUT", "/api/subsonic", { enabled: true });
      setKids(form, setupLogo(), stepCount(), h("h1", {}, "Your music apps can connect"), details(d),
        h("button", { class: "btn primary auth-submit", type: "button", onclick: () => finishStep(step) }, "Done"));
    } catch (err) { toast(err.message, "error"); }
  };
}
