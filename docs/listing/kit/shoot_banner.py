import sys
from playwright.sync_api import sync_playwright
H, OUT = sys.argv[1], sys.argv[2]
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--allow-file-access-from-files"])
    p = b.new_page(viewport={"width": 1920, "height": 640}, device_scale_factor=1)
    p.goto(f"file://{H}/banner.html#light"); p.wait_for_selector("body[data-ready]"); p.wait_for_timeout(800)
    p.screenshot(path=f"{OUT}/banner.png"); b.close()
