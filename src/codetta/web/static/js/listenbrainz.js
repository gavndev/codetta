// ListenBrainz scrobbling: the user token (Account → Connections, shown while ListenBrainz is on).
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { toast } from "./state.js";
import { connectionOn } from "./setup.js";

export const listenbrainz = { data: null };

export async function loadListenBrainz() {
  if (!connectionOn("listenbrainz")) { listenbrainz.data = null; return null; }
  try { listenbrainz.data = await api("GET", "/api/listenbrainz"); } catch { listenbrainz.data = null; }
  return listenbrainz.data;
}

function status(d) {
  if (!d?.has_token) return null;
  if (d.error) return h("div", { class: "error-box" }, d.error);
  return h("div", { class: "sk-check" },
    h("p", { class: "sk-ok" }, icon("check"), d.user_name ? `Scrobbling to ${d.user_name}` : "Scrobbling is set up"),
    h("p", { class: "hint" }, [d.sent ? `${d.sent} sent since Codetta started.` : "", d.pending ? ` ${d.pending} waiting to be sent.` : ""].join("").trim()
      || "What you play in Codetta and your music apps is added to your ListenBrainz history."));
}

export function renderListenBrainzSettings() {
  const box = $("#listenbrainz-box");
  if (!box) return;
  const d = listenbrainz.data;
  if (!connectionOn("listenbrainz") || !d) { box.replaceChildren(); return; }
  const input = h("input", { type: "password", name: "lb-token", autocomplete: "off", maxlength: "200", disabled: d.locked,
    placeholder: d.has_token ? "Saved (type a new one to change it)" : "From listenbrainz.org → Settings → User token" });
  const slot = h("div", { class: "sk-check-slot" }, status(d));
  const form = h("form", { class: "sk-settings" },
    h("h3", { class: "field-label sk-head" }, "ListenBrainz scrobbling"),
    h("div", { class: "sk-fields" },
      h("label", { class: "field" }, h("span", { class: "field-label" }, "User token"), input),
      d.locked ? h("p", { class: "conn-lock" }, "Set on the server by CODETTA_LISTENBRAINZ_TOKEN.") : null,
      h("p", { class: "hint" }, "Optional. With your token, what you play is kept in your ListenBrainz listening history (and improves its recommendations). Codetta keeps the token on this server and never shows it again."),
      slot),
    h("div", { class: "inbox-settings-actions" },
      d.has_token && !d.locked ? h("button", { class: "btn", type: "button", onclick: async () => {
        try { listenbrainz.data = await api("PUT", "/api/listenbrainz", { token: "" }); renderListenBrainzSettings(); toast("Scrobbling stopped"); }
        catch (err) { toast(err.message, "error"); }
      } }, "Remove token") : null,
      h("button", { class: "btn primary", type: "submit" }, d.has_token ? "Test" : "Save and test")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    go.disabled = true;
    try {
      const token = input.value.trim();
      const res = token ? await api("PUT", "/api/listenbrainz", { token }) : await api("POST", "/api/listenbrainz/test");
      listenbrainz.data = res;
      renderListenBrainzSettings();
      toast(res.error ? res.error : `Scrobbling to ${res.user_name || "ListenBrainz"}`, res.error ? "error" : "success");
    } catch (err) { toast(err.message, "error"); } finally { go.disabled = false; }
  });
  setKids(box, form);
}
