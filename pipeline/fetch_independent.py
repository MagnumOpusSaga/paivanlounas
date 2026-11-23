"""Read today's lunch from independent restaurants' own websites (heuristic pilot reader).
Usage: fetch_independent.py <restaurants.json> <YYYY-MM-DD> <out.json>
Each restaurant needs: id, name, website."""
import os, json, re, sys, time, html, datetime, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "fi,en;q=0.8"}
DAYS_FI = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"]
DAYS_SHORT = ["ma", "ti", "ke", "to", "pe", "la", "su"]
DAYS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
LINK_WORDS = re.compile(r"lounas|lunch|ruokalista|lounaslista|menu|viikko|week", re.I)
SOCIAL = re.compile(r"facebook\.com|instagram\.com|fb\.me|linktr\.ee", re.I)
PRICE = re.compile(r"\d{1,2}(?:[,.]\d{1,2})?\s*(?:€|eur)", re.I)


def fetch(url, maxb=2_500_000):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            ct = r.headers.get("Content-Type", "")
            b = r.read(maxb)
            return r.geturl(), ct, b
    except Exception as e:
        return url, "error:" + type(e).__name__, b""


def to_text(b):
    s = b.decode("utf-8", "replace")
    s = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|td|section|article)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return "\n".join(l.strip() for l in s.splitlines() if l.strip())


def links(base, b):
    s = b.decode("utf-8", "replace")
    out = []
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', s, re.I | re.S):
        href, txt = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        if LINK_WORDS.search(href) or LINK_WORDS.search(txt):
            u = urllib.parse.urljoin(base, href)
            if u.startswith("http") and u not in out:
                out.append(u)
    return out


IMG_WORDS = re.compile(r"lounas|lunch|ruokalista|menu|viikko|week|vko|ruoka", re.I)
IMG_SKIP = re.compile(r"logo|icon|favicon|sprite|banner-?ad|avatar|flag|payment|wolt|foodora", re.I)


def images(base, b):
    """Image URLs that look like a lunch menu (file name or alt text mentions lunch/menu)."""
    s = b.decode("utf-8", "replace")
    out = []
    for m in re.finditer(r"<img\b[^>]*>", s, re.I):
        tag = m.group(0)
        src = re.search(r'(?:data-src|data-lazy-src|src)=["\']([^"\']+)["\']', tag, re.I)
        if not src:
            continue
        alt = re.search(r'(?:alt|title)=["\']([^"\']*)["\']', tag, re.I)
        u = urllib.parse.urljoin(base, html.unescape(src.group(1)))
        name = urllib.parse.unquote(urllib.parse.urlparse(u).path.rsplit("/", 1)[-1])
        if not re.search(r"\.(jpe?g|png|webp)$", name, re.I) or IMG_SKIP.search(name):
            continue
        if IMG_WORDS.search(name) or (alt and IMG_WORDS.search(alt.group(1))):
            if u.startswith("http") and u not in out:
                out.append(u)
    return out[:3]


TIME_LINE = re.compile(r"^[\w\s.,–:-]{0,20}\d{1,2}([.:]\d{2})?\s*[-–]\s*\d{1,2}([.:]\d{2})?\s*$")
FOODISH = re.compile(r"(?i)\b(L|G|M|VL|VE|VEG|VS)\b|\(|kastike|keitto|pihvi|broiler|kana|lohi|kala|riisi|peruna|pasta|salaatti|"
                     r"curry|pata|uuni|paisti|vegaani|kasvis|soup|chicken|salmon|beef|pork|tofu|wok|nuudeli|noodle|jälki|dessert")


def day_block(text, day):
    dt = datetime.date.fromisoformat(day)
    wd = dt.weekday()
    low = text.lower()
    # weekly menu structure: at least 3 weekday names or dates of this week present
    week = [dt + datetime.timedelta(days=i - wd) for i in range(5)]
    hits = sum(1 for i, d in enumerate(week)
               if re.search(rf"\b({DAYS_FI[i]}|{DAYS_EN[i]})\b", low) or re.search(rf"\b0?{d.day}\.0?{d.month}\.", low))
    if hits < 3:
        return None
    head = re.compile(rf"\b({DAYS_FI[wd]}|{DAYS_EN[wd]})\b|\b{DAYS_SHORT[wd]}\s+0?{dt.day}\.0?{dt.month}\.|\b0?{dt.day}\.0?{dt.month}\.(?!\d)", re.I)
    others = [d for i, d in enumerate(DAYS_FI[:5] + DAYS_EN[:5]) if i % 5 != wd]
    others_dates = [rf"0?{d.day}\.0?{d.month}\." for d in week if d != dt]
    nxt = re.compile(r"\b(" + "|".join(others) + r")\b|(?<!\d)(" + "|".join(others_dates) + r")", re.I)
    for m in head.finditer(low):
        start = m.end()
        n = nxt.search(low, start)
        end = n.start() if n else min(len(low), start + 1200)
        block = text[start:end].strip()
        lines = [l for l in block.split("\n") if l.strip()]
        food = [l for l in lines if FOODISH.search(l) and not TIME_LINE.match(l) and len(l) > 8]
        if 1 <= len(lines) <= 40 and food:
            return block
    return None


