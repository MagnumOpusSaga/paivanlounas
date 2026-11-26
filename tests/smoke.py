"""Smoke test run on every build BEFORE deploy (fails the workflow = the old site stays live).
Checks what has broken before: JS errors, empty map band, sheet/cards on phones, lists, venue pages, data volume.
Usage: python tests/smoke.py dist"""
import functools, http.server, json, os, sys, threading, datetime
from playwright.sync_api import sync_playwright

DIST = sys.argv[1] if len(sys.argv) > 1 else "dist"
fails = []


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg, flush=True)
    if not ok:
        fails.append(msg)


# 1. data volume: never publish a day that lost most lists
wk = json.load(open(f"{DIST}/data/week.json"))
day = wk["date"]
n_today = sum(1 for v in wk["venues"] if (v.get("ms") or {}).get(day))
per_day = {}
for v in wk["venues"]:
    for d in (v.get("ms") or {}):
        per_day[d] = per_day.get(d, 0) + 1
best = max(per_day.values() or [0])
# a holiday can legitimately be thin, so this only warns (shows in the run summary), it does not block the deploy
if n_today < best * 0.6:
    print(f"::warning::only {n_today} menus for {day} (best day this week {best}) - check the fetchers")
print(f"info menus today {n_today}, best day this week {best}")
venue = next((v["i"] for v in wk["venues"] if (v.get("ms") or {}).get(day)), None)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8799), functools.partial(Quiet, directory=DIST))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:8799"

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])

    def page(**kw):
        c = b.new_context(**kw)
        pg = c.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for pat in ("**/cloudflareinsights.com/**", "**/api/e", "**/api/like", "**/googlesyndication.com/**"):
            pg.route(pat, lambda r: r.abort())
        return pg, errs

    # 2. phone front page: map fills the screen under the header, sheet with lists, cards open
    pg, errs = page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                    geolocation={"latitude": 60.1699, "longitude": 24.9384}, permissions=["geolocation"])
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(7000)
    g = pg.evaluate("""()=>{const m=document.getElementById('map').getBoundingClientRect(),h=document.querySelector('.top').getBoundingClientRect();
      const c=document.querySelector('.maplibregl-canvas'),cr=c?c.getBoundingClientRect():null;
      return {mt:m.top,mb:m.bottom,hb:h.bottom,vh:innerHeight,ct:cr&&cr.top,cb:cr&&cr.bottom,
        sheet:getComputedStyle(document.getElementById('sheet')).display,title:document.getElementById('shTitle').textContent,
        rows:document.querySelectorAll('#shRows li').length,pins:document.querySelectorAll('.pin').length,scroll:document.scrollingElement.scrollHeight}}""")
    check(abs(g["mt"] - g["hb"]) <= 2 and g["mb"] >= g["vh"] - 2, f"phone map fills screen under header (top {g['mt']:.0f}/{g['hb']:.0f}, bottom {g['mb']:.0f}/{g['vh']})")
    if g["ct"] is not None:
        check(abs(g["ct"] - g["mt"]) <= 2 and abs(g["cb"] - g["mb"]) <= 2, f"basemap canvas covers the map (no empty band) {g['ct']:.0f}-{g['cb']:.0f} vs {g['mt']:.0f}-{g['mb']:.0f}")
    check(g["sheet"] == "flex" and g["rows"] >= 1 and "lounas" in g["title"], f"phone sheet shows lists ({g['title']!r}, rows {g['rows']})")
    check(g["pins"] >= 50, f"price pins on map: {g['pins']}")
    check(g["scroll"] <= g["vh"] + 2, f"phone page itself does not scroll (height {g['scroll']})")
    pg.screenshot(path="smoke-phone.png")
    pg.click("#grab"); pg.wait_for_timeout(900)
    pg.screenshot(path="smoke-phone-full.png")
    nc = pg.evaluate("document.querySelectorAll('.cards .card').length")
    check(pg.evaluate("document.querySelector('.app').classList.contains('sheetfull')") and nc >= 5, f"pulled-up sheet shows cards ({nc})")
    check(not errs, f"phone front page JS errors: {errs[:3]}")

    # 3. desktop front page: list next to the map
    pg, errs = page(viewport={"width": 1280, "height": 800})
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(5000)
    pg.screenshot(path="smoke-desktop.png")
    nl = pg.evaluate("document.querySelectorAll('.list>li').length")
    check(nl >= 20, f"desktop list rows {nl}")
    check(not errs, f"desktop JS errors: {errs[:3]}")

    # 4. a restaurant page with a menu, and the cheapest-lunch page
    for path in ([f"/ravintola/{venue}/"] if venue else []) + ["/halvin-lounas-helsinki/"]:
        pg, errs = page(viewport={"width": 390, "height": 844}, is_mobile=True)
        r = pg.goto(BASE + path, wait_until="domcontentloaded"); pg.wait_for_timeout(1500)
        txt = pg.inner_text("main") if pg.query_selector("main") else ""
        check(r and r.status == 200 and len(txt) > 200 and not errs, f"{path} renders ({r.status if r else '-'}, {len(txt)} chars, errors {errs[:2]})")
    b.close()

srv.shutdown()
print(f"\n{len(fails)} failed" if fails else "\nall smoke checks passed")
sys.exit(1 if fails else 0)
