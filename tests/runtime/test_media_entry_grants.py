import hashlib
import pytest


@pytest.mark.asyncio
async def test_entry_uses_exact_unique_granted_binding(tmp_path, monkeypatch):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        store.bind(owner, service.principal_id, 'ungranted-alias', 'connection', '-1004379835477', rights=('publish',))
    original = store.bindings
    monkeypatch.setattr(store, 'bindings', lambda db, actor: list(reversed(original(db, actor))))
    read = await app.call(service, 'vibepublish_media_store', get_args(proof['entry_ref'], 'exact-binding'))
    assert 'operation_id' in read, read
    await worker.run_once()
    done = store.receipt(service, read['operation_id'])
    assert done['state'] == 'verified', done
    assert done['media_store_items'][0]['destination'] == 'archive'
    cache = done['items'][0]['media'][0]['source']['id']
    assert app.read_asset(service, cache)[2] == proof['origin']['sha256']
import json
from dataclasses import replace

from social_operations.domain import DomainError, canonical
from social_operations.media_entry_grants import (
    apply_entry_grants, check_download, entry_proof, require_grant, revoke_entry_grant)
from tests.runtime.test_media_store import args, get_args, runtime


async def setup_grant(tmp_path):
    store, owner, asset, provider, app, worker = runtime(tmp_path)
    with store.connection() as db:
        sha = db.execute('SELECT sha256 FROM assets WHERE id=?', (asset,)).fetchone()[0]
    origin = {'system': 'regional_knowledge', 'ref': 'knowledge://documents/synthetic/source', 'sha256': sha}
    put = await app.call(owner, 'vibepublish_media_store', args(asset, topic='2', origin=origin))
    await worker.run_once()
    service = store.authenticate(store.create_principal('t', 'archive-service', scopes={'bootstrap', 'status', 'media.store'}))
    store.bind(owner, service.principal_id, 'archive', 'connection', '-1004379835477', rights=('publish',))
    store.set_service_media_topic(owner, service.principal_id, 'archive', '2')
    with store.tx() as db:
        binding = store.binding(db, service, alias='archive')
        proof = entry_proof(store, db, service, binding, put['resource_id'])
        grant, = apply_entry_grants(store, db, owner, service.principal_id, 'archive', [proof])
    return store, owner, service, provider, app, worker, proof, grant


@pytest.mark.asyncio
async def test_proof_grant_is_exact_and_idempotent(tmp_path):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    with store.tx() as db:
        assert apply_entry_grants(store, db, owner, service.principal_id, 'archive', [proof]) == [grant]
        got, _ = require_grant(store, db, service, proof['entry_ref'], grant_id=grant)
        assert json.loads(got['proof']) == proof
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError, match='immutable entry grant'):
            db.execute('UPDATE media_service_entry_grants SET proof=? WHERE id=?', ('{}', grant))
        with pytest.raises(DomainError):
            require_grant(store, db, service, 'pub_foreign')
        with pytest.raises(DomainError):
            apply_entry_grants(store, db, service, service.principal_id, 'archive', [proof])
        assert db.execute('SELECT principal_id FROM publications WHERE id=?', (proof['entry_ref'],)).fetchone()[0] == owner.principal_id
    assert provider.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [
    ('tenant_id', 'foreign'), ('principal_id', 'foreign'), ('principal_epoch', 99),
    ('binding_id', 'foreign'), ('binding_epoch', 99), ('destination_id', 'foreign'),
    ('connection_id', 'foreign'), ('native_target', '-1009999999999'),
    ('entry_ref', 'pub_foreign'), ('source_principal_id', 'foreign'), ('revision', 99),
    ('topic_id', '4'), ('native_id', '999'), ('namespace', 'scheduled'),
    ('provider_media', ['document:foreign']), ('member_ids', ['999']),
    ('origin', {'system': 'regional_knowledge', 'ref': 'knowledge://foreign', 'sha256': '0'*64})])
async def test_proof_rejects_any_manifest_scope_change(tmp_path, field, value):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    with store.tx() as db:
        with pytest.raises(DomainError):
            apply_entry_grants(store, db, owner, service.principal_id, 'archive', [{**proof, field: value}])
        assert db.execute('SELECT COUNT(*) FROM media_service_entry_grants').fetchone()[0] == 1


@pytest.mark.asyncio
async def test_proof_revocation_and_regrant_do_not_revive_old_identity(tmp_path):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    with store.tx() as db:
        revoke_entry_grant(store, db, owner, grant)
        with pytest.raises(DomainError):
            require_grant(store, db, service, proof['entry_ref'], grant_id=grant)
        new_grant, = apply_entry_grants(store, db, owner, service.principal_id, 'archive', [proof])
        assert new_grant != grant
        with pytest.raises(DomainError):
            require_grant(store, db, service, proof['entry_ref'], grant_id=grant)
        require_grant(store, db, service, proof['entry_ref'], grant_id=new_grant)


