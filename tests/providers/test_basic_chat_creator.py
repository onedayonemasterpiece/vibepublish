"""Offline basic-chat creator capability; no sessions or live Telegram calls."""
from datetime import datetime, timezone

import pytest

from adapters.port import RemoteItem
from adapters.telegram import TelegramAdapter, peer_key
from social_operations.domain import DomainError, parse_source, timestamp
from tests.providers.scripted import ScriptedTL, TelegramClient, obj
from tests.providers.test_native_adapters import Journal, NOW, asset, request

CHAT_ID = 303
TARGET = '-303'


def basic_chat(**changes):
    values = dict(id=CHAT_ID, creator=True, left=False, kicked=False,
                  deactivated=False, migrated_to=None)
    values.update(changes)
    return obj('Chat', **values)


class BasicChatClient(TelegramClient):
    """Extend the channel-only fixture with native basic-chat update peers."""
    async def __call__(self, req):
        result = await super().__call__(req)
        if getattr(getattr(req, 'peer', None), 'id', None) == CHAT_ID:
            updates = []
            for update in getattr(result, 'updates', []):
                if type(update).__name__ == 'UpdateNewChannelMessage':
                    update.message.peer_id = obj('PeerChat', chat_id=CHAT_ID)
                    update = obj('UpdateNewMessage', message=update.message)
                updates.append(update)
            if hasattr(result, 'updates'):
                result.updates = updates
        return result


def setup(entity=None, *, account_type='mtproto_user', bot=False):
    client = BasicChatClient()
    client.bot = bot
    client.entities[CHAT_ID] = entity if entity is not None else basic_chat()
    adapter = TelegramAdapter(client, connection_id='connection', account_type=account_type,
                              tl=ScriptedTL(), clock=lambda: NOW)
    journal = Journal()
    client.before_mutation = lambda _: len(journal.markers) == 1 or pytest.fail('effect before marker')
    return adapter, client, journal


def publish(**changes):
    return request('telegram', native_target=TARGET, **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize('image_count', [0, 1, 2])
async def test_creator_preview_then_publish_exact_basic_chat_peer(image_count):
    adapter, client, journal = setup()
    r = publish(assets=tuple(asset(i + 1) for i in range(image_count)))
    capability = await adapter.inspect(r)
    assert capability.status == 'supported'
    assert capability.evidence == 'provider_read_preflight_only'
    prepared = await adapter.prepare(r, journal.hooks)
    assert client.effects == 0 and client.uploads == [] and journal.markers == []
    result = await adapter.execute(prepared, journal.hooks)
    assert result.observed == 'published'
    item, = result.items
    assert item.native_target == TARGET and item.namespace == 'published'
    assert item.text == 'Fixture' and item.scheduled_at is None
    assert item.media_hashes == tuple(a.sha256 for a in r.assets)
    assert len(item.member_ids) == max(1, image_count)
    assert len(journal.markers) == 1 and client.effects == 1
    assert not any(name == 'get_permissions' for name, _ in client.calls)
    for ident in item.member_ids:
        assert peer_key(client.messages[(CHAT_ID, int(ident))].peer_id) == TARGET
    send_name = ('SendMessageRequest', 'SendMediaRequest', 'SendMultiMediaRequest')[image_count]
    sends = [values for name, values in client.calls if name == send_name]
    assert len(sends) == 1 and sends[0].peer.id == CHAT_ID and sends[0].schedule_date is None


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'creator': False}, {'creator': None}, {'creator': 1}, {'creator': 'true'},
    {'deactivated': True}, {'migrated_to': obj('InputChannel', channel_id=404)},
])
async def test_only_explicit_active_unmigrated_creator_is_supported(changes):
    adapter, client, journal = setup(basic_chat(**changes))
    capability = await adapter.inspect(publish())
    assert capability.status == 'unsupported'
    assert capability.reason == 'telegram_group_mutations_needs_review'
    with pytest.raises(DomainError, match='telegram group mutations needs review'):
        await adapter.prepare(publish(), journal.hooks)
    assert client.effects == 0 and client.uploads == []


@pytest.mark.asyncio
@pytest.mark.parametrize('flag', ['left', 'kicked'])
async def test_creator_cannot_publish_after_leaving_or_removal(flag):
    adapter, client, _ = setup(basic_chat(**{flag: True}))
    assert (await adapter.inspect(publish())).reason == 'provider_access_denied'
    assert client.effects == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['ChatEmpty', 'ChatForbidden', 'Channel'])
async def test_chat_placeholders_and_megagroup_creators_stay_gated(kind):
    entity = (obj(kind, id=CHAT_ID, creator=True) if kind != 'Channel'
              else obj('Channel', id=CHAT_ID, broadcast=False, megagroup=True, creator=True))
    adapter, client, _ = setup(entity)
    r = publish() if kind != 'Channel' else publish_target_channel()
    assert (await adapter.inspect(r)).reason == 'telegram_group_mutations_needs_review'
    assert client.effects == 0


def publish_target_channel():
    return request('telegram', native_target=str(-1_000_000_000_000 - CHAT_ID))


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['forward', 'edit', 'delete', 'cancel', 'reschedule'])
async def test_other_group_actions_remain_gated(action):
    adapter, client, _ = setup()
    existing = RemoteItem('7', 'published', 'old', 'hash', timestamp(NOW), native_target=TARGET)
    r = publish(action=action, existing=existing if action != 'forward' else None)
    assert (await adapter.inspect(r)).reason == 'telegram_group_mutations_needs_review'
    assert client.effects == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [
    {'scheduled_at': timestamp(NOW + 3600)},
    {'existing': RemoteItem('7', 'published', 'old', 'hash', timestamp(NOW), native_target=TARGET)},
    {'source': parse_source('https://t.me/source/7')},
])
async def test_publish_cannot_smuggle_schedule_existing_item_or_forward_source(changes):
    adapter, client, _ = setup()
    assert (await adapter.inspect(publish(**changes))).reason == 'telegram_group_mutations_needs_review'
    assert client.effects == 0


@pytest.mark.asyncio
async def test_bot_creator_and_user_bot_mismatch_stay_gated():
    adapter, client, _ = setup(account_type='mtproto_bot', bot=True)
    assert (await adapter.inspect(publish(account_type='mtproto_bot'))).reason == 'telegram_group_mutations_needs_review'
    adapter.account_type = 'mtproto_user'
    assert (await adapter.inspect(publish())).reason == 'telegram_account_type_mismatch'
    assert client.effects == 0


@pytest.mark.asyncio
async def test_creator_rights_are_rechecked_before_upload_or_effect():
    adapter, client, journal = setup()
    prepared = await adapter.prepare(publish(assets=(asset(),)), journal.hooks)
    client.entities[CHAT_ID].creator = False
    with pytest.raises(DomainError, match='telegram group mutations needs review'):
        await adapter.execute(prepared, journal.hooks)
    assert client.effects == 0 and client.uploads == [] and journal.markers == []


@pytest.mark.asyncio
async def test_actual_telethon_chat_constructor_offline():
    types = pytest.importorskip('telethon.tl.types')
    entity = types.Chat(id=CHAT_ID, title='Offline fixture', photo=types.ChatPhotoEmpty(),
                        participants_count=1, date=datetime.now(timezone.utc), version=1, creator=True)
    adapter, client, _ = setup(entity)
    assert peer_key(entity) == TARGET
    assert (await adapter.inspect(publish())).status == 'supported'
    assert client.effects == 0
