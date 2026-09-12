from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from adapters.port import ReadRequest
from adapters.telegram import TelegramAdapter
from social_operations.domain import DomainError
from .scripted import ScriptedTL, obj
from .test_native_adapters import NOW, Journal, asset, request

TARGET = '-1000000000101'
TOPIC = '3'
OTHER_TOPIC = '9'


def forum_channel(ident=101, *, left=False, kicked=False):
    return obj('Channel', id=ident, broadcast=False, megagroup=True, forum=True,
               username='forum', noforwards=False, left=left, kicked=kicked)


def topic_message(ident, text='', *, topic=None, media=None, group=None):
    reply = (obj('MessageReplyHeader', forum_topic=True, reply_to_top_id=int(topic),
                 reply_to_msg_id=int(topic)) if topic else None)
    return obj('Message', id=ident, message=text, peer_id=obj('PeerChannel', channel_id=101),
               date=datetime(2026, 9, 12, 12, tzinfo=timezone.utc), grouped_id=group,
               media=media, fwd_from=None, views=0, forwards=0, noforwards=False,
               entities=[], reply_to=reply)


def photo_media(ident):
    return obj('MessageMediaPhoto', photo=obj('Photo', id=ident, access_hash=123, file_reference=b'p'))


def document_media(ident, mime='image/png', size=100):
    return obj('MessageMediaDocument', document=obj('Document', id=ident, access_hash=456,
               file_reference=b'd', mime_type=mime, size=size, attributes=[]))


class ForumTelegramClient:
    MUTATIONS = {'SendMessageRequest', 'SendMediaRequest', 'SendMultiMediaRequest',
                 'EditMessageRequest', 'DeleteMessagesRequest'}

    def __init__(self):
        self.calls, self.effects, self.uploads = [], 0, []
        self.entity = forum_channel()
        self.permissions = NS(is_creator=False, is_admin=False, has_default_permissions=True,
                              is_banned=False, has_left=False,
                              edit_messages=False, delete_messages=False)
        self.messages = {(101, 3): topic_message(3, 'Topic root'),
                         (101, 9): topic_message(9, 'Other root')}
        self.next_id, self.next_media = 100, 1000
        self.provider_bytes = {}
        self.before_mutation = None
        self.after_mutation = None

    async def get_me(self):
        return obj('User', id=5, bot=False)

    async def get_permissions(self, entity, me):
        return self.permissions

    async def get_entity(self, target):
        assert int(target) == int(TARGET)
        return self.entity

    async def get_messages(self, entity, *, ids):
        if isinstance(ids, list):
            return [copy.deepcopy(self.messages.get((101, i))) for i in ids]
        return copy.deepcopy(self.messages.get((101, ids)))

    async def upload_file(self, stream, *, file_size, file_name):
        data = stream.read()
        assert len(data) == file_size
        self.uploads.append(data)
        return obj('InputFile', id=len(self.uploads), parts=1, name=file_name, md5_checksum='fixture')

    async def download_media(self, message, file=None):
        media = message.media
        if getattr(media, 'photo', None):
            ref = ('photo', media.photo.id)
        else:
            ref = ('document', media.document.id)
        return self.provider_bytes[ref]

    def _stored_media(self, compiled):
        name = type(compiled).__name__
        if name == 'InputMediaPhoto':
            ident = compiled.id.id
            return photo_media(ident), ('photo', ident)
        if name == 'InputMediaDocument':
            ident = compiled.id.id
            return document_media(ident), ('document', ident)
        raise AssertionError(name)

    async def __call__(self, req):
        name = type(req).__name__
        self.calls.append((name, req))
        if name == 'GetForumTopicsByIDRequest':
            topics = [NS(id=value) for value in req.topics if (101, value) in self.messages]
            return NS(topics=topics, messages=[], chats=[], users=[], count=len(topics), pts=0)
        if name == 'GetRepliesRequest':
            rows = [m for (peer, _), m in self.messages.items()
                    if peer == 101 and getattr(getattr(m, 'reply_to', None), 'forum_topic', False)
                    and (getattr(m.reply_to, 'reply_to_top_id', None) or getattr(m.reply_to, 'reply_to_msg_id', None)) == req.msg_id
                    and (not req.offset_id or m.id < req.offset_id)]
            rows.sort(key=lambda m: m.id, reverse=True)
            return NS(messages=copy.deepcopy(rows[:req.limit]))
        if name == 'UploadMediaRequest':
            self.next_media += 1
            data = self.uploads[req.media.file.id - 1]
            if type(req.media).__name__ == 'InputMediaUploadedDocument':
                self.provider_bytes[('document', self.next_media)] = data
                return document_media(self.next_media, req.media.mime_type)
            self.provider_bytes[('photo', self.next_media)] = data
            return photo_media(self.next_media)
        if name == 'GetHistoryRequest':
            rows = [m for (peer, _), m in self.messages.items() if peer == 101 and (not req.offset_id or m.id < req.offset_id)]
            rows.sort(key=lambda m: m.id, reverse=True)
            return NS(messages=copy.deepcopy(rows[:req.limit]))
        if name not in self.MUTATIONS:
            raise AssertionError('Unexpected native call: ' + name)
        if self.before_mutation:
            self.before_mutation(name)
        self.effects += 1
        updates = []
        if name in {'SendMessageRequest', 'SendMediaRequest', 'SendMultiMediaRequest'}:
            target_reply = getattr(req, 'reply_to', None)
            topic = str(target_reply.top_msg_id) if target_reply else None
            if name == 'SendMultiMediaRequest':
                entries = [(x.random_id, x.message, x.entities, x.media) for x in req.multi_media]
            elif name == 'SendMediaRequest':
                entries = [(req.random_id, req.message, req.entities, req.media)]
            else:
                entries = [(req.random_id, req.message, req.entities, None)]
            grouped = self.next_id + 1 if len(entries) > 1 else None
            for random_id, text, entities, compiled in entries:
                self.next_id += 1
                native_media = None
                if compiled is not None:
                    native_media, _ = self._stored_media(compiled)
                msg = topic_message(self.next_id, text, topic=topic, media=native_media, group=grouped)
                msg.entities = copy.deepcopy(entities)
                self.messages[(101, msg.id)] = msg
                updates.extend([obj('UpdateMessageID', random_id=random_id, id=msg.id),
                                obj('UpdateNewChannelMessage', message=copy.deepcopy(msg))])
        elif name == 'EditMessageRequest':
            msg = self.messages[(101, req.id)]
            msg.message = req.message
            msg.entities = copy.deepcopy(req.entities)
        elif name == 'DeleteMessagesRequest':
            for ident in req.id:
                self.messages.pop((101, ident), None)
        if self.after_mutation:
            self.after_mutation(name)
        return NS(updates=updates)