@pytest.mark.asyncio
async def test_proof_foreign_tenant_and_principal_denied(tmp_path):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    for tenant, principal in [('t', 'other-service'), ('other-tenant', 'foreign-service')]:
        other = store.authenticate(store.create_principal(tenant, principal, scopes={'media.store'}))
        with store.connection() as db, pytest.raises(DomainError):
            require_grant(store, db, other, proof['entry_ref'], grant_id=grant)


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['revision', 'origin', 'topic', 'source_principal', 'binding_epoch', 'principal_epoch', 'revoke_topic'])
async def test_proof_current_authority_and_source_changes_fail_closed(tmp_path, mutation):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    with store.tx() as db:
        if mutation == 'revision':
            db.execute('UPDATE publications SET revision=2 WHERE id=?', (proof['entry_ref'],))
        elif mutation == 'origin':
            row = db.execute('SELECT intent FROM revisions WHERE publication_id=?', (proof['entry_ref'],)).fetchone()
            intent = json.loads(row[0]); intent['origin']['sha256'] = '0'*64
            import sqlite3
            with pytest.raises(sqlite3.IntegrityError, match='immutable revision'):
                db.execute('UPDATE revisions SET intent=? WHERE publication_id=?', (canonical(intent), proof['entry_ref']))
            return
        elif mutation == 'topic':
            row = db.execute('SELECT snapshot FROM facts WHERE publication_id=?', (proof['entry_ref'],)).fetchone()
            snapshot = json.loads(row[0]); snapshot['reply_to_native_id'] = '4'
            db.execute('UPDATE facts SET snapshot=? WHERE publication_id=?', (canonical(snapshot), proof['entry_ref']))
        elif mutation == 'source_principal':
            import sqlite3
            with pytest.raises(sqlite3.IntegrityError):
                db.execute('UPDATE publications SET principal_id=? WHERE id=?', (service.principal_id, proof['entry_ref']))
            return
        elif mutation == 'binding_epoch':
            db.execute('UPDATE bindings SET epoch=epoch+1 WHERE id=?', (proof['binding_id'],))
        elif mutation == 'principal_epoch':
            db.execute('UPDATE principals SET epoch=epoch+1 WHERE tenant_id=? AND id=?', (service.tenant_id, service.principal_id))
        else:
            db.execute('DELETE FROM media_service_topic_grants WHERE principal_id=?', (service.principal_id,))
        with pytest.raises(DomainError):
            require_grant(store, db, service, proof['entry_ref'], grant_id=grant)


@pytest.mark.asyncio
async def test_proof_download_hash_is_actual_bytes_not_claimed_hash(tmp_path):
    from adapters.port import ReadPage, ReadRequest
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    page = await provider.read(ReadRequest('connection', proof['native_target'], 'item', 1, native_item=proof['native_id']), None)
    check_download(proof, page)
    with pytest.raises(DomainError):
        check_download(proof, replace(page, downloads=(replace(page.downloads[0], data=b'foreign bytes'),)))
    for field, value in [('native_id', '999'), ('native_target', '-1009999999999'), ('reply_to_native_id', '4'), ('namespace', 'scheduled'), ('provider_media', ('document:foreign',)), ('member_ids', ('999',))]:
        with pytest.raises(DomainError):
            check_download(proof, replace(page, items=(replace(page.items[0], **{field: value}),)))


@pytest.mark.asyncio
async def test_entry_get_replay_and_cache_are_exact_read_only(tmp_path):
    from social_operations.service import Application
    from social_operations.storage import Store
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    command = get_args(proof['entry_ref'], 'legacy-read')
    read = await app.call(service, 'vibepublish_media_store', command)
    assert 'operation_id' in read, read
    restarted = Application(Store(store.path))
    replay = await restarted.call(service, 'vibepublish_media_store', command)
    assert replay['operation_id'] == read['operation_id']
    await worker.run_once()
    done = store.receipt(service, read['operation_id'])
    assert done['state'] == 'verified', done
    assert done['media_store_items'][0]['entry_ref'] == proof['entry_ref']
    assert done['media_store_items'][0]['origin'] == proof['origin']
    cache = done['items'][0]['media'][0]['source']['id']
    data, mime, sha = app.read_asset(service, cache)
    assert hashlib.sha256(data).hexdigest() == sha == proof['origin']['sha256']
    for query in [{'kind': 'list', 'to': 'archive', 'thread_ref': 'https://t.me/c/4379835477/2'},
                  {'kind': 'search', 'text': 'Synthetic'}]:
        listed = await app.call(service, 'vibepublish_media_store', {'command': query})
        assert listed['media_store_items'] == [], listed
    bypass = await app.call(service, 'vibepublish_read', {'query': {'kind': 'item', 'item_ref': done['items'][0]['ref']}})
    assert bypass['error']['code'] == 'access_denied'
    assert provider.effects == 1 and provider.reads == 1
    with store.connection() as db:
        assert db.execute('SELECT principal_id FROM publications WHERE id=?', (proof['entry_ref'],)).fetchone()[0] == owner.principal_id
        assert db.execute('SELECT COUNT(*) FROM publications').fetchone()[0] == 1
    with store.tx() as db:
        revoke_entry_grant(store, db, owner, grant)
    with pytest.raises(DomainError):
        app.read_asset(service, cache)
    with pytest.raises(DomainError):
        store.receipt(service, read['operation_id'])
    denied = await app.call(service, 'vibepublish_media_store', command)
    assert 'error' in denied
    with store.tx() as db:
        new_grant, = apply_entry_grants(store, db, owner, service.principal_id, 'archive', [proof])
    assert new_grant != grant
    with pytest.raises(DomainError):
        app.read_asset(service, cache)
    assert 'error' in await app.call(service, 'vibepublish_media_store', command)
    assert provider.reads == 1


