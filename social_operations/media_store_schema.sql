BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS media_store_assets(
 asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
 publication_id TEXT REFERENCES publications(id),
 purpose TEXT NOT NULL CHECK(purpose IN ('staging','download_cache')),
 expires REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS media_store_asset_expiry ON media_store_assets(expires);
PRAGMA user_version=6;
COMMIT;
