import sys
from playwright.sync_api import sync_playwright
H = sys.argv[1]
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--allow-file-access-from-files"])
    for theme in ("light", "dark"):
        p = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        p.goto(f"file://{H}/hero.html#{theme}"); p.wait_for_selector("body[data-ready]"); p.wait_for_timeout(800)
        p.screenshot(path=f"{H}/hero-{theme}.png"); print("saved", theme)
    b.close()
