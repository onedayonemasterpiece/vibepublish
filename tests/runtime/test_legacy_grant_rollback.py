"""Rollback compatibility uses only synthetic private ledgers/provider fixtures."""
import pytest
from social_operations.domain import DomainError, canonical
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.runtime.test_media_store import args, runtime

SCHEMA = '''BEGIN IMMEDIATE;
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
CREATE TABLE IF NOT EXISTS media_service_entry_assets(
 asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
 grant_id TEXT NOT NULL REFERENCES media_service_entry_grants(id) ON DELETE CASCADE
);
PRAGMA user_version=11;
COMMIT;
'''


@pytest.mark.asyncio
async def test_schema11_rollback_preserves_ledger_and_denies_delegated_reads(tmp_path):
    store, owner, asset, provider, app, worker = runtime(tmp_path)
    accepted = await app.call(owner, 'vibepublish_media_store', args(asset, topic='2'))
    await worker.run_once()
    assert provider.effects == 1
    service = store.authenticate(store.create_principal('t', 'archive-service', scopes={'bootstrap', 'status', 'media.store'}))
    store.bind(owner, service.principal_id, 'archive', 'connection', '-1004379835477', rights=('publish',))
    store.set_service_media_topic(owner, service.principal_id, 'archive', '2')
    with store.connection() as db:
        db.executescript(SCHEMA)
    with store.tx() as db:
        binding = store.binding(db, service, alias='archive')
        db.execute('INSERT INTO media_service_entry_grants VALUES(?,?,?,?,?,?,?)',
                   ('entrygrant_old', service.tenant_id, service.principal_id, accepted['resource_id'], binding['id'], '{}', store.clock()))
        row = db.execute('SELECT * FROM assets WHERE id=?', (asset,)).fetchone()
        db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('asset_oldcache', service.tenant_id, service.principal_id, row['sha256'], row['mime'], row['width'], row['height'], row['bytes'], row['source_sha256'], store.clock()))
        db.execute('INSERT INTO media_store_assets VALUES(?,?,?,?)',
                   ('asset_oldcache', accepted['resource_id'], 'download_cache', store.clock()+3600))
        db.execute('INSERT INTO media_service_entry_assets VALUES(?,?)', ('asset_oldcache', 'entrygrant_old'))
        op = app._new_operation(db, service, 'read', {
            'query': {'kind': 'item', 'item_ref': 'item_synthetic'},
            '_media_store_get': True, '_media_store_entry_ref': accepted['resource_id'],
            '_media_store_grant_id': 'entrygrant_old', '_binding_id': binding['id'],
            '_binding_epoch': binding['epoch'], '_native_item': '101', '_namespace': 'published'})
    # This opens a real schema11 ledger with rollback source, without downgrade.
    restarted = Store(store.path)
    rollback = Application(restarted)
    with pytest.raises(DomainError):
        restarted.receipt(service, op)
    with pytest.raises(DomainError):
        rollback.read_asset(service, 'asset_oldcache')
    await Worker(restarted, {'telegram': provider}).run_once()
    assert provider.reads == 0
    with restarted.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 11
        assert db.execute('SELECT COUNT(*) FROM media_service_entry_grants').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM media_service_entry_assets').fetchone()[0] == 1
        assert db.execute('SELECT principal_id FROM publications WHERE id=?', (accepted['resource_id'],)).fetchone()[0] == owner.principal_id
        assert db.execute('SELECT work_state FROM operations WHERE id=?', (op,)).fetchone()[0] == 'done'
    # Ordinary owner data remains readable, without creating provider messages.
    assert rollback.read_asset(owner, asset)[0] == row['bytes']
    assert provider.effects == 1
