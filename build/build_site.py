"""Build paivanlounas.fi (static, Cloudflare Pages) from the venue registry + today's menus.
Usage: build_site.py <lounas_dir> <out_dir> <YYYY-MM-DD> [--preview]"""
import json, math, re, sys, os, html, shutil, datetime, unicodedata, urllib.parse

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


def decap(s):
    """'VOISSA PAISTETTUA KUHAA' -> 'Voissa paistettua kuhaa' (short codes like BBQ, L, G stay)."""
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 8 or sum(c.isupper() for c in letters) < 0.8 * len(letters):
        return s
    out = s.lower()
    out = re.sub(r"\b(bbq|vl|veg|ve|l|g|m|k|tm|xl)\b", lambda m: m.group(0).upper(), out)
    return out[:1].upper() + out[1:]


def clean_dish(d):
    d = re.sub(r"\s*\((?:[A-Za-z]{1,4}[\s,+*/]*)+\)", "", d or "")
    d = re.sub(r"\s+(?:VL|VE|VEG|L|G|M|K|V|\*)(?:\s*[,/]\s*(?:VL|VE|VEG|L|G|M|K|V|\*))+(?=\s|$)", "", d)
    return re.sub(r"[\s,;·]+$", "", d)


def menu_text(v):
    return " ".join(" ".join(i["d"]) + " " + (i.get("t") or "") for i in v["menu"]["items"]).lower()


def is_veg(v):
    return any(("Veg" in i.get("diet", []) or "Kasvis" in i.get("diet", [])) for i in v["menu"]["items"]) or bool(re.search(r"kasvis|vegaan|vegan|vegetar", menu_text(v)))


def lunch_price(m):
    ps = [i["p"] for i in m["items"] if i.get("p") and 5 <= i["p"] <= 25]
    return min(ps) if ps else None


def entry_html(v, mp, t, lg, show_area=False):
    m = v["menu"]; o = (v["oiva"] or {}).get("grade")
    dishes = " · ".join(clean_dish(i["d"][0]) for i in m["items"][:4])
    meta = " · ".join(x for x in ((v["district"] if show_area else ""), v["street"], (t["oiva"] + " " + t["oiva_txt"][o]) if o in ("A", "B") else "",
                                  (AREA_T[lg]["until"] + m["hours"]) if m.get("hours") else "") if x)
    pr = fmt_price(mp[v["slug"]]) if mp.get(v["slug"]) else ""
    return (f'<article class="ent"><div class="row"><h3><a href="{t["venue"].format(s=v["slug"])}">{esc(v["name"])}</a></h3><span class="price">{pr}</span></div>'
            f'<p class="dish">{esc(dishes)}</p><p class="meta">{esc(meta)}</p></article>')


def public_price(prices):
    """Chains list student / staff / other prices together: the regular (highest sensible) price is what most visitors pay."""
    ps = [p for p in (prices or []) if 4 <= p <= 30]
    return max(ps) if ps else None


def student_price(r):
    """Student discount on offer: every UniCafe; Compass/Sodexo when the price text names students / Kela or has a
    Kela-level price (<= 4 €) next to the regular one."""
    if r.get("source") == "unicafe":
        return True
    for it in r.get("items", []):
        pt = (it.get("price_text") or "").lower()
        if re.search(r"opiskelij|student|kela", pt):
            return True
        ps = [float(x.replace(",", ".")) for x in re.findall(r"(\d{1,2}[,.]\d{2})", pt)]
        if len(ps) >= 2 and min(ps) <= 4.0 and max(ps) >= 6.0:
            return True
    return False


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
                          "p": public_price(it.get("prices"))})
        if items:
            res[r["id"]] = {"items": items, "src": names[r["source"]], "url": meta.get("url"), "conf": "api",
                            "hours": meta.get("lunch_today")}
            if student_price(r):
                res[r["id"]]["stu"] = 1
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
import hashlib
# cache-busting: each deploy points pages at /app.js?v=<content hash>, so phones never mix new HTML with an old cached script
VER = {f: hashlib.md5(open(os.path.join(os.path.dirname(__file__), f), "rb").read()).hexdigest()[:8] for f in ("style.css", "app.js", "suggest.js", "m.js")}



