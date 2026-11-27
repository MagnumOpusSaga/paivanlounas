// POST /api/promo/checkout {venue, zone, days[]} → Stripe Checkout URL. Price and availability are recomputed here, never taken from the browser.
import { schema, quote, enabled, stripe, randomId, json, MIN_ORDER_EUR, MAX_DAYS, VAT } from "../../../lib/promo.js";

async function venueName(env, request, slug) {
  const r = await env.ASSETS.fetch(new URL("/data/week.json", request.url));
  if (!r.ok) return null;
  const v = (await r.json()).venues.find((x) => x.i === slug);
  return v ? v.n : null;
}
async function taxRate(env) {
  const key = "taxrate_" + (String(env.STRIPE_SECRET_KEY).includes("_test_") ? "test" : "live");
  const row = await env.DB.prepare("SELECT v FROM promo_settings WHERE k = ?").bind(key).first();
  if (row) return row.v;
  const t = await stripe(env, "tax_rates", { display_name: "ALV", description: "Arvonlisävero 25,5 %", jurisdiction: "FI", country: "FI",
    percentage: (VAT * 100).toFixed(1), inclusive: "false" });
  await env.DB.prepare("INSERT OR REPLACE INTO promo_settings (k, v) VALUES (?, ?)").bind(key, t.id).run();
  return t.id;
}
const fmtDay = (d) => { const [y, m, dd] = d.split("-"); return `${+dd}.${+m}.`; };

export async function onRequestPost({ request, env }) {
  if (!enabled(env)) return json({ error: "Maksut eivät ole vielä käytössä." }, 503);
  let b; try { b = await request.json(); } catch { return json({ error: "bad" }, 400); }
  const zone = String(b.zone || ""), slug = String(b.venue || ""), want = [...new Set((b.days || []).map(String))].sort();
  if (!/^[a-z0-9-]{2,40}$/.test(zone) || !/^[a-z0-9-]{2,90}$/.test(slug) || !want.length || want.length > MAX_DAYS) return json({ error: "Tarkista valinnat." }, 400);
  await schema(env);
  const name = await venueName(env, request, slug);
  if (!name) return json({ error: "Ravintolaa ei löydy Päivän lounaasta." }, 400);   // only places that have a page with us (machine check)
  const q = await quote(env, request, zone, 20);
  if (!q) return json({ error: "Aluetta ei löydy." }, 400);
  const byDay = Object.fromEntries(q.days.map((d) => [d.day, d]));
  for (const d of want) if (!byDay[d] || byDay[d].free <= 0) return json({ error: `Päivä ${fmtDay(d)} ei ole vapaana.` }, 409);
  const net = want.reduce((s, d) => s + byDay[d].cents, 0), imps = want.reduce((s, d) => s + byDay[d].imps, 0);
  if (net < MIN_ORDER_EUR * 100) return json({ error: `Pienin tilaus on ${MIN_ORDER_EUR} € (alv 0 %). Valitse lisää päiviä.` }, 400);
  const vat = Math.round(net * VAT), id = randomId(8), origin = new URL(request.url).origin;
  await env.DB.prepare("INSERT INTO promos (id, venue, venue_name, zone, days, net_cents, vat_cents, imps, status, created) VALUES (?,?,?,?,?,?,?,?, 'pending', ?)")
    .bind(id, slug, name, zone, JSON.stringify(want), net, vat, imps, new Date().toISOString()).run();
  try {
    const s = await stripe(env, "checkout/sessions", {
      mode: "payment", locale: "fi", customer_creation: "always", billing_address_collection: "required",
      "tax_id_collection[enabled]": "true", "invoice_creation[enabled]": "true",
      "invoice_creation[invoice_data][description]": `Nosto Päivän lounaassa: ${name}, ${q.zone.name}`,
      "invoice_creation[invoice_data][footer]": "BR Entertainment · paivanlounas.fi · Mainos merkitään aina sanalla \"Mainos\".",
      "line_items[0][quantity]": 1, "line_items[0][tax_rates][0]": await taxRate(env),
      "line_items[0][price_data][currency]": "eur", "line_items[0][price_data][unit_amount]": net,
      "line_items[0][price_data][product_data][name]": `Nosto: ${name} – ${q.zone.name}`,
      "line_items[0][price_data][product_data][description]": `${want.length} arkipäivää (${want.map(fmtDay).join(", ")}). Arvio ${imps} näyttöä; jos toteutuu alle 80 %, nosto jatkuu seuraavina arkipäivinä.`,
      "metadata[promo]": id, "payment_intent_data[metadata][promo]": id,
      "payment_intent_data[description]": `Nosto ${id}: ${name} – ${q.zone.name}`,
      "payment_intent_data[statement_descriptor_suffix]": "NOSTO",
      expires_at: Math.floor(Date.now() / 1000) + 31 * 60,
      success_url: `${origin}/mainosta/kiitos/?s={CHECKOUT_SESSION_ID}`,
      cancel_url: `${origin}/mainosta/?v=${encodeURIComponent(slug)}&z=${zone}`,
    });
    await env.DB.prepare("UPDATE promos SET session = ? WHERE id = ?").bind(s.id, id).run();
    return json({ url: s.url });
  } catch (e) {
    await env.DB.prepare("UPDATE promos SET status = 'failed' WHERE id = ?").bind(id).run();
    return json({ error: "Maksun avaus epäonnistui. Yritä hetken päästä uudelleen." }, 502);
  }
}
export const onRequest = () => json({ error: "method" }, 405);
