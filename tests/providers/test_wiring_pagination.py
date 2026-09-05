from __future__ import annotations
import json
from dataclasses import replace

import pytest

from adapters.port import ReadRequest
from adapters.wiring import native_adapters, _bundle, vk_credentials
from social_operations.domain import DomainError
from social_operations.storage import Store
from .scripted import ScriptedTL, TelegramClient, tg_message
from .test_native_adapters import setup, TARGETS, request, NOW


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_feed_pagination_reads_past_first_native_page_without_repeating(provider):
    adapter, transport, journal = setup(provider)
    for i in range(1, 133):
        if provider == 'telegram':
            transport.messages[(101, i)] = tg_message(i)
        else:
            transport.posts[(-101, i)] = {'id': i, 'owner_id': -101, 'text': 'Fixture', 'date': NOW-100, 'attachments': [], 'post_type': 'post'}
    cursor, seen = None, []
    for _ in range(10):
        page = await adapter.read(ReadRequest('connection', TARGETS[provider], 'feed', limit=25, cursor=cursor), journal.hooks)
        seen.extend(i.native_id for i in page.items)
        cursor = page.cursor
        if cursor is None:
            break
    assert len(seen) == 132 and len(set(seen)) == 132
    assert transport.effects == 0


@pytest.mark.asyncio
async def test_telegram_history_page_boundary_never_splits_album():
    adapter, transport, journal = setup('telegram')
    for i in range(1, 135):
        group = 90 if 90 <= i <= 99 else None
        transport.messages[(101, i)] = tg_message(i, group=group, photo=i if group else None, text='Fixture' if i == 90 or not group else '')
    first = await adapter.read(ReadRequest('connection', TARGETS['telegram'], 'feed', limit=36), journal.hooks)
    album = next(i for i in first.items if len(i.member_ids) > 1)
    assert album.member_ids == tuple(map(str, range(90, 100)))
    second = await adapter.read(ReadRequest('connection', TARGETS['telegram'], 'feed', limit=36, cursor=first.cursor), journal.hooks)
    assert set(x for i in first.items for x in i.member_ids).isdisjoint(x for i in second.items for x in i.member_ids)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_native_delete_preserves_identity_and_verifies_absence(provider):
    adapter, transport, journal = setup(provider)
    r = request(provider)
    item, = (await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)).items
    r = replace(r, action='delete', existing=item, attempt_id='attempt_delete')
    journal.markers.clear()
    result = await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    assert result.observed == 'deleted' and result.items[0].native_id == item.native_id
    assert transport.effects == 2


@pytest.mark.asyncio
async def test_opt_in_native_wiring_disables_implicit_retries_and_never_starts_login(tmp_path):
    store = Store(tmp_path/'ledger.sqlite')
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    store.add_connection(actor, 'native-tg', 'telegram', account_type='mtproto_user', secret_ref='VIBEPUBLISH_TG')
    store.add_connection(actor, 'separate-max', 'max', account_type='max_web', secret_ref='VIBEPUBLISH_MAX')
    events, options = [], {}
    class Client(TelegramClient):
        async def connect(self): events.append('connect')
        async def is_user_authorized(self): events.append('authorized'); return True
        async def disconnect(self): events.append('disconnect')
        async def start(self, *a, **k): pytest.fail('Interactive login forbidden')
    def factory(credentials, **kw):
        options.update(kw)
        assert credentials['session'] == 'dedicated-fixture-session'
        return Client()
    env = {'VIBEPUBLISH_TG': json.dumps({'api_id': 1, 'api_hash': 'a'*32, 'session': 'dedicated-fixture-session'})}
    async with native_adapters(store, env=env, telegram_factory=factory, tl=ScriptedTL()) as adapters:
        assert set(adapters) == {'native-tg'}
        assert events == ['connect', 'authorized']
    assert events[-1] == 'disconnect'
    assert options == dict(request_retries=0, connection_retries=0, flood_sleep_threshold=0,
                           auto_reconnect=False, receive_updates=False, raise_last_call_error=True)


@pytest.mark.parametrize('name', ['TELEGRAM_SESSION', '../sessions/operator', 'https://example.test/token', 'VIBEPUBLISH_lower'])
def test_no_credential_fallbacks_or_other_project_sessions(name):
    with pytest.raises(DomainError, match='reference invalid'):
        _bundle(name, {name: '{}'})


def test_vk_wiring_rejects_ambiguous_roles_and_cross_kind_group():
    for bundle in [{'roles': {}}, {'roles': {'operator': {'token': 'fixture', 'kind': 'user'}}},
                   {'roles': {'editor': {'token': 'fixture', 'kind': 'group'}}},
                   {'roles': {'editor': {'token': 'fixture', 'kind': 'user', 'group_id': 101}}}]:
        with pytest.raises(DomainError):
            vk_credentials(bundle)


@pytest.mark.asyncio
async def test_cancel_lost_ack_cannot_mistake_empty_queue_for_deletion():
    from social_operations.domain import timestamp, OutcomeUnknown
    adapter, transport, journal = setup('telegram')
    r = request('telegram', scheduled_at=timestamp(NOW+3600))
    item, = (await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)).items
    r = replace(r, action='cancel', existing=item, scheduled_at=None, attempt_id='cancel_lost_ack')
    journal.markers.clear()
    def drop(_):
        raise OSError('lost fixture ack')
    transport.after_mutation = drop
    with pytest.raises(DomainError):
        await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    assert not transport.scheduled
    with pytest.raises(OutcomeUnknown):
        await adapter.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert transport.effects == 2
