from __future__ import annotations
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from adapters.telegram import TelegramAdapter
from adapters.vk import VKAdapter
from social_operations.assets import import_image
from social_operations.domain import canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from .scripted import ScriptedTL, TelegramClient, VKTransport, tg_message
from .test_native_adapters import NOW, TARGETS, asset


@pytest.fixture
def runtime(tmp_path):
    store = Store(tmp_path/'ledger.sqlite', clock=lambda: NOW)
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    transports, adapters = {}, {}
    for provider, account in [('telegram', 'mtproto_user'), ('vk', 'vk_user')]:
        store.add_connection(actor, provider, provider, account_type=account, shared=True)
        store.bind(actor, actor.principal_id, provider, provider, TARGETS[provider])
        transport = TelegramClient() if provider == 'telegram' else VKTransport()
        transports[provider] = transport
        adapters[provider] = (TelegramAdapter(transport, connection_id=provider, tl=ScriptedTL(), clock=store.clock)
                              if provider == 'telegram' else VKAdapter(transport, connection_id=provider, clock=store.clock))
        def check_marker(method, provider=provider):
            with store.connection() as db:
                assert db.execute('SELECT count(*) FROM attempts WHERE provider=? AND dispatched=1', (provider,)).fetchone()[0] > 0
        transport.before_mutation = check_marker
    app, worker = Application(store), Worker(store, adapters)
    return store, actor, transports, app, worker


async def call(app, actor, name, args):
    response = await app.call(actor, 'vibepublish_' + name, args)
    assert 'operation_id' in response, response
    return response


def result(store, actor, receipt):
    return store.receipt(actor, receipt['operation_id'])


@pytest.mark.asyncio
async def test_two_native_adapters_full_ledger_ordered_media_schedule_and_cancel(runtime):
    store, actor, transports, app, worker = runtime
    media = [{'source': {'kind': 'asset', 'id': import_image(store, actor, asset(i).data, 'image/png')}} for i in [1, 2]]
    accepted = await call(app, actor, 'publish', {'to': ['telegram', 'vk'], 'content': {'text': 'Ordered native album'},
        'media': media, 'delivery': {'kind': 'at', 'at': timestamp(NOW+3600)}, 'request_key': 'native-pair'})
    assert accepted['state'] == 'accepted'
    assert all(not t.calls for t in transports.values())
    assert await worker.run_once()
    scheduled = result(store, actor, accepted)
    assert scheduled['state'] == 'scheduled', scheduled
    assert [d['observed'] for d in scheduled['deliveries']] == ['provider_scheduled']*2
    assert all(d['media_check'] == 'provider_binding' for d in scheduled['deliveries'])
    assert all(t.effects == 1 for t in transports.values())
    again = await call(app, actor, 'publish', {'to': ['telegram', 'vk'], 'content': {'text': 'Ordered native album'},
        'media': media, 'delivery': {'kind': 'at', 'at': timestamp(NOW+3600)}, 'request_key': 'native-pair'})
    assert again['operation_id'] == accepted['operation_id']
    assert not await worker.run_once()
    cancel = await call(app, actor, 'publication_update', {'publication_id': scheduled['resource_id'], 'expected_revision': 1,
                                                         'change': {'kind': 'cancel'}, 'request_key': 'cancel-pair'})
    await worker.run_once()
    done = result(store, actor, cancel)
    assert done['state'] == 'cancelled', done
    assert [d['observed'] for d in done['deliveries']] == ['cancelled']*2
    assert all(t.effects == 2 for t in transports.values())
    assert not transports['telegram'].scheduled and not transports['vk'].posts


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_partner_reads_other_authors_and_updates_exact_native_queue_item(runtime, provider):
    store, owner, transports, app, worker = runtime
    token = store.create_principal('partner-tenant', 'partner', scopes={'bootstrap','publish','publication.manage','status','forward'})
    binding = store.bind(owner, 'partner', 'bound', provider, TARGETS[provider])
    actor = store.authenticate(token)
    transport = transports[provider]
    if provider == 'telegram':
        transport.scheduled[(101, 77)] = tg_message(77, text='Foreign scheduled post', photo=900,
            date=datetime.fromtimestamp(NOW+3600, timezone.utc))
    else:
        transport.posts[(-101, 77)] = {'owner_id': -101, 'id': 77, 'text': 'Foreign scheduled post', 'date': NOW+3600,
            'post_type': 'postpone', 'attachments': [{'type': 'photo', 'photo': {'owner_id': -101, 'id': 900}}]}
    read = await call(app, actor, 'read', {'query': {'kind': 'scheduled', 'destination': 'bound'}})
    await worker.run_once()
    item, = result(store, actor, read)['items']
    assert item['text'] == 'Foreign scheduled post' and 'publication_id' not in item
    edit = await call(app, actor, 'publication_update', {'item_ref': item['ref'], 'change': {'kind': 'edit', 'content': {'text': 'Corrected by authorized partner'}}, 'request_key': 'edit-native'})
    await worker.run_once()
    edited = result(store, actor, edit)
    assert edited['state'] == 'scheduled', edited
    assert transport.effects == 1
    if provider == 'telegram':
        assert transport.scheduled[(101, 77)].media.photo.id == 900
    else:
        assert transport.posts[(-101, 77)]['attachments'][0]['photo']['id'] == 900
    # The previous read ref is immutable and cannot clobber a newly changed item.
    stale = await call(app, actor, 'publication_update', {'item_ref': item['ref'], 'change': {'kind': 'cancel'}, 'request_key': 'stale-cancel'})
    await worker.run_once()
    assert result(store, actor, stale)['state'] == 'blocked'
    assert transport.effects == 1
    # Right revocation applies to the saved ref and cached operation receipts.
    store.revoke_binding(owner, binding)
    denied = await app.call(store.authenticate(token), 'vibepublish_status', {'ids': [read['operation_id']]})
    assert denied['error']['code'] == 'access_revoked'


