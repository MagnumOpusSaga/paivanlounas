"""Find websites for registry venues that have none, by trying likely domains (name.fi, name.com, ...)
and keeping only a site whose front page shows the venue's street name or postal code and part of its name.
Usage: find_websites.py <registry.json> <out.json> [limit|0] [round 1|2]"""
import json, re, sys, html, unicodedata, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "fi,en;q=0.8"}
STOP = {"ravintola", "restaurant", "ravintolat", "oy", "ab", "ltd", "kahvila", "cafe", "café", "bistro", "helsinki", "the", "ja", "and", "&",
        "lounasravintola", "pizzeria", "kebab", "grill", "baari", "bar", "pub", "ky", "tmi", "oyj", "co", "by", "och"}
SKIP_NAME = re.compile(r"(?i)hoiva|päiväkoti|koulu|sairaala|palvelutalo|kotihoito|asumis|neste|st1|abc|teboil|r-kioski|fazer|espresso house|"
                       r"robert'?s coffee|hesburger|mcdonald|subway|kotipizza|burger king|picnic|k-market|k-supermarket|s-market|alepa|lidl|sale\b")
PARKED = re.compile(r"(?i)domain (is )?for sale|verkkotunnus on myynnissä|this domain|parked|buy this domain|godaddy|sedo|hostinger|"
                    r"under construction|tulossa pian|coming soon|default web page|it works!|index of /")


def ascii_(s):
    s = (s or "").lower().replace("ä", "a").replace("ö", "o").replace("å", "a")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def tokens(name):
    t = [w for w in re.findall(r"[a-z0-9]+", ascii_(name)) if w not in STOP]
    return t[:4]


def candidates(name, operator=None, round2=False):
    t = tokens(name)
    if round2:
        return candidates2(name, operator)
    if not t or len("".join(t)) < 4:
        return []
    j, h = "".join(t), "-".join(t)
    c = [f"{j}.fi", f"{h}.fi", f"ravintola{j}.fi", f"{j}.com", f"ravintola-{h}.fi", f"{j}helsinki.fi", f"{j}helsinki.com"]
    if len(t) > 1:
        c += [f"{t[0]}{t[1]}.fi", f"{t[0]}.fi"] if len(t[0]) >= 5 else [f"{t[0]}{t[1]}.fi"]
    out = []
    for x in c:
        if x not in out and len(x) <= 40:
            out.append(x)
    return out


def candidates2(name, operator):
    """Second round: patterns the first round did not try."""
    t = tokens(name)
    out = []
    if t and len("".join(t)) >= 4:
        j, h = "".join(t), "-".join(t)
        out += [f"cafe{j}.fi", f"kahvila{j}.fi", f"{j}.eu", f"{j}.net", f"{h}.com", f"{j}restaurant.fi", f"{j}ravintola.fi", f"{j}lounas.fi",
                f"ravintola{j}.com", f"{j}hki.fi", f"{h}-helsinki.fi"]
        if len(t) > 2:
            out += [f"{t[0]}{t[1]}{t[2]}.fi", f"{t[0]}-{t[1]}.fi", f"{t[0]}{t[1]}.com"]
    op = [w for w in re.findall(r"[a-z0-9]+", ascii_(operator or "")) if w not in STOP]
    if op and len("".join(op)) >= 4:
        oj = "".join(op[:3])
        out += [f"{oj}.fi", f"{'-'.join(op[:3])}.fi", f"{oj}.com"]
    res = []
    for x in out:
        if x not in res and len(x) <= 40:
            res.append(x)
    return res


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10) as r:
            if "html" not in r.headers.get("Content-Type", ""):
                return None, ""
            return r.geturl(), r.read(1_500_000).decode("utf-8", "replace")
    except Exception:
        return None, ""


def text_of(s):
    s = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", s)
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


ROUND2 = False


def check(v):
    street = re.match(r"([^\d,]+)", v.get("street") or "")
    street = ascii_(street.group(1)).strip() if street else ""
    postal = v.get("postal") or ""
    toks = tokens(v["name"])
    for dom in candidates(v["name"], v.get("operator"), ROUND2):
        final, body = fetch("https://" + dom)
        if not final:
            final, body = fetch("https://www." + dom)
        if not final:
            continue
        low = ascii_(text_of(body))
        if len(low) < 300 or PARKED.search(low[:5000]):
            continue
        has_addr = (len(street) >= 5 and street in low) or (postal and postal in low)
        has_name = sum(1 for t in toks if len(t) >= 3 and t in low) >= max(1, min(2, len(toks)))
        if has_addr and has_name:
            return {"id": v["id"], "name": v["name"], "website": final, "domain": dom, "lunch": bool(re.search(r"\blounas|\blunch", low))}
    return None


def main(reg_path, out, limit=None, rnd="1"):
    global ROUND2
    ROUND2 = rnd == "2"
    reg = json.load(open(reg_path))
    todo = [v for v in reg if not v.get("website") and not v["sources"] and not SKIP_NAME.search(v["name"])
            and v.get("kind") in (None, "Kahvilat ja ravintolat", "Ruokalat")]
    if limit and int(limit):
        todo = todo[:int(limit)]
    print("venues to try", len(todo), file=sys.stderr)
    with ThreadPoolExecutor(24) as ex:
        found = [x for x in ex.map(check, todo) if x]
    json.dump(found, open(out, "w"), ensure_ascii=False, indent=1)
    print("found", len(found), "with lunch word", sum(x["lunch"] for x in found), file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:5])
