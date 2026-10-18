"""Synthetic exact legacy-origin-v1 evidence; no production identifiers."""
import hashlib
import io
import json
from dataclasses import replace

import pytest
from PIL import Image

from adapters.port import ReadRequest
from social_operations.domain import DomainError, canonical, timestamp
from social_operations.media_entry_grants import (
    apply_entry_grants, check_download, entry_proof, proof_sha256, require_grant,
    revoke_entry_grant)
from tests.runtime.test_media_store import args, get_args, runtime


ORIGIN = {'system': 'regional_knowledge',
          'ref': 'knowledge://illustrations/00000000-0000-4000-8000-000000000001'}


async def legacy(tmp_path, *, origin=None, topic='4', mutate=None):
    store, owner, asset, provider, app, worker = runtime(tmp_path)
    put = await app.call(owner, 'vibepublish_media_store',
                         args(asset, topic=topic, origin=ORIGIN if origin is None else origin))
    assert 'resource_id' in put, put
    await worker.run_once()
    service = store.authenticate(store.create_principal(
        't', 'archive-service', scopes={'bootstrap', 'status', 'media.store'}))
    store.bind(owner, service.principal_id, 'archive', 'connection',
               '-1004379835477', rights=('publish',))
    store.set_service_media_topic(owner, service.principal_id, 'archive', topic)
    with store.tx() as db:
        fact = db.execute('SELECT id,snapshot FROM facts WHERE publication_id=?',
                          (put['resource_id'],)).fetchone()
        snapshot = json.loads(fact['snapshot'])
        snapshot['media_hashes'] = []
        if mutate:
            mutate(snapshot)
        db.execute('UPDATE facts SET snapshot=? WHERE id=?', (canonical(snapshot), fact['id']))
        binding = store.binding(db, service, alias='archive')
        proof = entry_proof(store, db, service, binding, put['resource_id'])
        grant, = apply_entry_grants(store, db, owner, service.principal_id, 'archive', [proof])
    native = proof['native_id']
    item, payloads = provider.items[native]
    provider.items[native] = (replace(item, media_hashes=()), payloads)
    return store, owner, service, provider, app, worker, proof, grant


@pytest.mark.asyncio
async def test_legacy_get_receipt_asset_and_key_replay_survive_fact_refresh(tmp_path):
    store, owner, service, provider, app, worker, proof, grant = await legacy(tmp_path)
    assert proof['proof_kind'] == 'legacy_origin_v1'
    assert proof['origin'] == ORIGIN and 'sha256' not in proof['origin']
    assert set(proof['download_evidence']) == {'kind', 'slot', 'sha256', 'mime', 'size'}
    assert 'observed_at' not in proof
    command = get_args(proof['entry_ref'], 'legacy-replay')
    accepted = await app.call(service, 'vibepublish_media_store', command)
    item, payloads = provider.items[proof['native_id']]
    refreshed = replace(item, observed_at=timestamp(1800000300),
                        metrics=(('views', 7, 'count'),))
    provider.items[item.native_id] = (refreshed, payloads)
    await worker.run_once()
    done = store.receipt(service, accepted['operation_id'])
    assert done['state'] == 'verified', done
    cache = done['items'][0]['media'][0]['source']['id']
    data, mime, sha = app.read_asset(service, cache)
    assert hashlib.sha256(data).hexdigest() == sha == proof_sha256(proof)
    assert done['media_store_items'][0]['origin'] == ORIGIN
    with store.connection() as db:
        fact = db.execute('SELECT id,snapshot FROM facts WHERE publication_id=?',
                          (proof['entry_ref'],)).fetchone()
        assert fact['id'] == proof['source_fact_id']
        assert json.loads(fact['snapshot'])['observed_at'] == refreshed.observed_at
        assert json.loads(require_grant(store, db, service, proof['entry_ref'])[0]['proof']) == proof
        intent = json.loads(db.execute('SELECT intent FROM revisions WHERE publication_id=?',
                                       (proof['entry_ref'],)).fetchone()[0])
        assert intent['origin'] == ORIGIN
    replay = await app.call(service, 'vibepublish_media_store', command)
    assert replay['operation_id'] == accepted['operation_id']
    assert app.read_asset(service, cache)[0] == data
    assert provider.reads == 1 and provider.effects == 1
    for query in [{'kind': 'list', 'to': 'archive', 'thread_ref': 'https://t.me/c/4379835477/4'},
                  {'kind': 'search', 'text': 'Synthetic'}]:
        assert (await app.call(service, 'vibepublish_media_store', {'command': query}))['media_store_items'] == []
    denied = await app.call(service, 'vibepublish_media_store', get_args('pub_unlisted', 'outside-manifest'))
    assert 'error' in denied


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['missing', 'empty', 'extra', 'missing_hash', 'bad_hash',
                                  'kind', 'slot', 'mime', 'size', 'hash_conflict',
                                  'duplicate_hash', 'photo', 'extra_attachment'])
