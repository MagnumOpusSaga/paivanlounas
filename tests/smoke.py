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

# 1b. dish-name cleaning must stay fast for every text (a backtracking regex froze the page for 18-48 s on 26.11.)
import re as _re, subprocess, time as _time
texts = [x for v in wk["venues"] for m in (v.get("ms") or {}).values() if m for i in m.get("items", []) for x in i.get("d", [])]
js = open(f"{DIST}/app.js").read()
mjs = _re.search(r"(?:function decapJs[^\n]*\n\s*)?function clean\(d\) \{.*?\n", js)
if mjs:
    json.dump(texts, open("/tmp/_smoke_texts.json", "w"))
    node = ("const t=require('/tmp/_smoke_texts.json');" + mjs.group(0) +
            ";const a=Date.now();t.forEach(clean);console.log(Date.now()-a)")
    try:
        ms = int(subprocess.run(["node", "-e", node], capture_output=True, text=True, timeout=60).stdout.strip() or 99999)
    except subprocess.TimeoutExpired:
        ms = 99999
    check(ms < 1000, f"app.js clean() on {len(texts)} dish texts: {ms} ms (< 1000)")
else:
    check(False, "app.js clean() not found")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build"))
try:
    import importlib.util as _iu
    _sp = _iu.spec_from_file_location("_bs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "build_site.py"))
    _bs = _iu.module_from_spec(_sp); _sp.loader.exec_module(_bs)
    _a = _time.time(); [_bs.clean_dish(x) for x in texts]; _ms = int((_time.time() - _a) * 1000)
    check(_ms < 1000, f"build clean_dish() on {len(texts)} dish texts: {_ms} ms (< 1000)")
except Exception as e:
    print("info clean_dish timing skipped:", e)

# 1c. N46 lunch facts box: only on pages without today's list, always with the source link (never an unsourced claim)
import glob as _glob
_boxes = _bad = 0
for _f in _glob.glob(f"{DIST}/ravintola/*/index.html"):
    _h = open(_f, encoding="utf-8").read()
    if 'class="lunchinfo"' in _h:
        _boxes += 1
        _box = _h.split('class="lunchinfo"', 1)[1].split("</section>", 1)[0]
        if 'class="nomenu"' not in _h or not _re.search(r'class="li-src">[^<]*<a href="https?://', _box) or 'class="li-main"></p>' in _box:
            _bad += 1
print(f"info lunch facts boxes (N46): {_boxes}")
check(_bad == 0, f"lunch facts boxes only on pages without today's list and always with a source link ({_bad} bad)")

# 1f. a new city's pages stay out of search engines until Branu opens the city (LOUNAS_INDEX_CITIES; spam rule)
_open = set((os.environ.get("LOUNAS_INDEX_CITIES") or "helsinki").split(","))
for _c in ("espoo",):
    _pth = os.path.join(DIST, "lounas", _c, "index.html")
    if os.path.exists(_pth) and _c not in _open and os.environ.get("LOUNAS_GATE") == "1":
        check('content="noindex' in open(_pth).read(), f"{_c}: city page is noindex until the city is opened")
        check(f"/lounas/{_c}/" not in open(os.path.join(DIST, "sitemap.xml")).read(), f"{_c}: city page not in the sitemap yet")

# 1g. the postal code decides the city (Branu 27.11.): Ravilla, Valjakkotie 1, 00370 Helsinki sits just across the border
_rv = os.path.join(DIST, "ravintola", "lounasravintola-ravilla", "index.html")
if os.path.exists(_rv):
    _t = open(_rv).read()
    check(", Helsinki</p>" in _t and "/lounas/leppavaara/" not in _t, "Helsinki address (00370) is shown in Helsinki, not under an Espoo area")

# 1d. a site that does not open in a later run keeps this week's list (27.11.: 336 lists at 05.30, 288 at 09.50)
import tempfile as _tf
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))
    import ai_reader as _ar
    _wk = ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27"]
    _ar.call = lambda text, name, week, blocks=None: ({"belongs": True, "stale": False, "fixed": [], "days": {d: [{"dish": "Lohikeitto " + name, "price": 12.5}] for d in week}}, {})
    _old_key = os.environ.get("ANTHROPIC_API_KEY"); os.environ["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY") or "test"
    with _tf.TemporaryDirectory() as _td:
        _pg = {k: {"name": k, "website": f"https://{k}.fi", "pages": [{"url": f"https://{k}.fi/", "text": "Lounas " + k}], "pdfs": [], "imgs": []} for k in ("a", "b")}
        json.dump(_pg, open(f"{_td}/web_pages.json", "w"))
        _ar.main(f"{_td}/web_pages.json", ",".join(_wk), f"{_td}/menus_ai_{{day}}.json")
        del _pg["b"]; json.dump(_pg, open(f"{_td}/web_pages.json", "w"))
        _ar.main(f"{_td}/web_pages.json", ",".join(_wk), f"{_td}/menus_ai_{{day}}.json")
        _ids = sorted(r["id"] for r in json.load(open(f"{_td}/menus_ai_2026-11-27.json"))["results"])
    if _old_key is None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    check(_ids == ["a", "b"], f"AI reader keeps this week's list when a site does not open later ({_ids})")
    # page text only gives "Lounasbuffet 13,50 €", the dishes are in the week's PDF → the PDF is read (27.11.: Kuusenkerkkä)
    os.environ["ANTHROPIC_API_KEY"] = _old_key or "test"
    _ar.media_blocks = lambda v: ([{"type": "document"}], ["pdf1"]) if v.get("pdfs") else ([], [])
    _ar.call = lambda text, name, week, blocks=None: (({"belongs": True, "stale": False, "fixed": [], "days": {d: [{"dish": "Hernekeitto", "price": None}] for d in week}})
                                                     if blocks else {"belongs": True, "stale": False, "fixed": [{"dish": "Lounasbuffet", "price": 13.5}], "days": {}}, {})
    with _tf.TemporaryDirectory() as _td:
        json.dump({"k": {"name": "Kerkka", "website": "https://k.fi", "pages": [{"url": "https://k.fi/", "text": "Lounasbuffet 13,5 €"}],
                         "pdfs": ["https://k.fi/VIIKKO-48.pdf"], "imgs": []}}, open(f"{_td}/web_pages.json", "w"))
        _ar.main(f"{_td}/web_pages.json", ",".join(_wk), f"{_td}/menus_ai_{{day}}.json")
        _it = json.load(open(f"{_td}/menus_ai_2026-11-27.json"))["results"][0]["items"]
    if _old_key is None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    check(_it and "Hernekeitto" in json.dumps(_it, ensure_ascii=False) and "13.5" in json.dumps(_it),
          f"week PDF read when the page only names a buffet; buffet price kept ({json.dumps(_it, ensure_ascii=False)[:120]})")
