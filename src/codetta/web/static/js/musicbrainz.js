// Matching on MusicBrainz and switching editions.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, closeDialog, h, icon, openDialog, setKids } from "./dom.js";
import { api } from "./api.js";
import { fmtDuration, plural, relativeToFolder, state, toast } from "./state.js";
import { folderCache, isSearch, loadFolder } from "./browse.js";
import { folderCovers } from "./tools.js";
import { confirmDiscard, folderTrackPaths } from "./editor.js";
import { refreshActivity } from "./activity.js";
import { connectionOn } from "./setup.js";

// ---- Match on MusicBrainz ---------------------------------------------------------------------------
//
// Two steps in one sheet: pick the release (search results, or a pasted link),
// then review what changes per file before anything is written.

const mb = {
  target: null, // { body: {folder} | {paths}, label }
  query: { album: "", artist: "", link: "" },
  results: null, // /api/musicbrainz/search response
  error: null,
  busy: false,
  release: null, // chosen release id
  proposal: null, // /api/musicbrainz/preview response
  pairs: {}, // path -> track id ("" = leave this file alone), only the user's own picks
  recordings: {}, // path -> recording IDs heard by Identify by sound
  sound: null, // the last /api/musicbrainz/identify summary
  fields: null, // Set of tag names, or null for the server's default set
  mode: "overwrite",
  cover: "missing",
  openGroups: new Set(),
  openFiles: new Set(),
  token: 0,
  timer: null,
};

function mbTarget() {
  const n = state.selected.size;
  if (n) return { body: { paths: [...state.selected] }, label: plural(n, "selected track") };
  if (isSearch()) return { body: { paths: folderTrackPaths().slice(0, 1000) }, label: plural(Math.min(folderTrackPaths().length, 1000), "result") };
  return { body: { folder: state.path }, label: "this folder" };
}

export async function openMusicBrainz({ source = "auto" } = {}) {
  if (!(await confirmDiscard())) return;
  openMusicBrainzFor(mbTarget(), { source });
}

const SOURCE_NAMES = { auto: "MusicBrainz", deezer: "Deezer", itunes: "iTunes" };
const sourceName = () => (mb.source === "auto" && !connectionOn("musicbrainz") ? "Deezer and iTunes" : SOURCE_NAMES[mb.source || "auto"]);

/** Open the match dialog for any set of files; ``release`` jumps straight to its review. */
export function openMusicBrainzFor(target, { release = null, recordings = {}, onWritten = null, source = "auto" } = {}) {
  Object.assign(mb, {
    target, source, query: { album: "", artist: "", link: "" }, results: null, error: null,
    release: null, proposal: null, pairs: {}, fields: null, mode: "overwrite", cover: "missing",
    openGroups: new Set(), openFiles: new Set(), recordings: recordings || {}, sound: null, onWritten,
  });
  $("#mb-title").textContent = source !== "auto" ? `Find in ${SOURCE_NAMES[source]}`
    : connectionOn("musicbrainz") ? "Match on MusicBrainz" : "Find album details";
  openDialog($("#mb-dialog"));
  if (release) mbPick(release);
  else mbSearch({});
}

async function mbSearch(extra) {
  const token = ++mb.token;
  mb.busy = true;
  mb.error = null;
  mb.release = null;
  renderMbSearch();
  try {
    const res = await api("POST", "/api/musicbrainz/search", { ...mb.target.body, ...extra, source: mb.source || "auto" });
    if (token !== mb.token) return;
    mb.results = res;
    if (!extra.release) Object.assign(mb.query, { album: res.query.album, artist: res.query.artist });
    // A pasted link names exactly one release: go straight to the review.
    if (extra.release && res.candidates.length === 1) { mbPick(res.candidates[0].id); return; }
  } catch (err) {
    if (token !== mb.token) return;
    mb.error = err.message;
  }
  mb.busy = false;
  renderMbSearch();
}

