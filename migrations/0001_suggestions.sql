CREATE TABLE IF NOT EXISTS suggestions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  venue TEXT NOT NULL,
  url TEXT NOT NULL,
  lang TEXT,
  ip_hash TEXT,
  created TEXT NOT NULL DEFAULT (datetime('now')),
  status TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS suggestions_ip_day ON suggestions (ip_hash, created);
