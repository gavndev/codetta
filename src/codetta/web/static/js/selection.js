// The selection bar's tools: copy and paste tags, compare tracks side by side, and Match album
// tags (give stray tracks the album's album-wide tags so players group them).
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, closeDialog, h, icon, openDialog, sentences, setKids } from "./dom.js";
import { api } from "./api.js";
import { changeLine, first, isSpecialPath, plural, state, toast } from "./state.js";
import { fieldLabel, saveClipboard } from "./editor.js";
import { folderCache, loadFolder } from "./browse.js";
import { refreshActivity } from "./activity.js";

// Tags about the song itself, never copied as album tags (the server's list, from /api/fields).
const isTrackKey = (key) => (state.trackKeys || []).includes(key) || key.includes("lyrics") || key.startsWith("acoustid");

const dialog = () => $("#seltool-dialog");
const selectedPaths = () => [...state.selected];

/** The selected tracks with every tag (search results only carry some, so those are fetched). */
async function selectedTracks() {
  const paths = selectedPaths();
  const known = new Map((state.folder?.tracks || []).map((t) => [t.path, t]));
  return Promise.all(paths.map(async (p) => {
    const t = known.get(p);
    if (t && !t.partial && !t.error) return t;
    try { return await api("GET", `/api/track?path=${encodeURIComponent(p)}`); } catch { return t || { path: p, name: p.split("/").pop(), tags: {} }; }
  }));
}

/** Tags in the editor's order, then any others alphabetically. */
function orderKeys(keys) {
  const order = new Map(state.fields.map((f, i) => [f.key, i]));
  return [...keys].sort((a, b) => (order.get(a) ?? 1e6) - (order.get(b) ?? 1e6) || a.localeCompare(b));
}

const joined = (t, key) => (t.tags?.[key] || []).join("; ");
const trackName = (t) => first(t, "title") || t.name || t.path.split("/").pop();

function show(title, body, foot) {
  const d = dialog();
  $("#seltool-title").textContent = title;
  setKids($("#seltool-body"), body);
  setKids($("#seltool-foot"), foot);
  d.classList.remove("compare");
  if (!d.open) openDialog(d);
}

function refreshAfterWrite() {
  folderCache.clear();
  refreshActivity();
  loadFolder(state.path, { keepScroll: true });
}

// ---- Copy ---------------------------------------------------------------------------------------------

export async function copySelected() {
  const tracks = (await selectedTracks()).filter((t) => !t.error);
  if (!tracks.length) return;
  const keys = orderKeys(new Set(tracks.flatMap((t) => Object.keys(t.tags || {}).filter((k) => joined(t, k)))));
  const rows = keys.map((key) => {
    const values = new Set(tracks.map((t) => joined(t, key)));
    const same = values.size === 1;
    const input = h("input", { type: "checkbox", disabled: !same, checked: same && !isTrackKey(key) });
    input.dataset.key = key;
    return { key, input, same, row: h("label", { class: `copy-row${same ? "" : " differs"}` }, input,
      h("span", { class: "copy-key" }, fieldLabel(key)),
      h("span", { class: "copy-val", dir: "auto" }, same ? [...values][0] : "Differs between these tracks")) };
  });
  const go = h("button", { class: "btn primary", type: "button" }, "Copy");
  const sync = () => {
    const n = rows.filter((r) => r.input.checked).length;
    go.disabled = !n;
    go.textContent = n ? `Copy ${plural(n, "tag")}` : "Copy";
  };
  const pick = (test) => { for (const r of rows) if (r.same) r.input.checked = test(r.key); sync(); };
  for (const r of rows) r.input.addEventListener("change", sync);
  go.addEventListener("click", () => {
    const tags = {};
    for (const r of rows) if (r.input.checked) tags[r.key] = tracks[0].tags[r.key];
    saveClipboard({ tags, from: tracks.length === 1 ? trackName(tracks[0]) : plural(tracks.length, "track") });
    closeDialog(dialog());
    syncSelectionTools();
    toast(`Copied ${plural(Object.keys(tags).length, "tag")}. Select other tracks and press Paste.`, "success");
  });
  show(tracks.length === 1 ? `Copy tags from “${trackName(tracks[0])}”` : `Copy tags from ${plural(tracks.length, "track")}`,
    [h("p", { class: "hint" }, "Album tags are ticked. Paste them onto other tracks from this bar or the editor."),
      h("div", { class: "copy-picks" },
        h("button", { class: "btn small", type: "button", onclick: () => pick((k) => !isTrackKey(k)) }, "Album tags"),
        h("button", { class: "btn small", type: "button", onclick: () => pick(() => true) }, "All"),
        h("button", { class: "btn small", type: "button", onclick: () => pick(() => false) }, "None")),
      keys.length ? h("div", { class: "copy-list" }, rows.map((r) => r.row)) : h("p", { class: "hint" }, "These tracks have no tags.")],
    [h("span", { class: "spacer" }), h("button", { class: "btn", type: "button", "data-close": "" }, "Cancel"), go]);
  sync();
}

