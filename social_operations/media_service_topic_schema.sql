BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS media_service_topic_grants(
 tenant_id TEXT NOT NULL,
 principal_id TEXT NOT NULL,
 binding_id TEXT NOT NULL REFERENCES bindings(id) ON DELETE CASCADE,
 topic_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,principal_id,binding_id,topic_id),
 FOREIGN KEY(tenant_id,principal_id) REFERENCES principals(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS media_service_topic_binding
 ON media_service_topic_grants(binding_id,topic_id);
PRAGMA user_version=10;
COMMIT;
