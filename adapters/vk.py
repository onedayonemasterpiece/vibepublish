"""Native VK wall adapter: explicit token roles, ordered uploads, exact readback.

The transport is injected; no EventsBot runtime/credentials are imported. Native
postponed wall.post is implemented. Scheduled wall.repost is deliberately absent.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import replace

from .native import (bind_media, identity, load_checkpoint, plain_text, same_existing,
                     saved_checkpoint, schedule_guard, verify_assets)
from .port import Capability, Hooks, Observation, Prepared, ProviderRequest, ReadPage, ReadRequest, RemoteItem
from .vk_transport import POLICIES, validated_url
from social_operations.domain import DomainError, OutcomeUnknown, canonical, digest, parse_time, timestamp


def _items(response):
    if isinstance(response, dict):
        response = response.get('items')
    if not isinstance(response, list) or any(not isinstance(item, dict) for item in response):
        raise DomainError('vk_response_invalid')
    return response


def _int(value):
    if type(value) is not int:
        raise DomainError('vk_native_identity_invalid')
    return value


class VKAdapter:
    def __init__(self, transport, *, connection_id: str, account_type='vk_user', clock=time.time):
        self.transport, self.connection_id, self.account_type, self.clock = transport, connection_id, account_type, clock

    def _connection(self, request):
        if request.connection_id != self.connection_id:
            raise DomainError('connection_mismatch')
        actual_type = getattr(self.transport, 'account_type', self.account_type)
        if actual_type is not None and actual_type != self.account_type:
            raise DomainError('vk_account_type_mismatch')
        if self.account_type not in {'vk_user', 'vk_group'}:
            raise DomainError('vk_account_type_needs_review')
        if hasattr(request, 'account_type') and request.account_type != self.account_type:
            raise DomainError('vk_account_type_mismatch')
        if not re.fullmatch(r'-[1-9][0-9]*', request.native_target):
            raise DomainError('vk_community_binding_required')

    async def _call(self, method: str, *, role=None, **params):
        # Exact fixed-role methods; transport independently checks the vocabulary.
        return await self.transport.invoke(role=role or POLICIES[method][0], method=method, params=params)

    async def _rights(self, request):
        self._connection(request)
        group = -int(request.native_target)
        response = await self._call('groups.getById', role='editor', group_ids=str(group), fields='is_admin,admin_level,is_closed')
        groups = response.get('groups', []) if isinstance(response, dict) else response
        if not isinstance(groups, list) or len(groups) != 1 or groups[0].get('id') != group:
            raise DomainError('vk_group_identity_mismatch')
        if self.account_type == 'vk_user' and (groups[0].get('is_admin') != 1 or groups[0].get('admin_level', 0) < 2):
            raise DomainError('provider_access_denied')
        methods = {'publish': ['wall.post'], 'forward': ['wall.repost'], 'edit': ['wall.edit'],
                   'reschedule': ['wall.edit'], 'cancel': ['wall.delete'], 'delete': ['wall.delete']}[request.action]
        methods += ['wall.get' if request.scheduled_at or (request.existing and request.existing.namespace == 'scheduled') else 'wall.getById']
        if request.assets:
            methods += ['photos.getWallUploadServer', 'photos.saveWallPhoto']
        for method in methods:
            if not self.transport.permits(POLICIES[method][0], method, group_id=group, scheduled=bool(request.scheduled_at)):
                raise DomainError('vk_token_role_not_permitted', next_action='contact_owner')
        return group

    async def inspect(self, request: ProviderRequest) -> Capability:
        try:
            if request.surface != 'post':
                raise DomainError('vk_surface_needs_review')
            if request.action not in {'publish', 'forward', 'edit', 'reschedule', 'cancel', 'delete'}:
                raise DomainError('vk_action_unsupported')
            if request.action == 'forward' and request.scheduled_at:
                raise DomainError('vk_scheduled_repost_unsupported')
            if request.source and request.selection == 'message':
                raise DomainError('vk_wall_repost_is_whole_post')
            plain_text(request, limit=16000)
            verify_assets(request)
            schedule_guard(request, self.clock())
            await self._rights(request)
            if request.existing:
                existing = request.existing
                if existing.native_target != request.native_target:
                    raise DomainError('remote_target_mismatch')
                if existing.namespace not in {'published', 'scheduled'}:
                    raise DomainError('vk_namespace_unsupported')
                if request.action in {'reschedule', 'cancel'} and existing.namespace != 'scheduled':
                    raise DomainError('native_queue_item_required')
                if request.action == 'delete' and existing.namespace != 'published':
                    raise DomainError('delete_requires_published')
            elif request.action not in {'publish', 'forward'}:
                raise DomainError('remote_item_required')
        except DomainError as exc:
            return Capability('unsupported', exc.code, evidence='not_canary_verified')
        return Capability('supported', 'Scoped token-role/target preflight; live canary not performed', evidence='provider_read_preflight_only')

    @staticmethod
    def _media(raw):
        result = []
        for attachment in raw.get('attachments', []):
            kind = attachment.get('type')
            value = attachment.get(kind, {})
            if kind not in {'photo', 'video', 'doc', 'audio'} or not isinstance(value, dict):
                raise DomainError('vk_attachment_needs_review')
            result.append(f'{kind}{_int(value.get("owner_id"))}_{_int(value.get("id"))}')
        return tuple(result)

    def _item(self, raw, namespace, target):
        if str(_int(raw.get('owner_id'))) != target or _int(raw.get('id')) <= 0:
            raise DomainError('vk_read_target_mismatch')
        if namespace == 'scheduled' and raw.get('post_type') not in {None, 'postpone'}:
            raise DomainError('vk_queue_namespace_mismatch')
        if namespace == 'published' and raw.get('post_type') in {'postpone', 'suggest'}:
            raise DomainError('vk_queue_namespace_mismatch')
        origin = None
        copies = raw.get('copy_history', [])
        if copies:
            if len(copies) != 1:
                raise DomainError('vk_repost_chain_needs_review')
            origin = f'https://vk.ru/wall{_int(copies[0].get("owner_id"))}_{_int(copies[0].get("id"))}'
        metrics = tuple((name, float(raw[name]['count']), 'count') for name in ('views', 'likes', 'comments', 'reposts')
                        if isinstance(raw.get(name), dict) and type(raw[name].get('count')) is int and raw[name]['count'] >= 0)
        media = self._media(copies[0] if copies else raw)
        item = RemoteItem(str(raw['id']), namespace, raw.get('text') or '', '', timestamp(self.clock()),
                          scheduled_at=timestamp(_int(raw.get('date'))) if namespace == 'scheduled' else None,
                          native_target=target, origin=origin, provider_media=media,
                          member_ids=(str(raw['id']),), metrics=metrics,
                          url=f'https://vk.ru/wall{target}_{raw["id"]}' if namespace == 'published' else None)
        return replace(item, fingerprint=identity(item))

    async def _queue(self, target):
        # A bounded complete read; never report absence from an incomplete page.
        values, seen, expected_count = [], set(), None
        for offset in range(0, 1000, 100):
            response = await self._call('wall.get', owner_id=int(target), filter='postponed', count=100, offset=offset)
            rows = _items(response)
            if len(rows) > 100:
                raise DomainError('vk_queue_response_invalid')
            count = response.get('count') if isinstance(response, dict) else None
            if type(count) is not int or count < 0 or count > 1000:
                raise DomainError('vk_queue_read_incomplete')
            if expected_count is not None and expected_count != count:
                raise DomainError('vk_queue_moved', next_action='refresh')
            expected_count = count
            for raw in rows:
                item = self._item(raw, 'scheduled', target)
                if item.native_id in seen:
                    raise DomainError('vk_queue_moved', next_action='refresh')
                seen.add(item.native_id)
                values.append(item)
            if len(values) == count:
                return values
            if len(rows) < 100:
                raise DomainError('vk_queue_read_incomplete')
        raise DomainError('vk_queue_read_incomplete')

    async def _exact(self, target, ident, namespace):
        if namespace == 'scheduled':
            return next((item for item in await self._queue(target) if item.native_id == ident), None)
        response = await self._call('wall.getById', posts=f'{target}_{ident}', extended=0)
        rows = _items(response)
        if not rows:
            return None
        if len(rows) != 1 or str(rows[0].get('id')) != ident:
            raise DomainError('vk_readback_identity_mismatch')
        return self._item(rows[0], namespace, target)

    async def _source(self, request):
        source = request.source
        if source is None or source.provider != 'vk':
            raise DomainError('vk_source_required')
        if int(source.channel) >= 0:
            raise DomainError('vk_personal_wall_source_needs_review')
        if not request.source_authorized:
            response = await self._call('groups.getById', group_ids=str(-int(source.channel)), fields='is_closed')
            groups = response.get('groups', []) if isinstance(response, dict) else response
            if (not isinstance(groups, list) or len(groups) != 1 or groups[0].get('id') != -int(source.channel)
                    or groups[0].get('is_closed') != 0):
                raise DomainError('source_not_public')
        raw = _items(await self._call('wall.getById', posts=f'{source.channel}_{source.item}', extended=0))
        if len(raw) != 1 or str(raw[0].get('id')) != source.item or str(raw[0].get('owner_id')) != source.channel:
            raise DomainError('source_not_found')
        if (raw[0].get('is_deleted') or raw[0].get('copy_history') or raw[0].get('copyright', {}).get('type') == 'protected'
                or raw[0].get('can_repost') == 0):
            raise DomainError('source_repost_not_proven')
        item = self._item(raw[0], 'published', source.channel)
        return {'object': f'wall{source.channel}_{source.item}', 'url': source.canonical_url,
                'fingerprint': item.fingerprint, 'media': list(item.provider_media)}

    async def prepare(self, request: ProviderRequest, hooks: Hooks) -> Prepared:
        capability = await self.inspect(request)
        if capability.status != 'supported':
            raise DomainError(capability.reason, next_action='contact_owner')
        state = {}
        if request.existing:
            observed = await self._exact(request.native_target, request.existing.native_id, request.existing.namespace)
            if observed is None:
                raise DomainError('remote_item_missing', next_action='refresh')
            same_existing(request.existing, observed)
        if request.source:
            state['source'] = await self._source(request)
        return Prepared(request, capability, canonical(state))

    async def execute(self, prepared: Prepared, hooks: Hooks) -> Observation:
        r = prepared.request
        group = await self._rights(r)
        state = json.loads(prepared.state_json)
        if r.existing:
            observed = await self._exact(r.native_target, r.existing.native_id, r.existing.namespace)
            if observed is None:
                raise DomainError('remote_item_missing', next_action='refresh')
            same_existing(r.existing, observed)
            if r.existing.namespace == 'scheduled' and parse_time(r.existing.scheduled_at or '') < self.clock()+60:
                raise DomainError('native_item_due_or_expired', next_action='refresh')
        if r.source and await self._source(r) != state.get('source'):
            raise DomainError('source_changed', next_action='refresh')
        attachments, native_media = [], []
        reuse = r.existing and tuple(a.sha256 for a in r.assets) == tuple(r.existing.media_hashes)
        if r.action == 'publish' or (r.action == 'edit' and not reuse):
            for n, asset in enumerate(r.assets):
                await hooks.emit_progress('uploading', 'started', f'Staging image {n+1}/{len(r.assets)}')
                server = await self._call('photos.getWallUploadServer', group_id=group)
                if not isinstance(server, dict):
                    raise DomainError('vk_upload_server_invalid')
                url = server.get('upload_url')
                validated_url(url)
                receipt = await self.transport.upload_photo(url, asset.data, asset.mime)
                saved = await self._call('photos.saveWallPhoto', group_id=group, **receipt)
                if not isinstance(saved, list) or len(saved) != 1:
                    raise DomainError('vk_saved_photo_invalid')
                photo = saved[0]
                owner, ident = _int(photo.get('owner_id')), _int(photo.get('id'))
                if ident <= 0 or owner == 0:
                    raise DomainError('vk_saved_photo_invalid')
                native = f'photo{owner}_{ident}'
                key = photo.get('access_key')
                if key is not None and (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', key)):
                    raise DomainError('vk_saved_photo_invalid')
                native_media.append(native)
                attachments.append(native + ('_' + key if key else ''))
        elif r.source:
            native_media = state['source']['media']
        elif r.existing:
            native_media = list(r.existing.provider_media)
            # Omitting attachments on edit preserves remote objects and avoids storing access keys.
        params = {'owner_id': int(r.native_target)}
        if r.action == 'forward':
            method, params = 'wall.repost', {'object': state['source']['object'], 'group_id': group}
        elif r.action in {'cancel', 'delete'}:
            method = 'wall.delete'
            params['post_id'] = int(r.existing.native_id)
        else:
            params['message'] = plain_text(r, limit=16000)
            if r.scheduled_at:
                params['publish_date'] = int(parse_time(r.scheduled_at))
            if r.existing:
                method = 'wall.edit'
                params['post_id'] = int(r.existing.native_id)
                if not reuse and r.action == 'edit':
                    params['attachments'] = ','.join(attachments)
            else:
                method = 'wall.post'
                params.update(from_group=1, signed=0, guid=digest([r.operation_id, r.attempt_id]))
                if attachments:
                    params['attachments'] = ','.join(attachments)
        checkpoint = {'id': r.existing.native_id if r.existing else None, 'media': native_media,
                      'source': state.get('source')}
        await hooks.checkpoint('vk_prepared', saved_checkpoint(r, **checkpoint))
        schedule_guard(r, self.clock())
        await hooks.before_effect(r.attempt_id, r.plan_digest)
        response = await self._call(method, **params)
        if r.action in {'publish', 'forward'}:
            ident = response.get('post_id') if isinstance(response, dict) else None
            if type(ident) is not int or ident <= 0:
                raise OutcomeUnknown('vk_response_identity_missing')
            checkpoint['id'] = str(ident)
        elif response != 1 and not (isinstance(response, dict) and response.get('post_id') == int(r.existing.native_id)):
            raise OutcomeUnknown('vk_mutation_acknowledgement_missing')
        await hooks.checkpoint('vk_response', saved_checkpoint(r, **checkpoint))
        return await self._observe(r, checkpoint, hooks)

    async def _observe(self, r, checkpoint, hooks):
        await hooks.emit_progress('reading_back', 'started', 'Reading exact VK wall or postponed queue identity')
        if not checkpoint.get('id'):
            raise OutcomeUnknown('vk_response_identity_missing')
        namespace = r.existing.namespace if r.action in {'cancel', 'delete'} else 'scheduled' if r.scheduled_at else 'published'
        item = await self._exact(r.native_target, checkpoint['id'], namespace)
        if r.action in {'cancel', 'delete'}:
            if item is not None:
                raise OutcomeUnknown('vk_deletion_unconfirmed')
            if r.action == 'cancel':
                # VK preserves post IDs when a postponed post goes live.
                published = await self._exact(r.native_target, checkpoint['id'], 'published')
                if published is not None:
                    raise OutcomeUnknown('vk_cancel_raced_publication')
            return Observation('cancelled' if r.action == 'cancel' else 'deleted', (replace(r.existing, observed_at=timestamp(self.clock())),))
        if item is None:
            raise OutcomeUnknown('vk_readback_missing')
        source = checkpoint.get('source')
        if source and item.origin != source['url']:
            raise OutcomeUnknown('vk_repost_origin_mismatch')
        item = bind_media(r, item, checkpoint['media'])
        return Observation('provider_scheduled' if r.scheduled_at else 'edited' if r.existing else 'published',
                           (item,), forward_origin_matched=bool(source))

    async def reconcile(self, request: ProviderRequest, checkpoint: str, hooks: Hooks) -> Observation:
        self._connection(request)
        return await self._observe(request, load_checkpoint(request, checkpoint), hooks)

    async def read(self, request: ReadRequest, hooks: Hooks) -> ReadPage:
        self._connection(request)
        if request.kind == 'item':
            item = await self._exact(request.native_target, request.native_item, request.namespace)
            return ReadPage((item,) if item else ())
        if request.kind == 'scheduled':
            items = await self._queue(request.native_target)
        elif request.kind in {'feed', 'search'}:
            offset, previous = 0, None
            if request.cursor:
                try:
                    cursor = json.loads(request.cursor)
                    if (cursor['kind'] != request.kind or cursor['target'] != request.native_target or
                            type(cursor['offset']) is not int or cursor['offset'] < 1):
                        raise ValueError()
                    offset, previous = cursor['offset'], cursor['previous']
                except (ValueError, KeyError, TypeError):
                    raise DomainError('provider_cursor_stale', next_action='refresh') from None
            # Repeat one boundary item to detect shifted VK offset pagination.
            start = offset-1 if previous else 0
            size = request.limit+2 if previous else request.limit+1
            response = (await self._call('wall.search', owner_id=int(request.native_target), query=request.text, count=size, offset=start)
                        if request.kind == 'search' else await self._call('wall.get', owner_id=int(request.native_target), filter='all', count=size, offset=start))
            rows = _items(response)
            items = [self._item(raw, 'published', request.native_target) for raw in rows]
            if previous:
                if not items or [items[0].native_id, items[0].fingerprint] != previous:
                    raise DomainError('provider_cursor_stale', next_action='refresh')
                items = items[1:]
            selected = items[:request.limit]
            cursor = (canonical({'kind': request.kind, 'target': request.native_target,
                                 'offset': offset+len(selected),
                                 'previous': [selected[-1].native_id, selected[-1].fingerprint]})
                      if len(items) > request.limit else None)
            return ReadPage(tuple(selected), cursor)
        else:
            raise DomainError('vk_read_needs_review', next_action='contact_owner')
        snapshot = digest([(i.native_id, i.fingerprint) for i in items])
        offset = 0
        if request.cursor:
            try:
                cursor = json.loads(request.cursor)
                if cursor['snapshot'] != snapshot or type(cursor['offset']) is not int or cursor['offset'] < 0:
                    raise ValueError()
                offset = cursor['offset']
            except (KeyError, ValueError, TypeError):
                raise DomainError('provider_cursor_stale', next_action='refresh') from None
        return ReadPage(tuple(items[offset:offset+request.limit]),
                        canonical({'snapshot': snapshot, 'offset': offset+request.limit}) if offset+request.limit < len(items) else None)
