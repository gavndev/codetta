// Lidarr: keeping the user's Lidarr in step (Account → Connections and a setup step).
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { state, toast } from "./state.js";
import { applyConnections, connectionOn, finishStep, setupLogo, stepCount } from "./setup.js";

export const lidarr = { data: null };

export async function loadLidarr() {
  if (!connectionOn("lidarr")) { lidarr.data = null; return null; }
  try { lidarr.data = await api("GET", "/api/lidarr"); } catch { lidarr.data = null; }
  return lidarr.data;
}

const ago = (t) => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
};

/** How Lidarr is set up, what Codetta does about it, and any conflicts. */
function checkView(d) {
  const c = d?.check;
  if (!c) return null;
  if (!c.ok) return h("div", { class: "error-box" }, c.error);
  const found = c.roots.filter((r) => r.folder !== null);
  const where = (r) => (r.folder ? `“${r.folder}” in your music folder` : "your music folder");
  return h("div", { class: "sk-check" },
    h("p", { class: "sk-ok" }, icon("check"), `Connected to Lidarr ${c.version}`),
    found.length ? h("p", { class: "hint" }, found.map((r) => `Lidarr's ${r.lidarr} is ${where(r)}.`).join(" "),
      " After Codetta changes files there, Lidarr rescans them straight away.") : null,
    h("p", { class: "hint" }, d.names_by_lidarr
      ? "Lidarr renames files, so Codetta leaves file names and folders in its folders alone and fixes tags only."
      : c.renames ? "Lidarr renames files, but you've chosen to let Codetta name them."
        : "Lidarr doesn't rename files, so Codetta's folder pattern names them."),
    (d.warnings || []).map((w) => h("div", { class: "sk-warn" }, h("strong", {}, w.title), h("span", {}, w.text))),
    d.last_sync?.at ? h("p", { class: "hint" }, d.last_sync.error
      ? `Last rescan request failed (${ago(d.last_sync.at)}): ${d.last_sync.error}`
      : `Last asked Lidarr to rescan ${d.last_sync.folders === 1 ? "a folder" : `${d.last_sync.folders} folders`} ${ago(d.last_sync.at)}.`) : null);
}

/** The connection fields (Account → Connections and the setup step). */
function fields(d) {
  const locked = d?.locked || {};
  return h("div", { class: "sk-fields" },
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Lidarr address"),
      h("input", { name: "ld-url", type: "text", inputmode: "url", placeholder: "http://lidarr:8686", value: d?.url || "", maxlength: "500",
        disabled: locked.url, autocomplete: "off", spellcheck: "false", autocapitalize: "off" })),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "API key"),
      h("input", { name: "ld-key", type: "password", disabled: locked.api_key, autocomplete: "off", maxlength: "500",
        placeholder: d?.has_key ? "Saved (type a new one to change it)" : "From Lidarr: Settings → General → API Key" })),
    locked.url || locked.api_key ? h("p", { class: "conn-lock" }, "Set on the server by CODETTA_LIDARR_URL / CODETTA_LIDARR_API_KEY.") : null,
    h("p", { class: "hint" }, "Codetta keeps the key on this server and never shows it again."),
    h("p", { class: "field-error ld-field-error", role: "alert", hidden: true }),
    h("label", { class: "switch-row" },
      h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, "Let Lidarr name its files"),
        h("span", { class: "switch-sub" }, "When Lidarr's renaming is on, Organize and Tidy up leave file names and folders in Lidarr's folders alone and fix tags only. Off: Codetta's folder pattern names them (turn off renaming in Lidarr then).")),
      h("input", { type: "checkbox", role: "switch", name: "ld-names", checked: (d?.settings?.names || "auto") === "auto" })),
    h("div", { class: "sk-check-slot" }, checkView(d)));
}

function fieldError(root) {
  const input = $('[name="ld-url"]', root);
  const url = input.value.trim();
  const key = $('[name="ld-key"]', root).value.trim();
  if (url) {
    let u = null;
    try { u = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : `http://${url}`); } catch { /* below */ }
    if (!u || !/^https?:$/.test(u.protocol) || !u.hostname || u.username || /\s/.test(url)) {
      return "Lidarr's address should look like http://lidarr:8686 or http://192.168.1.50:8686";
    }
  } else if (!input.disabled) return "Add Lidarr's address, like http://lidarr:8686";
  if (key && (key.length < 16 || /\s/.test(key))) return "That doesn't look like a Lidarr API key (Settings → General → API Key).";
  return "";
}

async function save(root) {
  const problem = fieldError(root);
  const out = $(".ld-field-error", root);
  out.textContent = problem;
  out.hidden = !problem;
  if (problem) throw new Error(problem);
  const key = $('[name="ld-key"]', root).value.trim();
  const d = await api("PUT", "/api/lidarr/settings", {
    url: $('[name="ld-url"]', root).value.trim(), api_key: key || null,
    names: $('[name="ld-names"]', root).checked ? "auto" : "codetta",
  });
  lidarr.data = d;
  setKids($(".sk-check-slot", root), checkView(d));
  return d;
}

export function renderLidarrSettings() {
  const box = $("#lidarr-box");
  if (!connectionOn("lidarr")) { box.replaceChildren(); return; }
  const form = h("form", { class: "sk-settings" },
    h("h3", { class: "field-label sk-head" }, "Lidarr"),
    fields(lidarr.data),
    h("div", { class: "inbox-settings-actions" }, h("button", { class: "btn primary", type: "submit" }, "Save and test")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    go.disabled = true;
    try {
      const d = await save(form);
      toast(d.check?.ok ? "Lidarr connected" : "Saved, but Lidarr didn't answer", d.check?.ok ? "success" : "error");
    } catch (err) { toast(err.message, "error"); } finally { go.disabled = false; }
  });
  box.replaceChildren(form);
}

export async function renderLidarrStep(form, step) {
  setKids(form, setupLogo(), stepCount(),
    h("h1", {}, "Do you use Lidarr?"),
    h("p", { class: "auth-sub" }, "Lidarr finds and downloads albums; Codetta makes their tags right. Connect them and Lidarr rescans "
      + "its folders as soon as Codetta changes something, so nothing looks missing and nothing is downloaded twice. "
      + "Codetta also tells you if a Lidarr setting would undo your fixes."),
    fields(null),
    h("button", { class: "btn primary auth-submit", type: "submit" }, "Connect Lidarr"),
    h("button", { class: "link-btn setup-skip", type: "button", onclick: () => finishStep(step) }, "I don't use Lidarr"),
    h("p", { class: "auth-foot" }, "You can connect it later in Account → Connections."));
  let shown = false;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    if (shown) { finishStep(step); return; }
    go.disabled = true;
    try {
      state.connections = await api("PUT", "/api/connections", { enabled: { lidarr: true } });
      applyConnections();
      const d = await save(form);
      if (!d.check?.ok) { go.disabled = false; return; }
      toast("Lidarr connected", "success");
      if (d.warnings?.length) { shown = true; go.textContent = "Continue"; go.disabled = false; return; } // let them read the warning
      finishStep(step);
    } catch (err) {
      toast(err.message, "error");
      go.disabled = false;
    }
  };
}