/** Identify by sound: fingerprint the files on the server, ask AcoustID what they are. */
async function mbIdentify() {
  const token = ++mb.token;
  mb.busy = "sound";
  mb.error = null;
  renderMbSearch();
  try {
    const res = await api("POST", "/api/musicbrainz/identify", mb.target.body);
    if (token !== mb.token) return;
    mb.results = res;
    mb.recordings = res.recordings;
    mb.sound = { identified: res.identified, total: res.total, files: res.files };
  } catch (err) {
    if (token !== mb.token) return;
    mb.error = err.message;
  }
  mb.busy = false;
  renderMbSearch();
}

/** A release's cover. ``fallback``: another picture to try when there's none (the files' own cover). */
export function mbThumb(id, size = 250, fallback = null) {
  const empty = () => h("span", { class: "mb-thumb mb-noart", "aria-hidden": "true" }, icon("note"));
  if (!id && !fallback) return empty();
  const img = h("img", { class: "mb-thumb", src: id ? `/api/musicbrainz/cover/${id}?size=${size}` : fallback, alt: "",
    loading: "lazy", decoding: "async", width: "56", height: "56" });
  img.addEventListener("error", function onError() {
    if (fallback && img.getAttribute("src") !== fallback) { img.src = fallback; return; }
    img.removeEventListener("error", onError);
    img.replaceWith(empty());
  });
  return img;
}

const mbYear = (date) => (date || "").slice(0, 4);

/** The cover already in the files being matched (most downloads have one), as a last resort. */
const ownCover = (p) => {
  const f = (p?.files || []).find((x) => x.has_art);
  return f ? `/api/art?path=${encodeURIComponent(f.path)}` : null;
};

export function mbMeta(c) {
  return [mbYear(c.date), c.country, c.formats, c.track_count ? plural(c.track_count, "track") : "", c.labels[0], c.type]
    .filter(Boolean).join(" · ");
}

