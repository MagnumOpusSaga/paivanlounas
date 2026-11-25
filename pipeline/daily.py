"""Daily run: fetch today's lunch lists and build the site into dist/.
Usage: python3 -I pipeline/daily.py [YYYY-MM-DD]   (default: today in Europe/Helsinki)"""
import urllib.parse, unicodedata, re
import datetime, json, os, subprocess, sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "pipeline")


def run(*args, ok_fail=False):
    print("+", " ".join(args), flush=True)
    r = subprocess.run([sys.executable, "-I", *args], cwd=ROOT)
    if r.returncode and not ok_fail:
        sys.exit(r.returncode)
    return r.returncode


def host(u):
    h = urllib.parse.urlsplit(u or "").hostname or ""
    return h[4:] if h.startswith("www.") else h


def slugify(s):
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("ä", "a").replace("ö", "o").replace("å", "a"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(ZoneInfo("Europe/Helsinki")).date().isoformat()
    os.makedirs(f"{ROOT}/raw", exist_ok=True)
    preview = [] if os.environ.get("PUBLIC") == "1" else ["--preview"]
    # code push: rebuild from the lists the last scheduled run fetched (restored from the Actions cache) – minutes instead of ~20
    if os.environ.get("QUICK") == "1" and os.path.exists(f"{ROOT}/data/menus_chains_{day}.json"):
        print("quick rebuild from cached lists", flush=True)
        run("build/build_site.py", ".", "dist", day, *preview)
        return
    dt = datetime.date.fromisoformat(day)
    mon = dt - datetime.timedelta(days=dt.weekday()) + datetime.timedelta(days=7 if dt.weekday() >= 5 else 0)
    week = [(mon + datetime.timedelta(days=i)).isoformat() for i in range(5)]
    # 1. chain APIs (Compass, Sodexo, UniCafe), Mon-Fri of this week
    for d in week:
        if run(f"{P}/fetch_chains.py", "data", d, f"data/menus_chains_{d}.json", ok_fail=d != day):
            print("chains failed for", d, flush=True)
    # 2. Raflaamo public lunch page
    if run(f"{P}/raflaamo.py", "raw/raf_hki_parsed.json", ok_fail=True):
        json.dump([], open(f"{ROOT}/raw/raf_hki_parsed.json", "w"))
    # 3. restaurants' own websites (registry venues with a website and no chain source)
    reg = json.load(open(f"{ROOT}/data/registry_helsinki.json"))
    todo = [{"id": "osm:" + v["osm"] if v.get("osm") else v["id"], "name": v["name"], "website": v["website"]}
            for v in reg if v.get("website") and not any(s.split(":")[0] in ("compass", "sodexo", "unicafe") for s in v["sources"])]
    # suggestions sent through the site form (data/suggestions.json, filled by the workflow from D1)
    sp = f"{ROOT}/data/suggestions_raw.json"
    if os.path.exists(sp):
        try:
            rows = json.load(open(sp))[0]["results"]
        except Exception as e:
            print("suggestions unreadable:", e, flush=True)
            rows = []
        # a form anyone can fill: only use an address that plausibly is the restaurant's own (its known site's domain,
        # or a domain containing a word of its name), or one approved by hand in data/approved_suggestions.json
        approved = set(json.load(open(f"{ROOT}/data/approved_suggestions.json"))) if os.path.exists(f"{ROOT}/data/approved_suggestions.json") else set()
        sites = {}
        for v in reg:
            if v.get("website"):
                sites.setdefault(slugify(v["name"]), set()).add(host(v["website"]))
        GENERIC = {"ravintola", "restaurant", "cafe", "kahvila", "lounas", "helsinki", "bistro", "kitchen", "bar"}
        seen, used, held = set(), 0, 0
        for s in rows[::-1]:  # newest first, one per venue
            if s["venue"] in seen:
                continue
            seen.add(s["venue"])
            h = host(s["url"])
            words = [w for w in s["venue"].split("-") if len(w) >= 4 and w not in GENERIC]
            ok = s["url"] in approved or h in sites.get(s["venue"], set()) or any(w in h.replace("-", "") for w in words)
            if not ok:
                held += 1
                continue
            used += 1
            todo.append({"id": "sug:" + s["venue"], "name": s["venue"].replace("-", " "), "website": s["url"]})
        print("suggestions", len(seen), "used", used, "held for approval", held, flush=True)
    json.dump(todo, open(f"{ROOT}/data/web_todo.json", "w"), ensure_ascii=False)
    if run(f"{P}/fetch_independent.py", "data/web_todo.json", ",".join(week), "data/menus_independent_{day}.json", ok_fail=True):
        for d in week:
            json.dump({"date": d, "results": []}, open(f"{ROOT}/data/menus_independent_{d}.json", "w"))
    # 4. AI reader for the saved lunch pages (skips itself without ANTHROPIC_API_KEY)
    run(f"{P}/ai_reader.py", "data/web_pages.json", ",".join(week), "data/menus_ai_{day}.json", ok_fail=True)
    # 5. build
    run("build/build_site.py", ".", "dist", day, *preview)


if __name__ == "__main__":
    main()
