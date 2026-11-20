// Talking to Codetta's JSON API.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { playOut, replay } from "./dom.js";
import { showAuth } from "./account.js";

// ---- API -----------------------------------------------------------------------------

// A thin line under the top bar while Codetta waits on the server for something you did
// (only after 200 ms, so quick answers never flicker). Background polls don't count.
const net = { pending: 0, timer: null };
const QUIET = /^\/api\/(notifications|activity|update|library-health\/summary|slskd$|inbox$|health$)/;
function netBusy(delta) {
  net.pending = Math.max(0, net.pending + delta);
  const bar = document.getElementById("net-bar");
  if (!bar) return;
  if (net.pending && !net.timer && bar.hidden) {
    net.timer = setTimeout(() => { net.timer = null; if (net.pending) { bar.hidden = false; replay(bar, "net-in"); } }, 200);
  } else if (!net.pending) {
    clearTimeout(net.timer);
    net.timer = null;
    if (!bar.hidden) playOut(bar, "net-out", () => { bar.hidden = true; });
  }
}

export async function api(method, url, body) {
  const quiet = method === "GET" && QUIET.test(url.split("?")[0]);
  if (!quiet) netBusy(1);
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Can't reach the Codetta server. Check your connection and try again.");
  } finally {
    if (!quiet) netBusy(-1);
  }
  if (res.status === 401 && !url.startsWith("/api/auth/")) {
    showAuth("login", "Your session ended. Sign in again to carry on where you left off.");
    throw new Error("Sign in required");
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const d = data && data.detail;
    const msg = typeof d === "string" ? d
      : Array.isArray(d) ? d.map((e) => e.msg).join("; ")
      : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}
