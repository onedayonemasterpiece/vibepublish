"""Real Telethon objects/resolve/TL wire on an OFFLINE provider-state double.

Exercises the unchanged production adapter; no authenticated TelegramClient or
network, no claim of provider acceptance. All RPCs and responses are TL-encoded.
"""
from dataclasses import replace
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest
from telethon import functions as f, types as t, utils

from adapters.telegram import TelegramAdapter
from scripts.verify.telegram_wire import ENTITY_SPECS, TEXT, roundtrip
from social_operations.domain import DomainError, OutcomeUnknown, canonical, timestamp
from tests.providers.test_native_adapters import NOW, TARGETS, Journal, asset, request

DATE = datetime.fromtimestamp(NOW, timezone.utc)


class NativeTransport:
    """Small state double with real TL boundary on BOTH sides of each RPC."""
    def __init__(self, journal):
        self.journal = journal
        self.peer = t.Channel(id=101, title='Offline fixture', photo=t.ChatPhotoEmpty(),
                             date=DATE, broadcast=True, creator=True, access_hash=101)
        self.user = t.User(id=1, premium=True)
        self.messages, self.calls, self.uploads = {}, [], []
        self.scheduled = set()
        self.effects = 0
        self.after_effect = None
        self.fail_read = False
        self.docs = [t.Document(id=int(e['document_id']), access_hash=4, file_reference=b'fixture',
            date=DATE, mime_type='image/png', size=1, dc_id=1,
            attributes=[t.DocumentAttributeCustomEmoji(alt=alt,
                stickerset=t.InputStickerSetID(id=99, access_hash=7))])
            for e, alt in zip(ENTITY_SPECS, ['❤️', '👩🏽\u200d💻', '🇷🇺'], strict=True)]

    async def get_entity(self, target):
        assert str(target) == TARGETS['telegram']
        return roundtrip(self.peer)

    async def get_input_entity(self, value):
        return utils.get_input_peer(value)

    async def get_me(self):
        return roundtrip(self.user)

    async def get_permissions(self, entity, user):
        assert entity.id == 101 and user.id == 1
        return SimpleNamespace(is_creator=True)

    async def get_messages(self, entity, *, ids):
        assert entity.id == 101
        if self.fail_read:
            raise OSError('offline read interruption')
        def one(i):
            return roundtrip(self.messages[i]) if i in self.messages and i not in self.scheduled else None
        return [one(i) for i in ids] if isinstance(ids, list) else one(ids)

    async def upload_file(self, stream, *, file_size, file_name):
        data = stream.read()
        assert len(data) == file_size
        self.uploads.append(data)
        return t.InputFile(id=len(self.uploads), parts=1, name=file_name, md5_checksum='0'*32)

    @staticmethod
    def photo(ident):
        return t.Photo(id=ident, access_hash=2, file_reference=b'fixture', date=DATE, sizes=[], dc_id=1)

    async def __call__(self, req):
        await req.resolve(self, utils)  # The actual Telethon resolution path.
        wire = roundtrip(req)
        self.calls.append(wire)
        for field in ('peer', 'to_peer'):
            value = getattr(wire, field, None)
            if value is not None:
                assert isinstance(value, t.InputPeerChannel) and value.channel_id == 101
        if isinstance(wire, f.help.GetAppConfigRequest):
            return roundtrip(t.help.AppConfig(hash=0, config=t.JsonObject(value=[
                t.JsonObjectValue(key='message_animated_emoji_max', value=t.JsonNumber(value=100))])))
        if isinstance(wire, f.messages.GetCustomEmojiDocumentsRequest):
            return [roundtrip(d) for d in self.docs if d.id in wire.document_id]
        if isinstance(wire, f.messages.GetScheduledHistoryRequest):
            if self.fail_read:
                raise OSError('offline read interruption')
            return roundtrip(t.messages.Messages(messages=[self.messages[i] for i in sorted(self.scheduled, reverse=True)], topics=[], chats=[], users=[]))
        if isinstance(wire, f.messages.UploadMediaRequest):
            return roundtrip(t.MessageMediaPhoto(photo=self.photo(1000+wire.media.file.id)))
        assert self.journal.markers, 'Effect attempted without durable marker'
        self.effects += 1
        updates = []
        if isinstance(wire, (f.messages.SendMessageRequest, f.messages.SendMediaRequest, f.messages.SendMultiMediaRequest)):
            rows = wire.multi_media if isinstance(wire, f.messages.SendMultiMediaRequest) else [wire]
            for row in rows:
                ident = max(self.messages, default=10)+1
                media = getattr(row, 'media', None)
                self.messages[ident] = t.Message(id=ident, peer_id=t.PeerChannel(channel_id=101),
                    date=wire.schedule_date or DATE, message=row.message, entities=row.entities,
                    media=t.MessageMediaPhoto(photo=self.photo(media.id.id)) if media else None,
                    grouped_id=80 if len(rows)>1 else None)
                if wire.schedule_date:
                    self.scheduled.add(ident)
                updates.append(t.UpdateMessageID(id=ident, random_id=row.random_id))
        elif isinstance(wire, f.messages.EditMessageRequest):
            message = self.messages[wire.id]
            message.message, message.entities = wire.message, wire.entities
            if wire.schedule_date:
                message.date = wire.schedule_date
            if wire.media is not None:
                message.media = t.MessageMediaPhoto(photo=self.photo(wire.media.id.id))
        elif isinstance(wire, (f.messages.DeleteScheduledMessagesRequest, f.channels.DeleteMessagesRequest)):
            for ident in wire.id:
                self.messages.pop(ident, None)
                self.scheduled.discard(ident)
            if isinstance(wire, f.messages.DeleteScheduledMessagesRequest):
                updates.append(t.UpdateDeleteScheduledMessages(peer=t.PeerChannel(channel_id=101), messages=wire.id))
        else:
            raise AssertionError('Unexpected fixture RPC: '+type(wire).__name__)
        if self.after_effect:
            self.after_effect(self)
        return roundtrip(t.Updates(updates=updates, users=[], chats=[], date=DATE, seq=self.effects))


