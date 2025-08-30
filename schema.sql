CREATE TABLE IF NOT EXISTS config(
  id INTEGER PRIMARY KEY CHECK (id=1),
  center_lat REAL, center_lng REAL, zoom INTEGER, updated_at TEXT
);
INSERT OR IGNORE INTO config(id, center_lat, center_lng, zoom, updated_at)
VALUES(1, 19.4326, -99.1332, 13, datetime('now'));

CREATE TABLE IF NOT EXISTS pins(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT, lat REAL, lng REAL, meta TEXT, created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS visits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_hash TEXT, name TEXT, age INTEGER, date TEXT, device_hint TEXT
);
