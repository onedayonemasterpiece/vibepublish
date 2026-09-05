"""Deterministic trusted rich-text compiler; public callers never supply spans/IDs.

Offsets are UTF-16 units. No normalization of Telegram's exact alt strings, no
post-send editing, no defaults imported from a different account's palette.
"""
from __future__ import annotations
import copy
import json
import re
import unicodedata
from .domain import DomainError, canonical

ENTITY_TYPES = {
    'bold': 'MessageEntityBold', 'italic': 'MessageEntityItalic',
    'code': 'MessageEntityCode', 'pre': 'MessageEntityPre',
    'spoiler': 'MessageEntitySpoiler', 'underline': 'MessageEntityUnderline',
    'strikethrough': 'MessageEntityStrike', 'text_link': 'MessageEntityTextUrl',
    'url': 'MessageEntityUrl', 'mention': 'MessageEntityMention',
    'custom_emoji': 'MessageEntityCustomEmoji',
}
REVERSE_TYPES = {v: k for k, v in ENTITY_TYPES.items()}


def utf16(text: str) -> int:
    try:
        return len(text.encode('utf-16-le')) // 2
    except (UnicodeError, AttributeError):
        raise DomainError('invalid_unicode') from None


def document_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value) or int(value) >= 2**63:
        raise DomainError('emoji_document_id_invalid')
    return value


def _extension(char):
    n = ord(char)
    return (unicodedata.category(char).startswith('M') or n in {0x200d, 0x20e3}
            or 0xfe00 <= n <= 0xfe0f or 0x1f3fb <= n <= 0x1f3ff
            or 0xe0020 <= n <= 0xe007f or 0xe0100 <= n <= 0xe01ef)


def _ri(char):
    return 0x1f1e6 <= ord(char) <= 0x1f1ff


def boundary(text, i):
    """Conservative emoji boundary gate, not a general Unicode text segmenter."""
    if i == 0 or i == len(text):
        return True
    if _extension(text[i]) or text[i-1] == '\u200d':
        return False
    # Reject splitting flag runs even if the selected pair would be a valid flag.
    return not (_ri(text[i-1]) and _ri(text[i]))


def valid_alt(alt):
    if (not isinstance(alt, str) or not alt or utf16(alt) > 64 or
            any(c.isspace() or unicodedata.category(c) == 'Cc' for c in alt) or
            _extension(alt[0]) or alt.endswith('\u200d')):
        raise DomainError('emoji_alt_invalid')
    return alt


def normalized_entities(text, entities):
    """Canonical semantic observation; reject unknown or malformed entities."""
    utf16(text)
    boundaries, offset = {0}, 0
    for char in text:
        offset += 2 if ord(char) > 0xffff else 1
        boundaries.add(offset)
    result = []
    for raw in entities:
        if not isinstance(raw, dict):
            raise DomainError('rich_entity_invalid')
        e = dict(raw)
        kind = e.get('type')
        extra = {'document_id'} if kind == 'custom_emoji' else {'url'} if kind == 'text_link' else {'language'} if kind == 'pre' else set()
        if kind not in ENTITY_TYPES or set(e) != {'type', 'offset', 'length'} | extra:
            raise DomainError('rich_entity_unsupported')
        a, n = e['offset'], e['length']
        if (type(a) is not int or type(n) is not int or n <= 0 or
                a not in boundaries or a+n not in boundaries):
            raise DomainError('rich_entity_span_invalid')
        if kind == 'custom_emoji':
            document_id(e['document_id'])
        if kind == 'text_link' and (not isinstance(e['url'], str) or not re.match(r'^https?://[^\s]+$', e['url'])):
            raise DomainError('rich_link_invalid')
        if kind == 'pre' and not isinstance(e['language'], str):
            raise DomainError('rich_entity_invalid')
        if e in result:
            raise DomainError('rich_entity_duplicate')
        result.append(e)
    result.sort(key=lambda e: (e['offset'], -e['length'], e['type'], canonical(e)))
    for i, x in enumerate(result):
        a, b = x['offset'], x['offset']+x['length']
        for y in result[i+1:]:
            c, d = y['offset'], y['offset']+y['length']
            if c >= b:
                break
            if x['type'] == y['type'] == 'custom_emoji' or (a < c < b < d):
                raise DomainError('rich_entity_overlap')
            if ('code' in {x['type'], y['type']} or 'pre' in {x['type'], y['type']}) and a < d and c < b:
                raise DomainError('rich_code_overlap')
    return result


def from_native(text, entities):
    result = []
    for native in entities or ():
        kind = REVERSE_TYPES.get(type(native).__name__)
        if kind is None:
            raise DomainError('telegram_entity_needs_review')
        e = {'type': kind, 'offset': native.offset, 'length': native.length}
        if kind == 'custom_emoji':
            e['document_id'] = str(native.document_id)
        elif kind == 'text_link':
            e['url'] = native.url
        elif kind == 'pre':
            e['language'] = native.language
        result.append(e)
    return normalized_entities(text, result)


def to_native(text, entities, tl):
    result = []
    for e in normalized_entities(text, entities):
        args = {k: v for k, v in e.items() if k != 'type'}
        if e['type'] == 'custom_emoji':
            args['document_id'] = int(args['document_id'])
        result.append(tl.type(ENTITY_TYPES[e['type']], **args))
    return result


def telegram_text_limit(request):
    # An edit/reschedule may preserve externally observed native media without
    # staging any source assets. That is still a caption, not a text message.
    existing = getattr(request, 'existing', None)
    return 1024 if request.assets or (existing and existing.provider_media) else 4096


