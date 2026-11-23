"""Collect Oiva inspection results for Helsinki (all food premises) via oivahymy.fi's public API.
Splits by postal code, then by name prefix when the 300-result cap is hit."""
import json, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

API = "https://www.oivahymy.fi/api/haku"
UA = {"User-Agent": "Mozilla/5.0 lounas-pilot", "Accept": "application/json"}
CAP = 300
LETTERS = "abcdefghijklmnopqrstuvwxyzåäö0123456789"


def q(**p):
    url = API + "?" + urllib.parse.urlencode(p)
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 + 2 * a)
    print("FAIL", url, file=sys.stderr)
    return []


def by_postal(pc):
    res = q(postinumero=pc)
    if len(res) < CAP:
        return res
    out = []
    for l in LETTERS:  # nimi matches substrings? we dedupe anyway
        out += q(postinumero=pc, nimi=l)
        time.sleep(0.2)
    return out


def main(out):
    codes = [f"00{n:03d}" for n in range(100, 1000, 10)]
    with ThreadPoolExecutor(4) as ex:
        chunks = list(ex.map(by_postal, codes))
    seen = {}
    for c in chunks:
        for r in c:
            if r.get("kunta", {}).get("kuntanumero") == "091":
                seen[r["kohdetoimintatunnus"]] = r
    rows = list(seen.values())
    json.dump(rows, open(out, "w"), ensure_ascii=False)
    capped = [codes[i] for i, c in enumerate(chunks) if len(c) >= CAP]
    print("oiva helsinki", len(rows), "capped postal codes", capped, file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
