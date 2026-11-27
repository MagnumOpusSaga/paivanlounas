"""Build the Helsinki lunch venue registry: Oiva (all food premises) + OSM (websites, coords) + chain sources.
Usage: build_registry.py <data_dir> <raw_dir> <out.json>"""
import json, re, sys, math, collections

EXCL = re.compile(r"(?i)päiväkoti|paivakoti|daghem|koulu|skola|lukio|gymnas|palvelutalo|palvelukeskus|hoivakoti|vanhain|"
                  r"asumis|sairaala|kotihoito|leikkipuisto|ryhmäkoti|kehitysvamma|seniori|vankila|kasarmi|varuskunta|"
                  r"kuntoutus|terveysasema|iltapäiväkerho|nuorisotalo|liikkuva|elintarvikehuoneisto|food ?truck|"
                  r"kioski|myyntiauto|tilapäinen")


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(ravintola|restaurant|oy|ab|ky|cafe|café|kahvila|bistro|ltd|lounasravintola|the)\b", "", s)
    return re.sub(r"[^a-zåäö0-9]", "", s)


def street_key(s):
    s = (s or "").lower().split(",")[0].strip()
    m = re.match(r"^(.*?)\s+(\d+)\s*([a-zåäö])?\b", s)
    return (re.sub(r"[^a-zåäö]", "", m.group(1)), m.group(2), (m.group(3) or "")) if m else (re.sub(r"[^a-zåäö]", "", s), "", "")


def dist(a, b):
    return math.hypot((a[0] - b[0]) * 111000, (a[1] - b[1]) * 111000 * math.cos(math.radians(60.2)))


def main(data, raw, out):
    """Helsinki (the original registry)."""
    build(json.load(open(f"{data}/oiva_helsinki.json")), json.load(open(f"{data}/osm.json")),
          json.load(open(f"{raw}/hel_osoitteet.json"))["features"], data, "helsinki", out)


def build(oiva, osm, addr, data, city, out):
    """Merge Oiva premises + OSM places + chain restaurants of one city into venues (written to out).
    addr: address points (GeoJSON features with katunimi / osoitenumero / osoitekirjain) for geocoding Oiva addresses."""
    A = {}
    for f in addr:
        p = f["properties"]
        k = (re.sub(r"[^a-zåäö]", "", (p["katunimi"] or "").lower()), str(p["osoitenumero"] or ""), (p["osoitekirjain"] or "").lower())
        A.setdefault(k, f["geometry"]["coordinates"])
        A.setdefault(k[:2] + ("",), f["geometry"]["coordinates"])
    osm_by_street = collections.defaultdict(list)
    for o in osm:
        osm_by_street[street_key(o.get("street"))[:2]].append(o)

    venues, used_osm = [], set()
    for x in oiva:
        if x["toimiala"]["FI"] not in ("Kahvilat ja ravintolat", "Ruokalat"):
            continue
        if EXCL.search(x["nimi"]):
            continue
        sk = street_key(x["osoiteFi"])
        coord = A.get(sk) or A.get(sk[:2] + ("",))
        n = norm(x["nimi"])
        cands = osm_by_street.get(sk[:2], [])
        hit = [o for o in cands if norm(o["name"]) and (norm(o["name"]) in n or n in norm(o["name"]))]
        if not hit and coord:  # name match within 60 m
            hit = [o for o in osm if norm(o["name"]) and len(norm(o["name"])) > 3 and (norm(o["name"]) in n or n in norm(o["name"]))
                   and dist((o["lat"], o["lon"]), (coord[1], coord[0])) < 60]
        o = hit[0] if hit else None
        if o:
            used_osm.add(o["osm"])
        oi = (x.get("oivat") or [{}])[0]
        venues.append({
            "id": f"oiva:{x['kohdetoimintatunnus']}", "name": x["nimi"], "operator": x.get("toimija"),
            "street": x["osoiteFi"], "postal": x.get("postinumero"), "kind": x["toimiala"]["FI"],
            "lat": coord[1] if coord else (o["lat"] if o else None), "lon": coord[0] if coord else (o["lon"] if o else None),
            "oiva": {"grade": oi.get("kokonaisarvosana"), "date": oi.get("tapahtumapaiva"), "id": x["kohdetoimintatunnus"]},
            "osm": o["osm"] if o else None, "website": o.get("website") if o else None,
            "opening_hours": o.get("opening_hours") if o else None, "cuisine": o.get("cuisine") if o else None,
            "sources": [],
        })
    # OSM places without an Oiva match (keep: may be under a different legal name)
    for o in osm:
        if o["osm"] not in used_osm and o.get("name"):
            venues.append({"id": f"osm:{o['osm']}", "name": o["name"], "operator": None, "street": o.get("street"), "postal": o.get("postal"),
                           "kind": o.get("amenity"), "lat": o["lat"], "lon": o["lon"], "oiva": None, "osm": o["osm"],
                           "website": o.get("website"), "opening_hours": o.get("opening_hours"), "cuisine": o.get("cuisine"), "sources": []})
    # chain sources: attach to nearest venue with similar name, else add
    chains = []
    for f, src in (("compass", "compass"), ("sodexo", "sodexo"), ("unicafe", "unicafe")):
        for c in json.load(open(f"{data}/{f}.json")):
            if (c.get("city") or "").lower() != city or not c.get("lat"):
                continue
            chains.append((src, c))
    attached = 0
    for src, c in chains:
        sid = c["id"]
        best = None
        for v in venues:
            if v["lat"] and dist((v["lat"], v["lon"]), (c["lat"], c["lon"])) < 120:
                nv, nc = norm(v["name"]), norm(c["name"])
                # a short chain name inside another restaurant's name ("Kaivopiha" in "Caverna Kaivopiha") is not a match
                other_brand = nc in nv and nv != nc and not any(b in nv for b in ("unicafe", "sodexo", "amica", "food co", "compass", "ravintola"))
                if nv and nc and not other_brand and (nv in nc or nc in nv or (v.get("operator") or "").lower().startswith(("compass", "sodexo", "unicafe", "ylioppilasravintolat", "food & co"))):
                    best = v
                    break
        if best:
            best["sources"].append(sid); attached += 1
        else:
            venues.append({"id": sid, "name": c["name"], "operator": src, "street": c.get("street"), "postal": c.get("postal"), "kind": "chain",
                           "lat": c["lat"], "lon": c["lon"], "oiva": None, "osm": None, "website": c.get("url"), "opening_hours": None,
                           "cuisine": None, "sources": [sid]})
    for v in venues:
        if v["website"] and not v["sources"]:
            v["sources"].append("web:" + v["website"])
        if city != "helsinki":
            v["city"] = city
    json.dump(venues, open(out, "w"), ensure_ascii=False)
    c = collections.Counter
    print("venues", len(venues), "| with coords", sum(1 for v in venues if v["lat"]), "| with Oiva", sum(1 for v in venues if v["oiva"]),
          "| with website", sum(1 for v in venues if v["website"]), "| chain-attached", attached,
          "| with any source", sum(1 for v in venues if v["sources"]), file=sys.stderr)
    print(c(v["oiva"]["grade"] for v in venues if v["oiva"]), file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:4])
