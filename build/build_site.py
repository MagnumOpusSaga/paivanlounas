"""Build paivanlounas.fi (static, Cloudflare Pages) from the venue registry + today's menus.
Usage: build_site.py <lounas_dir> <out_dir> <YYYY-MM-DD> [--preview]"""
import json, re, sys, os, html, shutil, datetime, unicodedata

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
    ch = json.load(open(f"{L}/data/menus_chains_{day}.json"))["results"]
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
    ind = json.load(open(f"{L}/data/menus_independent_{day}.json"))["results"]
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


def page(title, desc, path, body, preview, extra_head=""):
    robots = '<meta name="robots" content="noindex,nofollow">' if preview else ""
    bar = '<div class="preview">Esikatselu – sivusto on vielä kehitysvaiheessa</div>' if preview else ""
    return f"""<!doctype html><html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{DOMAIN}{path}">{robots}
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><meta name="theme-color" content="#1f6f4a">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:type" content="website">
<link rel="stylesheet" href="/style.css">{extra_head}</head><body>{bar}
<header class="top"><a class="logo" href="/">🍽️ Päivän lounas</a><nav><a href="/lounas/">Alueet</a></nav></header>
{body}
<footer><p>Lounaslistat haetaan automaattisesti ravintoloiden ja ketjujen omista lähteistä joka arkiaamu. Tarkista erityisruokavaliot aina ravintolasta.</p>
<p>Elintarvikevalvonnan tulokset: Oiva / Ruokavirasto (oivahymy.fi). Osoitteet ja kaupunginosat: Helsingin kaupunki, CC BY 4.0. Kartta: © OpenStreetMapin tekijät.</p>
<p>© 2026 Päivän lounas</p></footer></body></html>"""


OIVA_TXT = {"A": "Oivallinen", "B": "Hyvä", "C": "Korjattavaa", "D": "Huono"}


def menu_html(m):
    if not m:
        return '<p class="nomenu">Tämän päivän listaa ei ole saatavilla. Katso ravintolan omat sivut.</p>'
    out = []
    for it in m["items"]:
        price = f'<span class="price">{it["p"]:.2f} €</span>'.replace(".", ",") if it.get("p") else ""
        diet = "".join(f'<span class="diet">{esc(d)}</span>' for d in it.get("diet", []))
        title = f'<b>{esc(it["t"])}</b> ' if it.get("t") else ""
        out.append(f'<li>{title}{esc(" · ".join(it["d"]))} {diet} {price}</li>')
    src = f'<p class="src">Lähde: {esc(m["src"])}' + (f' – <a href="{esc(m["url"])}" rel="nofollow noopener">alkuperäinen lista</a>' if m.get("url") else "") + "</p>"
    return "<ul class=\"menu\">" + "".join(out) + "</ul>" + src


