// POST /api/report — "Väärä tieto?": a visitor says the menu shown for a venue and day is wrong.
// One report per visitor per venue and day. The daily run hides a day's menu after enough reports.
export async function onRequestPost({ request, env }) {
  let f;
  try { f = await request.formData(); } catch { return new Response("bad request", { status: 400 }); }
  const venue = String(f.get("venue") || "");
  const day = String(f.get("day") || "");
  if (!/^[a-z0-9-]{1,120}$/.test(venue) || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return new Response("bad input", { status: 400 });
  const ip = request.headers.get("cf-connecting-ip") || "";
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ip + "|" + day + "|paivanlounas-report"));
  const ipHash = [...new Uint8Array(h)].slice(0, 12).map((b) => b.toString(16).padStart(2, "0")).join("");
  const n = await env.DB.prepare("SELECT count(*) AS n FROM reports WHERE ip_hash = ? AND day = ?").bind(ipHash, day).first("n");
  if (n >= 20) return new Response("too many", { status: 429 });
  await env.DB.prepare("INSERT OR IGNORE INTO reports (venue, day, ip_hash) VALUES (?, ?, ?)").bind(venue, day, ipHash).run();
  return new Response("ok", { status: 200 });
}

export const onRequest = () => new Response("method not allowed", { status: 405, headers: { allow: "POST" } });
