// POST /api/promo/cancel {t} – before the first day the buyer can cancel himself: full refund through Stripe
import { enabled, stripe, json, fiDay } from "../../../lib/promo.js";
export async function onRequestPost({ request, env }) {
  if (!enabled(env)) return json({ error: "off" }, 503);
  let b; try { b = await request.json(); } catch { return json({ error: "bad" }, 400); }
  const t = String(b.t || "");
  if (!/^[a-f0-9]{32}$/.test(t)) return json({ error: "bad" }, 400);
  const p = await env.DB.prepare("SELECT id, days, extra, status, payment_intent FROM promos WHERE token = ?").bind(t).first();
  if (!p || p.status !== "paid" || !p.payment_intent) return json({ error: "Nostoa ei voi enää perua." }, 409);
  if (JSON.parse(p.days)[0] <= fiDay()) return json({ error: "Nosto on jo alkanut, joten sitä ei voi perua itse." }, 409);
  await stripe(env, "refunds", { payment_intent: p.payment_intent, "metadata[promo]": p.id });
  await env.DB.prepare("UPDATE promos SET status = 'refunded' WHERE id = ?").bind(p.id).run();
  return json({ ok: true });
}
export const onRequest = () => json({ error: "method" }, 405);
