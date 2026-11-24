// Notifications (the bell) and the status banner.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, h, icon, playOut, replay, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, state, toast } from "./state.js";
import { navigate } from "./browse.js";
import { openSoulseek } from "./search.js";
import { isPhone } from "./tools.js";
import { openNews } from "./setup.js";
import { openInbox } from "./inbox.js";
import { openSettings } from "./settings.js";

// ---- Notifications: the bell -------------------------------------------------------------------------
//
// Background news (the inbox finished, an album filed itself, an update is out).
// New ones pop out of the bell for a few seconds; the panel keeps the list.

const notif = { lastId: null, items: [], unread: 0, timer: null };
const notifIcon = (kind) => icon(kind === "inbox" ? "inbox" : kind === "update" ? "spark" : kind === "soulseek" ? "slskd" : kind === "warning" ? "alert" : "check");

const relTime = (secs) => {
  const d = Math.max(0, Date.now() / 1000 - secs);
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return new Date(secs * 1000).toLocaleDateString([], { day: "numeric", month: "short" });
};

export async function pollNotifications() {
  clearTimeout(notif.timer);
  try {
    // Pop what this browser hasn't shown yet (also what happened while you were away), at most 3.
    if (notif.lastId === null) {
      try { notif.lastId = Number(localStorage.getItem("codetta-notif-seen")) || 0; } catch { notif.lastId = 0; }
    }
    const res = await api("GET", `/api/notifications?after_id=${notif.lastId}`);
    for (const n of res.items.filter((x) => !x.read).slice(0, 3).reverse()) popNotification(n);
    notif.lastId = res.last_id;
    try { localStorage.setItem("codetta-notif-seen", String(res.last_id)); } catch { /* private mode */ }
    notif.unread = res.unread;
    renderNotifBadge();
    if (!$("#notif-panel").hidden) openNotifications(true);
  } catch { /* offline or signed out: try again later */ }
  if (!document.hidden) notif.timer = setTimeout(pollNotifications, 20000);
}

function renderNotifBadge() {
  $("#notif-count").hidden = !notif.unread;
  $("#notif-count").textContent = notif.unread > 99 ? "99+" : String(notif.unread);
}

function runNotifAction(n) {
  closeNotifications();
  const a = n.action || {};
  if (a.open === "inbox") openInbox();
  else if (a.open === "soulseek") openSoulseek(a.job || null);
  else if (a.open === "about" || a.open === "account") openSettings("about");
  else if (a.open === "news") openNews();
  else if (a.open === "folder" && a.path != null) navigate(a.path);
  api("POST", "/api/notifications/read", { ids: [n.id] }).then((res) => { notif.unread = res.unread; renderNotifBadge(); }).catch(() => {});
}

/** Position the panel and pop-ups under the bell, their corner pointing at it. */
function placeUnderBell(el) {
  const r = $("#notif-btn").getBoundingClientRect();
  // Line its right edge up with the bell, but never past the screen's left edge
  // (on phones the bell sits in from the edge, so the panel slides right).
  const gutter = 12;
  const width = Math.min(isPhone() ? 360 : 380, window.innerWidth - 2 * gutter); // as in app.css
  const right = Math.max(gutter, Math.min(window.innerWidth - r.right - 8, window.innerWidth - width - gutter));
  el.style.top = `${r.bottom + 8}px`;
  el.style.right = `${right}px`;
  el.style.setProperty("--origin-x", `${Math.max(16, window.innerWidth - right - (r.left + r.width / 2))}px`);
}

function popNotification(n) {
  const box = $("#notif-pops");
  placeUnderBell(box);
  const card = h("button", { class: `notif-pop ${n.kind}`, type: "button", onclick: () => { card.remove(); runNotifAction(n); } },
    h("span", { class: "notif-icon" }, notifIcon(n.kind)),
    h("span", { class: "notif-text" }, h("strong", {}, n.title), n.body ? h("span", {}, n.body) : null));
  box.prepend(card);
  while (box.children.length > 3) box.lastChild.remove();
  replay($("#notif-btn"), "ring");
  setTimeout(() => playOut(card, "notif-out", () => card.remove()), 7000);
}

export function openNotifications(refreshOnly = false) {
  const panel = $("#notif-panel");
  if (!refreshOnly) $("#notif-pops").replaceChildren(); // the panel has them all
  api("GET", "/api/notifications").then((res) => {
    notif.items = res.items;
    notif.unread = res.unread;
    renderNotifBadge();
    const list = res.items.length
      ? h("ul", { class: "notif-list" }, res.items.map((n) => h("li", {},
        h("button", { class: `notif-item${n.read ? "" : " unread"}`, type: "button", onclick: () => runNotifAction(n) },
          h("span", { class: "notif-icon" }, notifIcon(n.kind)),
          h("span", { class: "notif-text" }, h("strong", {}, n.title), n.body ? h("span", {}, n.body) : null,
            h("time", {}, relTime(n.time)))))))
      : h("p", { class: "notif-empty" }, "Nothing yet. Codetta tells you here when the inbox finishes, an album files itself, or an update is out.");
    setKids(panel,
      h("div", { class: "notif-head" },
        h("strong", {}, "Notifications"),
        res.items.length ? h("span", { class: "notif-tools" },
          res.unread ? h("button", { class: "link-btn", type: "button", onclick: async () => {
            const r = await api("POST", "/api/notifications/read", {}); notif.unread = r.unread; renderNotifBadge(); openNotifications(true);
          } }, "Mark all read") : null,
          h("button", { class: "link-btn", type: "button", onclick: async () => {
            await api("DELETE", "/api/notifications"); notif.unread = 0; renderNotifBadge(); openNotifications(true);
          } }, "Clear")) : null),
      list);
    if (!refreshOnly && panel.hidden) {
      placeUnderBell(panel);
      panel.hidden = false;
      replay(panel, "notif-in");
      $("#notif-btn").setAttribute("aria-expanded", "true");
    }
  }).catch((err) => toast(err.message, "error"));
}

export function closeNotifications() {
  const panel = $("#notif-panel");
  if (panel.hidden) return;
  $("#notif-btn").setAttribute("aria-expanded", "false");
  playOut(panel, "notif-out", () => { panel.hidden = true; });
}

// ---- Status banner -------------------------------------------------------------------------------------------

export function showStatus(status) {
  state.status = status;
  if (!status.music_dir_found) {
    els.banner.replaceChildren(
      h("strong", {}, "Music folder not found"),
      "Codetta is looking for your music at ", h("code", {}, status.music_dir), ". ",
      "Set ", h("code", {}, "CODETTA_MUSIC_DIR"), " to your library, or mount it at ", h("code", {}, "/music"), " in Docker.");
    els.banner.hidden = false;
  } else if (!status.music_dir_writable) {
    els.banner.replaceChildren(
      h("strong", {}, "Read-only library"),
      "Codetta can read your music but can't save changes. Check the folder's permissions (or remove ", h("code", {}, ":ro"), " from the Docker volume).");
    els.banner.hidden = false;
  }
}