def provider_content(content_json, limit):
    c = json.loads(content_json)
    if not isinstance(c, dict) or not isinstance(c.get('text'), str):
        raise DomainError('rich_content_invalid')
    if c.get('format', 'plain') == 'plain':
        if set(c) - {'text', 'format'}:
            raise DomainError('rich_content_invalid')
        entities = []
    elif c.get('format') == 'telegram_entities':
        if set(c) - {'text', 'format', 'entities', 'emoji_snapshot'}:
            raise DomainError('rich_content_invalid')
        entities = normalized_entities(c['text'], c.get('entities', []))
    else:
        raise DomainError('rich_content_needs_review')
    if utf16(c['text']) > limit:
        raise DomainError('provider_text_limit')
    return c['text'], entities


def compile_content(content, resolve, rules=(), *, provider='telegram', fallback=False, context=None):
    """Return immutable-by-value compilation; frozen internal input is never re-expanded."""
    c = copy.deepcopy(content)
    if c.get('format') == 'telegram_entities':
        provider_content(canonical(c), 32768)
        return c
    if 'text' in c and c.get('format', 'plain') != 'plain':
        raise DomainError('rich_content_needs_review')
    text, entities, snapshots = '', [], []
    def expand(alias):
        value = resolve(alias)
        if not value or not value.get('parts'):
            raise DomainError('emoji_alias_missing', next_action='refresh')
        parts = value['parts']
        if not 1 <= len(parts) <= 16:
            raise DomainError('emoji_chain_limit')
        for p in parts:
            document_id(p['document_id']); valid_alt(p['alt'])
        snapshots.append(copy.deepcopy(value))
        if provider != 'telegram':
            if not fallback or not value.get('fallback'):
                raise DomainError('emoji_fallback_required')
            return value['fallback'], []
        local, output = '', []
        for part in parts:
            output.append({'type': 'custom_emoji', 'offset': utf16(local),
                           'length': utf16(part['alt']), 'document_id': part['document_id']})
            local += part['alt']
        return local, output
    if 'text' in c:
        text = c['text']
    else:
        for number, paragraph in enumerate(c.get('paragraphs', [])):
            if number:
                text += '\n\n'
            for run in paragraph:
                start = utf16(text)
                if run['kind'] == 'text':
                    value = run['text']; style = run.get('style', 'normal')
                    if style != 'normal' and value:
                        if provider != 'telegram':
                            raise DomainError('rich_fallback_needs_review')
                        entities.append({'type': style, 'offset': start, 'length': utf16(value)})
                    text += value
                elif run['kind'] == 'link':
                    if provider != 'telegram':
                        raise DomainError('rich_fallback_needs_review')
                    value = run['label']
                    entities.append({'type': 'text_link', 'offset': start, 'length': utf16(value), 'url': run['url']})
                    text += value
                elif run['kind'] == 'emoji':
                    value, extra = expand(run['alias'])
                    entities.extend({**e, 'offset': e['offset']+start} for e in extra)
                    text += value
                else:
                    raise DomainError('rich_mention_needs_review')
    if utf16(text) > 32768:
        raise DomainError('rich_content_limit')
    if provider == 'telegram':
        candidates = []
        protected = [(e['offset'], e['offset']+e['length']) for e in entities
                     if e['type'] in {'custom_emoji', 'code', 'pre', 'url', 'mention'}]
        protected += [(utf16(text[:m.start()]), utf16(text[:m.end()]))
                      for m in re.finditer(r'https?://\S+|(?<!\w)@[\w]+', text)]
        active = [r for r in rules if r.get('enabled', True) and
                  all((context or {}).get(k) == v for k, v in r.get('context', {}).items())]
        for rule in active:
            trigger = rule['match']
            if not trigger:
                raise DomainError('emoji_rule_empty')
            for m in re.finditer(re.escape(trigger), text):
                a, b = m.span(); u, v = utf16(text[:a]), utf16(text[:b])
                if not boundary(text, a) or not boundary(text, b):
                    continue
                if (trigger[0].isalnum() and a and (text[a-1].isalnum() or text[a-1]=='_')) or (trigger[-1].isalnum() and b < len(text) and (text[b].isalnum() or text[b]=='_')):
                    continue
                if any(u < y and x < v for x, y in protected):
                    continue
                candidates.append((a, b, rule))
        selected = []
        for a, b, rule in sorted(candidates, key=lambda x: (-(x[1]-x[0]), x[0], x[2]['alias'])):
            overlaps = [(x, y, r) for x, y, r in selected if a < y and x < b]
            if overlaps:
                if any(b-a == y-x for x, y, _ in overlaps):
                    raise DomainError('emoji_rule_ambiguous')
                continue
            selected.append((a, b, rule))
        # Right-to-left replacements leave original text indices stable.
        for a, b, rule in sorted(selected, reverse=True, key=lambda v: v[0]):
            u, v = utf16(text[:a]), utf16(text[:b])
            value, extra = expand(rule['alias'])
            snapshots[-1]['rule_revision'] = rule.get('revision', 1)
            delta = utf16(value)-(v-u)
            adjusted = []
            for e in entities:
                x, y = e['offset'], e['offset']+e['length']
                if y <= u:
                    adjusted.append(e)
                elif x >= v:
                    adjusted.append({**e, 'offset': x+delta})
                elif x <= u and y >= v:
                    adjusted.append({**e, 'length': e['length']+delta})
                else:
                    raise DomainError('emoji_format_overlap')
            entities = adjusted + [{**e, 'offset': e['offset']+u} for e in extra]
            text = text[:a]+value+text[b:]
    entities = normalized_entities(text, entities)
    if not entities and not snapshots:
        return {'text': text}
    if provider != 'telegram':
        return {'text': text}  # Explicit semantic fallback, not Telegram alt glyphs.
    return {'text': text, 'format': 'telegram_entities', 'entities': entities,
            'emoji_snapshot': snapshots}
