"""Native Telegram MTProto adapter, independently wired (never an EventsBot import).

Ported behavior/provenance: docs/reference/native-adapter-provenance.md.
The injected client must be authenticated by trusted wiring with automatic RPC
retries disabled. The SDK is lazy; scripted tests exercise these exact TL calls.
Bot API and Business connections are different capability families, not aliases.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .native import (bind_media, identity, load_checkpoint, plain_text, same_existing,
                     saved_checkpoint, schedule_guard, verify_assets)
from .port import Capability, Hooks, Observation, Prepared, ProviderRequest, ReadPage, ReadRequest, RemoteItem
from social_operations.domain import DomainError, OutcomeUnknown, canonical, digest, parse_time, timestamp

_REQUESTS = {
    'emoji_set': ('messages', 'GetStickerSetRequest'),
    'emoji_documents': ('messages', 'GetCustomEmojiDocumentsRequest'),
    'app_config': ('help', 'GetAppConfigRequest'),
    'scheduled': ('messages', 'GetScheduledHistoryRequest'),
    'history': ('messages', 'GetHistoryRequest'),
    'upload': ('messages', 'UploadMediaRequest'),
    'send_text': ('messages', 'SendMessageRequest'),
    'send_media': ('messages', 'SendMediaRequest'),
    'send_album': ('messages', 'SendMultiMediaRequest'),
    'forward': ('messages', 'ForwardMessagesRequest'),
    'edit': ('messages', 'EditMessageRequest'),
    'cancel': ('messages', 'DeleteScheduledMessagesRequest'),
    'delete_channel': ('channels', 'DeleteMessagesRequest'),
    'delete_messages': ('messages', 'DeleteMessagesRequest'),
}
from social_operations.rich_text import ENTITY_TYPES, from_native, to_native, provider_content, telegram_text_limit
from .telegram_emoji import check_custom, load_set
_TYPES = {'InputMediaUploadedPhoto', 'InputPhoto', 'InputMediaPhoto', 'InputSingleMedia', 'InputStickerSetShortName'} | set(ENTITY_TYPES.values())


class TelethonTypes:
    """Fixed compiler; none of its names/kwargs are model-facing API parameters."""
    def __init__(self):
        try:
            import telethon
            from telethon import functions, types
        except ImportError:
            raise DomainError('telegram_sdk_missing', next_action='contact_owner') from None
        if not (telethon.__version__.split('.')[:2] == ['1', '44']):
            raise DomainError('telegram_sdk_version_needs_review', next_action='contact_owner')
        self.functions, self.types = functions, types

    def request(self, kind: str, **values: Any):
        namespace, name = _REQUESTS[kind]
        return getattr(getattr(self.functions, namespace), name)(**values)

    def type(self, name: str, **values: Any):
        if name not in _TYPES:
            raise DomainError('telegram_type_not_allowed')
        return getattr(self.types, name)(**values)


def peer_key(value: Any) -> str:
    """Use the observed native peer, never echo a requested target as evidence."""
    if getattr(value, 'channel_id', None) is not None:
        return str(-1_000_000_000_000 - int(value.channel_id))
    if getattr(value, 'chat_id', None) is not None:
        return str(-int(value.chat_id))
    if getattr(value, 'user_id', None) is not None:
        return str(int(value.user_id))
    ident = getattr(value, 'id', None)
    if type(ident) is not int or ident <= 0:
        raise DomainError('telegram_peer_invalid')
    name = type(value).__name__
    if hasattr(value, 'broadcast') or hasattr(value, 'megagroup') or name.startswith('Channel'):
        return str(-1_000_000_000_000 - ident)
    if name.startswith('Chat'):
        return str(-ident)
    if hasattr(value, 'bot') or name.startswith('User'):
        return str(ident)
    raise DomainError('telegram_peer_invalid')


def _date(value: Any) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DomainError('telegram_date_invalid')
    return timestamp(value.timestamp())


def _id(message: Any) -> str:
    ident = getattr(message, 'id', None)
    if type(ident) is not int or ident <= 0:
        raise DomainError('telegram_message_invalid')
    return str(ident)


def _media(message: Any) -> tuple[str, ...]:
    media = getattr(message, 'media', None)
    if not media:
        return ()
    photo = getattr(media, 'photo', None)
    document = getattr(media, 'document', None)
    if photo and type(getattr(photo, 'id', None)) is int:
        return ('photo:' + str(photo.id),)
    if document and type(getattr(document, 'id', None)) is int:
        return ('document:' + str(document.id),)
    # A webpage preview is not an uploaded asset; other media must not disappear.
    if type(media).__name__ == 'MessageMediaWebPage':
        return ()
    raise DomainError('telegram_media_needs_review', next_action='contact_owner')


class TelegramAdapter:
    def __init__(self, client, *, connection_id: str, account_type='mtproto_user', tl=None, clock=time.time):
        self.client = client
        self.connection_id = connection_id
        self.account_type = account_type
        self.tl = tl or TelethonTypes()
        self.clock = clock

    def _connection(self, request):
        if request.connection_id != self.connection_id:
            raise DomainError('connection_mismatch')
        if self.account_type not in {'mtproto_user', 'mtproto_bot'}:
            raise DomainError('telegram_account_type_needs_review', next_action='contact_owner')
        if hasattr(request, 'account_type') and request.account_type != self.account_type:
            raise DomainError('telegram_account_type_mismatch')

    async def _call(self, kind: str, **values):
        # Exactly one RPC. RPC retry/flood sleeps are disabled in trusted wiring.
        try:
            return await self.client(self.tl.request(kind, **values))
        except DomainError:
            raise
        except Exception as exc:
            name = type(exc).__name__
            code = ('telegram_cooldown' if name in {'FloodWaitError', 'SlowModeWaitError'} else
                    'telegram_auth_required' if name in {'AuthKeyUnregisteredError', 'SessionRevokedError'} else
                    'telegram_rpc_failed')
            raise DomainError(code, next_action='contact_owner') from None

    async def _entity(self, target: str):
        if not re.fullmatch(r'-?[1-9][0-9]*', target):
            raise DomainError('telegram_numeric_binding_required', next_action='contact_owner')
        entity = await self.client.get_entity(int(target))
        if peer_key(entity) != target:
            raise DomainError('telegram_peer_mismatch')
        return entity

    async def _rights(self, request):
        self._connection(request)
        me = await self.client.get_me()
        if me is None or bool(getattr(me, 'bot', False)) != (self.account_type == 'mtproto_bot'):
            raise DomainError('telegram_account_type_mismatch')
        entity = await self._entity(request.native_target)
        if getattr(entity, 'left', False) or getattr(entity, 'kicked', False):
            raise DomainError('provider_access_denied')
        if (request.scheduled_at or (request.existing and request.existing.namespace == 'scheduled')) and self.account_type != 'mtproto_user':
            raise DomainError('telegram_bot_native_schedule_unsupported')
        if request.action in {'edit', 'reschedule', 'cancel', 'delete'}:
            required = 'delete_messages' if request.action in {'cancel', 'delete'} else 'edit_messages'
        else:
            required = 'post_messages'
        if getattr(entity, 'broadcast', False):
            permissions = await self.client.get_permissions(entity, me)
            if not (getattr(permissions, 'is_creator', False) or getattr(permissions, required, False)):
                raise DomainError('provider_access_denied')
        elif getattr(entity, 'megagroup', False) or type(entity).__name__.startswith('Chat'):
            # Basic-chat ownership is explicit native evidence, not a channel's
            # post_messages permission. Keep every other group mutation gated.
            if not (type(entity).__name__ == 'Chat'
                    and getattr(entity, 'creator', False) is True
                    and not getattr(entity, 'megagroup', False)
                    and not getattr(entity, 'deactivated', False)
                    and getattr(entity, 'migrated_to', None) is None
                    and self.account_type == 'mtproto_user'
                    and request.action == 'publish' and request.surface == 'post'
                    and request.existing is None and request.scheduled_at is None
                    and request.source is None):
                raise DomainError('telegram_group_mutations_needs_review', next_action='contact_owner')
        elif peer_key(entity) != peer_key(me):
            raise DomainError('telegram_direct_messages_needs_review', next_action='contact_owner')
        return entity

    async def inspect(self, request: ProviderRequest) -> Capability:
        try:
            if request.surface != 'post':
                raise DomainError('telegram_surface_needs_review')
            if request.action not in {'publish', 'forward', 'edit', 'reschedule', 'cancel', 'delete'}:
                raise DomainError('telegram_action_unsupported')
            provider_content(request.content_json, telegram_text_limit(request))
            verify_assets(request)
            schedule_guard(request, self.clock())
            await self._rights(request)
            await check_custom(self, request)
            if request.existing:
                if request.existing.native_target != request.native_target:
                    raise DomainError('remote_target_mismatch')
                if request.existing.namespace not in {'scheduled', 'published'}:
                    raise DomainError('telegram_namespace_unsupported')
                if request.action in {'edit', 'reschedule'} and len(request.existing.member_ids) > 1:
                    raise DomainError('telegram_album_edit_needs_review')
                if request.action == 'cancel' and request.existing.namespace != 'scheduled':
                    raise DomainError('cancel_requires_native_queue')
                if request.action == 'delete' and request.existing.namespace != 'published':
                    raise DomainError('delete_requires_published')
                if request.action == 'reschedule' and request.existing.namespace != 'scheduled':
                    raise DomainError('reschedule_requires_native_queue')
            elif request.action not in {'publish', 'forward'}:
                raise DomainError('remote_item_required')
        except DomainError as exc:
            return Capability('unsupported', exc.code, evidence='not_canary_verified')
        return Capability('supported', 'Scoped account/target preflight; live canary not performed',
                          evidence='provider_read_preflight_only')

    async def _scheduled(self, entity):
        result = await self._call('scheduled', peer=entity, hash=0)
        messages = getattr(result, 'messages', None)
        if not isinstance(messages, (list, tuple)) or len(messages) > 1000:
            raise DomainError('telegram_queue_response_invalid')
        return list(messages)

    async def _history(self, entity, *, offset=0, limit=100):
        result = await self._call('history', peer=entity, offset_id=offset, offset_date=None,
                                  add_offset=0, limit=limit, max_id=0, min_id=0, hash=0)
        messages = getattr(result, 'messages', None)
        if not isinstance(messages, (list, tuple)) or len(messages) > limit:
            raise DomainError('telegram_history_response_invalid')
        return list(messages)

    def _groups(self, messages, target: str):
        groups = {}
        seen = set()
        for message in messages:
            if peer_key(getattr(message, 'peer_id', None)) != target:
                raise DomainError('telegram_read_target_mismatch')
            ident = _id(message)
            if ident in seen:
                raise DomainError('telegram_duplicate_message')
            seen.add(ident)
            group = getattr(message, 'grouped_id', None)
            key = ('album', group) if group is not None else ('message', ident)
            groups.setdefault(key, []).append(message)
        result = [sorted(members, key=lambda m: int(_id(m))) for members in groups.values()]
        if any(len(members) > 10 for members in result):
            raise DomainError('telegram_album_invalid')
        return sorted(result, key=lambda members: int(_id(members[0])), reverse=True)

    def _item(self, members, namespace: str, target: str, *, source=None, source_peer=None):
        texts = [getattr(m, 'message', '') or '' for m in members]
        nonempty = [t for t in texts if t]
        if len(nonempty) > 1:
            raise DomainError('telegram_multi_caption_needs_review')
        text = nonempty[0] if nonempty else ''
        dates = [_date(m.date) for m in members]
        if namespace == 'scheduled' and len(set(dates)) != 1:
            raise DomainError('telegram_album_time_mismatch')
        origin = None
        if source:
            for m in members:
                fwd = getattr(m, 'fwd_from', None)
                if (fwd is None or peer_key(getattr(fwd, 'from_id', None)) != source_peer
                        or str(getattr(fwd, 'channel_post', '')) not in source['ids']):
                    raise OutcomeUnknown('telegram_forward_origin_mismatch')
            origin = source['url']
        else:
            fwd = getattr(members[0], 'fwd_from', None)
            if fwd and getattr(fwd, 'channel_post', None) and getattr(getattr(fwd, 'from_id', None), 'channel_id', None):
                origin = f'https://t.me/c/{fwd.from_id.channel_id}/{fwd.channel_post}'
        metrics = tuple((name, float(value), 'count') for name, value in (
            ('views', getattr(members[0], 'views', None)), ('shares', getattr(members[0], 'forwards', None)))
                        if type(value) is int and value >= 0)
        item = RemoteItem(_id(members[0]), namespace, text, '', timestamp(self.clock()),
                          scheduled_at=dates[0] if namespace == 'scheduled' else None,
                          native_target=target, origin=origin, metrics=metrics,
                          provider_media=tuple(x for m in members for x in _media(m)),
                          member_ids=tuple(_id(m) for m in members),
                          entities_json=canonical(from_native(text, getattr(next((m for m in members if getattr(m, 'message', '')), members[0]), 'entities', ()))))
        return replace(item, fingerprint=identity(item))

    async def _exact(self, entity, remote: RemoteItem):
        if remote.namespace == 'scheduled':
            raw = await self._scheduled(entity)
        else:
            ids = [int(i) for i in (remote.member_ids or (remote.native_id,))]
            raw = await self.client.get_messages(entity, ids=ids)
            raw = [m for m in raw if m is not None and getattr(m, 'peer_id', None) is not None]
        groups = self._groups(raw, peer_key(entity))
        matches = [g for g in groups if remote.native_id in {_id(m) for m in g}]
        if not matches:
            return None
        if len(matches) != 1:
            raise OutcomeUnknown('telegram_ambiguous_item')
        return self._item(matches[0], remote.namespace, peer_key(entity))

    async def _source(self, request):
        source = request.source
        if source is None or source.provider != 'telegram':
            raise DomainError('telegram_source_required')
        if not source.public_candidate and not request.source_authorized:
            raise DomainError('source_access_denied')
        entity = (await self.client.get_entity(source.channel) if source.public_candidate
                  else await self._entity(source.channel))
        if source.public_candidate:
            if (not getattr(entity, 'broadcast', False) and not getattr(entity, 'megagroup', False)
                    or (getattr(entity, 'username', '') or '').lower() != source.channel.lower()):
                raise DomainError('source_not_public')
        if getattr(entity, 'noforwards', False):
            raise DomainError('protected_content')
        # Exact link lookup only. Neighbours are bounded solely to resolve its album.
        message = await self.client.get_messages(entity, ids=int(source.item))
        if message is None or _id(message) != source.item or peer_key(message.peer_id) != peer_key(entity):
            raise DomainError('source_not_found')
        members = [message]
        if request.selection == 'post' and getattr(message, 'grouped_id', None):
            nearby = await self.client.get_messages(entity, ids=list(range(max(1, int(source.item)-10), int(source.item)+11)))
            members = sorted([m for m in nearby if m is not None and getattr(m, 'grouped_id', None) == message.grouped_id], key=lambda m: int(_id(m)))
        if not members or len(members) > 10:
            raise DomainError('source_album_invalid')
        for member in members:
            if peer_key(member.peer_id) != peer_key(entity) or getattr(member, 'noforwards', False):
                raise DomainError('protected_content')
            if getattr(member, 'fwd_from', None):
                raise DomainError('forward_chain_attribution_needs_review')
        item = self._item(members, 'published', peer_key(entity))
        return entity, {'ids': [_id(m) for m in members], 'peer': peer_key(entity),
                        'url': source.canonical_url, 'fingerprint': item.fingerprint,
                        'media': list(item.provider_media), 'content_digest': digest([item.text, item.entities_json])}

    async def prepare(self, request: ProviderRequest, hooks: Hooks) -> Prepared:
        capability = await self.inspect(request)
        if capability.status != 'supported':
            raise DomainError(capability.reason, next_action='contact_owner')
        state = {}
        if request.existing:
            current = await self._exact(await self._entity(request.native_target), request.existing)
            if current is None:
                raise DomainError('remote_item_missing', next_action='refresh')
            same_existing(request.existing, current)
        if request.source:
            await hooks.emit_progress('resolving_source', 'started', 'Resolving the exact native source')
            _, state['source'] = await self._source(request)
        return Prepared(request, capability, canonical(state))

    async def execute(self, prepared: Prepared, hooks: Hooks) -> Observation:
        r = prepared.request
        entity = await self._rights(r)
        state = json.loads(prepared.state_json)
        existing = r.existing
        if existing:
            current = await self._exact(entity, existing)
            if current is None:
                raise DomainError('remote_item_missing', next_action='refresh')
            same_existing(existing, current)
            if existing.namespace == 'scheduled' and parse_time(existing.scheduled_at or '') < self.clock()+60:
                raise DomainError('native_item_due_or_expired', next_action='refresh')
        source_entity = None
        if r.source:
            source_entity, checked = await self._source(r)
            if checked != state.get('source'):
                raise DomainError('source_changed', next_action='refresh')
        text, semantic_entities = provider_content(r.content_json, telegram_text_limit(r))
        native_entities = to_native(text, semantic_entities, self.tl)
        native_media, compiled_media = [], []
        if r.action == 'publish' or (r.action == 'edit' and r.assets and tuple(a.sha256 for a in r.assets) != tuple(existing.media_hashes)):
            for ordinal, asset in enumerate(r.assets):
                await hooks.emit_progress('uploading', 'started', f'Staging image {ordinal+1}/{len(r.assets)}')
                stream = io.BytesIO(asset.data)
                stream.name = 'verified.' + {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[asset.mime]
                uploaded = await self.client.upload_file(stream, file_size=asset.size, file_name=stream.name)
                photo_result = await self._call('upload', peer=entity,
                    media=self.tl.type('InputMediaUploadedPhoto', file=uploaded))
                photo = getattr(photo_result, 'photo', None)
                if photo is None or type(getattr(photo, 'id', None)) is not int:
                    raise DomainError('telegram_upload_readback_invalid')
                native_media.append('photo:' + str(photo.id))
                compiled_media.append(self.tl.type('InputMediaPhoto', id=self.tl.type('InputPhoto',
                    id=photo.id, access_hash=photo.access_hash, file_reference=photo.file_reference)))
        elif r.source:
            native_media = state['source']['media']
        elif existing:
            native_media = list(existing.provider_media)
            if r.action == 'edit' and len(r.assets) != len(existing.media_hashes):
                raise DomainError('telegram_media_removal_needs_review')
        random_ids = [int.from_bytes(hashlib.sha256(f'{r.attempt_id}:{n}'.encode()).digest()[:8], 'big') & ((1 << 63)-1) or 1
                      for n in range(len(state['source']['ids']) if r.source else max(1, len(r.assets)))]
        ids = list(existing.member_ids or (existing.native_id,)) if existing else []
        checkpoint = {'ids': ids, 'media': native_media, 'source': state.get('source'), 'random_ids': random_ids}
        await hooks.checkpoint('telegram_prepared', saved_checkpoint(r, **checkpoint))
        schedule_guard(r, self.clock())
        schedule = datetime.fromtimestamp(parse_time(r.scheduled_at), timezone.utc) if r.scheduled_at else None
        if r.action == 'forward':
            kind, values = 'forward', dict(from_peer=source_entity, id=[int(i) for i in state['source']['ids']],
                random_id=random_ids, to_peer=entity, schedule_date=schedule, drop_author=False, drop_media_captions=False)
        elif r.action in {'cancel', 'delete'}:
            if r.action == 'cancel':
                kind, values = 'cancel', dict(peer=entity, id=[int(i) for i in ids])
            elif int(r.native_target) < -1_000_000_000_000:
                kind, values = 'delete_channel', dict(channel=entity, id=[int(i) for i in ids])
            else:
                kind, values = 'delete_messages', dict(id=[int(i) for i in ids], revoke=True)
        elif r.action in {'edit', 'reschedule'}:
            kind, values = 'edit', dict(peer=entity, id=int(existing.native_id), message=text,
                                      schedule_date=schedule, no_webpage=True, entities=native_entities)
            if compiled_media:
                if len(compiled_media) != 1:
                    raise DomainError('telegram_album_edit_needs_review')
                values['media'] = compiled_media[0]
        elif len(compiled_media) > 1:
            kind, values = 'send_album', dict(peer=entity, schedule_date=schedule, multi_media=[
                self.tl.type('InputSingleMedia', media=media, random_id=random_ids[i], message=text if i == 0 else '', entities=native_entities if i == 0 else [])
                for i, media in enumerate(compiled_media)])
        elif compiled_media:
            kind, values = 'send_media', dict(peer=entity, media=compiled_media[0], message=text,
                random_id=random_ids[0], schedule_date=schedule, entities=native_entities)
        else:
            kind, values = 'send_text', dict(peer=entity, message=text, random_id=random_ids[0],
                schedule_date=schedule, no_webpage=True, entities=native_entities)
        await check_custom(self, r)
        schedule_guard(r, self.clock())
        await hooks.before_effect(r.attempt_id, r.plan_digest)
        response = await self._call(kind, **values)
        if not ids:
            mapping = {getattr(u, 'random_id', None): getattr(u, 'id', None) for u in getattr(response, 'updates', [])
                       if type(u).__name__ == 'UpdateMessageID'}
            ids = [str(mapping[n]) for n in random_ids if type(mapping.get(n)) is int and mapping[n] > 0]
            if len(ids) != len(random_ids):
                if len(random_ids) == 1 and type(response).__name__ == 'UpdateShortSentMessage':
                    ids = [_id(response)]
                else:
                    raise OutcomeUnknown('telegram_response_identity_missing')
            if len(set(ids)) != len(ids):
                raise OutcomeUnknown('telegram_duplicate_response_identity')
        if r.action == 'cancel':
            deleted = set()
            for update in getattr(response, 'updates', []):
                if type(update).__name__ != 'UpdateDeleteScheduledMessages' or peer_key(update.peer) != r.native_target:
                    continue
                if getattr(update, 'sent_messages', None):
                    raise OutcomeUnknown('telegram_cancel_raced_publication')
                deleted.update(str(i) for i in update.messages)
            if not set(ids) <= deleted:
                raise OutcomeUnknown('telegram_cancellation_ack_missing')
            checkpoint['cancel_confirmed'] = True
        checkpoint['ids'] = ids
        await hooks.checkpoint('telegram_response', saved_checkpoint(r, **checkpoint))
        return await self._observe(r, checkpoint, hooks)

    async def _observe(self, r, checkpoint, hooks):
        await hooks.emit_progress('reading_back', 'started', 'Reading exact native Telegram identities')
        entity = await self._entity(r.native_target)
        ids = checkpoint.get('ids', [])
        if not ids:
            # Never guess an identity from text and time after a lost mutation response.
            raise OutcomeUnknown('telegram_response_identity_missing')
        namespace = r.existing.namespace if r.action in {'cancel', 'delete'} else 'scheduled' if r.scheduled_at else 'published'
        remote = RemoteItem(ids[0], namespace, '', '', timestamp(self.clock()), native_target=r.native_target, member_ids=tuple(ids))
        if namespace == 'scheduled':
            raw = await self._scheduled(entity)
        else:
            raw = await self.client.get_messages(entity, ids=[int(i) for i in ids])
            raw = [m for m in raw if m is not None and getattr(m, 'peer_id', None) is not None]
        matches = [g for g in self._groups(raw, r.native_target) if any(_id(m) in ids for m in g)]
        if r.action in {'cancel', 'delete'}:
            if matches or (r.action == 'cancel' and not checkpoint.get('cancel_confirmed')):
                raise OutcomeUnknown('telegram_deletion_unconfirmed')
            return Observation('cancelled' if r.action == 'cancel' else 'deleted',
                               (replace(r.existing, observed_at=timestamp(self.clock())),))
        if len(matches) != 1 or tuple(_id(m) for m in matches[0]) != tuple(ids):
            raise OutcomeUnknown('telegram_readback_identity_mismatch')
        source = checkpoint.get('source')
        item = self._item(matches[0], namespace, r.native_target, source=source, source_peer=source['peer'] if source else None)
        if source:
            if digest([item.text, item.entities_json]) != source.get('content_digest'):
                raise OutcomeUnknown('telegram_forward_content_mismatch')
        else:
            expected_text, expected_entities = provider_content(r.content_json, telegram_text_limit(r))
            if item.text != expected_text or json.loads(item.entities_json) != expected_entities:
                raise OutcomeUnknown('telegram_entities_readback_mismatch')
        item = bind_media(r, item, checkpoint['media'])
        return Observation('provider_scheduled' if r.scheduled_at else 'edited' if r.existing else 'published',
                           (item,), forward_origin_matched=bool(source))

    async def emoji_set(self, short_name: str, target: str):
        return await load_set(self, short_name, target)

    async def reconcile(self, request: ProviderRequest, checkpoint: str, hooks: Hooks) -> Observation:
        self._connection(request)
        return await self._observe(request, load_checkpoint(request, checkpoint), hooks)

    async def read(self, request: ReadRequest, hooks: Hooks) -> ReadPage:
        self._connection(request)
        entity = await self._entity(request.native_target)
        if request.kind not in {'scheduled', 'feed', 'item'}:
            raise DomainError('telegram_read_needs_review', next_action='contact_owner')
        if request.kind == 'scheduled' or (request.kind == 'item' and request.namespace == 'scheduled'):
            if self.account_type != 'mtproto_user':
                raise DomainError('telegram_bot_native_queue_unsupported')
            raw = await self._scheduled(entity)
            namespace = 'scheduled'
        elif request.kind == 'item':
            message = await self.client.get_messages(entity, ids=int(request.native_item))
            if message is None:
                return ReadPage(())
            raw = [message]
            if getattr(message, 'grouped_id', None):
                nearby = await self.client.get_messages(entity, ids=list(range(max(1, int(request.native_item)-10), int(request.native_item)+11)))
                raw = [m for m in nearby if m is not None and getattr(m, 'grouped_id', None) == message.grouped_id]
            namespace = 'published'
        else:
            # Keyset history pagination. Load one complete logical item beyond the
            # requested page, so no physical-page boundary truncates an album.
            offset = 0
            if request.cursor:
                try:
                    cursor = json.loads(request.cursor)
                    if cursor['kind'] != 'history' or cursor['target'] != request.native_target or type(cursor['offset_id']) is not int or cursor['offset_id'] <= 0:
                        raise ValueError()
                    offset = cursor['offset_id']
                except (KeyError, TypeError, ValueError):
                    raise DomainError('provider_cursor_stale', next_action='refresh') from None
            raw = []
            for _ in range(6):
                chunk = await self._history(entity, offset=offset, limit=100)
                raw.extend(chunk)
                groups = self._groups(raw, request.native_target)
                at_end = len(chunk) < 100
                if len(groups) > request.limit or at_end:
                    break
                next_offset = min(int(_id(m)) for m in chunk)
                if next_offset == offset:
                    raise DomainError('telegram_history_did_not_advance')
                offset = next_offset
            else:
                raise DomainError('telegram_history_window_needs_review', next_action='contact_owner')
            selected = groups[:request.limit]
            items = tuple(self._item(g, 'published', request.native_target) for g in selected)
            next_cursor = (canonical({'kind': 'history', 'target': request.native_target,
                                      'offset_id': min(int(_id(m)) for m in selected[-1])})
                           if selected and (len(groups) > request.limit or not at_end) else None)
            return ReadPage(items, next_cursor)
        groups = self._groups(raw, request.native_target)
        items = [self._item(g, namespace, request.native_target) for g in groups]
        if request.native_item:
            items = [i for i in items if request.native_item in i.member_ids]
        # Queue snapshots are fetched anew; movement invalidates rather than shifts cursors.
        fingerprint = digest([(i.native_id, i.fingerprint) for i in items])
        offset = 0
        if request.cursor:
            try:
                cursor = json.loads(request.cursor)
                if cursor['snapshot'] != fingerprint or type(cursor['offset']) is not int or cursor['offset'] < 0:
                    raise ValueError()
                offset = cursor['offset']
            except (ValueError, KeyError, TypeError):
                raise DomainError('provider_cursor_stale', next_action='refresh') from None
        page = tuple(items[offset:offset+request.limit])
        cursor = canonical({'snapshot': fingerprint, 'offset': offset+request.limit}) if offset+request.limit < len(items) else None
        return ReadPage(page, cursor)
