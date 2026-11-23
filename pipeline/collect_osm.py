"""Discover Helsinki restaurants from OpenStreetMap via Photon search, then fetch tags (website,
opening_hours, cuisine) from the OSM API in batches."""
import json, os, sys, time, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "lounas-pilot/0.1" + (f" ({os.environ['LOUNAS_CONTACT']})" if os.environ.get("LOUNAS_CONTACT") else "")}
# Helsinki mainland lunch area
LAT0, LAT1, LON0, LON1 = 60.145, 60.300, 24.82, 25.12
GRID = 5
TERMS = ("ravintola restaurant lounas bistro kitchen keittiö cafe kahvila thai sushi pizza pizzeria burger "
         "grill kebab nepal india intia vietnam ramen deli bar pub buffet wok kiina china asia sali tupa "
         "kulma oy house food ruoka bistrot brasserie trattoria taverna tandoor curry pho poke salad "
         "halal mexican taco korea japan street").split()
VALUES = ("restaurant", "cafe", "fast_food")


def get_json(url):
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 + a * 2)
    print("FAIL", url, file=sys.stderr)
    return None


def photon(term, bbox, value):
    q = urllib.parse.urlencode({"q": term, "osm_tag": f"amenity:{value}", "bbox": ",".join(map(str, bbox)),
                                "limit": 50, "lang": "default"})
    d = get_json("https://photon.komoot.io/api/?" + q) or {"features": []}
    time.sleep(0.25)
    return d["features"]


def main(out):
    boxes = []
    for i in range(GRID):
        for j in range(GRID):
            boxes.append((LON0 + (LON1 - LON0) * j / GRID, LAT0 + (LAT1 - LAT0) * i / GRID,
                          LON0 + (LON1 - LON0) * (j + 1) / GRID, LAT0 + (LAT1 - LAT0) * (i + 1) / GRID))
    jobs = [(t, b, v) for t in dict.fromkeys(TERMS) for b in boxes for v in VALUES]
    print("photon jobs", len(jobs), file=sys.stderr)
    found = {}
    with ThreadPoolExecutor(3) as ex:
        for feats in ex.map(lambda a: photon(*a), jobs):
            for f in feats:
                p = f["properties"]
                key = p["osm_type"].lower() + str(p["osm_id"])
                found[key] = {"osm": key, "name": p.get("name"), "amenity": p.get("osm_value"),
                              "street": " ".join(x for x in (p.get("street"), p.get("housenumber")) if x),
                              "postal": p.get("postcode"), "district": p.get("district"), "city": p.get("city"),
                              "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]}
    print("unique places", len(found), file=sys.stderr)

    by_type = {"n": "nodes", "w": "ways", "r": "relations"}
    for t, plural in by_type.items():
        ids = [k[1:] for k in found if k[0] == t]
        for i in range(0, len(ids), 300):
            url = f"https://api.openstreetmap.org/api/0.6/{plural}?{plural}=" + ",".join(ids[i:i + 300])
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                    root = ET.parse(r).getroot()
            except Exception as e:
                print("osm fail", e, file=sys.stderr)
                continue
            for el in root:
                key = t + el.get("id")
                if key in found:
                    tags = {tg.get("k"): tg.get("v") for tg in el.findall("tag")}
                    found[key]["website"] = tags.get("website") or tags.get("contact:website") or tags.get("url")
                    found[key]["opening_hours"] = tags.get("opening_hours")
                    found[key]["cuisine"] = tags.get("cuisine")
                    found[key]["brand"] = tags.get("brand")
                    found[key]["lunch"] = tags.get("lunch") or tags.get("opening_hours:lunch")
            time.sleep(1)
    rows = list(found.values())
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=1)
    print("wrote", len(rows), "with website", sum(1 for r in rows if r.get("website")), file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