def setup():
    client = ForumTelegramClient()
    adapter = TelegramAdapter(client, connection_id='connection', tl=ScriptedTL(), clock=lambda: NOW)
    journal = Journal()
    client.before_mutation = lambda _: len(journal.markers) == 1 or pytest.fail('effect before durable marker')
    return adapter, client, journal


def topic_request(*, assets=(), action='publish', existing=None):
    return request('telegram', action=action, assets=assets, existing=existing, topic_root_id=TOPIC)


@pytest.mark.asyncio
async def test_thread_read_isolates_interleaved_topics_and_paginates():
    adapter, client, journal = setup()
    client.messages[(101, 20)] = topic_message(20, 'a', topic=TOPIC)
    client.messages[(101, 19)] = topic_message(19, 'other', topic=OTHER_TOPIC)
    client.messages[(101, 18)] = topic_message(18, 'b', topic=TOPIC)
    first = await adapter.read(ReadRequest('connection', TARGET, 'thread', 1, topic_root_id=TOPIC), journal.hooks)
    assert [i.text for i in first.items] == ['a']
    assert first.cursor
    second = await adapter.read(ReadRequest('connection', TARGET, 'thread', 1, first.cursor, topic_root_id=TOPIC), journal.hooks)
    assert [i.text for i in second.items] == ['b']
    assert all(i.reply_to_native_id == TOPIC for i in first.items + second.items)
    assert all(getattr(call, 'msg_id', None) == 3 for name, call in client.calls if name == 'GetRepliesRequest')


@pytest.mark.asyncio
async def test_topic_text_publish_uses_native_reply_target_and_reads_back_exact_topic():
    adapter, client, journal = setup()
    r = topic_request()
    prepared = await adapter.prepare(r, journal.hooks)
    result = await adapter.execute(prepared, journal.hooks)
    remote, = result.items
    assert result.observed == 'published' and remote.reply_to_native_id == TOPIC
    call = next(req for name, req in client.calls if name == 'SendMessageRequest')
    assert call.reply_to.reply_to_msg_id == 3 and call.reply_to.top_msg_id == 3
    assert client.effects == 1


