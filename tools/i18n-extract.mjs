// Lists the page's English texts (JS modules + index.html) for the translation catalogs.
//
//   npm install --no-save acorn   (once, anywhere on NODE_PATH)
//   node tools/i18n-extract.mjs > /tmp/page-strings.json
//
// Template literals become patterns: `Moved to “${name}”` -> "Moved to “{name}”".
// python tools/i18n.py merges this with the server's messages and updates the catalogs.
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(join(process.cwd(), "x.js"));
const acorn = require("acorn");
const STATIC = new URL("../src/codetta/web/static/", import.meta.url).pathname;
const out = new Map();

const looksLikeText = (s) => {
  const t = s.trim();
  if (!/[A-Za-z]{2}/.test(t)) return false;
  if (/^[a-z0-9_.:/#@-]+$/.test(t) && !/^[a-z]+$/.test(t)) return false; // ids, paths, classes, keys
  if (/^(\/|\.\/|#|\[|\.)/.test(t) || /^[a-z-]+:[a-z]/.test(t)) return false; // selectors, mime types
  if (/^[A-Z0-9_]+$/.test(t)) return false; // GET, POST, CONSTANT
  const bare = t.replace(/\{[a-z0-9_]+\}/gi, "X");
  if (/[{};]\s*$/.test(bare) && /[:{]/.test(bare)) return false; // css
  if (/^[a-z][a-z0-9-]*( [a-z][a-z0-9-]*)*$/.test(t) && /-/.test(t)) return false; // "btn primary-x" class lists
  if (/^(?:[a-z]+[A-Z][A-Za-z]*|[a-z]+)$/.test(t) && !/^(and|or|on|off|yes|no)$/.test(t)) return false; // camelCase / bare keys
  return /\s/.test(t) || /^[A-Z]/.test(t) || /[…?!.]$/.test(t);
};

const name = (src) => {
  const m = src.match(/([A-Za-z_$][\w$]*)\s*(?:\)|\]|\?\.|\.length)?\s*$/);
  return (m ? m[1] : "x").replace(/\$/g, "");
};

function add(text, file) {
  if (!looksLikeText(text)) return;
  const key = text.trim();
  if (!out.has(key)) out.set(key, new Set());
  out.get(key).add(file);
}

function walk(node, visit, parent) {
  if (!node || typeof node.type !== "string") return;
  visit(node, parent);
  for (const k of Object.keys(node)) {
    const v = node[k];
    if (Array.isArray(v)) v.forEach((c) => c && typeof c.type === "string" && walk(c, visit, node));
    else if (v && typeof v.type === "string") walk(v, visit, node);
  }
}

const SKIP_CALLS = new Set(["$", "$$", "querySelector", "querySelectorAll", "closest", "matches", "getElementById",
  "addEventListener", "removeEventListener", "getItem", "setItem", "removeItem", "api", "fetch", "createElement",
  "setAttribute", "getAttribute", "removeAttribute", "toggleAttribute", "startsWith", "endsWith", "includes", "split", "icon",
  "replace", "test", "match", "classList", "add", "remove", "toggle", "contains", "dispatchEvent", "Event", "CustomEvent"]);

for (const file of readdirSync(join(STATIC, "js")).filter((f) => f.endsWith(".js"))) {
  if (file === "i18n.js") continue;
  const src = readFileSync(join(STATIC, "js", file), "utf8");
  const ast = acorn.parse(src, { ecmaVersion: "latest", sourceType: "module" });
  walk(ast, (node, parent) => {
    if (parent?.type === "CallExpression" && parent.arguments[0] === node) {
      const callee = parent.callee.type === "MemberExpression" ? parent.callee.property.name : parent.callee.name;
      if (SKIP_CALLS.has(callee)) return;
    }
    if (parent?.type === "ImportDeclaration" || parent?.type === "ExportNamedDeclaration") return;
    if (parent?.type === "Property" && parent.key === node) return;
    if (parent?.type === "MemberExpression" && parent.property === node) return;
    if (parent?.type === "BinaryExpression" && ["===", "!==", "==", "!="].includes(parent.operator)) return;
    if (parent?.type === "SwitchCase") return;
    if (node.type === "Literal" && typeof node.value === "string") add(node.value, file);
    if (node.type === "TemplateLiteral") {
      let s = "";
      const seen = {};
      node.quasis.forEach((q, i) => {
        s += q.value.cooked;
        if (i < node.expressions.length) {
          const n = name(src.slice(node.expressions[i].start, node.expressions[i].end));
          seen[n] = (seen[n] || 0) + 1;
          s += `{${seen[n] === 1 ? n : n + seen[n]}}`;
        }
      });
      // A template that's only placeholders and punctuation isn't text of its own.
      if (s.replace(/\{[^}]+\}/g, "").match(/[A-Za-z]{2}/)) add(s, file);
    }
  });
}

// index.html: text between tags and the translatable attributes.
const html = readFileSync(join(STATIC, "index.html"), "utf8").replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>|<!--[\s\S]*?-->/g, "");
for (const m of html.matchAll(/>([^<>]+)</g)) {
  const text = m[1].replace(/\s+/g, " ").replace(/&amp;/g, "&").replace(/&rarr;/g, "→").replace(/&hellip;/g, "…");
  if (text.trim()) add(text, "index.html");
}
for (const m of html.matchAll(/\s(?:placeholder|title|aria-label|alt)="([^"]+)"/g)) add(m[1], "index.html");

const result = Object.fromEntries([...out].sort(([a], [b]) => a.localeCompare(b)).map(([k, files]) => [k, [...files].sort()]));
process.stdout.write(JSON.stringify(result, null, 1));