async def test_legacy_rejects_ambiguous_or_wrong_evidence_at_grant(tmp_path, case):
    def mutate(snapshot):
        evidence = snapshot['observed_media'][0]
        if case == 'missing':
            snapshot.pop('observed_media')
        elif case == 'empty':
            snapshot['observed_media'] = []
        elif case == 'extra':
            snapshot['observed_media'].append(dict(evidence))
        elif case == 'missing_hash':
            evidence.pop('sha256')
        elif case in {'bad_hash', 'kind', 'slot', 'mime', 'size'}:
            field, value = {'bad_hash': ('sha256', 'bad'), 'kind': ('kind', 'source_sha256'),
                            'slot': ('slot', 1), 'mime': ('mime', 'application/pdf'),
                            'size': ('size', 0)}[case]
            evidence[field] = value
        elif case == 'hash_conflict':
            snapshot['media_hashes'] = ['0' * 64]
        elif case == 'duplicate_hash':
            snapshot['media_hashes'] = [evidence['sha256']] * 2
        elif case == 'photo':
            snapshot['provider_media'] = ['photo:1']
        else:
            snapshot['provider_media'].append('document:2')
    with pytest.raises(DomainError):
        await legacy(tmp_path, mutate=mutate)


@pytest.mark.asyncio
@pytest.mark.parametrize('origin,topic', [
    ({**ORIGIN, 'system': 'foreign'}, '4'),
    ({**ORIGIN, 'ref': 'knowledge://documents/00000000-0000-4000-8000-000000000001'}, '4'),
    ({**ORIGIN, 'ref': 'knowledge://illustrations/not-a-uuid'}, '4'),
    (ORIGIN, '2'),
])
async def test_legacy_rejects_wrong_origin_or_topic(tmp_path, origin, topic):
    with pytest.raises(DomainError):
        await legacy(tmp_path, origin=origin, topic=topic)


