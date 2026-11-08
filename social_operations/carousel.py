"""Private SVG stories, immutable revisions and ordered exports in the existing ledger."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import time
import threading
from collections import OrderedDict
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from fontTools.misc.transform import Identity
from PIL import Image, ImageDraw, ImageOps

from .assets import (EXPIRED_MEDIA_STORE_ASSET, AssetPreview, FULL_MAX_EDGE, insert_verified_image,
                     render_asset_full, render_asset_preview, verify_image)
from .carousel_compositor import _ASSET, _NUMBER, _XLINK, render_svg, slice_cards, validate_svg
from .carousel_guide import GuideImages, guide, review_questions
from .carousel_references import ReferenceBank
from .domain import DomainError, canonical, digest, new_id, timestamp


# Process-local cache of full rendered canvases, bounded by entries and PNG bytes.
_RENDERED: 'OrderedDict' = OrderedDict()
_RENDERED_MAX = 12
_RENDERED_MAX_BYTES = 128 * 1024 * 1024
_RENDERED_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class ComponentImages:
    metadata: dict
    images: tuple[AssetPreview, ...]


def _placement_transform(value):
    """Parse SVG affine operations; matrix arithmetic stays in fontTools."""
    pattern = r'([A-Za-z]+)\s*\(([^()]*)\)'
    if re.sub(pattern, '', value).strip(' ,\t\r\n'):
        raise ValueError('Unsupported SVG transform')
    transform = Identity
    for name, arguments in re.findall(pattern, value):
        if _NUMBER.sub('', arguments).strip(' ,\t\r\n'):
            raise ValueError('Unsupported SVG transform arguments')
        values = [float(n) for n in _NUMBER.findall(arguments)]
        match name, values:
            case 'matrix', [a, b, c, d, e, f]:
                transform = transform.transform((a, b, c, d, e, f))
            case 'translate', [x]:
                transform = transform.translate(x)
            case 'translate', [x, y]:
                transform = transform.translate(x, y)
            case 'scale', [x]:
                transform = transform.scale(x)
            case 'scale', [x, y]:
                transform = transform.scale(x, y)
            case 'rotate', [angle, *center] if len(center) in (0, 2):
                x, y = center or (0, 0)
                transform = transform.translate(x, y).rotate(math.radians(angle)).translate(-x, -y)
            case 'skewX', [angle]:
                transform = transform.skew(math.radians(angle), 0)
            case 'skewY', [angle]:
                transform = transform.skew(0, math.radians(angle))
            case _:
                raise ValueError('Unsupported SVG transform')
    return transform


def _placement_length(value, viewport):
    match = re.fullmatch(rf'({_NUMBER.pattern})(px|in|cm|mm|pt|pc|%)?', value.strip())
    if not match:
        raise ValueError('Length needs computed CSS, font metrics or intrinsic image dimensions')
    number, unit = match.groups()
    # SVG absolute lengths use CSS's 96 dpi; percentages use the current viewport.
    factor = {'px': 1, 'in': 96, 'cm': 96 / 2.54, 'mm': 96 / 25.4,
              'pt': 96 / 72, 'pc': 16, '%': viewport / 100, None: 1}[unit]
    return float(number) * factor


def _component_placements(svg, width, height):
    """Image placement rectangles, not alpha/clip painted bounds or a second renderer."""
    if not svg:
        return []
    root, groups = ET.fromstring(svg), {}
    css_geometry = r'(?:^|[;{])\s*(?:transform(?:-origin|-box)?|x|y|width|height)\s*:'
    styled = any(node.tag.rsplit('}', 1)[-1] == 'style'
                 and re.search(css_geometry, node.text or '', re.I) for node in root.iter())
    referenced = {node.get('href', node.get('{' + _XLINK + '}href', '')).removeprefix('#') for node in root.iter()
                  if node.tag.rsplit('}', 1)[-1] == 'use'}

    def visit(node, matrix=Identity, transforms=(), unavailable=None):
        tag = node.tag.rsplit('}', 1)[-1]
        own_transform = node.get('transform', '')
        if own_transform:
            transforms = (*transforms, own_transform)
            try:
                matrix = matrix.transform(_placement_transform(own_transform))
            except (ValueError, OverflowError):
                unavailable = 'Unsupported SVG transform'
        if (tag in {'defs', 'symbol', 'pattern', 'mask', 'clipPath'}
                or tag == 'svg' and node is not root or node.get('id') in referenced):
            unavailable = 'Nested or referenced viewport; canvas bounds require a rendered crop'
        if (styled or re.search(css_geometry, node.get('style', ''), re.I)
                or 'transform-origin' in node.attrib or 'transform-box' in node.attrib):
            unavailable = 'CSS geometry is not resolved; inspect the local placement and rendered crop'
        href = node.get('href', node.get('{' + _XLINK + '}href', ''))
        match = _ASSET.fullmatch(href) if tag == 'image' else None
        if match:
            item = groups.setdefault(match[1], {'asset_ref': match[1],
                'element_ids': [], 'classes': [], 'placements': []})
            placement = {}
            if node.get('id'):
                item['element_ids'].append(node.get('id'))
                placement['element_id'] = node.get('id')
            for name in node.get('class', '').split():
                if name not in item['classes']:
                    item['classes'].append(name)
            local = {key: node.get(key, '0' if key in {'x', 'y'} else 'auto')
                     for key in ('x', 'y', 'width', 'height')}
            try:
                if unavailable:
                    raise ValueError(unavailable)
                x, y, w, h = (_placement_length(local[key], axis) for key, axis in
                              zip(local, (width, height, width, height)))
                if w < 0 or h < 0:
                    raise ValueError('Negative image dimensions')
                corners = [matrix.transformPoint(point) for point in
                           ((x, y), (x + w, y), (x, y + h), (x + w, y + h))]
                if not all(math.isfinite(n) for point in corners for n in point):
                    raise ValueError('Non-finite placement bounds')
                xs, ys = zip(*corners)
                placement.update(x=min(xs), y=min(ys), w=max(xs) - min(xs), h=max(ys) - min(ys))
            except (ValueError, OverflowError) as exc:
                placement.update(bounds_unavailable=str(exc)[:160],
                    local={key: value[:256] for key, value in local.items()},
                    transforms=[value[:1024] for value in transforms])
            item['placements'].append(placement)
        for child in node:
            visit(child, matrix, transforms, unavailable)

    visit(root)
    for item in groups.values():
        placements = item['placements']
        if any('bounds_unavailable' in placement for placement in placements):
            item['bounds_unavailable'] = 'See placements; some canvas bounds are unavailable'
        else:
            x, y = min(p['x'] for p in placements), min(p['y'] for p in placements)
            item.update(x=x, y=y, w=max(p['x'] + p['w'] for p in placements) - x,
                        h=max(p['y'] + p['h'] for p in placements) - y)
    return list(groups.values())


class CarouselService:
    def __init__(self, app):
        self.app, self.store = app, app.store

    def _actor(self, db, actor):
        actor = self.store.current(db, actor)
        if 'visual' not in actor.scopes:
            raise DomainError('access_denied', next_action='contact_owner')
        return actor

    def _version(self, db, actor, ident, revision=None):
        actor = self._actor(db, actor)
        params = [ident, actor.tenant_id, actor.principal_id]
        query = 'SELECT * FROM carousel_versions WHERE id=? AND tenant_id=? AND principal_id=?'
        if revision is not None:
            query += ' AND revision=?'
            params.append(revision)
        row = db.execute(query + ' ORDER BY revision DESC LIMIT 1', params).fetchone()
        if not row:
            raise DomainError('carousel_not_available', next_action='refresh')
        self.store.private_operation(db, actor, row['operation_id'])
        return dict(row)

    def command(self, actor, args):
        intent = json.loads(canonical(args))
        intent.pop('request_key', None)
        command = intent['command']
        kind = command['kind']
        if kind == 'get':
            return self.get(actor, command)
        if kind == 'render':
            return self.render(actor, command)
        if kind not in {'create', 'revise', 'export'}:
            raise DomainError('invalid_input')
        started = time.perf_counter()
        if not args.get('request_key'):
            raise DomainError('carousel_request_key_required')
        # Both admission and commit reuse the existing key. Pure rendering happens
        # outside the write transaction; concurrent retries cannot double-commit.
        with self.store.tx() as db:
            actor = self._actor(db, actor)
            op = self.app._replay(db, actor, 'carousel', intent, args, implicit=False)
            row = None if op or kind == 'create' else self._version(
                db, actor, command['carousel_id'], command.get('revision'))
            if not op and kind == 'revise' and row['revision'] != command['expected_revision']:
                raise DomainError('carousel_revision_conflict', next_action='refresh')
        if op:
            return self.store.receipt(actor, op)
        if kind == 'export':
            png = self._render(actor, row)
            images = [verify_image(data, 'image/png') for data in slice_cards(png,
                card_count=row['card_count'], card_width=row['card_width'], card_height=row['card_height'])]
        else:
            scene = self._prepare(actor, command, row)
        with self.store.tx() as db:
            actor = self._actor(db, actor)
            op = self.app._replay(db, actor, 'carousel', intent, args, implicit=False)
            if not op:
                if kind == 'revise':
                    current = self._version(db, actor, command['carousel_id'])
                    if current['revision'] != command['expected_revision']:
                        raise DomainError('carousel_revision_conflict', next_action='refresh')
                elif kind == 'export':
                    self._version(db, actor, row['id'], row['revision'])
                ident = new_id('carousel') if kind == 'create' else row['id']
                revision = 1 if kind == 'create' else row['revision'] + (kind == 'revise')
                result = {'resource_id': ident, 'carousel_id': ident, 'revision': revision,
                          'private': True, 'generation_dispatch': 'not_sent'}
                if kind == 'export':
                    cards = []
                    for index, image in enumerate(images, 1):
                        ref = insert_verified_image(self.store, db, actor, image)
                        cards.append({'index': index, 'asset_ref': ref,
                            'resource_uri': 'vibepublish://assets/' + ref,
                            'sha256': hashlib.sha256(image.data).hexdigest(), 'mime_type': image.mime,
                            'width': image.width, 'height': image.height})
                    result.update(cards=cards, caption=row['caption'],
                        media=[{'source': {'kind': 'asset', 'id': card['asset_ref']}} for card in cards])
                else:
                    result['scene_ready'] = bool(scene['svg'])
                result['duration_ms'] = round((time.perf_counter() - started) * 1000)
                op = self.app._new_operation(db, actor, 'carousel', intent,
                    revision=revision, complete=True, result=result)
                if kind != 'export':
                    # Track each imported asset at its first use in this carousel.
                    previously_used = {r[0] for r in db.execute(
                        "SELECT DISTINCT j.value FROM carousel_versions v, json_each(v.asset_refs) j "
                        "WHERE v.id=? AND v.tenant_id=? AND v.principal_id=?",
                        (ident, actor.tenant_id, actor.principal_id))}
                    db.execute('INSERT INTO carousel_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (ident, revision, actor.tenant_id, actor.principal_id, op,
                         scene['brief'], scene['svg'], scene['card_count'], scene['card_width'],
                         scene['card_height'], scene['caption'], canonical(scene['asset_refs']), self.store.clock()))
                    for ref in scene['asset_refs']:
                        if ref not in previously_used:
                            asset = db.execute(
                                'SELECT created FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                                (ref, actor.tenant_id, actor.principal_id)).fetchone()
                            self._log(db, actor, ident, revision, 'asset_import',
                                      asset_ref=ref, imported_at=timestamp(asset['created']))
                self.app._key(db, actor, args['request_key'], digest(['carousel', intent]), op)
        return self.store.receipt(actor, op)

    def _composition_asset(self, actor, ident):
        """Use the private alpha original only for this carousel's SVG resources."""
        derivative = self.app.read_asset(actor, ident)
        with self.store.connection() as db:
            actor = self._actor(db, actor)
            original = db.execute(
                f"""SELECT source.id FROM assets AS derived
                   JOIN assets AS source
                     ON source.tenant_id=derived.tenant_id
                    AND source.principal_id=derived.principal_id
                    AND source.sha256=derived.source_sha256
                   WHERE derived.id=? AND derived.tenant_id=? AND derived.principal_id=?
                     AND source.id!=derived.id AND source.mime IN ('image/png','image/webp')
                     AND NOT EXISTS (SELECT 1 FROM media_store_assets m
                                     WHERE m.asset_id=source.id AND {EXPIRED_MEDIA_STORE_ASSET})
                   ORDER BY source.rowid LIMIT 1""",
                (ident, actor.tenant_id, actor.principal_id, self.store.clock())).fetchone()
        if not original:
            return derivative
        original_bytes, _, _ = self.app.read_asset(actor, original['id'])
        with Image.open(io.BytesIO(original_bytes)) as source:
            oriented = ImageOps.exif_transpose(source)
            if 'A' not in oriented.getbands() and 'transparency' not in oriented.info:
                return derivative
            clean = Image.new('RGBA', oriented.size)
            clean.paste(oriented.convert('RGBA'))
            output = io.BytesIO()
            clean.save(output, format='PNG')
        rgba = output.getvalue()
        return rgba, 'image/png', hashlib.sha256(rgba).hexdigest()

    def _log(self, db, actor, carousel_id, revision, kind, *, duration_ms=None, **details):
        intent = {'command': {'kind': kind, 'carousel_id': carousel_id, **details}}
        result = {'carousel_id': carousel_id}
        if duration_ms is not None:
            result['duration_ms'] = duration_ms
        return self.app._new_operation(db, actor, 'carousel', intent,
                                       revision=revision, complete=True, result=result)

    def log_event(self, actor, carousel_id, kind, *, duration_ms, revision=None, **details):
        with self.store.tx() as db:
            row = self._version(db, actor, carousel_id, revision)
            self._log(db, actor, row['id'], row['revision'], kind,
                      duration_ms=duration_ms, **details)

    def _prepare(self, actor, command, previous):
        defaults = {'brief': '', 'svg': '', 'card_count': 7, 'card_width': 1080,
                    'card_height': 1350, 'caption': ''}
        scene = {key: command.get(key, previous[key] if previous else default)
                 for key, default in defaults.items()}
        count, width, height = (scene[key] for key in ('card_count', 'card_width', 'card_height'))
        if (any(type(v) is not int for v in (count, width, height)) or not 3 <= count <= 10
                or not 128 <= width <= 2560 or not 128 <= height <= 2560 or count*width*height > 20_000_000):
            raise DomainError('carousel_dimensions_invalid')
        if previous and not any(key in command for key in (*defaults, 'note', 'reference_use')):
            raise DomainError('carousel_revision_empty')
        if command.get('reference_use'):
            ReferenceBank(self.store).describe(actor, command['reference_use']['reference_id'])
        assets = {}
        def read_asset(ident):
            if ident not in assets:
                assets[ident] = self._composition_asset(actor, ident)
            return assets[ident]
        if scene['svg']:
            validate_svg(scene['svg'], card_count=count, card_width=width,
                         card_height=height, read_asset=read_asset)
        scene['asset_refs'] = list(assets)
        return scene

    def get(self, actor, command):
        if command.get('scope') == 'guide':
            with self.store.connection() as db:
                if command.get('carousel_id'):
                    self._version(db, actor, command['carousel_id'])
                else:
                    self._actor(db, actor)
            result = guide(command.get('topic'), command.get('section'))
            if command.get('carousel_id'):
                # The service layer journals linked guide reads once, like reference/library/icons.
                (result.metadata if isinstance(result, GuideImages) else result)['carousel_id'] = command['carousel_id']
            return result
        with self.store.connection() as db:
            row = self._version(db, actor, command['carousel_id'], command.get('revision'))
            latest = self._version(db, actor, row['id'])
            journal = []
            full_journal = command.get('scope') == 'journal'
            limit = command.get('limit', 50) if full_journal else 10
            offset = command.get('offset', 0) if full_journal else 0
            operations = [] if command.get('scope') == 'components' else db.execute(
                    "SELECT id,revision,request,result,created FROM operations WHERE tenant_id=? "
                    "AND principal_id=? AND action='carousel' AND json_extract(result,'$.carousel_id')=? "
                    "ORDER BY created DESC,rowid DESC LIMIT ? OFFSET ?",
                    (actor.tenant_id, actor.principal_id, row['id'], limit + 1, offset)).fetchall()
            for op in operations[:limit]:
                entry = json.loads(op['request'])['command']
                recorded = json.loads(op['result'])
                journal.append({'operation_id': op['id'], 'revision': op['revision'], 'kind': entry['kind'],
                    'at': timestamp(op['created']),
                    **{key: entry[key] for key in ('note', 'reference_use', 'scope', 'view',
                        'region', 'card', 'reference_id', 'icon_id', 'asset_ref', 'imported_at',
                        'scale', 'layers', 'save_asset') if key in entry},
                    **({'duration_ms': recorded['duration_ms']} if 'duration_ms' in recorded else {})})
        result = {key: row[key] for key in ('revision', 'card_count', 'card_width', 'card_height')}
        result.update(carousel_id=row['id'], latest_revision=latest['revision'], private=True,
            next_step='render_then_review' if row['svg'] else 'compose_svg')
        if command.get('scope') == 'components':
            components = _component_placements(row['svg'],
                row['card_count'] * row['card_width'], row['card_height'])
            limit, offset = command.get('limit', 5), command.get('offset', 0)
            result.update(components=components[offset:offset + limit], total=len(components),
                offset=offset, next_offset=offset + limit if offset + limit < len(components) else None)
            images = []
            for component in result['components']:
                data, mime, sha = self._composition_asset(actor, component['asset_ref'])
                thumb = render_asset_preview(data, sha, '')
                component['preview'] = {'image_index': len(images),
                    **{key: thumb.metadata[key] for key in ('mime_type', 'width', 'height')}}
                images.append(thumb)
            return ComponentImages(result, tuple(images))
        result.update(brief=row['brief'], caption=row['caption'], scene_ready=bool(row['svg']),
            asset_refs=json.loads(row['asset_refs']), journal=journal)
        if full_journal:
            result.update(offset=offset, next_offset=offset + limit if len(operations) > limit else None)
        if command.get('include_svg'):
            result['svg'] = row['svg']
        return result

    def _render(self, actor, row, layers=None):
        if not row['svg']:
            raise DomainError('carousel_scene_missing', 'Save an SVG composition with revise before rendering or exporting')
        assets = {}

        def read_asset(ident):
            if ident not in assets:
                assets[ident] = self._composition_asset(actor, ident)
            return assets[ident]

        # Cache hits obey the same current asset checks as cold renders, before layer filtering.
        validate_svg(row['svg'], card_count=row['card_count'], card_width=row['card_width'],
                     card_height=row['card_height'], read_asset=read_asset)
        # The resolver may select an alpha original or its retained derivative.
        key = (actor.tenant_id, actor.principal_id, hashlib.sha256(row['svg'].encode()).hexdigest(),
               row['card_count'], row['card_width'], row['card_height'], canonical(layers or {}),
               tuple((ident, source[2]) for ident, source in assets.items()))
        with _RENDERED_LOCK:
            cached = _RENDERED.get(key)
            if cached is not None:
                _RENDERED.move_to_end(key)
                return cached
        data = render_svg(row['svg'], card_count=row['card_count'], card_width=row['card_width'],
            card_height=row['card_height'], read_asset=read_asset, layers=layers)
        if len(data) <= _RENDERED_MAX_BYTES:
            with _RENDERED_LOCK:
                _RENDERED[key] = data
                while (len(_RENDERED) > _RENDERED_MAX
                       or sum(map(len, _RENDERED.values())) > _RENDERED_MAX_BYTES):
                    _RENDERED.popitem(last=False)
        return data

    def render(self, actor, command):
        started = time.perf_counter()
        with self.store.connection() as db:
            row = self._version(db, actor, command['carousel_id'], command['revision'])
        view = command.get('view', 'master')
        width, height = row['card_width'] * row['card_count'], row['card_height']
        region = command.get('region')
        if 'card' in command:
            card = command['card']
            if type(card) is not int or not 1 <= card <= row['card_count'] or region is not None:
                raise DomainError('carousel_region_invalid')
            region = [(card - 1) * row['card_width'], 0, row['card_width'], height]
            view = 'region'
        if view == 'master':
            if region is not None:
                raise DomainError('carousel_region_invalid', 'Use view:region for a crop')
        elif view == 'region':
            if (not isinstance(region, (list, tuple)) or len(region) != 4
                    or any(type(v) is not int for v in region)):
                raise DomainError('carousel_region_invalid')
            x, y, w, h = region
            if min(x, y) < 0 or min(w, h) <= 0 or x+w > width or y+h > height:
                raise DomainError('carousel_region_invalid')
            if command.get('scale') == 1 and max(w, h) > FULL_MAX_EDGE:
                raise DomainError('carousel_region_exact_limit',
                                  'Exact region exceeds 2560 pixels; split into smaller regions')
        else:
            raise DomainError('carousel_view_invalid')
        scale = command.get('scale')
        if (scale is not None and not ((view == 'region' and scale == 1) or (view == 'master' and scale == 0.5))
                or (command.get('cutlines') and not (view == 'master' and scale == 0.5))
                or (command.get('save_asset') and (view != 'region' or scale != 1))):
            raise DomainError('carousel_region_exact_required',
                              'Use scale:1 (and save_asset) only with view:region; scale:0.5 and cutlines only with view:master')

        data = self._render(actor, row, layers=command.get('layers'))
        sha = hashlib.sha256(data).hexdigest()
        if view == 'master' and scale == 0.5:
            with Image.open(io.BytesIO(data)) as master:
                rgba = master.convert('RGBA')
                clean = Image.new('RGB', rgba.size, 'white')
                clean.paste(rgba, mask=rgba.getchannel('A'))
                half = clean.resize(
                    (width // 2, height // 2), Image.Resampling.LANCZOS)
            if command.get('cutlines'):
                draw = ImageDraw.Draw(half)
                for index in range(1, row['card_count']):
                    x = round(index * row['card_width'] / 2)
                    draw.line((x, 0, x, half.height), fill='white', width=3)
                    draw.line((x, 0, x, half.height), fill='#303030', width=1)
            output = io.BytesIO()
            half.save(output, format='JPEG', quality=82, optimize=True)
            encoded = output.getvalue()
            preview = AssetPreview({'mime_type': 'image/jpeg', 'width': half.width,
                'height': half.height, 'size': 'full', 'reencoded': True,
                'bytes': len(encoded), 'source_sha256': sha}, encoded)
        elif view == 'master':
            preview = render_asset_preview(data, sha, '')
        else:
            with Image.open(io.BytesIO(data)) as master:
                cropped = master.crop((x, y, x+w, y+h))
                if (command.get('scale') == 1 and cropped.mode == 'RGBA'
                        and cropped.getextrema()[3] == (255, 255)):
                    # Keep exact pixels without a redundant alpha channel exceeding ingress limits.
                    cropped = cropped.convert('RGB')
                output = io.BytesIO()
                cropped.save(output, format='PNG')
            exact_png = output.getvalue()
            if command.get('scale') == 1:
                preview = AssetPreview({
                    'source_sha256': hashlib.sha256(exact_png).hexdigest(),
                    'mime_type': 'image/png', 'width': w, 'height': h,
                    'bytes': len(exact_png), 'size': 'full', 'reencoded': False,
                }, exact_png)
            else:
                preview = render_asset_full(exact_png, 'image/png', sha, '')

        details = {'view': 'card' if 'card' in command else view}
        if 'card' in command:
            details['card'] = command['card']
        elif view == 'region':
            details['region'] = list(region)
        for name in ('scale', 'layers', 'save_asset'):
            if name in command:
                details[name] = command[name]
        prepared = verify_image(preview.data, 'image/png') if command.get('save_asset') else None
        # The original revision remains private and authorized through the render.
        # A saved fragment and its journal record share one existing store transaction.
        with self.store.tx() as db:
            actor = self._actor(db, actor)
            self._version(db, actor, row['id'], row['revision'])
            if prepared is not None:
                details['asset_ref'] = insert_verified_image(self.store, db, actor, prepared)
            self._log(db, actor, row['id'], row['revision'], 'render',
                      duration_ms=round((time.perf_counter() - started) * 1000), **details)
        metadata = {key: value for key, value in preview.metadata.items() if key != 'resource_uri'}
        review_view = 'card' if 'card' in command else view
        if view == 'region' and 'card' not in command:
            x, _, w, _ = region
            if any(x < i * row['card_width'] < x + w for i in range(1, row['card_count'])):
                review_view = 'pair'
        metadata.update(carousel_id=row['id'], revision=row['revision'], private=True,
                        view=view, source_width=width, source_height=height,
                        review_questions=review_questions(review_view))
        if view == 'master' and command.get('scale') == 0.5:
            metadata['scale'] = 0.5
            metadata['cutlines'] = bool(command.get('cutlines'))
        if view == 'region':
            metadata['region'] = list(region)
        for name in ('scale', 'layers', 'save_asset'):
            if name in command:
                metadata[name] = command[name]
        if 'asset_ref' in details:
            metadata['asset_ref'] = details['asset_ref']
            metadata['resource_uri'] = 'vibepublish://assets/' + details['asset_ref']
        return AssetPreview(metadata, preview.data)
