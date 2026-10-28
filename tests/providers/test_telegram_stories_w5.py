"""W5 Telegram channel Stories: offline MTProto-shaped requests only, never a live client."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from adapters.port import Asset, ReadRequest
from adapters.telegram import TelegramAdapter
from adapters.telegram_resilient import ResilientTelegramAdapter
from adapters.vk import VKAdapter
from social_operations.domain import DomainError, OutcomeUnknown, canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import ScriptedTL, TelegramClient, VKTransport, channel, obj
from tests.providers.test_native_adapters import NOW, Journal, asset, request


class BoostsRequiredError(Exception):
    pass


class StoryClient(TelegramClient):
    """Emulates only the Stories RPC/response contract, including random_id deduplication."""

    def __init__(self):
        super().__init__()
        self.story_quota = 2
        self.boosts_required = False
        self.stories = {}
        self.random_stories = {}
        self.next_story = 500
        self.story_sends = 0

    async def __call__(self, req):
        name = type(req).__name__
        if name == 'CanSendStoryRequest':
            self.calls.append((name, req))
            if self.boosts_required:
                raise BoostsRequiredError('fixture channels need boosts')
            return NS(count_remains=self.story_quota)
        if name == 'UploadMediaRequest' and type(req.media).__name__ == 'InputMediaUploadedDocument':
            self.calls.append((name, req))
            self.next_photo += 1
            return obj('MessageMediaDocument', document=obj('Document', id=self.next_photo,
                       access_hash=123, file_reference=b'fixture'))
        if name == 'GetStoriesByIDRequest':
            self.calls.append((name, req))
            return NS(stories=[self.stories[(req.peer.id, i)] for i in req.id
                               if (req.peer.id, i) in self.stories])
        if name == 'SendStoryRequest':
            self.calls.append((name, req))
            if self.before_mutation:
                self.before_mutation(name)
            if req.random_id not in self.random_stories:
                self.next_story += 1
                media_id = req.media.id.id
                if type(req.media).__name__ == 'InputMediaPhoto':
                    media = obj('MessageMediaPhoto', photo=obj('Photo', id=media_id))
                else:
                    media = obj('MessageMediaDocument', document=obj('Document', id=media_id))
                item = obj('StoryItem', id=self.next_story, media=media, caption=req.caption,
                           entities=req.entities)
                self.stories[(req.peer.id, self.next_story)] = item
                self.random_stories[req.random_id] = self.next_story
                self.story_sends += 1
                self.effects += 1
                self.story_quota -= 1
            if self.after_mutation:
                self.after_mutation(name)
            return NS(updates=[obj('UpdateStoryID', id=self.random_stories[req.random_id],
                                   random_id=req.random_id)])
        if name == 'DeleteStoriesRequest':
            self.calls.append((name, req))
            if self.before_mutation:
                self.before_mutation(name)
            for ident in req.id:
                self.stories.pop((req.peer.id, ident), None)
            self.effects += 1
            return list(req.id)
        return await super().__call__(req)


def test_telethon_144_compiles_story_requests_without_network():
    pytest.importorskip('telethon')
    from adapters.telegram import TelethonTypes
    tl = TelethonTypes()
    peer = tl.types.InputPeerChannel(channel_id=101, access_hash=123)
    media = tl.type('InputMediaPhoto', id=tl.type('InputPhoto', id=5,
                    access_hash=12, file_reference=b'fixture'))
    assert type(tl.request('story_can_send', peer=peer)).__name__ == 'CanSendStoryRequest'
    assert type(tl.request('story_by_id', peer=peer, id=[501])).__name__ == 'GetStoriesByIDRequest'
    assert type(tl.request('story_delete', peer=peer, id=[501])).__name__ == 'DeleteStoriesRequest'
    sent = tl.request('story_send', peer=peer, media=media, random_id=99,
                      privacy_rules=[tl.type('InputPrivacyValueAllowAll')],
                      period=86400, caption='Fixture', entities=[])
    assert type(sent).__name__ == 'SendStoryRequest' and sent.random_id == 99
    assert type(tl.types.UpdateStoryID(id=501, random_id=99)).__name__ == 'UpdateStoryID'


def build(adapter_cls=TelegramAdapter):
    client = StoryClient()
    adapter = adapter_cls(client, connection_id='connection', tl=ScriptedTL(), clock=lambda: NOW)
    return client, adapter, Journal()


def story_request(*, text='Story caption', assets=None, **kwargs):
    return request('telegram', surface='story',
                   content_json=canonical({'text': text}),
                   assets=(asset(),) if assets is None else assets, **kwargs)


@pytest.mark.asyncio
async def test_photo_caption_channel_privacy_24h_exact_readback_and_delete():
    client, adapter, journal = build()
    r = story_request()
    prepared = await adapter.prepare(r, journal.hooks)
    assert not client.effects and not client.uploads
    assert any(name == 'CanSendStoryRequest' for name, _ in client.calls)
    client.before_mutation = lambda _: (len(journal.markers) == 1 and
                                        len(journal.checkpoints) == 1) or pytest.fail('missing durable send marker')
    published = await adapter.execute(prepared, journal.hooks)
    assert published.observed == 'published'
    item, = published.items
    assert item.namespace == 'story' and item.native_id == '501'
    assert item.url == 'https://t.me/target/s/501'
    assert item.text == 'Story caption'
    assert item.media_hashes == (r.assets[0].sha256,)
    assert item.provider_media[0].startswith('photo:')
    assert client.story_sends == 1
    sent, = [req for name, req in client.calls if name == 'SendStoryRequest']
    assert sent.peer.id == 101 and sent.period == 86400
    assert sent.caption == 'Story caption' and type(sent.privacy_rules[0]).__name__ == 'InputPrivacyValueAllowAll'
    assert sent.random_id == journal.checkpoints[0][1]['random_ids'][0]
    assert [name for name, _ in client.calls if name == 'GetStoriesByIDRequest'] == ['GetStoriesByIDRequest']

    fetched = await adapter.read(ReadRequest('connection', r.native_target,
                                'item', native_item='501', namespace='story'), journal.hooks)
    assert len(fetched.items) == 1 and fetched.items[0].native_id == '501'
    client.before_mutation = None
    deletion = replace(r, action='delete', existing=item, assets=())
    delete_journal = Journal()
    done = await adapter.execute(await adapter.prepare(deletion, delete_journal.hooks),
                                 delete_journal.hooks)
    assert done.observed == 'deleted'
    assert (101, 501) not in client.stories
    assert len([name for name, _ in client.calls if name == 'DeleteStoriesRequest']) == 1
    assert not (await adapter.read(ReadRequest('connection', r.native_target,
                    'item', native_item='501', namespace='story'), journal.hooks)).items


@pytest.mark.asyncio
async def test_video_mp4_and_private_channel_has_no_fabricated_permalink(monkeypatch):
    from social_operations import video_assets
    monkeypatch.setattr(video_assets, 'video_metadata', lambda data: (720, 1280, 7))
    data = b'offline-mp4-fixture'
    video = Asset('video', hashlib.sha256(data).hexdigest(), 'video/mp4',
                  len(data), role='video', data=data)
    client, adapter, journal = build()
    client.entities[101] = channel(101, None)
    r = story_request(assets=(video,), text='')
    result = await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    item, = result.items
    assert item.url is None and item.provider_media[0].startswith('document:')
    assert item.media_hashes == (video.sha256,)
    sent, = [req for name, req in client.calls if name == 'SendStoryRequest']
    assert type(sent.media).__name__ == 'InputMediaDocument' and sent.caption == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['boosts', 'quota', 'rights', 'schedule', 'two_media',
                                  'forward', 'bot', 'no_channel'])
async def test_ineligible_story_rejected_before_upload_or_effect(kind):
    client, adapter, journal = build()
    changes = {}
    if kind == 'boosts':
        client.boosts_required = True
    if kind == 'quota':
        client.story_quota = 0
    if kind == 'rights':
        client.permissions = NS(is_creator=False, post_stories=False)
    if kind == 'schedule':
        changes['scheduled_at'] = timestamp(NOW + 3600)
    if kind == 'two_media':
        changes['assets'] = (asset(1), asset(2))
    if kind == 'forward':
        changes['action'] = 'forward'
    if kind == 'bot':
        adapter.account_type = 'mtproto_bot'
        client.bot = True
        changes['account_type'] = 'mtproto_bot'
    if kind == 'no_channel':
        client.entities[101] = obj('Channel', id=101, broadcast=False, megagroup=False,
                                    left=False, kicked=False)
    r = story_request(**changes)
    with pytest.raises(DomainError) as raised:
        await adapter.prepare(r, journal.hooks)
    assert raised.value.code in {
        'telegram_story_not_allowed', 'telegram_story_schedule_or_forward_unsupported',
        'telegram_story_media_invalid', 'telegram_story_action_unsupported'
    }
    if kind in {'boosts', 'quota', 'rights'}:
        assert raised.value.code == 'telegram_story_not_allowed'
        assert raised.value.message
    assert not client.uploads and not client.effects
    assert not any(name == 'SendStoryRequest' for name, _ in client.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('adapter_cls', [TelegramAdapter, ResilientTelegramAdapter])
async def test_lost_response_replays_same_random_id_without_second_story(adapter_cls):
    client, adapter, journal = build(adapter_cls)
    r = story_request()
    prepared = await adapter.prepare(r, journal.hooks)

    def lose_response(_):
        raise OSError('transport lost response after channel accepted')

    client.after_mutation = lose_response
    with pytest.raises(DomainError) as failure:
        await adapter.execute(prepared, journal.hooks)
    assert failure.value.code in {'telegram_rpc_failed', 'telegram_transport_unhealthy'}
    assert client.story_sends == 1 and len(journal.markers) == 1
    prior = journal.checkpoint_json
    random_id = journal.checkpoints[0][1]['random_ids'][0]
    client.after_mutation = None
    resumed = adapter_cls(client, connection_id='connection', tl=ScriptedTL(), clock=lambda: NOW)
    result = await resumed.reconcile(r, prior, journal.hooks)
    assert result.observed == 'published' and result.items[0].native_id == '501'
    assert client.story_sends == 1
    sends = [req for name, req in client.calls if name == 'SendStoryRequest']
    assert len(sends) == 2 and all(x.random_id == random_id for x in sends)
    assert len(journal.markers) == 1


@pytest.mark.asyncio
async def test_access_revoked_before_send_does_not_create_a_story():
    client, adapter, journal = build()
    r = story_request()
    prepared = await adapter.prepare(r, journal.hooks)
    journal.fail_before = True
    with pytest.raises(DomainError) as error:
        await adapter.execute(prepared, journal.hooks)
    assert error.value.code == 'access_revoked'
    assert journal.checkpoints[0][0] == 'telegram_prepared'
    assert not client.story_sends and not client.stories


@pytest.mark.asyncio
async def test_exact_story_id_missing_is_not_guessed_from_caption():
    client, adapter, journal = build()
    r = story_request()
    await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    saved = journal.checkpoint_json
    client.stories.clear()
    with pytest.raises(OutcomeUnknown) as failure:
        await adapter.reconcile(r, saved, journal.hooks)
    assert failure.value.code == 'incomplete_readback'
    assert client.story_sends == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('telegram_allowed', [True, False])
async def test_worker_delivers_telegram_and_vk_stories_independently(tmp_path, telegram_allowed):
    store = Store(tmp_path / 'w5.sqlite', clock=lambda: NOW)
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    store.add_connection(actor, 'tg', 'telegram', account_type='mtproto_user')
    store.add_connection(actor, 'vk', 'vk', account_type='vk_user')
    store.bind(actor, 'owner', 'tg-story', 'tg', '-1000000000101')
    store.bind(actor, 'owner', 'vk-story', 'vk', '-101')
    photo = asset()
    with store.tx() as db:
        db.execute('INSERT INTO assets(id,tenant_id,principal_id,sha256,mime,width,height,bytes,source_sha256,created) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('w5_story_photo', actor.tenant_id, actor.principal_id, photo.sha256,
                    photo.mime, 4, 4, photo.data, photo.sha256, NOW))
    operation = await Application(store).call(actor, 'vibepublish_publish', {
        'to': ['tg-story', 'vk-story'], 'surface': 'story', 'content': {'text': ''},
        'media': [{'source': {'kind': 'asset', 'id': 'w5_story_photo'}, 'role': 'image'}],
        'request_key': 'w5-dual-story',
    })
    client = StoryClient()
    if not telegram_allowed:
        client.story_quota = 0
    vk = VKTransport()
    worker = Worker(store, {'tg': TelegramAdapter(client, connection_id='tg',
                     tl=ScriptedTL(), clock=lambda: NOW),
                  'vk': VKAdapter(vk, connection_id='vk', clock=lambda: NOW)})
    assert await worker.run_once()
    receipt = store.receipt(actor, operation['operation_id'])
    assert receipt['state'] == ('verified' if telegram_allowed else 'partial'), receipt
    assert client.story_sends == (1 if telegram_allowed else 0) and vk.effects == 1
    assert sum(d['observed'] == 'published' for d in receipt['deliveries']) == (2 if telegram_allowed else 1)
