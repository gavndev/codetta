"""Twelve original album covers for invented artists, drawn in SVG/CSS and rendered to 640px images.

Run from this folder: uv run --with playwright --with pillow python make_covers.py .
Every cover is authored here (no photos, no generated imagery, no real artwork)."""
import math
import random
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
FONT = str((Path(__file__).resolve().parent.parent / "fonts" / "schibsted-grotesk.woff2"))
rnd = random.Random(7)

GRAIN = """<svg class="grain" viewBox="0 0 640 640"><filter id="g{n}"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/>
<feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .55 0"/></filter><rect width="640" height="640" filter="url(#g{n})"/></svg>"""


def contours(n=14, seed=3, color="#1f3b2d"):
    r = random.Random(seed)
    paths = []
    cx, cy = 300 + r.randint(-60, 60), 330 + r.randint(-60, 60)
    for i in range(n):
        rad = 30 + i * 26
        pts = []
        for k in range(0, 73):
            a = k / 72 * 2 * math.pi
            wob = 1 + 0.12 * math.sin(3 * a + i * 0.5) + 0.07 * math.sin(5 * a + i)
            pts.append((cx + math.cos(a) * rad * wob * 1.15, cy + math.sin(a) * rad * wob))
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z"
        paths.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{2.2 if i % 4 == 0 else 1.1}"/>')
    return "".join(paths)


def waves(rows=22, a="#1c2c4c", b="#e8d3a7"):
    out = []
    for i in range(rows):
        y = 40 + i * 27
        amp = 6 + 10 * math.sin(i / 3)
        d = f"M-10,{y} " + " ".join(f"Q{x + 40},{y - amp} {x + 80},{y} T{x + 160},{y}" for x in range(-10, 640, 160))
        out.append(f'<path d="{d}" fill="none" stroke="{a if i % 2 else b}" stroke-width="{7 if i % 3 == 0 else 3}"/>')
    return "".join(out)


def orbits():
    out = []
    for i, r in enumerate([70, 120, 175, 235, 300]):
        out.append(f'<ellipse cx="320" cy="340" rx="{r * 1.25}" ry="{r * 0.62}" fill="none" stroke="#f3ead8" stroke-opacity=".55" stroke-width="1.6" stroke-dasharray="2 9" transform="rotate(-18 320 340)"/>')
    for k, (r, a) in enumerate([(120, 0.6), (175, 2.4), (235, 4.1), (300, 5.4), (70, 3.3)]):
        x = 320 + math.cos(a) * r * 1.25
        y = 340 + math.sin(a) * r * 0.62
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{6 + k * 2}" fill="#f3ead8" transform="rotate(-18 320 340)"/>')
    return "".join(out)


