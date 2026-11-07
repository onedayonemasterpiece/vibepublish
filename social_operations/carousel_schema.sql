BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS carousel_versions(
 id TEXT NOT NULL, revision INTEGER NOT NULL,
 tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 operation_id TEXT NOT NULL UNIQUE, brief TEXT NOT NULL, svg TEXT NOT NULL,
 card_count INTEGER NOT NULL, card_width INTEGER NOT NULL, card_height INTEGER NOT NULL,
 caption TEXT NOT NULL, asset_refs TEXT NOT NULL, created REAL NOT NULL,
 PRIMARY KEY(id,revision),
 FOREIGN KEY(tenant_id,principal_id,operation_id) REFERENCES operations(tenant_id,principal_id,id));
CREATE TRIGGER IF NOT EXISTS carousel_version_immutable BEFORE UPDATE ON carousel_versions
 BEGIN SELECT RAISE(ABORT,'immutable carousel version'); END;
CREATE TRIGGER IF NOT EXISTS carousel_version_retained BEFORE DELETE ON carousel_versions
 BEGIN SELECT RAISE(ABORT,'immutable carousel version'); END;
PRAGMA user_version=12;
COMMIT;