function renderMbSearch() {
  const body = $("#mb-body");
  const album = h("input", { type: "text", value: mb.query.album, dir: "auto", autocomplete: "off", spellcheck: "false", "aria-label": "Album" });
  const artist = h("input", { type: "text", value: mb.query.artist, dir: "auto", autocomplete: "off", spellcheck: "false", "aria-label": "Artist" });
  const link = h("input", { type: "text", value: mb.query.link, autocomplete: "off", spellcheck: "false", inputmode: "url",
    placeholder: "https://musicbrainz.org/release/…", "aria-label": "MusicBrainz release link" });
  for (const [input, key] of [[album, "album"], [artist, "artist"], [link, "link"]]) {
    input.addEventListener("input", () => { mb.query[key] = input.value; });
  }
  const search = (e) => {
    e.preventDefault();
    mbSearch({ album: album.value.trim(), artist: artist.value.trim() });
  };
  const useLink = (e) => {
    e.preventDefault();
    if (link.value.trim()) mbSearch({ release: link.value.trim() });
  };
  const res = mb.results;
  let list;
  if (mb.busy === "sound") list = h("p", { class: "loading" }, "Listening to your tracks, then asking AcoustID… (a few seconds per track)");
  else if (mb.busy) list = h("p", { class: "loading" }, `Asking ${sourceName()}…`);
  else if (mb.error) list = h("div", { class: "error-box" }, mb.error);
  else if (res && !res.candidates.length) {
    list = h("p", { class: "mb-empty" }, res.query.album || res.query.artist
      ? (mb.source && mb.source !== "auto" ? `${SOURCE_NAMES[mb.source]} has nothing for this. Try fewer words.` : "No releases found. Try fewer words, or paste the release link from musicbrainz.org.")
      : connectionOn("acoustid")
        ? "These tracks have no album or artist yet. Type what to search for, or identify them by sound."
        : "These tracks have no album or artist yet. Type what to search for above.");
  } else if (res) {
    list = h("div", { class: "mb-cands", role: "list" }, res.note ? h("p", { class: "hint mb-note" }, res.note) : null, res.candidates.map((c) => h("button", {
      type: "button", class: "mb-cand", role: "listitem", onclick: () => mbPick(c.id),
    },
      mbThumb(c.id),
      h("span", { class: "mb-cand-main" },
        h("span", { class: "mb-cand-title", dir: "auto" }, c.title, c.disambiguation ? h("span", { class: "mb-dis" }, ` (${c.disambiguation})`) : null),
        h("span", { class: "mb-cand-artist", dir: "auto" }, c.artist),
        h("span", { class: "mb-cand-meta" }, mbMeta(c)),
        c.heard != null ? h("span", { class: "mb-heard" }, `${c.heard} of your ${plural(res.total, "track")} ${c.heard === 1 ? "is" : "are"} on it`) : null,
        c.current ? h("span", { class: "mb-current" }, h("span", { class: "badge" }, "Your files use this release")) : null,
        c.source && c.source !== "musicbrainz" ? h("span", { class: `src-badge ${c.source}` }, c.source === "deezer" ? "From Deezer" : "From iTunes") : null),
      h("span", { class: "mb-cand-side" },
        h("span", { class: `mb-score ${c.score >= 85 ? "good" : c.score >= 60 ? "ok" : "low"}`, title: "How well this release fits these files" }, `${c.score}%`),
        h("span", { class: "mb-chev" }, icon("chevron"))))));
  }
  const sound = mb.sound;
  const unknown = sound ? sound.files.filter((f) => f.status !== "identified") : [];
  const catalogOnly = mb.source && mb.source !== "auto";
  const soundBox = connectionOn("acoustid") && !catalogOnly ? h("div", { class: "mb-sound" },
    h("div", { class: "mb-sound-text" },
      h("strong", {}, "Identify by sound"),
      h("span", {}, sound
        ? `Recognised ${sound.identified} of ${plural(sound.total, "track")}.${unknown.length ? ` Not recognised: ${unknown.slice(0, 3).map((f) => relativeToFolder(f.path)).join(", ")}${unknown.length > 3 ? ` +${unknown.length - 3} more` : ""}.` : ""}`
        : "Works even on untagged files. Codetta fingerprints each track here and sends only that code to AcoustID.")),
    h("button", { class: "btn", type: "button", disabled: !!mb.busy, "aria-busy": String(mb.busy === "sound"), onclick: mbIdentify },
      mb.busy === "sound" ? "Listening…" : sound ? "Listen again" : "Listen")) : null;
  setKids(body,
    h("p", { class: "mb-lead" }, `Find the release for ${mb.target.label}. Pick the exact edition (year, country, format), then review every change before it's written.`),
    soundBox,
    h("form", { class: "mb-search", onsubmit: search },
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Album"), album),
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Artist"), artist),
      h("button", { class: "btn", type: "submit", disabled: mb.busy }, icon("search"), "Search")),
    catalogOnly ? null : h("form", { class: "mb-link", onsubmit: useLink },
      h("label", { class: "field" }, h("span", { class: "field-label" }, "Or paste a release link"), link),
      h("button", { class: "btn", type: "submit", disabled: mb.busy }, "Use link")),
    list);
  const credit = { deezer: ["Deezer", "https://www.deezer.com"], itunes: ["iTunes", "https://music.apple.com"] }[mb.source] || ["MusicBrainz", "https://musicbrainz.org"];
  setKids($("#mb-foot"),
    h("span", { class: "mb-credit" }, "Data from ", h("a", { href: credit[1], target: "_blank", rel: "noopener noreferrer" }, credit[0])),
    h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"));
}

// ---- Editions: every edition of the album, to switch between ------------------------------------

async function loadEditions(id) {
  if (mb.editions?.for === id) return;
  mb.editions = { for: id, loading: true };
  try {
    const d = await api("GET", `/api/musicbrainz/editions?release=${encodeURIComponent(id)}`);
    mb.editions = { for: id, ...d };
  } catch (err) { mb.editions = { for: id, error: err.message }; }
  if (mb.showEditions) renderMbReview();
}

function editionsList(id) {
  const e = mb.editions;
  if (!e || e.for !== id || e.loading) return h("p", { class: "loading mb-editions" }, "Finding every edition on MusicBrainz…");
  if (e.error) return h("div", { class: "error-box" }, e.error);
  return h("div", { class: "mb-editions" },
    h("p", { class: "hint" }, `${plural(e.editions.length, "edition")} of “${e.title}”${e.first ? `, first released ${mbYear(e.first)}` : ""}. Pick the one that matches your copy.`),
    h("ul", { class: "mb-edition-list" }, e.editions.map((c) => h("li", {},
      h("button", { class: `mb-edition${c.current ? " current" : ""}`, type: "button", disabled: c.current,
        onclick: () => { mb.showEditions = false; mbPick(c.id); } },
      h("span", { class: "mb-edition-main" },
        h("strong", {}, [mbYear(c.date) || "No date", c.country].filter(Boolean).join(" · ")),
        h("span", {}, [c.formats, c.track_count ? plural(c.track_count, "track") : "", c.labels[0], c.disambiguation].filter(Boolean).join(" · "))),
      c.current ? h("span", { class: "mb-edition-tag" }, "This one") : c.recommended ? h("span", { class: "mb-edition-tag rec" }, "Recommended") : null)))));
}

export async function openEditionPrefs() {
  let p;
  try { p = await api("GET", "/api/editions"); } catch (err) { toast(err.message, "error"); return; }
  const sw = (name, title, sub, on) => h("label", { class: "switch-row" },
    h("span", { class: "switch-text" }, h("span", { class: "switch-title" }, title), h("span", { class: "switch-sub" }, sub)),
    h("input", { type: "checkbox", role: "switch", name, checked: on }));
  const format = h("select", { name: "format" }, [["any", "Any"], ["digital", "Digital"], ["cd", "CD"], ["vinyl", "Vinyl"]]
    .map(([v, l]) => h("option", { value: v, selected: p.format === v }, l)));
  const countries = [["", "Any"], ["XW", "Worldwide"], ["US", "United States"], ["GB", "United Kingdom"], ["CA", "Canada"], ["AU", "Australia"],
    ["DE", "Germany"], ["FR", "France"], ["JP", "Japan"], ["NL", "Netherlands"], ["SE", "Sweden"], ["IT", "Italy"], ["ES", "Spain"], ["BR", "Brazil"]];
  if (p.country && !countries.some(([v]) => v === p.country)) countries.push([p.country, p.country]);
  const country = h("select", { name: "country" }, countries.map(([v, l]) => h("option", { value: v, selected: p.country === v }, l)));
  const form = h("div", { class: "edition-prefs" },
    sw("original_year", "Use the album's original year", "A 2011 reissue of a 1977 album is tagged and filed as 1977.", p.original_year),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Preferred format"), format),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Preferred country"), country),
    sw("avoid_deluxe", "Prefer the standard edition", "Skip deluxe and expanded editions, unless your files match one.", p.avoid_deluxe));
  const ok = await ask({ title: "Album editions", confirmLabel: "Save", details: form,
    message: "An album can have dozens of editions. When Codetta matches on its own (the inbox, Tidy up), it picks the one you'd pick." });
  if (!ok) return;
  try {
    await api("PUT", "/api/editions", { original_year: $('[name="original_year"]', form).checked, format: format.value,
      country: country.value, avoid_deluxe: $('[name="avoid_deluxe"]', form).checked });
    toast("Saved", "success");
  } catch (err) { toast(err.message, "error"); }
}

