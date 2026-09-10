BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO settings VALUES('restore_guard','0');
CREATE TABLE IF NOT EXISTS tenants(
 id TEXT PRIMARY KEY, timezone TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 command_limit INTEGER NOT NULL DEFAULT 100, storage_limit INTEGER NOT NULL DEFAULT 67108864);
CREATE TABLE IF NOT EXISTS principals(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
 token_hash TEXT NOT NULL UNIQUE, scopes TEXT NOT NULL, owner INTEGER NOT NULL DEFAULT 0,
 epoch INTEGER NOT NULL DEFAULT 1, routing_revision INTEGER NOT NULL DEFAULT 1,
 active INTEGER NOT NULL DEFAULT 1, UNIQUE(tenant_id,id));
CREATE TABLE IF NOT EXISTS connections(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
 provider TEXT NOT NULL CHECK(provider IN ('telegram','vk','max')),
 account_type TEXT NOT NULL, secret_ref TEXT NOT NULL, shared INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS destinations(
 id TEXT PRIMARY KEY, connection_id TEXT NOT NULL REFERENCES connections(id),
 native_id TEXT NOT NULL, handle TEXT NOT NULL DEFAULT '', label TEXT NOT NULL,
 UNIQUE(connection_id,native_id));
CREATE TABLE IF NOT EXISTS bindings(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 alias TEXT NOT NULL, destination_id TEXT NOT NULL REFERENCES destinations(id),
 rights TEXT NOT NULL, epoch INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1,
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id),
 UNIQUE(tenant_id,principal_id,alias), UNIQUE(principal_id,destination_id));
CREATE TABLE IF NOT EXISTS destination_sets(
 tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, alias TEXT NOT NULL,
 label TEXT NOT NULL, revision INTEGER NOT NULL, members TEXT NOT NULL,
 PRIMARY KEY(tenant_id,principal_id,alias),
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id));
CREATE TABLE IF NOT EXISTS profiles(
 tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, alias TEXT NOT NULL,
 revision INTEGER NOT NULL, profile TEXT NOT NULL,
 PRIMARY KEY(tenant_id,principal_id,alias),
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id));
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 sha256 TEXT NOT NULL, mime TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
 bytes BLOB NOT NULL, source_sha256 TEXT NOT NULL, created REAL NOT NULL,
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id));
CREATE TABLE IF NOT EXISTS publications(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 revision INTEGER NOT NULL, kind TEXT NOT NULL, created REAL NOT NULL,
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id),
 UNIQUE(tenant_id,principal_id,id));
CREATE TABLE IF NOT EXISTS revisions(
 tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, publication_id TEXT NOT NULL,
 revision INTEGER NOT NULL, intent TEXT NOT NULL, plan TEXT NOT NULL, plan_digest TEXT NOT NULL,
 PRIMARY KEY(publication_id,revision),
 FOREIGN KEY(tenant_id,principal_id,publication_id) REFERENCES publications(tenant_id,principal_id,id));
CREATE TRIGGER IF NOT EXISTS immutable_revision_update BEFORE UPDATE ON revisions
 BEGIN SELECT RAISE(ABORT,'immutable revision'); END;
CREATE TRIGGER IF NOT EXISTS immutable_revision_delete BEFORE DELETE ON revisions
 BEGIN SELECT RAISE(ABORT,'immutable revision'); END;
CREATE TABLE IF NOT EXISTS operations(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 actor_epoch INTEGER NOT NULL, publication_id TEXT, revision INTEGER NOT NULL DEFAULT 1,
 action TEXT NOT NULL, request_digest TEXT NOT NULL, request TEXT NOT NULL,
 created REAL NOT NULL, deadline REAL NOT NULL,
 state TEXT NOT NULL DEFAULT 'accepted', complete INTEGER NOT NULL DEFAULT 0,
 work_state TEXT NOT NULL DEFAULT 'ready', lease_owner TEXT, fence INTEGER NOT NULL DEFAULT 0,
 lease_until REAL NOT NULL DEFAULT 0, worker_seen REAL,
 result TEXT NOT NULL DEFAULT '{}', error TEXT,
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id),
 FOREIGN KEY(tenant_id,principal_id,publication_id) REFERENCES publications(tenant_id,principal_id,id),
 UNIQUE(tenant_id,principal_id,id));