def main(L, out, day, preview):
    os.makedirs(out, exist_ok=True)
    dt = datetime.date.fromisoformat(day)
    reg = json.load(open(f"{L}/data/registry_helsinki.json"))
    ds = load_districts(os.path.join(os.path.dirname(__file__), "..", "kaupunginosat.json"))
    M = menus_today(L, day)
    R = raflaamo_today(L)
    venues = []
    for v in reg:
        if v["lat"] is None:
            continue
        m = None
        for s in v["sources"]:
            if s in M:
                m = M[s]; break
            if s.startswith("web:"):
                pass
        if not m and v["id"] in M:
            m = M[v["id"]]
        if not m:
            for k in (v.get("osm") and "osm:" + v["osm"],):
                if k and k in M:
                    m = M[k]
        if not m and norm(v["name"]) in R:
            m = R.pop(norm(v["name"]))["menu"]
        d = district_of(v["lat"], v["lon"], ds)
        venues.append({**v, "menu": m, "district": d["name"] if d else None, "dslug": d["slug"] if d else None})
    # slugs
    seen = {}
    for v in venues:
        s = slug(v["name"])
        if s in seen:
            s = f"{s}-{slug(v['street'] or '')[:30]}".strip("-")
        if s in seen:
            s = f"{s}-{len(seen)}"
        seen[s] = 1
        v["slug"] = s
    with_menu = [v for v in venues if v["menu"]]
    print("venues", len(venues), "with menu today", len(with_menu), file=sys.stderr)

    # data for the app
    os.makedirs(f"{out}/data", exist_ok=True)
    app = [{"i": v["slug"], "n": v["name"], "a": v["street"], "y": round(v["lat"], 5), "x": round(v["lon"], 5),
            "o": (v["oiva"] or {}).get("grade"), "d": v["district"], "w": v.get("website"),
            "m": v["menu"]} for v in venues]
    json.dump({"date": day, "weekday": WD[dt.weekday()], "venues": app}, open(f"{out}/data/today.json", "w"), ensure_ascii=False, separators=(",", ":"))

    # static assets
    for f in ("style.css", "app.js", "favicon.svg"):
        shutil.copy(os.path.join(os.path.dirname(__file__), f), f"{out}/{f}")
    os.makedirs(f"{out}/vendor/leaflet/images", exist_ok=True)
    lf = os.path.join(os.path.dirname(__file__), "..", "node_modules", "leaflet", "dist")
    for f in ("leaflet.js", "leaflet.css"):
        shutil.copy(f"{lf}/{f}", f"{out}/vendor/leaflet/{f}")
    for f in os.listdir(f"{lf}/images"):
        shutil.copy(f"{lf}/images/{f}", f"{out}/vendor/leaflet/images/{f}")

    datestr = f"{WD[dt.weekday()]} {dt.day}.{dt.month}.{dt.year}"
    urls = ["/", "/lounas/"]
    # home = app
    body = f"""<main class="app"><div id="map"></div><section class="panel" id="panel">
<div class="grip"></div><h1>Lounas Helsinki tänään <small>{esc(datestr)}</small></h1>
<div class="search"><input id="q" type="search" placeholder="Hae ravintolaa, ruokaa tai aluetta"><button id="near" type="button">📍 Lähellä</button></div>
<div class="chips"><button data-f="menu" class="on">Lista tänään</button><button data-f="open">Auki nyt</button><button data-f="cheap">Halvin ensin</button>
<button data-f="Veg">Veg</button><button data-f="G">G</button><button data-f="L">L</button><button data-f="M">M</button><button data-f="oivaA">Oiva 😃</button></div>
<p id="count" class="count"></p><ol id="list" class="list"></ol></section></main>
<link rel="stylesheet" href="/vendor/leaflet/leaflet.css"><script src="/vendor/leaflet/leaflet.js"></script><script src="/app.js"></script>"""
    ld = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE, "url": DOMAIN + "/"}
    open(f"{out}/index.html", "w").write(page(f"Lounas Helsinki tänään – päivän lounaslistat kartalla | {SITE}",
        f"Helsingin lounaslistat tänään ({datestr}): {len(with_menu)} ravintolan lista, hinnat, ruokavaliot ja Oiva-hymy kartalla.", "/", body, preview,
        f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'))

    # district pages
    by_d = {}
    for v in venues:
        if v["dslug"]:
            by_d.setdefault((v["dslug"], v["district"]), []).append(v)
    idx = []
    for (ds_, dn), vs in sorted(by_d.items(), key=lambda x: x[0][1]):
        vs.sort(key=lambda v: (v["menu"] is None, (min([i["p"] for i in v["menu"]["items"] if i.get("p")] or [99]) if v["menu"] else 99), v["name"]))
        nm = sum(1 for v in vs if v["menu"])
        prices = [i["p"] for v in vs if v["menu"] for i in v["menu"]["items"] if i.get("p") and i["p"] >= 5]
        cheapest = f"Halvin lounas tänään {min(prices):.2f} €.".replace(".", ",", 1) if prices else ""
        cards = []
        for v in vs[:150]:
            o = (v["oiva"] or {}).get("grade")
            oiva = f'<span class="oiva oiva-{o}" title="Oiva: {OIVA_TXT.get(o, "")}">{"😃" if o == "A" else "🙂" if o == "B" else "😐" if o == "C" else "☹️"}</span>' if o else ""
            cards.append(f'<li class="card"><h3><a href="/ravintola/{v["slug"]}/">{esc(v["name"])}</a> {oiva}</h3><p class="addr">{esc(v["street"])}</p>{menu_html(v["menu"]) if v["menu"] else ""}</li>')
        body = f"""<main class="content"><nav class="crumbs"><a href="/">Etusivu</a> › <a href="/lounas/">Alueet</a> › {esc(dn)}</nav>
<h1>Lounas {esc(dn)} tänään</h1><p class="lead">{esc(datestr)}: {nm} ravintolan lounaslista alueella {esc(dn)}. {cheapest} Yhteensä {len(vs)} ravintolaa ja kahvilaa, Oiva-arvosanat mukana.</p>
<p><a class="btn" href="/?d={ds_}">Näytä kartalla</a></p><ol class="cards">{''.join(cards)}</ol></main>"""
        path = f"/lounas/{ds_}/"
        os.makedirs(f"{out}{path}", exist_ok=True)
        open(f"{out}{path}index.html", "w").write(page(f"Lounas {dn} tänään – {nm} lounaslistaa | {SITE}",
            f"Päivän lounas {dn}: {nm} lounaslistaa tänään, hinnat ja ruokavaliot. {cheapest}", path, body, preview))
        urls.append(path)
        idx.append((dn, ds_, nm, len(vs)))
    lis = "".join(f'<li><a href="/lounas/{s}/">{esc(n)}</a> <small>{m} listaa · {t} paikkaa</small></li>' for n, s, m, t in idx)
    os.makedirs(f"{out}/lounas", exist_ok=True)
    open(f"{out}/lounas/index.html", "w").write(page(f"Lounas Helsingissä alueittain | {SITE}", "Helsingin kaupunginosien lounaslistat tänään.", "/lounas/",
        f'<main class="content"><h1>Lounas Helsingissä alueittain</h1><ul class="areas">{lis}</ul></main>', preview))

    # venue pages (venues with a menu source or Oiva grade A/B and a website)
    for v in venues:
        if not (v["menu"] or v["sources"]):
            continue
        o = (v["oiva"] or {})
        path = f"/ravintola/{v['slug']}/"
        oiva = f'<p class="oivabox">Oiva-arvosana: <b>{OIVA_TXT.get(o.get("grade"), "")}</b> ({esc(o.get("date"))}) – <a href="https://www.oivahymy.fi/hae-yrityksia/" rel="nofollow noopener">Oiva-raportti</a></p>' if o.get("grade") else ""
        web = f'<p><a href="{esc(v["website"])}" rel="nofollow noopener">Ravintolan verkkosivu</a></p>' if v.get("website") else ""
        dlink = f' · <a href="/lounas/{v["dslug"]}/">Lounas {esc(v["district"])}</a>' if v["dslug"] else ""
        jl = {"@context": "https://schema.org", "@type": "Restaurant", "name": v["name"],
              "address": {"@type": "PostalAddress", "streetAddress": v["street"], "postalCode": v.get("postal"), "addressLocality": "Helsinki", "addressCountry": "FI"},
              "geo": {"@type": "GeoCoordinates", "latitude": v["lat"], "longitude": v["lon"]}}
        if v.get("website"):
            jl["url"] = v["website"]
        body = f"""<main class="content"><nav class="crumbs"><a href="/">Etusivu</a>{dlink}</nav>
<h1>{esc(v["name"])} – lounas tänään</h1><p class="addr">{esc(v["street"])}, Helsinki</p>
<h2>Lounaslista {esc(datestr)}</h2>{menu_html(v["menu"])}{oiva}{web}
<p><a class="btn" href="/?v={v['slug']}">Näytä kartalla</a> <a class="btn ghost" href="https://www.google.com/maps/dir/?api=1&destination={v['lat']},{v['lon']}" rel="nofollow noopener">Reittiohjeet</a></p></main>"""
        os.makedirs(f"{out}{path}", exist_ok=True)
        open(f"{out}{path}index.html", "w").write(page(f"{v['name']} lounas tänään – lounaslista | {SITE}",
            f"{v['name']} ({v['street']}): päivän lounaslista, hinnat, ruokavaliot ja Oiva-arvosana.", path, body, preview,
            f'<script type="application/ld+json">{json.dumps(jl, ensure_ascii=False)}</script>'))
        urls.append(path)

    open(f"{out}/404.html", "w").write(page(f"Sivua ei löytynyt | {SITE}", "Sivua ei löytynyt.", "/404", '<main class="content"><h1>Sivua ei löytynyt</h1><p><a href="/">Etusivulle</a></p></main>', True))
    open(f"{out}/robots.txt", "w").write("User-agent: *\nDisallow: /\n" if preview else f"User-agent: *\nAllow: /\nSitemap: {DOMAIN}/sitemap.xml\n")
    sm = "".join(f"<url><loc>{DOMAIN}{u}</loc><lastmod>{day}</lastmod></url>" for u in urls)
    open(f"{out}/sitemap.xml", "w").write(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
    open(f"{out}/_headers", "w").write("/data/*\n  Cache-Control: public, max-age=600\n/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n")
    print("pages", len(urls), file=sys.stderr)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    main(a[0], a[1], a[2], "--preview" in sys.argv)
