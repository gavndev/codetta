// Music server: Navidrome (or any Subsonic server), Jellyfin, Emby or Plex hears about Codetta's
// changes (Settings → Music apps & server, and a setup step).
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { state, toast } from "./state.js";
import { applyConnections, connectionOn, finishStep, setupLogo, stepCount } from "./setup.js";

export const server = { data: null };

const KINDS = [["subsonic", "Navidrome"], ["jellyfin", "Jellyfin"], ["emby", "Emby"], ["plex", "Plex"]];
const PLACEHOLDER = { subsonic: "http://navidrome:4533", jellyfin: "http://jellyfin:8096", emby: "http://emby:8096", plex: "http://plex:32400" };
const TOKEN_HELP = {
  jellyfin: "From Jellyfin: Dashboard → API Keys → +",
  emby: "From Emby: Settings → Advanced → API Keys → New",
  plex: "Your Plex token (see “Finding your Plex token” in the docs)",
};

export async function loadServer() {
  if (!connectionOn("mediaserver")) { server.data = null; return null; }
  try { server.data = await api("GET", "/api/mediaserver"); } catch { server.data = null; }
  return server.data;
}

const ago = (t) => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
};

/** What the server said, and when Codetta last asked it to scan. */
function checkView(d) {
  const c = d?.check;
  if (!c) return null;
  if (!c.ok) return h("div", { class: "error-box" }, c.error);
  const libs = c.libraries || [];
  return h("div", { class: "sk-check" },
    h("p", { class: "sk-ok" }, icon("check"), `Connected to ${c.name}${c.version ? ` ${c.version}` : ""}`),
    c.can_scan ? h("p", { class: "hint" },
      `After Codetta changes files, ${c.name} gets a quick scan${libs.length && d.kind !== "subsonic" ? ` of ${libs.map((l) => `“${l.name}”`).join(", ")}` : ""}, so your edits show up in your player within a minute.`) : null,
    c.note ? h("div", { class: "sk-warn" }, h("strong", {}, "Worth knowing"), h("span", {}, c.note)) : null,
    d.last_scan?.at ? h("p", { class: "hint" }, d.last_scan.error
      ? `Last scan request failed (${ago(d.last_scan.at)}): ${d.last_scan.error}`
      : `Last asked ${c.name} to scan ${ago(d.last_scan.at)}.`) : null);
}

/** The connection fields: which server, its address, and how Codetta signs in. */
function fields(d) {
  const locked = d?.locked || {};
  const wrap = h("div", { class: "sk-fields" });
  let kind = d?.kind || "subsonic";
  const signIn = h("div", { class: "ms-sign-in" });
  const url = h("input", { name: "ms-url", type: "text", inputmode: "url", placeholder: PLACEHOLDER[kind], value: d?.url || "",
    maxlength: "500", disabled: locked.url, autocomplete: "off", spellcheck: "false", autocapitalize: "off" });

  const drawSignIn = () => {
    const same = kind === (d?.kind || "subsonic");
    url.placeholder = PLACEHOLDER[kind];
    setKids(signIn, kind === "subsonic"
      ? [h("label", { class: "field" }, h("span", { class: "field-label" }, "Username"),
          h("input", { name: "ms-user", type: "text", value: d?.username || "", maxlength: "200", disabled: locked.username,
            autocomplete: "off", spellcheck: "false", autocapitalize: "off" })),
        h("label", { class: "field" }, h("span", { class: "field-label" }, "Password"),
          h("input", { name: "ms-password", type: "password", maxlength: "500", disabled: locked.password, autocomplete: "off",
            placeholder: same && d?.has_password ? "Saved (type a new one to change it)" : "" })),
        h("p", { class: "hint" }, "Navidrome only lets admin users start scans. Works with any Subsonic server too: Gonic, Airsonic, Ampache and more.")]
      : [h("label", { class: "field" }, h("span", { class: "field-label" }, kind === "plex" ? "Plex token" : "API key"),
          h("input", { name: "ms-token", type: "password", maxlength: "500", disabled: locked.token, autocomplete: "off",
            placeholder: same && d?.has_token ? "Saved (type a new one to change it)" : TOKEN_HELP[kind] }))]);
  };

  const picker = h("div", { class: "segmented ms-kind", role: "radiogroup", "aria-label": "Your music server" },
    KINDS.map(([v, label]) => {
      const input = h("input", { type: "radio", name: "ms-kind", value: v, checked: kind === v, disabled: locked.kind });
      input.addEventListener("change", () => { kind = v; drawSignIn(); });
      return h("label", {}, input, h("span", {}, label));
    }));
  drawSignIn();
  setKids(wrap,
    h("div", { class: "field" }, h("span", { class: "field-label" }, "Your music server"), picker),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Server address"), url),
    signIn,
    Object.values(locked).some(Boolean) ? h("p", { class: "conn-lock" }, "Some of these are set on the server (CODETTA_MEDIA_SERVER_…).") : null,
    h("p", { class: "hint" }, "Codetta keeps these on this server and never shows them again."),
    h("p", { class: "field-error ms-field-error", role: "alert", hidden: true }),
    h("div", { class: "sk-check-slot" }, checkView(d)));
  return wrap;
}

