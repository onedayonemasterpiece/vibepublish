"""Closed native-adapter helpers. No credentials, retry loop or second ledger.

Observation identity is independent from uploaded bytes: providers may transcode.
Only a proved native-object binding may map an asset SHA to a remote media slot.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from .port import ProviderRequest, RemoteItem
from social_operations.domain import DomainError, OutcomeUnknown, canonical, digest, parse_time


def plain_text(request: ProviderRequest, *, limit: int) -> str:
    content = json.loads(request.content_json)
    if (not isinstance(content, dict) or set(content) - {'text', 'format'} or not isinstance(content.get('text'), str)
            or content.get('format', 'plain') != 'plain'):
        raise DomainError('rich_content_needs_review', next_action='contact_owner')
    if len(content['text'].encode('utf-16-le')) // 2 > limit:
        raise DomainError('provider_text_limit')
    return content['text']


def verify_assets(request: ProviderRequest) -> None:
    if len(request.assets) > 10:
        raise DomainError('provider_media_limit')
    for asset in request.assets:
        if (asset.role not in {'image', 'auto'} or asset.mime not in {'image/png', 'image/jpeg', 'image/webp'}
                or asset.caption or asset.alt_text):
            raise DomainError('media_rendering_needs_review', next_action='contact_owner')
        if (not 0 < asset.size <= 20 * 1024 * 1024 or len(asset.data) != asset.size
                or hashlib.sha256(asset.data).hexdigest() != asset.sha256):
            raise DomainError('asset_integrity')


def schedule_guard(request: ProviderRequest, now: float, *, lead: int = 60) -> None:
    if request.scheduled_at:
        epoch = parse_time(request.scheduled_at)
        # Native APIs have second precision: no hidden rounding of a frozen intent.
        if epoch != int(epoch):
            raise DomainError('native_time_precision', 'Native scheduling requires whole seconds')
        if epoch < now + lead:
            raise DomainError('native_lead_time', 'Native submission window closed; no fallback send')
    if now > request.deadline:
        raise DomainError('command_expired')


def identity(item: RemoteItem) -> str:
    """Content/lifecycle CAS excludes changing view counters and observation time."""
    fields = [item.native_target, item.namespace, item.native_id, item.text,
              item.scheduled_at, list(item.provider_media), list(item.member_ids), item.origin]
    if item.entities_json != '[]':
        from social_operations.rich_text import normalized_entities
        fields.append(normalized_entities(item.text, json.loads(item.entities_json)))
    return digest(fields)


def same_existing(expected: RemoteItem, observed: RemoteItem) -> None:
    if identity(expected) != identity(observed):
        raise DomainError('remote_revision_conflict', 'The native item changed; refresh before editing', 'refresh')


def saved_checkpoint(request: ProviderRequest, **values: Any) -> str:
    return canonical({'version': 1, 'attempt': request.attempt_id, 'plan': request.plan_digest,
                      'target': request.native_target, **values})


def load_checkpoint(request: ProviderRequest, checkpoint: str) -> dict[str, Any]:
    try:
        payload = json.loads(checkpoint)
        payload = payload.get('adapter', payload)
        if (payload['version'] != 1 or payload['attempt'] != request.attempt_id
                or payload['plan'] != request.plan_digest or payload['target'] != request.native_target):
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise OutcomeUnknown('reconcile_checkpoint_invalid') from None
    return payload


def bind_media(request: ProviderRequest, item: RemoteItem, expected_media: list[str]) -> RemoteItem:
    if tuple(item.provider_media) != tuple(expected_media):
        raise OutcomeUnknown('media_identity_or_order_mismatch')
    if request.action == 'forward':
        return item
    if request.assets:
        if len(expected_media) != len(request.assets):
            raise OutcomeUnknown('media_identity_missing')
        hashes = tuple(a.sha256 for a in request.assets)
    else:
        hashes = ()
    return replace(item, media_hashes=hashes,
                   media_check='provider_binding' if expected_media else 'not_applicable')
