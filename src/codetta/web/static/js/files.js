// The context menu, importing music, Recently deleted and Report a problem.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, ask, closeDialog, h, icon, replay, setKids } from "./dom.js";
import { api } from "./api.js";
import { els, first, plural, state, toast } from "./state.js";
import { folderCache, loadFolder, renderSelectionBar, toggleSelect, trackByPath } from "./browse.js";
import { setBang } from "./search.js";
import { folderCovers, isPhone, openActions, setSelectMode } from "./tools.js";
import { closeEditor, confirmDiscard } from "./editor.js";
import { refreshActivity } from "./activity.js";
import { openMusicBrainzFor } from "./musicbrainz.js";
import { loadInbox, skReady } from "./inbox.js";
import { appStarted, copyText, showAuth } from "./account.js";

// ---- Context menu: right-click on a computer, a long press on a phone ---------------------------------
//
// One small menu for a track or a folder: Rename, Move to, Select, Actions, Get info, Find in
// MusicBrainz / slskd, Delete. Moves and deletes go through the same safe mover as Organize
// (nothing overwritten, one undo); Delete sends things to "Recently deleted" for 30 days.

const ctx = { menu: null, openedAt: 0, press: null, suppressClick: false };
const LONG_PRESS_MS = 500;

function closeContextMenu() {
  ctx.menu?.remove();
  ctx.menu = null;
}

function openContextMenu(x, y, items) {
  closeContextMenu();
  document.querySelector(".tools-menu")?.remove();
  const menu = h("div", { class: "tools-menu ctx-menu", role: "menu" }, items.filter(Boolean).map((t) => t === "-"
    ? h("div", { class: "ctx-sep", role: "separator" })
    : h("button", { class: `tools-item${t.danger ? " danger" : ""}`, type: "button", role: "menuitem",
      onclick: () => { closeContextMenu(); t.run(); } }, icon(t.icon), t.label)));
  document.body.append(menu);
  // Next to the pointer, but always fully on screen.
  const left = Math.min(Math.max(8, x), window.innerWidth - menu.offsetWidth - 8);
  const top = Math.min(Math.max(8, y), window.innerHeight - menu.offsetHeight - 8);
  Object.assign(menu.style, { left: `${left}px`, top: `${top}px` });
  menu.style.transformOrigin = `${x - left}px ${y - top}px`;
  replay(menu, "opening");
  ctx.menu = menu;
  ctx.openedAt = Date.now();
  // No focus on open (a ring around the first item after a click looks like a selection);
  // the first arrow key moves into the menu instead.
  const away = (e) => { if (!menu.contains(e.target)) { closeContextMenu(); off(); } };
  const key = (e) => {
    if (e.key === "Escape") { closeContextMenu(); off(); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const btns = [...menu.querySelectorAll("button")];
      const i = btns.indexOf(document.activeElement);
      btns[(i + (e.key === "ArrowDown" ? 1 : btns.length - 1)) % btns.length]?.focus();
      e.preventDefault();
    }
  };
  const off = () => { document.removeEventListener("pointerdown", away, true); document.removeEventListener("keydown", key, true);
    window.removeEventListener("scroll", scrolled, true); };
  const scrolled = () => { closeContextMenu(); off(); };
  setTimeout(() => {
    document.addEventListener("pointerdown", away, true);
    document.addEventListener("keydown", key, true);
    window.addEventListener("scroll", scrolled, true);
  }, 0);
}

const baseOf = (p) => p.split("/").pop();
const stemOf = (name) => (name.includes(".") ? name.slice(0, name.lastIndexOf(".")) : name);

async function afterFileChange(paths = []) {
  folderCache.clear(); folderCovers.clear();
  if (state.editor && state.editor.paths.some((p) => paths.some((q) => p === q || p.startsWith(`${q}/`)))) closeEditor(true);
  for (const p of paths) state.selected.delete(p);
  renderSelectionBar();
  refreshActivity();
  await loadFolder(state.path, { keepScroll: true });
}

