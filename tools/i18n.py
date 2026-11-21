"""Keep the translation catalogs (src/codetta/web/static/i18n/*.json) up to date.

    node tools/i18n-extract.mjs > /tmp/page.json      # the page's texts (needs acorn)
    python tools/i18n.py /tmp/page.json               # + the server's messages -> update catalogs

Every catalog gets every English text as a key. New texts come in empty ("") and are shown
in English until someone translates them; texts that no longer exist are dropped. Run with
--missing es to list what's left to translate in Spanish.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "codetta"
CATALOGS = SRC / "web" / "static" / "i18n"
SKIP_FILES = {"cli", "tests"}
SKIP_CALLS = {"debug", "info", "warning", "error", "exception", "critical", "getLogger", "compile", "match", "search",
              "sub", "split", "startswith", "endswith", "strftime", "strptime", "get", "pop", "setdefault", "getenv",
              "environ", "Query", "Field", "open", "encode", "decode", "join", "replace", "fullmatch", "findall"}


def sentence(s: str) -> bool:
    t = s.strip()
    if len(t) < 3 or not re.search(r"[A-Za-z]{2}", t) or t.startswith(("<", "/", "http", "%")):
        return False
    if "\n" in t and len(t) > 400:
        return False
    if not re.search(r"\s", t):
        return False  # single words are mostly keys; the page has its labels
    return bool(re.match(r"[A-Z“\"'(0-9]", t)) and not re.search(r"[{}]|\\[dws]|\$\(|SELECT |CREATE |PRAGMA ", t)


def fstring_key(node: ast.JoinedStr) -> str:
    out, seen = [], {}
    for v in node.values:
        if isinstance(v, ast.Constant):
            out.append(str(v.value))
        else:
            src = ast.unparse(v.value)
            m = re.search(r"([A-Za-z_]\w*)\W*$", src)
            n = m.group(1) if m else "x"
            seen[n] = seen.get(n, 0) + 1
            out.append("{" + (n if seen[n] == 1 else f"{n}{seen[n]}") + "}")
    return "".join(out)


def server_strings() -> dict[str, list[str]]:
    found: dict[str, set[str]] = {}
    for f in sorted(SRC.rglob("*.py")):
        if set(f.relative_to(SRC).parts) & SKIP_FILES:
            continue
        tree = ast.parse(f.read_text("utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        skipped: set[int] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                if name in SKIP_CALLS:
                    skipped.update(id(x) for a in n.args for x in ast.walk(a))
            if isinstance(n, ast.JoinedStr):
                skipped.update(id(v) for v in n.values)
        for n in ast.walk(tree):
            if id(n) in docs or id(n) in skipped:
                continue
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                key = n.value
            elif isinstance(n, ast.JoinedStr):
                key = fstring_key(n)
            else:
                continue
            key = key.strip()
            if sentence(re.sub(r"\{[^}]+\}", "x", key)):
                found.setdefault(key, set()).add(str(f.relative_to(SRC)))
    # Single-word labels the page shows from the server: the editor's fields, Library health's checks.
    sys.path.insert(0, str(ROOT / "src"))
    from codetta.core import connections, health, tagmap

    for f in tagmap.FIELDS:
        found.setdefault(f.label, set()).add("core/tagmap.py")
        found.setdefault(f.group, set()).add("core/tagmap.py")
    for label in [*health.CATEGORIES.values(), *(c.label for c in health.CHECKS)]:
        found.setdefault(label, set()).add("core/health.py")
    for word in ("On", "Off"):  # drawn by the stylesheet (quick settings), see js/i18n.js
        found.setdefault(word, set()).add("web/static/app.css")
    for c in connections.CONNECTIONS:
        found.setdefault(c.name, set()).add("core/connections.py")
    return {k: sorted(v) for k, v in found.items()}


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--missing":
        cat = json.loads((CATALOGS / f"{sys.argv[2]}.json").read_text("utf-8"))
        for k, v in cat["strings"].items():
            if not v:
                print(k)
        return
    page = json.loads(Path(sys.argv[1]).read_text("utf-8")) if len(sys.argv) > 1 else {}
    page = {k: v for k, v in page.items() if not k.startswith("<")}
    keys = sorted(set(page) | set(server_strings()))
    for path in sorted(CATALOGS.glob("*.json")):
        cat = json.loads(path.read_text("utf-8"))
        old = cat.get("strings", {})
        cat["strings"] = {k: old.get(k, "") for k in keys}
        path.write_text(json.dumps(cat, ensure_ascii=False, indent=1) + "\n", "utf-8")
        left = sum(1 for v in cat["strings"].values() if not v)
        print(f"{path.name}: {len(keys)} texts, {left} not translated yet")
    if not list(CATALOGS.glob("*.json")):
        print(f"{len(keys)} texts (no catalogs yet)")


if __name__ == "__main__":
    main()
