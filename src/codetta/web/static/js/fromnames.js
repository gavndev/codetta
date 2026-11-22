// Tags from file names: "03 - Radiohead - Bodysnatchers.flac" + "{track} - {artist} - {title}".
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, closeDialog, h, openDialog, setKids } from "./dom.js";
import { api } from "./api.js";
import { plural, state, toast } from "./state.js";
import { folderCache, loadFolder } from "./browse.js";
import { refreshActivity } from "./activity.js";
import { fieldLabel } from "./editor.js";
import { t as tr } from "./i18n.js";

const fn = { target: null, label: "", timer: null, token: 0, data: null, el: {} };
const CHIPS = ["{track}", "{title}", "{artist}", "{album}", "{albumartist}", "{year}", "{disc}", "{skip}", "/"];
const EXAMPLES = ["{track} - {title}", "{track} - {artist} - {title}", "{artist} - {title}", "{track}. {title}",
  "{artist}/{album}/{track} - {title}", "{artist}/{album} ({year})/{track} - {title}"];

export function openFromNames(target, label) {
  fn.target = target; fn.label = tr(label); fn.data = null;
  const el = fn.el;
  el.pattern = h("input", { type: "text", maxlength: "300", spellcheck: "false", autocomplete: "off", autocapitalize: "off",
    placeholder: "{track} - {artist} - {title}", "aria-label": "Pattern", class: "fn-pattern" });
  el.keep = h("input", { type: "checkbox", checked: true });
  el.under = h("input", { type: "checkbox" });
  el.pattern.addEventListener("input", () => previewSoon());
  for (const c of [el.keep, el.under]) c.addEventListener("change", () => previewSoon(0));
  const insert = (text) => {
    const i = el.pattern.selectionStart ?? el.pattern.value.length;
    const j = el.pattern.selectionEnd ?? i;
    el.pattern.value = el.pattern.value.slice(0, i) + text + el.pattern.value.slice(j);
    el.pattern.focus();
    el.pattern.setSelectionRange(i + text.length, i + text.length);
    previewSoon(0);
  };
  const examples = h("select", { "aria-label": "Start from a pattern" },
    h("option", { value: "" }, "Start from a pattern"), EXAMPLES.map((p) => h("option", { value: p }, p)));
  examples.addEventListener("change", () => { if (examples.value) { el.pattern.value = examples.value; examples.value = ""; previewSoon(0); } });
  setKids($("#names-body"),
    h("p", { class: "mb-lead" }, `Fill in the tags of ${fn.label} from their file and folder names. Describe how they're named, and you'll see every change before anything is written.`),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "File names look like"), el.pattern),
    h("div", { class: "fn-chips" }, CHIPS.map((c) => h("button", { class: "fn-chip", type: "button", translate: "no",
      title: c === "/" ? tr("A folder") : c === "{skip}" ? tr("A part to leave out") : null, onclick: () => insert(c) }, c)), examples),
    h("p", { class: "hint" }, "Text outside the braces must be in the name as written. A / reaches into the folders above, so {artist}/{album}/{track} - {title} reads the artist and album from the folders too."),
    h("div", { class: "rep-options" },
      h("label", { class: "rep-check" }, el.keep, "Keep tags that already have a value"),
      h("label", { class: "rep-check" }, el.under, "Underscores are spaces")),
    h("div", { class: "rep-preview", id: "names-preview" }));
  setKids($("#names-foot"), h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", id: "names-apply", disabled: true, onclick: apply }, "Fill in tags"));
  openDialog($("#names-dialog"));
  previewSoon(0); // with no pattern yet, Codetta suggests one
}

function body(dry) {
  return { ...fn.target, pattern: fn.el.pattern.value, keep_existing: fn.el.keep.checked, underscores: fn.el.under.checked, dry_run: dry };
}

function previewSoon(wait = 300) {
  clearTimeout(fn.timer);
  fn.timer = setTimeout(preview, wait);
}

const name = (p) => p.split("/").pop();

async function preview() {
  const box = $("#names-preview");
  const go = $("#names-apply");
  const token = ++fn.token;
  setKids(box, h("p", { class: "hint mbx-wait" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Looking…"));
  try {
    const d = await api("POST", "/api/tags/from-names", body(true));
    if (token !== fn.token) return;
    fn.data = d;
    if (d.suggested && !fn.el.pattern.value) fn.el.pattern.value = d.pattern;
    go.disabled = !d.changing;
    go.textContent = d.changing ? `Fill in ${plural(d.changing, "track")}` : "Fill in tags";
    setKids(box,
      h("p", { class: "rep-count" }, d.changing ? `${plural(d.changing, "track")} of ${d.tracks} would change`
        : d.matched ? `Nothing to change in ${plural(d.matched, "track")}: their tags already say this.` : "No file names fit this pattern."),
      d.suggested && d.matched ? h("p", { class: "hint" }, "Codetta picked the pattern that fits these files best. Change it if it's not right.") : null,
      d.preview.length ? h("ul", { class: "rep-list" }, d.preview.map((p) => h("li", {},
        h("span", { class: "rep-file", dir: "auto" }, name(p.path)),
        p.changes.map((ch) => h("span", { class: "rep-change" }, h("b", {}, fieldLabel(ch.key)), " ",
          ch.old ? [h("del", { dir: "auto" }, ch.old), " → "] : null, h("ins", { dir: "auto" }, ch.new)))))) : null,
      d.changing > d.preview.length ? h("p", { class: "hint" }, `…and ${d.changing - d.preview.length} more`) : null,
      d.unmatched_count ? h("details", { class: "fn-unmatched" },
        h("summary", {}, d.unmatched_count === 1 ? "One file doesn't fit the pattern and will be left alone"
          : `${d.unmatched_count} files don't fit the pattern and will be left alone`),
        h("ul", { class: "rep-list" }, d.unmatched.map((p) => h("li", {}, h("span", { class: "rep-file", dir: "auto" }, name(p)))))) : null);
  } catch (err) {
    if (token !== fn.token) return;
    go.disabled = true;
    setKids(box, h("p", { class: "field-error" }, err.message));
  }
}

async function apply() {
  const go = $("#names-apply");
  go.disabled = true; go.textContent = "Writing…";
  try {
    const d = await api("POST", "/api/tags/from-names", body(false));
    closeDialog($("#names-dialog"));
    toast(d.failed ? `Changed ${d.changed}, ${d.failed} couldn't be changed` : `Filled in ${plural(d.changed, "track")}. Undo is in Activity.`,
      d.failed ? "error" : "success");
    folderCache.clear();
    refreshActivity();
    loadFolder(state.path, { keepScroll: true });
  } catch (err) {
    toast(err.message, "error");
    go.disabled = false; go.textContent = "Fill in tags";
  }
}
