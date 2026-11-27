// GET /api/promo/status?s=<checkout session id> – thank-you page: is it paid, link to the report
import { json } from "../../../lib/promo.js";
export async function onRequestGet({ request, env }) {
  const s = new URL(request.url).searchParams.get("s") || "";
  if (!/^cs_[A-Za-z0-9_]{10,200}$/.test(s)) return json({ error: "bad" }, 400);
  const p = await env.DB.prepare("SELECT id, venue_name, zone, days, status, token FROM promos WHERE session = ?").bind(s).first();
  if (!p) return json({ status: "unknown" });
  return json({ status: p.status, venue: p.venue_name, zone: p.zone, days: JSON.parse(p.days), token: p.status === "paid" ? p.token : null });
}
