// Tiny DOM helpers (h, $, icons) and motion helpers.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

// ---- Tiny DOM helpers ----------------------------------------------------------

export const $ = (sel, root = document) => root.querySelector(sel);

/** Create an element: h("div", {class: "x", onclick: fn}, child, "text", ...) */
/** Sentences side by side, each its own text (a translation matches whole sentences). */
export const sentences = (list) => list.flatMap((s, i) => (i ? [" ", h("span", {}, s)] : [h("span", {}, s)]));

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (["value", "checked", "disabled", "indeterminate", "open"].includes(k)) el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  // dir="auto" marks the user's own text (titles, artists, folder names): never translated.
  if (attrs?.dir === "auto" && !("translate" in attrs) && tag !== "input" && tag !== "textarea") el.setAttribute("translate", "no");
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

/** Like el.replaceChildren(...), but skips null/false (which would render as "null"). */
export function setKids(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
}

// ---- Motion helpers ------------------------------------------------------------------

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Play an exit animation (CSS class ``cls``), then call ``done``. Instant with reduced motion. */
export function playOut(el, cls, done) {
  if (reducedMotion() || el.hidden) { done(); return; }
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    el.classList.remove(cls);
    done();
  };
  el.classList.add(cls);
  el.addEventListener("animationend", finish, { once: true });
  setTimeout(finish, 400); // safety net if the animation doesn't run
}

/** Restart an entrance animation class on an element. */
export function replay(el, cls) {
  el.classList.remove("nav-forward", "nav-back", "nav-fade", cls);
  void el.offsetWidth; // force reflow so the animation starts again
  el.classList.add(cls);
}

/**
 * Codetta's own confirmation sheet. Resolves true (confirmed) or false.
 * ask({ title, message, details, confirmLabel, cancelLabel, danger })
 */
export function ask({ title, message = "", details = null, confirmLabel = "OK", cancelLabel = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    const d = $("#confirm-dialog");
    const ok = $("#confirm-ok");
    const cancel = $("#confirm-cancel");
    $("#confirm-title").textContent = title;
    setKids($("#confirm-body"), message ? h("p", { class: "confirm-msg" }, message) : null, details);
    ok.textContent = confirmLabel;
    ok.className = `btn ${danger ? "danger-fill" : "primary"}`;
    cancel.hidden = cancelLabel == null;
    cancel.textContent = cancelLabel ?? "";
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeDialog(d);
      resolve(value);
    };
    ok.onclick = () => finish(true);
    cancel.onclick = () => finish(false);
    d.oncancel = (e) => { e.preventDefault(); finish(false); }; // Escape
    d.onclick = (e) => { if (e.target === d) finish(false); }; // backdrop
    openDialog(d);
    setTimeout(() => (danger ? cancel : ok).focus(), 60); // safe default for destructive actions
  });
}

export function closeDialog(dialog) {
  if (!dialog.open || dialog.classList.contains("closing")) return;
  dialog.cancelClose = false;
  playOut(dialog, "closing", () => { if (!dialog.cancelClose) dialog.close(); });
}

export function openDialog(dialog) {
  if (dialog.open) {
    // Reopened while its close animation was still playing: keep it open.
    dialog.cancelClose = true;
    dialog.classList.remove("closing");
    return;
  }
  dialog.showModal();
  // The browser focuses the first control, usually the close button, and Safari then draws a
  // focus ring around it even after a tap. Focus the sheet itself instead (Tab still goes
  // straight to the first control); a field meant to get focus (autofocus) keeps it.
  if (document.activeElement?.matches("[data-close], .sheet-head .icon-btn")) {
    dialog.tabIndex = -1;
    dialog.focus({ preventScroll: true });
  }
}