def setup(**changes):
    journal = Journal()
    client = NativeTransport(journal)
    adapter = TelegramAdapter(client, connection_id='connection', clock=lambda: NOW)
    r = request('telegram', content_json=canonical(dict(text=TEXT, format='telegram_entities', entities=list(ENTITY_SPECS))), **changes)
    return adapter, client, journal, r


@pytest.mark.asyncio
@pytest.mark.parametrize('scheduled', [False, True])
@pytest.mark.parametrize('images', [0, 1, 2])
async def test_real_tl_publish_and_exact_native_entities(scheduled, images):
    adapter, client, journal, r = setup(assets=tuple(asset(i+1) for i in range(images)),
        scheduled_at=timestamp(NOW+3600) if scheduled else None)
    prepared = await adapter.prepare(r, journal.hooks)
    assert not client.effects and not client.uploads
    result = await adapter.execute(prepared, journal.hooks)
    item, = result.items
    assert client.effects == 1 and len(journal.markers) == 1
    assert item.text == TEXT and json.loads(item.entities_json) == list(ENTITY_SPECS)
    assert item.scheduled_at == r.scheduled_at
    assert item.media_hashes == tuple(a.sha256 for a in r.assets)
    assert client.uploads == [a.data for a in r.assets]
    assert len(item.member_ids) == max(1, images)
    assert result.observed == ('provider_scheduled' if scheduled else 'published')


@pytest.mark.asyncio
async def test_real_tl_edit_reschedule_cancel_preserves_media():
    adapter, client, journal, r = setup(assets=(asset(),), scheduled_at=timestamp(NOW+3600))
    previous, = (await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)).items
    for action, at in [('edit', NOW+3600), ('reschedule', NOW+7200)]:
        r = replace(r, action=action, existing=previous, scheduled_at=timestamp(at))
        previous, = (await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)).items
        assert previous.provider_media == ('photo:1001',)
        assert previous.media_hashes == (asset().sha256,)
        assert previous.scheduled_at == timestamp(at)
        assert json.loads(previous.entities_json) == list(ENTITY_SPECS)
    r = replace(r, action='cancel', existing=previous)
    result = await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    assert result.observed == 'cancelled' and client.effects == 4
    assert not client.messages and len(client.uploads) == 1


@pytest.mark.asyncio
async def test_real_tl_media_edit_replaces_exact_photo():
    adapter, client, journal, r = setup(assets=(asset(),))
    previous, = (await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)).items
    r = replace(r, action='edit', existing=previous, assets=(asset(2),))
    current, = (await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)).items
    assert current.native_id == previous.native_id
    assert current.provider_media == ('photo:1002',) and current.media_hashes == (asset(2).sha256,)
    assert json.loads(current.entities_json) == list(ENTITY_SPECS)


@pytest.mark.asyncio
async def test_native_readback_wrong_emoji_is_not_success_or_resend():
    adapter, client, journal, r = setup()
    prepared = await adapter.prepare(r, journal.hooks)
    def corrupt(transport):
        next(iter(transport.messages.values())).entities[0].document_id += 1
    client.after_effect = corrupt
    with pytest.raises(OutcomeUnknown) as failure:
        await adapter.execute(prepared, journal.hooks)
    assert failure.value.code == 'telegram_entities_readback_mismatch'
    for _ in range(2):
        with pytest.raises(OutcomeUnknown) as failure:
            await adapter.reconcile(r, journal.checkpoint_json, journal.hooks)
        assert failure.value.code == 'telegram_entities_readback_mismatch'
    assert client.effects == 1


@pytest.mark.asyncio
async def test_native_response_checkpoint_recovery_is_read_only():
    adapter, client, journal, r = setup(scheduled_at=timestamp(NOW+3600))
    prepared = await adapter.prepare(r, journal.hooks)
    client.after_effect = lambda c: setattr(c, 'fail_read', True)
    with pytest.raises(DomainError):
        await adapter.execute(prepared, journal.hooks)
    client.fail_read = False
    restarted = TelegramAdapter(client, connection_id='connection', clock=lambda: NOW)
    result = await restarted.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert result.observed == 'provider_scheduled' and client.effects == 1


@pytest.mark.asyncio
async def test_native_marker_refusal_stops_before_send():
    adapter, client, journal, r = setup()
    prepared = await adapter.prepare(r, journal.hooks)
    journal.fail_before = True
    with pytest.raises(DomainError) as failure:
        await adapter.execute(prepared, journal.hooks)
    assert failure.value.code == 'access_revoked'
    assert client.effects == 0