def weekly_lunch(text):
    """Restaurants with a fixed daily lunch (buffet) and no per-day menu."""
    for m in re.finditer(r"(?i)(lounas|lunch)[^\n]{0,120}", text):
        seg = text[m.start(): m.start() + 600]
        if PRICE.search(seg) and re.search(r"(?i)ma\s*[-–]\s*pe|mon\w*\s*[-–]\s*fri|arkisin|weekdays|klo|\d{1,2}[.:]\d{2}", seg):
            return seg
    return None


def read(r, days):
    site = r.get("website")
    if not site:
        return {"status": "no_website"}
    if not site.startswith("http"):
        site = "http://" + site
    if SOCIAL.search(site):
        return {"status": "social_only", "url": site}
    if "lounaat.info" in site:
        return {"status": "competitor_link", "url": site}
    final, ct, b = fetch(site)
    if ct.startswith("error"):
        pu = urllib.parse.urlparse(site)
        host = pu.netloc[4:] if pu.netloc.startswith("www.") else "www." + pu.netloc
        for alt in (pu._replace(netloc=host).geturl(), pu._replace(scheme="http").geturl()):
            final, ct, b = fetch(alt)
            if not ct.startswith("error"):
                break
    if ct.startswith("error"):
        return {"status": "unreachable", "url": site, "err": ct}
    pages = [(final, ct, b)]
    for u in links(final, b)[:4]:
        if SOCIAL.search(u) or "lounaat.info" in u:
            continue
        pages.append(fetch(u))
        time.sleep(0.2)
    saw_pdf = saw_lunch_word = False
    texts, imgs = [], []
    for url, ct, body in pages:
        if body and "html" in ct:
            imgs += [i for i in images(url, body) if i not in imgs]
        if "pdf" in ct:
            saw_pdf = True
            continue
        if not body or "html" not in ct and "text" not in ct:
            continue
        t = to_text(body)
        if re.search(r"(?i)\blounas|\blunch", t):
            saw_lunch_word = True
        texts.append((url, t))
    out = {}
    for d in days:
        res = None
        best_weekly = None
        for url, t in texts:
            blk = day_block(t, d)
            if blk and saw_lunch_word:
                res = {"status": "ok_daily", "url": url, "text": blk[:1500]}
                break
            w = weekly_lunch(t)
            if w and not best_weekly:
                best_weekly = (url, w)
        if not res:
            if best_weekly:
                res = {"status": "ok_fixed", "url": best_weekly[0], "text": best_weekly[1][:800]}
            elif saw_pdf:
                res = {"status": "pdf_menu", "url": final}
            elif saw_lunch_word:
                res = {"status": "lunch_mentioned_unparsed", "url": final}
            else:
                res = {"status": "no_lunch_found", "url": final}
        out[d] = res
    # pages that mention lunch, kept for the AI reader (main page first)
    lp = [(u, t) for u, t in texts if re.search(r"(?i)\blounas|\blunch", t)]
    out["_pages"] = [{"url": u, "text": t[:9000]} for u, t in lp[:2]]
    pdfs = [u for u, ct, _ in pages if "pdf" in ct]
    pdfs += [u for u in links(final, b) if u.lower().split("?")[0].endswith(".pdf") and u not in pdfs]
    out["_pdfs"] = pdfs[:2]
    out["_imgs"] = imgs[:3]
    return out


def main(inp, days, out):
    """days: comma-separated dates; out: path with {day} placeholder (or a plain path for one day)."""
    days = days.split(",")
    rest = json.load(open(inp))
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda r: (r, read(r, days)), rest))
    pages = {r["id"]: {"name": r["name"], "website": r.get("website"), "pages": x["_pages"], "pdfs": x["_pdfs"], "imgs": x["_imgs"]}
             for r, x in res if "status" not in x and (x["_pages"] or x["_pdfs"] or x["_imgs"])}
    json.dump(pages, open(os.path.join(os.path.dirname(out), "web_pages.json"), "w"), ensure_ascii=False)
    for d in days:
        rows = [{"id": r["id"], "name": r["name"], "website": r.get("website"), **(x if "status" in x else x[d])} for r, x in res]
        json.dump({"date": d, "results": rows}, open(out.replace("{day}", d), "w"), ensure_ascii=False, indent=1)




if __name__ == "__main__":
    main(*sys.argv[1:4])