function mbPick(id) {
  mb.release = id;
  mb.proposal = null;
  mb.pairs = {};
  mb.fields = null;
  mb.openFiles = new Set();
  mb.error = null;
  mbPreview(0);
}

function mbBody(extra = {}) {
  return {
    ...mb.target.body, release: mb.release, mode: mb.mode, cover: mb.cover,
    pairs: Object.fromEntries(Object.entries(mb.pairs).map(([p, t]) => [p, t || null])),
    recordings: mb.recordings,
    fields: mb.fields ? [...mb.fields] : null,
    ...extra,
  };
}

function mbPreview(delay = 200) {
  clearTimeout(mb.timer);
  mb.busy = true;
  if (!mb.proposal) renderMbReview();
  else $("#mb-go")?.setAttribute("disabled", "");
  mb.timer = setTimeout(async () => {
    const token = ++mb.token;
    try {
      const p = await api("POST", "/api/musicbrainz/preview", mbBody());
      if (token !== mb.token) return;
      mb.proposal = p;
      mb.error = null;
      if (!mb.fields) mb.fields = new Set(p.fields);
    } catch (err) {
      if (token !== mb.token) return;
      mb.error = err.message;
    }
    mb.busy = false;
    renderMbReview();
  }, delay);
}

function mbValue(values) {
  return values.length ? values.join("; ") : "";
}

