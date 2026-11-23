// The player: a quick listen, the now-playing pill and the full player.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, closeDialog, h, icon, openDialog, playOut, reducedMotion, replay, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, first, fmtDuration, state, toast } from "./state.js";
import { discInfo, navigate, visibleTracks } from "./browse.js";
import { artUrlFor, openEditor } from "./editor.js";
import { artistButton } from "./artists.js";

// ---- Player: a quick listen, straight from the file -------------------------------------------
//
// One shared <audio>, streaming /api/stream (the server sends the file as-is
// and supports seeking). Formats the browser can't decode get no button.

const STREAM_TYPES = {
  flac: "audio/flac", mp3: "audio/mpeg", mp2: "audio/mpeg", m4a: "audio/mp4", wav: "audio/wav", aiff: "audio/aiff",
  ogg: 'audio/ogg; codecs="vorbis"', opus: 'audio/ogg; codecs="opus"', oggflac: 'audio/ogg; codecs="flac"',
};
const playable = new Map();
export function canPlay(format) {
  if (!playable.has(format)) {
    const type = STREAM_TYPES[format];
    playable.set(format, !!type && document.createElement("audio").canPlayType(type) !== "");
  }
  return playable.get(format);
}

const player = {
  audio: null, path: null, folder: null, folderName: "", track: null, seeking: false,
  queue: [], order: [], pos: -1, // what plays (folder order), the play order (shuffled or not), where we are in it
  shuffle: (() => { try { return localStorage.getItem("codetta-shuffle") === "1"; } catch { return false; } })(),
  // Autoplay: when the queue runs out, similar songs from the library keep playing (on unless switched off).
  autoplay: (() => { try { return localStorage.getItem("codetta-autoplay") !== "0"; } catch { return true; } })(),
  played: [], // paths played this visit, oldest first: Autoplay's seeds, and what it won't repeat
  extending: null, // the Autoplay request on its way
  because: "", source: "", // what the latest Autoplay songs are like, and who picked them
};
const shuffled = (list) => { const a = [...list]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

/** Play ``t`` with the rest of what's on screen queued after it (shuffled, if shuffle is on). */
function buildQueue(t) {
  const list = visibleTracks().filter((x) => !x.error && canPlay(x.format));
  player.queue = list.includes(t) ? list : [t];
  const start = player.queue.indexOf(t);
  const rest = player.queue.map((_, i) => i).filter((i) => i !== start);
  player.order = player.shuffle ? [start, ...shuffled(rest)] : player.queue.map((_, i) => i);
  player.pos = player.shuffle ? 0 : start;
  player.folder = state.path;
  player.folderName = state.folder?.name || "";
}

function playPos(pos) {
  if (pos < 0 || pos >= player.order.length) return;
  player.pos = pos;
  startTrack(player.queue[player.order[pos]]);
}

async function playNext() {
  if (player.pos + 1 < player.order.length) { playPos(player.pos + 1); return; }
  if (player.autoplay && await extendQueue()) { playPos(player.pos + 1); return; }
  stopPlayer(); // the end of the queue
}

const canGoOn = () => player.pos + 1 < player.order.length || (player.autoplay && !!player.track);

/** Autoplay: add similar songs from the library to the end of the queue. True if any came. */
function extendQueue() {
  if (player.extending) return player.extending;
  const queued = new Set(player.queue.map((x) => x.path));
  const body = { seeds: player.played.slice(-3), avoid: [...new Set([...player.played, ...queued])].slice(-2000), n: 10 };
  player.extending = api("POST", "/api/autoplay/next", body).then((d) => {
    const fresh = (d.tracks || []).filter((x) => !x.error && canPlay(x.format) && !queued.has(x.path));
    for (const x of fresh) {
      x.auto = true;
      player.queue.push(x);
      player.order.push(player.queue.length - 1);
    }
    if (fresh.length) { player.because = d.because || ""; player.source = d.source_name || ""; }
    return fresh.length > 0;
  }).catch(() => false).finally(() => {
    player.extending = null;
    renderPlayerSheet();
    npRender(!!(player.audio && !player.audio.paused));
  });
  return player.extending;
}

function setAutoplay(on) {
  player.autoplay = on;
  try { localStorage.setItem("codetta-autoplay", on ? "1" : "0"); } catch { /* private mode */ }
  if (!on) { // drop the Autoplay songs that haven't played yet
    const keep = player.order.filter((qi, k) => k <= player.pos || !player.queue[qi].auto);
    player.order = keep;
  } else if (player.track && player.pos + 1 >= player.order.length) {
    extendQueue();
  }
  renderPlayerSheet();
  npRender(!!(player.audio && !player.audio.paused));
  toast(on ? "Autoplay is on: similar songs keep playing when the queue ends." : "Autoplay is off: playback stops at the end of the queue.");
}

function playPrev() {
  const a = player.audio;
  if (a && a.currentTime > 3) { a.currentTime = 0; return; } // like every player: first back to the start
  if (player.pos > 0) playPos(player.pos - 1);
  else if (a) a.currentTime = 0;
}

function setShuffle(on) {
  player.shuffle = on;
  try { localStorage.setItem("codetta-shuffle", on ? "1" : "0"); } catch { /* private mode */ }
  if (player.pos >= 0) {
    const current = player.order[player.pos];
    const rest = player.queue.map((_, i) => i).filter((i) => i !== current);
    player.order = on ? [current, ...shuffled(rest)] : player.queue.map((_, i) => i);
    player.pos = on ? 0 : current;
  }
  renderPlayerSheet();
  npRender(!!(player.audio && !player.audio.paused));
}

function removeFromQueue(pos) {
  if (pos === player.pos || pos < 0 || pos >= player.order.length) return;
  player.order.splice(pos, 1);
  if (pos < player.pos) player.pos -= 1;
  renderPlayerSheet();
}

function playerAudio() {
  if (player.audio) return player.audio;
  const a = new Audio();
  a.preload = "none";
  for (const ev of ["play", "pause", "ended", "emptied"]) a.addEventListener(ev, syncPlayer);
  a.addEventListener("timeupdate", npProgress);
  a.addEventListener("loadedmetadata", npProgress);
  a.addEventListener("ended", playNext);
  a.addEventListener("error", () => {
    if (!player.path) return;
    toast("This browser can't play that file.", "error");
    stopPlayer();
  });
  player.audio = a;
  return a;
}

export async function togglePlay(t) {
  const a = playerAudio();
  if (player.path === t.path) {
    if (a.paused) a.play().catch(() => {}); else a.pause();
    return;
  }
  buildQueue(t);
  await startTrack(t);
}

async function startTrack(t) {
  const a = playerAudio();
  player.path = t.path;
  player.track = t;
  if (player.played.at(-1) !== t.path) player.played.push(t.path);
  if (player.played.length > 2000) player.played.splice(0, player.played.length - 2000);
  lyr.path = null; // fetched again for the new track when shown
  a.src = `/api/stream?path=${encodeURIComponent(t.path)}`;
  if ("mediaSession" in navigator) { // lock screen / headphone controls
    navigator.mediaSession.metadata = new MediaMetadata({
      title: first(t, "title") || t.name, artist: (t.tags.artist || []).join(", "), album: first(t, "album"),
      artwork: t.art ? [{ src: artUrlFor(t), sizes: "512x512" }] : [],
    });
    navigator.mediaSession.setActionHandler("play", () => a.play());
    navigator.mediaSession.setActionHandler("pause", () => a.pause());
    navigator.mediaSession.setActionHandler("seekto", (d) => { if (d.seekTime != null) a.currentTime = d.seekTime; });
    try {
      navigator.mediaSession.setActionHandler("nexttrack", canGoOn() ? playNext : null);
      navigator.mediaSession.setActionHandler("previoustrack", playPrev);
    } catch { /* older browsers */ }
  }
  if (player.autoplay && player.pos + 1 >= player.order.length) extendQueue(); // ready before this one ends
  try {
    await a.play();
  } catch (err) {
    if (err.name !== "AbortError") { toast("This browser can't play that file.", "error"); stopPlayer(); }
  }
  syncPlayer();
}

function stopPlayer() {
  if (!player.audio) return;
  player.audio.pause();
  player.audio.removeAttribute("src");
  player.audio.load();
  player.path = null;
  player.track = null;
  player.queue = []; player.order = []; player.pos = -1;
  if ($("#player-dialog").open) closeDialog($("#player-dialog"));
  syncPlayer();
}

/** Reflect what's playing on the rows (button, progress line, spinning disc). */
export function syncPlayer() {
  const playing = player.audio && !player.audio.paused && !player.audio.ended;
  let disc = null;
  for (const [path, { row, track }] of state.rows) {
    const current = path === player.path;
    row.classList.toggle("is-current", current);
    row.classList.toggle("playing", current && !!playing);
    if (current) disc = discInfo()?.discOf(track) ?? null;
    const btn = $(".play-btn", row);
    if (!btn) continue;
    const on = current && playing;
    btn.replaceChildren(icon(on ? "pause" : "play"), h("span", { class: "play-label" }, on ? "Pause" : "Play"));
    btn.setAttribute("aria-label", `${on ? "Pause" : "Play"} ${first(track, "title") || track.name}`);
  }
  for (const head of els.tracks.querySelectorAll(".disc-head")) {
    head.classList.toggle("spinning", !!playing && head.dataset.disc === String(disc) && player.folder === state.path);
  }
  npRender(!!playing);
  renderPlayerSheet();
}

// ---- Now playing: a pill that grows out of a circle at the bottom centre ----------------------------

const np = { built: false, els: {} };

function npBuild() {
  if (np.built) return;
  const box = $("#now-playing");
  const e = np.els;
  e.art = h("span", { class: "np-art", "aria-hidden": "true" });
  e.title = h("span", { class: "np-title", dir: "auto" });
  e.artist = h("span", { class: "np-artist", dir: "auto" });
  e.info = h("button", { class: "np-info", type: "button", title: "Open the player (queue, lyrics)", onclick: openPlayerSheet }, e.title, e.artist);
  e.time = h("span", { class: "np-time" });
  e.play = h("button", { class: "np-play", type: "button", onclick: () => player.track && togglePlay(player.track) });
  e.close = h("button", { class: "np-close", type: "button", "aria-label": "Stop", title: "Stop", onclick: stopPlayer }, icon("close"));
  e.next = h("button", { class: "np-next", type: "button", "aria-label": "Next track", title: "Next", onclick: playNext }, icon("next"));
  e.art.addEventListener("click", openPlayerSheet);
  e.seek = h("input", { class: "np-seek", type: "range", min: "0", max: "1000", value: "0", step: "1", "aria-label": "Position in the track" });
  e.seek.addEventListener("input", () => {
    player.seeking = true;
    const a = player.audio;
    if (a?.duration) e.time.textContent = `${fmtDuration((e.seek.value / 1000) * a.duration)} / ${fmtDuration(a.duration)}`;
  });
  e.seek.addEventListener("change", () => {
    const a = player.audio;
    if (a?.duration) a.currentTime = (e.seek.value / 1000) * a.duration;
    player.seeking = false;
  });
  box.replaceChildren(h("div", { class: "np-inner" }, e.art, e.info, e.time, e.play, e.next, e.close), e.seek);
  box.setAttribute("role", "region");
  box.setAttribute("aria-label", "Now playing");
  np.built = true;
}

function npRender(playing) {
  const box = $("#now-playing");
  const t = player.track;
  if (!t) {
    if (!box.hidden && !box.classList.contains("np-leave")) playOut(box, "np-leave", () => { box.hidden = true; });
    return;
  }
  npBuild();
  const e = np.els;
  e.title.textContent = first(t, "title") || t.name;
  e.artist.textContent = (t.tags.artist || []).join(", ") || first(t, "album");
  setKids(e.art, t.art ? h("img", { src: artUrlFor(t), alt: "" }) : icon("note"));
  setKids(e.play, icon(playing ? "pause" : "play"));
  e.play.setAttribute("aria-label", playing ? "Pause" : "Play");
  e.next.disabled = !canGoOn();
  box.classList.toggle("is-playing", playing);
  if (box.hidden) {
    box.classList.remove("np-leave");
    box.hidden = false;
    replay(box, "np-enter");
  }
  npProgress();
}

function npProgress() {
  const a = player.audio;
  psProgress();
  if (!np.built || !a || player.seeking) return;
  const d = a.duration;
  np.els.seek.value = d ? String(Math.round((a.currentTime / d) * 1000)) : "0";
  np.els.seek.style.setProperty("--pos", d ? `${(a.currentTime / d) * 100}%` : "0%");
  np.els.time.textContent = d ? `${fmtDuration(a.currentTime)} / ${fmtDuration(d)}` : "";
}

// ---- The full player: big cover, controls, Up next and (synced) lyrics -------------------------------

const ps = { tab: "queue", els: null };
const lyr = { path: null, data: null, lines: [], current: -1, userScroll: 0 };

/** "[01:23.45] line" (several stamps per line allowed; [offset:+250] honoured) -> sorted [{t, text}]. */
function parseLrc(text) {
  let offset = 0;
  const out = [];
  for (const raw of text.split(/\r?\n/)) {
    const off = /^\[offset:\s*([+-]?\d+)\]/i.exec(raw);
    if (off) { offset = Number(off[1]) / 1000; continue; }
    const stamps = [...raw.matchAll(/\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]/g)];
    if (!stamps.length) continue;
    const words = raw.replace(/\[[^\]]*\]/g, "").trim();
    for (const m of stamps) {
      const t = Number(m[1]) * 60 + Number(m[2]) + (m[3] ? Number(`0.${m[3]}`) : 0) - offset;
      out.push({ t: Math.max(0, t), text: words });
    }
  }
  return out.sort((a, b) => a.t - b.t);
}