@pytest.mark.asyncio
async def test_present_origin_sha_never_falls_back_to_observed_sha(tmp_path):
    store, owner, service, provider, app, worker, proof, grant = await legacy(
        tmp_path, origin={**ORIGIN, 'sha256': '0' * 64})
    assert 'proof_kind' not in proof
    assert proof_sha256(proof) == '0' * 64
    page = await provider.read(ReadRequest('connection', proof['native_target'], 'item', 1,
                                          native_item=proof['native_id']), None)
    with pytest.raises(DomainError):
        check_download(proof, page)
    for changed in [{'proof_kind': 'unknown'}, {'proof_kind': None},
                    {'origin': {**ORIGIN, 'sha256': None}}]:
        with pytest.raises(DomainError):
            proof_sha256({**proof, **changed})


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['fact', 'sha256', 'mime', 'size', 'revision', 'epoch'])
async def test_legacy_current_evidence_and_authority_changes_revoke_old_proof(tmp_path, changed):
    store, owner, service, provider, app, worker, proof, grant = await legacy(tmp_path)
    read = await app.call(service, 'vibepublish_media_store', get_args(proof['entry_ref'], 'read'))
    await worker.run_once()
    cache = store.receipt(service, read['operation_id'])['items'][0]['media'][0]['source']['id']
    with store.tx() as db:
        if changed == 'fact':
            db.execute('UPDATE facts SET id=? WHERE id=?', ('fact_replaced', proof['source_fact_id']))
        elif changed == 'revision':
            db.execute('UPDATE publications SET revision=2 WHERE id=?', (proof['entry_ref'],))
        elif changed == 'epoch':
            db.execute('UPDATE bindings SET epoch=epoch+1 WHERE id=?', (proof['binding_id'],))
        else:
            row = db.execute('SELECT snapshot FROM facts WHERE id=?', (proof['source_fact_id'],)).fetchone()
            snapshot = json.loads(row[0])
            snapshot['observed_media'][0][changed] = {'sha256': '0' * 64,
                                                     'mime': 'image/jpeg', 'size': 1}[changed]
            db.execute('UPDATE facts SET snapshot=? WHERE id=?',
                       (canonical(snapshot), proof['source_fact_id']))
    with pytest.raises(DomainError):
        store.receipt(service, read['operation_id'])
    with pytest.raises(DomainError):
        app.read_asset(service, cache)
    assert 'error' in await app.call(service, 'vibepublish_media_store', get_args(proof['entry_ref'], 'read'))


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['swapped_rendition', 'extra_evidence', 'media_hash_conflict', 'revoke'])
async def test_legacy_worker_does_not_cache_changed_or_revoked_download(tmp_path, case):
    store, owner, service, provider, app, worker, proof, grant = await legacy(tmp_path)
    accepted = await app.call(service, 'vibepublish_media_store', get_args(proof['entry_ref'], case))
    original = provider.read
    async def altered(request, hooks):
        page = await original(request, hooks)
        remote = page.items[0]
        if case == 'revoke':
            with store.tx() as db:
                revoke_entry_grant(store, db, owner, grant)
            return page
        if case == 'extra_evidence':
            extra = replace(remote.observed_media[0], slot=1)
            return replace(page, items=(replace(remote, observed_media=remote.observed_media + (extra,)),))
        if case == 'media_hash_conflict':
            return replace(page, items=(replace(remote, media_hashes=('0' * 64,)),))
        output = io.BytesIO()
        Image.new('RGB', (12, 10), 'red').save(output, format='PNG')
        data = output.getvalue()
        evidence = replace(remote.observed_media[0], sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        return replace(page, items=(replace(remote, observed_media=(evidence,)),),
                       downloads=(replace(page.downloads[0], data=data),))
    provider.read = altered
    await worker.run_once()
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM media_store_assets WHERE purpose='download_cache'").fetchone()[0] == 0
    if case == 'revoke':
        with pytest.raises(DomainError):
            store.receipt(service, accepted['operation_id'])
    else:
        assert store.receipt(service, accepted['operation_id'])['state'] != 'verified'


@pytest.mark.asyncio
async def test_legacy_regrant_cannot_revive_old_receipt_or_cache(tmp_path):
    store, owner, service, provider, app, worker, proof, grant = await legacy(tmp_path)
    command = get_args(proof['entry_ref'], 'old-grant')
    accepted = await app.call(service, 'vibepublish_media_store', command)
    await worker.run_once()
    cache = store.receipt(service, accepted['operation_id'])['items'][0]['media'][0]['source']['id']
    with store.tx() as db:
        revoke_entry_grant(store, db, owner, grant)
        new, = apply_entry_grants(store, db, owner, service.principal_id, 'archive', [proof])
        assert new != grant
    with pytest.raises(DomainError):
        app.read_asset(service, cache)
    with pytest.raises(DomainError):
        store.receipt(service, accepted['operation_id'])
    assert 'error' in await app.call(service, 'vibepublish_media_store', command)
    assert provider.reads == 1
