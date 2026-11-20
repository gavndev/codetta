// Tag Presets: applying and managing them.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, closeDialog, h, icon, openDialog, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, plural, relativeToFolder, state, toast } from "./state.js";
import { isSearch, loadFolder } from "./browse.js";
import { confirmDiscard, folderTrackPaths } from "./editor.js";
import { refreshActivity } from "./activity.js";

// ---- Presets: apply -----------------------------------------------------------------------------------

async function refreshPresets() {
  state.presets = await api("GET", "/api/presets");
}

let previewTimer = null;
let previewToken = 0;

function applyOptions() {
  const d = els.applyDialog;
  const target = $('input[name="target"]:checked', d)?.value || "folder";
  const body = {
    name: $("#apply-preset").value,
    mode: $('input[name="mode"]:checked', d).value,
  };
  if (target === "selection") body.paths = [...state.selected];
  else if (isSearch()) body.paths = folderTrackPaths().slice(0, 1000); // "All results"
  else { body.folder = state.path; body.recursive = $("#apply-recursive").checked; }
  return { body, target };
}

export async function openApply(target) {
  if (!(await confirmDiscard())) return;
  try { await refreshPresets(); } catch (err) { toast(err.message, "error"); return; }
  if (!state.presets.length) {
    toast("You don't have any presets yet. Create one first.");
    openManage();
    return;
  }
  const d = els.applyDialog;
  const select = $("#apply-preset");
  const previous = select.value;
  select.replaceChildren(...state.presets.map((lo) => h("option", { value: lo.name }, lo.name)));
  if (state.presets.some((lo) => lo.name === previous)) select.value = previous;

  const n = state.selected.size;
  const selRadio = $('input[name="target"][value="selection"]', d);
  selRadio.disabled = n === 0;
  $("#apply-target-sel").textContent = n ? `${plural(n, "selected track")}` : "Selected tracks";
  $("#apply-target-all").textContent = isSearch() ? `All ${plural(folderTrackPaths().length, "result")}` : "This folder";
  $(`input[name="target"][value="${target === "selection" && n ? "selection" : "folder"}"]`, d).checked = true;
  $("#apply-recursive").checked = false;
  syncApplyUi();
  openDialog(d);
  runPreview();
}

export function syncApplyUi() {
  const { target } = applyOptions();
  $("#apply-recursive-wrap").hidden = target !== "folder" || !(state.folder?.folders.length);
  const lo = state.presets.find((l) => l.name === $("#apply-preset").value);
  $("#apply-desc").textContent = lo?.description || "";
}

export function runPreview() {
  clearTimeout(previewTimer);
  const go = $("#apply-go");
  go.disabled = true;
  $("#apply-preview").replaceChildren(h("p", { class: "loading" }, "Checking what will change…"));
  previewTimer = setTimeout(async () => {
    const token = ++previewToken;
    const { body } = applyOptions();
    try {
      const results = await api("POST", "/api/presets/apply", { ...body, dry_run: true });
      if (token !== previewToken) return;
      renderPreview(results);
    } catch (err) {
      if (token !== previewToken) return;
      $("#apply-preview").replaceChildren(h("div", { class: "error-box" }, err.message));
    }
  }, 150);
}