function trackMenu(t) {
  const many = state.selected.has(t.path) && state.selected.size > 1;
  const paths = many ? [...state.selected] : [t.path];
  const title = first(t, "title") || t.name;
  const label = many ? plural(paths.length, "selected track") : `“${title}”`;
  const artist = first(t, "artist") || first(t, "albumartist");
  return [
    many ? null : { icon: "rename", label: "Rename…", run: () => renameEntry(t.path, false) },
    { icon: "move", label: "Move to…", run: () => moveEntries(paths, label) },
    many ? null : { icon: "select", label: "Select", run: () => { if (isPhone()) setSelectMode(true); toggleSelect(t.path, true, false); } },
    { icon: "wand", label: "Actions…", run: () => openActions({ paths }, label) },
    many ? null : { icon: "info", label: "Get info", run: () => showInfo(t.path) },
    state.status?.matching ? { icon: "musicbrainz", label: "Find in MusicBrainz", run: () => openMusicBrainzFor({ body: { paths }, label }) } : null,
    !many && skReady() ? { icon: "slskd", label: "Find in slskd", run: () => slskdFor([artist, title].filter(Boolean).join(" ")) } : null,
    "-",
    { icon: "trash", label: "Delete…", danger: true, run: () => deleteEntries(paths, label) },
  ];
}

function folderMenu(path) {
  const name = baseOf(path);
  const parts = path.split("/");
  return [
    { icon: "rename", label: "Rename…", run: () => renameEntry(path, true) },
    { icon: "move", label: "Move to…", run: () => moveEntries([path], `“${name}”`) },
    { icon: "info", label: "Get info", run: () => showInfo(path) },
    state.status?.matching ? { icon: "musicbrainz", label: "Find in MusicBrainz", run: () => openMusicBrainzFor({ body: { folder: path }, label: `“${name}”` }) } : null,
    skReady() ? { icon: "slskd", label: "Find in slskd", run: () => slskdFor(parts.slice(-2).join(" ").replace(/\s*[([]\d{4}[)\]]\s*/g, " ").trim()) } : null,
    "-",
    { icon: "trash", label: "Delete…", danger: true, run: () => deleteEntries([path], `“${name}”`) },
  ];
}

function slskdFor(query) {
  els.filter.value = query;
  setBang(true, "");
  els.filter.focus();
  els.filter.select();
}

async function renameEntry(path, isFolder) {
  if (!(await confirmDiscard())) return;
  const name = baseOf(path);
  const ext = isFolder || !name.includes(".") ? "" : name.slice(name.lastIndexOf("."));
  const input = h("input", { type: "text", value: isFolder ? name : stemOf(name), maxlength: "255", dir: "auto", spellcheck: "false", autocomplete: "off", class: "rename-input" });
  setTimeout(() => { input.focus(); input.select(); }, 80);
  const ok = await ask({ title: isFolder ? "Rename folder" : "Rename file",
    message: isFolder ? "Every file moves with it. Nothing is overwritten, and Activity can undo it."
      : `The ${ext || "file"} extension stays, and a lyrics file with the same name follows. Activity can undo it.`,
    details: h("label", { class: "field" }, h("span", { class: "field-label" }, "New name"), input), confirmLabel: "Rename" });
  const value = input.value.trim();
  if (!ok || !value || value === (isFolder ? name : stemOf(name))) return;
  try {
    const r = await api("POST", isFolder ? "/api/folders/rename" : "/api/files/rename", { path, name: value });
    toast(r.failed ? `${r.failed} file(s) couldn't move` : `Renamed to “${baseOf(r.path)}”`, r.failed ? "error" : "success");
    await afterFileChange([path]);
  } catch (err) { toast(err.message, "error"); }
}