@pytest.mark.asyncio
async def test_photo_and_image_document_are_distinct_and_downloadable():
    seen = []
    for original, role, prefix in ((asset(1), 'image', 'photo:'), (asset(2), 'document', 'document:')):
        adapter, client, journal = setup()
        media = replace(original, role=role)
        r = topic_request(assets=(media,))
        result = await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
        remote, = result.items
        assert remote.provider_media[0].startswith(prefix)
        page = await adapter.read(ReadRequest('connection', TARGET, 'item', 25, native_item=remote.native_id,
                                              namespace='published'), journal.hooks)
        item, = page.items
        assert [d.media_kind for d in page.downloads] == [role == 'document' and 'document' or 'photo']
        assert [d.data for d in page.downloads] == [media.data]
        assert [e.sha256 for e in item.observed_media] == [media.sha256]
        seen.append(remote)
    assert seen[0].provider_media[0].startswith('photo:') and seen[1].provider_media[0].startswith('document:')


@pytest.mark.asyncio
async def test_multiple_image_documents_use_one_album_and_mixed_album_is_blocked():
    adapter, client, journal = setup()
    docs = (replace(asset(3), role='document'), replace(asset(4), role='document'))
    result = await adapter.execute(await adapter.prepare(topic_request(assets=docs), journal.hooks), journal.hooks)
    remote, = result.items
    assert len(remote.member_ids) == 2 and all(ref.startswith('document:') for ref in remote.provider_media)
    mixed = topic_request(assets=(asset(5), replace(asset(6), role='document')))
    cap = await adapter.inspect(mixed)
    assert cap.status == 'unsupported' and cap.reason == 'telegram_mixed_media_album_needs_review'


@pytest.mark.asyncio
async def test_regular_member_allowed_banned_restricted_and_left_denied():
    adapter, client, journal = setup()
    assert (await adapter.inspect(topic_request())).status == 'supported'
    # Telethon represents ChannelParticipantBanned for both bans and restricted participants.
    client.permissions = replace_ns(client.permissions, is_banned=True, has_default_permissions=False)
    cap = await adapter.inspect(topic_request())
    assert cap.status == 'unsupported' and cap.reason == 'provider_access_denied'
    client.permissions = replace_ns(client.permissions, is_banned=False, has_default_permissions=True, has_left=True)
    cap = await adapter.inspect(topic_request())
    assert cap.status == 'unsupported' and cap.reason == 'provider_access_denied'
    client.permissions = replace_ns(client.permissions, has_left=False, has_default_permissions=False)
    cap = await adapter.inspect(topic_request())
    assert cap.status == 'unsupported' and cap.reason == 'provider_access_denied'
    client.permissions = replace_ns(client.permissions, has_default_permissions=True)
    client.entity.default_banned_rights = NS(send_messages=True)
    cap = await adapter.inspect(topic_request())
    assert cap.status == 'unsupported' and cap.reason == 'provider_access_denied'
    client.entity.default_banned_rights = NS(send_messages=False)
    client.entity.left = True
    cap = await adapter.inspect(topic_request())
    assert cap.status == 'unsupported' and cap.reason == 'provider_access_denied'


def replace_ns(value, **changes):
    data = vars(value).copy()
    data.update(changes)
    return NS(**data)


@pytest.mark.asyncio
async def test_lost_response_reconcile_does_not_duplicate_topic_send():
    adapter, client, journal = setup()
    r = topic_request()
    prepared = await adapter.prepare(r, journal.hooks)
    client.after_mutation = lambda _: (_ for _ in ()).throw(OSError('lost response'))
    with pytest.raises(DomainError, match='telegram rpc failed'):
        await adapter.execute(prepared, journal.hooks)
    assert client.effects == 1
    client.after_mutation = None
    # The last durable checkpoint before the response contains stable random IDs but no native IDs,
    # so core correctly refuses to retry blindly. A provider response checkpoint is needed to reconcile.
    from social_operations.domain import OutcomeUnknown
    with pytest.raises(OutcomeUnknown):
        await adapter.reconcile(r, journal.checkpoint_json, journal.hooks)
    assert client.effects == 1


def test_document_role_is_telegram_opt_in_not_global_native_default():
    from adapters.native import verify_assets
    document = replace(asset(7), role='document')
    with pytest.raises(DomainError):
        verify_assets(request('vk', assets=(document,)))
    verify_assets(request('telegram', assets=(document,)), allow_document=True)

@pytest.mark.asyncio
async def test_non_image_document_does_not_break_thread_text_read():
    adapter, client, journal = setup()
    client.messages[(101, 30)] = topic_message(30, 'PDF metadata only', topic=TOPIC,
                                               media=document_media(3000, 'application/pdf'))
    client.provider_bytes[('document', 3000)] = b'%PDF-1.7 fixture'
    page = await adapter.read(ReadRequest('connection', TARGET, 'thread', 10, topic_root_id=TOPIC), journal.hooks)
    item, = page.items
    assert item.text == 'PDF metadata only'
    assert item.provider_media == ('document:3000',)
    assert item.observed_media == () and page.downloads == ()