# ---------------------------------------------------------------- i18n
T = {
    "fi": {"home": "/", "areas": "/lounas/", "area": "/lounas/{s}/", "venue": "/ravintola/{s}/", "nav_areas": "Alueet", "other": "In English", "other_home": "/en/",
           "wd": ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"],
           "wd_short": ["Ma", "Ti", "Ke", "To", "Pe", "La", "Su"],
           "h1_home": "Lounas Helsinki", "v_map": "Kartta", "v_list": "Lista", "d_list": "Lista", "d_map": "Kartta", "d_filter": "Suodata", "d_big": "Koko kartta", "d_back": "Takaisin listaan", "sheet_label": "Lounaat lähellä", "locate": "Hae sijaintini", "sheet_more": "Näytä lisää", "as_list": "Näytä listana", "done": "Valmis", "search_ph": "Hae ruokaa tai paikkaa",
           "pills": [("near", "Lähellä"), ("pop", "Suosituimmat"), ("cheap", "Halvimmat"), ("veg", "Kasvis"), ("stu", "Opiskelija")], "search": "Hae ravintolaa, ruokaa tai aluetta", "near": "Lähellä",
           "cats": [("soup", "Keitto"), ("fish", "Kala"), ("chicken", "Kana"), ("meat", "Liha"), ("veg", "Kasvis"), ("pasta", "Pasta"), ("pizza", "Pizza"), ("burger", "Burger"), ("asian", "Aasialainen"), ("salad", "Salaatti"), ("buffet", "Buffet")],
           "chips": [("fav", "Suosikit"), ("menu", "Vain listalliset"), ("stu", "Opiskelijahinta"), ("open", "Auki nyt"), ("u13", "Alle 13 €"), ("cheap", "Halvin ensin"), ("Veg", "Kasvis"), ("G", "G"), ("L", "L"), ("M", "M"), ("oivaA", "Oiva A")],
           "title_home": "Lounas Helsinki tänään – päivän lounaslistat kartalla | Päivän lounas",
           "desc_home": "Helsingin lounaslistat tänään ({d}): {n} ravintolan lista, hinnat, ruokavaliot ja Oiva-hymy kartalla.",
           "area_h1": "Lounas {a} tänään", "area_title": "Lounas {a} tänään – {n} lounaslistaa | Päivän lounas",
           "area_lead": "{d}: {n} ravintolan lounaslista alueella {a}. {c} Yhteensä {t} ravintolaa ja kahvilaa, Oiva-arvosanat mukana.",
           "cheapest": "Halvin lounas tänään {p}.", "show_map": "Näytä kartalla", "areas_h1": "Lounas Helsingissä alueittain",
           "areas_title": "Lounas Helsingissä alueittain | Päivän lounas", "lists": "listaa", "places": "paikkaa",
           "venue_h1": "{n} – lounas tänään", "venue_title": "{n} lounas tänään – lounaslista | Päivän lounas",
           "venue_desc": "{n} ({a}): päivän lounaslista, hinnat, ruokavaliot ja Oiva-arvosana.",
           "list_for": "Lounaslista {d}", "week": "Tämän viikon listat", "nearby_h": "Lähellä tänään", "g_reviews": "Arviot Google Mapsissa", "like": "Söin täällä – hyvä lounas", "liked": "Kiitos! Merkitty suositukseksi", "pop_n": "kävijää suosittelee (30 pv)", "nearby_p": "Näillä lähimmillä ravintoloilla on tämän päivän lounaslista:", "nomenu": "Tämän päivän listaa ei ole saatavilla. Katso ravintolan omat sivut.",
           "src": "Lähde", "orig": "alkuperäinen lista", "oiva": "Oiva-arvosana", "oiva_rep": "Oiva-raportti", "website": "Ravintolan verkkosivu",
           "route": "Reittiohjeet", "park": "Halvin parkki lähellä (Parkpenny)", "oiva_txt": {"A": "Oivallinen", "B": "Hyvä", "C": "Korjattavaa", "D": "Huono"},
           "wrong": "Väärä tieto?", "wrong_ok": "Kiitos ilmoituksesta!", "report_h": "Onko tämä sinun ravintolasi?", "report_p": "Kerro, missä lounaslistasi julkaistaan (oma sivu, Facebook-sivu tai pdf). Haemme sen jatkossa automaattisesti joka aamu – sinun ei tarvitse tehdä muuta.",
           "report_url": "Lounaslistan osoite", "report_btn": "Lähetä", "report_ok": "Kiitos! Tarkistamme osoitteen seuraavassa päivityksessä.",
           "footer1": "Lounaslistat haetaan automaattisesti ravintoloiden ja ketjujen omista lähteistä joka arkiaamu. Tarkista erityisruokavaliot aina ravintolasta.",
           "footer2": "Elintarvikevalvonnan tulokset: Oiva / Ruokavirasto (oivahymy.fi). Osoitteet ja kaupunginosat: Helsingin kaupunki, CC BY 4.0. Kartta: © OpenStreetMapin tekijät.",
           "about": "/tietoa/", "about_l": "Tietoa palvelusta", "privacy": "/tietosuoja/", "privacy_l": "Tietosuoja",
           "preview": "Esikatselu – sivusto on vielä kehitysvaiheessa", "notfound": "Sivua ei löytynyt", "tohome": "Etusivulle", "crumb_home": "Etusivu", "lang": "fi", "menu_lang": ""},
    "en": {"home": "/en/", "areas": "/en/lunch/", "area": "/en/lunch/{s}/", "venue": "/en/restaurant/{s}/", "nav_areas": "Areas", "other": "Suomeksi", "other_home": "/",
           "wd": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
           "wd_short": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
           "h1_home": "Lunch in Helsinki", "v_map": "Map", "v_list": "List", "d_list": "List", "d_map": "Map", "d_filter": "Filter", "d_big": "Full map", "d_back": "Back to list", "sheet_label": "Lunches nearby", "locate": "Find my location", "sheet_more": "Show more", "as_list": "Show as list", "done": "Done", "search_ph": "Search food or place",
           "pills": [("near", "Nearby"), ("pop", "Most liked"), ("cheap", "Cheapest"), ("veg", "Vegetarian"), ("stu", "Student")], "search": "Search restaurant, dish or area", "near": "Near me",
           "cats": [("soup", "Soup"), ("fish", "Fish"), ("chicken", "Chicken"), ("meat", "Meat"), ("veg", "Vegetarian"), ("pasta", "Pasta"), ("pizza", "Pizza"), ("burger", "Burger"), ("asian", "Asian"), ("salad", "Salad"), ("buffet", "Buffet")],
           "chips": [("fav", "Favourites"), ("menu", "With menu"), ("stu", "Student price"), ("open", "Open now"), ("u13", "Under 13 €"), ("cheap", "Cheapest first"), ("Veg", "Vegetarian"), ("G", "GF"), ("L", "LF"), ("M", "DF"), ("oivaA", "Oiva A")],
           "title_home": "Lunch in Helsinki today – lunch menus on a map | Päivän lounas",
           "desc_home": "Helsinki lunch menus today ({d}): {n} restaurants with menus, prices, diets and food-safety ratings on a map.",
           "area_h1": "Lunch in {a} today", "area_title": "Lunch in {a} today – {n} lunch menus | Päivän lounas",
           "area_lead": "{d}: {n} restaurants in {a} with today's lunch menu. {c} {t} restaurants and cafés in total, with Oiva food-safety ratings.",
           "cheapest": "Cheapest lunch today {p}.", "show_map": "Show on map", "areas_h1": "Lunch in Helsinki by area",
           "areas_title": "Lunch in Helsinki by area | Päivän lounas", "lists": "menus", "places": "places",
           "venue_h1": "{n} – lunch today", "venue_title": "{n} lunch today – lunch menu | Päivän lounas",
           "venue_desc": "{n} ({a}): today's lunch menu, prices, diets and Oiva food-safety rating.",
           "list_for": "Lunch menu {d}", "week": "This week's menus", "nearby_h": "Nearby today", "g_reviews": "Reviews on Google Maps", "like": "I ate here – good lunch", "liked": "Thanks! Counted as a recommendation", "pop_n": "visitors recommend (30 days)", "nearby_p": "The closest restaurants with today's lunch menu:", "nomenu": "Today's menu is not available. See the restaurant's own website.",
           "src": "Source", "orig": "original menu", "oiva": "Oiva food-safety rating", "oiva_rep": "Oiva report", "website": "Restaurant website",
           "route": "Directions", "park": "Cheapest parking nearby (Parkpenny)", "oiva_txt": {"A": "Excellent", "B": "Good", "C": "To be corrected", "D": "Poor"},
           "wrong": "Wrong info?", "wrong_ok": "Thanks for letting us know!", "report_h": "Is this your restaurant?", "report_p": "Tell us where your lunch menu is published (website, Facebook page or pdf). We will fetch it automatically every morning – nothing else is needed.",
           "report_url": "Lunch menu address", "report_btn": "Send", "report_ok": "Thank you! We will check the address in the next update.",
           "footer1": "Lunch menus are fetched automatically from restaurants' and chains' own sources every weekday morning. Menus are shown in the language the restaurant publishes them (mostly Finnish). Always check special diets with the restaurant.",
           "footer2": "Food-control results: Oiva / Finnish Food Authority (oivahymy.fi). Addresses and districts: City of Helsinki, CC BY 4.0. Map: © OpenStreetMap contributors.",
           "about": "/en/about/", "about_l": "About", "privacy": "/en/privacy/", "privacy_l": "Privacy",
           "preview": "Preview – the site is still under development", "notfound": "Page not found", "tohome": "Front page", "crumb_home": "Home", "lang": "en", "menu_lang": "en"},
}


ADSENSE = os.environ.get("ADSENSE_CLIENT", "").strip()  # ca-pub-…; empty = no ads anywhere
# reserved ad places (Branu 26.11.: ad-funded, ads must not be in the way). Empty until AdSense approves the site and
# ad units exist: ADSENSE_SLOTS='{"card": "<slot id>", "list": "<slot id>", "content": "<slot id>"}'
try:
    AD_SLOTS = json.loads(os.environ.get("ADSENSE_SLOTS") or "{}") if ADSENSE else {}
except ValueError:
    AD_SLOTS = {}


def ad_block(kind, lg):
    """One ad after the page's own answer (restaurant menu, district picks) – never above it, never on the map."""
    sl = AD_SLOTS.get(kind)
    if not sl:
        return ""
    return (f'<div class="adslot"><span class="adlbl">{"Mainos" if lg == "fi" else "Advertisement"}</span>'
            f'<ins class="adsbygoogle" style="display:block" data-ad-client="{esc(ADSENSE)}" data-ad-slot="{esc(sl)}" data-ad-format="auto" data-full-width-responsive="true"></ins>'
            f'<script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script></div>')
CONTACT = "info@paivanlounas.fi"
OWNER = "BR Entertainment (toiminimi), Y-tunnus 3183394-5"


# ---- indexing gate (spam rule, Branu 25.11.2026: claude/kirjasto/10-spamsuoja.md) ----
# A page goes to the index and the sitemap only if it has its own data that answers its question.
# Everything else is still built for visitors but gets noindex, no sitemap entry and no ads.
GATE = {
    "venue": 30,        # restaurant page: a lunch menu on some day in the last 30 days, OR search visitors land on it
                        # (counters 'land', 60 days), OR its own site talks about lunch, OR >= 3 lunch menus within 1 km
                        # (the page then answers "lunch near X" with its own data) – Branu 26.11.: never drop what people look for
    "venue_near": 3,
    "area": 1,          # district page: at least 1 restaurant with a menu this week
    "topic": 5,         # cheapest / vegetarian / buffet page: at least 5 restaurants today
    "areas_index": 1,   # list of districts: at least one indexable district
    "en": {"/en/"},     # English: only the front page until Search Console shows demand (language gate)
}
SITEMAP = {}            # path -> data signature, filled by add_url()
GATE_ON = os.environ.get("LOUNAS_GATE") == "1"  # off until Branu approves publishing the gate (N25); then set in the workflow


