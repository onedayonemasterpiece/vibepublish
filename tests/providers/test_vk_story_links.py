"""VK Story links: exact scoped wall identity, frozen request and safe recovery."""
import copy
import hashlib
import json
from dataclasses import replace

import pytest

from adapters.native import identity
from adapters.vk import VKAdapter
from social_operations.domain import DomainError, OutcomeUnknown, canonical
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from .scripted import VKTransport
from .test_native_adapters import NOW, Journal, asset, request
from .test_vk_stories import png_bytes


LINK = {'url': 'https://vk.com/wall-101_42', 'text': 'read', 'target': '-101', 'id': '42'}


def linked_request(**changes):
    return request('vk', surface='story', content_json=canonical({'text': ''}),
                   assets=(asset(),), story_link_json=canonical(LINK), **changes)


def source(transport):
    transport.posts[(-101, 42)] = {'owner_id': -101, 'id': 42, 'text': 'Original wall post',
                                 'date': NOW - 60, 'attachments': []}


def adapter_setup():
    transport, journal = VKTransport(), Journal()
    source(transport)
    adapter = VKAdapter(transport, connection_id='connection', clock=lambda: NOW)
    return adapter, transport, journal


@pytest.mark.asyncio
@pytest.mark.parametrize('visible_label', ['read', 'Читать', 'Read more'])
async def test_link_upload_exact_readback_and_fingerprint(visible_label):
    adapter, transport, journal = adapter_setup()
    r = linked_request()
    original = transport.invoke

    async def invoke(**kwargs):
        result = await original(**kwargs)
        if kwargs['method'] in {'stories.save', 'stories.getById'}:
            result['items'][0]['link']['text'] = visible_label
        return result

    transport.invoke = invoke
    observation = await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    item = observation.items[0]
    assert json.loads(item.story_link_json) == {'url': LINK['url'], 'text': visible_label}
    upload = next(params for method, _, params in transport.calls if method == 'stories.getPhotoUploadServer')
    assert upload == {'group_id': 101, 'add_to_news': 1, 'link_url': LINK['url'], 'link_text': 'read'}
    assert transport.effects == 1 and item.media_check == 'provider_binding'
    assert identity(item) != identity(replace(item, story_link_json='{}'))
    again = await adapter.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert again.items[0].story_link_json == item.story_link_json
    assert transport.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['missing', 'url', 'text', 'photo', 'identity'])
async def test_story_readback_mismatch_never_republishes(change):
    adapter, transport, journal = adapter_setup()
    r = linked_request()
    original = transport.invoke

    async def invoke(**kwargs):
        result = await original(**kwargs)
        if kwargs['method'] == 'stories.getById':
            row = result['items'][0]
            if change == 'missing':
                row.pop('link')
            elif change == 'url':
                row['link']['url'] = 'https://vk.com/wall-101_43'
            elif change == 'text':
                row['link']['text'] = ''
            elif change == 'photo':
                row['photo']['id'] += 1
            else:
                row['id'] += 1
        return result

    transport.invoke = invoke
    with pytest.raises(DomainError):
        await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    assert transport.effects == 1
    with pytest.raises(DomainError):
        await adapter.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert transport.effects == 1


@pytest.mark.asyncio
async def test_ambiguous_save_never_retries():
    adapter, transport, journal = adapter_setup()
    r = linked_request()
    transport.after_mutation = lambda method: (_ for _ in ()).throw(OSError('response lost'))
    with pytest.raises(OSError):
        await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    assert transport.effects == 1
    with pytest.raises(OutcomeUnknown):
        await adapter.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert transport.effects == 1


@pytest.mark.asyncio
async def test_missing_wall_source_stops_before_upload():
    adapter, transport, journal = adapter_setup()
    transport.posts.clear()
    with pytest.raises(DomainError, match='source missing'):
        await adapter.execute(await adapter.prepare(linked_request(), journal.hooks), journal.hooks)
    assert transport.effects == 0 and not transport.uploads and not journal.markers


