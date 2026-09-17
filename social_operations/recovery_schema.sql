BEGIN IMMEDIATE;
-- An additive observation/resolution journal; never a new social dispatch.
CREATE TABLE IF NOT EXISTS attempt_recovery(
 attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
 plan_digest TEXT NOT NULL,
 original_checkpoint TEXT NOT NULL,
 hint TEXT NOT NULL DEFAULT '{}',
 observation TEXT,
 finalize_state TEXT NOT NULL DEFAULT 'unresolved'
   CHECK(finalize_state IN ('unresolved','pending','done')),
 created REAL NOT NULL, resolved REAL, finalized REAL);
CREATE TRIGGER IF NOT EXISTS immutable_recovery_origin
 BEFORE UPDATE OF attempt_id,plan_digest,original_checkpoint ON attempt_recovery
 BEGIN SELECT RAISE(ABORT,'immutable recovery origin'); END;
PRAGMA user_version=5;
COMMIT;
