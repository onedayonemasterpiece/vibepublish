BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS visual_jobs(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 actor_epoch INTEGER NOT NULL, routing_revision INTEGER NOT NULL,
 operation_id TEXT NOT NULL UNIQUE, parent_publication TEXT, parent_revision INTEGER,
 spec TEXT NOT NULL, sources TEXT NOT NULL, plans TEXT NOT NULL, input_digest TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL DEFAULT 'accepted',
 dispatched INTEGER NOT NULL DEFAULT 0, execution_ref TEXT, observation TEXT NOT NULL DEFAULT '{}',
 selected_candidate TEXT, selection_digest TEXT, created REAL NOT NULL, deadline REAL NOT NULL,
 consent TEXT NOT NULL DEFAULT '{"shared_training":false,"version":1}',
 FOREIGN KEY(tenant_id,principal_id,operation_id) REFERENCES operations(tenant_id,principal_id,id),
 FOREIGN KEY(tenant_id,principal_id,parent_publication) REFERENCES publications(tenant_id,principal_id,id));
CREATE TRIGGER IF NOT EXISTS visual_job_frozen BEFORE UPDATE OF tenant_id,principal_id,actor_epoch,
 routing_revision,operation_id,parent_publication,parent_revision,spec,sources,plans,input_digest,created,deadline,consent ON visual_jobs
 BEGIN SELECT RAISE(ABORT,'immutable visual input'); END;
CREATE TRIGGER IF NOT EXISTS visual_choice_frozen BEFORE UPDATE OF selected_candidate,selection_digest ON visual_jobs
 WHEN old.selected_candidate IS NOT NULL
 BEGIN SELECT RAISE(ABORT,'immutable visual choice'); END;
CREATE TABLE IF NOT EXISTS visual_candidates(
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES visual_jobs(id), ordinal INTEGER NOT NULL,
 asset_ref TEXT NOT NULL REFERENCES assets(id), sha256 TEXT NOT NULL,
 art_ref TEXT NOT NULL REFERENCES assets(id), art_sha256 TEXT NOT NULL,
 width INTEGER NOT NULL, height INTEGER NOT NULL, format TEXT NOT NULL,
 recipe TEXT NOT NULL, provenance TEXT NOT NULL, selection_token_hash TEXT NOT NULL,
 fixture INTEGER NOT NULL, requires_review INTEGER NOT NULL DEFAULT 1,
 UNIQUE(job_id,ordinal));
CREATE TRIGGER IF NOT EXISTS visual_candidate_frozen BEFORE UPDATE ON visual_candidates
 BEGIN SELECT RAISE(ABORT,'immutable visual candidate'); END;
CREATE TABLE IF NOT EXISTS visual_asset_origins(
 asset_id TEXT PRIMARY KEY REFERENCES assets(id), job_id TEXT NOT NULL REFERENCES visual_jobs(id),
 fixture INTEGER NOT NULL, kind TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS visual_asset_origin_frozen BEFORE UPDATE ON visual_asset_origins
 BEGIN SELECT RAISE(ABORT,'immutable visual asset origin'); END;
CREATE TABLE IF NOT EXISTS visual_feedback(
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES visual_jobs(id),
 candidate_id TEXT NOT NULL REFERENCES visual_candidates(id), rating TEXT NOT NULL,
 reason TEXT NOT NULL, created REAL NOT NULL, shared_training INTEGER NOT NULL DEFAULT 0);
CREATE TRIGGER IF NOT EXISTS visual_feedback_frozen BEFORE UPDATE ON visual_feedback
 BEGIN SELECT RAISE(ABORT,'immutable visual feedback'); END;
CREATE TRIGGER IF NOT EXISTS asset_bytes_immutable BEFORE UPDATE ON assets
 BEGIN SELECT RAISE(ABORT,'immutable asset'); END;
PRAGMA user_version=2;
COMMIT;