function renderPreview(results) {
  const changing = results.filter((r) => !r.error && Object.keys(r.applied).length);
  const errors = results.filter((r) => r.error);
  const unchanged = results.length - changing.length - errors.length;
  const tagCount = changing.reduce((n, r) => n + Object.keys(r.applied).length, 0);

  const go = $("#apply-go");
  go.disabled = !changing.length;
  go.textContent = changing.length ? `Apply to ${plural(changing.length, "file")}` : "Apply";

  const summary = [];
  if (!results.length) summary.push("There are no audio files to apply this to.");
  else if (changing.length) summary.push(`${plural(tagCount, "tag")} will be set across ${plural(changing.length, "file")}.`);
  else summary.push("Nothing to change — these files already match.");
  if (unchanged && changing.length) summary.push(`${plural(unchanged, "file")} already up to date.`);
  if (errors.length) summary.push(`${plural(errors.length, "file")} can't be read.`);

  const shown = [...errors, ...changing].slice(0, 200);
  const items = shown.map((r) => {
    const notes = [];
    if (r.kept_existing.length) notes.push(`Kept existing: ${r.kept_existing.join(", ")}`);
    if (r.unsupported.length) notes.push(`Not supported by this format: ${r.unsupported.join(", ")}`);
    return h("div", { class: `preview-item${r.error ? " error" : ""}` },
      h("div", { class: "name" }, relativeToFolder(r.path)),
      r.error ? h("div", { class: "note" }, r.error)
        : h("div", { class: "changes" }, Object.entries(r.applied).flatMap(([k, v], i) =>
          [i ? ", " : "", h("b", {}, k), ` → ${v.join("; ")}`])),
      notes.map((n) => h("div", { class: "note" }, n)));
  });
  setKids($("#apply-preview"),
    h("p", { class: "preview-summary" }, summary.join(" ")),
    items.length ? h("div", { class: "preview-list" }, items) : null,
    shown.length < changing.length + errors.length ? h("p", { class: "hint" }, `…and ${changing.length + errors.length - shown.length} more`) : null,
  );
}

export async function doApply() {
  const go = $("#apply-go");
  go.disabled = true;
  go.textContent = "Applying…";
  const { body } = applyOptions();
  try {
    const results = await api("POST", "/api/presets/apply", { ...body, dry_run: false });
    const failed = results.filter((r) => r.error);
    const changed = results.filter((r) => !r.error && Object.keys(r.applied).length);
    closeDialog(els.applyDialog);
    if (failed.length) toast(`Updated ${plural(changed.length, "file")}; ${failed.length} failed: ${failed[0].error}`, "error");
    else toast(`Updated ${plural(changed.length, "file")}`, "success");
    refreshActivity();
    await loadFolder(state.path, { keepScroll: true });
  } catch (err) {
    toast(err.message, "error");
    runPreview();
  }
}

// ---- Presets: manage -----------------------------------------------------------------------------------

export async function openManage() {
  try { await refreshPresets(); } catch (err) { toast(err.message, "error"); return; }
  renderManageList();
  if (!els.manageDialog.open || els.manageDialog.classList.contains("closing")) openDialog(els.manageDialog);
}