function renderMbReview() {
  const body = $("#mb-body");
  const p = mb.proposal;
  const back = h("button", { class: "btn", type: "button", onclick: () => { mb.release = null; mb.busy = false; renderMbSearch(); } }, "Back");
  if (!p) {
    setKids(body, mb.error ? h("div", { class: "error-box" }, mb.error) : h("p", { class: "loading" }, "Reading the release from MusicBrainz…"));
    setKids($("#mb-foot"), back, h("span", { class: "spacer" }), h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"));
    return;
  }
  const scroll = body.scrollTop;
  const r = p.release;
  const labels = new Map(p.groups.flatMap((g) => g.fields.map((f) => [f.key, f.label])));

  // Fields to include, by group.
  const groups = h("div", { class: "mb-groups" }, p.groups.map((g) => {
    const keys = g.fields.map((f) => f.key);
    const on = keys.filter((k) => mb.fields.has(k)).length;
    const all = h("input", { type: "checkbox", checked: on === keys.length, indeterminate: on > 0 && on < keys.length });
    all.addEventListener("change", () => {
      for (const k of keys) all.checked ? mb.fields.add(k) : mb.fields.delete(k);
      mbPreview();
      renderMbReview();
    });
    const open = mb.openGroups.has(g.id);
    return h("div", { class: `mb-group${open ? " open" : ""}` },
      h("div", { class: "mb-group-row" },
        h("label", { class: "check" }, all, h("span", { class: "mb-group-name" }, g.label)),
        keys.length > 1 ? h("button", {
          class: "link-btn mb-group-more", type: "button", "aria-expanded": String(open),
          onclick: () => { open ? mb.openGroups.delete(g.id) : mb.openGroups.add(g.id); renderMbReview(); },
        }, on === keys.length ? "All" : `${on} of ${keys.length}`, icon("chevron")) : null),
      open ? h("div", { class: "mb-group-fields" }, g.fields.map((f) => {
        const box = h("input", { type: "checkbox", checked: mb.fields.has(f.key) });
        box.addEventListener("change", () => {
          box.checked ? mb.fields.add(f.key) : mb.fields.delete(f.key);
          mbPreview();
          renderMbReview();
        });
        return h("label", { class: "check" }, box, f.label);
      })) : null);
  }));

  const segmented = (name, value, options, onpick, disabled = false) => h("div", { class: "segmented" },
    options.map(([v, label]) => {
      const input = h("input", { type: "radio", name, value: v, checked: value === v, disabled });
      input.addEventListener("change", () => { onpick(v); mbPreview(); });
      return h("label", {}, input, h("span", {}, label));
    }));

  // Files and what changes in each.
  const used = new Set(p.files.map((f) => f.track?.id).filter(Boolean));
  const multiDisc = new Set(p.tracks.map((t) => t.disc)).size > 1;
  const trackLabel = (t) => `${multiDisc ? `${t.disc}-` : ""}${t.number || t.position}. ${t.title}${t.length ? ` (${fmtDuration(t.length)})` : ""}`;
  const changing = p.files.filter((f) => !f.error && f.track && (Object.keys(f.changes).length || f.cover));
  const tagTotal = changing.reduce((n, f) => n + Object.keys(f.changes).length, 0);
  const covers = changing.filter((f) => f.cover).length;
  const check = p.files.filter((f) => f.confidence === "check" || (!f.track && !f.error)).length;
  const files = p.files.map((f) => {
    const name = relativeToFolder(f.path);
    if (f.error) return h("div", { class: "mb-file error" }, h("div", { class: "mb-file-name" }, name), h("div", { class: "note" }, f.error));
    const select = h("select", { "aria-label": `Track for ${name}` },
      h("option", { value: "" }, "Leave this file alone"),
      p.tracks.map((t) => h("option", { value: t.id, selected: f.track?.id === t.id },
        `${trackLabel(t)}${used.has(t.id) && f.track?.id !== t.id ? "  · used" : ""}`)));
    select.addEventListener("change", () => { mb.pairs[f.path] = select.value; mbPreview(0); });
    const keys = Object.keys(f.changes);
    const state_ = !f.track ? "skip" : f.confidence === "check" ? "check" : "ok";
    const diff = keys.length || f.cover ? h("details", { class: "mb-diff", open: mb.openFiles.has(f.path) },
      h("summary", {}, [keys.length ? plural(keys.length, "tag") : "", f.cover ? "cover art" : ""].filter(Boolean).join(" + ")),
      h("div", { class: "mb-diff-list" },
        keys.map((k) => h("div", { class: "mb-diff-row" },
          h("span", { class: "mb-diff-key" }, labels.get(k) || k),
          h("span", { class: "mb-diff-val", dir: "auto" },
            f.changes[k].old.length ? [h("span", { class: "mb-old" }, mbValue(f.changes[k].old)), " → "] : null,
            h("span", { class: "mb-new" }, mbValue(f.changes[k].new))))),
        f.cover ? h("div", { class: "mb-diff-row" }, h("span", { class: "mb-diff-key" }, "Cover art"),
          h("span", { class: "mb-diff-val" }, f.has_art ? "Replace with the release's front cover" : "Add the release's front cover")) : null)) : null;
    if (diff) diff.addEventListener("toggle", () => { diff.open ? mb.openFiles.add(f.path) : mb.openFiles.delete(f.path); });
    return h("div", { class: `mb-file ${state_}` },
      h("div", { class: "mb-file-head" },
        h("span", { class: "mb-file-icon", role: "img", "aria-label": state_ === "ok" ? "Matched" : state_ === "check" ? "Check this match" : "Not matched" },
          icon(state_ === "ok" ? "check" : "alert")),
        h("span", { class: "mb-file-name", title: f.path }, name),
        select),
      f.notes?.length && state_ !== "ok" ? h("div", { class: "note" }, f.notes.join(" · ")) : null,
      f.unsupported?.length ? h("div", { class: "note" }, `This format can't store: ${f.unsupported.map((k) => labels.get(k) || k).join(", ")}`) : null,
      diff || (f.track ? h("div", { class: "note" }, "Already matches") : null));
  });
  const spare = p.tracks.filter((t) => !used.has(t.id)).length;

  const summary = [];
  if (changing.length) summary.push(`${plural(changing.length, "track")} will change (${plural(tagTotal, "tag")}${covers ? `, cover on ${covers}` : ""}).`);
  else summary.push("Nothing to change with these settings.");
  if (check) summary.push(`${plural(check, "file")} to check.`);
  if (spare) summary.push(`${plural(spare, "track")} on this release ${spare === 1 ? "has" : "have"} no file here.`);

  setKids(body,
    h("div", { class: "mb-release" },
      mbThumb(r.id, 250, ownCover(p)),
      h("div", { class: "mb-release-main" },
        h("div", { class: "mb-cand-title", dir: "auto" }, r.title, r.disambiguation ? h("span", { class: "mb-dis" }, ` (${r.disambiguation})`) : null),
        h("div", { class: "mb-cand-artist", dir: "auto" }, r.artist),
        h("div", { class: "mb-cand-meta" }, mbMeta(r)),
        h("div", { class: "mb-release-links" },
          h("button", { class: "link-btn", type: "button", onclick: () => { mb.release = null; mb.busy = false; renderMbSearch(); } }, "Choose another release"),
          r.source === "musicbrainz" && connectionOn("musicbrainz") ? h("button", { class: "link-btn", type: "button", "aria-expanded": String(!!mb.showEditions),
            onclick: () => { mb.showEditions = !mb.showEditions; renderMbReview(); if (mb.showEditions) loadEditions(r.id); } }, "Other editions") : null,
          h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, "View on MusicBrainz")))),
    mb.showEditions ? editionsList(r.id) : null,
    mb.error ? h("div", { class: "error-box" }, mb.error) : null,
    h("div", { class: "field" }, h("span", { class: "field-label" }, "Include"), groups),
    h("div", { class: "mb-options" },
      h("fieldset", { class: "field" }, h("legend", { class: "field-label" }, "Existing values"),
        segmented("mb-mode", mb.mode, [["overwrite", "Replace"], ["fill", "Only fill empty"]], (v) => { mb.mode = v; })),
      h("fieldset", { class: "field" }, h("legend", { class: "field-label" }, "Cover art"),
        segmented("mb-cover", r.has_cover === false ? "none" : mb.cover,
          [["missing", "Where missing"], ["all", "Replace all"], ["none", "Leave"]], (v) => { mb.cover = v; }, r.has_cover === false),
        r.has_cover === false ? h("p", { class: "hint" }, "This release has no cover art on the Cover Art Archive.") : null)),
    h("p", { class: "preview-summary", "aria-live": "polite" }, summary.join(" ")),
    h("div", { class: "mb-files" }, files));
  body.scrollTop = scroll;

  setKids($("#mb-foot"),
    back,
    h("span", { class: "spacer" }),
    h("button", { class: "btn", type: "button", "data-close": true }, "Cancel"),
    h("button", { class: "btn primary", type: "button", id: "mb-go", disabled: mb.busy || !changing.length, onclick: mbApply },
      changing.length ? `Write to ${plural(changing.length, "track")}` : "Write"));
}

async function mbApply() {
  const go = $("#mb-go");
  go.disabled = true;
  go.textContent = "Writing…";
  try {
    const res = await api("POST", "/api/musicbrainz/apply", mbBody());
    closeDialog($("#mb-dialog"));
    const failed = res.results.filter((r) => !r.ok);
    if (failed.length) toast(`Tagged ${plural(res.updated, "track")}; ${failed.length} failed: ${failed[0].error}`, "error");
    else toast(`Tagged ${plural(res.updated, "track")} from MusicBrainz. Undo is in the activity log.`, "success");
    if (res.cover_error) toast(`Cover art wasn't added: ${res.cover_error}`, "error");
    if (mb.onWritten) { const done = mb.onWritten; mb.onWritten = null; done(mb.release); }
    refreshActivity();
    folderCache.clear(); folderCovers.clear();
    await loadFolder(state.path, { keepScroll: true });
  } catch (err) {
    toast(err.message, "error");
    mbPreview(0);
  }
}
