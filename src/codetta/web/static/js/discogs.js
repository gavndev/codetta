// Discogs: the person's token (Account → Connections), which searching Discogs needs.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, h, icon, setKids } from "./dom.js";
import { api } from "./api.js";
import { toast } from "./state.js";
import { connectionOn } from "./setup.js";

let data = null;

export async function loadDiscogs() {
  if (!connectionOn("discogs")) { data = null; return null; }
  try { data = await api("GET", "/api/discogs"); } catch { data = null; }
  return data;
}

function status(d) {
  const c = d?.check;
  if (c?.ok) return h("p", { class: "sk-ok" }, icon("check"), c.username ? `Connected to Discogs as ${c.username}` : "Connected to Discogs");
  if (c && !c.ok) return h("div", { class: "error-box" }, c.error);
  return d?.has_token ? h("p", { class: "hint" }, "A token is saved. Searching Discogs is ready.") : null;
}

export function renderDiscogsSettings() {
  const box = $("#discogs-box");
  if (!connectionOn("discogs")) { box.replaceChildren(); return; }
  const input = h("input", { type: "password", name: "dg-token", autocomplete: "off", maxlength: "200", disabled: data?.locked,
    placeholder: data?.has_token ? "Saved (paste a new one to change it)" : "Your Discogs token", "aria-label": "Discogs token" });
  const slot = h("div", { class: "sk-check-slot" }, status(data));
  const form = h("form", { class: "sk-settings" },
    h("h3", { class: "field-label sk-head" }, "Discogs"),
    h("p", { class: "hint" }, "Looking up a Discogs link works as it is. To search Discogs (Find in Discogs, !dg), make a free personal token: on discogs.com go to Settings → Developers → Generate new token, then paste it here."),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Token"), input),
    data?.locked ? h("p", { class: "conn-lock" }, "Set on the server by CODETTA_DISCOGS_TOKEN.") : null,
    h("p", { class: "hint" }, "Codetta keeps the token on this server and never shows it again."),
    slot,
    h("div", { class: "inbox-settings-actions" },
      data?.has_token && !data?.locked ? h("button", { class: "btn", type: "button", onclick: async () => {
        try { data = await api("PUT", "/api/discogs", { token: "" }); toast("Discogs token removed"); renderDiscogsSettings(); }
        catch (err) { toast(err.message, "error"); }
      } }, "Remove token") : null,
      h("button", { class: "btn primary", type: "submit", disabled: data?.locked }, "Save and test")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const go = $("[type=submit]", form);
    go.disabled = true;
    try {
      data = input.value.trim() ? await api("PUT", "/api/discogs", { token: input.value.trim() }) : await api("POST", "/api/discogs/test");
      setKids(slot, status(data));
      toast(data.check?.ok ? "Discogs connected" : (data.check?.error || "Discogs didn't answer"), data.check?.ok ? "success" : "error");
      if (data.check?.ok) input.value = "";
    } catch (err) { toast(err.message, "error"); } finally { go.disabled = false; }
  });
  box.replaceChildren(form);
}