function renderManageList() {
  $("#manage-title").textContent = "Presets";
  const body = $("#manage-body");
  if (!state.presets.length) {
    body.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "No presets yet"), "A preset is a saved set of tags you can apply to many tracks at once."));
  } else {
    setKids(body,
      h("p", { class: "hint" }, "Saved sets of tags you can apply to tracks or whole folders. Blank values are skipped when applying."),
      h("div", { class: "preset-list" }, state.presets.map((lo) =>
        h("div", { class: "preset-card" },
          h("div", { class: "info" },
            h("div", { class: "name" }, lo.name),
            lo.description && h("div", { class: "desc" }, lo.description),
            h("div", { class: "tags" }, Object.keys(lo.tags).join(", ") || "No tags")),
          h("button", { class: "btn small", type: "button", onclick: () => renderManageForm(lo) }, "Edit")))));
  }
  setKids($("#manage-foot"),
    h("button", { class: "btn", type: "button", onclick: () => renderManageForm(null) }, icon("plus"), "New preset"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn primary", type: "button", onclick: () => closeDialog(els.manageDialog) }, "Done"));
}

function renderManageForm(preset) {
  $("#manage-title").textContent = preset ? "Edit preset" : "New preset";
  const nameInput = h("input", { type: "text", value: preset?.name || "", placeholder: "e.g. SoundCloud single", "aria-label": "Preset name" });
  const descInput = h("input", { type: "text", value: preset?.description || "", placeholder: "What it's for (optional)", "aria-label": "Description" });
  const rowsEl = h("div", { class: "tag-rows" });
  let lastValueInput = null;

  const addRow = (key = "", value = "") => {
    const k = h("input", { type: "text", value: key, placeholder: "Tag", list: "tag-keys", "aria-label": "Tag name", autocapitalize: "off", spellcheck: "false" });
    const v = h("input", { type: "text", value, placeholder: "Value (blank = fill in later)", "aria-label": "Tag value" });
    v.addEventListener("focus", () => { lastValueInput = v; });
    const row = h("div", { class: "add-tag" }, k, v,
      h("button", { class: "icon-btn", type: "button", "aria-label": "Remove tag", onclick: () => row.remove() }, icon("close")));
    rowsEl.append(row);
    return k;
  };

  const entries = preset ? Object.entries(preset.tags) : [["title", ["{filename_title}"]], ["artist", [""]], ["album", [""]], ["genre", [""]]];
  for (const [k, v] of entries) addRow(k, v.join("; "));

  const chips = state.placeholders.map((p) => h("button", {
    class: "chip", type: "button", title: "Insert into the last value you edited",
    onclick: () => {
      const target = lastValueInput && lastValueInput.isConnected ? lastValueInput : null;
      if (!target) { toast("Click into a value first, then pick a placeholder"); return; }
      const pos = target.selectionStart ?? target.value.length;
      target.value = target.value.slice(0, pos) + `{${p}}` + target.value.slice(target.selectionEnd ?? pos);
      target.focus();
    },
  }, `{${p}}`));

  const errorBox = h("div", { class: "error-box", hidden: true });

  setKids($("#manage-body"),
    errorBox,
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Name"), nameInput),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Description"), descInput),
    h("div", { class: "field" },
      h("span", { class: "field-label" }, "Tags"),
      rowsEl,
      h("button", { class: "btn small", type: "button", onclick: () => addRow().focus() }, icon("plus"), "Add tag")),
    h("div", { class: "field" },
      h("span", { class: "field-label" }, "Placeholders"),
      h("p", { class: "hint", style: "margin:0 0 6px" }, "Filled in per file. Separate multiple values with ;"),
      h("div", {}, chips),
      h("p", { class: "hint", style: "margin:4px 0 0" },
        h("code", {}, "{filename_title}"), " “01 - My Song” → “My Song” · ",
        h("code", {}, "{folder}"), " folder name · ",
        h("code", {}, "{track}/{tracktotal}"), " 1/12, 2/12…")),
  );

  const save = async () => {
    const tags = {};
    for (const row of rowsEl.children) {
      const [k, v] = row.querySelectorAll("input");
      const key = k.value.trim().toLowerCase();
      if (!key) continue;
      const raw = v.value.trim();
      tags[key] = state.fieldMap.get(key)?.multi && raw.includes(";")
        ? raw.split(";").map((s) => s.trim()).filter(Boolean)
        : raw;
    }
    try {
      await api("POST", "/api/presets", {
        name: nameInput.value, description: descInput.value, tags,
        previous_name: preset ? preset.name : null,
      });
      toast(`Saved “${nameInput.value.trim()}”`, "success");
      await refreshPresets();
      renderManageList();
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.hidden = false;
      errorBox.scrollIntoView({ block: "nearest" });
    }
  };

  const del = async () => {
    if (!(await ask({ title: `Delete “${preset.name}”?`, message: "This preset will be deleted. This can't be undone.",
      confirmLabel: "Delete", danger: true }))) return;
    try {
      await api("DELETE", `/api/presets/${encodeURIComponent(preset.name)}`);
      toast(`Deleted “${preset.name}”`, "success");
      await refreshPresets();
      renderManageList();
    } catch (err) { toast(err.message, "error"); }
  };

  setKids($("#manage-foot"),
    preset && h("button", { class: "btn danger", type: "button", onclick: del }, "Delete"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", onclick: renderManageList }, "Cancel"),
    h("button", { class: "btn primary", type: "button", onclick: save }, "Save"));
  nameInput.focus();
}