def add_url(path, ok, sig):
    """Gate decision for one page. Returns True if it may be indexed (then it also goes to the sitemap)."""
    if not GATE_ON:
        ok = True
    elif path.startswith("/en/") and path not in GATE["en"]:
        ok = False
    if ok:
        SITEMAP[path] = hashlib.md5(json.dumps(sig, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return ok


def write_sitemap(out, root, today):
    """lastmod = the day the page's data last changed (stored in data/lastmod.json between runs), not the build day."""
    lp = os.path.join(root, "data", "lastmod.json")
    old = json.load(open(lp)) if os.path.exists(lp) else {}
    new = {}
    for path, h in SITEMAP.items():
        prev = old.get(path)
        new[path] = prev if prev and prev[0] == h else [h, today]
    json.dump(new, open(lp, "w"), ensure_ascii=False)
    sm = "".join(f"<url><loc>{DOMAIN}{u}</loc><lastmod>{new[u][1]}</lastmod></url>" for u in sorted(new))
    open(f"{out}/sitemap.xml", "w").write(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
    return len(new)


def ads_tag(path):
    """AdSense script on every page (site verification needs the front page too).
    Keep auto ads off the map app with AdSense's page exclusions (/ and /en/)."""
    if not ADSENSE or path.startswith("/404"):
        return ""
    return f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={esc(ADSENSE)}" crossorigin="anonymous"></script>'


TOPIC_T = {
    "fi": {"today": "tänään", "more": "Lisää lounaslistoja", "areas": "Suosituimmat alueet", "empty": "Tänään ei löytynyt listoja.",
           "cheap": {"path": "/halvin-lounas-helsinki/", "h1": "Halvin lounas Helsingissä", "title": "Halvin lounas Helsingissä tänään – alle 13 € | Päivän lounas",
                     "desc": "Helsingin halvimmat lounaat tänään ({d}): {n} lounasta alle 13 eurolla hintoineen ja ruokalistoineen.",
                     "lead": "{d}: <b>{n} lounasta alle 13 eurolla</b>, halvin {p}. Lista päivittyy joka arkiaamu.",
                     "outro": "Hinta on ravintolan ilmoittama tavallinen lounashinta. Opiskelija- ja henkilökuntahinnat voivat olla edullisempia."},
           "veg": {"path": "/kasvislounas-helsinki/", "h1": "Kasvislounas Helsingissä", "title": "Kasvislounas Helsingissä tänään – kasvis- ja vegaanilounaat | Päivän lounas",
                   "desc": "Kasvislounas Helsingissä tänään ({d}): {n} ravintolaa, joiden listalla on kasvis- tai vegaaniannos.",
                   "lead": "{d}: <b>{n} ravintolaa</b>, joiden lounaslistalla on kasvis- tai vegaaniannos, alueittain. Halvin {p}.",
                   "outro": "Merkinnät (Veg, K, vegaani) tulevat ravintolan omalta listalta. Tarkista erityisruokavaliot aina ravintolasta."},
           "buffet": {"path": "/buffet-lounas-helsinki/", "h1": "Buffet-lounas Helsingissä", "title": "Buffet-lounas Helsingissä tänään – noutopöydät | Päivän lounas",
                      "desc": "Buffet-lounaat Helsingissä tänään ({d}): {n} noutopöytälounasta alueittain hintoineen.",
                      "lead": "{d}: <b>{n} buffet- ja noutopöytälounasta</b> alueittain. Halvin {p}.",
                      "outro": "Hinnat ja sisältö ravintolan omalta listalta."}},
    "en": {"today": "today", "more": "More lunch lists", "areas": "Popular areas", "empty": "No menus found today.",
           "cheap": {"path": "/en/cheap-lunch-helsinki/", "h1": "Cheapest lunch in Helsinki", "title": "Cheapest lunch in Helsinki today – under 13 € | Päivän lounas",
                     "desc": "The cheapest lunches in Helsinki today ({d}): {n} lunches under 13 euros with prices and menus.",
                     "lead": "{d}: <b>{n} lunches under 13 euros</b>, cheapest {p}. Updated every weekday morning.",
                     "outro": "The price is the restaurant's regular lunch price. Student and staff prices may be lower."},
           "veg": {"path": "/en/vegetarian-lunch-helsinki/", "h1": "Vegetarian lunch in Helsinki", "title": "Vegetarian lunch in Helsinki today – vegetarian and vegan | Päivän lounas",
                   "desc": "Vegetarian lunch in Helsinki today ({d}): {n} restaurants with a vegetarian or vegan dish.",
                   "lead": "{d}: <b>{n} restaurants</b> with a vegetarian or vegan dish, by area. Cheapest {p}.",
                   "outro": "Diet markings come from the restaurant's own menu. Always check special diets with the restaurant."},
           "buffet": {"path": "/en/buffet-lunch-helsinki/", "h1": "Buffet lunch in Helsinki", "title": "Buffet lunch in Helsinki today | Päivän lounas",
                      "desc": "Buffet lunches in Helsinki today ({d}): {n} all-you-can-eat lunches by area with prices.",
                      "lead": "{d}: <b>{n} buffet lunches</b> by area. Cheapest {p}.",
                      "outro": "Prices and contents from the restaurant's own menu."}},
}


AREA_T = {
    "fi": {"cheap_h": "Alle 13 euroa", "cheap_p": "Edullisimmat lounaat alueella {a} tänään", "veg_h": "Kasvisvaihtoehdot", "veg_p": "Listalla vähintään yksi kasvisannos",
           "buf_h": "Buffet-lounaat", "buf_p": "Noutopöytä – syö niin paljon kuin jaksat", "all_h": "Kaikki {n} lounaslistaa", "all_p": "Aakkosjärjestyksessä",
           "all_j": "Kaikki {n}", "rest": "Muut ravintolat ja kahvilat ilman tämän päivän listaa ({n})", "until": "lounas ",
           "lead": "{d}: <b>{n} ravintolan lounaslista</b>. {c} Kasvisvaihtoehto {v} paikassa.", "lead0": "{d}: alueelta ei löytynyt tämän päivän lounaslistoja. Alueella on {t} ravintolaa ja kahvilaa.",
           "none": "Alueelta {a} ei löytynyt tämän päivän lounaslistoja. Katso lähialueet.",
           "trust": "Listat haetaan joka arkiaamu ravintoloiden ja ketjujen omista lähteistä. Lähde ja alkuperäinen lista näkyvät ravintolan sivulla.",
           "jump": "Osiot", "share_h": "Jaa päivän halvimmat", "share_p": "Kuva päivittyy joka aamu. Lähetä se työkavereille tai WhatsApp-ryhmään.", "share_b": "Jaa", "share_dl": "Lataa kuva", "map_h": "Kartalla", "map_p": "{n} listaa alueella {a} kartalla – lähin ja halvin heti näkyviin.", "near_h": "Lähialueet",
           "rest_h": "Puuttuuko listasi?", "rest_p": "Kerro ravintolasi sivulla, missä lounaslistasi julkaistaan. Haemme sen joka aamu automaattisesti.",
           "desc": "Lounas {a} tänään ({d}): {n} lounaslistaa hintoineen. {c} Kasvis-, buffet- ja halvimmat lounaat sekä Oiva-arvosanat."},
    "en": {"cheap_h": "Under 13 euros", "cheap_p": "The most affordable lunches in {a} today", "veg_h": "Vegetarian options", "veg_p": "At least one vegetarian dish on the menu",
           "buf_h": "Buffet lunches", "buf_p": "All you can eat", "all_h": "All {n} lunch menus", "all_p": "In alphabetical order",
           "all_j": "All {n}", "rest": "Other restaurants and cafés without today's menu ({n})", "until": "lunch ",
           "lead": "{d}: <b>{n} restaurants with today's lunch menu</b>. {c} Vegetarian option in {v} places.", "lead0": "{d}: no lunch menus found in this area today. The area has {t} restaurants and cafés.",
           "none": "No lunch menus found in {a} today. See nearby areas.",
           "trust": "Menus are fetched every weekday morning from restaurants' and chains' own sources. The source and original menu are shown on each restaurant's page.",
           "jump": "Sections", "share_h": "Share today's cheapest", "share_p": "The picture updates every morning. Send it to colleagues or a WhatsApp group.", "share_b": "Share", "share_dl": "Download", "map_h": "On the map", "map_p": "{n} menus in {a} on the map – nearest and cheapest first.", "near_h": "Nearby areas",
           "rest_h": "Is your menu missing?", "rest_p": "Tell us on your restaurant's page where your lunch menu is published. We fetch it automatically every morning.",
           "desc": "Lunch in {a} today ({d}): {n} lunch menus with prices. {c} Vegetarian, buffet and cheapest lunches plus Oiva ratings."},
}


SHARE_JS = """<script>document.querySelectorAll('[data-share]').forEach(function(b){b.addEventListener('click',async function(){
var u=location.href,t=b.getAttribute('data-title');
try{var r=await fetch(b.getAttribute('data-share'));var f=new File([await r.blob()],'lounas.png',{type:'image/png'});
if(navigator.canShare&&navigator.canShare({files:[f]})){await navigator.share({files:[f],title:t,text:t+' '+u});return}}catch(e){if(e&&e.name==='AbortError')return}
if(navigator.share){try{await navigator.share({title:t,url:u})}catch(e){}return}
try{await navigator.clipboard.writeText(u);b.textContent='\u2713'}catch(e){location.href=b.getAttribute('data-share')}})});</script>"""


def area_near(vs, lg):
    """District without menus today: never an empty answer – the 5 nearest lunches (own data)."""
    pts = [v for v in vs if v.get("lat")]
    if not pts or not TODAY_M:
        return ""
    la, lo = sum(v["lat"] for v in pts) / len(pts), sum(v["lon"] for v in pts) / len(pts)
    cl = math.cos(math.radians(la))
    dd = sorted(TODAY_M, key=lambda w: (w["lat"] - la) ** 2 + ((w["lon"] - lo) * cl) ** 2)[:5]
    t = T[lg]
    li = "".join(f'<li><a href="{t["venue"].format(s=w["slug"])}">{esc(w["name"])}</a> <span class="mdish">{esc(clean_dish(w["menu"]["items"][0]["d"][0]))}</span>'
                 f'<span class="price">{fmt_price(lunch_price(w["menu"])) if lunch_price(w["menu"]) else ""}</span><small>{esc(w.get("district") or "")}</small></li>' for w in dd)
    return f'<section class="nearby"><h2>{t["nearby_h"]}</h2><p>{t["nearby_p"]}</p><ul class="picks">{li}</ul></section>'


TODAY_M = []


def share_image(out, key, title, ds_, items, mp, url_path):
    """/jako/<key>.png – cheapest lunches of the day as a picture for WhatsApp / Instagram; None if not enough priced menus."""
    rows = sorted([v for v in items if mp.get(v["slug"])], key=lambda v: mp[v["slug"]])[:6]
    if len(rows) < 3:
        return None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import share_img
        os.makedirs(f"{out}/jako", exist_ok=True)
        share_img.make(f"{out}/jako/{key}.png", "Halvimmat lounaat tänään", title, ds_,
                       [(v["name"], clean_dish(v["menu"]["items"][0]["d"][0]), fmt_price(mp[v["slug"]])) for v in rows], "paivanlounas.fi" + url_path)
        return f"/jako/{key}.png"
    except Exception as e:  # never let a picture break the daily build
        print("share image failed", key, e, file=sys.stderr)
        return None


def page_type(path):
    p = path[3:] if path.startswith("/en/") else path
    if p in ("/", ""):
        return "home"
    for k, pre in (("venue", ("/ravintola/", "/restaurant/")), ("area", ("/lounas/", "/lunch/"))):
        if p.startswith(pre):
            return k
    if any(p == TOPIC_T[l][k]["path"].replace("/en", "", 1) for l in TOPIC_T for k in ("cheap", "veg", "buffet")):
        return "topic"
    return "info"


def page(lg, title, desc, path, alt_path, body, preview, extra_head="", og_image=None, index=True, has_list=True):
    t = T[lg]
    extra_head += ads_tag(path) if index else ""  # ads only on pages with own data
    robots = '<meta name="robots" content="noindex,nofollow">' if preview else ("" if index else '<meta name="robots" content="noindex,follow">')
    if GATE_ON and not (alt_path and alt_path in SITEMAP and path in SITEMAP) and path not in ("/", "/en/"):
        alt_path_hl = None  # hreflang only between two indexable versions
    else:
        alt_path_hl = alt_path
    bar = f'<div class="preview">{t["preview"]}</div>' if preview else ""
    other = "en" if lg == "fi" else "fi"
    hl = (f'<link rel="alternate" hreflang="{lg}" href="{DOMAIN}{path}"><link rel="alternate" hreflang="{other}" href="{DOMAIN}{alt_path}">'
          f'<link rel="alternate" hreflang="x-default" href="{DOMAIN}{path if lg == "fi" else alt_path}">') if alt_path_hl else ""
    pk = path.rstrip("/").rsplit("/", 1)[-1][:40] if page_type(path) in ("venue", "area") else ""
    ads_attr = f' data-ads="{esc(json.dumps({"c": ADSENSE, **AD_SLOTS}))}"' if AD_SLOTS and index else ""
    return f"""<!doctype html><html lang="{lg}" data-pt="{page_type(path)}" data-hl="{1 if has_list else 0}" data-k="{pk}"{ads_attr}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{DOMAIN}{path}">{hl}{robots}
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/apple-touch-icon.png"><meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#221a16" media="(prefers-color-scheme: dark)"><meta name="color-scheme" content="light dark">
<meta property="og:image" content="{DOMAIN}{og_image or '/icon-512.png'}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:type" content="website">
<link rel="stylesheet" href="/style.css?v={VER['style.css']}">{extra_head}<script src="/m.js?v={VER['m.js']}" defer></script></head><body>{bar}
<header class="top"><a class="logo" href="{t['home']}"><img src="/favicon.svg" width="28" height="28" alt="">Päivän lounas</a><nav><a href="{t['areas']}">{t['nav_areas']}</a><a href="{alt_path or t['other_home']}" hreflang="{other}">{t['other']}</a></nav></header>
{body}
<footer><p class="flinks">{' · '.join(f'<a href="{TOPIC_T[lg][k]["path"]}">{TOPIC_T[lg][k]["h1"]}</a>' for k in ("cheap", "veg", "buffet"))}</p><p>{t['footer1']}</p><p>{t['footer2']}</p><p>© 2026 Päivän lounas · <a href="{t['about']}">{t['about_l']}</a> · <a href="{t['privacy']}">{t['privacy_l']}</a> · {CONTACT}</p></footer></body></html>"""


def fmt_price(p):
    return f"{p:.2f} €".replace(".", ",")


def menu_html(m, lg, slug_=None, day=None, show_src=True):
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
    if not show_src:
        src = f'<p class="src">{wrong[3:]}</p>' if wrong else ""
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
    def assign_slugs(vs):
        seen_, out_ = {}, []
        for v in vs:
            s_ = slug(v["name"])
            if s_ in seen_:
                s_ = f"{s_}-{slug(v['street'] or '')[:30]}".strip("-")
            if s_ in seen_:
                s_ = f"{s_}-{len(seen_)}"
            seen_[s_] = 1
            out_.append(s_)
        return out_
    legacy = list(zip(assign_slugs(venues), venues))  # addresses before merging duplicates – they get 301s below
    merged = {}  # id(dropped venue) -> kept venue
    GENERIC = {"ravintola", "restaurant", "cafe", "café", "kahvila", "helsinki", "lounas", "bar", "bistro", "kitchen", "and", "the"}
    def words(n):
        return {w for w in re.findall(r"[a-zåäö0-9]+", n.lower()) if len(w) > 3 and w not in GENERIC}
    for v in venues:  # tidy shouting menus
        for m in v["ms"].values():
            for it in m["items"]:
                it["d"] = [decap(x) for x in it["d"]]
                if it.get("t"):
                    it["t"] = decap(it["t"])
    sig, drop = {}, set()
    for i, v in enumerate(venues):  # same venue twice in the registry: same menu, <250 m apart, a shared name word
        if not v["menu"]:
            continue
        key = " | ".join(" ".join(it["d"]) for it in v["menu"]["items"]).lower()[:300]
        for j in sig.get(key, []):
            w = venues[j]
            if abs(w["lat"] - v["lat"]) < 0.0023 and abs(w["lon"] - v["lon"]) < 0.0045 and words(w["name"]) & words(v["name"]):
                lose, keep = (i, j) if (w.get("oiva") or w.get("website") or len(w["ms"]) >= len(v["ms"])) else (j, i)
                drop.add(lose); merged[id(venues[lose])] = venues[keep]
                break
        sig.setdefault(key, []).append(i)
    byns = {}
    for i, v in enumerate(venues):  # same name at the same street address = one restaurant (rule: one page per question)
        k = (norm(v["name"]), norm(v.get("street") or ""))
        if k in byns and i not in drop:
            j = byns[k]
            keep_j = bool(venues[j]["ms"]) >= bool(v["ms"])
            lose, keep = (i, j) if keep_j else (j, i)
            drop.add(lose); merged[id(venues[lose])] = venues[keep]
            if not keep_j:
                byns[k] = i
        else:
            byns.setdefault(k, i)
    if drop:
        print("duplicates merged", len(drop), sorted(venues[i]["name"] for i in drop)[:30], file=sys.stderr)
    venues = [v for i, v in enumerate(venues) if i not in drop]
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
    os.makedirs(f"{out}/data", exist_ok=True)
    if os.path.exists(rp):  # for the daily check: which menus people say are wrong
        json.dump(sorted(({"venue": k[0], "day": k[1], "n": n} for k, n in reps.items()), key=lambda x: -x["n"])[:100],
                  open(f"{out}/data/reports.json", "w"), ensure_ascii=False)
    with_menu = [v for v in venues if v["menu"]]
    TODAY_M[:] = with_menu
    print("venues", len(venues), "with menu", show_day, len(with_menu), "| week", {d: sum(1 for v in venues if d in v["ms"]) for d in days}, file=sys.stderr)

    LIKES = {}
    lk_ = f"{L}/data/likes_raw.json"
    if os.path.exists(lk_):
        try:
            LIKES = {r["venue"]: int(r["n"]) for r in json.load(open(lk_))[0]["results"]}
        except Exception as e:
            print("likes unreadable", e, file=sys.stderr)
    os.makedirs(f"{out}/data", exist_ok=True)
    st = f"{L}/data/ai_stats.json"
    if os.path.exists(st):
        shutil.copy(st, f"{out}/data/status.json")
    app = [{"i": v["slug"], "n": v["name"], "a": v["street"], "y": round(v["lat"], 5), "x": round(v["lon"], 5),
            "o": (v["oiva"] or {}).get("grade"), "d": v["district"], "w": v.get("website"), "ms": v["ms"],
            **({"lk": LIKES[v["slug"]]} if LIKES.get(v["slug"]) else {})} for v in venues]
    json.dump({"date": show_day, "days": days, "venues": app}, open(f"{out}/data/week.json", "w"), ensure_ascii=False, separators=(",", ":"))

    here = os.path.dirname(__file__)
    for f in ("style.css", "app.js", "suggest.js", "m.js", "favicon.svg", "favicon.ico", "apple-touch-icon.png", "icon-48.png", "icon-192.png", "icon-512.png", "logo.png", "brand.html"):
        shutil.copy(os.path.join(here, f), f"{out}/{f}")
    os.makedirs(f"{out}/vendor/leaflet/images", exist_ok=True)
    lf = os.path.join(here, "..", "node_modules", "leaflet", "dist")
    for f in ("leaflet.js", "leaflet.css"):
        shutil.copy(f"{lf}/{f}", f"{out}/vendor/leaflet/{f}")
    os.makedirs(f"{out}/vendor/maplibre", exist_ok=True)  # clean vector basemap (OpenFreeMap), loaded after the page
    nm = os.path.join(here, "..", "node_modules")
    for src, dst in ((f"{nm}/maplibre-gl/dist/maplibre-gl.js", "maplibre-gl.js"), (f"{nm}/maplibre-gl/dist/maplibre-gl.css", "maplibre-gl.css"),
                     (f"{nm}/@maplibre/maplibre-gl-leaflet/leaflet-maplibre-gl.js", "leaflet-maplibre-gl.js")):
        if os.path.exists(src):
            shutil.copy(src, f"{out}/vendor/maplibre/{dst}")
    for f in os.listdir(f"{lf}/images"):
        shutil.copy(f"{lf}/images/{f}", f"{out}/vendor/leaflet/images/{f}")
    os.makedirs(f"{out}/fonts", exist_ok=True)
    fs = os.path.join(here, "..", "node_modules", "@fontsource")
    for src, dst in (("inter/files/inter-latin-400-normal.woff2", "inter-400.woff2"), ("inter/files/inter-latin-600-normal.woff2", "inter-600.woff2"),
                     ("inter/files/inter-latin-700-normal.woff2", "inter-700.woff2"),
                     ("bricolage-grotesque/files/bricolage-grotesque-latin-800-normal.woff2", "bricolage-800.woff2")):
        shutil.copy(os.path.join(fs, src), f"{out}/fonts/{dst}")

    urls = []
    # last day each restaurant had a menu (kept between runs) – the restaurant-page gate looks back GATE["venue"] days
    sp = f"{L}/data/menu_seen.json"
    SEEN = json.load(open(sp)) if os.path.exists(sp) else {}
    for v in venues:
        got = [d for d, m in v["ms"].items() if m and m.get("items")]
        if got:
            SEEN[v["slug"]] = max([SEEN.get(v["slug"], "")] + got)
    json.dump(SEEN, open(sp, "w"))
    since = (datetime.date.today() - datetime.timedelta(days=GATE["venue"])).isoformat()
    LANDED = set()
    lp_ = f"{L}/data/landed_raw.json"
    if os.path.exists(lp_):
        try:
            LANDED = {r["key"] for r in json.load(open(lp_))[0]["results"]}
        except Exception as e:
            print("landed unreadable", e, file=sys.stderr)
    wp_ = f"{L}/data/web_pages.json"
    LUNCHY = set(json.load(open(wp_))) if os.path.exists(wp_) else set()
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
        cats = "".join(f'<button data-cat="{k}">{esc(lbl)}</button>' for k, lbl in t["cats"])
        pills_html = "".join(f'<button type="button" data-pill="{k}"' + (' class="on"' if k == "near" else "") + f'>{esc(l)}</button>' for k, l in t["pills"])
        dchips = "".join(f'<button data-day="{d}"{" class=on" if d == show_day else ""}>{t["wd_short"][i]} {int(d[8:])}.{int(d[5:7])}.</button>' for i, d in enumerate(days))
        body = f"""<main class="app" data-lang="{lg}">
<div class="days daybar">{dchips}</div>
<section class="panel" id="panel">
<button type="button" id="pdone" class="pdone">{t['done']}</button>
<div id="sel" class="selcard" hidden></div>
<div class="ptop"><div><p class="sub" id="dlabel">{esc(ds_)}</p><h1>{t['h1_home']}</h1></div>
<div class="views" role="tablist"><button data-view="split" class="on">{t['v_map']}</button><button data-view="list">{t['v_list']}</button></div></div>
<div class="cats" id="cats" role="group">{cats}</div>
<div class="search"><input id="q" type="search" placeholder="{esc(t['search'])}" aria-label="{esc(t['search'])}"><button id="near" type="button">{t['near']}</button></div>
<section class="top3" id="top3s" aria-labelledby="t3h" hidden><div class="t3head"><h2 id="t3h"></h2></div><div id="top3" class="t3"></div></section>
<div class="chips" id="chips">{chips}</div><p id="count" class="count"></p><ol id="list" class="list"></ol><button id="more" class="btn ghost more" hidden></button>
<p class="hl">{' · '.join(f'<a href="{TOPIC_T[lg][k]["path"]}">{TOPIC_T[lg][k]["h1"]}</a>' for k in ("cheap", "veg", "buffet"))} · <a href="{t['areas']}">{t['nav_areas']}</a></p>
</section>
<div id="map" role="region" aria-label="{t['v_map']}" data-big="{t['d_big']}" data-back="{t['d_back']}"></div>
<div class="mtop" id="mtop"><label class="msearch"><span class="sr">{t['search_ph']}</span><input id="q2" type="search" autocomplete="off" placeholder="{t['search_ph']}"></label><button id="mfilt" type="button" class="mfbtn">{t['d_filter']}</button></div>
<button type="button" class="locfab" id="locfab" aria-label="{t['locate']}" title="{t['locate']}"><svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path fill="currentColor" d="M21 3 3 10.5l7.2 2.3L12.5 20z"/></svg></button>
<section class="sheet" id="sheet" aria-label="{t['sheet_label']}">
<button type="button" class="grab" id="grab" aria-label="{t['sheet_more']}"><span></span></button>
<h2 id="shTitle"></h2>
<ul id="shRows" class="shrows"></ul>
<div class="shfull"><div class="pills" role="group">{pills_html}</div>
<div class="cards" id="cards"></div><p class="cardnav"><span id="cardPos"></span><button type="button" id="asList" class="linkbtn">{t['as_list']}</button></p></div>
</section>
</main>
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css"><script src="/vendor/leaflet/leaflet.js"></script><script src="/app.js?v={VER['app.js']}"></script><script src="/suggest.js?v={VER['suggest.js']}" defer></script>"""
        ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": SITE, "url": DOMAIN + t["home"], "inLanguage": lg},
              {"@context": "https://schema.org", "@type": "Organization", "name": SITE, "url": DOMAIN + "/", "logo": DOMAIN + "/icon-512.png"}]
        hp = t["home"]
        os.makedirs(f"{out}{hp}", exist_ok=True)
        ix = add_url(hp, len(with_menu) > 0, [(v["slug"], v["menu"]) for v in with_menu])
        open(f"{out}{hp}index.html", "w").write(page(lg, t["title_home"], t["desc_home"].format(d=ds_, n=len(with_menu)), hp, T[other]["home"], body, preview,
                                                       f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>', index=ix))
        # districts (digest layout: sections people scan, then the full list)
        A = AREA_T[lg]
        cent = {k: (sum(v["lat"] for v in vs) / len(vs), sum(v["lon"] for v in vs) / len(vs)) for k, vs in by_d.items()}
        nmenu = {k: sum(1 for v in vs if v["menu"]) for k, vs in by_d.items()}
        idx = []
        n_area_ix = 0
        for (dslug, dn), vs in sorted(by_d.items(), key=lambda x: x[0][1]):
            withm = [v for v in vs if v["menu"]]
            nm = len(withm)
            mp = {}
            for v in withm:
                ps = [i["p"] for i in v["menu"]["items"] if i.get("p") and 5 <= i["p"] <= 25]
                mp[v["slug"]] = min(ps) if ps else None
            prices = [x for x in mp.values() if x]
            cheapest = t["cheapest"].format(p=fmt_price(min(prices))) if prices else ""
            def clean(d):
                d = re.sub(r"\s*\((?:[A-Za-z]{1,4}[\s,+*/]*)+\)", "", d)
                return re.sub(r"[\s,;·]+$", "", d)
            def txt(v):
                return " ".join(" ".join(i["d"]) + " " + (i.get("t") or "") for i in v["menu"]["items"]).lower()
            cheap = sorted([v for v in withm if mp[v["slug"]] and mp[v["slug"]] < 13], key=lambda v: mp[v["slug"]])[:6]
            veg = [v for v in withm if any(("Veg" in i.get("diet", []) or "Kasvis" in i.get("diet", [])) for i in v["menu"]["items"]) or re.search(r"kasvis|vegaan|vegan|vegetar", txt(v))]
            nveg = len(veg)
            veg = sorted(veg, key=lambda v: (mp[v["slug"]] or 99))[:6]
            buf = sorted([v for v in withm if re.search(r"buffet|noutopöytä|seisova", txt(v))], key=lambda v: v["name"])[:6]
            def mini(v):
                m = v["menu"]
                pr = fmt_price(mp[v["slug"]]) if mp.get(v["slug"]) else ""
                return (f'<li><a href="#v-{v["slug"]}">{esc(v["name"])}</a> <span class="mdish">{esc(clean(m["items"][0]["d"][0]))}</span><span class="price">{pr}</span></li>')
            def ent(v):
                m = v["menu"]; o = (v["oiva"] or {}).get("grade")
                dishes = " · ".join(clean(i["d"][0]) for i in m["items"][:4])
                meta = " · ".join(x for x in (v["street"], (t["oiva"] + " " + t["oiva_txt"][o]) if o in ("A", "B") else "", (A["until"] + m["hours"]) if m.get("hours") else "") if x)
                pr = fmt_price(mp[v["slug"]]) if mp.get(v["slug"]) else ""
                return (f'<article class="ent" id="v-{v["slug"]}"><div class="row"><h3><a href="{t["venue"].format(s=v["slug"])}">{esc(v["name"])}</a></h3><span class="price">{pr}</span></div>'
                        f'<p class="dish">{esc(dishes)}</p><p class="meta">{esc(meta)}</p></article>')
            secs, jumps = [], []
            for sid, title, lead, items in (("halvat", A["cheap_h"], A["cheap_p"].format(a=dn), cheap), ("kasvis", A["veg_h"], A["veg_p"], veg),
                                            ("buffet", A["buf_h"], A["buf_p"], buf)):
                if len(items) >= 2:
                    secs.append(f'<section class="sec" id="{sid}"><h2>{title}</h2><ul class="picks">{"".join(mini(v) for v in items)}</ul></section>')
                    jumps.append(f'<a href="#{sid}">{title}</a>')
            allm = sorted(withm, key=lambda v: v["name"].lower())
            if allm:
                if secs:
                    secs.append(ad_block("content", lg))
                secs.append(f'<section class="sec" id="kaikki"><h2>{A["all_h"].format(n=nm)}</h2>{"".join(ent(v) for v in allm)}</section>')
                jumps.append(f'<a href="#kaikki">{A["all_j"].format(n=nm)}</a>')
            others = sorted([v for v in vs if not v["menu"]], key=lambda v: v["name"].lower())
            if others:
                lis_o = "".join((f'<li><a href="{t["venue"].format(s=v["slug"])}">{esc(v["name"])}</a></li>' if (v["ms"] or v["sources"]) else f'<li>{esc(v["name"])}</li>') for v in others[:200])
                secs.append(f'<details class="rest"><summary>{A["rest"].format(n=len(others))}</summary><ul>{lis_o}</ul></details>')
            if not withm:
                secs.insert(0, f'<p class="nomenu">{A["none"].format(a=esc(dn))}</p>')
            img = share_image(out, dslug, dn, ds_, withm, mp, T["fi"]["area"].format(s=dslug)) if lg == "fi" else (f"/jako/{dslug}.png" if os.path.exists(f"{out}/jako/{dslug}.png") else None)
            share_box = (f'<div class="box share"><h2>{A["share_h"]}</h2><p style="margin:0 0 12px;color:var(--mut);font-size:14px">{A["share_p"]}</p>'
                         f'<img src="{img}" alt="" width="270" height="338" loading="lazy" style="width:100%;height:auto;border-radius:12px;border:1px solid var(--line)">'
                         f'<p style="margin:12px 0 0;display:flex;gap:8px;flex-wrap:wrap"><button class="btn" type="button" data-share="{img}" data-title="{esc(t["area_h1"].format(a=dn))}">{A["share_b"]}</button>'
                         f'<a class="btn ghost" href="{img}" download>{A["share_dl"]}</a></p></div>') if img else ""
            near = sorted((k for k in by_d if k[0] != dslug), key=lambda k: (cent[k][0] - cent[(dslug, dn)][0]) ** 2 + ((cent[k][1] - cent[(dslug, dn)][1]) * 0.5) ** 2)[:5]
            near_li = "".join(f'<li><a href="{t["area"].format(s=k[0])}">{esc(k[1])}</a> <small>· {nmenu[k]} {t["lists"]}</small></li>' for k in near)
            lead = A["lead"].format(d=esc(ds_), n=nm, c=esc(cheapest), v=nveg) if nm else A["lead0"].format(d=esc(ds_), t=len(vs))
            path, alt = t["area"].format(s=dslug), T[other]["area"].format(s=dslug)
            body = f"""<main class="content"><nav class="crumbs"><a href="{t['home']}">{t['crumb_home']}</a> › <a href="{t['areas']}">{t['nav_areas']}</a> › {esc(dn)}</nav>
<h1>{t['area_h1'].format(a=esc(dn))}</h1><p class="lead">{lead}</p>{area_near(vs, lg) if not nm else ""}
<nav class="jump" aria-label="{A['jump']}">{''.join(jumps)}</nav>
<div class="cols"><div class="maincol">{''.join(secs)}</div>
<aside class="side"><div class="box"><h2>{A['map_h']}</h2><p style="margin:0 0 12px;color:var(--mut);font-size:14px">{A['map_p'].format(n=nm, a=esc(dn))}</p><a class="btn" href="{t['home']}?d={dslug}">{t['show_map']}</a></div>
{share_box}<div class="box"><h2>{A['near_h']}</h2><ul>{near_li}</ul></div>
<div class="box tint"><h2>{A['rest_h']}</h2><p style="margin:0;font-size:14px">{A['rest_p']}</p></div></aside></div></main>"""
            desc = (A["desc"].format(a=dn, d=ds_, n=nm, c=cheapest) if nm else A["lead0"].format(d=ds_, t=len(vs)))
            ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                      {"@type": "ListItem", "position": 1, "name": t["crumb_home"], "item": DOMAIN + t["home"]},
                      {"@type": "ListItem", "position": 2, "name": t["nav_areas"], "item": DOMAIN + t["areas"]},
                      {"@type": "ListItem", "position": 3, "name": dn, "item": DOMAIN + path}]}]
            if allm:
                ld.append({"@context": "https://schema.org", "@type": "ItemList", "name": t["area_h1"].format(a=dn), "numberOfItems": len(allm),
                           "itemListElement": [{"@type": "ListItem", "position": k + 1, "name": v["name"], "url": DOMAIN + t["venue"].format(s=v["slug"])} for k, v in enumerate(allm)]})
            ldh = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
            os.makedirs(f"{out}{path}", exist_ok=True)
            weekly = [v for v in vs if any(m and m.get("items") for m in v["ms"].values())]
            ix = add_url(path, len(weekly) >= GATE["area"], [(v["slug"], v["ms"]) for v in weekly])
            open(f"{out}{path}index.html", "w").write(page(lg, t["area_title"].format(a=dn, n=nm), desc, path, alt, body + (SHARE_JS if img else ""), preview, ldh if ix else "", img, index=ix, has_list=nm > 0))
            idx.append((dn, dslug, nm, len(vs)))
            if ix:
                n_area_ix += 1
        lis = "".join(f'<li><a href="{t["area"].format(s=s)}">{esc(n)}</a> <small>{m} {t["lists"]} · {tt} {t["places"]}</small></li>' for n, s, m, tt in idx)
        os.makedirs(f"{out}{t['areas']}", exist_ok=True)
        ix = add_url(t["areas"], n_area_ix >= GATE["areas_index"], idx)
        open(f"{out}{t['areas']}index.html", "w").write(page(lg, t["areas_title"], t["areas_h1"], t["areas"], T[other]["areas"],
                                                              f'<main class="content"><h1>{t["areas_h1"]}</h1><ul class="areas">{lis}</ul></main>', preview, index=ix))
        # topic pages (cheapest / vegetarian / buffet in all of Helsinki), refreshed daily
        TP = TOPIC_T[lg]
        allm_g = [v for v in venues if v["menu"]]
        mp_g = {v["slug"]: lunch_price(v["menu"]) for v in allm_g}
        topics = {
            "cheap": sorted([v for v in allm_g if mp_g[v["slug"]] and mp_g[v["slug"]] < 13], key=lambda v: mp_g[v["slug"]])[:80],
            "veg": sorted([v for v in allm_g if is_veg(v)], key=lambda v: (v["district"] or "", mp_g[v["slug"]] or 99))[:200],
            "buffet": sorted([v for v in allm_g if re.search(r"buffet|noutopöytä|seisova", menu_text(v))], key=lambda v: (v["district"] or "", v["name"]))[:200],
        }
        top_areas = sorted(nmenu.items(), key=lambda kv: -kv[1])[:10]
        for key, items in topics.items():
            path, alt = TP[key]["path"], TOPIC_T[other][key]["path"]
            ps = [mp_g[v["slug"]] for v in items if mp_g[v["slug"]]]
            lead = TP[key]["lead"].format(d=esc(ds_), n=len(items), p=fmt_price(min(ps)) if ps else "–")
            others_l = "".join(f'<li><a href="{TP[k]["path"]}">{esc(TP[k]["h1"])}</a></li>' for k in topics if k != key)
            areas_l = "".join(f'<li><a href="{t["area"].format(s=k[0])}">{esc(t["area_h1"].format(a=k[1]))}</a> <small>· {n} {t["lists"]}</small></li>' for k, n in top_areas)
            img = None
            if key == "cheap":
                img = share_image(out, "helsinki", "Helsinki", ds_, items, mp_g, TOPIC_T["fi"]["cheap"]["path"]) if lg == "fi" else ("/jako/helsinki.png" if os.path.exists(f"{out}/jako/helsinki.png") else None)
            A = AREA_T[lg]
            share_box = (f'<div class="box share"><h2>{A["share_h"]}</h2><img src="{img}" alt="" width="270" height="338" loading="lazy" style="width:100%;height:auto;border-radius:12px;border:1px solid var(--line)">'
                         f'<p style="margin:12px 0 0;display:flex;gap:8px;flex-wrap:wrap"><button class="btn" type="button" data-share="{img}" data-title="{esc(TP[key]["h1"])}">{A["share_b"]}</button>'
                         f'<a class="btn ghost" href="{img}" download>{A["share_dl"]}</a></p></div>') if img else ""
            ents = "".join(entry_html(v, mp_g, t, lg, show_area=True) for v in items) or f'<p class="nomenu">{TP["empty"]}</p>'
            body = f"""<main class="content"><nav class="crumbs"><a href="{t['home']}">{t['crumb_home']}</a> › {esc(TP[key]['h1'])}</nav>
<h1>{esc(TP[key]['h1'])} {TP['today']}</h1><p class="lead">{lead}</p>
<div class="cols"><div class="maincol"><section class="sec">{ents}</section><p style="margin-top:22px">{TP[key]['outro']}</p></div>
<aside class="side">{share_box}<div class="box"><h2>{TP['more']}</h2><ul>{others_l}</ul></div><div class="box"><h2>{TP['areas']}</h2><ul>{areas_l}</ul></div>
<div class="box"><a class="btn" href="{t['home']}">{t['show_map']}</a></div></aside></div></main>"""
            os.makedirs(f"{out}{path}", exist_ok=True)
            ix = add_url(path, len(items) >= GATE["topic"], [(v["slug"], v["menu"]) for v in items])
            open(f"{out}{path}index.html", "w").write(page(lg, TP[key]["title"], TP[key]["desc"].format(d=ds_, n=len(items)), path, alt, body + (SHARE_JS if img else ""), preview, "", img, index=ix))
        # venues
        today_m = [w for w in venues if w["menu"]]
        def near_count(v, km_=1.0):
            cl = math.cos(math.radians(v["lat"]))
            return sum(1 for w in today_m if math.hypot(w["lat"] - v["lat"], (w["lon"] - v["lon"]) * cl) * 111.32 <= km_)
        def near_box(v, k=5):
            if v["menu"] or not today_m:
                return ""
            cl = math.cos(math.radians(v["lat"]))
            dd = sorted(today_m, key=lambda w: (w["lat"] - v["lat"]) ** 2 + ((w["lon"] - v["lon"]) * cl) ** 2)[:k]
            li = []
            for w in dd:
                m = int(round(math.hypot(w["lat"] - v["lat"], (w["lon"] - v["lon"]) * cl) * 111_320))
                dist_ = f"{m} m" if m < 1000 else f"{m / 1000:.1f} km".replace(".", ",") if lg == "fi" else f"{m / 1000:.1f} km"
                pr = lunch_price(w["menu"])
                li.append(f'<li><a href="{t["venue"].format(s=w["slug"])}">{esc(w["name"])}</a> <span class="mdish">{esc(clean_dish(w["menu"]["items"][0]["d"][0]))}</span>'
                          f'<span class="price">{fmt_price(pr) if pr else ""}</span><small>{dist_}</small></li>')
            return f'<section class="nearby"><h2>{t["nearby_h"]}</h2><p>{t["nearby_p"]}</p><ul class="picks">{"".join(li)}</ul></section>'
        for v in venues:
            if not (v["ms"] or v["sources"]):
                continue
            o = v["oiva"] or {}
            path, alt = t["venue"].format(s=v["slug"]), T[other]["venue"].format(s=v["slug"])
            oiva = f'<p class="oivabox">{t["oiva"]}: <b>{t["oiva_txt"].get(o.get("grade"), "")}</b> ({esc(o.get("date"))}) – <a href="https://www.oivahymy.fi/hae-yrityksia/" rel="nofollow noopener">{t["oiva_rep"]}</a></p>' if o.get("grade") else ""
            web = f'<p><a href="{esc(v["website"])}" rel="nofollow noopener">{t["website"]}</a></p>' if v.get("website") else ""
            dlink = f' · <a href="{t["area"].format(s=v["dslug"])}">{esc(t["area_h1"].format(a=v["district"]))}</a>' if v["dslug"] else ""
            src0 = (v["menu"] or {}).get("url")
            week = "".join(f'<h3>{esc(datestr(d, lg))}</h3>{menu_html(v["ms"].get(d), lg, v["slug"], d, show_src=not v["menu"] or v["ms"][d].get("url") != src0)}' for d in days if d != show_day and d in v["ms"])
            week = f'<h2>{t["week"]}</h2>{week}' if week else ""
            jl = {"@context": "https://schema.org", "@type": "Restaurant", "name": v["name"],
                  "address": {"@type": "PostalAddress", "streetAddress": v["street"], "postalCode": v.get("postal"), "addressLocality": "Helsinki", "addressCountry": "FI"},
                  "geo": {"@type": "GeoCoordinates", "latitude": v["lat"], "longitude": v["lon"]}}
            if v.get("website"):
                jl["url"] = v["website"]
            body = f"""<main class="content"><nav class="crumbs"><a href="{t['home']}">{t['crumb_home']}</a>{dlink}</nav>
<h1>{esc(t['venue_h1'].format(n=v['name']))}</h1><p class="addr">{esc(v['street'])}, Helsinki</p>{near_box(v)}
<h2>{esc(t['list_for'].format(d=ds_))}</h2>{menu_html(v['menu'], lg, v['slug'], show_day)}{week}{oiva}{web}{ad_block("content", lg) if v["menu"] else ""}
<p class="actions"><a class="btn" href="{t['home']}?v={v['slug']}">{t['show_map']}</a> <a class="btn ghost" href="https://www.google.com/maps/dir/?api=1&destination={v['lat']},{v['lon']}" rel="nofollow noopener">{t['route']}</a> {parkpenny(v, lg)} <a class="btn ghost" href="https://www.google.com/maps/search/?api=1&amp;query={urllib.parse.quote(v['name'] + ', ' + (v['street'] or '') + ', Helsinki')}" rel="nofollow noopener">{t['g_reviews']}</a></p>
<p class="likerow">{f'<span class="popn">{LIKES[v["slug"]]} {t["pop_n"]}</span> ' if LIKES.get(v["slug"]) else ""}<button type="button" class="likebtn" data-like="{v['slug']}" data-done="{t['liked']}">{t['like']}</button></p>
{report_form(v, lg)}</main><script src="/suggest.js?v={VER['suggest.js']}" defer></script>"""
            os.makedirs(f"{out}{path}", exist_ok=True)
            rid = ("osm:" + v["osm"]) if v.get("osm") else v.get("id")
            ok_v = ((SEEN.get(v["slug"]) or "") >= since or v["slug"][:40] in LANDED or rid in LUNCHY
                    or near_count(v) >= GATE["venue_near"])
            ix = add_url(path, ok_v, [v["ms"], v["slug"] in LANDED])
            open(f"{out}{path}index.html", "w").write(page(lg, t["venue_title"].format(n=v["name"]), t["venue_desc"].format(n=v["name"], a=v["street"]), path, alt, body, preview,
                                                           f'<script type="application/ld+json">{json.dumps(jl, ensure_ascii=False)}</script>', index=ix, has_list=bool(v["menu"])))
    write_info_pages(out, preview, urls)
    if ADSENSE:
        open(f"{out}/ads.txt", "w").write(f"google.com, {ADSENSE.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n")
    nf = ('<main class="content"><h1>Sivua ei löytynyt</h1><p>Osoitetta ei ole tai se on vaihtunut. Päivän lounaslistat löydät näistä:</p>'
          '<ul><li><a href="/">Lounas Helsinki – kartta ja lista</a></li><li><a href="/lounas/">Lounas alueittain</a></li>'
          '<li><a href="/halvin-lounas-helsinki/">Halvin lounas Helsingissä</a></li><li><a href="/kasvislounas-helsinki/">Kasvislounas Helsingissä</a></li></ul></main>')
    open(f"{out}/404.html", "w").write(page("fi", "Sivua ei löytynyt | Päivän lounas", "", "/404", None, nf, preview, '<meta name="robots" content="noindex">'))
    open(f"{out}/robots.txt", "w").write("User-agent: *\nDisallow: /\n" if preview else f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {DOMAIN}/sitemap.xml\n")
    n_sm = write_sitemap(out, L, datetime.date.today().isoformat())
    built = sum(1 for _, _, fs in os.walk(out) for f in fs if f == "index.html")
    print(f"index gate: {n_sm} of {built} pages indexable (sitemap), {built - n_sm} noindex", file=sys.stderr)
    # old restaurant addresses (before duplicate merging) keep working: 301 to the restaurant's page now
    reds = []
    live_slugs = {v["slug"] for v in venues}
    for old_s, v in legacy:
        k = v
        while id(k) in merged:
            k = merged[id(k)]
        new_s = k.get("slug")
        if new_s and old_s != new_s and old_s not in live_slugs:
            for lg_ in ("fi", "en"):
                reds.append(f'{T[lg_]["venue"].format(s=old_s)} {T[lg_]["venue"].format(s=new_s)} 301')
    open(f"{out}/_redirects", "w").write("\n".join(reds) + "\n")
    print("redirects", len(reds), file=sys.stderr)
    open(f"{out}/_headers", "w").write("/data/*\n  Cache-Control: public, max-age=600\n/jako/*\n  Cache-Control: public, max-age=1800\n/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n")
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
<li><b>Karttatiilet</b> ladataan OpenStreetMapin palvelimilta, jotka näkevät IP-osoitteesi.</li>
<li><b>Kävijätilastot:</b> Cloudflare Web Analytics laskee sivujen katselut ilman evästeitä eikä tunnista yksittäisiä kävijöitä.</li>
<li><b>Oma käyttölaskuri:</b> sivusto laskee päiväkohtaisia summia siitä, millaisia sivuja avataan ja mitä painikkeita käytetään (esim. "reitti", "toinen päivä") sekä kuinka moni poistuu alle 15 sekunnissa. Tallennamme vain päivän, sivutyypin ja lukumäärän – emme IP-osoitetta, evästeitä emmekä mitään, mistä kävijän voisi tunnistaa.</li></ul>
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
<li><b>Map tiles</b> are loaded from OpenStreetMap's servers, which see your IP address.</li>
<li><b>Visitor statistics:</b> Cloudflare Web Analytics counts page views without cookies and does not identify individual visitors.</li>
<li><b>Own usage counter:</b> the site keeps daily totals of which kinds of pages are opened, which buttons are used (e.g. "directions", "another day") and how many visitors leave within 15 seconds. We store only the day, the page type and the count – no IP address, no cookies, nothing that could identify a visitor.</li></ul>
{ads}
<h2>Retention and your rights</h2><p>Reports are deleted when no longer needed, at the latest after 24 months. You can request access or deletion at {contact}. You have the right to lodge a complaint with the Finnish Data Protection Ombudsman (tietosuoja.fi).</p>"""),
        "ads": """<h2>Advertising</h2><p>The site shows Google AdSense ads. Google and its partners may use cookies and other identifiers to show and measure ads. In the European Economic Area we ask for your consent with a Google-certified consent message, and you can change your choice at any time. More: <a href="https://policies.google.com/technologies/ads" rel="nofollow noopener">policies.google.com/technologies/ads</a>.</p>""",
    },
}


INFO_DATE = "26.11.2026"  # when the about/privacy text last changed – update by hand when the text changes


def write_info_pages(out, preview, urls):
    today = datetime.date.today()
    for lg in ("fi", "en"):
        for key in ("about", "privacy"):
            path, alt, title, desc, body = INFO[lg][key]
            body = body.format(owner=OWNER if lg == "fi" else OWNER.replace("toiminimi", "sole trader").replace("Y-tunnus", "Business ID"),
                               contact=CONTACT, date=INFO_DATE, ads=INFO[lg]["ads"] if ADSENSE else "")
            os.makedirs(f"{out}{path}", exist_ok=True)
            ix = add_url(path, True, body)
            open(f"{out}{path}index.html", "w").write(page(lg, title, desc, path, alt, f'<main class="content">{body}</main>', preview, index=ix))


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    main(a[0], a[1], a[2], "--preview" in sys.argv)