// ---- Paste --------------------------------------------------------------------------------------------

export async function pasteSelected() {
  const clip = state.clipboard;
  const paths = selectedPaths();
  if (!clip || !paths.length) return;
  const keys = orderKeys(Object.keys(clip.tags));
  const ok = await ask({
    title: `Paste ${plural(keys.length, "tag")} onto ${plural(paths.length, "track")}?`,
    message: clip.from ? `Copied from ${clip.from}. Activity can undo it.` : "Activity can undo it.",
    details: h("ul", { class: "change-list" }, keys.map((k) => h("li", {}, h("b", {}, fieldLabel(k)), h("span", { dir: "auto" }, clip.tags[k].join("; "))))),
    confirmLabel: "Paste",
  });
  if (!ok) return;
  try {
    const res = await api("PATCH", "/api/tracks", { paths, changes: clip.tags });
    const failed = res.filter((r) => !r.ok).length;
    const pasted = res.length - failed;
    toast(failed ? `Pasted onto ${pasted}, ${failed} couldn't be changed` : `Pasted onto ${plural(res.length, "track")}`, failed ? "error" : "success");
    refreshAfterWrite();
  } catch (err) { toast(err.message, "error"); }
}

// ---- Compare ------------------------------------------------------------------------------------------

export async function compareSelected() {
  const tracks = await selectedTracks();
  if (tracks.length < 2) return;
  const keys = orderKeys(new Set(tracks.flatMap((t) => Object.keys(t.tags || {}).filter((k) => joined(t, k)))));
  const differs = (k) => new Set(tracks.map((t) => joined(t, k))).size > 1;
  const albumDiffs = keys.filter((k) => !isTrackKey(k) && differs(k));
  const only = h("input", { type: "checkbox", role: "switch", checked: true });
  const table = h("div", { class: "cmp-table" });
  table.style.setProperty("--cols", tracks.length);
  const draw = () => setKids(table,
    h("div", { class: "cmp-row cmp-headrow" }, h("span", { class: "cmp-key" }, ""),
      tracks.map((t) => h("span", { class: "cmp-cell cmp-head", dir: "auto", title: t.path }, trackName(t)))),
    keys.filter((k) => !only.checked || differs(k)).map((k) => {
      const diff = differs(k);
      return h("div", { class: `cmp-row${diff ? (isTrackKey(k) ? " diff-song" : " diff") : ""}` },
        h("span", { class: "cmp-key" }, fieldLabel(k), isTrackKey(k) ? h("span", { class: "cmp-song" }, "song") : null),
        tracks.map((t) => h("span", { class: `cmp-cell${joined(t, k) ? "" : " empty"}`, dir: "auto" }, joined(t, k) || "—")));
    }));
  only.addEventListener("change", draw);
  draw();
  const summary = albumDiffs.length
    ? h("div", { class: "cmp-summary bad" }, icon("alert"), h("span", {},
      h("b", {}, albumDiffs.length === 1 ? "1 album tag differs:" : `${albumDiffs.length} album tags differ:`), " ",
      h("span", { dir: "auto" }, `${albumDiffs.map(fieldLabel).join(", ")}.`), " ",
      h("span", {}, "Music players can show these tracks as separate albums because of them.")))
    : h("div", { class: "cmp-summary good" }, icon("check"), h("span", {}, "Every album tag matches, so players should group these tracks together."));
  show("Compare tags", [summary,
    h("label", { class: "switch-row cmp-only" }, h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, "Only differences")),
      only),
    table],
  [albumDiffs.length ? h("button", { class: "btn", type: "button", onclick: () => matchSelected() }, icon("disc"), "Match album tags…") : null,
    h("span", { class: "spacer" }), h("button", { class: "btn primary", type: "button", "data-close": "" }, "Done")]);
  dialog().classList.add("compare");
}

// ---- Match album tags ------------------------------------------------------------------------------------

const match = { token: 0, timer: null };

