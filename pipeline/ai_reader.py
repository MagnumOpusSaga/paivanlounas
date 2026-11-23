"""AI reader: turn restaurants' own lunch pages into structured menus with Claude Haiku.
Usage: ai_reader.py <web_pages.json> <comma-separated week dates> <out pattern with {day}>
Needs ANTHROPIC_API_KEY. Without it, writes nothing and exits 0.
Input: pages saved by fetch_independent.py (text already extracted from HTML)."""
import json, os, re, sys, time, hashlib, collections, urllib.request, urllib.error, datetime
from concurrent.futures import ThreadPoolExecutor

MODEL = os.environ.get("LOUNAS_AI_MODEL", "claude-haiku-5-5")
MAX_SITES = int(os.environ.get("LOUNAS_AI_MAX", "450"))
WD = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai"]

SYSTEM = """You extract lunch menus (lounas) from the text of a Finnish restaurant's web page.
Rules:
- Use ONLY what the text says. Never invent dishes, prices or dates.
- Return dishes only for the weekdays of the week given by the user. If the page clearly shows a different week (stale list, other dates), return "stale": true and empty "days".
- If the page lists a fixed lunch that is the same every weekday (e.g. "Lounas ma-pe: ..."), put it in "fixed" instead of "days".
- Set "belongs": false ONLY if the menu clearly belongs to another, differently named restaurant (e.g. a listing or chain page that shows other places and not this one). Brand names, company names, abbreviations and the restaurant's other spellings count as the same restaurant; a restaurant's own site is the same restaurant even if the name is not repeated.
- Dishes: keep the original language and wording, one dish per entry, without the price. Remove day names, opening hours and marketing text.
- diet: only markings written next to the dish, normalised to: L, G, M, VL, Veg (vegan/vegaani/VE/V), K (kasvis).
- price: the lunch price in euros as a number if shown for that dish or for the whole lunch; otherwise null.
- hours: lunch serving hours if shown, like "10.30-14.00", else null.
Answer with JSON only, no prose:
{"belongs": true, "stale": false, "hours": null, "fixed": [], "days": {"YYYY-MM-DD": [{"dish": "...", "diet": ["L"], "price": 12.9}]}}"""


def call(text, name, week):
    wk = ", ".join(f"{WD[i]} {d}" for i, d in enumerate(week))
    body = {"model": MODEL, "max_tokens": 1800, "system": SYSTEM,
            "messages": [{"role": "user", "content": f"Restaurant: {name}\nThis week: {wk}\n\nPage text:\n{text}"}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                j = json.load(r)
            out = "".join(c.get("text", "") for c in j.get("content", []))
            m = re.search(r"\{.*\}", out, re.S)
            try:
                return (json.loads(m.group(0)) if m else {"error": "no json"}), j.get("usage", {})
            except ValueError:
                return {"error": "bad json"}, j.get("usage", {})
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 5:
                try:
                    wait = float(e.headers.get("retry-after") or 0)
                except ValueError:
                    wait = 0
                time.sleep(max(wait, 6 * (attempt + 1)))
                continue
            try:
                msg = json.load(e).get("error", {}).get("message", "")[:80]
            except Exception:
                msg = ""
            return {"error": f"http {e.code} {msg}"}, {}
        except Exception as e:  # network, bad JSON
            if attempt < 3:
                time.sleep(3)
                continue
            return {"error": str(e)[:100]}, {}
    return {"error": "gave up"}, {}


def clean_items(lst):
    items = []
    for x in lst or []:
        d = (x.get("dish") or "").strip()
        if not (3 <= len(d) <= 160):
            continue
        p = x.get("price")
        try:
            p = float(p) if p is not None else None
        except (TypeError, ValueError):
            p = None
        if p is not None and not (3 <= p <= 60):
            p = None
        diet = [t for t in (x.get("diet") or []) if t in ("L", "G", "M", "VL", "Veg", "K")]
        items.append({"t": "", "d": [d], "diet": sorted(set(diet)), "p": p})
    return items[:15]


def main(inp, days, out):
    week = days.split(",")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ai_reader: no ANTHROPIC_API_KEY, skipping", file=sys.stderr)
        return
    pages = json.load(open(inp))
    todo = [(k, v) for k, v in pages.items() if v["pages"]][:MAX_SITES]

    cp = os.path.join(os.path.dirname(inp) or ".", "ai_cache.json")
    try:
        cache = json.load(open(cp))
    except Exception:
        cache = {}
    hits = 0

    def one(kv):
        nonlocal hits
        k, v = kv
        text = "\n\n---\n\n".join(f"[{p['url']}]\n{p['text']}" for p in v["pages"])[:12000]
        h = hashlib.sha256(f"{MODEL}|{v['name']}|{week[0]}|{text}".encode()).hexdigest()[:24]
        if h in cache:
            hits += 1
            return k, v, cache[h]["r"], {}
        res, usage = call(text, v["name"], week)
        if isinstance(res, dict) and not res.get("error"):
            cache[h] = {"r": res, "d": week[0]}
        return k, v, res, usage

    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(one, todo))
    # keep only this and last week's entries
    keep = (datetime.date.fromisoformat(week[0]) - datetime.timedelta(days=7)).isoformat()
    json.dump({h: x for h, x in cache.items() if x["d"] >= keep}, open(cp, "w"), ensure_ascii=False)
    errs = collections.Counter(r["error"] for _, _, r, _ in results if isinstance(r, dict) and r.get("error"))
    tin = sum(u.get("input_tokens", 0) for *_, u in results)
    tout = sum(u.get("output_tokens", 0) for *_, u in results)
    per_day = {d: [] for d in week}
    stats = {"sites": len(results), "cache_hits": hits, "ok": 0, "fixed": 0, "stale": 0, "other_restaurant": 0, "errors": 0, "empty": 0}
    for k, v, r, _ in results:
        if not isinstance(r, dict) or r.get("error"):
            stats["errors"] += 1
            continue
        if r.get("belongs") is False:
            stats["other_restaurant"] += 1
            continue
        if r.get("stale"):
            stats["stale"] += 1
            continue
        url = v["pages"][0]["url"]
        got = False
        dd = r.get("days") or {}
        for d in week:
            items = clean_items(dd.get(d))
            if len(items) >= 1:
                per_day[d].append({"id": k, "url": url, "items": items, "hours": r.get("hours"), "kind": "daily"})
                got = True
        fixed = clean_items(r.get("fixed"))
        if not got and fixed:
            for d in week:
                per_day[d].append({"id": k, "url": url, "items": fixed, "hours": r.get("hours"), "kind": "fixed"})
            stats["fixed"] += 1
        elif got:
            stats["ok"] += 1
        else:
            stats["empty"] += 1
    for d in week:
        json.dump({"date": d, "model": MODEL, "results": per_day[d]}, open(out.replace("{day}", d), "w"), ensure_ascii=False, indent=1)
    cost = tin / 1e6 * 0.10 + tout / 1e6 * 0.50
    print(f"ai_reader: {json.dumps(stats)} tokens in {tin} out {tout} ≈ ${cost:.3f}", file=sys.stderr)
    with open(os.path.join(os.path.dirname(out) or ".", "ai_stats.json"), "w") as f:
        json.dump({"stats": stats, "errors": dict(errs.most_common(5)), "tokens_in": tin, "tokens_out": tout, "usd": round(cost, 4),
                   "at": datetime.datetime.utcnow().isoformat() + "Z"}, f)


if __name__ == "__main__":
    main(*sys.argv[1:4])
