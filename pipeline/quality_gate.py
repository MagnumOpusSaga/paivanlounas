"""Quality gate before deploy (N41, Branu 26.11.: lists missing or late is never acceptable).
Writes date + lists_today into dist/data/status.json and decides whether to deploy:
  - today's lists >= 80 % of the usual (same weekday last week, else median of the last 5 stored days) -> deploy
  - below 80 % but the live site still shows an older day -> deploy anyway (a thinner today beats yesterday) + alert
  - below 80 % and the live site already has today -> keep the live site (exit 3) + alert
Prints 'alert=...' / 'deploy=...' lines for GitHub Actions (GITHUB_OUTPUT)."""
import datetime, json, os, statistics, sys, urllib.request

hist_p, dist = "data/lists_history.json", "dist"
wk = json.load(open(f"{dist}/data/week.json"))
day = wk["date"]
n = sum(1 for v in wk["venues"] if (v.get("ms") or {}).get(day))
try:
    hist = json.load(open(hist_p))
except Exception:
    hist = {}
prev = (datetime.date.fromisoformat(day) - datetime.timedelta(days=7)).isoformat()
older = [hist[d] for d in sorted(hist) if d < day][-5:]
# no history yet: the other weekdays of this week's lists (fetched ahead) stand in for "usual"
wkd = [sum(1 for v in wk["venues"] if (v.get("ms") or {}).get(d)) for d in wk.get("days", []) if d != day]
wkd = [x for x in wkd if x]
usual = hist.get(prev) or (statistics.median(older) if older else (statistics.median(wkd) if wkd else None))
live_day = None
try:
    live_day = json.load(urllib.request.urlopen(urllib.request.Request("https://paivanlounas.fi/data/status.json", headers={"User-Agent": "Mozilla/5.0 (paivanlounas quality gate)"}), timeout=15)).get("date")
except Exception as e:
    print("live status unreadable:", e)
ok = usual is None or n >= 0.8 * usual
deploy = ok or live_day != day
alert = "" if ok else f"Lounaslistoja {day}: {n}, tavallisesti {usual:.0f} (alle 80 %). Verkossa {'pidetään vanha' if not deploy else 'julkaistiin silti, koska verkossa oli ' + str(live_day)}."
print(f"lists today {n}, usual {usual}, live {live_day}, deploy {deploy}")
if deploy:
    hist[day] = max(n, hist.get(day, 0))
    json.dump(dict(sorted(hist.items())[-40:]), open(hist_p, "w"))
sp = f"{dist}/data/status.json"
try:
    st = json.load(open(sp))
except Exception:
    st = {}
st.update({"date": day, "lists_today": n, "lists_usual": round(usual) if usual else None})
json.dump(st, open(sp, "w"))
with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
    f.write(f"deploy={'1' if deploy else '0'}\nalert={alert}\n")
sys.exit(0)