async function moveEntries(paths, label) {
  if (!(await confirmDiscard())) return;
  const from = paths[0].includes("/") ? paths[0].slice(0, paths[0].lastIndexOf("/")) : "";
  const pick = { path: from };
  const box = h("div", { class: "picker" });
  const draw = async () => {
    let data;
    try { data = await api("GET", `/api/folders?path=${encodeURIComponent(pick.path)}`); } catch (err) { setKids(box, h("p", { class: "error-box" }, err.message)); return; }
    const crumbs = pick.path ? pick.path.split("/") : [];
    setKids(box,
      h("div", { class: "picker-head" },
        pick.path ? h("button", { class: "icon-btn", type: "button", "aria-label": "Up one folder",
          onclick: () => { pick.path = crumbs.slice(0, -1).join("/"); draw(); } }, icon("chevron")) : null,
        h("strong", { class: "picker-where" }, crumbs.length ? crumbs[crumbs.length - 1] : "Library")),
      h("div", { class: "picker-list" }, data.folders.length
        ? data.folders.map((f) => h("button", { class: "picker-item", type: "button", disabled: paths.includes(f.path),
          onclick: () => { pick.path = f.path; draw(); } }, icon("folder"), h("span", {}, f.name), icon("chevron")))
        : h("p", { class: "hint" }, "No folders inside. Move here, or go up.")));
  };
  draw();
  const ok = await ask({ title: `Move ${label}`, message: "Pick the folder it goes into. Nothing is overwritten, and Activity can undo it.",
    details: box, confirmLabel: "Move here" });
  if (!ok) return;
  try {
    const r = await api("POST", "/api/files/move", { paths, to: pick.path });
    if (!r.moved && !r.failed) toast("It's already in that folder.");
    else toast(r.failed ? `Moved ${r.moved}, ${r.failed} couldn't move: ${r.errors[0]?.error || ""}` : `Moved to “${pick.path ? baseOf(pick.path) : "Library"}”`, r.failed ? "error" : "success");
    await afterFileChange(paths);
  } catch (err) { toast(err.message, "error"); }
}

async function deleteEntries(paths, label) {
  if (!(await confirmDiscard())) return;
  // One question: nothing is erased, so there's always a way back.
  if (!(await ask({ title: `Delete ${label}?`, danger: true, confirmLabel: "Move to Recently deleted",
    message: "It leaves your library and goes to Recently deleted, where it's kept for 30 days. Activity can put it back." }))) return;
  try {
    const r = await api("POST", "/api/files/delete", { paths });
    toast(r.failed ? `${r.failed} file(s) couldn't be deleted` : `Moved ${label} to Recently deleted. Undo is in Activity.`, r.failed ? "error" : "success");
    await afterFileChange(paths);
  } catch (err) { toast(err.message, "error"); }
}

const fmtBytes = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${Math.round(n / 1e3)} KB` : `${n} bytes`);

async function showInfo(path) {
  let d;
  try { d = await api("GET", `/api/files/info?path=${encodeURIComponent(path)}`); } catch (err) { toast(err.message, "error"); return; }
  const when = new Date(d.modified * 1000).toLocaleString();
  const rows = d.kind === "folder" ? [
    ["Contains", `${plural(d.audio, "song")}${d.files - d.audio ? `, ${plural(d.files - d.audio, "other file")}` : ""}${d.capped ? " (counted the first 20,000)" : ""}`],
    ["Folders inside", String(d.folders)],
    ["Size", fmtBytes(d.size)],
    ["Modified", when],
    ["Location", d.path || "Library"],
    ...(state.advanced ? [["On disk", d.on_disk]] : []),
  ] : [
    ["Format", [d.format?.toUpperCase(), d.codec && d.codec.toLowerCase() !== d.format ? d.codec : null].filter(Boolean).join(" · ")],
    ["Length", d.duration ? `${Math.floor(d.duration / 60)}:${String(Math.round(d.duration % 60)).padStart(2, "0")}` : "Unknown"],
    ["Quality", [d.bits_per_sample ? `${d.bits_per_sample}-bit` : null, d.sample_rate ? `${(d.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz` : null,
      d.bitrate ? `${Math.round(d.bitrate / 1000)} kbps` : null, d.channels === 2 ? "Stereo" : d.channels === 1 ? "Mono" : d.channels ? `${d.channels} channels` : null].filter(Boolean).join(" · ")],
    ["Size", fmtBytes(d.size)],
    ["Tags", d.tag_kind ? `${d.tag_kind}, ${plural(d.tag_count, "value")}` : "None"],
    ["Cover", d.art ? `${d.art.width && d.art.height ? `${d.art.width} × ${d.art.height}, ` : ""}${d.art.mime.replace("image/", "").toUpperCase()}, ${fmtBytes(d.art.size)}` : "None"],
    ["Modified", when],
    ["Location", d.path],
    ...(state.advanced ? [
      ["Encoder", d.encoder || "Not recorded"],
      ["Fields", d.fields_unsupported.length ? `${d.fields_supported} of ${d.fields_total} can be stored (not: ${d.fields_unsupported.join(", ")})`
        : `All ${d.fields_total} of Codetta's fields can be stored`],
      ["On disk", d.on_disk],
    ] : []),
  ];
  await ask({ title: d.name || "Library", details: h("dl", { class: "info-list" }, rows.map(([k, v]) => [h("dt", {}, k), h("dd", { dir: "auto" }, v || "—")])),
    confirmLabel: "Done", cancelLabel: "Copy location" }).then((done) => {
    if (done === false) navigator.clipboard?.writeText(d.path).then(() => toast("Location copied"), () => {});
  });
}