CREATE INDEX IF NOT EXISTS ready_commands ON operations(work_state,lease_until,created);
CREATE INDEX IF NOT EXISTS recent_intents ON operations(principal_id,request_digest,created);
CREATE TRIGGER IF NOT EXISTS immutable_request BEFORE UPDATE OF request,request_digest ON operations
 BEGIN SELECT RAISE(ABORT,'immutable request'); END;
CREATE TABLE IF NOT EXISTS request_keys(
 tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, key TEXT NOT NULL,
 digest TEXT NOT NULL, operation_id TEXT NOT NULL, created REAL NOT NULL,
 PRIMARY KEY(tenant_id,principal_id,key),
 FOREIGN KEY(tenant_id,principal_id,operation_id) REFERENCES operations(tenant_id,principal_id,id));
CREATE TABLE IF NOT EXISTS attempts(
 id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES operations(id),
 binding_id TEXT NOT NULL REFERENCES bindings(id), binding_epoch INTEGER NOT NULL,
 alias TEXT NOT NULL, provider TEXT NOT NULL, plan TEXT NOT NULL, plan_digest TEXT NOT NULL,
 dispatched INTEGER NOT NULL DEFAULT 0, dispatch_at REAL,
 state TEXT NOT NULL DEFAULT 'accepted', stage TEXT NOT NULL DEFAULT 'accepted',
 observed TEXT NOT NULL DEFAULT 'not_attempted', result TEXT NOT NULL DEFAULT '{}',
 checkpoint TEXT NOT NULL DEFAULT '{}', UNIQUE(operation_id,binding_id));
CREATE TRIGGER IF NOT EXISTS immutable_attempt_plan BEFORE UPDATE OF plan,plan_digest ON attempts
 BEGIN SELECT RAISE(ABORT,'immutable attempt plan'); END;
CREATE TABLE IF NOT EXISTS events(
 operation_id TEXT NOT NULL REFERENCES operations(id), seq INTEGER NOT NULL,
 body TEXT NOT NULL, PRIMARY KEY(operation_id,seq));
CREATE TABLE IF NOT EXISTS cursors(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 epoch INTEGER NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL,
 position TEXT NOT NULL, expires REAL NOT NULL,
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id));
CREATE TABLE IF NOT EXISTS item_refs(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 binding_id TEXT NOT NULL REFERENCES bindings(id), binding_epoch INTEGER NOT NULL,
 native_id TEXT NOT NULL, namespace TEXT NOT NULL, snapshot TEXT NOT NULL,
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id));
CREATE TABLE IF NOT EXISTS facts(
 id TEXT PRIMARY KEY, destination_id TEXT NOT NULL REFERENCES destinations(id),
 native_id TEXT NOT NULL, namespace TEXT NOT NULL, initiator TEXT,
 publication_id TEXT, kind TEXT NOT NULL, snapshot TEXT NOT NULL, text TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 UNIQUE(destination_id,native_id,namespace));
CREATE INDEX IF NOT EXISTS publication_history ON facts(destination_id,initiator,observed_at);
CREATE VIRTUAL TABLE IF NOT EXISTS fact_search USING fts5(fact_id UNINDEXED,text);
CREATE TRIGGER IF NOT EXISTS fact_search_insert AFTER INSERT ON facts BEGIN
 INSERT INTO fact_search(fact_id,text) VALUES(new.id,new.text); END;
CREATE TRIGGER IF NOT EXISTS fact_search_update AFTER UPDATE OF text ON facts BEGIN
 DELETE FROM fact_search WHERE fact_id=old.id;
 INSERT INTO fact_search(fact_id,text) VALUES(new.id,new.text); END;
CREATE TABLE IF NOT EXISTS decisions(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 publication_id TEXT NOT NULL, revision INTEGER NOT NULL, plan_digest TEXT NOT NULL,
 token_hash TEXT NOT NULL, consumed_by TEXT,
 FOREIGN KEY(tenant_id,principal_id,publication_id) REFERENCES publications(tenant_id,principal_id,id));

PRAGMA user_version=1;
COMMIT;
