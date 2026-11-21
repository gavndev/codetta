"""The page's JavaScript modules fit together: every import points at a real module and a
name it really exports. (A browser stops the whole page on a broken import.)"""
import re
from pathlib import Path

STATIC = Path(__file__).parent.parent / "src" / "codetta" / "web" / "static"
MODULES = [STATIC / "app.js", *sorted((STATIC / "js").glob("*.js"))]
IMPORT = re.compile(r'^import \{([^}]*)\} from "(\./[^"]+)";', re.MULTILINE)
EXPORT = re.compile(r"^export (?:async )?(?:function\*? |class |const |let |var )([A-Za-z_$][\w$]*)", re.MULTILINE)
EXPORT_PATTERN = re.compile(r"^export (?:const|let|var) \{([^}]*)\}", re.MULTILINE)


def exports_of(path: Path) -> set[str]:
    text = path.read_text("utf-8")
    names = set(EXPORT.findall(text))
    # `export const a = 1, b = 2;` and `export const { a, b } = ...`
    for m in re.finditer(r"^export (?:const|let|var) (.+?);\s*$", text, re.MULTILINE | re.DOTALL):
        names |= set(re.findall(r"(?:^|,)\s*([A-Za-z_$][\w$]*)\s*=", m.group(1)))
    for m in EXPORT_PATTERN.finditer(text):
        names |= {n.split(":")[-1].strip() for n in m.group(1).split(",") if n.strip()}
    return names


def test_the_page_loads_app_js_as_a_module():
    html = (STATIC / "index.html").read_text("utf-8")
    assert re.search(r'<script src="/static/app\.js\?v=\d+" type="module"></script>', html)


def test_every_import_names_something_its_module_exports():
    assert len(MODULES) > 10
    for mod in MODULES:
        for names, target in IMPORT.findall(mod.read_text("utf-8")):
            dep = (mod.parent / target).resolve()
            assert dep.is_file(), f"{mod.name} imports {target}, which doesn't exist"
            missing = {n.split(" as ")[0].strip() for n in names.split(",") if n.strip()} - exports_of(dep)
            assert not missing, f"{mod.name} imports {sorted(missing)} from {target}, which doesn't export them"


def test_modules_only_import_from_codetta_itself():
    for mod in MODULES:
        for stmt in re.findall(r"^import [^;]*;", mod.read_text("utf-8"), re.MULTILINE):
            assert re.search(r'from "\./[\w/.-]+\.js";$', stmt), f"{mod.name}: {stmt}"


def test_the_page_knows_the_servers_import_limit():
    """The page skips files over the limit up front (a browser can't show the server's answer
    once it has stopped reading an upload), so both sides must agree on the number."""
    from codetta.core.importer import MAX_IMPORT_BYTES
    js = (STATIC / "js" / "files.js").read_text("utf-8")
    m = re.search(r"const MAX_IMPORT_BYTES = (\d+) \* 1024 \*\* 3;", js)
    assert m and int(m.group(1)) * 1024 ** 3 == MAX_IMPORT_BYTES


def test_every_module_is_preloaded():
    """The page asks for every module up front (no waterfall of imports); the links must match
    the import addresses exactly, or the browser would fetch each module twice."""
    html = (STATIC / "index.html").read_text("utf-8")
    preloaded = set(re.findall(r'<link rel="modulepreload" href="/static/js/([\w-]+\.js)">', html))
    assert preloaded == {p.name for p in (STATIC / "js").glob("*.js")}
