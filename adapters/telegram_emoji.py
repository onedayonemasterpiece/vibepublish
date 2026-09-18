"""Native metadata/eligibility reads for Telegram custom emoji, no subscription writes."""
from __future__ import annotations
import io
import math
from types import SimpleNamespace
from PIL import Image
from social_operations.domain import DomainError, canonical
from social_operations.rich_text import document_id, valid_alt, provider_content, telegram_text_limit


class BoundedPreview(io.BytesIO):
    def write(self, data):
        if self.tell()+len(data) > 2*1024*1024:
            raise DomainError('emoji_preview_size_limit')
        return super().write(data)


def metadata(doc):
    attrs = [a for a in getattr(doc, 'attributes', ()) if type(a).__name__ == 'DocumentAttributeCustomEmoji']
    if len(attrs) != 1 or type(getattr(doc, 'id', None)) is not int:
        raise DomainError('emoji_document_unavailable')
    attr = attrs[0]
    return {'document_id': document_id(str(doc.id)), 'alt': valid_alt(attr.alt),
            'free': bool(getattr(attr, 'free', False))}, attr


def config_value(value):
    kind = type(value).__name__
    if kind == 'JsonObject':
        return {v.key: config_value(v.value) for v in value.value}
    if kind in {'JsonNumber', 'JsonString', 'JsonBool'}:
        return value.value
    if kind == 'JsonArray':
        return [config_value(v) for v in value.value]
    if kind == 'JsonNull':
        return None
    raise DomainError('telegram_config_needs_review')


async def check_custom(adapter, request):
    text, entities = provider_content(request.content_json, telegram_text_limit(request))
    selected = [e for e in entities if e['type'] == 'custom_emoji']
    if not selected:
        return
    if adapter.account_type != 'mtproto_user':
        raise DomainError('telegram_bot_custom_emoji_needs_review')
    me = await adapter.client.get_me()
    result = await adapter._call('app_config', hash=0)
    config = config_value(result.config)
    maximum = config.get('message_animated_emoji_max') if isinstance(config, dict) else None
    if type(maximum) not in {int, float} or not math.isfinite(maximum) or maximum != int(maximum) or not 1 <= maximum <= 10000:
        raise DomainError('telegram_emoji_limit_unknown')
    if len(selected) > maximum:
        raise DomainError('telegram_custom_emoji_limit')
    ids = list(dict.fromkeys(e['document_id'] for e in selected))
    docs = await adapter._call('emoji_documents', document_id=[int(i) for i in ids])
    if not isinstance(docs, (list, tuple)) or len(docs) != len(ids):
        raise DomainError('emoji_document_unavailable')
    observed = {}
    for doc in docs:
        item, _ = metadata(doc)
        if item['document_id'] in observed:
            raise DomainError('emoji_document_unavailable')
        observed[item['document_id']] = item
    if set(observed) != set(ids):
        raise DomainError('emoji_document_unavailable')
    encoded = text.encode('utf-16-le')
    for e in selected:
        item = observed[e['document_id']]
        alt = encoded[2*e['offset']:2*(e['offset']+e['length'])].decode('utf-16-le')
        if alt != item['alt']:
            raise DomainError('emoji_alt_metadata_changed', next_action='refresh')
        if not item['free'] and not getattr(me, 'premium', False):
            raise DomainError('telegram_custom_emoji_premium_required')


async def load_set(adapter, short_name, target):
    # Metadata access stays bounded to the same authorized publishing connection.
    request = SimpleNamespace(connection_id=adapter.connection_id, account_type=adapter.account_type,
        native_target=target, action='publish', scheduled_at=None, existing=None)
    await adapter._rights(request)
    result = await adapter._call('emoji_set', stickerset=adapter.tl.type('InputStickerSetShortName', short_name=short_name), hash=0)
    pack = getattr(result, 'set', None)
    docs = getattr(result, 'documents', None)
    if (not pack or not getattr(pack, 'emojis', False) or not isinstance(docs, (list, tuple))
            or not 1 <= len(docs) <= 200 or getattr(pack, 'short_name', '').lower() != short_name.lower()):
        raise DomainError('emoji_set_type_or_size')
    entries = []
    total = 0
    for doc in docs:
        item, attr = metadata(doc)
        if getattr(getattr(attr, 'stickerset', None), 'id', None) != pack.id:
            raise DomainError('emoji_document_set_mismatch')
        if type(getattr(doc, 'size', None)) is not int or not 0 < doc.size <= 20*1024*1024:
            raise DomainError('emoji_document_size_limit')
        static = getattr(doc, 'mime_type', '') in {'image/webp', 'image/png', 'image/jpeg'}
        if not static and not getattr(doc, 'thumbs', None):
            raise DomainError('emoji_preview_unavailable', next_action='refresh')
        stream = BoundedPreview()
        await adapter.client.download_media(doc, file=stream, **({} if static else {'thumb': -1}))
        data = stream.getvalue()
        total += len(data)
        if total > 16*1024*1024:
            raise DomainError('emoji_preview_total_limit')
        try:
            with Image.open(io.BytesIO(data)) as image:
                mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}[image.format]
        except (OSError, KeyError):
            raise DomainError('emoji_preview_unavailable') from None
        entries.append({**item, 'preview': data, 'preview_mime': mime})
    return {'short_name': pack.short_name, 'is_emoji': True, 'entries': entries}
