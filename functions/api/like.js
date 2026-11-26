// POST /api/like — "Söin täällä – hyvä lounas" (kind=like) or a new favourite star (kind=fav). Anonymous:
// one per visitor per restaurant per day (salted hash of the address, never stored raw), max 30 a day per visitor.
export async function onRequestPost({ request, env }) {
  let b;
  try { b = await request.json(); } catch { return new Response("bad", { status: 400 }); }
  const venue = String((b && b.v) || ""), kind = b && b.k === "fav" ? "fav" : "like";
  if (!/^[a-z0-9-]{1,120}$/.test(venue)) return new Response("bad", { status: 400 });
  const day = new Date(Date.now() + 2 * 3600e3).toISOString().slice(0, 10);
  const ip = request.headers.get("cf-connecting-ip") || "";
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ip + "|" + day + "|paivanlounas-like"));
  const ipHash = [...new Uint8Array(h)].slice(0, 12).map((x) => x.toString(16).padStart(2, "0")).join("");
  const n = await env.DB.prepare("SELECT count(*) AS n FROM likes WHERE ip_hash = ? AND day = ?").bind(ipHash, day).first("n");
  if (n >= 30) return new Response(null, { status: 204 });
  await env.DB.prepare("INSERT OR IGNORE INTO likes (venue, day, kind, ip_hash) VALUES (?, ?, ?, ?)").bind(venue, day, kind, ipHash).run();
  return new Response(null, { status: 204 });
}
export const onRequest = () => new Response("method not allowed", { status: 405, headers: { allow: "POST" } });
