"""Lunch facts for restaurants that publish no daily list (N46): how lunch is served (buffet, daily
changing, fixed list, à la carte, set menu), on which days, at what hours and for what price – read
with Claude Haiku from the restaurant's OWN page text (saved by fetch_independent.py).
Every answer must quote the page verbatim; a quote, price or hour that is not on the page is dropped.
Usage: ai_info.py <web_pages.json> <comma-separated week dates> <out lunch_info.json> [landed_raw.json]
Needs ANTHROPIC_API_KEY (without it the previous lunch_info.json is kept). Cache: data/info_cache.json."""
import datetime, hashlib, json, os, re, sys, glob
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_reader import MODEL  # same model as the menu reader

BUDGET = float(os.environ.get("LOUNAS_INFO_BUDGET", "0.04"))  # USD per run for new readings; cached readings are free
MAX_CHARS = 6000
KEEP_DAYS = 45  # a reading is reused while the page text is unchanged; dropped when not used for this long
FORMATS = ("buffet", "daily", "fixed", "a_la_carte", "set")
DAYS = ["ma", "ti", "ke", "to", "pe", "la", "su"]

SYSTEM = """You read the text of a Finnish restaurant's own web page and say how the restaurant serves its weekday LUNCH (lounas).
Use ONLY what the text says. Never guess. If the page does not say that the restaurant serves lunch, answer {"lunch": false}.
Answer with one compact JSON object only:
{"lunch": true, "format": "buffet" | "daily" | "fixed" | "a_la_carte" | "set" | null, "days": "ma-pe" | null, "hours": "10.30-14.00" | null, "price": 13.9 | null, "price_max": null, "quote": "..."}
- format: buffet = lunch buffet / noutopöytä; daily = a lunch menu that changes daily or weekly; fixed = the same lunch dishes every day; a_la_carte = lunch ordered from a menu (lounas à la carte, lounasannokset listalta); set = a lunch set menu (e.g. 2 or 3 courses). null if not stated.
- days: lunch days with Finnish abbreviations ma ti ke to pe la su, e.g. "ma-pe", "to-la", "ma-la", "ma,ke,pe". null if not stated.
- hours: lunch serving hours, e.g. "10.30-14.00". Not the restaurant's opening hours unless they are explicitly lunch hours. null if not stated.
- price: the regular adult lunch price in euros (the lowest if several lunch options); price_max: the highest lunch price if a range or several options are listed. Not student, child or senior prices, not drinks, sides or desserts. null if not stated.
- quote: copy VERBATIM from the text the shortest passage (max 160 characters) that shows the lunch information. Do not change a single character."""

PV = hashlib.sha256(SYSTEM.encode()).hexdigest()[:6]


def norm(s):
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip().lower()


def page_text(v):
    return "\n\n".join(p.get("text", "") for p in v.get("pages", []))[:MAX_CHARS]