except Exception as e:
    check(False, f"AI reader carry-over test crashed: {e}")

# 1e. own-site reader: a site that fails or shows a bot check in a later run keeps what was read earlier this week
# (27.11.: Ilo Konala was read fine at one run and lost at the next – the place vanished from the app)
try:
    import fetch_independent as _fi
    _seq = {"n": 0}
    _ok_html = ("<html><body><h1>Lounas</h1><p>Lounaslista</p><h2>Perjantai 27.11.</h2><p>Lohikeitto L,G</p><p>Broilerikastike ja riisi L</p>"
                "<p>Kasvispata L</p><p>Lounas 13,50 €</p></body></html>").encode()
    _bot = b"<html><body>One moment, please... Please wait while your request is being verified...</body></html>"
    def _fake(url, maxb=2_500_000, tries=3):
        if _seq["n"] == 0:
            return url, "text/html", _ok_html
        return url, "error:BotCheck", b""
    _fi.fetch = _fake
    with _tf.TemporaryDirectory() as _td:
        json.dump([{"id": "x", "name": "Testi", "website": "https://testi.fi/"}], open(f"{_td}/todo.json", "w"))
        _fi.main(f"{_td}/todo.json", "2026-11-23,2026-11-24,2026-11-25,2026-11-26,2026-11-27", f"{_td}/m_{{day}}.json")
        _first = json.load(open(f"{_td}/m_2026-11-27.json"))["results"][0]["status"]
        _seq["n"] = 1
        _fi.main(f"{_td}/todo.json", "2026-11-23,2026-11-24,2026-11-25,2026-11-26,2026-11-27", f"{_td}/m_{{day}}.json")
        _r = json.load(open(f"{_td}/m_2026-11-27.json"))["results"][0]
        _wp = json.load(open(f"{_td}/web_pages.json"))
    check(_first in ("ok_daily", "ok_fixed") and _r["status"] == _first and _r.get("carried") and "x" in _wp,
          f"own-site reader keeps this week's reading when the site fails later ({_first} -> {_r['status']}, pages kept {'x' in _wp})")
    check(bool(_fi.CHALLENGE.search(_bot)), "bot-check page recognised (not read as 'no lunch')")
