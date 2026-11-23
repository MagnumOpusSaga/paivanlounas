"""Collect all Compass Group Finland (Food & Co, Amica) restaurants with cost centers."""
import json, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

BASE = "https://www.compass-group.fi"
UA = {"User-Agent": "Mozilla/5.0 lounas-pilot", "Accept": "application/json"}


def get(path, **q):
    url = BASE + path + "?" + urllib.parse.urlencode(q)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                return json.load(r)
        except Exception as e:  # retry transient errors
            if attempt == 2:
                print("FAIL", url, e, file=sys.stderr)
                return None
            time.sleep(1.5)


def main(out):
    hits, page = [], 1
    while True:
        d = get("/api/restaurant-search", language="fi", page=page)
        if not d or not d.get("hits"):
            break
        hits += d["hits"]
        if not d.get("hasMore"):
            break
        page += 1
    print("search hits", len(hits), file=sys.stderr)

    def detail(h):
        d = get("/api/restaurant-search/details", id=h["contentId"], language="fi") or {}
        brand = h["url"].split("/")[2] if h.get("url") else ""
        return {
            "source": "compass",
            "brand": brand,
            "id": f"compass:{d.get('costCenter') or h['contentId']}",
            "name": h["title"],
            "street": h.get("streetAddress"),
            "postal": h.get("postalCode"),
            "city": h.get("city"),
            "lat": (h.get("coordinates") or {}).get("latitude"),
            "lon": (h.get("coordinates") or {}).get("longitude"),
            "url": BASE + h["url"] if h.get("url") else None,
            "cost_center": d.get("costCenter"),
            "jamix": bool(d.get("mashieMenuUrl")),
            "phone": d.get("telephone"),
            "email": d.get("email"),
            "opening_html": d.get("openingHoursHtml"),
            "lunch_today": h.get("lunchHoursToday"),
        }

    with ThreadPoolExecutor(6) as ex:
        rows = list(ex.map(detail, hits))
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=1)
    print("wrote", len(rows), out, file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