@pytest.mark.asyncio
@pytest.mark.parametrize('link', [
    {**LINK, 'url': 'https://example.com'},
    {**LINK, 'text': 'arbitrary'},
    {**LINK, 'id': '0'},
    {**LINK, 'target': '101'},
])
async def test_adapter_rejects_invalid_link(link):
    adapter, transport, journal = adapter_setup()
    r = replace(linked_request(), story_link_json=canonical(link))
    with pytest.raises(DomainError):
        await adapter.prepare(r, journal.hooks)
    assert not transport.uploads and transport.effects == 0


def runtime(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite')
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    store.add_connection(actor, 'vk-connection', 'vk', account_type='vk_user', secret_ref='VIBEPUBLISH_TEST')
    store.bind(actor, 'owner', 'vk-story', 'vk-connection', '-101')
    data = png_bytes()
    sha = hashlib.sha256(data).hexdigest()
    with store.tx() as db:
        db.execute('INSERT INTO assets(id,tenant_id,principal_id,sha256,mime,width,height,bytes,source_sha256,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('asset_story', actor.tenant_id, actor.principal_id, sha, 'image/png', 90, 160, data, sha, store.clock()))
    transport = VKTransport()
    source(transport)
    worker = Worker(store, {'vk-connection': VKAdapter(transport, connection_id='vk-connection', clock=store.clock)})
    args = {'to': ['vk-story'], 'surface': 'story',
            'media': [{'source': {'kind': 'asset', 'id': 'asset_story'}, 'role': 'image'}],
            'story_link': {'item_ref': LINK['url'], 'text': 'read'}, 'request_key': 'linked'}
    return store, actor, Application(store), worker, transport, args


@pytest.mark.asyncio
async def test_core_freezes_photo_and_link_idempotently(tmp_path):
    store, actor, app, worker, transport, args = runtime(tmp_path)
    accepted = await app.call(actor, 'vibepublish_publish', args)
    assert accepted['state'] == 'accepted', accepted
    replay = await app.call(actor, 'vibepublish_publish', copy.deepcopy(args))
    assert replay['operation_id'] == accepted['operation_id']
    with store.connection() as db:
        plan = json.loads(db.execute('SELECT plan FROM attempts WHERE operation_id=?', (accepted['operation_id'],)).fetchone()[0])
    assert json.loads(plan['story_link_json']) == LINK
    assert plan['assets'][0]['ref'] == 'asset_story'
    assert len(plan['assets'][0]['sha256']) == 64
    assert await worker.run_once()
    receipt = store.receipt(actor, accepted['operation_id'])
    assert receipt['state'] == 'verified', receipt
    assert transport.effects == 1
    args['story_link']['text'] = 'more'
    changed = await app.call(actor, 'vibepublish_publish', args)
    assert changed['error']['code'] == 'idempotency_conflict'


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['unbound', 'crossprovider', 'post', 'scheduled'])
async def test_core_rejects_unauthorized_or_unsupported_link(tmp_path, mutation):
    store, actor, app, worker, transport, args = runtime(tmp_path)
    if mutation == 'unbound':
        args['story_link']['item_ref'] = 'https://vk.com/wall-202_42'
    elif mutation == 'crossprovider':
        args['story_link']['item_ref'] = 'https://t.me/example/42'
    elif mutation == 'post':
        args['surface'] = 'post'
    else:
        from social_operations.domain import timestamp
        args['delivery'] = {'kind': 'at', 'at': timestamp(store.clock() + 3600)}
    receipt = await app.call(actor, 'vibepublish_publish', args)
    assert 'error' in receipt, receipt
    assert transport.effects == 0 and not transport.calls


@pytest.mark.asyncio
async def test_source_access_revoked_before_worker_no_read_or_send(tmp_path):
    store, actor, app, worker, transport, args = runtime(tmp_path)
    accepted = await app.call(actor, 'vibepublish_publish', args)
    assert accepted['state'] == 'accepted'
    with store.tx() as db:
        db.execute("UPDATE bindings SET epoch=epoch+1 WHERE alias='vk-story'")
    assert await worker.run_once()
    with pytest.raises(DomainError, match='access revoked'):
        store.receipt(actor, accepted['operation_id'])
    with store.connection() as db:
        state = db.execute('SELECT state FROM attempts WHERE operation_id=?', (accepted['operation_id'],)).fetchone()[0]
    assert state == 'blocked'
    assert not transport.calls and transport.effects == 0

@pytest.mark.asyncio
async def test_scoped_native_item_ref_without_vibepublish_origin(tmp_path):
    from dataclasses import asdict
    store, actor, app, worker, transport, args = runtime(tmp_path)
    native = VKAdapter(transport, connection_id='vk-connection', clock=store.clock)._item(
        transport.posts[(-101, 42)], 'published', '-101')
    with store.tx() as db:
        binding = store.binding(db, actor, alias='vk-story')
        projected = app.project_item(db, actor, binding, asdict(native))
    args['story_link']['item_ref'] = projected['ref']
    accepted = await app.call(actor, 'vibepublish_publish', args)
    assert accepted['state'] == 'accepted', accepted
    assert await worker.run_once()
    assert store.receipt(actor, accepted['operation_id'])['state'] == 'verified'


@pytest.mark.asyncio
async def test_distinct_source_binding_revocation_fails_before_read(tmp_path):
    store, actor, app, worker, transport, args = runtime(tmp_path)
    store.bind(actor, 'owner', 'vk-source', 'vk-connection', '-202')
    args['story_link']['item_ref'] = 'https://vk.com/wall-202_42'
    accepted = await app.call(actor, 'vibepublish_publish', args)
    assert accepted['state'] == 'accepted', accepted
    with store.tx() as db:
        db.execute("UPDATE bindings SET epoch=epoch+1 WHERE alias='vk-source'")
    assert await worker.run_once()
    assert store.receipt(actor, accepted['operation_id'])['state'] == 'blocked'
    assert not transport.calls and not transport.effects


@pytest.mark.asyncio
async def test_no_photo_evidence_keeps_linked_story_unknown():
    adapter, transport, journal = adapter_setup()
    original = transport.invoke

    async def invoke(**kwargs):
        result = await original(**kwargs)
        if kwargs['method'] in {'stories.save', 'stories.getById'}:
            result['items'][0].pop('photo')
        return result

    transport.invoke = invoke
    r = linked_request()
    with pytest.raises(OutcomeUnknown) as failure:
        await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    assert failure.value.code == 'vk_story_photo_binding_missing'
    with pytest.raises(OutcomeUnknown):
        await adapter.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert transport.effects == 1


@pytest.mark.asyncio
async def test_linked_story_known_readback_failure_recovers_without_save():
    adapter, transport, journal = adapter_setup()
    r = linked_request()
    original = transport.invoke
    fail_read = True

    async def invoke(**kwargs):
        if kwargs['method'] == 'stories.getById' and fail_read:
            raise OSError('read response lost')
        return await original(**kwargs)

    transport.invoke = invoke
    with pytest.raises(OSError):
        await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    fail_read = False
    result = await adapter.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert result.observed == 'published'
    assert transport.effects == 1

@pytest.mark.asyncio
async def test_save_link_projection_does_not_lose_known_story_identity():
    adapter, transport, journal = adapter_setup()
    original = transport.invoke

    async def invoke(**kwargs):
        result = await original(**kwargs)
        if kwargs['method'] == 'stories.save':
            result['items'][0]['link'] = {'url': LINK['url']}
        return result

    transport.invoke = invoke
    r = linked_request()
    result = await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    assert result.observed == 'published'
    assert journal.checkpoints[-1][1]['id'] == result.items[0].native_id
    assert transport.effects == 1
