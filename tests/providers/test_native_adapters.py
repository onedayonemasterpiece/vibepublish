from __future__ import annotations
import gzip
import hashlib
import io
import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from adapters.native import identity
from adapters.port import Asset, Hooks, ProviderRequest, ReadRequest, RemoteItem
from adapters.telegram import TelegramAdapter, peer_key
from adapters.vk import VKAdapter
from adapters.vk_transport import VKHTTPTransport, VKToken, decoded_json, validated_url
from social_operations.domain import DomainError, OutcomeUnknown, canonical, parse_source, timestamp
from .scripted import ScriptedTL, TelegramClient, VKTransport, channel, obj, tg_message

NOW = 1_800_000_000
TARGETS = {'telegram': '-1000000000101', 'vk': '-101'}


def asset(number=1):
    stream = io.BytesIO()
    Image.new('RGB', (4, 4), (number, 40, 60)).save(stream, format='PNG')
    data = stream.getvalue()
    return Asset('asset_' + str(number), hashlib.sha256(data).hexdigest(), 'image/png', len(data), data=data)


def request(provider, **changes):
    r = ProviderRequest('op_test', 'attempt_test', 'a'*64, 'connection',
                        'mtproto_user' if provider == 'telegram' else 'vk_user', 'VIBEPUBLISH_FIXTURE',
                        'destination', TARGETS[provider], 'publish', 'post', canonical({'text': 'Fixture'}),
                        (), None, NOW+120)
    return replace(r, **changes)


class Journal:
    def __init__(self):
        self.markers = []
        self.checkpoints = []
        self.events = []
        self.fail_before = False
        self.hooks = Hooks(self.emit, self.checkpoint, self.before)

    async def emit(self, *args):
        self.events.append(args)

    async def checkpoint(self, transition, state):
        self.checkpoints.append((transition, json.loads(state)))
        assert 'private_fixture_key' not in state and 'upload-private-fixture' not in state

    async def before(self, *args):
        if self.fail_before:
            raise DomainError('access_revoked')
        self.markers.append(args)

    @property
    def checkpoint_json(self):
        return canonical({'adapter': self.checkpoints[-1][1]})


