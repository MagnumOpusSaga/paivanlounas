"""Build the venue registry and lunch areas of one more city (Branu 27.11.2026: expand city by city to all of Finland).
Usage: build_city.py <city-key>   (keys in pipeline/cities.py)

Sources, all open:
  - OpenStreetMap restaurants/cafés/fast food inside the municipality (Overpass; website, opening hours, coordinates)
  - Oiva food-control premises of the municipality (oivahymy.fi public search; skipped if the service is down,
    the previous file is kept) – adds places OSM does not know and the Oiva grade
  - Compass / Sodexo / UniCafe restaurants of the city (data/compass.json etc., already collected for all of Finland)
  - address points + statistical areas from the Helsinki region open data (kartta.hel.fi WFS, CC BY 4.0)
Writes data/registry_<key>.json, data/areas_<key>.json, raw/oiva_<key>.json, raw/osm_<key>.json, raw/addr_<key>.json."""
import json, os, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cities import CITIES  # noqa: E402
import build_registry  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UA = {"User-Agent": "paivanlounas.fi registry builder" + (f" ({os.environ['LOUNAS_CONTACT']})" if os.environ.get("LOUNAS_CONTACT") else ""),
      "Accept": "application/json"}
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]
WFS = "https://kartta.hel.fi/ws/geoserver/avoindata/wfs"


def get(url, data=None, timeout=90):
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def osm_places(cfg):
    q = (f'[out:json][timeout:120];area["name"="{cfg["name"]}"]["admin_level"="8"]["boundary"="administrative"]->.a;'
         'nwr["amenity"~"^(restaurant|cafe|fast_food|food_court)$"](area.a);out center tags;')
    d = None
    for attempt in range(3):  # public Overpass servers are often busy: a few rounds over all of them
        for url in OVERPASS:
            try:
                d = json.loads(get(url, urllib.parse.urlencode({"data": q}).encode(), 150))
                break
            except Exception as e:
                print("overpass failed", url, e, file=sys.stderr)
        if d:
            break
        time.sleep(15)
    if not d:
        raise SystemExit("no Overpass server answered")
    rows = []
    for el in d["elements"]:
        t = el.get("tags", {})
        if not t.get("name"):
            continue
        lat, lon = (el["lat"], el["lon"]) if "lat" in el else (el["center"]["lat"], el["center"]["lon"])
        rows.append({"osm": el["type"][0] + str(el["id"]), "name": t["name"], "amenity": t.get("amenity"),
                     "street": " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x),
                     "postal": t.get("addr:postcode"), "city": t.get("addr:city"), "lat": lat, "lon": lon,
                     "website": t.get("website") or t.get("contact:website") or t.get("url"),
                     "opening_hours": t.get("opening_hours"), "cuisine": t.get("cuisine"), "brand": t.get("brand"),
                     "lunch": t.get("lunch") or t.get("opening_hours:lunch")})
    return rows


def oiva_rows(cfg, key):
    path = f"{ROOT}/raw/oiva_{key}.json"
    import collect_oiva
    try:
        with ThreadPoolExecutor(4) as ex:
            chunks = list(ex.map(collect_oiva.by_postal, cfg["postal"]))
    except Exception as e:
        chunks = []
        print("oiva failed", e, file=sys.stderr)
    seen = {}
    for c in chunks:
        for r in c or []:
            if r.get("kunta", {}).get("kuntanumero") == cfg["kunta"]:
                seen[r["kohdetoimintatunnus"]] = r
    if len(seen) < 50:  # service down → keep the last good collection (or none yet; the next build adds Oiva)
        print(f"oiva: only {len(seen)} rows now, keeping the previous file", file=sys.stderr)
        return json.load(open(path)) if os.path.exists(path) else []
    json.dump(list(seen.values()), open(path, "w"), ensure_ascii=False)
    return list(seen.values())


def wfs(layer, cql=None):
    p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": f"avoindata:{layer}",
         "outputFormat": "application/json", "srsName": "EPSG:4326"}
    if cql:
        p["CQL_FILTER"] = cql
    return json.loads(get(WFS + "?" + urllib.parse.urlencode(p), timeout=180))["features"]


def fill_streets(osm, addr):
    """OSM places without addr:street get the nearest address point within 35 m (one address = one place on its page)."""
    import math
    grid = {}
    for f in addr:
        lon, lat = f["geometry"]["coordinates"][:2]
        grid.setdefault((round(lat, 3), round(lon, 3)), []).append(f)
    n = 0
    for o in osm:
        if o["street"]:
            continue
        best, bd = None, 35.0
        for dy in (-0.001, 0, 0.001):
            for dx in (-0.001, 0, 0.001):
                for f in grid.get((round(o["lat"] + dy, 3), round(o["lon"] + dx, 3)), []):
                    lon, lat = f["geometry"]["coordinates"][:2]
                    d = math.hypot((lat - o["lat"]) * 111000, (lon - o["lon"]) * 111000 * math.cos(math.radians(60.2)))
                    if d < bd:
                        best, bd = f, d
        if best:
            p = best["properties"]
            o["street"] = f"{p['katunimi']} {p.get('osoitenumero_teksti') or p.get('osoitenumero') or ''}{p.get('osoitekirjain') or ''}".strip()
            o["postal"] = o.get("postal") or p.get("postinumero")
            n += 1
    print(f"street filled from address points: {n}", file=sys.stderr)


def main(key):
    cfg = CITIES[key]
    os.makedirs(f"{ROOT}/raw", exist_ok=True)
    osm = osm_places(cfg)
    json.dump(osm, open(f"{ROOT}/raw/osm_{key}.json", "w"), ensure_ascii=False)
    print(f"{key}: OSM places {len(osm)}, with website {sum(1 for o in osm if o['website'])}", file=sys.stderr)
    addr = wfs(cfg["addr_wfs"], f"kaupunki='{cfg['addr_city']}'")
    json.dump({"features": addr}, open(f"{ROOT}/raw/addr_{key}.json", "w"), ensure_ascii=False)
    print(f"{key}: address points {len(addr)}", file=sys.stderr)
    fill_streets(osm, addr)
    oiva = oiva_rows(cfg, key)
    print(f"{key}: Oiva premises {len(oiva)}", file=sys.stderr)
    build_registry.build(oiva, osm, addr, f"{ROOT}/data", key, f"{ROOT}/data/registry_{key}.json")
    areas = []
    for f in wfs(cfg["areas_wfs"], f"kunta='{cfg['kunta']}'"):
        n = f["properties"]["nimi"]
        areas.append({"type": "Feature", "geometry": f["geometry"],
                      "properties": {"nimi_fi": cfg["area_names"].get(n, n), "city": key}})
    json.dump({"type": "FeatureCollection", "features": areas}, open(f"{ROOT}/data/areas_{key}.json", "w"), ensure_ascii=False)
    print(f"{key}: areas {len(areas)}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