function contextTarget(el) {
  const row = el.closest(".track-row:not(.head)");
  if (row?.dataset.path) { const t = trackByPath(row.dataset.path); return t && !t.error ? { items: () => trackMenu(t) } : null; }
  const folder = el.closest(".folder[data-path]");
  if (folder && !folder.dataset.path.startsWith("@")) return { items: () => folderMenu(folder.dataset.path) };
  return null;
}

export function setupContextMenu() {
  for (const host of [els.tracks, els.folders]) {
    host.addEventListener("contextmenu", (e) => {
      const target = contextTarget(e.target);
      if (!target || state.folder?.mb) return;
      e.preventDefault();
      if (Date.now() - ctx.openedAt < 700) return; // a long press already opened it (Android fires both)
      openContextMenu(e.clientX, e.clientY, target.items());
    });
    host.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" || state.folder?.mb) return;
      const target = contextTarget(e.target);
      if (!target) return;
      const start = { x: e.clientX, y: e.clientY };
      clearTimeout(ctx.press?.timer);
      ctx.press = { start, timer: setTimeout(() => {
        ctx.press = null;
        ctx.suppressClick = true; // the finger lifting must not also open the track
        navigator.vibrate?.(10);
        openContextMenu(start.x, start.y, target.items());
      }, LONG_PRESS_MS) };
    });
    const cancel = (e) => {
      if (!ctx.press) return;
      if (e.type === "pointermove" && Math.hypot(e.clientX - ctx.press.start.x, e.clientY - ctx.press.start.y) < 10) return;
      clearTimeout(ctx.press.timer);
      ctx.press = null;
    };
    for (const type of ["pointermove", "pointerup", "pointercancel"]) host.addEventListener(type, cancel);
    host.addEventListener("click", (e) => {
      if (ctx.suppressClick) { ctx.suppressClick = false; e.preventDefault(); e.stopPropagation(); }
    }, true);
  }
}

// ---- Import: add music from this computer or phone ----------------------------------------------------
//
// Files go up one at a time (streamed to disk on the server) into one folder per import: the inbox,
// where they're matched and filed like new music, or "Imported" in the library, where Organize
// places them. Anything that isn't audio gets a warning first, never a refusal.

const AUDIO_EXT = /\.(flac|mp3|m4a|m4b|aac|ogg|oga|opus|wav|aif|aiff|dsf|wv|tta|mp2|wma|spx)$/i;
const MAX_IMPORT_BYTES = 2 * 1024 ** 3; // the server's limit per file (MAX_IMPORT_BYTES in core/importer.py)