def call(text, name):
    import urllib.request, urllib.error, time
    body = {"model": MODEL, "max_tokens": 400, "system": SYSTEM,
            "messages": [{"role": "user", "content": f"Restaurant: {name}\n\nPage text:\n{text}"}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.load(r)
            out = "".join(c.get("text", "") for c in j.get("content", []))
            i = out.find("{")
            try:
                return (json.JSONDecoder().raw_decode(out[i:])[0] if i >= 0 else {"error": "no json"}), j.get("usage", {})
            except ValueError:
                return {"error": "bad json"}, j.get("usage", {})
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                time.sleep(6 * (attempt + 1))
                continue
            return {"error": f"http {e.code}"}, {}
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
                continue
            return {"error": str(e)[:80]}, {}
    return {"error": "gave up"}, {}


def norm_days(s):
    """'ma-pe' / 'to–la' / 'ma, ke, pe' -> canonical text + set of weekday indexes (0 = Monday); None if unclear."""
    s = norm(s).replace("–", "-").replace("—", "-").replace(" ", "")
    if not s:
        return None
    idx = set()
    for part in s.split(","):
        m = re.fullmatch(r"(ma|ti|ke|to|pe|la|su)(?:-(ma|ti|ke|to|pe|la|su))?", part)
        if not m:
            return None
        a = DAYS.index(m.group(1))
        b = DAYS.index(m.group(2)) if m.group(2) else a
        if b < a:
            return None
        idx.update(range(a, b + 1))
    txt = ", ".join((f"{DAYS[x[0]]}–{DAYS[x[-1]]}" if len(x) > 1 else DAYS[x[0]]) for x in runs(sorted(idx)))
    return txt, sorted(idx)


def runs(xs):
    out = []
    for x in xs:
        if out and x == out[-1][-1] + 1:
            out[-1].append(x)
        else:
            out.append([x])
    return out


def hm(s):
    m = re.fullmatch(r"(\d{1,2})(?:[.:](\d{2}))?", s.strip())
    if not m or int(m.group(1)) > 23:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def norm_hours(s, text):
    s = (s or "").replace("–", "-").replace("—", "-")
    parts = [p for p in s.split("-") if p.strip()]
    if len(parts) != 2:
        return None
    a, b = hm(parts[0]), hm(parts[1])
    if not a or not b or not (8 <= a[0] <= 15) or not (11 <= b[0] <= 18) or b <= a:
        return None
    # both hours must be written on the page (e.g. "11" and "14" in "klo 11–14")
    t = norm(text)
    pat = lambda h: rf"(?<!\d){h[0]}[.:]{h[1]:02d}(?!\d)" if h[1] else rf"(?<!\d){h[0]}(?:[.:]00)?(?![\d]|[.:]\d)"
    if not all(re.search(pat(h), t) for h in (a, b)):
        return None
    f = lambda h: f"{h[0]}.{h[1]:02d}" if h[1] else str(h[0])
    return f"{f(a)}–{f(b)}"


def price_on_page(p, text):
    if p is None:
        return None
    try:
        p = round(float(p), 2)
    except (TypeError, ValueError):
        return None
    if not (5 <= p <= 45):
        return None
    t = norm(text)
    e, c = int(p), int(round((p - int(p)) * 100))
    pats = [rf"(?<![\d,.]){e}[,.]{c:02d}(?!\d)"] + ([rf"(?<![\d,.]){e}[,.]{c // 10}(?!\d)"] if c % 10 == 0 else []) + \
           ([rf"(?<![\d,.]){e}(?:[,.]-|,00)?\s*(?:€|e\b|eur)", rf"(?<![\d,.]){e}[,.]-"] if c == 0 else [])
    return p if any(re.search(x, t) for x in pats) else None


def validate(r, text):
    """Keep only what the page text supports. Returns a compact dict or None."""
    if not isinstance(r, dict) or r.get("error") or r.get("lunch") is not True:
        return None
    q = norm(r.get("quote"))
    if len(q) < 8 or q not in norm(text):
        return None  # the model must quote the page verbatim
    out = {"q": (r.get("quote") or "").strip()[:200]}
    if r.get("format") in FORMATS:
        out["f"] = r["format"]
    d = norm_days(r.get("days") or "")
    if d:
        out["days"], out["di"] = d
    h = norm_hours(r.get("hours"), text)
    if h:
        out["h"] = h
    p = price_on_page(r.get("price"), text)
    if p:
        out["p"] = p
        p2 = price_on_page(r.get("price_max"), text)
        if p2 and p2 > p:
            out["p2"] = p2
    return out if len(out) > 1 else None


def listed_ids(week, data_dir):
    """Restaurants that already have a list this week (from the AI reader and the rule reader)."""
    ids = set()
    for d in week:
        for f in glob.glob(os.path.join(data_dir, f"menus_*_{d}.json")):
            try:
                for r in json.load(open(f)).get("results", []):
                    if r.get("items") or r.get("status") in ("ok_daily", "ok_fixed"):
                        ids.add(r.get("id"))
            except Exception:
                pass
    return ids


def main(inp, days, out, landed_path=None):
    week = days.split(",")
    data_dir = os.path.dirname(out) or "."
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ai_info: no ANTHROPIC_API_KEY, keeping the previous lunch_info.json", file=sys.stderr)
        return
    pages = json.load(open(inp))
    cp = os.path.join(data_dir, "info_cache.json")
    try:
        cache = json.load(open(cp))
    except Exception:
        cache = {}
    landed = set()
    if landed_path and os.path.exists(landed_path):
        try:
            landed = {r["key"] for r in json.load(open(landed_path))[0]["results"]}
        except Exception:
            pass
    has_list = listed_ids(week, data_dir)
    today = datetime.date.today().isoformat()
    # only restaurants without a list this week; Google landing pages first (that is where visitors arrive)
    todo = [(k, v) for k, v in pages.items() if k not in has_list and page_text(v).strip()]
    slug_of = lambda v: re.sub(r"[^a-z0-9]+", "-", (v.get("name") or "").lower()).strip("-")[:40]
    todo.sort(key=lambda kv: (not any(slug_of(kv[1]) and x.startswith(slug_of(kv[1])) for x in landed), kv[0]))
    spent, tin, tout, new, hits, skipped = [0.0], [0], [0], [0], [0], [0]

    def one(kv):
        k, v = kv
        text = page_text(v)
        h = hashlib.sha256(f"{PV}|{MODEL}|{text}".encode()).hexdigest()[:24]
        if h in cache:
            cache[h]["t"] = today
            hits[0] += 1
            return k, v, text, cache[h]["r"]
        if spent[0] >= BUDGET:
            skipped[0] += 1
            return k, v, text, None
        r, u = call(text, v.get("name", ""))
        ti, to = u.get("input_tokens", 0), u.get("output_tokens", 0)
        tin[0] += ti; tout[0] += to; spent[0] += ti / 1e6 * 0.10 + to / 1e6 * 0.50; new[0] += 1
        if not r.get("error"):
            cache[h] = {"r": r, "t": today}
        return k, v, text, r

    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(one, todo))
    try:
        old = json.load(open(out))
    except Exception:
        old = {}
    info, stats = {}, {"candidates": len(todo), "new": new[0], "cache_hits": hits[0], "skipped_budget": skipped[0], "kept": 0, "no_lunch_or_unsupported": 0}
    for k, v, text, r in res:
        if r is None:  # out of budget this run: keep the earlier reading
            if k in old:
                info[k] = old[k]
            continue
        x = validate(r, text)
        if not x:
            stats["no_lunch_or_unsupported"] += 1
            continue
        x["u"] = (v.get("pages") or [{}])[0].get("url") or v.get("website")
        x["c"] = old.get(k, {}).get("c") if old.get(k, {}).get("q") == x["q"] else today
        x["c"] = x["c"] or today
        info[k] = x
        stats["kept"] += 1
    json.dump(info, open(out, "w"), ensure_ascii=False, indent=0)
    keep = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    json.dump({h: c for h, c in cache.items() if c.get("t", "") >= keep}, open(cp, "w"), ensure_ascii=False)
    print(f"ai_info: {json.dumps(stats)} tokens in {tin[0]} out {tout[0]} ≈ ${spent[0]:.3f}", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:5])
