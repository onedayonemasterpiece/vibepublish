BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS media_service_entry_grants(
 id TEXT PRIMARY KEY,
 tenant_id TEXT NOT NULL,
 principal_id TEXT NOT NULL,
 entry_ref TEXT NOT NULL REFERENCES publications(id),
 binding_id TEXT NOT NULL REFERENCES bindings(id) ON DELETE CASCADE,
 proof TEXT NOT NULL,
 created REAL NOT NULL,
 UNIQUE(tenant_id,principal_id,entry_ref),
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id)
);
CREATE TRIGGER IF NOT EXISTS immutable_media_service_entry_grant
 BEFORE UPDATE ON media_service_entry_grants
 BEGIN SELECT RAISE(ABORT, 'immutable entry grant'); END;
CREATE TABLE IF NOT EXISTS media_service_entry_assets(
 asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
 grant_id TEXT NOT NULL REFERENCES media_service_entry_grants(id) ON DELETE CASCADE
);
PRAGMA user_version=11;
COMMIT;
