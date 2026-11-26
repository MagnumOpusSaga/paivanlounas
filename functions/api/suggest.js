// POST /api/suggest — a restaurant tells where its lunch menu is published.
// No email, no account. The daily pipeline checks the URL itself before using it.
const OK = (lang) => new Response(lang === "en" ? "Thank you" : "Kiitos", { status: 200, headers: { "content-type": "text/plain; charset=utf-8" } });

export async function onRequestPost({ request, env }) {
  let f;
  try { f = await request.formData(); } catch { return new Response("bad request", { status: 400 }); }
  const lang = f.get("lang") === "en" ? "en" : "fi";
  if (f.get("website")) return OK(lang); // honeypot
  const venue = String(f.get("venue") || "").slice(0, 120);
  let url = String(f.get("url") || "").trim().slice(0, 500);
  if (!/^[a-z0-9-]{1,120}$/.test(venue)) return new Response("bad venue", { status: 400 });
  try {
    const u = new URL(url);
    if (!/^https?:$/.test(u.protocol) || !u.hostname.includes(".")) throw 0;
    if (/^[\d.]+$|^\[/.test(u.hostname) || u.username || u.password) throw 0; // raw IPs, credentials in URL
    // obvious spam / adult / gambling / shorteners never reach the pipeline (it also waits for a name match or manual approval)
    // other lunch-listing services (their data is never copied) – accepted silently, never used
    if (/(^|\.)(lounaat\.info|lounasaika\.(net|fi)|lounaspaikka\.fi|lounasinfo\.fi|lounas\.info|ruokalistat\.fi|lounastaulu\.fi|mobiililounas\.fi|lounasravintolat\.fi|lounaslistat\.fi)$/i.test(u.hostname)) return OK(lang);
    if (/porn|xxx|sex|escort|adult|onlyfans|casino|kasino|betting|vedonly|poker|slot|viagra|cialis|crypto|bitcoin|loan|laina|bit\.ly|tinyurl|t\.co\b|goo\.gl|is\.gd|cutt\.ly|rebrand\.ly/i.test(u.hostname + u.pathname)) return OK(lang);
    url = u.toString();
  } catch { return new Response("bad url", { status: 400 }); }
  const ip = request.headers.get("cf-connecting-ip") || "";
  const day = new Date().toISOString().slice(0, 10);
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ip + "|" + day + "|paivanlounas"));
  const ipHash = [...new Uint8Array(h)].slice(0, 12).map((b) => b.toString(16).padStart(2, "0")).join("");
  const n = await env.DB.prepare("SELECT count(*) AS n FROM suggestions WHERE ip_hash = ? AND created >= date('now')").bind(ipHash).first("n");
  if (n >= 5) return new Response("too many", { status: 429 });
  await env.DB.prepare("INSERT INTO suggestions (venue, url, lang, ip_hash) VALUES (?, ?, ?, ?)").bind(venue, url, lang, ipHash).run();
  return OK(lang);
}

export const onRequest = () => new Response("method not allowed", { status: 405, headers: { allow: "POST" } });
