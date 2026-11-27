// Shared logic for "Nosto" – restaurants' self-serve promoted placements (Branu 27.11.2026, plan: claude/lounas-mainosmyynti.md).
// Price comes from real counted views: price/day = max(MIN, forecast impressions × CPM / 1000) × demand.
// Nothing here trusts the browser: price, availability and the restaurant are always recomputed on the server.

export const CPM_EUR = 10;          // per 1 000 impressions (benchmarks: JCDecaux Helsinki digital 8,50–9,32 €, Meta Finland ~7–11 $)
export const MIN_DAY_EUR = 1;       // floor per day (Stripe fee 1,5 % + 0,25 €)
export const MIN_ORDER_EUR = 3;     // smallest purchase
export const SLOTS = 2;             // promos per area per day
export const VAT = 0.255;           // Finnish general VAT rate since 1.9.2024
export const VISIBLE = 0.7;         // share of area views where the promo card is really on screen (replaced by measured rate)
export const MAKEGOOD = 0.8;        // under 80 % of promised impressions → the promo runs on extra weekdays
export const MAX_DAYS = 20;

export function fiDay(d = new Date()) {            // Finnish calendar day (UTC+2, DST ignored like the counters)
  return new Date(d.getTime() + 2 * 3600e3).toISOString().slice(0, 10);
}
export function weekdaysFrom(day, n) {             // next n weekdays starting at day (inclusive)
  const out = []; let t = new Date(day + "T12:00:00Z");
  while (out.length < n) { const w = t.getUTCDay(); if (w > 0 && w < 6) out.push(t.toISOString().slice(0, 10)); t = new Date(t.getTime() + 864e5); }
  return out;
}
export function median(a) { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }

export async function zones(env, request) {
  const r = await env.ASSETS.fetch(new URL("/data/zones.json", request.url));
  return r.ok ? r.json() : [];
}

