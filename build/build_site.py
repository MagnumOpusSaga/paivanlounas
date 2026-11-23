"""Build paivanlounas.fi (static, Cloudflare Pages) from the venue registry + today's menus.
Usage: build_site.py <lounas_dir> <out_dir> <YYYY-MM-DD> [--preview]"""
import json, re, sys, os, html, shutil, datetime, unicodedata, urllib.parse

SITE = "Päivän lounas"
DOMAIN = "https://paivanlounas.fi"
WD = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"]
DIETS = {"G": "G", "L": "L", "M": "M", "VL": "VL", "VEG": "Veg", "VE": "Veg", "V": "Veg", "VEGAN": "Veg", "K": "Kasvis"}


def slug(s):
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("ä", "a").replace("ö", "o").replace("å", "a"))
    s = re.sub(r"[^a-z0-9]+", "-", s.encode("ascii", "ignore").decode()).strip("-")
    return s or "x"


def esc(s):
    return html.escape(str(s or ""), quote=True)


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(ravintola|restaurant|oy|ab|cafe|café|kahvila|bistro|lounasravintola|the)\b", "", s)
    return re.sub(r"[^a-zåäö0-9]", "", s)


def diets_of(*texts):
    out = set()
    for t in texts:
        for tok in re.findall(r"\b(VEGAN|VEG|VE|VL|G|L|M|V|K)\b", (t or "").upper()):
            out.add(DIETS[tok])
    return sorted(out)


def point_in_poly(x, y, poly):
    inside = False
    for ring in poly:
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i][:2]; xj, yj = ring[j][:2]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
    return inside


