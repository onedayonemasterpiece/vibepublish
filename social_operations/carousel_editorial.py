"""Addressed editorial changes inside a single immutable carousel revision."""
from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from contracts.social_mcp_v1 import CAROUSEL_STORY
from .domain import DomainError


def prepare_story(command, previous):
    story = json.loads(previous['story_json']) if previous and previous['story_json'] else None
    if story is not None and 'brief' in command:
        raise DomainError('carousel_editorial_conflict',
                          'Structured story is current; get(story) and use story_changes')
    if 'story' in command:
        if story is not None or 'brief' in command or 'story_changes' in command:
            raise DomainError('carousel_editorial_conflict',
                              'story initializes structured editing once; use story_changes afterwards')
        story = json.loads(json.dumps(command['story']))
    if 'story_changes' in command:
        if story is None or 'brief' in command:
            raise DomainError('carousel_editorial_conflict', 'Initialize story explicitly before story_changes')
        for change in command['story_changes']:
            kind = change['kind']
            if kind == 'narrative_set':
                story['narrative'] = change['text']
                continue
            if kind == 'cards_order':
                cards = {card['id']: card for card in story['cards']}
                if len(change['ids']) != len(cards) or set(change['ids']) != set(cards):
                    raise DomainError('carousel_story_reference', 'cards_order must name every card exactly once')
                story['cards'] = [cards[ident] for ident in change['ids']]
                continue
            collection = {'material_add': 'materials', 'material_remove': 'materials',
                          'point_patch': 'points', 'point_remove': 'points',
                          'card_patch': 'cards', 'card_remove': 'cards'}.get(kind)
            if collection is None:
                raise DomainError('invalid_input')
            items = story[collection]
            item = change['material'] if kind == 'material_add' else change
            index = next((n for n, value in enumerate(items) if value['id'] == item['id']), None)
            if kind.endswith('_remove'):
                if index is None:
                    raise DomainError('carousel_story_reference', 'Cannot remove an unknown stable ID')
                items.pop(index)
            elif kind == 'material_add':
                if index is not None:
                    raise DomainError('carousel_material_immutable', 'Add a new ID with supersedes for a correction')
                items.append(item)
            else:
                # Named fields replace their value; no recursive/universal merge.
                fields = ('id', 'text', 'material_ids', 'modality') if collection == 'points' else ('id', 'text', 'point_ids')
                patch = {key: item[key] for key in fields if key in item}
                if index is None:
                    items.append(patch)
                else:
                    items[index] = {**items[index], **patch}
    if story is None:
        return None
    if not Draft202012Validator(CAROUSEL_STORY).is_valid(story):
        raise DomainError('carousel_story_invalid', 'A new point/card needs all its typed fields')
    ids = {}
    for name in ('materials', 'points', 'cards'):
        ids[name] = {item['id'] for item in story[name]}
        if len(ids[name]) != len(story[name]):
            raise DomainError('carousel_story_reference', 'Stable IDs must be unique within their collection')
    for material in story['materials']:
        for key in ('supersedes', 'continuation_of'):
            if key in material and (material[key] not in ids['materials'] or material[key] == material['id']):
                raise DomainError('carousel_story_reference', 'Material version/continuation must name another material')
    if any(set(point['material_ids']) - ids['materials'] for point in story['points']):
        raise DomainError('carousel_story_reference', 'Point names an unknown material')
    if any(set(card['point_ids']) - ids['points'] for card in story['cards']):
        raise DomainError('carousel_story_reference', 'Card names an unknown point')
    return story