export function pickImport() {
  const files = h("input", { type: "file", multiple: true, hidden: true });
  const folder = h("input", { type: "file", multiple: true, hidden: true, webkitdirectory: true });
  const take = (input, useFolders) => () => {
    importFiles([...input.files].map((f) => ({ file: f, path: useFolders && f.webkitRelativePath ? f.webkitRelativePath : f.name })));
    input.remove();
  };
  files.addEventListener("change", take(files, false));
  folder.addEventListener("change", take(folder, true));
  document.body.append(files, folder);
  const canFolder = "webkitdirectory" in folder && !isPhone();
  if (!canFolder) { files.click(); return; }
  ask({ title: "Import music", message: "Pick some files, or a whole folder (an album, or several).",
    confirmLabel: "Choose a folder", cancelLabel: "Choose files" }).then((wantFolder) => (wantFolder ? folder : files).click());
}

async function importFiles(list) {
  list = list.filter((x) => x.file && !x.path.split("/").some((p) => p.startsWith(".")));
  const huge = list.filter((x) => x.file.size > MAX_IMPORT_BYTES);
  if (huge.length) {
    list = list.filter((x) => x.file.size <= MAX_IMPORT_BYTES);
    toast(`${huge.length === 1 ? `“${huge[0].path.split("/").pop()}” is` : `${huge.length} files are`} over 2 GB, the most one file can be, so ${huge.length === 1 ? "it was" : "they were"} skipped.`, "error");
  }
  if (!list.length) return;
  const other = list.filter((x) => !AUDIO_EXT.test(x.path));
  if (other.length && !(await ask({ title: other.length === list.length ? "These aren't music files" : "Some of these aren't music",
    message: `${plural(other.length, "file")} of ${list.length} ${other.length === 1 ? "isn't" : "aren't"} audio (${other.slice(0, 3).map((x) => x.path.split("/").pop()).join(", ")}${other.length > 3 ? "…" : ""}). ${other.length === 1 ? "It'll" : "They'll"} be imported too, next to the music.`,
    confirmLabel: "Import anyway" }))) return;
  const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
  const batch = `${stamp}-${Math.random().toString(36).slice(2, 6)}`;
  const bar = h("div", { class: "import-progress", role: "status" }, h("span", {}, "Importing…"), h("span", { class: "import-bar" }, h("span", {})));
  document.body.append(bar);
  const done = [];
  let failed = 0;
  for (const [i, x] of list.entries()) {
    bar.firstChild.textContent = `Importing ${i + 1} of ${list.length}: ${x.path.split("/").pop()}`;
    bar.lastChild.firstChild.style.width = `${Math.round((i / list.length) * 100)}%`;
    try {
      const res = await fetch(`/api/import?batch=${encodeURIComponent(batch)}&path=${encodeURIComponent(x.path)}`, { method: "PUT", body: x.file });
      if (res.status === 401) { showAuth("login", "Your session ended. Sign in again, then import again."); break; }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Couldn't import ${x.path}`);
      done.push(data.path);
    } catch (err) {
      failed += 1;
      // fetch() itself fails (a TypeError) when the connection drops: say that, not "Failed to fetch".
      const why = err instanceof TypeError ? `Couldn't import “${x.path.split("/").pop()}”: the connection to Codetta dropped.` : err.message;
      if (failed === 1) toast(why, "error");
    }
  }
  bar.remove();
  if (!done.length) return;
  try {
    const r = await api("POST", "/api/import/done", { batch, paths: done });
    const extra = failed ? ` ${plural(failed, "file")} couldn't be imported.` : "";
    if (r.where === "inbox") {
      toast(`Imported ${plural(r.files, "file")} into your inbox: Codetta is matching ${r.files === 1 ? "it" : "them"}.${extra}`, failed ? "error" : "success");
      if ($("#inbox-dialog").open) loadInbox();
    } else {
      const why = [r.stayed_taken ? `${r.stayed_taken} already in your library` : "", r.stayed_untagged ? `${r.stayed_untagged} without enough tags` : ""].filter(Boolean).join(", ");
      toast(`Imported ${plural(r.files, "file")}${r.organized ? `, ${r.organized} placed with your folder pattern` : ""}${r.stayed ? `; ${r.stayed} stayed in “${r.folder}” (${why})` : ""}.${extra}`, failed ? "error" : "success");
    }
    folderCache.clear(); folderCovers.clear();
    refreshActivity();
    loadFolder(state.path, { keepScroll: true });
  } catch (err) { toast(err.message, "error"); }
}