def load_districts(path):
    out = []
    for f in json.load(open(path))["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        name = f["properties"]["nimi_fi"].title().replace("-", "-")
        out.append({"name": name, "slug": slug(name), "polys": polys})
    return out


def district_of(lat, lon, ds):
    if lat is None:
        return None
    for d in ds:
        if any(point_in_poly(lon, lat, p) for p in d["polys"]):
            return d
    return None


def menus_today(L, day):
    """Return {source_id: {items, source, url, kind}} from chain APIs, Raflaamo page and heuristic reader."""
    res = {}
    pc, pi = f"{L}/data/menus_chains_{day}.json", f"{L}/data/menus_independent_{day}.json"
    ch = json.load(open(pc))["results"] if os.path.exists(pc) else []
    comp = {c["id"]: c for c in json.load(open(f"{L}/data/compass.json"))}
    sod = {c["id"]: c for c in json.load(open(f"{L}/data/sodexo.json"))}
    uni = {c["id"]: c for c in json.load(open(f"{L}/data/unicafe.json"))}
    names = {"compass": "Compass Group", "sodexo": "Sodexo", "unicafe": "UniCafe"}
    for r in ch:
        if r["status"] != "ok":
            continue
        meta = comp.get(r["id"]) or sod.get(r["id"]) or uni.get(r["id"]) or {}
        items = []
        for it in r["items"]:
            dishes = [d for d in it["dishes"] if d]
            if not dishes:
                continue
            items.append({"t": it.get("title") or "", "d": dishes, "diet": sorted(set(diets_of(*it.get("diets", []), *dishes))),
                          "p": min(it["prices"]) if it.get("prices") else None})
        if items:
            res[r["id"]] = {"items": items, "src": names[r["source"]], "url": meta.get("url"), "conf": "api",
                            "hours": meta.get("lunch_today")}
    # independent sites read by the rule reader (precision ~93 % in manual check)
    ind = json.load(open(pi))["results"] if os.path.exists(pi) else []
    for r in ind:
        if r["status"] != "ok_daily" or "lounaat.info" in (r.get("url") or ""):
            continue
        lines = [l.strip(" •-–") for l in r["text"].split("\n") if l.strip(" •-–")]
        lines = [l for l in lines if 3 < len(l) <= 110 and not re.match(r"^(ti|ke|to|pe|tiistai|keskiviikko|torstai|perjantai)\b", l, re.I)
                 and not re.search(r"\b(klo|varaa|tilaa|joulu|tervetuloa|aukiolo)\b", l, re.I)][:12]
        food = [l for l in lines if FOOD.search(l)]
        if len(food) >= 2 and not FASTFOOD.search(r.get("name") or ""):
            lines = food
            ps = [float(p.replace(",", ".")) for p in re.findall(r"(\d{1,2}[,.]\d{2})\s*€", r["text"])]
            res[r["id"]] = {"items": [{"t": "", "d": lines, "diet": diets_of(*lines), "p": min(ps) if ps else None}],
                            "src": "ravintolan oma sivu", "url": r.get("url"), "conf": "web", "hours": None}
    # AI reader (Claude Haiku) – overrides the rule reader for the same site
    pa = f"{L}/data/menus_ai_{day}.json"
    for r in (json.load(open(pa))["results"] if os.path.exists(pa) else []):
        if FASTFOOD.search(r.get("url") or ""):
            continue
        res[r["id"]] = {"items": r["items"], "src": "ravintolan oma sivu", "url": r.get("url"), "conf": "ai", "hours": r.get("hours")}
    return res


def raflaamo_today(L):
    path = f"{L}/raw/raf_hki_parsed.json"
    if not os.path.exists(path):
        return {}
    out = {}
    for r in json.load(open(path)):
        it = r["items"]
        street = it[0].rstrip(",") if it else ""
        body = it[2:]
        ps = [float(x.replace(",", ".")) for x in re.findall(r"^(\d{1,2},\d{2}) €$", "\n".join(body), re.M)]
        dishes = [l for l in body if not re.match(r"^\d{1,2},\d{2} €$", l) and len(l) > 2][:12]
        out[norm(r["name"])] = {"name": r["name"], "street": street,
                                "menu": {"items": [{"t": "", "d": dishes, "diet": diets_of(*dishes), "p": min(ps) if ps else None}],
                                         "src": "Raflaamo", "url": "https://www.raflaamo.fi/fi/ravintolat/helsinki/lounas", "conf": "web", "hours": None}}
    return out


FOOD = re.compile(r"(?i)\(?\b(L|G|M|VL|VEG|VE|K)\b[,)]|kastike|keitto|pihvi|broiler|kana\b|kanaa|lohi|lohta|kala|riisi|peruna|pasta|salaatti|curry|pata|paisti|kasvis|soup|chicken|salmon|beef|pork|tofu|wok|nuudeli|noodle|lammas|naudan|härkä|vegaani|masala|tikka|pyöry|laatikko|risotto|leike|muhennos")
FASTFOOD = re.compile(r"(?i)burger king|mcdonald|hesburger|subway|kotipizza|taco bell|kfc|domino")
CSS = open(os.path.join(os.path.dirname(__file__), "style.css")).read()



# ---------------------------------------------------------------- i18n
T = {
    "fi": {"home": "/", "areas": "/lounas/", "area": "/lounas/{s}/", "venue": "/ravintola/{s}/", "nav_areas": "Alueet", "other": "In English", "other_home": "/en/",
           "wd": ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"],
           "wd_short": ["Ma", "Ti", "Ke", "To", "Pe", "La", "Su"],
           "h1_home": "Lounas Helsinki", "v_map": "🗺️ Kartta", "v_list": "☰ Lista", "search": "Hae ravintolaa, ruokaa tai aluetta", "near": "📍 Lähellä",
           "chips": [("menu", "Vain listalliset"), ("open", "Auki nyt"), ("cheap", "Halvin ensin"), ("Veg", "Veg"), ("G", "G"), ("L", "L"), ("M", "M"), ("oivaA", "Oiva 😃")],
           "title_home": "Lounas Helsinki tänään – päivän lounaslistat kartalla | Päivän lounas",
           "desc_home": "Helsingin lounaslistat tänään ({d}): {n} ravintolan lista, hinnat, ruokavaliot ja Oiva-hymy kartalla.",
           "area_h1": "Lounas {a} tänään", "area_title": "Lounas {a} tänään – {n} lounaslistaa | Päivän lounas",
           "area_lead": "{d}: {n} ravintolan lounaslista alueella {a}. {c} Yhteensä {t} ravintolaa ja kahvilaa, Oiva-arvosanat mukana.",
           "cheapest": "Halvin lounas tänään {p}.", "show_map": "Näytä kartalla", "areas_h1": "Lounas Helsingissä alueittain",
           "areas_title": "Lounas Helsingissä alueittain | Päivän lounas", "lists": "listaa", "places": "paikkaa",
           "venue_h1": "{n} – lounas tänään", "venue_title": "{n} lounas tänään – lounaslista | Päivän lounas",
           "venue_desc": "{n} ({a}): päivän lounaslista, hinnat, ruokavaliot ja Oiva-arvosana.",
           "list_for": "Lounaslista {d}", "week": "Tämän viikon listat", "nomenu": "Tämän päivän listaa ei ole saatavilla. Katso ravintolan omat sivut.",
           "src": "Lähde", "orig": "alkuperäinen lista", "oiva": "Oiva-arvosana", "oiva_rep": "Oiva-raportti", "website": "Ravintolan verkkosivu",
           "route": "Reittiohjeet", "park": "🅿️ Halvin parkki lähellä (Parkpenny)", "oiva_txt": {"A": "Oivallinen", "B": "Hyvä", "C": "Korjattavaa", "D": "Huono"},
           "wrong": "Väärä tieto?", "wrong_ok": "Kiitos ilmoituksesta!", "report_h": "Onko tämä sinun ravintolasi?", "report_p": "Kerro, missä lounaslistasi julkaistaan (oma sivu, Facebook-sivu tai pdf). Haemme sen jatkossa automaattisesti joka aamu – sinun ei tarvitse tehdä muuta.",
           "report_url": "Lounaslistan osoite", "report_btn": "Lähetä", "report_ok": "Kiitos! Tarkistamme osoitteen seuraavassa päivityksessä.",
           "footer1": "Lounaslistat haetaan automaattisesti ravintoloiden ja ketjujen omista lähteistä joka arkiaamu. Tarkista erityisruokavaliot aina ravintolasta.",
           "footer2": "Elintarvikevalvonnan tulokset: Oiva / Ruokavirasto (oivahymy.fi). Osoitteet ja kaupunginosat: Helsingin kaupunki, CC BY 4.0. Kartta: © OpenStreetMapin tekijät.",
           "about": "/tietoa/", "about_l": "Tietoa palvelusta", "privacy": "/tietosuoja/", "privacy_l": "Tietosuoja",
           "preview": "Esikatselu – sivusto on vielä kehitysvaiheessa", "notfound": "Sivua ei löytynyt", "tohome": "Etusivulle", "crumb_home": "Etusivu", "lang": "fi", "menu_lang": ""},
    "en": {"home": "/en/", "areas": "/en/lunch/", "area": "/en/lunch/{s}/", "venue": "/en/restaurant/{s}/", "nav_areas": "Areas", "other": "Suomeksi", "other_home": "/",
           "wd": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
           "wd_short": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
           "h1_home": "Lunch in Helsinki", "v_map": "🗺️ Map", "v_list": "☰ List", "search": "Search restaurant, dish or area", "near": "📍 Near me",
           "chips": [("menu", "With menu"), ("open", "Open now"), ("cheap", "Cheapest first"), ("Veg", "Veg"), ("G", "GF"), ("L", "LF"), ("M", "DF"), ("oivaA", "Oiva 😃")],
           "title_home": "Lunch in Helsinki today – lunch menus on a map | Päivän lounas",
           "desc_home": "Helsinki lunch menus today ({d}): {n} restaurants with menus, prices, diets and food-safety ratings on a map.",
           "area_h1": "Lunch in {a} today", "area_title": "Lunch in {a} today – {n} lunch menus | Päivän lounas",
           "area_lead": "{d}: {n} restaurants in {a} with today's lunch menu. {c} {t} restaurants and cafés in total, with Oiva food-safety ratings.",
           "cheapest": "Cheapest lunch today {p}.", "show_map": "Show on map", "areas_h1": "Lunch in Helsinki by area",
           "areas_title": "Lunch in Helsinki by area | Päivän lounas", "lists": "menus", "places": "places",
           "venue_h1": "{n} – lunch today", "venue_title": "{n} lunch today – lunch menu | Päivän lounas",
           "venue_desc": "{n} ({a}): today's lunch menu, prices, diets and Oiva food-safety rating.",
           "list_for": "Lunch menu {d}", "week": "This week's menus", "nomenu": "Today's menu is not available. See the restaurant's own website.",
           "src": "Source", "orig": "original menu", "oiva": "Oiva food-safety rating", "oiva_rep": "Oiva report", "website": "Restaurant website",
           "route": "Directions", "park": "🅿️ Cheapest parking nearby (Parkpenny)", "oiva_txt": {"A": "Excellent", "B": "Good", "C": "To be corrected", "D": "Poor"},
           "wrong": "Wrong info?", "wrong_ok": "Thanks for letting us know!", "report_h": "Is this your restaurant?", "report_p": "Tell us where your lunch menu is published (website, Facebook page or pdf). We will fetch it automatically every morning – nothing else is needed.",
           "report_url": "Lunch menu address", "report_btn": "Send", "report_ok": "Thank you! We will check the address in the next update.",
           "footer1": "Lunch menus are fetched automatically from restaurants' and chains' own sources every weekday morning. Menus are shown in the language the restaurant publishes them (mostly Finnish). Always check special diets with the restaurant.",
           "footer2": "Food-control results: Oiva / Finnish Food Authority (oivahymy.fi). Addresses and districts: City of Helsinki, CC BY 4.0. Map: © OpenStreetMap contributors.",
           "about": "/en/about/", "about_l": "About", "privacy": "/en/privacy/", "privacy_l": "Privacy",
           "preview": "Preview – the site is still under development", "notfound": "Page not found", "tohome": "Front page", "crumb_home": "Home", "lang": "en", "menu_lang": "en"},
}


ADSENSE = os.environ.get("ADSENSE_CLIENT", "").strip()  # ca-pub-…; empty = no ads anywhere
CONTACT = "info@paivanlounas.fi"
OWNER = "BR Entertainment (toiminimi), Y-tunnus 3183394-5"


def ads_tag(path):
    """Auto ads only on content pages, never on the map app."""
    if not ADSENSE or path in ("/", "/en/") or path.startswith(("/tietosuoja", "/en/privacy", "/404")):
        return ""
    return f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={esc(ADSENSE)}" crossorigin="anonymous"></script>'


def page(lg, title, desc, path, alt_path, body, preview, extra_head=""):
    t = T[lg]
    extra_head += ads_tag(path)
    robots = '<meta name="robots" content="noindex,nofollow">' if preview else ""
    bar = f'<div class="preview">{t["preview"]}</div>' if preview else ""
    other = "en" if lg == "fi" else "fi"
    hl = (f'<link rel="alternate" hreflang="{lg}" href="{DOMAIN}{path}"><link rel="alternate" hreflang="{other}" href="{DOMAIN}{alt_path}">'
          f'<link rel="alternate" hreflang="x-default" href="{DOMAIN}{path if lg == "fi" else alt_path}">') if alt_path else ""
    return f"""<!doctype html><html lang="{lg}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{DOMAIN}{path}">{hl}{robots}
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><meta name="theme-color" content="#1f6f4a">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:type" content="website">
<link rel="stylesheet" href="/style.css">{extra_head}</head><body>{bar}
<header class="top"><a class="logo" href="{t['home']}">🍽️ Päivän lounas</a><nav><a href="{t['areas']}">{t['nav_areas']}</a><a href="{alt_path or t['other_home']}" hreflang="{other}">{t['other']}</a></nav></header>
{body}
<footer><p>{t['footer1']}</p><p>{t['footer2']}</p><p>© 2026 Päivän lounas · <a href="{t['about']}">{t['about_l']}</a> · <a href="{t['privacy']}">{t['privacy_l']}</a> · {CONTACT}</p></footer></body></html>"""


def fmt_price(p):
    return f"{p:.2f} €".replace(".", ",")


def menu_html(m, lg, slug_=None, day=None):
    t = T[lg]
    if not m:
        return f'<p class="nomenu">{t["nomenu"]}</p>'
    out = []
    for it in m["items"]:
        price = f'<span class="price">{fmt_price(it["p"])}</span>' if it.get("p") else ""
        diet = "".join(f'<span class="diet">{esc(d)}</span>' for d in it.get("diet", []))
        title = f'<b>{esc(it["t"])}</b> ' if it.get("t") else ""
        out.append(f'<li>{title}{esc(" · ".join(it["d"]))} {diet} {price}</li>')
    wrong = f' · <a href="#" class="wrong" data-wrong="{esc(slug_)}" data-day="{day}" data-ok="{esc(t["wrong_ok"])}" rel="nofollow">{t["wrong"]}</a>' if slug_ else ""
    src = f'<p class="src">{t["src"]}: {esc(m["src"])}' + (f' – <a href="{esc(m["url"])}" rel="nofollow noopener">{t["orig"]}</a>' if m.get("url") else "") + wrong + "</p>"
    return '<ul class="menu">' + "".join(out) + "</ul>" + src


def parkpenny(v, lg):
    q = urllib.parse.urlencode({"lat": round(v["lat"], 5), "lon": round(v["lon"], 5), "q": v["name"], "dur": 60})
    base = "https://parkpenny.com/en/" if lg == "en" else "https://parkpenny.com/"
    return f'<a class="btn ghost" href="{base}?{q}" rel="noopener">{T[lg]["park"]}</a>'


def report_form(v, lg):
    t = T[lg]
    return f"""<section class="report"><h2>{t['report_h']}</h2><p>{t['report_p']}</p>
<form method="post" action="/api/suggest" class="suggest"><input type="hidden" name="venue" value="{esc(v['slug'])}"><input type="hidden" name="lang" value="{lg}">
<input type="text" name="website" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">
<label>{t['report_url']}<input type="url" name="url" required placeholder="https://"></label><button class="btn" type="submit">{t['report_btn']}</button>
<p class="ok" hidden>{t['report_ok']}</p></form></section>"""


def week_days(day):
    dt = datetime.date.fromisoformat(day)
    mon = dt - datetime.timedelta(days=dt.weekday())
    if dt.weekday() >= 5:
        mon = mon + datetime.timedelta(days=7)
    return [(mon + datetime.timedelta(days=i)).isoformat() for i in range(5)]


def datestr(d, lg):
    dt = datetime.date.fromisoformat(d)
    return f"{T[lg]['wd'][dt.weekday()]} {dt.day}.{dt.month}.{dt.year}" if lg == "fi" else f"{T[lg]['wd'][dt.weekday()]} {dt.day}.{dt.month}.{dt.year}"


def main(L, out, day, preview):
    os.makedirs(out, exist_ok=True)
    days = week_days(day)
    show_day = day if datetime.date.fromisoformat(day).weekday() < 5 else days[0]
    reg = json.load(open(f"{L}/data/registry_helsinki.json"))
    ds = load_districts(os.path.join(os.path.dirname(__file__), "..", "kaupunginosat.json"))
    M = {d: menus_today(L, d) for d in days}
    R = raflaamo_today(L)
    venues = []
    for v in reg:
        if v["lat"] is None:
            continue
        keys = list(v["sources"]) + [v["id"]] + (["osm:" + v["osm"]] if v.get("osm") else [])
        ms = {}
        for d in days:
            for k in keys:
                if k in M[d]:
                    ms[d] = M[d][k]
                    break
        if show_day not in ms and norm(v["name"]) in R:
            ms[show_day] = R.pop(norm(v["name"]))["menu"]
        dd = district_of(v["lat"], v["lon"], ds)
        venues.append({**v, "ms": ms, "menu": ms.get(show_day), "district": dd["name"] if dd else None, "dslug": dd["slug"] if dd else None})
    seen = {}
    for v in venues:
        s = slug(v["name"])
        if s in seen:
            s = f"{s}-{slug(v['street'] or '')[:30]}".strip("-")
        if s in seen:
            s = f"{s}-{len(seen)}"
        seen[s] = 1
        v["slug"] = s
        for d in days:  # menu address sent by the restaurant through the form
            if d not in v["ms"] and "sug:" + s in M[d]:
                v["ms"][d] = M[d]["sug:" + s]
        v["menu"] = v["ms"].get(show_day)
    rp = f"{L}/data/reports_raw.json"
    hidden = 0
    if os.path.exists(rp):
        try:
            reps = {(r["venue"], r["day"]): r["n"] for r in json.load(open(rp))[0]["results"]}
        except Exception as e:
            print("reports unreadable:", e, file=sys.stderr)
            reps = {}
        for v in venues:
            for d in list(v["ms"]):
                need = 3 if v["ms"][d].get("conf") == "api" else 2
                if reps.get((v["slug"], d), 0) >= need:
                    del v["ms"][d]
                    hidden += 1
            v["menu"] = v["ms"].get(show_day)
    print("hidden by reports", hidden, file=sys.stderr)
    with_menu = [v for v in venues if v["menu"]]
    print("venues", len(venues), "with menu", show_day, len(with_menu), "| week", {d: sum(1 for v in venues if d in v["ms"]) for d in days}, file=sys.stderr)

    os.makedirs(f"{out}/data", exist_ok=True)
    st = f"{L}/data/ai_stats.json"
    if os.path.exists(st):
        shutil.copy(st, f"{out}/data/status.json")
    app = [{"i": v["slug"], "n": v["name"], "a": v["street"], "y": round(v["lat"], 5), "x": round(v["lon"], 5),
            "o": (v["oiva"] or {}).get("grade"), "d": v["district"], "w": v.get("website"), "ms": v["ms"]} for v in venues]
    json.dump({"date": show_day, "days": days, "venues": app}, open(f"{out}/data/week.json", "w"), ensure_ascii=False, separators=(",", ":"))

    here = os.path.dirname(__file__)
    for f in ("style.css", "app.js", "suggest.js", "favicon.svg"):
        shutil.copy(os.path.join(here, f), f"{out}/{f}")
    os.makedirs(f"{out}/vendor/leaflet/images", exist_ok=True)
    lf = os.path.join(here, "..", "node_modules", "leaflet", "dist")
    for f in ("leaflet.js", "leaflet.css"):
        shutil.copy(f"{lf}/{f}", f"{out}/vendor/leaflet/{f}")
    for f in os.listdir(f"{lf}/images"):
        shutil.copy(f"{lf}/images/{f}", f"{out}/vendor/leaflet/images/{f}")

    urls = []
    by_d = {}
    for v in venues:
        if v["dslug"]:
            by_d.setdefault((v["dslug"], v["district"]), []).append(v)
    for lg in ("fi", "en"):
        t = T[lg]
        other = "en" if lg == "fi" else "fi"
        ds_ = datestr(show_day, lg)
        # home / app
        chips = "".join(f'<button data-f="{k}"{" class=on" if k == "menu" else ""}>{esc(lbl)}</button>' for k, lbl in t["chips"])
        dchips = "".join(f'<button data-day="{d}"{" class=on" if d == show_day else ""}>{t["wd_short"][i]} {int(d[8:])}.{int(d[5:7])}.</button>' for i, d in enumerate(days))
        body = f"""<main class="app" data-lang="{lg}"><div id="map"></div><section class="panel" id="panel">
<div class="grip"></div><div class="views" role="tablist"><button data-view="map" class="on">{t['v_map']}</button><button data-view="list">{t['v_list']}</button></div><h1>{t['h1_home']} <small id="dlabel">{esc(ds_)}</small></h1>
<div class="days">{dchips}</div>
<div class="search"><input id="q" type="search" placeholder="{esc(t['search'])}"><button id="near" type="button">{t['near']}</button></div>
<div class="chips">{chips}</div><p id="count" class="count"></p><ol id="list" class="list"></ol><button id="more" class="btn ghost more" hidden></button></section></main>
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css"><script src="/vendor/leaflet/leaflet.js"></script><script src="/app.js"></script><script src="/suggest.js" defer></script>"""
        ld = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE, "url": DOMAIN + t["home"], "inLanguage": lg}
        hp = t["home"]
        os.makedirs(f"{out}{hp}", exist_ok=True)
        open(f"{out}{hp}index.html", "w").write(page(lg, t["title_home"], t["desc_home"].format(d=ds_, n=len(with_menu)), hp, T[other]["home"], body, preview,
                                                       f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'))
        urls.append(hp)
        # districts
        idx = []
        for (dslug, dn), vs in sorted(by_d.items(), key=lambda x: x[0][1]):
            vs.sort(key=lambda v: (v["menu"] is None, (min([i["p"] for i in v["menu"]["items"] if i.get("p")] or [99]) if v["menu"] else 99), v["name"]))
            nm = sum(1 for v in vs if v["menu"])
            prices = [i["p"] for v in vs if v["menu"] for i in v["menu"]["items"] if i.get("p") and i["p"] >= 5]
            cheapest = t["cheapest"].format(p=fmt_price(min(prices))) if prices else ""
            cards = []
            for v in vs[:150]:
                o = (v["oiva"] or {}).get("grade")
                oiva = f'<span class="oiva" title="Oiva: {t["oiva_txt"].get(o, "")}">{"😃" if o == "A" else "🙂" if o == "B" else "😐" if o == "C" else "☹️"}</span>' if o else ""
                cards.append(f'<li class="card"><h3><a href="{t["venue"].format(s=v["slug"])}">{esc(v["name"])}</a> {oiva}</h3><p class="addr">{esc(v["street"])}</p>{menu_html(v["menu"], lg) if v["menu"] else ""}</li>')
            path, alt = t["area"].format(s=dslug), T[other]["area"].format(s=dslug)
            body = f"""<main class="content"><nav class="crumbs"><a href="{t['home']}">{t['crumb_home']}</a> › <a href="{t['areas']}">{t['nav_areas']}</a> › {esc(dn)}</nav>
<h1>{t['area_h1'].format(a=esc(dn))}</h1><p class="lead">{esc(t['area_lead'].format(d=ds_, n=nm, a=dn, c=cheapest, t=len(vs)))}</p>
<p><a class="btn" href="{t['home']}?d={dslug}">{t['show_map']}</a></p><ol class="cards">{''.join(cards)}</ol></main>"""
            os.makedirs(f"{out}{path}", exist_ok=True)
            open(f"{out}{path}index.html", "w").write(page(lg, t["area_title"].format(a=dn, n=nm), t["area_lead"].format(d=ds_, n=nm, a=dn, c=cheapest, t=len(vs)), path, alt, body, preview))
            urls.append(path)
            idx.append((dn, dslug, nm, len(vs)))
        lis = "".join(f'<li><a href="{t["area"].format(s=s)}">{esc(n)}</a> <small>{m} {t["lists"]} · {tt} {t["places"]}</small></li>' for n, s, m, tt in idx)
        os.makedirs(f"{out}{t['areas']}", exist_ok=True)
        open(f"{out}{t['areas']}index.html", "w").write(page(lg, t["areas_title"], t["areas_h1"], t["areas"], T[other]["areas"],
                                                              f'<main class="content"><h1>{t["areas_h1"]}</h1><ul class="areas">{lis}</ul></main>', preview))
        urls.append(t["areas"])
        # venues
        for v in venues:
            if not (v["ms"] or v["sources"]):
                continue
            o = v["oiva"] or {}
            path, alt = t["venue"].format(s=v["slug"]), T[other]["venue"].format(s=v["slug"])
            oiva = f'<p class="oivabox">{t["oiva"]}: <b>{t["oiva_txt"].get(o.get("grade"), "")}</b> ({esc(o.get("date"))}) – <a href="https://www.oivahymy.fi/hae-yrityksia/" rel="nofollow noopener">{t["oiva_rep"]}</a></p>' if o.get("grade") else ""
            web = f'<p><a href="{esc(v["website"])}" rel="nofollow noopener">{t["website"]}</a></p>' if v.get("website") else ""
            dlink = f' · <a href="{t["area"].format(s=v["dslug"])}">{esc(t["area_h1"].format(a=v["district"]))}</a>' if v["dslug"] else ""
            week = "".join(f'<h3>{esc(datestr(d, lg))}</h3>{menu_html(v["ms"].get(d), lg, v["slug"], d)}' for d in days if d != show_day and d in v["ms"])
            week = f'<h2>{t["week"]}</h2>{week}' if week else ""
            jl = {"@context": "https://schema.org", "@type": "Restaurant", "name": v["name"],
                  "address": {"@type": "PostalAddress", "streetAddress": v["street"], "postalCode": v.get("postal"), "addressLocality": "Helsinki", "addressCountry": "FI"},
                  "geo": {"@type": "GeoCoordinates", "latitude": v["lat"], "longitude": v["lon"]}}
            if v.get("website"):
                jl["url"] = v["website"]
            body = f"""<main class="content"><nav class="crumbs"><a href="{t['home']}">{t['crumb_home']}</a>{dlink}</nav>
<h1>{esc(t['venue_h1'].format(n=v['name']))}</h1><p class="addr">{esc(v['street'])}, Helsinki</p>
<h2>{esc(t['list_for'].format(d=ds_))}</h2>{menu_html(v['menu'], lg, v['slug'], show_day)}{week}{oiva}{web}
<p class="actions"><a class="btn" href="{t['home']}?v={v['slug']}">{t['show_map']}</a> <a class="btn ghost" href="https://www.google.com/maps/dir/?api=1&destination={v['lat']},{v['lon']}" rel="nofollow noopener">{t['route']}</a> {parkpenny(v, lg)}</p>
{report_form(v, lg)}</main><script src="/suggest.js" defer></script>"""
            os.makedirs(f"{out}{path}", exist_ok=True)
            open(f"{out}{path}index.html", "w").write(page(lg, t["venue_title"].format(n=v["name"]), t["venue_desc"].format(n=v["name"], a=v["street"]), path, alt, body, preview,
                                                           f'<script type="application/ld+json">{json.dumps(jl, ensure_ascii=False)}</script>'))
            urls.append(path)
    write_info_pages(out, preview, urls)
    if ADSENSE:
        open(f"{out}/ads.txt", "w").write(f"google.com, {ADSENSE.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n")
    open(f"{out}/404.html", "w").write(page("fi", "Sivua ei löytynyt | Päivän lounas", "", "/404", None, '<main class="content"><h1>Sivua ei löytynyt</h1><p><a href="/">Etusivulle</a></p></main>', True))
    open(f"{out}/robots.txt", "w").write("User-agent: *\nDisallow: /\n" if preview else f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {DOMAIN}/sitemap.xml\n")
    sm = "".join(f"<url><loc>{DOMAIN}{u}</loc><lastmod>{show_day}</lastmod></url>" for u in urls)
    open(f"{out}/sitemap.xml", "w").write(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
    open(f"{out}/_headers", "w").write("/data/*\n  Cache-Control: public, max-age=600\n/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n")
    print("pages", len(urls), file=sys.stderr)


INFO = {
    "fi": {
        "about": ("/tietoa/", "/en/about/", "Tietoa palvelusta | Päivän lounas", "Mikä Päivän lounas on ja mistä lounaslistat tulevat.", """
<h1>Tietoa palvelusta</h1>
<p>Päivän lounas kokoaa Helsingin lounaslistat yhteen paikkaan: kartalle ja listaksi, päivittäin ja koko viikolle. Mukana ovat myös ravintolat, jotka eivät ole itse ilmoittaneet listaansa mihinkään.</p>
<h2>Mistä listat tulevat</h2>
<ul><li>Ravintolaketjujen julkiset ruokalistapalvelut (esim. Compass Group, Sodexo, UniCafe) ja Raflaamon julkinen lounassivu.</li>
<li>Ravintoloiden omat verkkosivut, PDF-listat ja listakuvat. Ne luetaan joka arkiaamu koneellisesti, osin tekoälyn avulla (Anthropicin Claude).</li></ul>
<p>Lähde ja linkki alkuperäiseen listaan näkyvät jokaisen listan alla. Lista voi joskus olla vanha tai väärä – tarkista erityisruokavaliot ja hinnat aina ravintolasta. Jos huomaat virheen, paina listan alla <b>Väärä tieto?</b>. Kun ilmoituksia tulee useampi, lista piilotetaan.</p>
<h2>Muut tiedot</h2>
<p>Oiva-hymyt: Ruokaviraston ja kuntien elintarvikevalvonta (oivahymy.fi). Osoitteet ja kaupunginosat: Helsingin kaupunki, CC BY 4.0. Kartta: © OpenStreetMapin tekijät.</p>
<h2>Ravintoloille</h2>
<p>Listaa ei tarvitse syöttää meille. Jos listasi puuttuu, kerro ravintolasi sivulla, missä osoitteessa lounaslistasi julkaistaan – haemme sen sieltä joka aamu automaattisesti.</p>
<h2>Ylläpitäjä ja yhteystiedot</h2>
<p>{owner}<br>Sähköposti: {contact}</p>"""),
        "privacy": ("/tietosuoja/", "/en/privacy/", "Tietosuojaseloste | Päivän lounas", "Mitä tietoja Päivän lounas käsittelee.", """
<h1>Tietosuojaseloste</h1>
<p>Päivitetty {date}.</p>
<h2>Rekisterinpitäjä</h2><p>{owner}, {contact}</p>
<h2>Mitä tietoja käsitellään</h2>
<ul><li><b>Ei käyttäjätilejä.</b> Palvelua käytetään kirjautumatta.</li>
<li><b>Sijainti:</b> jos painat ”Lähellä”, selain kysyy luvan ja sijaintia käytetään vain selaimessasi ravintoloiden järjestämiseen. Sitä ei lähetetä meille.</li>
<li><b>Asetukset:</b> kartta- tai listanäkymän valinta tallennetaan selaimesi paikalliseen muistiin (localStorage). Se ei lähde meille.</li>
<li><b>”Väärä tieto?” -ilmoitukset ja ravintoloiden listaosoitteet:</b> tallennamme ravintolan, päivän ja ilmoitetun osoitteen. IP-osoitetta ei tallenneta; siitä lasketaan päiväkohtainen tiiviste, jolla rajoitetaan toistuvia ilmoituksia.</li>
<li><b>Palvelin:</b> sivusto toimii Cloudflaren palveluissa, jotka käsittelevät teknisiä yhteystietoja (esim. IP-osoite) sivun toimittamiseksi ja tietoturvan vuoksi.</li>
<li><b>Karttatiilet</b> ladataan OpenStreetMapin palvelimilta, jotka näkevät IP-osoitteesi.</li></ul>
{ads}
<h2>Säilytys ja oikeutesi</h2><p>Ilmoitukset poistetaan, kun niitä ei enää tarvita, viimeistään 24 kuukauden kuluttua. Voit pyytää tietoja tai niiden poistamista osoitteesta {contact}. Sinulla on oikeus tehdä valitus tietosuojavaltuutetulle (tietosuoja.fi).</p>"""),
        "ads": """<h2>Mainonta</h2><p>Sivustolla näytetään Google AdSense -mainoksia. Google ja sen kumppanit voivat käyttää evästeitä ja muita tunnisteita mainosten näyttämiseen ja mittaamiseen. Euroopan talousalueella kysymme suostumuksesi Googlen sertifioimalla suostumusikkunalla, ja voit muuttaa valintaasi milloin tahansa. Lisätietoja: <a href="https://policies.google.com/technologies/ads" rel="nofollow noopener">policies.google.com/technologies/ads</a>.</p>""",
    },
    "en": {
        "about": ("/en/about/", "/tietoa/", "About | Päivän lounas", "What Päivän lounas is and where the lunch menus come from.", """
<h1>About</h1>
<p>Päivän lounas collects Helsinki's lunch menus in one place – on a map and as a list, for today and the whole week – including restaurants that never submitted their menu anywhere.</p>
<h2>Where the menus come from</h2>
<ul><li>Restaurant chains' public menu services (e.g. Compass Group, Sodexo, UniCafe) and Raflaamo's public lunch page.</li>
<li>Restaurants' own websites, PDF menus and menu images, read automatically every weekday morning, partly with AI (Anthropic's Claude).</li></ul>
<p>The source and a link to the original menu are shown under every menu. A menu can sometimes be outdated or wrong – always check special diets and prices with the restaurant. If you spot a mistake, press <b>Wrong info?</b> under the menu; menus with several reports are hidden.</p>
<h2>Other data</h2>
<p>Oiva ratings: Finnish Food Authority and municipal food control (oivahymy.fi). Addresses and districts: City of Helsinki, CC BY 4.0. Map: © OpenStreetMap contributors.</p>
<h2>For restaurants</h2>
<p>You don't need to send us your menu. If it is missing, tell us on your restaurant's page where your lunch menu is published – we fetch it automatically every morning.</p>
<h2>Operator and contact</h2>
<p>{owner}<br>Email: {contact}</p>"""),
        "privacy": ("/en/privacy/", "/tietosuoja/", "Privacy policy | Päivän lounas", "What data Päivän lounas processes.", """
<h1>Privacy policy</h1>
<p>Updated {date}.</p>
<h2>Controller</h2><p>{owner}, {contact}</p>
<h2>What we process</h2>
<ul><li><b>No user accounts.</b> The service is used without signing in.</li>
<li><b>Location:</b> if you press “Near me”, your browser asks for permission and the location is used only in your browser to sort restaurants. It is not sent to us.</li>
<li><b>Settings:</b> your choice of map or list view is stored in your browser (localStorage). It is not sent to us.</li>
<li><b>“Wrong info?” reports and menu addresses sent by restaurants:</b> we store the restaurant, the day and the submitted address. IP addresses are not stored; a daily hash of it is used to limit repeated reports.</li>
<li><b>Hosting:</b> the site runs on Cloudflare, which processes technical connection data (e.g. IP address) to deliver pages and for security.</li>
<li><b>Map tiles</b> are loaded from OpenStreetMap's servers, which see your IP address.</li></ul>
{ads}
<h2>Retention and your rights</h2><p>Reports are deleted when no longer needed, at the latest after 24 months. You can request access or deletion at {contact}. You have the right to lodge a complaint with the Finnish Data Protection Ombudsman (tietosuoja.fi).</p>"""),
        "ads": """<h2>Advertising</h2><p>The site shows Google AdSense ads. Google and its partners may use cookies and other identifiers to show and measure ads. In the European Economic Area we ask for your consent with a Google-certified consent message, and you can change your choice at any time. More: <a href="https://policies.google.com/technologies/ads" rel="nofollow noopener">policies.google.com/technologies/ads</a>.</p>""",
    },
}


def write_info_pages(out, preview, urls):
    today = datetime.date.today()
    for lg in ("fi", "en"):
        for key in ("about", "privacy"):
            path, alt, title, desc, body = INFO[lg][key]
            body = body.format(owner=OWNER if lg == "fi" else OWNER.replace("toiminimi", "sole trader").replace("Y-tunnus", "Business ID"),
                               contact=CONTACT, date=f"{today.day}.{today.month}.{today.year}", ads=INFO[lg]["ads"] if ADSENSE else "")
            os.makedirs(f"{out}{path}", exist_ok=True)
            open(f"{out}{path}index.html", "w").write(page(lg, title, desc, path, alt, f'<main class="content">{body}</main>', preview))
            urls.append(path)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    main(a[0], a[1], a[2], "--preview" in sys.argv)