@pytest.mark.asyncio
async def test_opaque_scoped_source_ref_forwards_natively_but_never_grants_private_source(runtime):
    store, actor, transports, app, worker = runtime
    source_binding = store.bind(actor, actor.principal_id, 'source', 'telegram', '-1000000000202')
    transports['telegram'].messages[(202, 77)] = tg_message(77, 202, 'Private source body')
    read = await call(app, actor, 'read', {'query': {'kind': 'feed', 'destination': 'source'}})
    await worker.run_once()
    item, = result(store, actor, read)['items']
    forward = await call(app, actor, 'engage', {'command': {'kind': 'forward', 'item_ref': item['ref'], 'to': ['telegram']}})
    await worker.run_once()
    done = result(store, actor, forward)
    assert done['state'] == 'verified', done
    assert done['deliveries'][0]['forward_origin']['original_url'] == 'https://t.me/c/202/77'
    partner_token = store.create_principal('partner-tenant','partner', scopes={'publish','forward','status'})
    store.bind(actor, 'partner', 'telegram', 'telegram', TARGETS['telegram'])
    partner = store.authenticate(partner_token)
    denied = await app.call(partner, 'vibepublish_engage', {'command': {'kind': 'forward', 'item_ref': item['ref'], 'to': ['telegram']}})
    assert denied['error']['code'] == 'item_not_available'
    denied = await app.call(partner, 'vibepublish_engage', {'command': {'kind': 'forward', 'item_ref': 'https://t.me/c/202/77', 'to': ['telegram']}})
    assert denied['error']['code'] == 'source_access_denied'


@pytest.mark.asyncio
async def test_partner_history_does_not_expose_other_private_publication_identity(runtime):
    store, owner, transports, app, worker = runtime
    publication = await call(app, owner, 'publish', {'to': ['vk'], 'content': {'text': 'Visible channel content'}})
    await worker.run_once()
    token = store.create_principal('partner-tenant', 'partner', scopes={'publish','status'})
    store.bind(owner, 'partner', 'vk', 'vk', TARGETS['vk'])
    partner = store.authenticate(token)
    history = await call(app, partner, 'read', {'query': {'kind': 'history', 'destination': 'vk', 'author': 'channel'}})
    rows = history['items']
    assert len(rows) == 1 and rows[0]['text'] == 'Visible channel content'
    assert 'publication_id' not in rows[0]
    forbidden = await app.call(partner, 'vibepublish_status', {'ids': [publication['resource_id']]})
    assert forbidden['error']['code'] == 'not_found'


@pytest.mark.asyncio
async def test_actual_adapter_schedule_readback_cannot_downgrade_into_immediate_success(runtime):
    store, actor, transports, app, worker = runtime
    adapter = worker.adapters['telegram']
    original = adapter._observe
    async def malformed(r, checkpoint, hooks):
        observed = await original(r, checkpoint, hooks)
        return replace(observed, observed='published', items=(replace(observed.items[0], namespace='published', scheduled_at=None),))
    adapter._observe = malformed
    receipt = await call(app, actor, 'publish', {'to': ['telegram'], 'content': {'text': 'Must be queued'},
        'delivery': {'kind': 'at', 'at': timestamp(NOW+3600)}})
    await worker.run_once()
    done = result(store, actor, receipt)
    assert done['state'] == 'outcome_unknown', done
    assert done['error']['code'] == 'native_schedule_not_observed'
    assert transports['telegram'].effects == 1
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_unknown_native_child_never_erases_other_provider_success(runtime):
    store, actor, transports, app, worker = runtime
    def dropped(_):
        raise OSError('Lost fixture response')
    transports['telegram'].after_mutation = dropped
    receipt = await call(app, actor, 'publish', {'to': ['telegram', 'vk'], 'content': {'text': 'Independent children'}})
    await worker.run_once()
    done = result(store, actor, receipt)
    assert [d['state'] for d in done['deliveries']] == ['outcome_unknown', 'verified']
    assert all(t.effects == 1 for t in transports.values())
    assert not await worker.run_once()
