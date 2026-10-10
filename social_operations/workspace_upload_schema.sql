BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS workspace_uploads(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 actor_epoch INTEGER NOT NULL, source_sha256 TEXT NOT NULL, mime TEXT NOT NULL,
 size_bytes INTEGER NOT NULL CHECK(size_bytes>0 AND size_bytes<=20971520),
 received_bytes INTEGER NOT NULL DEFAULT 0 CHECK(received_bytes>=0 AND received_bytes<=size_bytes),
 bytes BLOB NOT NULL DEFAULT X'',
 state TEXT NOT NULL DEFAULT 'receiving' CHECK(state IN ('receiving','completed','aborted','expired')),
 created REAL NOT NULL, expires REAL NOT NULL, resource_id TEXT,
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS workspace_upload_expiry ON workspace_uploads(expires);
CREATE INDEX IF NOT EXISTS workspace_upload_owner ON workspace_uploads(tenant_id,principal_id,state);
PRAGMA user_version=8;
COMMIT;
