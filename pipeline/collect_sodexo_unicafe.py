"""Collect Sodexo restaurants (page -> weekly_json id, address) and UniCafe restaurants.
Geocode addresses with Photon."""
import json, re, sys, time, html, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 lounas-pilot"}


def fetch(url, as_json=False):
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                b = r.read()
                return json.loads(b) if as_json else b.decode("utf-8", "replace")
        except Exception:
            time.sleep(2)
    return None


def field(h, name):
    m = re.search(r'field--name-field-' + name + r'[^>]*>([^<]+)<', h)
    return html.unescape(m.group(1).strip()) if m else None


def geocode(street, city):
    if not street:
        return None, None
    q = urllib.parse.urlencode({"q": f"{street}, {city or 'Helsinki'}", "limit": 1, "lang": "default",
                                "lat": 60.17, "lon": 24.94})
    d = fetch("https://photon.komoot.io/api/?" + q, True)
    time.sleep(0.3)
    if d and d.get("features"):
        lon, lat = d["features"][0]["geometry"]["coordinates"]
        return lat, lon
    return None, None


def sodexo():
    listing = fetch("https://www.sodexo.fi/ravintolat")
    paths = sorted(set(re.findall(r'href="(/ravintolat/[^"#?]+)"', listing)))

    def one(p):
        h = fetch("https://www.sodexo.fi" + p) or ""
        m = re.search(r'weekly_json/(\d+)', h)
        title = re.search(r'field--name-title[^>]*>([^<]+)<', h)
        street, postal, city = field(h, "street-address"), field(h, "postal-code"), field(h, "postal-office")
        lat, lon = geocode(street, city)
        return {"source": "sodexo", "brand": "sodexo", "id": f"sodexo:{m.group(1) if m else p}",
                "name": html.unescape(title.group(1).strip()) if title else p.split("/")[-1],
                "street": street, "postal": postal, "city": city, "lat": lat, "lon": lon,
                "url": "https://www.sodexo.fi" + p, "menu_id": m.group(1) if m else None}

    with ThreadPoolExecutor(3) as ex:
        return list(ex.map(one, paths))


def unicafe():
    d = fetch("https://unicafe.fi/wp-json/swiss/v1/restaurants?lang=fi", True) or []
    rows = []
    for r in d:
        addr = (r.get("address") or "").split(",")[0].strip()
        lat, lon = geocode(addr, "Helsinki")
        rows.append({"source": "unicafe", "brand": "unicafe", "id": f"unicafe:{r['id']}", "name": r["title"],
                     "street": addr, "postal": None, "city": "Helsinki", "lat": lat, "lon": lon,
                     "url": r.get("permalink"), "menu_id": r["id"]})
    return rows


if __name__ == "__main__":
    s = sodexo()
    json.dump(s, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
    print("sodexo", len(s), "with menu id", sum(1 for x in s if x["menu_id"]), file=sys.stderr)
    u = unicafe()
    json.dump(u, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
    print("unicafe", len(u), file=sys.stderr)
