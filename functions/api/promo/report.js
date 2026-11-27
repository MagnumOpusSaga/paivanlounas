// GET /api/promo/report?t=<secret token> – the buyer's report: days, impressions and clicks per day (no login)
import { adStats, zones, json, fiDay, MAKEGOOD } from "../../../lib/promo.js";
export async function onRequestGet({ request, env }) {
  const t = new URL(request.url).searchParams.get("t") || "";
  if (!/^[a-f0-9]{32}$/.test(t)) return json({ error: "bad" }, 400);
  const p = await env.DB.prepare("SELECT * FROM promos WHERE token = ?").bind(t).first();
  if (!p) return json({ error: "Raporttia ei löydy." }, 404);
  const r = await env.DB.prepare("SELECT day, kind, SUM(n) n FROM counters WHERE key = ? AND kind IN ('adimp','adclick') GROUP BY day, kind").bind(p.id).all();
  const per = {};
  for (const x of r.results || []) (per[x.day] ||= { imp: 0, click: 0 })[x.kind === "adimp" ? "imp" : "click"] = x.n;
  const tot = (await adStats(env, [p.id]))[p.id] || { imp: 0, click: 0 };
  const days = JSON.parse(p.days), extra = JSON.parse(p.extra || "[]"), today = fiDay();
  const z = (await zones(env, request)).find((x) => x.slug === p.zone);
  return json({ id: p.id, venue: p.venue_name, slug: p.venue, zone: z ? z.name : p.zone, days, extra, status: p.status, promised: p.imps, delivered: tot.imp,
    clicks: tot.click, per, net: p.net_cents, vat: p.vat_cents, test: !p.live, can_cancel: p.status === "paid" && days[0] > today && !extra.length,
    makegood: MAKEGOOD });
}