async function loadLyrics() {
  const t = player.track;
  if (!t || lyr.path === t.path) return;
  lyr.path = t.path; lyr.data = null; lyr.lines = []; lyr.current = -1;
  renderLyrics();
  try {
    const d = await api("GET", `/api/lyrics?path=${encodeURIComponent(t.path)}`);
    if (lyr.path !== t.path) return; // the track changed meanwhile
    lyr.data = d;
    lyr.lines = d.synced ? parseLrc(d.lyrics) : [];
  } catch { lyr.data = { lyrics: "", synced: false, error: true }; }
  renderLyrics();
}

function renderLyrics() {
  if (!ps.els) return;
  const box = ps.els.lyrics;
  const d = lyr.data;
  if (!d) { setKids(box, h("p", { class: "ps-empty" }, h("span", { class: "spinner", "aria-hidden": "true" }), " Loading lyrics…")); return; }
  if (!d.lyrics) {
    setKids(box, h("p", { class: "ps-empty" }, d.error ? "Couldn't load the lyrics." : "No lyrics for this track yet. Add them in the editor (Find lyrics can look them up)."));
    return;
  }
  if (!lyr.lines.length) { setKids(box, h("div", { class: "ps-plain", dir: "auto" }, d.lyrics.replace(/\[[a-z]+:[^\]]*\]\s*/gi, ""))); return; }
  setKids(box, h("ol", { class: "ps-lines" }, lyr.lines.map((l, i) => h("li", {
    class: "ps-line", dataset: { i: String(i) }, dir: "auto",
    onclick: () => { if (player.audio) player.audio.currentTime = l.t + 0.01; },
  }, l.text || "\u266a"))));
  lyr.current = -1;
  psLyricsTick();
}