// Drag music (files or whole folders) onto the page to import it.
async function droppedFiles(dt) {
  const out = [];
  const walk = (entry, prefix) => new Promise((resolve) => {
    if (entry.isFile) entry.file((f) => { out.push({ file: f, path: prefix + f.name }); resolve(); }, () => resolve());
    else if (entry.isDirectory) {
      const reader = entry.createReader();
      const all = [];
      const more = () => reader.readEntries(async (batch) => {
        if (!batch.length) { for (const e of all) await walk(e, `${prefix}${entry.name}/`); resolve(); return; }
        all.push(...batch);
        more();
      }, () => resolve());
      more();
    } else resolve();
  });
  const entries = [...(dt.items || [])].map((it) => it.webkitGetAsEntry?.()).filter(Boolean);
  if (entries.length) { for (const e of entries) await walk(e, ""); return out; }
  return [...dt.files].map((f) => ({ file: f, path: f.name }));
}

export function setupDropImport() {
  let depth = 0;
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  const veil = h("div", { class: "drop-veil", hidden: true }, h("div", {}, icon("upload"), h("strong", {}, "Drop to import"),
    h("span", {}, "Music goes to your inbox (or Imported) and is matched and placed like new music.")));
  document.body.append(veil);
  document.addEventListener("dragenter", (e) => { if (!hasFiles(e) || !appStarted) return; depth += 1; veil.hidden = false; });
  document.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) veil.hidden = true; });
  document.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener("drop", async (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    veil.hidden = true;
    if (!appStarted) return;
    importFiles(await droppedFiles(e.dataTransfer));
  });
}

// ---- Recently deleted: put things back, or delete them for good (carefully) ---------------------------

export async function openTrash() {
  let d;
  try { d = await api("GET", "/api/deleted"); } catch (err) { toast(err.message, "error"); return; }
  const day = 86400000;
  const box = h("div", { class: "trash-list" });
  const draw = () => {
    if (!d.items.length) { setKids(box, h("p", { class: "hint" }, "Nothing here. Deleted files stay for 30 days, then they're removed for good.")); return; }
    setKids(box, d.items.map((it) => {
      const left = Math.max(0, Math.ceil((it.expires * 1000 - Date.now()) / day));
      return h("div", { class: "trash-item" },
        h("div", { class: "trash-main" },
          h("strong", { dir: "auto" }, it.what.split("/").pop() || it.what),
          h("span", {}, `${it.what} · ${plural(it.files, "file")} · ${fmtBytes(it.size)}`),
          h("span", {}, `Deleted ${new Date(it.deleted * 1000).toLocaleDateString()} · ${left ? `removed in ${plural(left, "day")}` : "removed today"}`)),
        h("div", { class: "trash-actions" },
          h("button", { class: "btn small", type: "button", onclick: () => trashRestore([it.id]) }, "Put back"),
          h("button", { class: "btn small danger", type: "button", onclick: () => trashErase([it.id], it.files, it.what) }, "Delete now")));
    }));
  };
  const trashRestore = async (ids) => {
    try {
      const r = await api("POST", "/api/deleted/restore", { ids });
      toast(r.failed ? `Put back ${r.moved}; ${r.failed} couldn't (something else has that name now)` : `Put back ${plural(r.moved, "file")}`, r.failed ? "error" : "success");
      d = r; draw(); afterFileChange([]);
    } catch (err) { toast(err.message, "error"); }
  };
  const trashErase = async (ids, files, what) => {
    // The one thing that can't be undone: type the number of files to confirm.
    const input = h("input", { type: "text", inputmode: "numeric", autocomplete: "off", placeholder: String(files), class: "rename-input" });
    setTimeout(() => input.focus(), 80);
    const ok = await ask({ title: `Delete ${what === "everything" ? "everything" : `“${what.split("/").pop()}”`} for good?`, danger: true,
      message: `${plural(files, "file")} will be erased from the disk. This can't be undone, not even from Activity. To confirm, type ${files}.`,
      details: h("label", { class: "field" }, h("span", { class: "field-label" }, "Number of files"), input), confirmLabel: "Delete permanently" });
    if (!ok) { openTrash(); return; }
    if (Number(input.value.trim()) !== files) { toast("That number doesn't match, so nothing was deleted.", "error"); openTrash(); return; }
    try {
      const r = await api("POST", "/api/deleted/erase", { ids, confirm: files });
      toast(`Deleted ${plural(r.erased, "file")} for good`, "success");
      refreshActivity();
    } catch (err) { toast(err.message, "error"); }
    openTrash();
  };
  draw();
  const empty = d.items.length ? h("button", { class: "btn small danger", type: "button",
    onclick: () => { closeDialog($("#confirm-dialog")); setTimeout(() => trashErase(d.items.map((i) => i.id), d.files, "everything"), 250); } },
    `Empty (${plural(d.files, "file")})`) : null;
  await ask({ title: "Recently deleted", confirmLabel: "Done", cancelLabel: null, // one way out: nothing here needs a choice
    message: d.items.length ? `${plural(d.files, "file")}, ${fmtBytes(d.size)}. Each item is removed for good ${d.keep_days} days after it was deleted.` : "",
    details: h("div", {}, box, empty ? h("div", { class: "trash-foot" }, empty) : null) });
}

