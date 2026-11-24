// The inbox and Soulseek through slskd.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, closeDialog, h, icon, openDialog, setKids } from "./dom.js";
import { api } from "./api.js";
import { plural, toast } from "./state.js";
import { folderCache, navigate } from "./browse.js";
import { openSoulseek } from "./search.js";
import { folderCovers } from "./tools.js";
import { refreshActivity } from "./activity.js";
import { connectionOn, inboxLabel, inboxSettingsFields, readInboxFields } from "./setup.js";
import { mbMeta, mbThumb, openMusicBrainzFor } from "./musicbrainz.js";
import { pollNotifications } from "./notifications.js";
import { pickImport } from "./files.js";
import { openSettings } from "./settings.js";

// ---- Inbox: new music waiting to be filed -------------------------------------------------------------

const inboxState = { data: null, timer: null, settingsOpen: false };
const INBOX_LABELS = {
  downloading: "Still arriving", waiting: "Waiting", matching: "Looking up…", ready: "Ready", review: "Not sure", nomatch: "Not found",
  local: "Files by its tags", filed: "Filed", skipped: "Skipped", error: "Problem",
};
const inboxPending = (d) => (d?.groups || []).filter((g) => !["filed", "skipped"].includes(g.status)).length;
// "2 albums and 3 songs": a loose download is one song, not an album.
const inboxWaitingText = (d) => {
  const left = (d?.groups || []).filter((g) => !["filed", "skipped"].includes(g.status));
  const songs = left.filter((g) => g.files === 1).length;
  return [left.length - songs ? plural(left.length - songs, "album") : "", songs ? plural(songs, "song") : ""].filter(Boolean).join(" and ");
};

export async function refreshInboxBadge(data = null) {
  try { data = data || await api("GET", "/api/inbox"); } catch { return; }
  inboxState.data = data;
  const n = inboxPending(data);
  $("#inbox-btn").hidden = false; // always reachable: with no folder yet, it opens the setup
  $("#inbox-count").hidden = !n;
  $("#inbox-count").textContent = n > 99 ? "99+" : String(n);
}

export async function openInbox() {
  openDialog($("#inbox-dialog"));
  setKids($("#inbox-body"), h("p", { class: "loading" }, "Looking in your inbox…"));
  setKids($("#inbox-foot"));
  await loadInbox();
}

/** Settings → Inbox: the folder, automatic filing, watching and moving, saved with a button. */
export async function inboxSettings() {
  let d, root;
  try { [d, root] = await Promise.all([api("GET", "/api/inbox"), api("GET", "/api/browse?path=").catch(() => ({ folders: [] }))]); }
  catch (err) { return h("p", { class: "error-box" }, err.message); }
  const form = h("form", { class: "inbox-settings set-pad" },
    h("p", { class: "hint set-lead" }, "The folder new music lands in (downloads, rips). Codetta finds each album on MusicBrainz and files it into your music folder."),
    inboxSettingsFields(d.settings, root.folders, d.external),
    h("div", { class: "set-actions" }, h("button", { class: "btn primary", type: "submit" }, "Save")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      inboxState.data = await api("PUT", "/api/inbox/settings", readInboxFields(form));
      refreshInboxBadge(inboxState.data);
      toast("Saved", "success");
    } catch (err) { toast(err.message, "error"); }
  });
  return form;
}

export async function loadInbox() {
  clearTimeout(inboxState.timer);
  try {
    inboxState.data = await api("GET", "/api/inbox");
  } catch (err) {
    setKids($("#inbox-body"), h("div", { class: "error-box" }, err.message));
    return;
  }
  renderInbox();
  // Keep it fresh while lookups run (and, more slowly, while downloads arrive) and the sheet is open.
  if ($("#inbox-dialog").open && (inboxState.data.running || inboxState.data.downloading)) {
    const live = inboxState.data.groups.some((g) => g.transfer); // a progress bar to keep moving
    inboxState.timer = setTimeout(loadInbox, inboxState.data.running ? 1500 : live ? 3000 : 15000);
  }
}

