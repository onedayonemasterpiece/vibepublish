BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS telegram_media_admissions(
 id TEXT PRIMARY KEY,
 connection_id TEXT NOT NULL REFERENCES connections(id),
 attempt_id TEXT NOT NULL REFERENCES attempts(id),
 media_count INTEGER NOT NULL CHECK(media_count BETWEEN 1 AND 20),
 admitted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS telegram_media_admission_window
 ON telegram_media_admissions(connection_id,admitted_at);
CREATE INDEX IF NOT EXISTS telegram_media_admission_attempt
 ON telegram_media_admissions(attempt_id);
PRAGMA user_version=7;
COMMIT;
