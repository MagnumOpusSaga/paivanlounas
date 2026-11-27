"""Find the official website (and lunch page) for registry venues that have none, with Claude + web search.
Feedback 27.11.: around Esplanadi 314 places within 500 m, only 18 with a list – most have no known website
(e.g. Minne Champagne & Wine publishes its lunch, but the registry had no site). Domain guessing (find_websites.py)
found what it could; this asks a search engine, then keeps only a page that shows the venue's street or postal code.

Order: places search visitors landed on, then nearest to the lunch hubs (centre, Kamppi, Pasila, Ruoholahti, Kalasatama).
Each venue is asked once (data/sites_found.json, kept in the Actions cache; 'none' answers are retried after 30 days).
Budget per run in dollars (env SITES_BUDGET, default 0.25). Never uses competing lunch-list services.
Usage: find_sites_ai.py <registry.json> <sites_found.json> [landed_raw.json]"""
import datetime, json, math, os, re, sys, time, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_websites import fetch, text_of, tokens, ascii_, SKIP_NAME, PARKED  # noqa: E402

MODEL = os.environ.get("SITES_MODEL", "claude-haiku-5-5")
HUBS = [(60.1690, 24.9440), (60.1690, 24.9320), (60.1990, 24.9330), (60.1640, 24.9150), (60.1870, 24.9770), (60.1780, 24.9500)]
COMPETITORS = re.compile(r"(?i)lounaat\.info|lounasaika|lounashaku|lounasinfo|ruokapaikkahaku|kanttiinit|lounari|tripadvisor|"
                         r"facebook\.com|instagram\.com|wolt\.com|foodora|google\.|myhelsinki|yelp|thefork|eat\.fi|fonecta|finder\.fi")
PRICE_IN, PRICE_OUT, PRICE_SEARCH = 0.2 / 1e6, 1.0 / 1e6, 0.01  # $ per token (Haiku list price x2, to stay on the safe side) / per search
SYSTEM = ("You find the official website of one restaurant in Helsinki. Use web search. Answer ONLY with JSON: "
          '{"website": "<official site URL or null>", "lunch_url": "<URL of its weekday lunch/lounas menu page on that site, or null>", '
          '"weekday_lunch": true|false|null}. The official site is the restaurant\'s or its operator\'s own domain – never a listing, '
          "review, delivery, social media or lunch-aggregator site. If unsure, use null.")


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111, (a[1] - b[1]) * 111 * math.cos(math.radians(a[0])))


def ask(v):
    q = f'Restaurant "{v["name"]}", {v.get("street") or ""} {v.get("postal") or ""} Helsinki. Find its official website and weekday lunch menu page.'
    body = {"model": MODEL, "max_tokens": 600, "system": SYSTEM, "messages": [{"role": "user", "content": q}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.load(r)
            u = j.get("usage", {})
            cost = u.get("input_tokens", 0) * PRICE_IN + u.get("output_tokens", 0) * PRICE_OUT + \
                (u.get("server_tool_use") or {}).get("web_search_requests", 0) * PRICE_SEARCH
            out = "".join(c.get("text", "") for c in j.get("content", []) if c.get("type") == "text")
            m = re.search(r"\{.*\}", out, re.S)
            return (json.loads(m.group(0)) if m else {}), cost
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                time.sleep(8 * (attempt + 1))
                continue
            print("http", e.code, e.read()[:200], file=sys.stderr)
            return None, 0.0
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
                continue
            print("error", e, file=sys.stderr)
            return None, 0.0
    return None, 0.0


def verify(v, url):
    """Keep the page only if it is reachable, not parked, not a competitor, and shows the street or postal code + part of the name."""
    if not url or COMPETITORS.search(url):
        return None
    final, body = fetch(url)
    if not final or COMPETITORS.search(final):
        return None
    low = ascii_(text_of(body))
    if len(low) < 300 or PARKED.search(low[:5000]):
        return None
    street = re.match(r"([^\d,]+)", v.get("street") or "")
    street = ascii_(street.group(1)).strip() if street else ""
    postal = v.get("postal") or ""
    toks = [t for t in tokens(v["name"]) if len(t) >= 3]
    has_name = not toks or sum(1 for t in toks if t in low) >= max(1, min(2, len(toks)))
    has_addr = (len(street) >= 5 and street in low) or (postal and postal in low)
    return final if has_name and has_addr else None


def main(reg_path, found_path, landed_path=None):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("find_sites_ai: no ANTHROPIC_API_KEY, skipping", file=sys.stderr)
        return
    budget = float(os.environ.get("SITES_BUDGET", "0.25"))
    reg = json.load(open(reg_path))
    found = json.load(open(found_path)) if os.path.exists(found_path) else {}
    landed = set()
    if landed_path and os.path.exists(landed_path):
        try:
            landed = {r["key"] for r in json.load(open(landed_path))[0]["results"]}
        except Exception:
            pass
    today = datetime.date.today()
    if found.get("_run") == today.isoformat():
        print("find_sites_ai: already ran today", flush=True)
        return
    found["_run"] = today.isoformat()  # once a day (the morning run), not again at 06.07 and 10.37
    todo = []
    for v in reg:
        if v.get("website") or v.get("kind") == "chain" or not v.get("lat") or SKIP_NAME.search(v["name"]):
            continue
        f = found.get(v["id"])
        if f and (f.get("status") == "ok" or (today - datetime.date.fromisoformat(f["checked"])).days < 30):
            continue
        d = min(km((v["lat"], v["lon"]), h) for h in HUBS)
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_(v["name"]).lower()).strip("-")
        todo.append((0 if slug[:40] in landed else 1, d, v))
    todo = [t for t in todo if t[0] == 0 or t[1] <= 1.5]
    todo.sort(key=lambda t: (t[0], t[1]))
    spent, n_ok, n_tried = 0.0, 0, 0
    for _, d, v in todo:
        if spent >= budget:
            break
        ans, cost = ask(v)
        spent += cost
        if ans is None:
            break  # API trouble: stop for this run, nothing written for this venue
        n_tried += 1
        site = verify(v, ans.get("lunch_url")) or verify(v, ans.get("website"))
        rec = {"name": v["name"], "checked": today.isoformat(), "status": "ok" if site else "none",
               "weekday_lunch": ans.get("weekday_lunch")}
        if site:
            rec["website"] = site
            n_ok += 1
        found[v["id"]] = rec
        json.dump(found, open(found_path, "w"), ensure_ascii=False, indent=0)
    print(f"find_sites_ai: tried {n_tried}, found {n_ok}, spent ${spent:.3f}, left {max(0, len(todo) - n_tried)}", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:4])
