// POST /api/e — anonymous usage counters (no cookies, no IP, no user id stored).
// Body: JSON array of [kind, key] pairs, max 20 per request. Only the daily count per (day, kind, key, lang, page, has_list) is kept.
const KINDS = new Set(["view", "click", "quick_exit"]);
const PAGES = new Set(["home", "area", "venue", "topic", "info", "other"]);
export async function onRequestPost({ request, env }) {
  if ((request.headers.get("content-length") | 0) > 2000) return new Response("too big", { status: 413 });
  let b;
  try { b = JSON.parse(await request.text()); } catch { return new Response("bad", { status: 400 }); }
  if (!b || !Array.isArray(b.e)) return new Response("bad", { status: 400 });
  const lang = b.l === "en" ? "en" : "fi";
  const page = PAGES.has(b.p) ? b.p : "other";
  const has = b.h ? 1 : 0;
  const day = new Date(Date.now() + 2 * 3600e3).toISOString().slice(0, 10); // Finnish day (close enough, DST ignored)
  const rows = b.e.slice(0, 20).filter((x) => Array.isArray(x) && KINDS.has(x[0]) && /^[a-z0-9_:-]{0,40}$/.test(String(x[1] || "")));
  if (!rows.length) return new Response(null, { status: 204 });
  const st = env.DB.prepare("INSERT INTO counters (day, kind, key, lang, page, has_list, n) VALUES (?, ?, ?, ?, ?, ?, 1) " +
    "ON CONFLICT(day, kind, key, lang, page, has_list) DO UPDATE SET n = n + 1");
  await env.DB.batch(rows.map((x) => st.bind(day, x[0], String(x[1] || ""), lang, page, has)));
  return new Response(null, { status: 204 });
}
export const onRequest = () => new Response("method not allowed", { status: 405, headers: { allow: "POST" } });