async function inboxAction(url, body, done) {
  try {
    const res = await api("POST", url, body);
    inboxState.data = res.inbox || res;
    if (done) done(res);
    renderInbox();
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    if (inboxState.data.running) inboxState.timer = setTimeout(loadInbox, 1500);
    setTimeout(pollNotifications, 2000);
  } catch (err) {
    toast(err.message, "error");
  }
}

function reviewInboxGroup(g) {
  closeDialog($("#inbox-dialog"));
  openMusicBrainzFor({ body: { paths: g.paths }, label: `“${g.title || g.key.split("/").pop()}”` }, {
    release: g.release?.id, recordings: g.recordings,
    onWritten: (release) => inboxAction("/api/inbox/accept", { key: g.key, release }, (res) => {
      toast(res.moved_to ? `Filed in ${res.moved_to}` : "Tagged", res.status === "filed" ? "success" : "error");
    }),
  });
}

function renderInbox() {
  const d = inboxState.data;
  const body = $("#inbox-body");
  refreshInboxBadge(d);
  if (!d.settings.folder || !d.folder_exists || inboxState.settingsOpen) {
    api("GET", "/api/browse?path=").catch(() => ({ folders: [] })).then((root) => {
      const form = h("form", { class: "inbox-settings" },
        h("p", { class: "mb-lead" }, d.settings.folder && !d.folder_exists
          ? `The inbox folder (${inboxLabel(d.settings.folder)}) isn't there any more${d.settings.folder.startsWith("@") ? ": is it still mounted?" : "."} Choose another.`
          : "Pick the folder new music lands in (downloads, rips). Codetta finds each album and files it into your music folder with your folder pattern."),
        inboxSettingsFields(d.settings, root.folders, d.external),
        h("div", { class: "inbox-settings-actions" },
          d.settings.folder && d.folder_exists ? h("button", { class: "btn", type: "button", onclick: () => { inboxState.settingsOpen = false; renderInbox(); } }, "Cancel") : null,
          h("button", { class: "btn primary", type: "submit", disabled: !d.settings.folder }, "Save")));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          inboxState.data = await api("PUT", "/api/inbox/settings", readInboxFields(form));
          inboxState.settingsOpen = false;
          renderInbox();
          if (inboxState.data.running) inboxState.timer = setTimeout(loadInbox, 1500);
        } catch (err) { toast(err.message, "error"); }
      });
      setKids(body, form);
      setKids($("#inbox-foot"), h("span", { class: "spacer" }), h("button", { class: "btn", type: "button", "data-close": true }, "Close"));
    });
    return;
  }
  const ready = d.groups.filter((g) => g.status === "ready");
  const pending = inboxPending(d);
  const item = (g) => {
    const name = g.title || g.key.split("/").pop();
    const actions = [];
    const btn = (label, onclick, primary = false) => h("button", { class: `btn small${primary ? " primary" : ""}`, type: "button", onclick }, label);
    const accept = () => inboxAction("/api/inbox/accept", { key: g.key }, (res) =>
      toast(res.status === "filed" ? `Filed in ${res.moved_to || "your library"}` : res.note, res.status === "filed" ? "success" : "error"));
    if (g.status === "ready") actions.push(btn("File", accept, true), btn("Review", () => reviewInboxGroup(g)));
    else if (g.status === "review") actions.push(btn("Review", () => reviewInboxGroup(g), true), btn("Use this match", accept));
    else if (g.status === "nomatch") actions.push(btn("Search", () => reviewInboxGroup(g), true), btn("Keep its own tags", accept));
    else if (g.status === "local") actions.push(btn("File", accept, true));
    else if (g.status === "error") actions.push(btn("Try again", () => inboxAction("/api/inbox/rematch", { key: g.key })), d.online ? btn("Review", () => reviewInboxGroup(g)) : null);
    else if (g.status === "skipped") actions.push(btn("Look again", () => inboxAction("/api/inbox/rematch", { key: g.key })));
    else if (g.status === "filed" && g.dest) actions.push(btn("Open", () => { closeDialog($("#inbox-dialog")); navigate(g.dest); }));
    if (g.status === "filed") {
      actions.push(h("button", { class: "link-btn inbox-skip", type: "button", title: "Take it off this list (the album stays in your library)",
        onclick: () => inboxAction("/api/inbox/dismiss", { key: g.key }) }, "Dismiss"));
    }
    if (["ready", "review", "nomatch", "local", "error"].includes(g.status)) {
      actions.push(h("button", { class: "link-btn inbox-skip", type: "button", onclick: () => inboxAction("/api/inbox/skip", { key: g.key }) }, "Skip"));
    }
    if (g.status !== "filed" && g.status !== "matching") {
      actions.push(h("button", { class: "link-btn inbox-skip danger-text", type: "button", onclick: async () => {
        if (await ask({ title: `Remove “${name}” from the inbox?`, danger: true, confirmLabel: "Move to Recently deleted",
          message: g.files === 1 ? "Its 1 file goes to Recently deleted for 30 days. Activity can put it back."
            : `Its ${plural(g.files, "file")} go to Recently deleted for 30 days. Activity can put them back.` })) {
          inboxAction("/api/inbox/remove", { key: g.key }, () => toast(`Removed “${name}”. Undo is in Activity.`, "success"));
        }
      } }, "Remove"));
    }
    const rel = g.release;
    // The release's cover, or (still in the inbox) the one in the files themselves.
    const own = g.status !== "filed" && g.paths?.length ? `/api/art?path=${encodeURIComponent(g.paths[0])}` : null;
    return h("div", { class: `inbox-item ${g.status}` },
      rel?.id && d.online ? mbThumb(rel.id, 250, own) : mbThumb(null, 250, own),
      h("div", { class: "inbox-main" },
        h("div", { class: "inbox-title", dir: "auto" }, name, g.artist ? h("span", { class: "inbox-artist" }, ` · ${g.artist}`) : null),
        h("div", { class: "mb-cand-meta" }, [rel ? mbMeta(rel) : "", `${plural(g.files, "file")} in ${inboxLabel(g.key)}`].filter(Boolean).join(" · ")),
        h("div", { class: "inbox-status" },
          h("span", { class: `inbox-chip ${g.status}` }, INBOX_LABELS[g.status] || g.status, g.score != null && g.status !== "filed" ? ` · ${g.score}%` : ""),
          g.note && !g.transfer ? h("span", { class: "inbox-note" }, g.note) : null,
          g.owned ? h("button", { class: "inbox-chip owned", type: "button", title: `Open ${g.owned.folder}`,
            onclick: () => { closeDialog($("#inbox-dialog")); navigate(g.owned.folder); } },
          `Already in your library (${plural(g.owned.tracks, "track")})`) : null),
        g.transfer ? progressBar(g.transfer.progress, [
          `${g.transfer.finished} of ${plural(g.transfer.files, "file")}`, etaText(g.transfer.eta)].filter(Boolean).join(" · ")) : null),
      h("div", { class: "inbox-actions" }, actions));
  };
  // One entry that can't be drawn must never hide the rest of the inbox (#4): show it plainly instead.
  const safeItem = (g) => {
    try { return item(g); } catch (err) {
      console.error("Inbox: couldn't show", g.key, err);
      return h("div", { class: `inbox-item ${g.status}` }, h("div", { class: "inbox-main" },
        h("div", { class: "inbox-title", dir: "auto" }, g.title || inboxLabel(g.key)),
        h("div", { class: "mb-cand-meta" }, `${plural(g.files, "file")} in ${inboxLabel(g.key)}`)));
    }
  };
  setKids(body,
    h("div", { class: "inbox-head" },
      h("p", { class: "mb-lead" }, d.groups.length
        ? `${pending ? inboxWaitingText(d) + " waiting" : "All caught up"} in ${inboxLabel(d.settings.folder)}.${d.downloading ? ` ${plural(d.downloading, "album")} still arriving: Codetta waits until the download finishes.` : ""}${d.settings.auto ? " Confident matches are filed automatically." : ""}`
        : `Nothing new in ${inboxLabel(d.settings.folder)}. When an album lands there, it shows up here.`),
      h("div", { class: "inbox-tools" },
        h("button", { class: "btn small with-icon", type: "button", onclick: pickImport }, icon("upload"), "Import"),
        skReady() ? h("button", { class: "btn small with-icon", type: "button", onclick: () => { closeDialog($("#inbox-dialog")); openSoulseek(); } },
          icon("slskd"), "Soulseek") : null,
        h("button", { class: "btn small with-icon", type: "button", onclick: () => { closeDialog($("#inbox-dialog")); openSettings("inbox"); } },
          icon("gear"), "Settings"))),
    d.groups.length ? h("div", { class: "inbox-list" }, d.groups.flatMap((g, i) => {
      const filed = d.groups.filter((x) => x.status === "filed");
      // Filed albums come last: a small heading before the first, with Dismiss all.
      const first = g.status === "filed" && (i === 0 || d.groups[i - 1].status !== "filed");
      return first ? [h("div", { class: "inbox-filed-head" }, h("span", {}, `Filed (${filed.length})`),
        filed.length > 1 ? h("button", { class: "link-btn", type: "button",
          onclick: () => inboxAction("/api/inbox/dismiss-all", {}, () => toast(`Dismissed ${plural(filed.length, "filed album")}`, "success")) }, "Dismiss all") : null),
        safeItem(g)] : [safeItem(g)];
    })) : null);
  setKids($("#inbox-foot"),
    h("button", { class: "btn", type: "button", onclick: loadInbox }, "Check again"),
    h("span", { class: "spacer" }),
    ready.length ? h("button", { class: "btn primary", type: "button", onclick: () => inboxAction("/api/inbox/accept-ready", {}, (res) =>
      toast(res.filed >= res.total ? `Filed ${plural(res.filed, "album")}`
        : res.total - res.filed === 1 ? `Filed ${plural(res.filed, "album")} (1 needs a look)`
        : `Filed ${plural(res.filed, "album")} (${res.total - res.filed} need a look)`, "success")) },
      `File ${plural(ready.length, "confident match", "confident matches")}`) : h("button", { class: "btn", type: "button", "data-close": true }, "Close"));
}

