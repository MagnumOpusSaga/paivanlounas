// N41 zero tolerance: today's lunch lists must be online Mon–Fri by 07.00 Helsinki time.
// GitHub's own schedule often starts 30–70 min late, so this Cloudflare cron checks /data/status.json
// at 05.30 and 06.30 Helsinki time and, if today's lists are missing or thin, starts the
// "Daily update" workflow itself (workflow_dispatch). At 06.30 it also opens an issue if they are still missing.
// Secret GH_TOKEN: fine-grained GitHub token for MagnumOpusSaga/paivanlounas only (Actions: write, Issues: write).
const REPO = "MagnumOpusSaga/paivanlounas";
const STATUS = "https://paivanlounas.fi/data/status.json";

function helsinkiNow() {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Helsinki", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", weekday: "short", hour12: false })
    .formatToParts(new Date()).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, hour: +p.hour, minute: +p.minute, weekday: p.weekday };
}

async function gh(env, path, init = {}) {
  return fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "paivanlounas-morning-check", "X-GitHub-Api-Version": "2022-11-28", ...(init.headers || {}) },
  });
}

export async function check(env, force = false) {
  const now = helsinkiNow();
  if (!force && (["Sat", "Sun"].includes(now.weekday) || ![5, 6].includes(now.hour))) return { skipped: "outside 05–06 Helsinki weekday window", now };
  let st = null;
  for (const u of [STATUS, "https://paivanlounas.pages.dev/data/status.json"]) {
    try {
      const r = await fetch(u + "?t=" + Date.now(), { headers: { "User-Agent": "Mozilla/5.0 (paivanlounas morning check)" }, cf: { cacheTtl: 0 } });
      if (r.ok) { st = await r.json(); break; }
    } catch (e) { /* try the next address */ }
  }
  const unread = !st; st = st || {};
  const fresh = st.date === now.date && (st.lists_today || 0) >= 0.8 * (st.lists_usual || 0);
  const out = { now, status: { date: st.date, lists_today: st.lists_today, lists_usual: st.lists_usual }, fresh, unread };
  if (fresh) return out;
  if (!env.GH_TOKEN) return { ...out, error: "GH_TOKEN secret missing - cannot start the workflow" };
  // do not pile up runs: a run already queued or running will publish soon
  const runs = await (await gh(env, "/actions/workflows/daily.yml/runs?per_page=5")).json();
  const busy = (runs.workflow_runs || []).some((r) => r.status === "queued" || r.status === "in_progress" || r.status === "waiting");
  out.busy = busy;
  if (!busy) {
    const r = await gh(env, "/actions/workflows/daily.yml/dispatches", { method: "POST", body: JSON.stringify({ ref: "main", inputs: { morning: "1" } }) });
    out.dispatched = r.status; // 204 = started
  }
  if (now.hour === 6 && now.minute >= 20) {
    const body = (unread ? "status.json ei auennut Workerista. " : "") + `Klo ${now.hour}.${String(now.minute).padStart(2, "0")} verkossa: päivä ${st.date || "?"}, listoja ${st.lists_today ?? "?"} / tavallinen ${st.lists_usual ?? "?"}. ` +
      (busy ? "Ajo on jo käynnissä." : "Aamutarkistus (Cloudflare Worker) käynnisti ajon.") + " N41: listojen pitää olla verkossa klo 7.00.";
    const r = await gh(env, "/issues", { method: "POST", body: JSON.stringify({ title: `Lounaslistat myöhässä ${now.date}`, body }) });
    out.issue = r.status;
  }
  return out;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(check(env).then((r) => console.log(JSON.stringify(r))));
  },
};
