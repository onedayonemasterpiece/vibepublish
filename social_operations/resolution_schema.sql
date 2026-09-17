BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS attempt_resolutions (
 attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
 operation_id TEXT NOT NULL UNIQUE REFERENCES operations(id),
 checkpoint_digest TEXT NOT NULL,
 proof TEXT NOT NULL,
 created REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS immutable_attempt_resolution_update
BEFORE UPDATE ON attempt_resolutions BEGIN
 SELECT RAISE(ABORT, 'immutable attempt resolution');
END;
CREATE TRIGGER IF NOT EXISTS immutable_attempt_resolution_delete
BEFORE DELETE ON attempt_resolutions BEGIN
 SELECT RAISE(ABORT, 'immutable attempt resolution');
END;
PRAGMA user_version=4;
COMMIT;
