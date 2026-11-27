"""AI reader: turn restaurants' own lunch pages into structured menus with Claude Haiku.
Usage: ai_reader.py <web_pages.json> <comma-separated week dates> <out pattern with {day}>
Needs ANTHROPIC_API_KEY. Without it, writes nothing and exits 0.
Input: pages saved by fetch_independent.py (text already extracted from HTML)."""
import json, os, re, sys, time, hashlib, base64, collections, urllib.request, urllib.error, datetime
from concurrent.futures import ThreadPoolExecutor

MODEL = os.environ.get("LOUNAS_AI_MODEL", "claude-haiku-5-5")
MAX_SITES = int(os.environ.get("LOUNAS_AI_MAX", "700"))
BUDGET = float(os.environ.get("LOUNAS_AI_BUDGET", "0.23"))  # max new spend per run in USD (~0.20 EUR); cached readings are free
MAX_CHARS = 12000  # changing this changes cache keys (all pages re-read), so keep it stable
PRICE_IN, PRICE_OUT = 0.10, 0.50  # Claude Haiku 5.5, USD per million tokens
WD = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai"]

SYSTEM = """You extract lunch menus (lounas) from the text of a Finnish restaurant's web page.
Rules:
- Use ONLY what the text says. Never invent dishes, prices or dates.
- Return dishes only for the weekdays of the week given by the user. If the page clearly shows a different week (stale list, other dates), return "stale": true and empty "days".
- If the page lists a fixed lunch that is the same every weekday (e.g. "Lounas ma-pe: ..."), put it in "fixed" instead of "days".
- Set "belongs": false ONLY if the menu clearly belongs to another, differently named restaurant (e.g. a listing or chain page that shows other places and not this one). Brand names, company names, abbreviations and the restaurant's other spellings count as the same restaurant; a restaurant's own site is the same restaurant even if the name is not repeated.
- Extract ONLY the weekday lunch (lounas, served on weekdays around 10.30–15). Ignore the regular à la carte / dinner menu, Christmas lunch (joululounas), brunch, events and drinks. If the page has no separate lunch offer, return empty "days" and "fixed". Photos of food or the room are not menus: return empty "days".
- Dishes: keep the original language and wording, one dish per entry, without the price. Remove day names, opening hours and marketing text.
- diet: only markings written next to the dish, normalised to: L, G, M, VL, Veg (vegan/vegaani/VE/V), K (kasvis).
- price: the regular adult lunch price in euros for that dish (or for the whole lunch) if shown; otherwise null.
  Use the normal price, NOT student, staff, child or senior prices, NOT the price of a side, extra, drink or dessert, and NOT a price for two people.
  If the soup or salad is sold on its own as a cheaper lunch option, give that dish its own price and keep the word soup/keitto/salaatti in the dish.
- hours: lunch serving hours if shown, like "10.30-14.00", else null.
Answer with one compact JSON object only (no code fence, no prose). At most 15 dishes per day:
{"belongs": true, "stale": false, "hours": null, "fixed": [], "days": {"YYYY-MM-DD": [{"dish": "...", "diet": ["L"], "price": 12.9}]}}"""


PV = hashlib.sha256(SYSTEM.encode()).hexdigest()[:6]  # prompt version: a changed prompt re-reads pages
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
IMG_TYPES = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


def download(url, maxb):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            b = r.read(maxb + 1)
            return (b if len(b) <= maxb else None), r.headers.get("Content-Type", "")
    except Exception:
        return None, ""


def media_blocks(v):
    """PDF and image blocks for the API, downloaded here (PDF max 8 MB, image max 4 MB)."""
    blocks, ids = [], []
    for u in v.get("pdfs", [])[:1]:
        b, ct = download(u, 8_000_000)
        if b and b[:4] == b"%PDF":
            blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(b).decode()}})
            ids.append(hashlib.sha256(b).hexdigest()[:16])
    for u in v.get("imgs", [])[:1]:
        b, ct = download(u, 4_000_000)
        if not b or len(b) < 15_000:  # tiny images are icons, not menus
            continue
        kind = ct.split("/")[-1].split(";")[0].strip().lower() if ct.startswith("image/") else u.lower().rsplit(".", 1)[-1].split("?")[0]
        if kind not in IMG_TYPES:
            continue
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": IMG_TYPES[kind], "data": base64.b64encode(b).decode()}})
        ids.append(hashlib.sha256(b).hexdigest()[:16])
    return blocks, ids


