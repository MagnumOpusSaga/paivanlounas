// GET /api/promo/quote?zone=<slug> – price per weekday for the next 3 weeks, from counted views
import { quote, json } from "../../../lib/promo.js";
export async function onRequestGet({ request, env }) {
  const zone = new URL(request.url).searchParams.get("zone") || "";
  if (!/^[a-z0-9-]{2,40}$/.test(zone)) return json({ error: "zone" }, 400);
  const q = await quote(env, request, zone);
  return q ? json(q) : json({ error: "zone" }, 404);
}
