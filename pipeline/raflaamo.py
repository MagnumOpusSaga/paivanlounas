"""Read today's lunch lists from Raflaamo's public Helsinki lunch page (server-rendered HTML).
Usage: raflaamo.py <out.json>"""
import html, json, re, sys, urllib.request

URL = "https://www.raflaamo.fi/fi/ravintolat/helsinki/lounas"


def main(out):
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 paivanlounas.fi"})
    h = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    L = [l.strip() for l in t.splitlines() if l.strip()]
    start = next((k for k, l in enumerate(L) if re.match(r"^(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai|Lauantai|Sunnuntai) \d", l)), None)
    rows, cur = [], None
    if start is not None:
        for k in range(start + 1, len(L)):
            l = L[k]
            if k + 1 < len(L) and re.match(r"^\d+([,.]\d)?\s*k?m$", L[k + 1]):
                cur = {"name": l, "items": []}
                rows.append(cur)
                continue
            if re.match(r"^(Lähetä palautetta|Näytä lisää|Raflaamo\.fi)", l):
                break
            if cur and not re.match(r"^\d+([,.]\d)?\s*k?m$|^Hinta:|^\d{1,2}:\d{2} - \d{1,2}:\d{2}$", l):
                cur["items"].append(l)
    json.dump(rows, open(out, "w"), ensure_ascii=False)
    print("raflaamo restaurants", len(rows), file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