def call(text, name, week, blocks=None):
    wk = ", ".join(f"{WD[i]} {d}" for i, d in enumerate(week))
    if blocks:
        content = blocks + [{"type": "text", "text": f"Restaurant: {name}\nThis week: {wk}\n\nThe attached PDF/images are from the restaurant's website. "
                                                       f"Read the lunch menu from them. Page text for context:\n{text[:3000]}"}]
    else:
        content = f"Restaurant: {name}\nThis week: {wk}\n\nPage text:\n{text}"
    body = {"model": MODEL, "max_tokens": 8000, "system": SYSTEM, "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                j = json.load(r)
            out = "".join(c.get("text", "") for c in j.get("content", []))
            i = out.find("{")
            if i < 0:
                return {"error": "no json: " + out[:60]}, j.get("usage", {})
            try:
                return json.JSONDecoder().raw_decode(out[i:])[0], j.get("usage", {})
            except ValueError:
                return {"error": "bad json" + (" (cut)" if j.get("stop_reason") == "max_tokens" else "")}, j.get("usage", {})
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
    todo = list(pages.items())[:MAX_SITES]

    cp = os.path.join(os.path.dirname(inp) or ".", "ai_cache.json")
    try:
        cache = json.load(open(cp))
    except Exception:
        cache = {}
    hits = 0
    media_n = [0]
    todo.sort(key=lambda kv: f"last:{kv[0]}" not in cache)  # sites that had a menu go first when the budget is tight

    def has_days(r):
        return isinstance(r, dict) and not r.get("error") and r.get("belongs") is not False and not r.get("stale") and \
            any(r.get("days", {}).get(d) for d in week)

    def has_menu(r):
        return isinstance(r, dict) and not r.get("error") and r.get("belongs") is not False and not r.get("stale") and \
            (any(r.get("days", {}).get(d) for d in week) or bool(r.get("fixed")))

    import threading
    lock = threading.Lock()
    spent = [0.0]
    skipped = {"budget": 0, "neg": 0}
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=2))).date()
    budget = BUDGET * (3 if today.weekday() == 0 else 1)  # Monday: new week, everything is read once

    def can_spend():
        with lock:
            if spent[0] >= budget:
                skipped["budget"] += 1
                return False
            return True

    def add_cost(u):
        c = u.get("input_tokens", 0) / 1e6 * PRICE_IN + u.get("output_tokens", 0) / 1e6 * PRICE_OUT
        with lock:
            spent[0] += c

    def neg_recent(key):
        """Site found no lunch in the last 3 days of this week → don't pay to read it again yet."""
        x = cache.get(key)
        return bool(x and x["d"] == week[0] and (today - datetime.date.fromisoformat(x["t"])).days < 3)

    def one(kv):
        nonlocal hits
        k, v = kv
        text = "\n\n---\n\n".join(f"[{p['url']}]\n{p['text']}" for p in v["pages"])[:MAX_CHARS]
        h = hashlib.sha256(f"{MODEL}|{PV}|{v['name']}|{week[0]}|{text}".encode()).hexdigest()[:24]
        last, neg = f"last:{k}", f"neg:{k}"
        usage = {}
        res = {}
        if text and h in cache:
            hits += 1
            res = cache[h]["r"]
        elif text and neg_recent(neg):
            skipped["neg"] += 1
        elif text and can_spend():
            res, usage = call(text, v["name"], week)
            add_cost(usage)
            if isinstance(res, dict) and not res.get("error"):
                cache[h] = {"r": res, "d": week[0]}
        elif text and last in cache and cache[last]["d"] == week[0]:
            res = cache[last]["r"]  # out of budget: keep this week's last good reading
        # nothing from the text → try the menu PDF / one image (images only when the page talks about lunch).
        # A PDF is also read when the text only gave a fixed lunch ("Lounasbuffet 13,50 €") – the dishes of the week are
        # often only in the PDF (feedback 27.11.: Kuusenkerkkä showed "Lounasbuffet" while VIIKKO-48.pdf had every day's food)
        imgs_ok = bool(v["pages"])
        want_pdf = bool(v.get("pdfs")) and not has_days(res)
        if (not has_menu(res) or want_pdf) and (v.get("pdfs") or (imgs_ok and v.get("imgs"))) and not neg_recent(neg + ":m"):
            blocks, ids = media_blocks(v if imgs_ok and not has_menu(res) else {**v, "imgs": []})
            if blocks:
                hm = hashlib.sha256(f"{MODEL}|{PV}|media|{v['name']}|{week[0]}|{'|'.join(ids)}".encode()).hexdigest()[:24]
                r2 = {}
                if hm in cache:
                    hits += 1
                    r2 = cache[hm]["r"]
                elif can_spend():
                    r2, u2 = call(text, v["name"], week, blocks)
                    add_cost(u2)
                    for kk, n in u2.items():
                        if isinstance(n, int):
                            usage[kk] = usage.get(kk, 0) + n
                    if isinstance(r2, dict) and not r2.get("error"):
                        cache[hm] = {"r": r2, "d": week[0]}
                    media_n[0] += 1
                if has_menu(r2) and (not has_menu(res) or has_days(r2)):
                    r2 = dict(r2)
                    r2["_media"] = True
                    fp = [x.get("price") for x in (res.get("fixed") or []) if isinstance(res, dict) and x.get("price")] if isinstance(res, dict) else []
                    if fp:  # the page's buffet price for PDF dishes that carry no price
                        r2["days"] = {d: [{**x, "price": x.get("price") or min(fp)} for x in (xs or [])] for d, xs in (r2.get("days") or {}).items()}
                    r2["hours"] = r2.get("hours") or (res.get("hours") if isinstance(res, dict) else None)
                    res = r2
                elif isinstance(r2, dict) and r2 and not r2.get("error"):
                    with lock:
                        cache[neg + ":m"] = {"d": week[0], "t": today.isoformat()}
        with lock:
            if has_menu(res):
                # keep enough of the page to show the list even if the site does not open in a later run today
                vv = {"name": v["name"], "website": v.get("website"), "pages": [{"url": p["url"], "text": ""} for p in v["pages"][:1]],
                      "pdfs": (v.get("pdfs") or [])[:1], "imgs": []}
                cache[last] = {"r": res, "d": week[0], "vv": vv}
                cache.pop(neg, None)
            elif isinstance(res, dict) and res and not res.get("error"):
                cache[neg] = {"d": week[0], "t": today.isoformat()}
        return k, v, res, usage

    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(one, todo))
    dbg = set(filter(None, os.environ.get("LOUNAS_DEBUG", "").split(",")))
    for k, v, r, _ in results:
        if k in dbg:
            print("debug", k, json.dumps(r, ensure_ascii=False)[:600], file=sys.stderr)
    # a site that does not open in this run (timeout, error, page changed for the day) keeps this week's last good
    # reading: later runs of the day lost ~50 lists that were read fine in the morning (27.11.: 336 -> 288)
    seen_k = {k for k, *_ in results}
    carried = 0
    for ck, cv in list(cache.items()):
        k = ck[5:] if ck.startswith("last:") else None
        if k and k not in seen_k and cv.get("d") == week[0] and cv.get("vv") and has_menu(cv.get("r")):
            results.append((k, cv["vv"], cv["r"], {}))
            carried += 1
    # keep only this and last week's entries
    keep = (datetime.date.fromisoformat(week[0]) - datetime.timedelta(days=7)).isoformat()
    json.dump({h: x for h, x in cache.items() if x["d"] >= keep}, open(cp, "w"), ensure_ascii=False)
    errs = collections.Counter(r["error"] for _, _, r, _ in results if isinstance(r, dict) and r.get("error"))
    tin = sum(u.get("input_tokens", 0) for *_, u in results)
    tout = sum(u.get("output_tokens", 0) for *_, u in results)
    per_day = {d: [] for d in week}
    stats = {"sites": len(results), "cache_hits": hits, "skipped_budget": skipped["budget"], "skipped_no_lunch": skipped["neg"], "media_tried": media_n[0], "ok": 0, "fixed": 0, "stale": 0, "other_restaurant": 0, "errors": 0, "empty": 0, "carried_over": carried}
    for k, v, r, _ in results:
        if not r:
            stats["empty"] += 1
            continue
        if not isinstance(r, dict) or r.get("error"):
            stats["errors"] += 1
            continue
        if r.get("belongs") is False:
            stats["other_restaurant"] += 1
            continue
        if r.get("stale"):
            stats["stale"] += 1
            continue
        url = ((v.get("pdfs") or [None])[0] if r.get("_media") and v.get("pdfs") else None) or (v["pages"][0]["url"] if v["pages"] else v.get("website"))
        if r.get("_media"):
            stats["media_ok"] = stats.get("media_ok", 0) + 1
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