const ICONS = {
  discogs: '<svg class="brand-logo" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 1a9 9 0 1 1 0 18 9 9 0 0 1 0-18zm0 3.2a5.8 5.8 0 1 0 0 11.6 5.8 5.8 0 0 0 0-11.6zm0 4.3a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3z"/><path d="M10 6.4a3.6 3.6 0 0 0-3.6 3.6" fill="none" stroke="currentColor" stroke-width=".9" opacity=".55"/></svg>',
  volume: '<svg viewBox="0 0 20 20"><path d="M3.5 8v4h3l4 3.5v-11l-4 3.5z"/><path d="M13.5 7.5a3.5 3.5 0 0 1 0 5M15.5 5.5a6.3 6.3 0 0 1 0 9"/></svg>',
  download: '<svg viewBox="0 0 20 20"><path d="M10 3.5V13M6 9l4 4 4-4M3.5 12.5v2A1.5 1.5 0 0 0 5 16h10a1.5 1.5 0 0 0 1.5-1.5v-2"/></svg>',
  upload: '<svg viewBox="0 0 20 20"><path d="M10 13V3.5M6 7.5l4-4 4 4M3.5 12.5v2A1.5 1.5 0 0 0 5 16h10a1.5 1.5 0 0 0 1.5-1.5v-2"/></svg>',
  tag: '<svg viewBox="0 0 20 20"><path d="M3.5 4.5v4.8l7.2 7.2a1.4 1.4 0 0 0 2 0l3.8-3.8a1.4 1.4 0 0 0 0-2L9.3 3.5H4.5a1 1 0 0 0-1 1Z"/><circle cx="6.8" cy="6.8" r="1.1"/></svg>',
  info: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7.5"/><path d="M10 9v5M10 6.2v.1"/></svg>',
  trash: '<svg viewBox="0 0 20 20"><path d="M3.5 5.5h13M8 5.5V4h4v1.5M5.5 5.5l.8 10.5h7.4l.8-10.5M8.5 8.5v5M11.5 8.5v5"/></svg>',
  move: '<svg viewBox="0 0 20 20"><path d="M2.5 5.5a1.5 1.5 0 0 1 1.5-1.5h3.6l1.8 2H16a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 16 16H4a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M8 11h5m-2-2 2 2-2 2"/></svg>',
  folder: '<svg viewBox="0 0 20 20"><path d="M2.5 5.5a1.5 1.5 0 0 1 1.5-1.5h3.6l1.8 2H16a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 16 16H4a1.5 1.5 0 0 1-1.5-1.5z"/></svg>',
  close: '<svg viewBox="0 0 20 20"><path d="m5 5 10 10M15 5 5 15"/></svg>',
  clear: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="m7.5 7.5 5 5m0-5-5 5"/></svg>',
  sun: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="3.5"/><path d="M10 2v2m0 12v2M2 10h2m12 0h2M4.3 4.3l1.4 1.4m8.6 8.6 1.4 1.4M4.3 15.7l1.4-1.4m8.6-8.6 1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 20 20"><path d="M16 12.5A6.5 6.5 0 0 1 7.5 4a6.5 6.5 0 1 0 8.5 8.5z"/></svg>',
  auto: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="M10 3a7 7 0 0 1 0 14z" fill="currentColor" stroke="none"/></svg>',
  plus: '<svg viewBox="0 0 20 20"><path d="M10 4v12M4 10h12"/></svg>',
  copy: '<svg viewBox="0 0 20 20"><rect x="7" y="7" width="9.5" height="9.5" rx="2"/><path d="M13 7V5a1.5 1.5 0 0 0-1.5-1.5h-6A1.5 1.5 0 0 0 4 5v6A1.5 1.5 0 0 0 5.5 12.5H7"/></svg>',
  chevron: '<svg viewBox="0 0 20 20"><path d="m8 5 5 5-5 5"/></svg>',
  rows: '<svg viewBox="0 0 20 20"><path d="M4 5.5h12M4 10h12M4 14.5h12"/></svg>',
  grid: '<svg viewBox="0 0 20 20"><rect x="3.5" y="3.5" width="5" height="5" rx="1"/><rect x="11.5" y="3.5" width="5" height="5" rx="1"/><rect x="3.5" y="11.5" width="5" height="5" rx="1"/><rect x="11.5" y="11.5" width="5" height="5" rx="1"/></svg>',
  note: '<svg viewBox="0 0 20 20"><path d="M8 15.5V5l8-1.5v10"/><circle cx="6" cy="15.5" r="2"/><circle cx="14" cy="13.5" r="2"/></svg>',
  search: '<svg viewBox="0 0 20 20"><circle cx="8.5" cy="8.5" r="5.5"/><path d="m13 13 4 4"/></svg>',
  check: '<svg viewBox="0 0 20 20"><path d="m5 10.5 3.2 3.2L15 7"/></svg>',
  alert: '<svg viewBox="0 0 20 20"><path d="M10 5v6.5M10 15v.01"/></svg>',
  user: '<svg viewBox="0 0 20 20"><circle cx="10" cy="7" r="3.2"/><path d="M3.8 16.5a6.2 6.2 0 0 1 12.4 0"/></svg>',
  undo: '<svg viewBox="0 0 20 20"><path d="M7.5 5 4 8.5 7.5 12"/><path d="M4.5 8.5h7a4.5 4.5 0 0 1 0 9H9"/></svg>',
  spark: '<svg viewBox="0 0 20 20"><path d="M10 3.5 11.4 8.6 16.5 10l-5.1 1.4L10 16.5l-1.4-5.1L3.5 10l5.1-1.4z"/></svg>',
  // A disc (drawn for Codetta): rim, label ring, spindle hole and two shine arcs.
  inbox: '<svg viewBox="0 0 20 20"><path d="M3.5 11.5 5.6 5a1.5 1.5 0 0 1 1.4-1h6a1.5 1.5 0 0 1 1.4 1l2.1 6.5v3A1.5 1.5 0 0 1 15 16H5a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M3.5 11.5h3.5l1 2h4l1-2h3.5"/></svg>',
  disc: '<svg class="disc-icon" viewBox="0 0 20 20"><circle cx="10" cy="10" r="7.5"/><circle cx="10" cy="10" r="2.6"/><circle cx="10" cy="10" r=".6" fill="currentColor" stroke="none"/><path d="M5.4 8.05A5 5 0 0 1 7.97 5.43"/><path d="M14.6 11.95a5 5 0 0 1-2.57 2.62"/></svg>',
  play: '<svg viewBox="0 0 20 20"><path d="M7 5.2v9.6a.6.6 0 0 0 .9.5l7.6-4.8a.6.6 0 0 0 0-1L7.9 4.7a.6.6 0 0 0-.9.5z" fill="currentColor" stroke="none"/></svg>',
  pause: '<svg viewBox="0 0 20 20"><rect x="5.5" y="4.5" width="3" height="11" rx="1" fill="currentColor" stroke="none"/><rect x="11.5" y="4.5" width="3" height="11" rx="1" fill="currentColor" stroke="none"/></svg>',
  // MusicBrainz's two-tone mark (drawn here: the page loads nothing from other sites).
  musicbrainz: '<svg class="mb-logo" viewBox="0 0 32 32"><path class="mb-l" d="M15.3 3.2 5.5 8.8v14.4l9.8 5.6z"/><path class="mb-r" d="M16.7 3.2l9.8 5.6v14.4l-9.8 5.6z"/><path class="mb-cut" d="M11.5 11.2c-1.8 0-3.2 1.4-3.2 3.2 0 1.2.7 2.3 1.7 2.8-.2.5-.3 1-.3 1.6 0 2.1 1.7 3.8 3.8 3.8h1.8V11.2z"/><path class="mb-cut" d="M20.5 11.2c1.8 0 3.2 1.4 3.2 3.2 0 1.2-.7 2.3-1.7 2.8.2.5.3 1 .3 1.6 0 2.1-1.7 3.8-3.8 3.8h-1.8V11.2z"/></svg>',
  deezer: '<svg class="brand-logo" viewBox="0 0 20 20"><ellipse cx="1.40" cy="9.20" rx="1.05" ry="2.20"/><ellipse cx="3.55" cy="8.30" rx="1.2" ry="4.70"/><ellipse cx="5.70" cy="8.20" rx="1.2" ry="6.60"/><ellipse cx="7.85" cy="9.80" rx="1.2" ry="6.90"/><ellipse cx="10.00" cy="12.00" rx="1.2" ry="6.60"/><ellipse cx="12.15" cy="9.80" rx="1.2" ry="6.90"/><ellipse cx="14.30" cy="8.20" rx="1.2" ry="6.60"/><ellipse cx="16.45" cy="8.30" rx="1.2" ry="4.70"/><ellipse cx="18.60" cy="9.20" rx="1.05" ry="2.20"/></svg>',
  itunes: '<svg class="brand-logo" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 1a9 9 0 1 1 0 18 9 9 0 0 1 0-18zm3.6 3.6-6 1.3c-.3.1-.5.3-.5.6v6.3a2.3 2.3 0 1 0 1.3 2.1V8.6l4.6-1v3.8a2.3 2.3 0 1 0 1.3 2.1V5.2c0-.4-.3-.7-.7-.6z"/></svg>',
  slskd: '<svg class="sk-logo" viewBox="0 0 20 20"><path class="sk-vane" d="M18 2c-6.2.3-10.6 3.8-11.7 9.6l3-.7-1.7 2c3.5.4 6.3-1.2 7.6-4l-2.3.3 2.8-2C16.6 5.5 17.3 3.8 18 2z"/><path class="sk-quill" d="M14.5 5.5 3 17.5"/></svg>',
  gear: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="2.6"/><path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4"/><circle cx="10" cy="10" r="5.2"/></svg>',
  code: '<svg viewBox="0 0 20 20"><path d="M7 6 3 10l4 4M13 6l4 4-4 4"/></svg>',
  bell: '<svg viewBox="0 0 20 20"><path d="M5.5 13.5V9a4.5 4.5 0 0 1 9 0v4.5l1.5 2h-12z"/><path d="M8.5 17.5a1.6 1.6 0 0 0 3 0"/></svg>',
  // Drawn for Codetta: a sheet of paper with a pencil (Tag Presets), a stack of layers (Organize),
  // a ticked circle (Select) and two of them (Select all).
  preset: '<svg viewBox="0 0 20 20"><path d="M10 17.5H5.5a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1h6l3 3v3.5"/><path d="M11.5 2.5v3h3"/><path d="M7.5 8.5h4.5M7.5 11.5h3"/><path d="m15.6 10.6 1.8 1.8-5.2 5.2-2.4.6.6-2.4z"/></svg>',
  layers: '<svg viewBox="0 0 20 20"><path d="M10 3 2.5 6.8 10 10.6l7.5-3.8z"/><path d="m2.5 10.2 7.5 3.8 7.5-3.8"/><path d="m2.5 13.6 7.5 3.8 7.5-3.8"/></svg>',
  select: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="m7 10.2 2.1 2.1L13.2 8"/></svg>',
  selectall: '<svg viewBox="0 0 20 20"><circle cx="8" cy="10" r="5.5"/><path d="M12.6 4.9a5.5 5.5 0 0 1 0 10.2"/><path d="m5.8 10 1.6 1.6 3-3.2"/></svg>',
  next: '<svg viewBox="0 0 20 20"><path d="M4.5 5.2v9.6a.6.6 0 0 0 .9.5l6.8-4.8a.6.6 0 0 0 0-1L5.4 4.7a.6.6 0 0 0-.9.5z" fill="currentColor" stroke="none"/><rect x="13.5" y="4.5" width="2.2" height="11" rx=".9" fill="currentColor" stroke="none"/></svg>',
  prev: '<svg viewBox="0 0 20 20"><path d="M15.5 5.2v9.6a.6.6 0 0 1-.9.5l-6.8-4.8a.6.6 0 0 1 0-1l6.8-4.8a.6.6 0 0 1 .9.5z" fill="currentColor" stroke="none"/><rect x="4.3" y="4.5" width="2.2" height="11" rx=".9" fill="currentColor" stroke="none"/></svg>',
  autoplay: '<svg viewBox="0 0 20 20"><path d="M5.6 13.2c-1.8 0-3.1-1.4-3.1-3.2s1.3-3.2 3.1-3.2c3.1 0 5.7 6.4 8.8 6.4 1.8 0 3.1-1.4 3.1-3.2s-1.3-3.2-3.1-3.2c-3.1 0-5.7 6.4-8.8 6.4z"/></svg>',
  shuffle: '<svg viewBox="0 0 20 20"><path d="M3 6h2.4c2.6 0 3.6 1.6 4.6 4s2 4 4.6 4H17"/><path d="M3 14h2.4c1.2 0 2-.4 2.7-1.1M11.9 7.1c.7-.7 1.5-1.1 2.7-1.1H17"/><path d="m15 4 2 2-2 2M15 12l2 2-2 2"/></svg>',
  lyrics: '<svg viewBox="0 0 20 20"><path d="M3.5 5h11M3.5 8.5h11M3.5 12h6"/><circle cx="13" cy="15" r="1.8"/><path d="M14.8 15V10l2.4.8"/></svg>',
  replace: '<svg viewBox="0 0 20 20"><circle cx="7.5" cy="7.5" r="4"/><path d="m10.5 10.5 2.5 2.5"/><path d="M12 4.5h5M14.5 2l2.5 2.5-2.5 2.5"/><path d="M9 16.5h8M11.5 14l-2.5 2.5 2.5 2.5"/></svg>',
  rename: '<svg viewBox="0 0 20 20"><path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h3l1.5 1.5H15A1.5 1.5 0 0 1 16.5 8v1.5"/><path d="M3 6.5v8A1.5 1.5 0 0 0 4.5 16H9"/><path d="m15.4 10.6 1.9 1.9-5 5-2.5.6.6-2.5z"/></svg>',
  wand: '<svg viewBox="0 0 20 20"><path d="m3.5 16.5 9-9"/><path d="m11 6 1.5-1.5 3 3L14 9z"/><path d="M15 2.5v2M16 3.5h-2M5.5 3v2.4M6.7 4.2H4.3M17 11v2M18 12h-2"/></svg>',
  more: '<svg viewBox="0 0 20 20"><circle cx="5" cy="10" r="1.3" fill="currentColor" stroke="none"/><circle cx="10" cy="10" r="1.3" fill="currentColor" stroke="none"/><circle cx="15" cy="10" r="1.3" fill="currentColor" stroke="none"/></svg>',
  pulse: '<svg viewBox="0 0 20 20"><path d="M2.5 10.5h3.5l2-5 3.5 9 2-4.5h4"/></svg>',
  paste: '<svg viewBox="0 0 20 20"><rect x="4.5" y="4" width="11" height="13" rx="2"/><path d="M8 4V3h4v1"/><path d="M7.5 9h5M7.5 12h3"/></svg>',
};

const iconCache = new Map(); // each icon is parsed once, then cloned (a big folder draws thousands)

export function icon(name) {
  let svg = iconCache.get(name);
  if (!svg) {
    const t = document.createElement("template");
    t.innerHTML = ICONS[name].trim();
    svg = t.content.firstChild;
    svg.setAttribute("aria-hidden", "true");
    iconCache.set(name, svg);
  }
  return svg.cloneNode(true);
}

/** Draw a long list without freezing the page: the first screenful at once, the rest in
 *  small batches between frames. A newer draw of the same list cancels the old one. */
export function drawInBatches(container, items, build, { head = [], first = 120, batch = 250, done = null } = {}) {
  const gen = (container.drawGen = (container.drawGen || 0) + 1);
  container.replaceChildren(...head, ...items.slice(0, first).map(build));
  let i = first;
  if (i >= items.length) { done?.(); return; }
  const step = () => {
    if (container.drawGen !== gen) return; // the list was redrawn meanwhile
    const frag = document.createDocumentFragment();
    for (const it of items.slice(i, i + batch)) frag.append(build(it));
    container.append(frag);
    i += batch;
    done?.();
    if (i < items.length) setTimeout(step, 0);
  };
  setTimeout(step, 0);
}