except Exception as e:
    check(False, f"own-site reader carry-over test crashed: {e}")

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
        check(g["ct"] <= g["mt"] + 2 and g["cb"] >= g["mb"] - 2, f"basemap canvas covers the map (no empty band) {g['ct']:.0f}-{g['cb']:.0f} vs {g['mt']:.0f}-{g['mb']:.0f}")
    check(g["sheet"] == "flex" and g["rows"] >= 1 and "lounas" in g["title"], f"phone sheet shows lists ({g['title']!r}, rows {g['rows']})")
    check(g["pins"] >= 20, f"price pins on map: {g['pins']}")
    check(g["scroll"] <= g["vh"] + 2, f"phone page itself does not scroll (height {g['scroll']})")
    me = pg.evaluate("""()=>{const d=[...document.querySelectorAll('path.leaflet-interactive')].find(p=>p.getAttribute('fill')==='#2563eb');
      if(!d)return null;const r=d.getBoundingClientRect(),q=document.getElementById('q2').getBoundingClientRect(),s=document.getElementById('sheet').getBoundingClientRect();
      return {y:Math.round(r.top+r.height/2),mid:Math.round((q.bottom+8+s.top)/2)}}""")
    if me:
        check(abs(me["y"] - me["mid"]) <= 30, f"phone: own location centred in the visible map (dot y {me['y']}, visible middle {me['mid']})")
    else:
        check(False, "phone: own location dot not shown")
    pg.screenshot(path="smoke-phone.png")
    pg.click("#grab"); pg.wait_for_timeout(900)
    pg.screenshot(path="smoke-phone-full.png")
    nc = pg.evaluate("document.querySelectorAll('.cards .card').length")
    check(pg.evaluate("document.querySelector('.app').classList.contains('sheetfull')") and nc >= 5, f"pulled-up sheet shows cards ({nc})")
    check(not errs, f"phone front page JS errors: {errs[:3]}")

    # phone in dark mode still gets the light page and map (feedback 27.11.: dark map hard to read outdoors)
    pg, errs = page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, color_scheme="dark")
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(3000)
    bg = pg.evaluate("getComputedStyle(document.body).backgroundColor")
    lum = sum(int(x) for x in bg[bg.find("(") + 1:bg.find(")")].split(",")[:3])
    check(lum > 600, f"phone in dark mode: page stays light (body {bg})")
    tb = pg.evaluate("(()=>{const r=document.getElementById('themebtn').getBoundingClientRect();return r.right<=innerWidth&&r.width>0})()")
    check(tb, "phone: dark/light button fully on screen")
    # small phone (360 px): header on one line, card texts inside their cards (feedback 27.11.: 'In English' and the
    # logo wrapped into two lines, long dish words like 'pippurikastikkeessa' ran past the card edge)
    pg, errs = page(viewport={"width": 360, "height": 740}, is_mobile=True, has_touch=True,
                    geolocation={"latitude": 60.1699, "longitude": 24.9384}, permissions=["geolocation"])
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(5000)
    hd = pg.evaluate("""()=>[...document.querySelectorAll('.top .logo,.top nav a')].map(a=>{const r=a.getBoundingClientRect(),
      lh=parseFloat(getComputedStyle(a).lineHeight)||parseFloat(getComputedStyle(a).fontSize)*1.4;return [a.textContent.trim(),Math.round(r.height),Math.round(lh),Math.round(r.right)]})""")
    bad = [h for h in hd if h[1] > max(h[2] * 1.5, 30) or h[3] > 360]
    check(not bad, f"360 px phone: header items on one line and on screen {bad or hd}")
    pg.click("#grab"); pg.wait_for_timeout(900)
    ov = pg.evaluate("""()=>{const o=[];document.querySelectorAll('.cards .card').forEach(c=>{const cr=c.getBoundingClientRect();
      c.querySelectorAll('.c1,.c2,.c3,.c4').forEach(e=>{if(e.scrollWidth>e.clientWidth+1||e.getBoundingClientRect().right>cr.right+1)o.push(e.textContent.slice(0,40))})});return o}""")
    check(not ov, f"360 px phone: card texts fit inside the cards {ov[:3]}")
    pg.screenshot(path="smoke-phone-360.png")
    check(not errs, f"360 px phone JS errors: {errs[:3]}")
    # a place without today's list is still found by its name (feedback 27.11.: searching a Konala place gave "0 lunches")
    _wk = json.load(open(os.path.join(DIST, "data", "week.json")))
    _nl = sorted(v["n"] for v in _wk["venues"] if not v.get("ms") and len(v["n"]) >= 8)
    if _nl:
        _name = _nl[len(_nl) // 2]
        pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(3000)
        pg.fill("#q2", _name); pg.wait_for_timeout(1000)
        _row = pg.evaluate("(()=>{const l=document.querySelector('#shRows li');return l?l.innerText:''})()")
        check(_name.lower() in _row.lower(), f"search finds a place without today's list by name ({_name!r} -> {_row[:60]!r})")
    # 3. desktop front page: list next to the map
    pg, errs = page(viewport={"width": 1280, "height": 800})
    pg.add_init_script("window.__lt=[];try{new PerformanceObserver(l=>l.getEntries().forEach(e=>window.__lt.push(Math.round(e.duration)))).observe({type:'longtask',buffered:true})}catch(e){}")
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(5000)
    for i in range(pg.evaluate("document.querySelectorAll('.days button').length")):
        pg.evaluate(f"document.querySelectorAll('.days button')[{i}].click()"); pg.wait_for_timeout(400)
    pg.wait_for_timeout(800)
    lt = pg.evaluate("window.__lt")
    check(max(lt or [0]) < 2000, f"desktop load + every day button: longest task {max(lt or [0])} ms (< 2000)")
    vis = pg.evaluate("(()=>{const b=document.getElementById('locfab');if(!b)return false;const r=b.getBoundingClientRect();return getComputedStyle(b).display!=='none'&&r.width>0&&r.height>0})()")
    check(not vis, "desktop: phone locate button hidden")
    mb = pg.evaluate("(()=>{const m=document.getElementById('map').getBoundingClientRect();return Math.round(innerHeight-m.bottom)})()")
    # feedback 27.11.: price pins must not pile on top of each other, and student restaurants are not among the three picks
    ov = pg.evaluate("""()=>{const r=[...document.querySelectorAll('.pin')].map(p=>p.getBoundingClientRect()).filter(b=>b.width&&b.bottom>0&&b.top<innerHeight);
      let n=0;for(let i=0;i<r.length;i++)for(let j=i+1;j<r.length;j++){const a=r[i],b=r[j];
        if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>a.width*0.5&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>a.height*0.5)n++}
      return {pins:r.length,overlap:n}}""")
    check(ov["overlap"] == 0, f"desktop: price pins do not pile up ({ov['pins']} pins, {ov['overlap']} overlapping pairs)")
    st3 = pg.evaluate("[...document.querySelectorAll('#top3 a')].filter(a=>/unicafe/i.test(a.textContent)).length")
    # no location given: one row of areas to pick from (feedback 27.11.); picking one is remembered
    ar = pg.evaluate("(()=>{const e=document.getElementById('areas');return e&&!e.hidden?e.querySelectorAll('[data-area]').length:0})()")
    check(ar >= 5, f"desktop without location: area picker shows {ar} areas")
    if ar:
        pg.click("#areas [data-area]"); pg.wait_for_timeout(800)
        check(bool(pg.evaluate("localStorage.getItem('pl_area')")), "desktop: picked area is remembered")
    check(st3 == 0, f"desktop: no student restaurant among the three picks ({st3})")
    print(f"info desktop gap under map {mb} px")
    pg.screenshot(path="smoke-desktop.png")
    nl = pg.evaluate("document.querySelectorAll('.list>li').length")
    check(nl >= 20, f"desktop list rows {nl}")
    # N45 (27.11.): "Näytä lisää (-30)" showed with 0 or few hits (CSS overrode [hidden]) and 0 hits had no message
    MORE = """(()=>{const b=document.getElementById('more');const v=getComputedStyle(b).display!=='none'&&b.offsetHeight>0;
      const e=document.querySelector('.list>li.empty');return {vis:v,txt:b.textContent,empty:e?e.innerText:'',clear:!!document.querySelector('.list [data-clear]')}})()"""
    bad = []
    for f in pg.evaluate("[...document.querySelectorAll('.chips button[data-f]')].map(b=>b.dataset.f)"):
        pg.click(f'.chips button[data-f="{f}"]'); pg.wait_for_timeout(250)
        m = pg.evaluate(MORE)
        if m["vis"] and ("-" in m["txt"] or "(0)" in m["txt"]):
            bad.append(f"{f}: {m['txt']}")
        pg.click(f'.chips button[data-f="{f}"]'); pg.wait_for_timeout(150)
    check(not bad, f"desktop: 'show more' never shows a zero/negative count {bad[:3]}")
    pg.fill("#q", "zzzzqx"); pg.wait_for_timeout(700)
    m = pg.evaluate(MORE)
    check(not m["vis"] and "Ei osumia" in m["empty"] and m["clear"], f"desktop: search with 0 hits shows a message + clear button and no 'show more' ({m})")
    pg.click(".list [data-clear]"); pg.wait_for_timeout(700)
    nl2 = pg.evaluate("document.querySelectorAll('.list>li[data-i]').length")
    check(nl2 >= 20 and pg.input_value("#q") == "", f"desktop: clear filters brings the list back ({nl2} rows)")
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
