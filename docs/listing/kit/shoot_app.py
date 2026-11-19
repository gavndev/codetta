"""Fresh listing screenshots from the demo library (server on :8118, account alex)."""
import sys
from playwright.sync_api import sync_playwright
URL = "http://localhost:8118"; OUT = sys.argv[1]
ALBUM = "/#/Frank%20Ocean/Blond%20(2016)"
DARK = "/#/Radiohead/In%20Rainbows%20(2007)"
PHONE = "/#/OsamaSon/psykotic%20(2025)"

def page(b, theme, phone=False):
    ctx = b.new_context(**({"viewport": {"width": 390, "height": 844}, "device_scale_factor": 3, "is_mobile": True, "has_touch": True}
                         if phone else {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 2}),
                        color_scheme=theme)
    ctx.add_init_script(f"try{{localStorage.setItem('codetta-seen-version','0.8.1');localStorage.setItem('codetta-theme','{theme}')}}catch(e){{}}")
    p = ctx.new_page()
    p.on("console", lambda m: print("console:", m.text) if m.type == "error" else None)
    p.goto(URL); p.fill("#auth-user", "alex"); p.fill("#auth-pass", "correct horse 1"); p.click("#auth-submit")
    p.wait_for_timeout(1500); p.keyboard.press("Escape"); p.wait_for_timeout(300)
    return p

def go(p, hash_, wait=1500):
    p.goto(URL + hash_); p.wait_for_timeout(wait)

def shot(p, name):
    p.mouse.move(0, 0) if not name.startswith("phone") else None
    p.wait_for_timeout(700); p.screenshot(path=f"{OUT}/{name}.png"); print("saved", name)

with sync_playwright() as pw:
    b = pw.chromium.launch()
    # sign-in
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme="light")
    sp = ctx.new_page(); sp.goto(URL); sp.wait_for_timeout(1200); shot(sp, "sign-in"); ctx.close()
    for theme in ("light", "dark"):
        p = page(b, theme)
        go(p, "/#/", 3500); p.click("button[title=List]"); p.wait_for_timeout(800); shot(p, f"library-{theme}")
        if theme == "light":
            p.click("text=Library health"); p.wait_for_timeout(4000); shot(p, "health"); p.keyboard.press("Escape"); p.wait_for_timeout(500)
        go(p, ALBUM if theme == "light" else DARK); shot(p, f"album-{theme}")
        p.click("#tracks .track-row:not(.head) >> nth=2"); p.wait_for_timeout(1200); shot(p, f"editor-{theme}")
        if theme == "light":
            p.keyboard.press("Escape"); p.wait_for_timeout(400)
            p.fill("#filter", "genre: ambient"); p.press("#filter", "Enter"); p.wait_for_timeout(1800); shot(p, "search")
            go(p, "/#/Downloads")
            p.click("button[aria-label=Actions] >> visible=true"); p.wait_for_timeout(1000)
            p.click("#actions-dialog .act-item >> nth=0"); p.wait_for_timeout(1500); shot(p, "actions")
        p.context.close()
    p = page(b, "light", phone=True)
    go(p, PHONE); shot(p, "phone-album")
    p.click("#tracks .track-row:not(.head) >> nth=2"); p.wait_for_timeout(1200); shot(p, "phone-editor")
    b.close()
