// The activity log and undo.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, h, icon } from "./dom.js";
import { api } from "./api.js";
import { plural, state, toast } from "./state.js";
import { folderCache, loadFolder } from "./browse.js";
import { folderCovers } from "./tools.js";
import { isDirty } from "./editor.js";

// ---- Activity log ---------------------------------------------------------------------------------------

export const activity = { entries: [], lastId: 0, timer: null, open: null };

function activityOpenPref() {
  try {
    const v = localStorage.getItem("codetta-activity-open");
    if (v !== null) return v === "1";
  } catch { /* ignore */ }
  return !window.matchMedia("(max-width: 760px)").matches; // open on desktop, closed on phones
}

export async function refreshActivity() {
  try {
    const sinceId = activity.lastId;
    let fresh = await api("GET", `/api/activity?limit=50&after_id=${sinceId}`);
    fresh = fresh.filter((e) => e.id > activity.lastId); // another refresh may have got these already
    if (sinceId > 0 && fresh.some((e) => e.undoes != null)) { await reloadActivity(); return; }
    if (!fresh.length && activity.entries.length) return;
    const isFirstLoad = activity.lastId === 0 && !activity.entries.length;
    activity.entries = [...fresh, ...activity.entries].slice(0, 50);
    if (fresh.length) activity.lastId = Math.max(activity.lastId, fresh[0].id);
    renderActivity(isFirstLoad ? new Set() : new Set(fresh.map((e) => e.id)));
  } catch { /* offline for a moment: try again on the next tick */ }
}

function fmtTime(iso) {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function renderActivity(newIds = new Set()) {
  if (activity.open === null) activity.open = activityOpenPref();
  const list = $("#activity-list");
  const toggle = $("#activity-toggle");
  toggle.setAttribute("aria-expanded", String(activity.open));
  list.hidden = !activity.open;
  $("#activity").classList.toggle("open", activity.open);

  const latest = activity.entries[0];
  $("#activity-dot").className = `activity-dot ${latest ? (latest.ok ? "ok" : "err") : ""}`;
  $("#activity-latest").textContent = activity.open ? "Activity" : latest ? latest.message : "Activity";
  $("#activity-latest-time").textContent = !activity.open && latest ? fmtTime(latest.time) : "";

  const editing = new Set(state.editor?.paths || []);
  if (!activity.entries.length) {
    list.replaceChildren(h("li", { class: "act-empty" }, "Changes you make will show up here."));
    return;
  }
  list.replaceChildren(...activity.entries.map((e) => {
    const related = e.files.some((f) => editing.has(f));
    return h("li", { class: `act ${e.ok ? "ok" : "err"}${related ? " related" : ""}${newIds.has(e.id) ? " new" : ""}${e.undone ? " undone" : ""}` },
      h("span", { class: "act-icon", role: "img", "aria-label": e.ok ? "Succeeded" : "Failed" }, icon(e.ok ? "check" : "alert")),
      h("div", { class: "act-main" },
        h("div", { class: "act-msg" }, e.message),
        e.changes.slice(0, 6).map((c) => h("div", { class: "act-change" },
          h("span", { class: "act-key" }, c.key),
          c.old && c.old !== c.new ? [h("span", { class: "act-old" }, c.old), " → "] : null,
          c.new ? h("span", { class: "act-new" }, c.new) : h("span", { class: "act-removed" }, "removed"))),
        e.changes.length > 6 ? h("div", { class: "act-change" }, `+${e.changes.length - 6} more`) : null,
        e.errors.slice(0, 3).map((x) => h("div", { class: "act-err" }, `${x.path.split("/").pop()}: ${x.error}`)),
        e.can_undo || e.undone ? h("div", { class: "act-actions" },
          e.can_undo
            ? h("button", { class: "link-btn act-undo", type: "button", onclick: () => undoEntry(e) },
                icon("undo"), e.kind === "undo" && !e.redo ? "Redo" : "Undo")
            : h("span", { class: "act-undone" }, "Undone")) : null),
      h("time", { datetime: e.time }, fmtTime(e.time)));
  }));
}

async function reloadActivity() {
  activity.entries = [];
  activity.lastId = 0;
  await refreshActivity();
}

async function undoEntry(e) {
  const verb = e.kind === "undo" && !e.redo ? "Redo" : "Undo";
  if (e.file_count > 1 && !(await ask({
    title: `${verb} this change?`,
    message: `“${e.message}” touched ${e.file_count} files. Files that were changed again since are left as they are.`,
    confirmLabel: `${verb} ${e.file_count} files`,
  }))) return;
  if (isDirty() && !(await ask({
    title: "Refresh the editor?",
    message: "This updates files you're editing, so their fields will reload. Your unsaved edits are kept.",
    confirmLabel: "Continue",
  }))) return;
  try {
    const res = await api("POST", `/api/activity/${e.id}/undo`);
    if (!res.undone) {
      toast(res.results.find((r) => r.error)?.error || "Nothing could be undone", "error");
    } else if (res.skipped || res.failed) {
      const left = res.skipped + res.failed;
      toast(res.message + ". " + (left === 1 ? "1 file left as it is (changed since or unreadable)."
        : `${plural(left, "file")} left as they are (changed since or unreadable).`));
    } else {
      toast(res.message, "success");
    }
  } catch (err) {
    toast(err.message, "error");
  }
  await reloadActivity();
  folderCache.clear(); folderCovers.clear(); // other folders may hold stale tags now
  await loadFolder(state.path, { keepScroll: true });
}

export function startActivityPolling() {
  clearInterval(activity.timer);
  // Picks up changes made from other devices too. Paused while the tab is hidden.
  activity.timer = setInterval(() => {
    if (document.visibilityState === "visible" && state.editor && $("#auth").hidden) refreshActivity();
  }, 4000);
}
