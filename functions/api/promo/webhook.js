// POST /api/promo/webhook – Stripe events (signature checked). Paid → the promo is live at once (Branu: "kone tarkistaa, heti näkyviin").
import { schema, verifyStripe, randomId, json } from "../../../lib/promo.js";
export async function onRequestPost({ request, env }) {
  const raw = await request.text();
  if (!(await verifyStripe(env, raw, request.headers.get("stripe-signature")))) return json({ error: "signature" }, 400);
  const ev = JSON.parse(raw), o = ev.data && ev.data.object;
  await schema(env);
  if (ev.type === "checkout.session.completed" || ev.type === "checkout.session.async_payment_succeeded") {
    const id = o.metadata && o.metadata.promo;
    if (id && o.payment_status === "paid") {
      const buyer = (o.customer_details && (o.customer_details.business_name || o.customer_details.name)) || "";
      await env.DB.prepare("UPDATE promos SET status = 'paid', payment_intent = ?, buyer = ?, token = COALESCE(token, ?), live = ? WHERE id = ? AND status IN ('pending','failed','expired')")
        .bind(o.payment_intent || "", buyer.slice(0, 120), randomId(16), o.livemode ? 1 : 0, id).run();
    }
  } else if (ev.type === "checkout.session.expired") {
    const id = o.metadata && o.metadata.promo;
    if (id) await env.DB.prepare("UPDATE promos SET status = 'expired' WHERE id = ? AND status = 'pending'").bind(id).run();
  } else if (ev.type === "charge.refunded") {
    if (o.payment_intent) await env.DB.prepare("UPDATE promos SET status = 'refunded' WHERE payment_intent = ?").bind(o.payment_intent).run();
  }
  return json({ ok: true });
}
export const onRequest = () => json({ error: "method" }, 405);