export async function schema(env) {
  await env.DB.batch([
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS promos (id TEXT PRIMARY KEY, venue TEXT NOT NULL, venue_name TEXT, zone TEXT NOT NULL,
      days TEXT NOT NULL, extra TEXT NOT NULL DEFAULT '[]', net_cents INTEGER NOT NULL, vat_cents INTEGER NOT NULL, imps INTEGER NOT NULL,
      status TEXT NOT NULL, created TEXT NOT NULL, session TEXT, payment_intent TEXT, token TEXT, buyer TEXT, live INTEGER NOT NULL DEFAULT 0)`),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS promo_settings (k TEXT PRIMARY KEY, v TEXT)"),
  ]);
}

// views per zone per day from the anonymous counters (kind 'zone' = the map was used in that area)
export async function zoneViews(env, days = 35) {
  const since = fiDay(new Date(Date.now() - days * 864e5));
  const r = await env.DB.prepare("SELECT day, key, SUM(n) n FROM counters WHERE kind = 'zone' AND day >= ? GROUP BY day, key").bind(since).all();
  const out = {};
  for (const x of r.results || []) (out[x.key] ||= {})[x.day] = x.n;
  return out;
}
export async function adStats(env, ids) {
  if (!ids.length) return {};
  const q = "SELECT kind, key, SUM(n) n FROM counters WHERE kind IN ('adimp','adclick') AND key IN (" + ids.map(() => "?").join(",") + ") GROUP BY kind, key";
  const r = await env.DB.prepare(q).bind(...ids).all();
  const out = {};
  for (const x of r.results || []) (out[x.key] ||= { imp: 0, click: 0 })[x.kind === "adimp" ? "imp" : "click"] = x.n;
  return out;
}

// forecast of views for one zone on one weekday: median of the same weekday over the last 4 weeks;
// without history, the site's daily views split by the zone's share of lunch lists
export function forecastViews(zv, zone, day, fallback) {
  const wd = new Date(day + "T12:00:00Z").getUTCDay();
  const same = Object.entries(zv[zone] || {}).filter(([d]) => new Date(d + "T12:00:00Z").getUTCDay() === wd).map(([, n]) => n);
  if (same.length >= 2) return Math.round(median(same.slice(-4)));
  return Math.max(0, Math.round(fallback));
}

export async function booked(env, zone, from) {
  const r = await env.DB.prepare("SELECT id, days, extra, status, created FROM promos WHERE zone = ? AND status IN ('paid','pending')").bind(zone).all();
  const cnt = {}, cutoff = Date.now() - 30 * 60e3;
  for (const p of r.results || []) {
    if (p.status === "pending" && Date.parse(p.created) < cutoff) continue;   // abandoned checkout frees the slot after 30 min
    for (const d of [...JSON.parse(p.days), ...JSON.parse(p.extra || "[]")]) if (d >= from) cnt[d] = (cnt[d] || 0) + 1;
  }
  return cnt;
}

// full quote for a zone: per-day price (cents, VAT 0), impressions, availability
export async function quote(env, request, zone, ndays = 15) {
  const zs = await zones(env, request);
  const z = zs.find((x) => x.slug === zone);
  if (!z) return null;
  // today only before 11 o'clock Finnish time (a Nosto bought after lunch starts on the next weekday)
  const today = fiDay(), fiHour = new Date(Date.now() + 2 * 3600e3).getUTCHours();
  const days = weekdaysFrom(fiHour < 11 ? today : fiDay(new Date(Date.now() + 864e5)), ndays);
  const zv = await zoneViews(env);
  const total = await env.DB.prepare("SELECT COUNT(DISTINCT day) d, SUM(n) n FROM counters WHERE kind = 'view' AND day >= ?").bind(fiDay(new Date(Date.now() - 14 * 864e5))).first();
  const perDay = total && total.d ? total.n / total.d : 0;
  const fallback = perDay * (z.share || 0.03);
  const cnt = await booked(env, zone, today);
  const soldRatio = days.reduce((s, d) => s + Math.min(SLOTS, cnt[d] || 0), 0) / (days.length * SLOTS);
  const demand = 1 + 0.5 * soldRatio;
  const out = days.map((d) => {
    const views = forecastViews(zv, zone, d, fallback);
    const imps = Math.round(views * VISIBLE);
    const cents = Math.round(Math.max(MIN_DAY_EUR, (imps * CPM_EUR) / 1000) * demand * 100);
    return { day: d, views, imps, cents, free: SLOTS - (cnt[d] || 0) };
  });
  return { zone: z, days: out, demand: Math.round(demand * 100) / 100, cpm: CPM_EUR, min_day: MIN_DAY_EUR, min_order: MIN_ORDER_EUR, vat: VAT, slots: SLOTS };
}

export function randomId(n = 16) {
  const a = new Uint8Array(n); crypto.getRandomValues(a);
  return [...a].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Stripe REST API (no SDK on Workers): form-encoded body, secret key only from the environment
export async function stripe(env, path, params, method = "POST") {
  const body = new URLSearchParams();
  const add = (k, v) => {
    if (v === undefined || v === null) return;
    if (typeof v === "object") for (const [kk, vv] of Object.entries(v)) add(`${k}[${kk}]`, vv);
    else body.append(k, String(v));
  };
  for (const [k, v] of Object.entries(params || {})) add(k, v);
  const r = await fetch("https://api.stripe.com/v1/" + path + (method === "GET" && params ? "?" + body : ""), {
    method, headers: { authorization: "Bearer " + env.STRIPE_SECRET_KEY, "content-type": "application/x-www-form-urlencoded" },
    body: method === "GET" ? undefined : body,
  });
  const j = await r.json();
  if (!r.ok) throw new Error((j.error && j.error.message) || "stripe " + r.status);
  return j;
}

// Stripe-Signature: t=…,v1=… ; HMAC-SHA256 of "t.payload" with the endpoint secret; 5 min tolerance
export async function verifyStripe(env, payload, header) {
  if (!env.STRIPE_WEBHOOK_SECRET || !header) return false;
  const parts = Object.fromEntries(header.split(",").map((x) => x.split("=")).map(([k, ...v]) => [k, v.join("=")]));
  const t = parts.t, sigs = header.split(",").filter((x) => x.startsWith("v1=")).map((x) => x.slice(3));
  if (!t || !sigs.length || Math.abs(Date.now() / 1000 - Number(t)) > 300) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.STRIPE_WEBHOOK_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(t + "." + payload));
  const hex = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return sigs.some((s) => s.length === hex.length && s.split("").reduce((acc, c, i) => acc | (c.charCodeAt(0) ^ hex.charCodeAt(i)), 0) === 0);
}

export const json = (o, status = 200, extra = {}) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra } });
export const enabled = (env) => !!(env.STRIPE_SECRET_KEY && env.STRIPE_WEBHOOK_SECRET);
export const testMode = (env) => String(env.STRIPE_SECRET_KEY || "").startsWith("sk_test_") || String(env.STRIPE_SECRET_KEY || "").startsWith("rk_test_");
