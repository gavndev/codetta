// Languages: Codetta's page in the reader's own language.
// Part of Codetta's page; app.js is the entry point (see the note at its top).
//
// The page is written in English. For another language, a catalog (static/i18n/<code>.json)
// maps each English text to its translation, and this module swaps the text in as it appears
// on screen: in the page, in menus, dialogs, toasts and the server's messages. Nothing else in
// the page has to know about languages.
//
// * Exact texts ("Rename…") are looked up directly.
// * Texts with names or numbers in them are patterns: "Moved to “{name}”" matches
//   "Moved to “Kid A”" and keeps "Kid A" as it is.
// * Anything inside translate="no" is left alone: song titles, artists, folder names and tag
//   values are the user's own, never translated (even if a song is called "Done").
//
// English readers never load a catalog, so this costs them nothing.

export const LANGUAGES = { en: "English", es: "Español" };
const KEY = "codetta-lang";
const ATTRS = ["placeholder", "title", "aria-label", "alt"];

const cat = { code: "en", exact: new Map(), byFirst: new Map(), byLast: new Map(), words: {}, observer: null };

/** A count with its word, in the reader's language: word(3, "track") -> "3 pistas". */
export function countWord(n, word, many) {
  const forms = cat.words[word];
  if (forms) return `${n} ${n === 1 ? forms[0] : forms[1]}`;
  return `${n} ${n === 1 ? word : many}`;
}

/** The language picked in Account ("" = follow the browser). */
export function chosenLanguage() {
  try { return localStorage.getItem(KEY) || ""; } catch { return ""; }
}

export function setLanguage(code) {
  try { if (code) localStorage.setItem(KEY, code); else localStorage.removeItem(KEY); } catch { /* private mode */ }
  location.reload();
}

/** The browser's own preference, if Codetta has that language. */
export function browserLanguage() {
  for (const l of navigator.languages || [navigator.language || "en"]) {
    const code = String(l).toLowerCase().split("-")[0];
    if (LANGUAGES[code]) return code;
  }
  return "en";
}

export const currentLanguage = () => cat.code;

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const firstWord = (s) => s.trimStart().split(/\s+/)[0] || "";
const lastWord = (s) => s.trimEnd().split(/\s+/).pop() || "";

function addPattern(english, translated) {
  const names = [];
  const literal = english.split(/\{([a-z0-9_]+)\}/i);
  const re = new RegExp(`^${literal.map((part, i) => {
    if (i % 2) { names.push(part); return "(.+?)"; }
    return escapeRe(part);
  }).join("")}$`, "s");
  const entry = { re, names, translated, weight: english.replace(/\{[a-z0-9_]+\}/gi, "").length };
  const head = literal[0];
  const tail = literal[literal.length - 1];
  // Indexed by a literal word at either end, so a text only tries a handful of patterns.
  if (head.trim()) (cat.byFirst.get(firstWord(head)) || cat.byFirst.set(firstWord(head), []).get(firstWord(head))).push(entry);
  else if (tail.trim()) (cat.byLast.get(lastWord(tail)) || cat.byLast.set(lastWord(tail), []).get(lastWord(tail))).push(entry);
}

/** Translate one text (English in, the reader's language out; unknown texts stay as they are). */
export function t(text, vars) {
  if (vars) text = text.replace(/\{([a-z0-9_]+)\}/gi, (m, k) => (k in vars ? String(vars[k]) : m));
  if (cat.code === "en" || !text) return text;
  return translateText(text) ?? text;
}

function translateText(text) {
  const core = text.trim();
  if (!core || !/[A-Za-z]/.test(core)) return null;
  const found = cat.exact.get(core);
  if (found !== undefined) return found === core ? null : text.replace(core, found);
  for (const entry of [...(cat.byFirst.get(firstWord(core)) || []), ...(cat.byLast.get(lastWord(core)) || [])]) {
    const m = entry.re.exec(core);
    if (!m) continue;
    const vals = Object.fromEntries(entry.names.map((n, i) => [n, m[i + 1]])); // names, numbers: kept as they are
    return text.replace(core, entry.translated.replace(/\{([a-z0-9_]+)\}/gi, (x, k) => (k in vals ? vals[k] : x)));
  }
  return null;
}

const skip = (el) => !el || el.closest?.('[translate="no"], script, style, code, pre, textarea, [contenteditable="true"]');

function translateNode(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    if (skip(node.parentElement)) return;
    const out = translateText(node.data);
    if (out != null && out !== node.data) node.data = out;
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE || skip(node)) return;
  translateAttrs(node);
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.nodeType === Node.ELEMENT_NODE && n.getAttribute("translate") === "no"
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) {
      if (["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE"].includes(n.parentElement?.tagName)) continue;
      const out = translateText(n.data);
      if (out != null && out !== n.data) n.data = out;
    } else translateAttrs(n);
  }
}

function translateAttrs(el) {
  for (const a of ATTRS) {
    const v = el.getAttribute(a);
    if (!v) continue;
    const out = translateText(v);
    if (out != null && out !== v) el.setAttribute(a, out);
  }
  if (el.tagName === "INPUT" && (el.type === "button" || el.type === "submit") && el.value) {
    const out = translateText(el.value);
    if (out != null) el.value = out;
  }
}

/** Load the reader's language and translate the page from now on. English: nothing to do. */
export async function startI18n() {
  const code = chosenLanguage() || browserLanguage();
  if (code === "en" || !LANGUAGES[code]) return;
  let data;
  try {
    const res = await fetch(`/static/i18n/${code}.json?v=1`);
    if (!res.ok) return;
    data = await res.json();
  } catch { return; } // no catalog: English it is
  cat.code = code;
  cat.words = data.words || {};
  for (const [english, translated] of Object.entries(data.strings || {})) {
    if (!translated) continue;
    if (/\{[a-z0-9_]+\}/i.test(english)) addPattern(english, translated);
    else cat.exact.set(english, translated);
  }
  // The most specific sentence first: "Nothing to change in {x}: their tags already say this." before
  // "Nothing to change in {x}.", which would otherwise swallow the rest as if it were a name.
  for (const bucket of [...cat.byFirst.values(), ...cat.byLast.values()]) bucket.sort((a, b) => b.weight - a.weight);
  document.documentElement.lang = code;
  // The few words the stylesheet draws itself (quick settings' On / Off).
  for (const [v, word] of [["--t-on", "On"], ["--t-off", "Off"]]) {
    document.documentElement.style.setProperty(v, JSON.stringify(cat.exact.get(word) || word));
  }
  translateNode(document.body);
  document.title = translateText(document.title) ?? document.title;
  cat.observer = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === "characterData") translateNode(r.target);
      else if (r.type === "attributes") { if (!skip(r.target)) translateAttrs(r.target); }
      else r.addedNodes.forEach(translateNode);
    }
  });
  cat.observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
}
