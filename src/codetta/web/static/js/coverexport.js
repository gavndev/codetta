// Save covers as files: each album's embedded cover as cover.jpg (or folder.jpg / front.jpg) next to
// the music, for players that look for a file. Part of Codetta's page; app.js is the entry point.

import { $, closeDialog, h, openDialog, setKids } from "./dom.js";
import { api } from "./api.js";
import { plural, state, toast } from "./state.js";
import { folderCache, loadFolder } from "./browse.js";
import { refreshActivity } from "./activity.js";
import { folderCovers } from "./tools.js";
import { t as tr } from "./i18n.js";

const ce = { target: null, label: "", token: 0, el: {} };

export function openCoverExport(target, label) {
  ce.target = target; ce.label = tr(label);
  const el = ce.el;
  el.name = h("select", { "aria-label": "File name" },
    [["cover", "cover.jpg"], ["folder", "folder.jpg"], ["front", "front.jpg"]].map(([v, l]) => h("option", { value: v, translate: "no" }, l)));
  el.replace = h("input", { type: "checkbox" });
  el.name.addEventListener("change", preview);
  el.replace.addEventListener("change", preview);
  setKids($("#ce-body"),
    h("p", { class: "mb-lead" }, `Save the cover embedded in each album of ${ce.label} as an image file in its folder, for players and apps that look for one (Plex, Jellyfin, Kodi, file browsers).`),
    h("div", { class: "rep-grid" }, h("label", { class: "field" }, h("span", { class: "field-label" }, "File name"), el.name)),
    h("p", { class: "hint" }, "A PNG cover is saved as .png. Disc folders count as part of their album, and the music itself isn't touched."),
    h("div", { class: "rep-options" }, h("label", { class: "rep-check" }, el.replace, "Replace image files of that name already there")),
    h("div", { class: "rep-preview", id: "ce-preview" }));
  setKids($("#ce-foot"), h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", id: "ce-apply", disabled: true, onclick: apply }, "Save covers"));
  openDialog($("#ce-dialog"));
  preview();
}

const body = (dry) => ({ ...ce.target, name: ce.el.name.value, replace: ce.el.replace.checked, dry_run: dry });
const kb = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
const folderName = (f) => f.split("/").pop() || tr("Library");

function statusText(p) {
  if (p.status === "write") return `Saves ${p.file} (${p.width && p.height ? `${p.width} × ${p.height}, ` : ""}${kb(p.size)})`;
  if (p.status === "replace") return `Replaces ${p.file} (${p.width && p.height ? `${p.width} × ${p.height}, ` : ""}${kb(p.size)})`;
  if (p.status === "exists") return `Keeps its own ${p.existing}`;
  if (p.status === "same") return `${p.file} is already this cover`;
  return "No embedded cover";
}

async function preview() {
  const box = $("#ce-preview");
  const go = $("#ce-apply");
  const token = ++ce.token;
  setKids(box, h("p", { class: "hint mbx-wait" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Looking…"));
  try {
    const d = await api("POST", "/api/covers/export", body(true));
    if (token !== ce.token) return;
    go.disabled = !d.writing;
    go.textContent = d.writing ? `Save ${plural(d.writing, "cover")}` : "Save covers";
    setKids(box,
      h("p", { class: "rep-count" }, d.writing ? `${plural(d.writing, "album")} of ${d.albums} would get a cover file`
        : `Nothing to save in ${plural(d.albums, "album")}.`),
      h("ul", { class: "rep-list" }, d.preview.map((p) => h("li", { class: ["write", "replace"].includes(p.status) ? null : "ce-skip" },
        h("span", { class: "rep-file", dir: "auto" }, folderName(p.folder)),
        h("span", { class: "rep-change" }, statusText(p))))));
  } catch (err) {
    if (token !== ce.token) return;
    go.disabled = true;
    setKids(box, h("p", { class: "field-error" }, err.message));
  }
}

async function apply() {
  const go = $("#ce-apply");
  go.disabled = true; go.textContent = "Saving…";
  try {
    const d = await api("POST", "/api/covers/export", body(false));
    closeDialog($("#ce-dialog"));
    toast(d.failed ? `Saved ${d.written}, ${d.failed} couldn't be saved` : `Saved ${plural(d.written, "cover")}. Undo is in Activity.`,
      d.failed ? "error" : "success");
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    loadFolder(state.path, { keepScroll: true });
  } catch (err) {
    toast(err.message, "error");
    go.disabled = false; go.textContent = "Save covers";
  }
}