/** Highlight the line being sung and keep it in view (unless you've just scrolled yourself). */
function psLyricsTick() {
  if (!ps.els || !lyr.lines.length || !player.audio) return;
  const t = player.audio.currentTime;
  let lo = 0, hi = lyr.lines.length - 1, idx = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (lyr.lines[mid].t <= t + 0.15) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
  if (idx === lyr.current) return;
  const items = ps.els.lyrics.querySelectorAll(".ps-line");
  items[lyr.current]?.classList.remove("current");
  lyr.current = idx;
  const el = items[idx];
  if (!el) return;
  el.classList.add("current");
  if (Date.now() - lyr.userScroll > 2500) {
    // Scroll the lyrics panel only (scrollIntoView would move the whole sheet too).
    const panel = ps.els.lyrics;
    const top = el.offsetTop - (panel.clientHeight - el.offsetHeight) / 2; // the panel is the lines' offsetParent
    panel.scrollTo({ top: Math.max(0, top), behavior: reducedMotion() ? "auto" : "smooth" });
  }
}

function psBuild() {
  if (ps.els) return;
  const e = {};
  e.cover = h("div", { class: "ps-cover" });
  e.title = h("strong", { class: "ps-title", dir: "auto" });
  e.artist = h("span", { class: "ps-artist", dir: "auto" });
  e.from = h("button", { class: "link-btn ps-from", type: "button", onclick: () => {
    closeDialog($("#player-dialog")); if (player.folder != null) navigate(player.folder);
  } });
  e.seek = h("input", { class: "np-seek ps-seek", type: "range", min: "0", max: "1000", value: "0", step: "1", "aria-label": "Position in the track" });
  e.seek.addEventListener("input", () => { player.seeking = true; });
  e.seek.addEventListener("change", () => {
    const a = player.audio;
    if (a?.duration) a.currentTime = (e.seek.value / 1000) * a.duration;
    player.seeking = false;
  });
  e.now = h("span", { class: "ps-time" });
  e.left = h("span", { class: "ps-time" });
  e.shuffle = h("button", { class: "ps-btn ps-shuffle", type: "button", "aria-label": "Shuffle", onclick: () => setShuffle(!player.shuffle) }, icon("shuffle"));
  e.autoplay = h("button", { class: "ps-btn ps-autoplay", type: "button", "aria-label": "Autoplay", title: "Autoplay: keep playing similar songs when the queue ends",
    onclick: () => setAutoplay(!player.autoplay) }, icon("autoplay"));
  e.prev = h("button", { class: "ps-btn", type: "button", "aria-label": "Previous track", onclick: playPrev }, icon("prev"));
  e.play = h("button", { class: "ps-btn ps-play", type: "button", onclick: () => player.track && togglePlay(player.track) });
  e.next = h("button", { class: "ps-btn", type: "button", "aria-label": "Next track", onclick: playNext }, icon("next"));
  e.lyricsBtn = h("button", { class: "ps-btn ps-tabbtn", type: "button", "aria-label": "Lyrics", onclick: () => psTab(ps.tab === "lyrics" ? "queue" : "lyrics") }, icon("lyrics"));
  e.tabs = h("div", { class: "ps-tabs", role: "tablist" },
    h("button", { type: "button", role: "tab", dataset: { tab: "queue" }, onclick: () => psTab("queue") }, "Up next"),
    h("button", { type: "button", role: "tab", dataset: { tab: "lyrics" }, onclick: () => psTab("lyrics") }, "Lyrics"));
  e.queue = h("div", { class: "ps-panel ps-queue" });
  e.lyrics = h("div", { class: "ps-panel ps-lyrics" });
  for (const ev of ["wheel", "touchmove"]) e.lyrics.addEventListener(ev, () => { lyr.userScroll = Date.now(); }, { passive: true });
  setKids($("#player-body"),
    h("div", { class: "ps-top" }, e.cover,
      h("div", { class: "ps-meta" }, e.title, e.artist, e.from)),
    h("div", { class: "ps-seekrow" }, e.now, e.seek, e.left),
    h("div", { class: "ps-controls" }, e.shuffle, e.prev, e.play, e.next, e.autoplay, e.lyricsBtn),
    e.tabs, e.queue, e.lyrics);
  ps.els = e;
}

