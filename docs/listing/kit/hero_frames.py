import sys
from playwright.sync_api import sync_playwright
H, theme, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--allow-file-access-from-files"])
    p = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    p.goto(f"file://{H}/hero.html#{theme}-anim"); p.wait_for_selector("body[data-ready]"); p.wait_for_timeout(800)
    for i in range(n):
        p.evaluate(f"setT({i} * LOOP / {n})")
        p.screenshot(path=f"{H}/f-{theme}/{i:04d}.png")
    b.close()
