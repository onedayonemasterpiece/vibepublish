"""Private SVG stories, immutable revisions and ordered exports in the existing ledger."""
from __future__ import annotations

import hashlib
import io
import json

from PIL import Image, ImageDraw, ImageOps

from .assets import AssetPreview, insert_verified_image, render_asset_full, render_asset_preview, verify_image
from .carousel_compositor import render_svg, slice_cards, validate_svg
from .carousel_guide import GuideImages, guide, review_questions
from .carousel_references import ReferenceBank
from .domain import DomainError, canonical, digest, new_id, timestamp


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
                op = self.app._new_operation(db, actor, 'carousel', intent,
                    revision=revision, complete=True, result=result)
                if kind != 'export':
                    db.execute('INSERT INTO carousel_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (ident, revision, actor.tenant_id, actor.principal_id, op,
                         scene['brief'], scene['svg'], scene['card_count'], scene['card_width'],
                         scene['card_height'], scene['caption'], canonical(scene['asset_refs']), self.store.clock()))
                self.app._key(db, actor, args['request_key'], digest(['carousel', intent]), op)
        return self.store.receipt(actor, op)

    def _composition_asset(self, actor, ident):
        """Use the private alpha original only for this carousel's SVG resources."""
        derivative = self.app.read_asset(actor, ident)
        with self.store.connection() as db:
            actor = self._actor(db, actor)
            original = db.execute(
                """SELECT source.id FROM assets AS derived
                   JOIN assets AS source
                     ON source.tenant_id=derived.tenant_id
                    AND source.principal_id=derived.principal_id
                    AND source.sha256=derived.source_sha256
                   WHERE derived.id=? AND derived.tenant_id=? AND derived.principal_id=?
                     AND source.id!=derived.id AND source.mime IN ('image/png','image/webp')
                   ORDER BY source.rowid LIMIT 1""",
                (ident, actor.tenant_id, actor.principal_id)).fetchone()
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
                (result.metadata if isinstance(result, GuideImages) else result)['carousel_id'] = command['carousel_id']
            return result
        with self.store.connection() as db:
            row = self._version(db, actor, command['carousel_id'], command.get('revision'))
            latest = self._version(db, actor, row['id'])
            journal = []
            for op in db.execute("SELECT id,revision,request,created FROM operations WHERE tenant_id=? "
                    "AND principal_id=? AND action='carousel' AND json_extract(result,'$.carousel_id')=? "
                    "ORDER BY created DESC,rowid DESC LIMIT 10", (actor.tenant_id, actor.principal_id, row['id'])):
                entry = json.loads(op['request'])['command']
                journal.append({'operation_id': op['id'], 'revision': op['revision'], 'kind': entry['kind'],
                    'at': timestamp(op['created']), **{key: entry[key] for key in ('note', 'reference_use') if key in entry}})
        result = {key: row[key] for key in ('revision', 'brief', 'card_count', 'card_width', 'card_height', 'caption')}
        result.update(carousel_id=row['id'], latest_revision=latest['revision'], private=True,
            scene_ready=bool(row['svg']), asset_refs=json.loads(row['asset_refs']), journal=journal,
            next_step='render_then_review' if row['svg'] else 'compose_svg')
        if command.get('include_svg'):
            result['svg'] = row['svg']
        return result

    def _render(self, actor, row):
        if not row['svg']:
            raise DomainError('carousel_scene_missing', 'Save an SVG composition with revise before rendering or exporting')
        return render_svg(row['svg'], card_count=row['card_count'], card_width=row['card_width'],
            card_height=row['card_height'], read_asset=lambda ident: self._composition_asset(actor, ident))

    def render(self, actor, command):
        with self.store.connection() as db:
            row = self._version(db, actor, command['carousel_id'], command['revision'])
        data = self._render(actor, row)
        sha = hashlib.sha256(data).hexdigest()
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
            if command.get('scale') == 0.5:
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
            else:
                preview = render_asset_preview(data, sha, '')
        elif view == 'region':
            if (not isinstance(region, (list, tuple)) or len(region) != 4
                    or any(type(v) is not int for v in region)):
                raise DomainError('carousel_region_invalid')
            x, y, w, h = region
            if min(x, y) < 0 or min(w, h) <= 0 or x+w > width or y+h > height:
                raise DomainError('carousel_region_invalid')
            with Image.open(io.BytesIO(data)) as master:
                cropped = master.crop((x, y, x+w, y+h))
                output = io.BytesIO()
                cropped.save(output, format='PNG')
            preview = render_asset_full(output.getvalue(), 'image/png', sha, '')
        else:
            raise DomainError('carousel_view_invalid')
        # An in-flight render is still private after it completes; do not return
        # pixels to an actor revoked while the compositor was running.
        with self.store.connection() as db:
            self._version(db, actor, row['id'], row['revision'])
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
        return AssetPreview(metadata, preview.data)