@pytest.mark.asyncio
async def test_entry_get_without_key_keeps_grant_fence(tmp_path):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    a = await app.call(service, 'vibepublish_media_store', get_args(proof['entry_ref']))
    b = await app.call(service, 'vibepublish_media_store', get_args(proof['entry_ref']))
    assert a['operation_id'] != b['operation_id']
    with store.connection() as db:
        requests = db.execute("SELECT request FROM operations WHERE action='read'").fetchall()
        assert all(json.loads(row[0])['_media_store_grant_id'] == grant for row in requests)
    with store.tx() as db:
        revoke_entry_grant(store, db, owner, grant)
    await worker.run_once()
    await worker.run_once()
    assert provider.reads == 0
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM media_store_assets WHERE purpose='download_cache'").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_entry_revoke_during_download_cannot_publish_cache(tmp_path):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    read = await app.call(service, 'vibepublish_media_store', get_args(proof['entry_ref'], 'in-flight'))
    original = provider.read
    async def revoked(request, hooks):
        page = await original(request, hooks)
        with store.tx() as db:
            revoke_entry_grant(store, db, owner, grant)
        return page
    provider.read = revoked
    await worker.run_once()
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM media_store_assets WHERE purpose='download_cache'").fetchone()[0] == 0
    with pytest.raises(DomainError):
        store.receipt(service, read['operation_id'])
    assert provider.reads == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('wrong', ['bytes', 'topic', 'source', 'target', 'provider_media', 'empty', 'extra'])
async def test_entry_worker_rejects_wrong_provider_bytes_and_source(tmp_path, wrong):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    read = await app.call(service, 'vibepublish_media_store', get_args(proof['entry_ref'], 'wrong'))
    original = provider.read
    async def altered(request, hooks):
        page = await original(request, hooks)
        if wrong == 'bytes':
            return replace(page, downloads=(replace(page.downloads[0], data=b'foreign'),))
        if wrong == 'empty':
            return replace(page, items=(), downloads=())
        if wrong == 'extra':
            return replace(page, items=page.items + page.items)
        field, value = {'topic': ('reply_to_native_id', '4'), 'source': ('native_id', '999'),
                        'target': ('native_target', '-1009999999999'),
                        'provider_media': ('provider_media', ('document:foreign',))}[wrong]
        return replace(page, items=(replace(page.items[0], **{field: value}),))
    provider.read = altered
    await worker.run_once()
    done = store.receipt(service, read['operation_id'])
    assert done['state'] != 'verified'
    assert not done.get('items')
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM media_store_assets WHERE purpose='download_cache'").fetchone()[0] == 0
    assert provider.effects == 1


@pytest.mark.asyncio
async def test_entry_admission_and_asset_deny_other_principals(tmp_path):
    store, owner, service, provider, app, worker, proof, grant = await setup_grant(tmp_path)
    read = await app.call(service, 'vibepublish_media_store', get_args(proof['entry_ref'], 'valid'))
    await worker.run_once()
    done = store.receipt(service, read['operation_id'])
    cache = done['items'][0]['media'][0]['source']['id']
    other = store.authenticate(store.create_principal('t', 'ungranted', scopes={'media.store'}))
    store.bind(owner, other.principal_id, 'archive', 'connection', '-1004379835477', rights=('publish',))
    store.set_service_media_topic(owner, other.principal_id, 'archive', '2')
    assert 'error' in await app.call(other, 'vibepublish_media_store', get_args(proof['entry_ref'], 'valid'))
    with pytest.raises(DomainError):
        app.read_asset(other, cache)
    with store.tx() as db:
        revoke_entry_grant(store, db, owner, grant)
        db.execute('UPDATE principals SET scopes=? WHERE id=?', (canonical(['media.store', 'publish']), service.principal_id))
    # Additional unrelated scope cannot bypass the revoked foreign-source cache grant.
    with pytest.raises(DomainError):
        app.read_asset(replace(service, scopes=frozenset({'media.store', 'publish'})), cache)
