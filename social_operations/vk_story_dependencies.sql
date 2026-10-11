BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS vk_story_dependencies(
 id TEXT PRIMARY KEY,
 parent_attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id),
 parent_publication_id TEXT NOT NULL REFERENCES publications(id),
 parent_revision INTEGER NOT NULL,
 binding_id TEXT NOT NULL REFERENCES bindings(id),
 binding_epoch INTEGER NOT NULL,
 connection_id TEXT NOT NULL REFERENCES connections(id),
 native_target TEXT NOT NULL,
 story_plan TEXT NOT NULL,
 story_plan_digest TEXT NOT NULL,
 link_text TEXT NOT NULL CHECK(link_text IN ('read','more')),
 state TEXT NOT NULL DEFAULT 'waiting' CHECK(state IN ('waiting','queued','verified','blocked','cancelled','expired','outcome_unknown')),
 child_operation_id TEXT UNIQUE REFERENCES operations(id),
 parent_native_id TEXT,
 next_check REAL NOT NULL,
 expires REAL NOT NULL,
 created REAL NOT NULL,
 updated REAL NOT NULL,
 reason TEXT,
 event_status TEXT NOT NULL DEFAULT 'not_checked',
 CHECK(expires>created)
);
CREATE INDEX IF NOT EXISTS vk_story_waiting ON vk_story_dependencies(state,next_check);
CREATE TRIGGER IF NOT EXISTS immutable_vk_story_dependency
 BEFORE UPDATE OF parent_attempt_id,parent_publication_id,parent_revision,binding_id,binding_epoch,connection_id,native_target,story_plan,story_plan_digest,link_text ON vk_story_dependencies
 BEGIN SELECT RAISE(ABORT,'immutable story dependency'); END;
CREATE TABLE IF NOT EXISTS vk_story_events(
 connection_id TEXT NOT NULL REFERENCES connections(id),
 native_target TEXT NOT NULL,
 event_key TEXT NOT NULL,
 event_type TEXT NOT NULL,
 native_id TEXT NOT NULL,
 source_native_id TEXT,
 received REAL NOT NULL,
 PRIMARY KEY(connection_id,native_target,event_key)
);
CREATE TABLE IF NOT EXISTS vk_story_event_cursors(
 connection_id TEXT NOT NULL REFERENCES connections(id),
 native_target TEXT NOT NULL,
 cursor TEXT NOT NULL,
 updated REAL NOT NULL,
 PRIMARY KEY(connection_id,native_target)
);
PRAGMA user_version=9;
COMMIT;