// ---- Report a problem: the details a bug report needs, ready to paste into a GitHub issue -------------

const ISSUES_URL = "https://github.com/gavndev/codetta/issues/new";

function browserName() {
  const ua = navigator.userAgent;
  const os = /iPhone|iPad/.test(ua) ? "iOS" : /Android/.test(ua) ? "Android" : /Mac OS X/.test(ua) ? "macOS" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "";
  const b = /Brave/.test(ua) || navigator.brave ? "Brave" : /Edg\//.test(ua) ? "Edge" : /Firefox|FxiOS/.test(ua) ? "Firefox"
    : /CriOS|Chrome/.test(ua) ? "Chrome" : /Safari/.test(ua) ? "Safari" : "a browser";
  return [b, os && `on ${os}`].filter(Boolean).join(" ");
}

export async function openReport() {
  let r;
  try { r = await api("GET", "/api/report"); } catch (err) { toast(err.message, "error"); return; }
  const env = [`Codetta ${r.version} (${r.install}, Python ${r.python}, ${r.system})`, `Browser: ${browserName()}`,
    `Library: ${r.tracks} tracks · Tidy up: ${r.tidy_up} · Connections: ${r.connections.join(", ") || "none"}`].join("\n");
  const log = r.log.map((l) => `${new Date(l.time * 1000).toISOString().slice(0, 19).replace("T", " ")} ${l.level.toUpperCase()} ${l.message}`).join("\n");
  const text = log ? `${env}\n\nRecent warnings:\n${log}` : env;
  const box = h("textarea", { class: "report-text", rows: "8", spellcheck: "false", "aria-label": "Details for the report" });
  box.value = text;
  const copy = h("button", { class: "btn small", type: "button", onclick: () => copyText(box.value) }, "Copy details");
  const body = (details) => `**What happened?**\n\n\n**What did you expect instead?**\n\n\n**Steps to get there**\n1. \n\n---\n<details><summary>Details from Codetta</summary>\n\n\`\`\`\n${details}\n\`\`\`\n</details>\n`;
  const ok = await ask({ title: "Report a problem", confirmLabel: "Open GitHub", cancelLabel: "Close",
    message: "Thanks for helping! These details go into a new GitHub issue for you to finish. Look them over first: log lines can include file and folder names, so remove anything you'd rather not share.",
    details: h("div", { class: "report-sheet" }, box, h("div", { class: "report-actions" }, copy)) });
  if (!ok) return;
  let url = `${ISSUES_URL}?labels=bug&body=${encodeURIComponent(body(box.value))}`;
  if (url.length > 7500) url = `${ISSUES_URL}?labels=bug&body=${encodeURIComponent(body(`${env}\n\n(Paste the copied details here.)`))}`;
  window.open(url, "_blank", "noopener");
}
