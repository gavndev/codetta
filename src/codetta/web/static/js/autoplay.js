// Autoplay: the AudioMuse-AI connection (Settings → Listening) and the "Keep the music going" setup step.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { state, toast } from "./state.js";
import { applyConnections, connectionOn, finishStep, setupLogo, stepCount } from "./setup.js";

export const audiomuse = { data: null };

export async function loadAudioMuse() {
  if (!connectionOn("audiomuse")) { audiomuse.data = null; return null; }
  try { audiomuse.data = await api("GET", "/api/audiomuse"); } catch { audiomuse.data = null; }
  return audiomuse.data;
}

function checkView(d) {
  if (!d?.checked) return null;
  return d.error ? h("div", { class: "error-box" }, d.error)
    : h("div", { class: "sk-check" }, h("p", { class: "sk-ok" }, icon("check"), "Connected to AudioMuse-AI"),
      h("p", { class: "hint" }, "Autoplay asks it first for songs that sound like the one playing."));
}

/** The connection fields (Settings → Listening and the setup step). */
function fields(d) {
  const locked = d?.locked || {};
  return h("div", { class: "sk-fields" },
    h("label", { class: "field" }, h("span", { class: "field-label" }, "AudioMuse-AI address"),
      h("input", { name: "am-url", type: "text", inputmode: "url", placeholder: "http://192.168.1.50:8000", value: d?.url || "", maxlength: "500",
        disabled: locked.url, autocomplete: "off", spellcheck: "false", autocapitalize: "off" })),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "API token"),
      h("input", { name: "am-token", type: "password", disabled: locked.token, autocomplete: "off", maxlength: "500",
        placeholder: d?.has_token ? "Saved (type a new one to change it)" : "The API_TOKEN set on AudioMuse-AI (leave empty if its sign-in is off)" })),
    locked.url || locked.token ? h("p", { class: "conn-lock" }, "Set on the server by CODETTA_AUDIOMUSE_URL / CODETTA_AUDIOMUSE_TOKEN.") : null,
    h("p", { class: "hint" }, "Codetta keeps the token on this server and never shows it again."),
    h("p", { class: "field-error am-field-error", role: "alert", hidden: true }),
    h("div", { class: "sk-check-slot" }, checkView(d)));
}

function fieldError(root) {
  const input = $('[name="am-url"]', root);
  const url = input.value.trim();
  if (!url) return input.disabled ? "" : "Add AudioMuse-AI's address, like http://192.168.1.50:8000";
  let u = null;
  try { u = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : `http://${url}`); } catch { /* below */ }
  if (!u || !/^https?:$/.test(u.protocol) || !u.hostname || u.username || /\s/.test(url)) {
    return "AudioMuse-AI's address should look like http://audiomuse:8000 or http://192.168.1.50:8000";
  }
  return "";
}

async function save(root) {
  const problem = fieldError(root);
  const out = $(".am-field-error", root);
  out.textContent = problem;
  out.hidden = !problem;
  if (problem) throw new Error(problem);
  const token = $('[name="am-token"]', root).value.trim();
  const d = await api("PUT", "/api/audiomuse", { url: $('[name="am-url"]', root).value.trim(), token: token || null });
  audiomuse.data = d;
  setKids($(".sk-check-slot", root), checkView(d));
  return d;
}

export function renderAudioMuseSettings() {
  const box = $("#audiomuse-box");
  if (!box) return;
  if (!connectionOn("audiomuse")) { box.replaceChildren(); return; }
  const form = h("form", { class: "sk-settings" },
    h("h3", { class: "field-label sk-head" }, "AudioMuse-AI"),
    fields(audiomuse.data),
    h("div", { class: "inbox-settings-actions" }, h("button", { class: "btn primary", type: "submit" }, "Save and test")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    go.disabled = true;
    try {
      const d = await save(form);
      toast(d.checked && !d.error ? "AudioMuse-AI connected" : "Saved, but AudioMuse-AI didn't answer", d.checked && !d.error ? "success" : "error");
    } catch (err) { toast(err.message, "error"); } finally { go.disabled = false; }
  });
  box.replaceChildren(form);
}

const autoplayOn = () => { try { return localStorage.getItem("codetta-autoplay") !== "0"; } catch { return true; } };

/** Setup: Autoplay on or off, and which services may suggest songs. */
export async function renderAutoplayStep(form, step) {
  if (!state.connections) { try { state.connections = await api("GET", "/api/connections"); } catch { /* shown as unlocked */ } }
  const conn = state.connections?.connections || [];
  const locked = (id) => !!conn.find((c) => c.id === id)?.locked_by;
  const toggle = (name, title, sub, checked, disabled = false) => h("label", { class: "switch-row" },
    h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, title), h("span", { class: "switch-sub" }, sub)),
    h("input", { type: "checkbox", role: "switch", name, checked, disabled }));
  const amBox = h("div", { class: "am-step-fields", hidden: !connectionOn("audiomuse") }, fields(audiomuse.data));
  setKids(form, setupLogo(), stepCount(),
    h("h1", {}, "Keep the music going?"),
    h("p", { class: "auth-sub" }, "When an album or folder ends, Autoplay keeps playing songs like it, picked from your own library. "
      + "It only ever plays music you already have. Your library alone works offline; these services can make better picks:"),
    h("div", { class: "sk-fields ap-switches" },
    toggle("ap-on", "Autoplay", "Turn it off any time with the ∞ button in the player.", autoplayOn()),
    toggle("ap-audiomuse", "AudioMuse-AI", "Songs that sound alike, from your own AudioMuse-AI server. Sends the playing song's title and artist to it.",
      connectionOn("audiomuse"), locked("audiomuse")),
    amBox,
    toggle("ap-listenbrainz", "ListenBrainz", "Artists people listen to together (open data, no account). Sends the playing artist's MusicBrainz ID.",
      connectionOn("listenbrainz"), locked("listenbrainz")),
    toggle("ap-deezer", "Deezer", "Deezer's related artists (no account). Sends the playing artist's name.",
      connectionOn("deezer"), locked("deezer"))),
    state.connections?.offline_locked ? h("p", { class: "conn-lock" }, "This server stays offline (CODETTA_OFFLINE), so Autoplay picks from your library alone.") : null,
    h("button", { class: "btn primary auth-submit", type: "submit" }, "Continue"),
    h("button", { class: "link-btn setup-skip", type: "button", onclick: () => finishStep(step) }, "Not now"),
    h("p", { class: "auth-foot" }, "You can change these later in Settings → Listening."));
  $('[name="ap-audiomuse"]', form).addEventListener("change", (e) => { amBox.hidden = !e.target.checked; });
  form.onsubmit = async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    go.disabled = true;
    try {
      try { localStorage.setItem("codetta-autoplay", $('[name="ap-on"]', form).checked ? "1" : "0"); } catch { /* private mode */ }
      const enabled = {};
      for (const id of ["audiomuse", "listenbrainz", "deezer"]) {
        if (!locked(id)) enabled[id] = $(`[name="ap-${id}"]`, form).checked;
      }
      state.connections = await api("PUT", "/api/connections", { enabled });
      applyConnections();
      if (enabled.audiomuse) {
        const d = await save(form);
        if (d.error) { go.disabled = false; return; } // show what went wrong; Not now still skips
        toast("AudioMuse-AI connected", "success");
      }
      finishStep(step);
    } catch (err) {
      toast(err.message, "error");
      go.disabled = false;
    }
  };
}
