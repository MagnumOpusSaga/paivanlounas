-- run on every deploy (idempotent)
CREATE TABLE IF NOT EXISTS counters (
  day TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, lang TEXT NOT NULL,
  page TEXT NOT NULL, has_list INTEGER NOT NULL, n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, kind, key, lang, page, has_list)
);