// ---- Soulseek through slskd ---------------------------------------------------------------------------
//
// "!slskd" in the search bar turns into a chip; Enter then asks the user's own slskd.
// Codetta downloads the best copy into the inbox, and the Soulseek sheet asks
// whether to keep it (or blocklist it and try the next one).

export const sk = { data: null, timer: null, focus: null, picking: null };
export const SK_LABELS = {
  searching: "Searching", choosing: "Pick a source", downloading: "Downloading", fetched: "Downloaded", arrived: "Matching", imported: "Imported",
  nothing: "Nothing found", failed: "Couldn't get it", cancelled: "Cancelled",
};
export const SK_ACTIVE = ["searching", "choosing", "downloading", "fetched"];
export const skReady = () => connectionOn("slskd") && !!sk.data?.configured;
/** "about 3 min left" from seconds (null: not known yet). */
export const etaText = (s) => (s == null ? "" : s < 60 ? "less than a minute left" : s < 3600 ? `about ${Math.round(s / 60)} min left`
  : `about ${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min left`);

/** A thin download bar with "62% · about 3 min left" under it. */
export function progressBar(fraction, extra = "") {
  const pct = Math.round(fraction * 100);
  const bar = h("div", { class: "sk-progress", role: "progressbar", "aria-label": "Download progress",
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct) }, h("span", {}));
  bar.firstChild.style.width = `${Math.max(2, pct)}%`;
  return h("div", { class: "dl-progress" }, bar, h("span", { class: "dl-progress-text" }, [`${pct}%`, extra].filter(Boolean).join(" · ")));
}

export const skSize = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(b / 1e6))} MB`);

export async function loadSlskd() {
  try { sk.data = await api("GET", "/api/slskd"); } catch { sk.data = null; }
  return sk.data;
}