export function matchSelected() {
  const paths = selectedPaths();
  if (!paths.length) return;
  const inFolder = !isSpecialPath(state.path);
  const others = inFolder ? (state.folder?.tracks || []).filter((t) => !t.error && !state.selected.has(t.path)) : [];
  const mode = (value, label, checked) => h("label", { class: "choice" },
    h("input", { type: "radio", name: "match-from", value, checked }), h("span", { class: "choice-text" }, h("span", { class: "choice-title" }, label)));
  const trackSelect = h("select", { "aria-label": "Track to match", disabled: true },
    others.map((t) => h("option", { value: t.path }, `${first(t, "tracknumber") ? `${first(t, "tracknumber").split("/")[0]}. ` : ""}${trackName(t)}`)));
  const removeExtra = h("input", { type: "checkbox", role: "switch", checked: true });
  const preview = h("div", { class: "rep-preview" });
  const go = h("button", { class: "btn primary", type: "button", disabled: true }, "Match");
  const body = () => {
    const from = $('input[name="match-from"]:checked', dialog())?.value || "folder";
    return { paths, track: from === "track" ? trackSelect.value : null, folder: null, remove_extra: removeExtra.checked };
  };
  const run = async () => {
    trackSelect.disabled = $('input[name="match-from"]:checked', dialog())?.value !== "track";
    const token = ++match.token;
    go.disabled = true;
    setKids(preview, h("p", { class: "hint mbx-wait" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Looking…"));
    try {
      const d = await api("POST", "/api/tags/match", { ...body(), dry_run: true });
      if (token !== match.token) return;
      go.disabled = !d.changing;
      go.textContent = d.changing ? `Match ${plural(d.changing, "track")}` : "Match";
      setKids(preview,
        h("p", { class: "rep-count" }, d.changing ? changeLine(d) : "These tracks already match. Nothing to change."),
        d.preview.length ? h("ul", { class: "rep-list" }, d.preview.map((p) => h("li", {},
          h("span", { class: "rep-file", dir: "auto" }, p.path.split("/").pop()),
          p.changes.map((ch) => h("span", { class: "rep-change" }, h("b", {}, fieldLabel(ch.key)), " ",
            ch.old ? h("del", { dir: "auto" }, ch.old) : null, ch.old ? " → " : "", h("ins", { dir: "auto" }, ch.new || "(removed)")))))) : null);
    } catch (err) {
      if (token !== match.token) return;
      setKids(preview, h("p", { class: "field-error" }, err.message));
    }
  };
  const soon = () => { clearTimeout(match.timer); match.timer = setTimeout(run, 150); };
  go.addEventListener("click", async () => {
    go.disabled = true;
    try {
      const d = await api("POST", "/api/tags/match", { ...body(), dry_run: false });
      closeDialog(dialog());
      toast(d.failed ? `Matched ${d.changed}, ${d.failed} couldn't be changed` : `Matched ${plural(d.changed, "track")} to “${d.source}”`, d.failed ? "error" : "success");
      refreshAfterWrite();
    } catch (err) { toast(err.message, "error"); go.disabled = false; }
  });
  show("Match album tags", [
    h("p", { class: "hint" }, sentences([
      paths.length === 1 ? "Gives the selected track the same album tags as the rest of the album, so music players group them as one."
        : `Gives the ${plural(paths.length, "selected track")} the same album tags as the rest of the album, so music players group them as one.`,
      "Tags about the song stay as they are: title, track artist, track and disc number, credits, lyrics, ISRC and song IDs."])),
    h("fieldset", { class: "choices match-from", onchange: soon },
      mode("folder", inFolder ? "What the other tracks in this folder share" : "What the other tracks in their folder share", true),
      others.length ? h("div", { class: "match-track" }, mode("track", "One track", false), trackSelect) : null),
    h("label", { class: "switch-row" },
      h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, "Also remove album tags the others don't have"),
        h("span", { class: "switch-sub" }, "An extra label or release ID on just one track is enough to split an album.")),
      removeExtra),
    preview],
  [h("span", { class: "spacer" }), h("button", { class: "btn", type: "button", "data-close": "" }, "Cancel"), go]);
  trackSelect.addEventListener("change", soon);
  removeExtra.addEventListener("change", soon);
  run();
}

// ---- The bar ---------------------------------------------------------------------------------------------

/** Paste only with something copied; Compare for 2 to 4 tracks. */
export function syncSelectionTools() {
  const n = state.selected.size;
  const paste = $("#sel-paste");
  if (!paste) return;
  paste.hidden = !state.clipboard;
  paste.title = state.clipboard ? `Paste ${Object.keys(state.clipboard.tags).map(fieldLabel).join(", ")}` : "";
  $("#sel-compare").hidden = n < 2 || n > 4;
}

export function setupSelectionTools() {
  document.addEventListener("codetta-clipboard", syncSelectionTools);
  $("#sel-copy").addEventListener("click", copySelected);
  $("#sel-paste").addEventListener("click", pasteSelected);
  $("#sel-compare").addEventListener("click", compareSelected);
  $("#sel-match").addEventListener("click", matchSelected);
  // A small picture beside each button's name.
  for (const [id, name] of [["sel-clear", "close"], ["sel-copy", "copy"], ["sel-paste", "paste"], ["sel-match", "disc"],
    ["sel-compare", "compare"], ["sel-preset", "preset"], ["sel-replace", "replace"], ["sel-actions", "wand"],
    ["sel-download", "download"], ["sel-edit", "pencil"]]) {
    const btn = $(`#${id}`);
    const label = btn.textContent.trim();
    btn.replaceChildren(icon(name), h("span", { class: "lbl" }, label));
    if (!btn.title) btn.title = label; // the name, when a narrow screen shows only the picture
  }
}