def setup(provider):
    transport = TelegramClient() if provider == 'telegram' else VKTransport()
    adapter = (TelegramAdapter(transport, connection_id='connection', tl=ScriptedTL(), clock=lambda: NOW)
               if provider == 'telegram' else VKAdapter(transport, connection_id='connection', clock=lambda: NOW))
    journal = Journal()
    transport.before_mutation = lambda _: len(journal.markers) == 1 or pytest.fail('effect before durable marker')
    return adapter, transport, journal


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
@pytest.mark.parametrize('scheduled', [False, True])
@pytest.mark.parametrize('images', [0, 1, 2])
async def test_exact_native_publish_and_ordered_uploads(provider, scheduled, images):
    adapter, transport, journal = setup(provider)
    r = request(provider, scheduled_at=timestamp(NOW+3600) if scheduled else None,
                assets=tuple(asset(i+1) for i in range(images)))
    prepared = await adapter.prepare(r, journal.hooks)
    assert transport.effects == 0 and not transport.uploads
    result = await adapter.execute(prepared, journal.hooks)
    assert transport.effects == 1
    assert result.observed == ('provider_scheduled' if scheduled else 'published')
    remote, = result.items
    assert remote.native_target == TARGETS[provider]
    assert remote.text == 'Fixture'
    assert tuple(remote.media_hashes) == tuple(a.sha256 for a in r.assets)
    assert tuple(transport.uploads) == tuple(a.data for a in r.assets)
    assert remote.scheduled_at == r.scheduled_at
    assert remote.media_check == ('provider_binding' if images else 'not_applicable')
    if provider == 'telegram':
        method = 'SendMessageRequest' if not images else 'SendMediaRequest' if images == 1 else 'SendMultiMediaRequest'
        call = next(p for n, p in transport.calls if n == method)
        assert call.schedule_date == (datetime.fromtimestamp(NOW+3600, timezone.utc) if scheduled else None)
        assert len(remote.member_ids) == max(1, images)
        if scheduled:
            assert any(n == 'GetScheduledHistoryRequest' for n, _ in transport.calls)
    else:
        calls = [x for x in transport.calls if x[0] == 'wall.post']
        assert len(calls) == 1
        assert calls[0][1] == 'editor'
        assert calls[0][2].get('publish_date') == (NOW+3600 if scheduled else None)
        if scheduled:
            assert any(n == 'wall.get' and p['filter'] == 'postponed' for n, _, p in transport.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_lost_response_is_readonly_reconcile_never_blind_retry(provider):
    adapter, transport, journal = setup(provider)
    r = request(provider)
    prepared = await adapter.prepare(r, journal.hooks)
    def dropped(_):
        raise OSError('Lost mutation response (fixture)')
    transport.after_mutation = dropped
    with pytest.raises((DomainError, OSError)):
        await adapter.execute(prepared, journal.hooks)
    assert transport.effects == 1
    for _ in range(2):
        with pytest.raises(OutcomeUnknown, match='requires observation'):
            await adapter.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert transport.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_response_checkpoint_recovers_after_adapter_restart(provider):
    adapter, transport, journal = setup(provider)
    r = request(provider, scheduled_at=timestamp(NOW+3600), assets=(asset(), asset(2)))
    prepared = await adapter.prepare(r, journal.hooks)
    transport.after_mutation = lambda _: setattr(transport, 'fail_read', True)
    with pytest.raises((DomainError, OSError)):
        await adapter.execute(prepared, journal.hooks)
    assert transport.effects == 1
    transport.fail_read = False
    restarted = (TelegramAdapter(transport, connection_id='connection', tl=ScriptedTL(), clock=lambda: NOW)
                 if provider == 'telegram' else VKAdapter(transport, connection_id='connection', clock=lambda: NOW))
    observed = await restarted.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert observed.observed == 'provider_scheduled'
    assert tuple(observed.items[0].media_hashes) == (asset().sha256, asset(2).sha256)
    assert transport.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_authorization_revoked_at_marker_prevents_effect(provider):
    adapter, transport, journal = setup(provider)
    r = request(provider, assets=(asset(),))
    prepared = await adapter.prepare(r, journal.hooks)
    journal.fail_before = True
    with pytest.raises(DomainError) as err:
        await adapter.execute(prepared, journal.hooks)
    assert err.value.code == 'access_revoked'
    assert transport.effects == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
@pytest.mark.parametrize('seconds', [-10, 0, 59])
async def test_native_time_guard_never_becomes_now(provider, seconds):
    adapter, transport, journal = setup(provider)
    with pytest.raises(DomainError) as err:
        await adapter.prepare(request(provider, scheduled_at=timestamp(NOW+seconds)), journal.hooks)
    assert err.value.code == 'native_lead_time'
    assert transport.effects == 0 and not transport.uploads


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_native_lifecycle_preserves_identity_and_enforces_external_cas(provider):
    adapter, transport, journal = setup(provider)
    r = request(provider, scheduled_at=timestamp(NOW+3600))
    first = (await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)).items[0]
    for action, text, schedule in [('edit', 'Edited', r.scheduled_at), ('reschedule', 'Edited', timestamp(NOW+7200))]:
        journal.markers.clear()
        r = request(provider, action=action, existing=first, content_json=canonical({'text': text}), scheduled_at=schedule)
        result = await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
        assert result.items[0].native_id == first.native_id
        first = result.items[0]
    journal.markers.clear()
    cancel = request(provider, action='cancel', existing=first)
    result = await adapter.execute(await adapter.prepare(cancel, journal.hooks), journal.hooks)
    assert result.observed == 'cancelled'
    assert transport.effects == 4
    # Observed queue ref is not a new publication; no submit call on cancellation.
    if provider == 'telegram':
        assert len([n for n, _ in transport.calls if n == 'SendMessageRequest']) == 1
    else:
        assert len([n for n, *_ in transport.calls if n == 'wall.post']) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_remote_edit_between_prepare_and_execute_blocks_before_marker(provider):
    adapter, transport, journal = setup(provider)
    r = request(provider)
    first = (await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)).items[0]
    journal.markers.clear()
    edit = request(provider, action='edit', existing=first, content_json=canonical({'text': 'New'}))
    prepared = await adapter.prepare(edit, journal.hooks)
    if provider == 'telegram':
        transport.messages[(101, int(first.native_id))].message = 'Changed by someone else'
    else:
        transport.posts[(-101, int(first.native_id))]['text'] = 'Changed by someone else'
    with pytest.raises(DomainError) as err:
        await adapter.execute(prepared, journal.hooks)
    assert err.value.code == 'remote_revision_conflict'
    assert transport.effects == 1 and not journal.markers


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_native_forward_uses_source_not_copy_or_rewrite(provider):
    adapter, transport, journal = setup(provider)
    if provider == 'telegram':
        transport.messages[(202, 77)] = tg_message(77, 202, 'Source', photo=500)
        source = parse_source('https://t.me/source/77')
    else:
        transport.posts[(-202, 77)] = {'id': 77, 'owner_id': -202, 'text': 'Source', 'date': NOW,
            'post_type': 'post', 'can_repost': 1, 'attachments': [{'type': 'photo', 'photo': {'owner_id': -202, 'id': 500}}]}
        source = parse_source('https://vk.ru/wall-202_77')
    r = request(provider, action='forward', content_json=canonical({'text': ''}), source=source)
    result = await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    assert result.forward_origin_matched
    assert result.items[0].origin == source.canonical_url
    assert transport.effects == 1 and not transport.uploads
    names = [c[0] for c in transport.calls]
    assert ('ForwardMessagesRequest' if provider == 'telegram' else 'wall.repost') in names
    assert ('SendMessageRequest' if provider == 'telegram' else 'wall.post') not in names