def halftone(color="#111", step=18):
    out = []
    for y in range(0, 660, step):
        for x in range(0, 660, step):
            t = (x + y) / 1280
            r = max(0.4, step * 0.48 * max(0.0, 1 - t) ** 1.4)
            off = step / 2 if (y // step) % 2 else 0
            out.append(f'<circle cx="{x + off}" cy="{y}" r="{r:.1f}" fill="{color}"/>')
    return "".join(out)


def grid_squares():
    out = []
    greys = ["#d9d6d0", "#c9c5be", "#b8b3ab", "#e6e3de"]
    s, g = 118, 22
    for i in range(4):
        for j in range(4):
            fill = "#c8372d" if (i, j) == (2, 1) else greys[(i * 3 + j) % 4]
            out.append(f'<rect x="{58 + j * (s + g)}" y="{58 + i * (s + g)}" width="{s}" height="{s}" fill="{fill}"/>')
    return "".join(out)


COVERS = [
    ("low-orbit", "Low Orbit", "Maren Holt", "2019", f"""
      <div class="c" style="background:linear-gradient(#2a1b3d 0%,#5c2a4d 48%,#e2734a 100%)">
        <svg viewBox="0 0 640 640"><defs><linearGradient id="sun" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd27a"/><stop offset="1" stop-color="#f06a3d"/></linearGradient>
        <clipPath id="bands">{''.join(f'<rect x="0" y="{170 + i * 34}" width="640" height="{34 - min(i, 6) * 4}"/>' for i in range(12))}</clipPath></defs>
        <circle cx="320" cy="330" r="190" fill="url(#sun)" clip-path="url(#bands)"/>
        <rect x="0" y="520" width="640" height="120" fill="#1b1230" opacity=".85"/></svg>
        <div class="t tl" style="color:#ffe8c7">maren holt<br><b>low orbit</b></div>{GRAIN.format(n=1)}</div>"""),
    ("midnight-tapes", "Midnight Tapes", "Nightfall Collective", "2024", f"""
      <div class="c" style="background:#efe7da">
        <svg viewBox="0 0 640 640" style="mix-blend-mode:multiply"><circle cx="270" cy="300" r="190" fill="#ff5d8f" opacity=".9"/><circle cx="370" cy="350" r="190" fill="#3b6fe0" opacity=".85" style="mix-blend-mode:multiply"/></svg>
        <div class="t bl" style="color:#1b1e24"><b>MIDNIGHT TAPES</b><br>nightfall collective · side a</div>{GRAIN.format(n=2)}</div>"""),
    ("glass-garden", "Glass Garden", "Marisol Vega", "2025", """
      <div class="c" style="background:#f2ebe0"><svg viewBox="0 0 640 640">
        <path d="M40 40 h280 v280 a280 280 0 0 1 -280 -280z" fill="#1d7c74"/><path d="M600 40 v280 h-280 a280 280 0 0 1 280 -280z" fill="#f2a541"/>
        <path d="M40 600 v-280 h280 a280 280 0 0 1 -280 280z" fill="#e4572e"/><circle cx="460" cy="460" r="140" fill="#1b1e24"/><circle cx="460" cy="460" r="52" fill="#f2ebe0"/></svg>
        </div>"""),
    ("northern-signal", "Northern Signal", "Kōsei Mori", "2021", """
      <div class="c" style="background:#f4f3ef"><div class="big" style="color:#121212">NS</div>
        <div style="position:absolute;left:44px;right:44px;top:452px;height:9px;background:#d7261e"></div>
        <div class="t" style="left:44px;bottom:40px;color:#121212;font-size:22px"><b>Northern Signal</b><br>Kōsei Mori&nbsp;&nbsp;2021</div></div>"""),
    ("slow-bloom", "Slow Bloom", "The Quiet Hours", "2022", f"""
      <div class="c" style="background:#f6e3dc"><div class="blob" style="left:120px;top:110px;width:330px;height:330px;background:#f59fb0"></div>
        <div class="blob" style="left:250px;top:220px;width:300px;height:300px;background:#c7a3f0"></div><div class="blob" style="left:180px;top:280px;width:220px;height:220px;background:#ffc98b"></div>
        <div class="t tl" style="color:#5a3a52">the quiet hours</div>{GRAIN.format(n=5)}</div>"""),
    ("paper-satellites", "Paper Satellites", "Aurora Lane", "2023", f"""
      <div class="c" style="background:radial-gradient(circle at 40% 45%,#22336b,#0d1430 70%)"><svg viewBox="0 0 640 640">{orbits()}</svg>
        <div class="t bl" style="color:#f3ead8">aurora lane<br><b>paper satellites</b></div>{GRAIN.format(n=6)}</div>"""),
    ("sunday-static", "Sunday Static", "Juno Park", "2024", f"""
      <div class="c" style="background:#f7d23e"><svg viewBox="0 0 640 640">{halftone()}</svg>
        <div class="t br" style="color:#111;background:#f7d23e;padding:6px 10px"><b>SUNDAY STATIC</b></div></div>"""),
    ("low-tide", "Low Tide", "Harbor Lights", "2020", f"""
      <div class="c" style="background:#2b3f63"><svg viewBox="0 0 640 640">{waves()}</svg>
        <div class="t tl" style="color:#f1e4c3;background:#2b3f63;padding:4px 8px">harbor lights · low tide ep</div></div>"""),
    ("coastline", "Coastline", "Mira Sol", "2023", f"""
      <div class="c" style="background:linear-gradient(#9fd3e0 0%,#4f9fb8 46%,#e9dcc0 46.5%,#d8c49b 100%)">
        <div style="position:absolute;left:0;right:0;top:282px;height:22px;background:linear-gradient(#ffffffaa,transparent)"></div>
        <div class="huge" style="color:#ffffff">coast<br>line</div>{GRAIN.format(n=9)}</div>"""),
    ("fieldwork", "Fieldwork", "Ines Calder", "2018", f"""
      <div class="c" style="background:#ece6d6"><svg viewBox="0 0 640 640">{contours()}</svg>
        <div class="t br" style="color:#1f3b2d"><b>fieldwork</b><br>ines calder</div></div>"""),
    ("afterhours", "Afterhours", "Theo Lindqvist", "2022", f"""
      <div class="c" style="background:#f1efea"><svg viewBox="0 0 640 640">{grid_squares()}</svg></div>"""),
    ("ferry-lights", "Ferry Lights", "Oda Saar", "2017", f"""
      <div class="c" style="background:#0c0f14"><div style="position:absolute;left:300px;top:60px;width:10px;height:520px;background:linear-gradient(transparent,#ffd9a0,#ff8c42 60%,transparent);filter:blur(3px)"></div>
        <div style="position:absolute;left:260px;top:60px;width:90px;height:520px;background:linear-gradient(transparent,#ff8c4233,transparent);filter:blur(18px)"></div>
        <div class="t bl" style="color:#cfd3da">oda saar — ferry lights</div>{GRAIN.format(n=12)}</div>"""),
]

CSS = f"""@font-face{{font-family:S;src:url(file://{FONT}) format("woff2");font-weight:400 900}}
*{{margin:0;box-sizing:border-box}} body{{background:#888;font-family:S,sans-serif}}
.c{{position:relative;width:640px;height:640px;overflow:hidden}} .c>svg{{position:absolute;inset:0;width:640px;height:640px}}
.grain{{position:absolute;inset:0;width:640px;height:640px;mix-blend-mode:overlay;opacity:.5}}
.t{{position:absolute;font-size:19px;line-height:1.25;letter-spacing:.01em}} .t b{{font-weight:800}}
.tl{{left:38px;top:34px}} .bl{{left:38px;bottom:36px}} .br{{right:38px;bottom:36px;text-align:right}}
.big{{position:absolute;left:30px;top:30px;font-size:430px;font-weight:900;letter-spacing:-.07em;line-height:.85}}
.huge{{position:absolute;left:36px;bottom:30px;font-size:150px;font-weight:900;letter-spacing:-.06em;line-height:.82}}
.blob{{position:absolute;border-radius:50%;filter:blur(38px);opacity:.9;mix-blend-mode:multiply}}"""

html = f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body>" + "".join(
    f'<div id="{slug}" style="margin:10px">{body}</div>' for slug, _, _, _, body in COVERS) + "</body></html>"
(OUT / "covers.html").write_text(html)

from playwright.sync_api import sync_playwright  # noqa: E402
from PIL import Image  # noqa: E402

with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 700, "height": 800}, device_scale_factor=1)
    p.goto((OUT / "covers.html").as_uri())
    p.wait_for_timeout(800)
    for slug, *_ in COVERS:
        png = OUT / f"{slug}.png"
        p.locator(f"#{slug} .c").screenshot(path=str(png))
        Image.open(png).convert("RGB").save(OUT / f"{slug}.webp", "WEBP", quality=84, method=6)
        png.unlink()
    b.close()
import json  # noqa: E402
(Path("/dev/null") if OUT == Path(".") else OUT / "albums.json").write_text(json.dumps([{"slug": s, "title": t, "artist": a, "year": y} for s, t, a, y, _ in COVERS], ensure_ascii=False, indent=1))
print("covers:", len(COVERS))
