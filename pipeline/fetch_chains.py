"""Fetch today's lunch from chain APIs (Compass, Sodexo, UniCafe) and normalise.
Usage: fetch_chains.py <data_dir> <YYYY-MM-DD> <out.json>"""
import json, re, sys, time, datetime, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 lounas-pilot", "Accept": "application/json"}


def get(url):
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, None
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return 0, None


PRICE = re.compile(r"(\d{1,2}(?:[,.]\d{2})?)\s*€|€\s*(\d{1,2}(?:[,.]\d{2})?)")


def prices(s):
    return sorted({float((a or b).replace(",", ".")) for a, b in PRICE.findall(s or "")})


def compass(r, day):
    if not r.get("cost_center"):
        return {"status": "no_id"}
    st, d = get("https://www.compass-group.fi/menuapi/day-menus?" +
                urllib.parse.urlencode({"costCenter": r["cost_center"], "date": day, "language": "fi"}))
    if st != 200 or not d:
        return {"status": f"http_{st}"}
    items = []
    for p in d.get("menuPackages") or []:
        meals = [m["name"].strip() for m in p.get("meals") or [] if m.get("name", "").strip()]
        if not meals:
            continue
        diets = sorted({x for m in p["meals"] for x in (m.get("diets") or []) if x in ("G", "L", "M", "VL", "Veg")})
        items.append({"title": p.get("name", "").strip(), "dishes": meals, "diets": diets,
                      "prices": prices(p.get("price")), "price_text": p.get("price")})
    return {"status": "ok" if items else "empty", "items": items}


def sodexo(r, day):
    if not r.get("menu_id"):
        return {"status": "no_id"}
    st, d = get(f"https://www.sodexo.fi/ruokalistat/output/daily_json/{r['menu_id']}/{day}")
    if st != 200 or not d:
        return {"status": f"http_{st}"}
    c = d.get("courses") or {}
    c = c.values() if isinstance(c, dict) else c
    items = [{"title": x.get("category") or "", "dishes": [x.get("title_fi") or x.get("title_en")],
              "diets": [s.strip() for s in (x.get("dietcodes") or "").split(",") if s.strip()],
              "prices": prices(x.get("price")), "price_text": x.get("price")} for x in c]
    return {"status": "ok" if items else "empty", "items": items}


_uni = None


def unicafe(r, day):
    global _uni
    if _uni is None:
        _uni = {x["id"]: x for x in (get("https://unicafe.fi/wp-json/swiss/v1/restaurants?lang=fi")[1] or [])}
    x = _uni.get(str(r["menu_id"]))
    if not x:
        return {"status": "no_id"}
    dt = datetime.date.fromisoformat(day)
    tag = f"{dt.day}.{dt.month}."
    for m in (x.get("menuData") or {}).get("menus") or []:
        if m.get("date", "").split(" ")[-1] == tag:
            items = [{"title": "", "dishes": [i.get("name")], "diets": (i.get("meta") or {}).get("0", []) if isinstance(i.get("meta"), dict) else [],
                      "prices": prices(json.dumps(i.get("price"), ensure_ascii=False)), "price_text": None}
                     for i in m.get("data") or [] if i.get("name")]
            return {"status": "ok" if items else "empty", "items": items}
    return {"status": "empty"}


FETCH = {"compass": compass, "sodexo": sodexo, "unicafe": unicafe}


def main(data_dir, day, out):
    global _uni
    for _ in range(3):
        st, d = get("https://unicafe.fi/wp-json/swiss/v1/restaurants?lang=fi")
        if d:
            _uni = {str(x["id"]): x for x in d}
            break
    rest = []
    for f in ("compass", "sodexo", "unicafe"):
        rest += json.load(open(f"{data_dir}/{f}.json"))
    def run(r):
        res = FETCH[r["source"]](r, day)
        return {"id": r["id"], "name": r["name"], "city": r.get("city"), "source": r["source"], **res}
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(run, rest))
    json.dump({"date": day, "results": res}, open(out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
