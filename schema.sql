-- run on every deploy (idempotent)
CREATE TABLE IF NOT EXISTS counters (
  day TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, lang TEXT NOT NULL,
  page TEXT NOT NULL, has_list INTEGER NOT NULL, n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, kind, key, lang, page, has_list)
);
CREATE TABLE IF NOT EXISTS likes (
  venue TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, ip_hash TEXT NOT NULL,
  PRIMARY KEY (venue, day, kind, ip_hash)
);
-- Nosto (self-serve promoted placements, 27.11.2026); same definitions as lib/promo.js schema()
CREATE TABLE IF NOT EXISTS promos (id TEXT PRIMARY KEY, venue TEXT NOT NULL, venue_name TEXT, zone TEXT NOT NULL,
  days TEXT NOT NULL, extra TEXT NOT NULL DEFAULT '[]', net_cents INTEGER NOT NULL, vat_cents INTEGER NOT NULL, imps INTEGER NOT NULL,
  status TEXT NOT NULL, created TEXT NOT NULL, session TEXT, payment_intent TEXT, token TEXT, buyer TEXT, live INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS promo_settings (k TEXT PRIMARY KEY, v TEXT);
