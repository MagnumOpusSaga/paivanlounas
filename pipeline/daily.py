"""Daily run: fetch today's lunch lists and build the site into dist/.
Usage: python3 -I pipeline/daily.py [YYYY-MM-DD]   (default: today in Europe/Helsinki)"""
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


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(ZoneInfo("Europe/Helsinki")).date().isoformat()
    os.makedirs(f"{ROOT}/raw", exist_ok=True)
    # 1. chain APIs (Compass, Sodexo, UniCafe)
    run(f"{P}/fetch_chains.py", "data", day, f"data/menus_chains_{day}.json")
    # 2. Raflaamo public lunch page
    if run(f"{P}/raflaamo.py", "raw/raf_hki_parsed.json", ok_fail=True):
        json.dump([], open(f"{ROOT}/raw/raf_hki_parsed.json", "w"))
    # 3. restaurants' own websites (registry venues with a website and no chain source)
    reg = json.load(open(f"{ROOT}/data/registry_helsinki.json"))
    todo = [{"id": "osm:" + v["osm"] if v.get("osm") else v["id"], "name": v["name"], "website": v["website"]}
            for v in reg if v.get("website") and not any(s.split(":")[0] in ("compass", "sodexo", "unicafe") for s in v["sources"])]
    json.dump(todo, open(f"{ROOT}/data/web_todo.json", "w"), ensure_ascii=False)
    if run(f"{P}/fetch_independent.py", "data/web_todo.json", day, f"data/menus_independent_{day}.json", ok_fail=True):
        json.dump({"date": day, "results": []}, open(f"{ROOT}/data/menus_independent_{day}.json", "w"))
    # 4. build
    preview = [] if os.environ.get("PUBLIC") == "1" else ["--preview"]
    run("build/build_site.py", ".", "dist", day, *preview)


if __name__ == "__main__":
    main()