@pytest.mark.asyncio
async def test_vk_scheduled_repost_and_missing_media_role_are_explicitly_blocked():
    adapter, transport, journal = setup('vk')
    r = request('vk', action='forward', source=parse_source('https://vk.ru/wall-202_77'), scheduled_at=timestamp(NOW+3600))
    assert (await adapter.inspect(r)).reason == 'vk_scheduled_repost_unsupported'
    transport.denied.add(('media', 'photos.getWallUploadServer'))
    with pytest.raises(DomainError) as err:
        await adapter.prepare(request('vk', assets=(asset(),)), journal.hooks)
    assert err.value.code == 'vk_token_role_not_permitted'
    assert transport.effects == 0 and not transport.uploads


@pytest.mark.asyncio
async def test_telegram_bot_account_cannot_be_mistaken_for_user_schedule():
    adapter, transport, journal = setup('telegram')
    transport.bot = True
    assert (await adapter.inspect(request('telegram'))).reason == 'telegram_account_type_mismatch'
    adapter.account_type = 'mtproto_bot'
    r = request('telegram', account_type='mtproto_bot', scheduled_at=timestamp(NOW+3600))
    assert (await adapter.inspect(r)).reason == 'telegram_bot_native_schedule_unsupported'
    assert transport.effects == 0


@pytest.mark.asyncio
async def test_telegram_protected_or_private_source_is_never_forwarded():
    adapter, transport, journal = setup('telegram')
    transport.entities[202].noforwards = True
    transport.messages[(202, 77)] = tg_message(77, 202)
    r = request('telegram', action='forward', source=parse_source('https://t.me/source/77'))
    with pytest.raises(DomainError) as err:
        await adapter.prepare(r, journal.hooks)
    assert err.value.code == 'protected_content'
    r = replace(r, source=replace(r.source, public_candidate=False, channel=TARGETS['telegram']))
    with pytest.raises(DomainError) as err:
        await adapter.prepare(r, journal.hooks)
    assert err.value.code == 'source_access_denied'
    assert not journal.markers and transport.effects == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_reordered_media_cannot_verify_even_when_count_matches(provider):
    adapter, transport, journal = setup(provider)
    r = request(provider, assets=(asset(), asset(2)))
    def reorder(_):
        if provider == 'telegram':
            messages = list(transport.messages.values())
            messages[0].media, messages[1].media = messages[1].media, messages[0].media
        else:
            next(iter(transport.posts.values()))['attachments'].reverse()
    transport.after_mutation = reorder
    with pytest.raises(OutcomeUnknown) as err:
        await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    assert err.value.code == 'media_identity_or_order_mismatch'


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'vk'])
async def test_live_queue_includes_foreign_items_and_rejects_stale_snapshot_cursor(provider):
    adapter, transport, journal = setup(provider)
    for ident in (1, 2, 3):
        if provider == 'telegram':
            transport.scheduled[(101, ident)] = tg_message(ident, date=datetime.fromtimestamp(NOW+3600, timezone.utc))
        else:
            transport.posts[(-101, ident)] = {'id': ident, 'owner_id': -101, 'text': 'Other author', 'date': NOW+3600, 'post_type': 'postpone'}
    query = ReadRequest('connection', TARGETS[provider], 'scheduled', limit=1)
    first = await adapter.read(query, journal.hooks)
    assert len(first.items) == 1 and first.cursor
    if provider == 'telegram':
        transport.scheduled[(101, 3)].message = 'External edit'
    else:
        transport.posts[(-101, 3)]['text'] = 'External edit'
    with pytest.raises(DomainError) as err:
        await adapter.read(replace(query, cursor=first.cursor), journal.hooks)
    assert err.value.code == 'provider_cursor_stale'
    assert transport.effects == 0


@pytest.mark.parametrize('url', ['http://pu.vk.com/upload', 'https://vk.com.attacker.invalid/u', 'https://127.0.0.1/u',
                                'https://pu.vk.com:8443/u', 'https://u:p@pu.vk.com/u', 'https://pu.vk.com/u#fragment',
                                'https://pu.vk.com\\@localhost/u'])
def test_vk_upload_url_is_closed(url):
    with pytest.raises(DomainError):
        validated_url(url)


def test_vk_bounded_compression_and_role_constraints():
    assert decoded_json(gzip.compress(b'{"response":1}'), 'gzip') == {'response': 1}
    with pytest.raises(DomainError):
        decoded_json(gzip.compress(b' '*(2*1024*1024)), 'gzip')
    group = VKHTTPTransport(tokens={'media': VKToken('fake-not-a-real-token', 'group', 101),
                                   'editor': VKToken('fake-not-a-real-token', 'group', 101)})
    assert not group.permits('media', 'photos.getWallUploadServer', group_id=101)
    assert not group.permits('editor', 'wall.post', group_id=202)
    assert not group.permits('editor', 'wall.post', group_id=101, scheduled=True)
    assert group.permits('editor', 'wall.post', group_id=101)
