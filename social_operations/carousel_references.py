"""Owner-only visual references from a private, locally provisioned directory."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import warnings
from contextlib import contextmanager

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from PIL import Image, UnidentifiedImageError

from contracts.social_mcp_v1 import CAROUSEL_REFERENCE
from .assets import AssetPreview, INGRESS_IMAGE_MAX_BYTES, render_asset_full
from .domain import DomainError


_REFERENCE_VALIDATOR = Draft202012Validator(CAROUSEL_REFERENCE, format_checker=FormatChecker())


def _reference_metadata(row):
    result = {key: row[key] for key in ('id', 'title', 'tags', 'look_for', 'transfer', 'use_note')}
    result['source'] = {key: row['source'][key] for key in ('slack_url', 'file_id')}
    if 'duplicate_of' in row:
        result['duplicate_of'] = row['duplicate_of']
    return result


def validate_reference_entries(rows):
    """One catalog boundary for provisioning and reads; private extras stay unprojected."""
    try:
        if not isinstance(rows, list):
            raise ValueError()
        seen = set()
        for row in rows:
            metadata = _reference_metadata(row)
            _REFERENCE_VALIDATOR.validate({**metadata, 'available': True})
            name = row['file']
            if (metadata['id'] in seen or not isinstance(name, str)
                    or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', name)):
                raise ValueError()
            seen.add(metadata['id'])
        return rows
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise DomainError('carousel_reference_catalog_invalid',
                          'The local reference catalog is invalid', 'contact_owner') from exc


class ReferenceBank:
    def __init__(self, store):
        self.store = store
        self.root = store.path.parent / 'carousel-references'

    def _authorize(self, actor):
        with self.store.connection() as db:
            current = self.store.current(db, actor)
        if not current.owner:
            raise DomainError('access_denied', next_action='contact_owner')
        if 'visual' not in current.scopes:
            raise DomainError('visual_scope_required', next_action='contact_owner')
        return current

    @contextmanager
    def _directory(self):
        try:
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise DomainError('carousel_reference_unavailable',
                              'The private reference bank is unavailable', 'contact_owner') from exc
        try:
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def _read(directory, name, maximum):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, 'rb') as stream:
                details = os.fstat(stream.fileno())
                if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= maximum:
                    raise DomainError('carousel_reference_unavailable')
                data = stream.read(maximum + 1)
                if len(data) > maximum:
                    raise DomainError('carousel_reference_unavailable')
                return data
        except OSError as exc:
            raise DomainError('carousel_reference_unavailable',
                              'The requested reference file is unavailable', 'contact_owner') from exc

    def _catalog(self, directory, actor):
        raw = self._read(directory, 'catalog.json', 2 * 1024 * 1024)
        try:
            catalog = json.loads(raw)
            owner = catalog['owner']
            if any(not isinstance(owner[key], str) or not owner[key]
                   for key in ('tenant_id', 'principal_id')):
                raise ValueError()
            if (owner['tenant_id'], owner['principal_id']) != (actor.tenant_id, actor.principal_id):
                raise DomainError('access_denied', next_action='contact_owner')
            return validate_reference_entries(catalog['references'])
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise DomainError('carousel_reference_catalog_invalid',
                              'The local reference catalog is invalid', 'contact_owner') from exc

    @staticmethod
    def _metadata(directory, row):
        result = _reference_metadata(row)
        try:
            details = os.stat(row['file'], dir_fd=directory, follow_symlinks=False)
            available = stat.S_ISREG(details.st_mode) and 0 < details.st_size <= INGRESS_IMAGE_MAX_BYTES
        except OSError:
            available = False
        return {**result, 'available': available}

    def _find(self, directory, actor, reference_id):
        row = next((r for r in self._catalog(directory, actor) if r['id'] == reference_id), None)
        if row is None:
            raise DomainError('carousel_reference_not_found', 'Unknown reference ID')
        metadata = self._metadata(directory, row)
        if not metadata['available']:
            raise DomainError('carousel_reference_unavailable',
                              'The requested reference file is unavailable', 'contact_owner')
        return row, metadata

    def list(self, actor, query='', limit=5, offset=0):
        actor = self._authorize(actor)
        if (not isinstance(query, str) or type(limit) is not int or not 1 <= limit <= 20
                or type(offset) is not int or offset < 0):
            raise DomainError('carousel_reference_query_invalid')
        with self._directory() as directory:
            entries = [self._metadata(directory, row) for row in self._catalog(directory, actor)]
        terms = set(re.findall(r'[^\W_]+', query.casefold()))
        ranked = []
        for entry in entries:
            words = set(re.findall(r'[^\W_]+', ' '.join([
                entry['id'], entry['title'], *entry['tags'],
                entry['look_for'], entry['transfer']
            ]).casefold()))
            # Exact words first; five-letter prefixes match common RU/EN inflections.
            score = sum(2 if term in words else
                        int(len(term) >= 5 and any(word.startswith(term[:5])
                            for word in words)) for term in terms)
            ranked.append((score, entry))
        ranked.sort(key=lambda item: -item[0])  # Catalog order breaks ties.
        page = ranked[offset:offset + limit]
        result = [{**entry, 'matched': bool(score or not terms)} for score, entry in page]
        return {'references': result, 'total': len(ranked), 'offset': offset,
                'next_offset': offset + len(page) if offset + len(page) < len(ranked) else None}

    def describe(self, actor, reference_id):
        """Validate a local reference without reading image bytes or claiming a visual review."""
        actor = self._authorize(actor)
        with self._directory() as directory:
            return self._find(directory, actor, reference_id)[1]

    def get(self, actor, reference_id, region=None):
        actor = self._authorize(actor)
        with self._directory() as directory:
            row, metadata = self._find(directory, actor, reference_id)
            original = self._read(directory, row['file'], INGRESS_IMAGE_MAX_BYTES)
        source_hash = hashlib.sha256(original).hexdigest()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(original)) as source:
                    mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(source.format)
                    if (not mime or source.width * source.height > 25_000_000
                            or getattr(source, 'n_frames', 1) != 1):
                        raise DomainError('invalid_image')
                    source.load()
                    width, height = source.size
                    data = original
                    if region is not None:
                        if (not isinstance(region, list) or len(region) != 4
                                or any(type(v) is not int for v in region)):
                            raise DomainError('carousel_reference_region_invalid')
                        x, y, w, h = region
                        if min(x, y) < 0 or min(w, h) <= 0 or x + w > width or y + h > height:
                            raise DomainError('carousel_reference_region_invalid')
                        mode = 'RGBA' if 'A' in source.getbands() or 'transparency' in source.info else 'RGB'
                        crop = source.crop((x, y, x + w, y + h)).convert(mode)
                        crop.info.clear()
                        output = io.BytesIO()
                        crop.save(output, format='PNG')
                        data, mime = output.getvalue(), 'image/png'
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            raise DomainError('invalid_image') from exc
        preview = render_asset_full(data, mime, source_hash,
                                    'vibepublish://carousel-references/' + row['id'])
        self._authorize(actor)
        result = {**preview.metadata, 'reference': metadata, 'view': 'crop' if region is not None else 'full',
                  'region': region, 'source_width': width, 'source_height': height,
                  'reencoded': preview.metadata['reencoded'] or region is not None}
        return AssetPreview(result, preview.data)
