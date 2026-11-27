// GET /api/promo/stats – public numbers per area (Branu 27.11.: "luvut julkisesti alueittain"): map views of the last 4 weeks
import { zones, zoneViews, fiDay, json } from "../../../lib/promo.js";
export async function onRequestGet({ request, env }) {
  const zs = await zones(env, request), zv = await zoneViews(env, 28);
  const since = fiDay(new Date(Date.now() - 28 * 864e5));
  const v = await env.DB.prepare("SELECT COUNT(DISTINCT day) d, SUM(n) n FROM counters WHERE kind = 'view' AND day >= ?").bind(since).first();
  const out = zs.map((z) => {
    const days = Object.entries(zv[z.slug] || {});
    const n = days.reduce((s, [, x]) => s + x, 0);
    return { slug: z.slug, name: z.name, city: z.city, lists: z.lists, views28: n, days: days.length };
  });
  return json({ since, site_views28: (v && v.n) || 0, site_days: (v && v.d) || 0, zones: out }, 200, { "cache-control": "public, max-age=300" });
}