function psTab(tab) {
  ps.tab = tab;
  renderPlayerSheet();
  if (tab === "lyrics") loadLyrics();
}

function openPlayerSheet() {
  if (!player.track) return;
  psBuild();
  openDialog($("#player-dialog"));
  renderPlayerSheet();
  if (ps.tab === "lyrics") loadLyrics();
}

function renderPlayerSheet() {
  const d = $("#player-dialog");
  if (!ps.els || !d?.open || !player.track) return;
  const e = ps.els;
  const t = player.track;
  const playing = player.audio && !player.audio.paused;
  setKids(e.cover, t.art ? h("img", { src: artUrlFor(t), alt: "" }) : icon("note"));
  e.cover.classList.toggle("playing", !!playing);
  e.title.textContent = first(t, "title") || t.name;
  const credit = (t.tags.artist || []).join(", ");
  setKids(e.artist, credit ? artistButton(credit, t.tags.artist || [], { pictures: true, before: () => closeDialog($("#player-dialog")) }) : "");
  e.from.textContent = player.folderName ? `From ${player.folderName}` : "";
  e.from.hidden = !player.folderName;
  setKids(e.play, icon(playing ? "pause" : "play"));
  e.play.setAttribute("aria-label", playing ? "Pause" : "Play");
  e.shuffle.classList.toggle("on", player.shuffle);
  e.shuffle.setAttribute("aria-pressed", String(player.shuffle));
  e.autoplay.classList.toggle("on", player.autoplay);
  e.autoplay.setAttribute("aria-pressed", String(player.autoplay));
  e.next.disabled = !canGoOn();
  e.lyricsBtn.classList.toggle("on", ps.tab === "lyrics");
  for (const b of e.tabs.children) b.setAttribute("aria-selected", String(b.dataset.tab === ps.tab));
  d.classList.toggle("lyrics-mode", ps.tab === "lyrics");
  e.queue.hidden = ps.tab !== "queue";
  e.lyrics.hidden = ps.tab !== "lyrics";
  const upcoming = player.order.slice(player.pos + 1);
  const firstAuto = upcoming.findIndex((qi) => player.queue[qi].auto);
  const autoHead = () => h("li", { class: "ps-auto-head" },
    h("span", { class: "ps-auto-title" }, icon("autoplay"), "Autoplay"),
    h("span", { class: "ps-auto-sub" },
      player.because ? h("span", {}, `Similar to ${player.because}`) : null,
      player.because && player.source ? " · " : null,
      player.source ? h("span", {}, `from ${player.source}`) : null));
  const empty = player.autoplay
    ? (player.extending ? "Finding similar songs…" : "Autoplay picks similar songs from your library when this one ends.")
    : "Nothing after this one. Play a track in another album to queue it up, or turn on Autoplay.";
  setKids(e.queue, upcoming.length
    ? h("ol", { class: "ps-list" }, upcoming.flatMap((qi, k) => {
      const x = player.queue[qi];
      const pos = player.pos + 1 + k;
      const row = h("li", { class: "ps-item" },
        h("button", { class: "ps-item-main", type: "button", onclick: () => playPos(pos) },
          h("span", { class: "ps-item-title", dir: "auto" }, first(x, "title") || x.name),
          h("span", { class: "ps-item-artist", dir: "auto" }, (x.tags.artist || []).join(", "))),
        h("button", { class: "icon-btn ps-remove", type: "button", "aria-label": `Remove ${first(x, "title") || x.name} from the queue`,
          onclick: () => removeFromQueue(pos) }, icon("close")));
      return k === firstAuto ? [autoHead(), row] : [row];
    }))
    : h("p", { class: "ps-empty" }, empty));
  psProgress();
}

function psProgress() {
  const a = player.audio;
  if (!ps.els || !$("#player-dialog")?.open || !a) return;
  const d = a.duration;
  if (!player.seeking) {
    ps.els.seek.value = d ? String(Math.round((a.currentTime / d) * 1000)) : "0";
    ps.els.seek.style.setProperty("--pos", d ? `${(a.currentTime / d) * 100}%` : "0%");
  }
  ps.els.now.textContent = fmtDuration(a.currentTime || 0);
  ps.els.left.textContent = d ? `-${fmtDuration(Math.max(0, d - a.currentTime))}` : "";
  if (ps.tab === "lyrics") psLyricsTick();
}

export function openTrack(track) {
  if (track.error) { toast(`Can't read this file: ${track.error}`, "error"); return; }
  openEditor([track.path]);
}
