CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  venue TEXT NOT NULL,
  day TEXT NOT NULL,
  ip_hash TEXT NOT NULL,
  created TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (venue, day, ip_hash)
);