function fieldError(root) {
  const input = $('[name="ms-url"]', root);
  const url = input.value.trim();
  if (url) {
    let u = null;
    try { u = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : `http://${url}`); } catch { /* below */ }
    if (!u || !/^https?:$/.test(u.protocol) || !u.hostname || u.username || /\s/.test(url)) {
      return "The server's address should look like http://navidrome:4533 or http://192.168.1.50:8096";
    }
  } else if (!input.disabled) return "Add your server's address, like http://navidrome:4533";
  const user = $('[name="ms-user"]', root);
  if (user && !user.disabled && !user.value.trim()) return "Add the username Codetta signs in with.";
  return "";
}

async function save(root) {
  const problem = fieldError(root);
  const out = $(".ms-field-error", root);
  out.textContent = problem;
  out.hidden = !problem;
  if (problem) throw new Error(problem);
  const val = (name) => $(`[name="${name}"]`, root)?.value;
  const password = val("ms-password");
  const token = val("ms-token")?.trim();
  const d = await api("PUT", "/api/mediaserver/settings", {
    kind: $('[name="ms-kind"]:checked', root)?.value || "subsonic",
    url: val("ms-url").trim(), username: (val("ms-user") || "").trim(),
    password: password ? password : null, token: token ? token : null,
  });
  server.data = d;
  setKids($(".sk-check-slot", root), checkView(d));
  return d;
}

export function renderServerSettings() {
  const box = $("#mediaserver-box");
  if (!connectionOn("mediaserver")) { box.replaceChildren(); return; }
  const form = h("form", { class: "sk-settings" },
    h("h3", { class: "field-label sk-head" }, "Music server"),
    fields(server.data),
    h("div", { class: "inbox-settings-actions" },
      server.data?.check?.ok ? h("button", { class: "btn", type: "button", onclick: async (e) => {
        e.currentTarget.disabled = true;
        try {
          const d = await api("POST", "/api/mediaserver/scan");
          server.data = d;
          setKids($(".sk-check-slot", form), checkView(d));
          toast(d.last_scan?.error ? d.last_scan.error : `Asked ${d.check?.name || "the server"} to scan`, d.last_scan?.error ? "error" : "success");
        } catch (err) { toast(err.message, "error"); } finally { e.target.closest("button").disabled = false; }
      } }, "Scan now") : null,
      h("button", { class: "btn primary", type: "submit" }, "Save and test")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    go.disabled = true;
    try {
      const d = await save(form);
      toast(d.check?.ok ? `${d.check.name} connected` : "Saved, but the server didn't answer", d.check?.ok ? "success" : "error");
      if (d.check?.ok) renderServerSettings(); // brings in "Scan now"
    } catch (err) { toast(err.message, "error"); } finally { go.disabled = false; }
  });
  box.replaceChildren(form);
}

export async function renderServerStep(form, step) {
  setKids(form, setupLogo(), stepCount(),
    h("h1", {}, "Which music server do you use?"),
    h("p", { class: "auth-sub" }, "Codetta can tell your server about its changes, so the tags you fix show up in your "
      + "player straight away, even on network shares where servers don't notice changes by themselves."),
    fields(null),
    h("button", { class: "btn primary auth-submit", type: "submit" }, "Connect"),
    h("button", { class: "link-btn setup-skip", type: "button", onclick: () => finishStep(step) }, "I don't use one"),
    h("p", { class: "auth-foot" }, "You can connect it later in Settings → Music apps & server."));
  let shown = false;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    if (shown) { finishStep(step); return; }
    go.disabled = true;
    try {
      state.connections = await api("PUT", "/api/connections", { enabled: { mediaserver: true } });
      applyConnections();
      const d = await save(form);
      if (!d.check?.ok) { go.disabled = false; return; }
      toast(`${d.check.name} connected`, "success");
      if (d.check.note) { shown = true; go.textContent = "Continue"; go.disabled = false; return; } // let them read it
      finishStep(step);
    } catch (err) {
      toast(err.message, "error");
      go.disabled = false;
    }
  };
}
