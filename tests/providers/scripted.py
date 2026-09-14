"""Provider-shaped responses, not implementations of ProviderAdapter.

These fixtures intentionally know only native method/parameter vocabularies.
The actual adapters compile all writes and verify all observations.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from adapters.telegram import _REQUESTS
from adapters.vk_transport import POLICIES, role_allowed


def obj(type_name, **values):
    return type(type_name, (NS,), {})(**values)


def channel(ident, username=None, *, noforwards=False):
    return obj('Channel', id=ident, broadcast=True, megagroup=False, username=username,
               noforwards=noforwards, left=False, kicked=False)


def tg_message(ident, target=101, text='Fixture', *, photo=None, group=None, date=None, forward=None):
    return obj('Message', id=ident, message=text, peer_id=obj('PeerChannel', channel_id=target),
               date=date or datetime(2026, 9, 5, 12, tzinfo=timezone.utc), grouped_id=group,
               media=obj('MessageMediaPhoto', photo=obj('Photo', id=photo)) if photo else None,
               fwd_from=forward, views=12, forwards=1, noforwards=False)


class ScriptedTL:
    def request(self, kind, **values):
        return obj(_REQUESTS[kind][1], **values)

    def type(self, name, **values):
        return obj(name, **values)


class TelegramClient:
    MUTATIONS = {'SendMessageRequest', 'SendMediaRequest', 'SendMultiMediaRequest', 'ForwardMessagesRequest',
                 'EditMessageRequest', 'DeleteScheduledMessagesRequest', 'DeleteMessagesRequest'}

    def __init__(self):
        self.calls, self.effects, self.uploads = [], 0, []
        self.entities = {101: channel(101, 'target'), 202: channel(202, 'source')}
        self.messages, self.scheduled = {}, {}
        self.bot = False
        self.permissions = NS(is_creator=True, post_messages=True, edit_messages=True, delete_messages=True)
        self.next_id = 10
        self.next_photo = 1000
        self.before_mutation = None
        self.after_mutation = None
        self.fail_read = False

    async def get_me(self):
        self.calls.append(('get_me', {}))
        return obj('User', id=5, bot=self.bot)

    async def get_permissions(self, entity, me):
        self.calls.append(('get_permissions', {'entity': entity.id}))
        return self.permissions

    async def get_entity(self, target):
        self.calls.append(('get_entity', {'target': target}))
        if isinstance(target, str) and not target.lstrip('-').isdigit():
            return next(e for e in self.entities.values() if e.username == target)
        ident = abs(int(target))
        ident = ident-1_000_000_000_000 if ident >= 1_000_000_000_000 else ident
        return self.entities[ident]

    async def get_messages(self, entity, *, ids):
        self.calls.append(('get_messages', {'entity': entity.id, 'ids': ids}))
        if self.fail_read:
            raise OSError('fixture read failure')
        if isinstance(ids, list):
            return [copy.deepcopy(self.messages.get((entity.id, i))) for i in ids]
        return copy.deepcopy(self.messages.get((entity.id, ids)))

    async def upload_file(self, stream, *, file_size, file_name):
        data = stream.read()
        assert len(data) == file_size
        self.uploads.append(data)
        self.calls.append(('upload_file', {'size': file_size, 'filename': file_name}))
        return obj('InputFile', id=len(self.uploads), parts=1, name=file_name, md5_checksum='fixture')

    async def __call__(self, req):
        name = type(req).__name__
        self.calls.append((name, req))
        target = getattr(getattr(req, 'peer', None), 'id', 101)
        if name == 'GetScheduledHistoryRequest':
            assert req.hash == 0
            if self.fail_read:
                raise OSError('fixture read failure')
            # Raw API commonly returns newest first, while an album is ascending.
            return NS(messages=copy.deepcopy(sorted([m for (p, _), m in self.scheduled.items() if p == target], key=lambda m: m.id, reverse=True)))
        if name == 'GetHistoryRequest':
            return NS(messages=copy.deepcopy(sorted([m for (p, _) ,m in self.messages.items() if p == target and (not req.offset_id or m.id < req.offset_id)], key=lambda m: m.id, reverse=True)[:req.limit]))
        if name == 'UploadMediaRequest':
            self.next_photo += 1
            return obj('MessageMediaPhoto', photo=obj('Photo', id=self.next_photo, access_hash=123, file_reference=b'fixture'))
        if name not in self.MUTATIONS:
            raise AssertionError('Unexpected native call: ' + name)
        if self.before_mutation:
            self.before_mutation(name)
        self.effects += 1
        updates = []
        if name in {'SendMessageRequest', 'SendMediaRequest', 'SendMultiMediaRequest', 'ForwardMessagesRequest'}:
            is_forward = name == 'ForwardMessagesRequest'
            if is_forward:
                target = req.to_peer.id
                random_ids = req.random_id
                originals = [self.messages[(req.from_peer.id, i)] for i in req.id]
                texts = [m.message for m in originals]
                rich = [copy.deepcopy(getattr(m, 'entities', [])) for m in originals]
                photos = [getattr(getattr(m.media, 'photo', None), 'id', None) for m in originals]
                forwards = [obj('MessageFwdHeader', from_id=obj('PeerChannel', channel_id=req.from_peer.id), channel_post=m.id) for m in originals]
                assert req.drop_author is False and req.drop_media_captions is False
            elif name == 'SendMultiMediaRequest':
                random_ids = [m.random_id for m in req.multi_media]
                texts = [m.message for m in req.multi_media]
                rich = [copy.deepcopy(m.entities) for m in req.multi_media]
                photos = [m.media.id.id for m in req.multi_media]
                forwards = [None] * len(texts)
            else:
                random_ids, texts = [req.random_id], [req.message]
                rich = [copy.deepcopy(req.entities)]
                photos = [req.media.id.id] if name == 'SendMediaRequest' else [None]
                forwards = [None]
            group = self.next_id if len(texts) > 1 else None
            for rid, text, photo, fwd, entities in zip(random_ids, texts, photos, forwards, rich):
                self.next_id += 1
                m = tg_message(self.next_id, target, text, photo=photo, group=group, date=req.schedule_date, forward=fwd)
                storage = self.scheduled if req.schedule_date else self.messages
                m.entities = entities
                storage[(target, m.id)] = m
                updates.extend([obj('UpdateMessageID', random_id=rid, id=m.id), obj('UpdateNewScheduledMessage' if req.schedule_date else 'UpdateNewChannelMessage', message=m)])
        elif name == 'EditMessageRequest':
            storage = self.scheduled if (target, req.id) in self.scheduled else self.messages
            m = storage[(target, req.id)]
            m.message = req.message
            m.entities = copy.deepcopy(req.entities)
            if req.schedule_date:
                m.date = req.schedule_date
            if hasattr(req, 'media'):
                m.media = obj('MessageMediaPhoto', photo=obj('Photo', id=req.media.id.id))
        else:
            target = getattr(getattr(req, 'channel', None), 'id', target)
            storage = self.scheduled if name == 'DeleteScheduledMessagesRequest' else self.messages
            for ident in req.id:
                storage.pop((target, ident), None)
            if name == 'DeleteScheduledMessagesRequest':
                updates.append(obj('UpdateDeleteScheduledMessages', peer=obj('PeerChannel', channel_id=target), messages=req.id, sent_messages=None))
        if self.after_mutation:
            self.after_mutation(name)
        return NS(updates=updates)


class VKTransport:
    def __init__(self):
        self.calls, self.effects, self.uploads = [], 0, []
        self.groups = {101: {'id': 101, 'is_admin': 1, 'admin_level': 3, 'is_closed': 0},
                       202: {'id': 202, 'is_admin': 0, 'admin_level': 0, 'is_closed': 0}}
        self.posts = {}
        self.next_id, self.next_photo = 10, 1000
        self.denied = set()
        self.before_mutation = None
        self.after_mutation = None
        self.fail_read = False
        self.queue_override = None

    def permits(self, role, method, *, group_id, scheduled=False):
        return role_allowed(role, method) and (role, method) not in self.denied

    async def upload_photo(self, url, data, mime):
        assert url == 'https://pu.vk.com/upload?fixture=1'
        self.uploads.append(data)
        self.calls.append(('upload_photo', 'media', {'mime': mime, 'size': len(data)}))
        return {'server': 100, 'photo': '[fixture]', 'hash': 'upload-private-fixture'}

    async def invoke(self, *, role, method, params):
        policy = POLICIES[method]
        assert role_allowed(role, method) and policy[1] <= params.keys() and params.keys() <= policy[2]
        assert (role, method) not in self.denied
        self.calls.append((method, role, copy.deepcopy(params)))
        if method == 'groups.getById':
            return {'groups': [copy.deepcopy(self.groups[int(params['group_ids'])])]}
        if method == 'photos.getWallUploadServer':
            return {'upload_url': 'https://pu.vk.com/upload?fixture=1'}
        if method == 'photos.saveWallPhoto':
            self.next_photo += 1
            return [{'id': self.next_photo, 'owner_id': -params['group_id'], 'access_key': 'private_fixture_key'}]
        if method in {'wall.get', 'wall.getById', 'wall.search'}:
            if self.fail_read:
                raise OSError('fixture read failure')
            if method == 'wall.getById':
                owner, ident = map(int, params['posts'].split('_'))
                found = self.posts.get((owner, ident))
                return [copy.deepcopy(found)] if found and found.get('post_type') != 'postpone' else []
            if self.queue_override is not None and params.get('filter') == 'postponed':
                return copy.deepcopy(self.queue_override)
            rows = [copy.deepcopy(post) for (owner, _), post in self.posts.items() if owner == params['owner_id'] and
                    (post.get('post_type') == 'postpone' if params.get('filter') == 'postponed' else post.get('post_type') != 'postpone')]
            if method == 'wall.search':
                rows = [p for p in rows if params['query'] in p['text']]
            return {'count': len(rows), 'items': rows[params['offset']:params['offset']+params['count']]}
        if self.before_mutation:
            self.before_mutation(method)
        self.effects += 1
        if method == 'wall.post':
            self.next_id += 1
            owner, ident = params['owner_id'], self.next_id
            post = {'id': ident, 'owner_id': owner, 'text': params['message'], 'date': params.get('publish_date', 1_800_000_000),
                    'post_type': 'postpone' if params.get('publish_date') else 'post', 'attachments': [], 'can_repost': 1}
            for item in filter(None, params.get('attachments', '').split(',')):
                aowner, aid = map(int, item.removeprefix('photo').split('_')[:2])
                post['attachments'].append({'type': 'photo', 'photo': {'owner_id': aowner, 'id': aid}})
            self.posts[(owner, ident)] = post
            result = {'post_id': ident}
        elif method == 'wall.repost':
            src_owner, src_id = map(int, params['object'].removeprefix('wall').split('_'))
            self.next_id += 1
            post = {'id': self.next_id, 'owner_id': -params['group_id'], 'text': '', 'date': 1_800_000_000,
                    'post_type': 'post', 'copy_history': [copy.deepcopy(self.posts[(src_owner, src_id)])]}
            self.posts[(post['owner_id'], post['id'])] = post
            result = {'success': 1, 'post_id': post['id']}
        elif method == 'wall.edit':
            post = self.posts[(params['owner_id'], params['post_id'])]
            post['text'] = params.get('message', post['text'])
            post['date'] = params.get('publish_date', post['date'])
            if 'attachments' in params:
                post['attachments'] = []
                for item in filter(None, params['attachments'].split(',')):
                    aowner, aid = map(int, item.removeprefix('photo').split('_')[:2])
                    post['attachments'].append({'type': 'photo', 'photo': {'owner_id': aowner, 'id': aid}})
            result = 1
        elif method == 'wall.delete':
            self.posts.pop((params['owner_id'], params['post_id']), None)
            result = 1
        else:
            raise AssertionError('Unexpected native call: ' + method)
        if self.after_mutation:
            self.after_mutation(method)
        return result
