// GET /api/promo/active – today's paid promos (shown with the word "Mainos"). Also runs the make-good: a promo whose days are over
// with under 80 % of the promised impressions continues on the next weekdays (max 10 extra days, only where a slot is free).
import { schema, adStats, booked, json, fiDay, SLOTS, MAKEGOOD } from "../../../lib/promo.js";
export async function onRequestGet({ env }) {
  const today = fiDay(), wd = new Date(today + "T12:00:00Z").getUTCDay();
  await schema(env);
  const r = await env.DB.prepare("SELECT id, venue, zone, days, extra, imps FROM promos WHERE status = 'paid'").all();
  const rows = r.results || [], out = [];
  const st = await adStats(env, rows.map((p) => p.id));
  for (const p of rows) {
    const days = JSON.parse(p.days), extra = JSON.parse(p.extra || "[]");
    if (days.includes(today) || extra.includes(today)) { out.push({ id: p.id, v: p.venue, z: p.zone }); continue; }
    const last = [...days, ...extra].sort().pop();
    const got = (st[p.id] || {}).imp || 0;
    if (wd > 0 && wd < 6 && last < today && got < MAKEGOOD * p.imps && extra.length < 10) {
      const cnt = await booked(env, p.zone, today);
      if ((cnt[today] || 0) < SLOTS) {
        await env.DB.prepare("UPDATE promos SET extra = ? WHERE id = ?").bind(JSON.stringify([...extra, today]), p.id).run();
        out.push({ id: p.id, v: p.venue, z: p.zone });
      }
    }
  }
  return json({ day: today, promos: out }, 200, { "cache-control": "public, max-age=60" });
}
