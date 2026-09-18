BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS emoji_catalogs (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL,
 binding_id TEXT NOT NULL REFERENCES bindings(id), binding_epoch INTEGER NOT NULL,
 actor_epoch INTEGER NOT NULL, short_name TEXT NOT NULL, revision INTEGER NOT NULL,
 snapshot TEXT NOT NULL, observed REAL NOT NULL,
 UNIQUE(tenant_id,principal_id,binding_id,short_name,revision));
CREATE TABLE IF NOT EXISTS emoji_aliases (
 tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, alias TEXT NOT NULL,
 revision INTEGER NOT NULL, snapshot TEXT NOT NULL,
 PRIMARY KEY(tenant_id,principal_id,alias,revision));
CREATE TABLE IF NOT EXISTS emoji_rules (
 tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, name TEXT NOT NULL,
 revision INTEGER NOT NULL, snapshot TEXT NOT NULL,
 PRIMARY KEY(tenant_id,principal_id,name,revision));
CREATE TABLE IF NOT EXISTS emoji_choices (
 token_hash TEXT PRIMARY KEY, catalog_id TEXT NOT NULL REFERENCES emoji_catalogs(id),
 tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, actor_epoch INTEGER NOT NULL,
 expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS emoji_asset_origins (
 asset_id TEXT PRIMARY KEY REFERENCES assets(id), catalog_id TEXT NOT NULL REFERENCES emoji_catalogs(id));
CREATE TRIGGER IF NOT EXISTS emoji_alias_immutable_update BEFORE UPDATE ON emoji_aliases
 BEGIN SELECT RAISE(ABORT,'immutable emoji alias revision'); END;
CREATE TRIGGER IF NOT EXISTS emoji_alias_immutable_delete BEFORE DELETE ON emoji_aliases
 BEGIN SELECT RAISE(ABORT,'immutable emoji alias revision'); END;
CREATE TRIGGER IF NOT EXISTS emoji_rule_immutable_update BEFORE UPDATE ON emoji_rules
 BEGIN SELECT RAISE(ABORT,'immutable emoji rule revision'); END;
CREATE TRIGGER IF NOT EXISTS emoji_rule_immutable_delete BEFORE DELETE ON emoji_rules
 BEGIN SELECT RAISE(ABORT,'immutable emoji rule revision'); END;
CREATE TRIGGER IF NOT EXISTS emoji_catalog_immutable_update BEFORE UPDATE ON emoji_catalogs WHEN OLD.snapshot!='{}'
 BEGIN SELECT RAISE(ABORT,'immutable emoji catalog revision'); END;
CREATE TRIGGER IF NOT EXISTS emoji_catalog_immutable_delete BEFORE DELETE ON emoji_catalogs
 BEGIN SELECT RAISE(ABORT,'immutable emoji catalog revision'); END;
CREATE TRIGGER IF NOT EXISTS emoji_origin_immutable_update BEFORE UPDATE ON emoji_asset_origins
 BEGIN SELECT RAISE(ABORT,'immutable emoji asset origin'); END;
CREATE TRIGGER IF NOT EXISTS emoji_origin_immutable_delete BEFORE DELETE ON emoji_asset_origins
 BEGIN SELECT RAISE(ABORT,'immutable emoji asset origin'); END;
PRAGMA user_version=3;
COMMIT;
