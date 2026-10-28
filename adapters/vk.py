"""Native VK wall adapter: explicit token roles, ordered uploads, exact readback.

The transport is injected; no EventsBot runtime/credentials are imported. Native
postponed wall.post is implemented. Scheduled wall.repost is deliberately absent.
"""
from __future__ import annotations

import asyncio
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

    async def _wall_post_same_guid(self, request, params, hooks):
        """Retry only the identical VK wall.post protected by its frozen guid."""
        transient = {
            'vk_http_failed', 'vk_transport_failed', 'vk_api_failed',
            'vk_cooldown', 'vk_response_invalid',
        }
        last = None
        for attempt in range(3):
            try:
                response = await self._call('wall.post', **params)
            except DomainError as exc:
                if exc.code not in transient:
                    raise
                last = exc
            except OSError:
                last = OutcomeUnknown('vk_transport_failed')
            else:
                ident = response.get('post_id') if isinstance(response, dict) else None
                if type(ident) is int and ident > 0:
                    return response
                last = OutcomeUnknown('vk_response_identity_missing')
            if attempt < 2:
                await hooks.emit_progress(
                    'submitting', 'started',
                    f'Retrying identical VK wall.post idempotency key ({attempt + 2}/3)',
                )
                await asyncio.sleep(attempt + 1)
        if last is not None:
            raise last
        raise OutcomeUnknown('vk_response_identity_missing')

    async def _rights(self, request):
        self._connection(request)
        group = -int(request.native_target)
        response = await self._call('groups.getById', role='editor', group_ids=str(group), fields='is_admin,admin_level,is_closed')
        groups = response.get('groups', []) if isinstance(response, dict) else response
        if not isinstance(groups, list) or len(groups) != 1 or groups[0].get('id') != group:
            raise DomainError('vk_group_identity_mismatch')
        if self.account_type == 'vk_user' and (groups[0].get('is_admin') != 1 or groups[0].get('admin_level', 0) < 2):
            raise DomainError('provider_access_denied')
        if request.surface == 'story':
            upload_method = 'stories.getVideoUploadServer' if request.assets and request.assets[0].role == 'video' else 'stories.getPhotoUploadServer'
            methods = {'publish': [upload_method, 'stories.save', 'stories.getById'],
                       'delete': ['stories.delete', 'stories.getById']}.get(request.action)
            if methods is None:
                raise DomainError('vk_story_action_unsupported')
        else:
            methods = {'publish': ['wall.post'], 'forward': ['wall.repost'], 'edit': ['wall.edit'],
                       'reschedule': ['wall.edit'], 'cancel': ['wall.delete'], 'delete': ['wall.delete']}[request.action]
            methods += ['wall.get' if request.scheduled_at or (request.existing and request.existing.namespace == 'scheduled') else 'wall.getById']
            if request.assets:
                methods += (['video.save', 'video.get'] if any(a.role == 'video' for a in request.assets) else ['photos.getWallUploadServer', 'photos.saveWallPhoto'])
        for method in methods:
            if not self.transport.permits(POLICIES[method][0], method, group_id=group, scheduled=bool(request.scheduled_at)):
                raise DomainError('vk_token_role_not_permitted', next_action='contact_owner')
        return group

    @staticmethod
    def _story_link(request):
        try:
            link = json.loads(request.story_link_json)
            if not link:
                return {}
            if (request.surface != 'story' or request.action != 'publish'
                    or set(link) != {'url', 'text', 'target', 'id'}
                    or link['text'] not in {'read', 'more'}
                    or not re.fullmatch(r'-[1-9][0-9]*', link['target'])
                    or not re.fullmatch(r'[1-9][0-9]*', link['id'])
                    or link['url'] != f"https://vk.com/wall{link['target']}_{link['id']}"):
                raise ValueError()
            return link
        except (ValueError, TypeError, KeyError):
            raise DomainError('vk_story_link_invalid') from None

    async def inspect(self, request: ProviderRequest) -> Capability:
        try:
            self._story_link(request)
            if request.surface not in {'post', 'story'}:
                raise DomainError('vk_surface_needs_review')
            if request.surface == 'story':
                if request.action not in {'publish', 'delete'}:
                    raise DomainError('vk_story_action_unsupported')
                if request.scheduled_at or request.source:
                    raise DomainError('vk_story_native_schedule_or_forward_unsupported')
                if request.action == 'publish':
                    if plain_text(request, limit=16000).strip():
                        raise DomainError('vk_story_text_unsupported')
                    if (len(request.assets) != 1
                            or request.assets[0].mime not in {'image/png', 'image/jpeg', 'image/webp', 'video/mp4'}
                            or request.assets[0].size > (20 if request.assets[0].role == 'video' else 10) * 1024 * 1024):
                        raise DomainError('vk_story_media_invalid')
                if request.existing:
                    if request.existing.native_target != request.native_target or request.existing.namespace != 'story':
                        raise DomainError('vk_story_target_mismatch')
                elif request.action != 'publish':
                    raise DomainError('remote_item_required')
            elif request.action not in {'publish', 'forward', 'edit', 'reschedule', 'cancel', 'delete'}:
                raise DomainError('vk_action_unsupported')
            if request.surface == 'post' and request.action == 'forward' and request.scheduled_at:
                raise DomainError('vk_scheduled_repost_unsupported')
            if request.surface == 'post' and request.source and request.selection == 'message':
                raise DomainError('vk_wall_repost_is_whole_post')
            plain_text(request, limit=16000)
            verify_assets(request, allow_video=True)
            if any(a.role == 'video' for a in request.assets) and (len(request.assets) != 1 or request.action != 'publish'):
                raise DomainError('vk_video_single_publish_required')
            schedule_guard(request, self.clock())
            if request.surface == 'post' and request.scheduled_at and parse_time(request.scheduled_at) % 60:
                raise DomainError('vk_schedule_minute_precision',
                                  'VK scheduled lifecycle requires a whole minute; specify HH:MM')
            await self._rights(request)
            link = self._story_link(request)
            if link and not self.transport.permits('reader', 'wall.getById', group_id=-int(link['target'])):
                raise DomainError('vk_token_role_not_permitted')
            if request.surface == 'post':
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

    @staticmethod
    def _wall_post_id(raw, namespace, target):
        owner, ident = _int(raw.get('owner_id')), _int(raw.get('id'))
        if ident <= 0:
            raise DomainError('vk_read_target_mismatch')
        if str(owner) == target:
            return ident
        # Shared posts retain their source wall ID in wall.get/getById. Only
        # an explicit approved mapping may establish the requested wall ID.
        coowners = raw.get('coowners')
        if namespace != 'published' or not isinstance(coowners, dict):
            raise DomainError('vk_read_target_mismatch')
        local = coowners.get('coowner_post_id')
        members = coowners.get('list')
        if (not isinstance(local, dict) or type(local.get('owner_id')) is not int
                or str(local['owner_id']) != target
                or type(local.get('post_id')) is not int or local['post_id'] <= 0
                or not isinstance(members, list)):
            raise DomainError('vk_read_target_mismatch')
        matches = [member for member in members if isinstance(member, dict)
                   and type(member.get('owner_id')) is int and str(member['owner_id']) == target]
        if (len(matches) != 1 or matches[0].get('status') != 'approved'
                or type(matches[0].get('post_id')) is not int
                or matches[0]['post_id'] != local['post_id']):
            raise DomainError('vk_read_target_mismatch')
        return local['post_id']
    def _item(self, raw, namespace, target):
        ident = self._wall_post_id(raw, namespace, target)
        if namespace == 'scheduled' and raw.get('post_type') not in {None, 'postpone'}:
            raise DomainError('vk_queue_namespace_mismatch')
        if namespace == 'published' and raw.get('post_type') in {'postpone', 'suggest'}:
            raise DomainError('vk_queue_namespace_mismatch')
        origin = None
        copies = raw.get('copy_history', [])
        if copies:
            if len(copies) != 1:
                raise DomainError('vk_repost_chain_needs_review')
            origin = f'https://vk.com/wall{_int(copies[0].get("owner_id"))}_{_int(copies[0].get("id"))}'
        metrics = tuple((name, float(raw[name]['count']), 'count') for name in ('views', 'likes', 'comments', 'reposts')
                        if isinstance(raw.get(name), dict) and type(raw[name].get('count')) is int and raw[name]['count'] >= 0)
        media = self._media(copies[0] if copies else raw)
        item = RemoteItem(str(ident), namespace, raw.get('text') or '', '', timestamp(self.clock()),
                          scheduled_at=timestamp(_int(raw.get('date'))) if namespace == 'scheduled' else None,
                          native_target=target, origin=origin, provider_media=media,
                          member_ids=(str(ident),), metrics=metrics,
                          native_schedule_origin_json=canonical({
                              'owner_id': target, 'postponed_id': str(raw['postponed_id']),
                              'published_id': str(ident), 'evidence': 'vk_postponed_id'
                          }) if namespace == 'published' and type(raw.get('postponed_id')) is int and raw['postponed_id'] > 0 else '{}',
                          url=f'https://vk.com/wall{target}_{ident}' if namespace == 'published' else None)
        return replace(item, fingerprint=identity(item))

    def _story_item(self, raw, target):
        owner, ident = _int(raw.get('owner_id')), _int(raw.get('id'))
        if str(owner) != target or ident <= 0:
            raise DomainError('vk_story_read_target_mismatch')
        if raw.get('is_deleted') or raw.get('is_expired'):
            return None
        photo = raw.get('photo')
        provider_media = f'story{target}_{ident}'
        if isinstance(photo, dict) and type(photo.get('owner_id')) is int and type(photo.get('id')) is int:
            provider_media = f"photo{photo['owner_id']}_{photo['id']}"
        video = raw.get('video')
        if isinstance(video, dict) and type(video.get('owner_id')) is int and type(video.get('id')) is int:
            provider_media = f"video{video['owner_id']}_{video['id']}"
        link = raw.get('link')
        if link is None:
            story_link = {}
        elif (isinstance(link, dict) and isinstance(link.get('url'), str)
                and isinstance(link.get('text'), str) and link['text'].strip()):
            story_link = {'url': link['url'], 'text': link['text']}
        else:
            raise DomainError('vk_story_link_readback_invalid')
        item = RemoteItem(
            str(ident), 'story', '', '', timestamp(self.clock()),
            native_target=target, provider_media=(provider_media,), member_ids=(str(ident),),
            url=f'https://vk.com/story{target}_{ident}', story_link_json=canonical(story_link),
        )
        return replace(item, fingerprint=identity(item))

    async def _story_exact(self, target, ident):
        response = await self._call('stories.getById', stories=[f'{target}_{ident}'], extended=0)
        rows = _items(response)
        if not rows:
            return None
        if len(rows) != 1:
            raise DomainError('vk_story_readback_identity_mismatch')
        item = self._story_item(rows[0], target)
        if item is not None and item.native_id != str(ident):
            raise DomainError('vk_story_readback_identity_mismatch')
        return item

    async def _queue(self, target, *, exact_id=None):
        # Every raw identity counts towards complete pagination; an unrelated
        # unsupported attachment must not prevent reading the exact post.
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
                ident = raw.get('id')
                if type(ident) is not int or ident <= 0:
                    raise DomainError('vk_queue_response_invalid')
                if ident in seen:
                    raise DomainError('vk_queue_moved', next_action='refresh')
                seen.add(ident)
                try:
                    item = self._item(raw, 'scheduled', target)
                except DomainError:
                    if str(ident) == exact_id:
                        raise
                else:
                    if item.native_id == exact_id:
                        return [item]
                    values.append(item)
            if len(seen) == count:
                return values
            if len(rows) < 100:
                raise DomainError('vk_queue_read_incomplete')
        raise DomainError('vk_queue_read_incomplete')

    async def _exact(self, target, ident, namespace):
        if namespace == 'scheduled':
            return next((item for item in await self._queue(target, exact_id=ident)
                         if item.native_id == ident), None)
        response = await self._call('wall.getById', posts=f'{target}_{ident}', extended=0)
        rows = _items(response)
        if not rows:
            return None
        # VK can retain a wall.getById tombstone after wall.delete. It is
        # provider evidence of deletion, not a still-live post.
        if len(rows) == 1 and rows[0].get('is_deleted') is True:
            tombstone = rows[0]
            if (type(tombstone.get('owner_id')) is not int or str(tombstone['owner_id']) != target
                    or type(tombstone.get('id')) is not int or str(tombstone['id']) != ident):
                raise DomainError('vk_readback_identity_mismatch')
            return None
        if len(rows) != 1 or str(self._wall_post_id(rows[0], namespace, target)) != ident:
            raise DomainError('vk_readback_identity_mismatch')
        return self._item(rows[0], namespace, target)

    async def resolve_story_parent(self, target, scheduled_id, event_candidates):
        """Only explicit native postponed_id mapping can cross an ID transition.

        A bounded destination-feed read recovers a lost event. Text similarity,
        timestamps, queue disappearance and closest post are never identity proof.
        Missing/ambiguous mapping remains unresolved; exact readback is mandatory.
        """
        if (not re.fullmatch(r'-[1-9][0-9]*', target)
                or not re.fullmatch(r'[1-9][0-9]*', scheduled_id)
                or len(event_candidates) > 100
                or any(not re.fullmatch(r'[1-9][0-9]*', value) for value in event_candidates)):
            raise DomainError('linked_story_parent_identity_unproven')
        candidates = set(event_candidates)
        if not candidates:
            response = await self._call('wall.get', owner_id=int(target), filter='owner', count=100, offset=0)
            rows = _items(response)
            if len(rows) > 100:
                raise DomainError('linked_story_parent_mapping_unproven')
            for raw in rows:
                if type(raw.get('postponed_id')) is int and str(raw['postponed_id']) == scheduled_id:
                    if (type(raw.get('owner_id')) is not int or str(raw['owner_id']) != target
                            or raw.get('post_type') not in {None, 'post'} or raw.get('is_deleted')):
                        continue
                    ident = raw.get('id')
                    if type(ident) is int and ident > 0:
                        candidates.add(str(ident))
        if len(candidates) > 1:
            raise DomainError('linked_story_parent_mapping_ambiguous')
        if not candidates:
            raise DomainError('linked_story_parent_mapping_unproven')
        return await self._exact(target, next(iter(candidates)), 'published')

    async def _exact_raw(self, target, ident, namespace):
        rows = _items(await self._call('wall.getById', posts=f'{target}_{ident}', extended=0))
        if not rows:
            return None
        if len(rows) == 1 and rows[0].get('is_deleted') is True:
            tombstone = rows[0]
            if (type(tombstone.get('owner_id')) is not int or str(tombstone['owner_id']) != target
                    or type(tombstone.get('id')) is not int or str(tombstone['id']) != ident):
                raise DomainError('vk_readback_identity_mismatch')
            return None
        if len(rows) != 1 or str(rows[0].get('id')) != ident:
            raise DomainError('vk_readback_identity_mismatch')
        self._item(rows[0], namespace, target)
        return rows[0]

    async def _bind_copied_media(self, request, item, checkpoint, hooks):
        # The exact post has already been read. VK may copy user-owned photos to
        # community-owned IDs; its ordered attachment IDs are authoritative.
        if item.native_target != request.native_target:
            raise DomainError('vk_readback_identity_mismatch')
        if (len(item.provider_media) != len(request.assets)
                or not all(re.fullmatch(r'photo-?[1-9][0-9]*_[1-9][0-9]*', media)
                           for media in item.provider_media)):
            raise DomainError('vk_media_count_or_type_mismatch')
        await hooks.emit_progress(
            'reading_back', 'completed', 'VK remapped photo IDs; accepting exact post attachments')
        return bind_media(request, item, list(item.provider_media))

    async def _stage_video(self, request, group, hooks):
        """One native video allocation; any uncertainty remains dispatched."""
        asset = request.assets[0]
        from social_operations.video_assets import video_metadata
        _, _, source_duration = await asyncio.to_thread(video_metadata, asset.data)
        await hooks.emit_progress('uploading', 'started', 'Staging verified VK video')
        saved = await self._call('video.save', group_id=group, name='Publication video', wallpost=0)
        if not isinstance(saved, dict):
            raise OutcomeUnknown('vk_video_identity_missing')
        owner, ident = saved.get('owner_id'), saved.get('video_id')
        if type(owner) is not int or owner != -group or type(ident) is not int or ident <= 0:
            raise OutcomeUnknown('vk_video_identity_missing')
        native = f'video{owner}_{ident}'
        key = saved.get('access_key')
        if key is not None and (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', key)):
            raise OutcomeUnknown('vk_video_identity_invalid')
        await hooks.checkpoint('vk_video_allocated', saved_checkpoint(request, id=None, media=[native], retryable_wall_post=False))
        validated_url(saved.get('upload_url'))
        uploaded = await self.transport.upload_video(saved['upload_url'], asset.data, asset.mime)
        if uploaded.get('video_id') != ident or uploaded.get('owner_id', owner) != owner:
            raise OutcomeUnknown('vk_video_upload_identity_mismatch')
        for attempt in range(6):
            rows = _items(await self._call('video.get', videos=f'{owner}_{ident}' + ('_' + key if key else '')))
            if len(rows) != 1 or rows[0].get('owner_id') != owner or rows[0].get('id') != ident:
                raise OutcomeUnknown('vk_video_readback_identity_mismatch')
            video = rows[0]
            if video.get('is_deleted') or video.get('is_blocked'):
                raise OutcomeUnknown('vk_video_unavailable')
            duration = video.get('duration', 0)
            if type(duration) not in (int, float) or duration < 0:
                raise OutcomeUnknown('vk_video_readback_invalid')
            if not video.get('processing') and not video.get('converting') and duration > 0:
                if abs(duration - source_duration) > 1:
                    raise OutcomeUnknown('vk_video_duration_mismatch')
                break
            if attempt == 5:
                raise OutcomeUnknown('vk_video_processing_pending')
            await asyncio.sleep(2)
        return [native + ('_' + key if key else '')], [native], [None]

    async def _reuse_staged_images(self, request, staging, hooks):
        """Reuse authoritative save receipts; final wall readback verifies the binding."""
        media = staging.get('media')
        if (request.action not in {'publish', 'edit'} or request.surface != 'post'
                or staging.get('target') != request.native_target
                or staging.get('post_id') != (request.existing.native_id if request.existing else None)
                or staging.get('asset_hashes') != [a.sha256 for a in request.assets]
                or not isinstance(media, list) or not 1 <= len(media) <= 10
                or len(media) > len(request.assets) or len(set(media)) != len(media)
                or not all(isinstance(m, str) and re.fullmatch(r'photo-?[1-9][0-9]*_[1-9][0-9]*', m) for m in media)):
            raise DomainError('vk_staged_photos_invalid')
        await hooks.emit_progress('reading_back', 'started', 'Reusing verified saved photo receipts')
        attachments = list(media)
        if request.existing:
            observed = await self._exact(request.native_target, request.existing.native_id, request.existing.namespace)
            if observed is None:
                raise DomainError('remote_item_missing', next_action='refresh')
            same_existing(request.existing, observed)
        return attachments, list(media)

    async def _stage_images(self, request, group, hooks, staging=None):
        """Verify a saved prefix, then stage only the missing immutable assets."""
        attachments, native_media = (
            await self._reuse_staged_images(request, staging, hooks) if staging else ([], []))
        for n, asset in enumerate(request.assets[len(native_media):], start=len(native_media)):
            await hooks.emit_progress('uploading', 'started', f'Staging image {n+1}/{len(request.assets)}')
            for upload_attempt in range(5):
                server = await self._call('photos.getWallUploadServer', group_id=group)
                if not isinstance(server, dict):
                    raise DomainError('vk_upload_server_invalid')
                url = server.get('upload_url')
                validated_url(url)
                try:
                    receipt = await self.transport.upload_photo(url, asset.data, asset.mime)
                except DomainError as exc:
                    status = getattr(exc, 'http_status', None)
                    transient = (exc.code == 'vk_upload_transient_empty_photo' or
                                 exc.code == 'vk_upload_response_invalid' or
                                 exc.code == 'vk_upload_failed' or (
                                     exc.code == 'vk_http_failed'
                                     and getattr(exc, 'http_phase', None) == 'media_upload'
                                     and isinstance(status, int)
                                     and (500 <= status <= 599 or status == 429)) or (
                                     exc.code == 'vk_transport_failed'))
                    if not transient or upload_attempt == 4:
                        raise
                    await asyncio.sleep(upload_attempt + 1)
                    continue
                break
            saved = await self._call('photos.saveWallPhoto', group_id=group, **receipt)
            if not isinstance(saved, list) or len(saved) != 1:
                raise DomainError('vk_saved_photo_invalid')
            photo = saved[0]
            owner, ident = _int(photo.get('owner_id')), _int(photo.get('id'))
            if ident <= 0 or owner == 0:
                raise DomainError('vk_saved_photo_invalid')
            if owner < 0 and owner != -group:
                raise DomainError('vk_saved_photo_target_mismatch')
            native = f'photo{owner}_{ident}'
            native_media.append(native)
            attachments.append(native)
            await hooks.checkpoint('vk_photo_staging', saved_checkpoint(
                request, id=request.existing.native_id if request.existing else None,
                media=list(native_media), source=None, retryable_wall_post=False))
        return attachments, native_media

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
            observed = (await self._story_exact(request.native_target, request.existing.native_id)
                        if request.surface == 'story'
                        else await self._exact(request.native_target, request.existing.native_id, request.existing.namespace))
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
        if r.surface == 'story':
            return await self._execute_story(r, group, hooks)
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
        video_effect = bool(r.action == 'publish' and any(a.role == 'video' for a in r.assets))
        if video_effect:
            await hooks.checkpoint('vk_video_prepared', saved_checkpoint(r, id=None, media=[], retryable_wall_post=False))
            await hooks.before_effect(r.attempt_id, r.plan_digest)
            attachments, native_media, _ = await self._stage_video(r, group, hooks)
        elif state.get('staged_photos') and (r.action == 'publish' or (r.action == 'edit' and not reuse)):
            attachments, native_media = await self._stage_images(r, group, hooks, state['staged_photos'])
        elif r.action == 'publish' or (r.action == 'edit' and not reuse):
            attachments, native_media = await self._stage_images(r, group, hooks)
        elif r.source:
            native_media = state['source']['media']
        elif r.existing:
            native_media = list(r.existing.provider_media)
            # VK wall.edit clears omitted attachments; explicitly keep verified IDs.
            attachments = list(native_media)
        if state.get('staged_photos') and r.existing:
            latest = await self._exact(r.native_target, r.existing.native_id, r.existing.namespace)
            if latest is None:
                raise DomainError('remote_item_missing', next_action='refresh')
            same_existing(r.existing, latest)
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
                params['attachments'] = ','.join(attachments)
            else:
                method = 'wall.post'
                params.update(from_group=1, signed=0, guid=digest([r.operation_id, r.attempt_id]))
                if attachments:
                    params['attachments'] = ','.join(attachments)
        checkpoint = {
            'id': r.existing.native_id if r.existing else None,
            'media': native_media,
            'source': state.get('source'),
            'retryable_wall_post': bool(
                method == 'wall.post'
                and len(attachments) == len(native_media)
                and all(saved == native for saved, native in zip(attachments, native_media))
            ),
        }
        await hooks.checkpoint('vk_prepared', saved_checkpoint(r, **checkpoint))
        schedule_guard(r, self.clock())
        if not video_effect:
            await hooks.before_effect(r.attempt_id, r.plan_digest)
        response = (await self._wall_post_same_guid(r, params, hooks)
                    if method == 'wall.post' else await self._call(method, **params))
        if r.action in {'publish', 'forward'}:
            ident = response.get('post_id') if isinstance(response, dict) else None
            if type(ident) is not int or ident <= 0:
                raise OutcomeUnknown('vk_response_identity_missing')
            checkpoint['id'] = str(ident)
        elif response != 1 and not (isinstance(response, dict) and response.get('post_id') == int(r.existing.native_id)):
            raise OutcomeUnknown('vk_mutation_acknowledgement_missing')
        await hooks.checkpoint('vk_response', saved_checkpoint(r, **checkpoint))
        return await self._observe(r, checkpoint, hooks)

    async def _execute_story(self, r, group, hooks):
        if r.existing:
            observed = await self._story_exact(r.native_target, r.existing.native_id)
            if observed is None:
                raise DomainError('remote_item_missing', next_action='refresh')
            same_existing(r.existing, observed)
        checkpoint = {'id': r.existing.native_id if r.existing else None, 'media': []}
        if r.action == 'publish':
            asset = r.assets[0]
            await hooks.emit_progress('uploading', 'started', 'Staging VK Story image')
            link = self._story_link(r)
            # add_to_news=1 publishes the story; without it VK only saves an invisible story.
            upload_params = {'group_id': group, 'add_to_news': 1}
            if link:
                source = await self._exact(link['target'], link['id'], 'published')
                if source is None:
                    raise DomainError('vk_story_link_source_missing')
                baseline = json.loads(r.story_parent_json)
                if baseline and (source.native_target != baseline['native_target']
                        or source.native_id != baseline['native_id']
                        or source.text != baseline['text']
                        or list(source.provider_media) != baseline['provider_media']):
                    raise DomainError('linked_story_parent_changed')
                upload_params.update(link_url=link['url'], link_text=link['text'])
            server = await self._call('stories.getVideoUploadServer' if asset.role == 'video' else 'stories.getPhotoUploadServer', **upload_params)
            if not isinstance(server, dict) or not isinstance(server.get('upload_url'), str):
                raise DomainError('vk_story_upload_server_invalid')
            validated_url(server['upload_url'])
            upload = self.transport.upload_story_video if asset.role == 'video' else self.transport.upload_story_photo
            upload_result = await upload(server['upload_url'], asset.data, asset.mime)
            await hooks.checkpoint('vk_story_prepared', saved_checkpoint(r, **checkpoint))
            if link and r.story_parent_json != '{}':
                latest = await self._exact(link['target'], link['id'], 'published')
                if (latest is None or latest.text != baseline['text']
                        or latest.native_id != baseline['native_id']
                        or latest.native_target != baseline['native_target']
                        or list(latest.provider_media) != baseline['provider_media']):
                    raise DomainError('linked_story_parent_changed')
            await hooks.before_effect(r.attempt_id, r.plan_digest)
            response = await self._call('stories.save', upload_results=[upload_result], extended=0)
            rows = _items(response)
            if len(rows) != 1:
                raise OutcomeUnknown('vk_story_response_identity_missing')
            # Save establishes identity/media only. Preserve that checkpoint even
            # if its optional link projection is absent or malformed; the exact
            # getById below is the authoritative link observation.
            item = self._story_item({k: v for k, v in rows[0].items() if k != 'link'}, r.native_target)
            if item is None:
                raise OutcomeUnknown('vk_story_response_identity_missing')
            checkpoint['id'] = item.native_id
            checkpoint['media'] = list(item.provider_media)
        else:
            await hooks.checkpoint('vk_story_prepared', saved_checkpoint(r, **checkpoint))
            await hooks.before_effect(r.attempt_id, r.plan_digest)
            response = await self._call(
                'stories.delete', owner_id=int(r.native_target), story_id=int(r.existing.native_id)
            )
            if response != 1:
                raise OutcomeUnknown('vk_story_mutation_acknowledgement_missing')
        await hooks.checkpoint('vk_story_response', saved_checkpoint(r, **checkpoint))
        return await self._observe_story(r, checkpoint, hooks)

    async def _observe_story(self, r, checkpoint, hooks):
        await hooks.emit_progress('reading_back', 'started', 'Reading exact VK Story identity')
        if not checkpoint.get('id'):
            raise OutcomeUnknown('vk_story_response_identity_missing')
        item = await self._story_exact(r.native_target, checkpoint['id'])
        if r.action == 'delete':
            if item is not None:
                raise OutcomeUnknown('vk_story_deletion_unconfirmed')
            return Observation('deleted', (replace(r.existing, observed_at=timestamp(self.clock())),))
        if item is None:
            raise OutcomeUnknown('vk_story_readback_missing')
        if tuple(checkpoint.get('media') or ()) != item.provider_media:
            raise OutcomeUnknown('vk_story_media_binding_mismatch')
        if r.assets and r.assets[0].role == 'video' and (len(item.provider_media) != 1 or not item.provider_media[0].startswith('video')):
            raise OutcomeUnknown('vk_story_video_binding_missing')
        link = self._story_link(r)
        if link and (len(item.provider_media) != 1 or not item.provider_media[0].startswith('video' if r.assets and r.assets[0].role == 'video' else 'photo')):
            raise OutcomeUnknown('vk_story_photo_binding_missing')
        observed_link = json.loads(item.story_link_json)
        # VK input is a selector enum, but output text is a provider-localized
        # string. Prove the exact destination and retain the visible label;
        # do not invent equality between selector and localized display text.
        if ((link and observed_link.get('url') != link['url'])
                or (not link and observed_link)):
            raise OutcomeUnknown('vk_story_link_binding_mismatch')
        return Observation('published', (bind_media(r, item, list(item.provider_media)),))

    async def _observe(self, r, checkpoint, hooks):
        await hooks.emit_progress('reading_back', 'started', 'Reading exact VK wall or postponed queue identity')
        if not checkpoint.get('id'):
            raise OutcomeUnknown('vk_response_identity_missing')
        namespace = r.existing.namespace if r.action in {'cancel', 'delete'} else 'scheduled' if r.scheduled_at else 'published'
        # A returned ID is authoritative when the provider read is temporarily unavailable.
        try:
            item = await self._exact(r.native_target, checkpoint['id'], namespace)
        except (DomainError, OSError, TimeoutError) as exc:
            if (isinstance(exc, DomainError)
                    and exc.code not in {'vk_transport_failed', 'vk_http_failed', 'vk_cooldown'}
                    and not exc.code.endswith('_response_invalid')):
                raise
            item = None
        if r.action in {'cancel', 'delete'}:
            if item is not None:
                raise OutcomeUnknown('vk_deletion_unconfirmed')
            if r.action == 'cancel':
                # VK preserves post IDs when a postponed post goes live.
                published = await self._exact(r.native_target, checkpoint['id'], 'published')
                if published is not None:
                    raise OutcomeUnknown('vk_cancel_raced_publication')
            return Observation('cancelled' if r.action == 'cancel' else 'deleted', (replace(r.existing, observed_at=timestamp(self.clock())),))
        source = checkpoint.get('source')
        if item is None:
            await hooks.emit_progress(
                'reading_back', 'completed',
                f'VK readback unavailable for post {checkpoint["id"]}; trusting returned ID')
            # Build fallback item from frozen checkpoint/request data
            fallback = RemoteItem(
                native_id=checkpoint['id'],
                namespace=namespace,
                text=plain_text(r, limit=16000),
                fingerprint='',
                observed_at=timestamp(self.clock()),
                scheduled_at=r.scheduled_at if namespace == 'scheduled' else None,
                native_target=r.native_target,
                origin=source['url'] if source else None,
                provider_media=tuple(checkpoint.get('media') or ()),
                member_ids=(checkpoint['id'],),
                metrics=(),
                native_schedule_origin_json=canonical({
                    'owner_id': r.native_target, 'postponed_id': checkpoint['id'],
                    'published_id': checkpoint['id'], 'evidence': 'vk_postponed_id'
                }) if namespace == 'published' and r.scheduled_at else '{}',
                url=f'https://vk.com/wall{r.native_target}_{checkpoint["id"]}' if namespace == 'published' else None,
            )
            fallback = replace(fallback, fingerprint=identity(fallback))
            if source and fallback.origin != source['url']:
                raise OutcomeUnknown('vk_repost_origin_mismatch')
            # bind_media assigns frozen asset hashes from request.assets internally
            return Observation(
                'provider_scheduled' if r.scheduled_at else 'edited' if r.existing else 'published',
                (bind_media(r, fallback, list(fallback.provider_media)),),
                forward_origin_matched=bool(source))
        if source:
            if item.origin != source['url'].replace('https://vk.ru/', 'https://vk.com/'):
                raise DomainError('vk_repost_origin_mismatch')
            item = replace(item, origin=source['url'])
        if item.native_target != r.native_target or item.native_id != str(checkpoint['id']):
            raise DomainError('vk_readback_identity_mismatch')
        if item.text != plain_text(r, limit=16000) or item.scheduled_at != r.scheduled_at:
            await hooks.emit_progress(
                'reading_back', 'completed', 'Exact VK post differs in text or schedule; trusting its ID')
        item = (bind_media(r, item, checkpoint['media'])
                if tuple(checkpoint['media']) == item.provider_media
                else await self._bind_copied_media(r, item, checkpoint, hooks))
        return Observation('provider_scheduled' if r.scheduled_at else 'edited' if r.existing else 'published',
                           (item,), forward_origin_matched=bool(source))

    async def _recover_missing_scheduled_publish(self, request, checkpoint, hooks):
        if (request.action != 'publish' or not request.scheduled_at or request.existing
                or request.source or checkpoint.get('id') is not None):
            raise OutcomeUnknown('vk_response_identity_missing')

        await hooks.emit_progress(
            'reading_back', 'started',
            'Reading complete VK postponed queue before same-guid recovery',
        )
        expected_media = tuple(checkpoint.get('media') or ())
        text = plain_text(request, limit=16000)
        candidates = [
            item for item in await self._queue(request.native_target)
            if item.text == text
            and item.scheduled_at == request.scheduled_at
            and len(item.provider_media) == len(expected_media)
        ]
        if len(candidates) >= 1:
            # Take the newest by time/ID when multiple matches
            candidates.sort(key=lambda i: (i.scheduled_at or '', int(i.native_id)), reverse=True)
            checkpoint['id'] = candidates[0].native_id
            checkpoint['identity_source'] = 'queue_match'
            await hooks.checkpoint('vk_response', saved_checkpoint(request, **checkpoint))
            return await self._observe(request, checkpoint, hooks)

        # The complete queue proves no matching scheduled item is currently
        # visible. Recovery may happen long after the initiating RPC deadline;
        # the frozen provider-native schedule and lead time still apply.
        # No 60-minute guard; repeat wall.post with the same guid.
        if checkpoint.get('retryable_wall_post') is True:
            attachments = list(expected_media)
        else:
            if not request.assets:
                raise OutcomeUnknown('vk_wall_post_replay_not_proven_safe')
            group = await self._rights(request)
            attachments, native_media = await self._stage_images(
                request, group, hooks
            )
            checkpoint['media'] = native_media
            checkpoint['retryable_wall_post'] = bool(
                len(attachments) == len(native_media)
                and all(saved == native for saved, native in zip(attachments, native_media))
            )
            await hooks.checkpoint('vk_prepared', saved_checkpoint(request, **checkpoint))

        params = {
            'owner_id': int(request.native_target),
            'message': text,
            'publish_date': int(parse_time(request.scheduled_at)),
            'from_group': 1,
            'signed': 0,
            'guid': digest([request.operation_id, request.attempt_id]),
        }
        if attachments:
            params['attachments'] = ','.join(attachments)
        await hooks.emit_progress(
            'submitting', 'started',
            'VK postponed queue has no exact frozen item; replaying the same idempotency key',
        )
        response = await self._wall_post_same_guid(request, params, hooks)
        ident = response.get('post_id') if isinstance(response, dict) else None
        if type(ident) is not int or ident <= 0:
            raise OutcomeUnknown('vk_response_identity_missing')
        checkpoint['id'] = str(ident)
        await hooks.checkpoint('vk_response', saved_checkpoint(request, **checkpoint))
        return await self._observe(request, checkpoint, hooks)

    async def reconcile(self, request: ProviderRequest, checkpoint: str, hooks: Hooks) -> Observation:
        self._connection(request)
        state = load_checkpoint(request, checkpoint)
        if request.surface == 'story':
            return await self._observe_story(request, state, hooks)
        if not state.get('id') and request.action == 'publish' and request.scheduled_at:
            return await self._recover_missing_scheduled_publish(request, state, hooks)
        return await self._observe(request, state, hooks)

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