// ReplayGain: measure loudness and write the tags players use to play everything at one volume.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, closeDialog, h, openDialog, setKids } from "./dom.js";
import { api } from "./api.js";
import { plural, state, toast } from "./state.js";
import { folderCache, loadFolder } from "./browse.js";
import { refreshActivity } from "./activity.js";
import { t as tr } from "./i18n.js";

const rg = { target: null, label: "", mode: "album", data: null, token: 0 };

export const replayGainReady = () => !!state.status?.replaygain;

/** Open the ReplayGain sheet for { folder } or { paths }. */
export function openReplayGain(target, label) {
  rg.target = target; rg.label = tr(label); rg.data = null; // "this folder" in the reader's language
  rg.mode = target.paths?.length === 1 ? "track" : "album";
  openDialog($("#rg-dialog"));
  measure();
}

function modePicker() {
  return h("div", { class: "segmented rg-mode", role: "radiogroup", "aria-label": "How to measure" },
    [["album", "As albums"], ["track", "Each track on its own"]].map(([v, label]) => {
      const input = h("input", { type: "radio", name: "rg-mode", value: v, checked: rg.mode === v });
      input.addEventListener("change", () => { rg.mode = v; measure(); });
      return h("label", {}, input, h("span", {}, label));
    }));
}

function intro() {
  return [
    h("p", { class: "mb-lead" }, `Evens out the volume of ${rg.label}, so a quiet album and a loud one play at the same level in Navidrome, Plex, Jellyfin and most players.`),
    modePicker(),
    h("p", { class: "hint" }, rg.mode === "album"
      ? "Albums keep their own ups and downs: quiet songs stay quieter than loud ones, as the artist meant. Best for most music."
      : "Every track at the same level. Handy for playlists of singles."),
  ];
}

async function measure() {
  const token = ++rg.token;
  setKids($("#rg-body"), intro(), h("p", { class: "hint mbx-wait" }, h("span", { class: "spinner", "aria-hidden": "true" }),
    "Measuring loudness… (a second or two per track)"));
  setKids($("#rg-foot"), h("span", { class: "spacer" }), h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", disabled: true }, "Write ReplayGain"));
  try {
    const d = await api("POST", "/api/replaygain", { ...rg.target, mode: rg.mode, dry_run: true });
    if (token !== rg.token) return;
    rg.data = d;
    render();
  } catch (err) {
    if (token !== rg.token) return;
    setKids($("#rg-body"), intro(), h("div", { class: "error-box" }, err.message));
  }
}

const name = (p) => p.split("/").pop();
const lufs = (x) => (x == null ? "silent" : `${x.toFixed(1)} LUFS`);

function render() {
  const d = rg.data;
  setKids($("#rg-body"), intro(),
    h("div", { class: "rg-results" }, d.albums.map((a) => h("section", { class: "rg-album" },
      rg.mode === "album" ? h("div", { class: "rg-album-head" },
        h("strong", { dir: "auto" }, name(a.folder) || "Library"),
        h("span", { class: "rg-gain" }, a.gain || "—"), h("span", { class: "hint" }, lufs(a.loudness))) : null,
      h("ul", { class: "rg-list" }, a.tracks.map((t) => h("li", {},
        h("span", { class: "rg-file", dir: "auto" }, name(t.path)),
        h("span", { class: "rg-gain" }, t.gain || "—"),
        h("span", { class: "hint" }, lufs(t.loudness)))))))),
    d.failed.length ? h("div", { class: "rg-failed" }, h("p", { class: "field-error" }, `${plural(d.failed.length, "track")} couldn't be measured:`),
      h("ul", { class: "rg-list" }, d.failed.slice(0, 10).map((f) => h("li", {}, h("span", { class: "rg-file", dir: "auto" }, name(f.path)),
        h("span", { class: "hint" }, f.error))))) : null,
    h("p", { class: "hint" }, "Players turn tracks up or down by the gain shown. The music itself isn't changed, only its tags, and Activity can undo it."));
  setKids($("#rg-foot"), h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", id: "rg-apply", disabled: !d.measured, onclick: apply },
      d.measured ? `Write ReplayGain to ${plural(d.measured, "track")}` : "Write ReplayGain"));
}

async function apply() {
  const go = $("#rg-apply");
  go.disabled = true; go.textContent = "Writing…";
  try {
    const d = await api("POST", "/api/replaygain", { ...rg.target, mode: rg.mode, dry_run: false });
    closeDialog($("#rg-dialog"));
    toast(d.write_failed ? `Wrote ReplayGain to ${d.changed}, ${d.write_failed} couldn't be changed`
      : `ReplayGain written to ${plural(d.changed, "track")}. Undo is in Activity.`, d.write_failed ? "error" : "success");
    folderCache.clear();
    refreshActivity();
    loadFolder(state.path, { keepScroll: true });
  } catch (err) {
    toast(err.message, "error");
    go.disabled = false; go.textContent = "Write ReplayGain";
  }
}
