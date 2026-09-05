"""Authenticated original upload; no network fetching or image executor."""
from __future__ import annotations
import hashlib
import json
from .assets import verify_image, insert_verified_image
from .domain import DomainError, digest

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ACTION = 'asset_ingress'


def upload_image(service, actor, data: bytes, mime: str, key: str | None):
    if not key or len(key) > 200 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise DomainError('idempotency_key_required')
    if mime not in {'image/png', 'image/jpeg', 'image/webp'}:
        raise DomainError('asset_format_or_dimensions')
    if not 1 <= len(data) <= MAX_UPLOAD_BYTES:
        raise DomainError('asset_size_limit')
    store = service.store
    # Check authority before expensive decoding, then again inside admission.
    with store.connection() as db:
        actor = store.current(db, actor)
        if not actor.scopes.intersection({'publish', 'visual'}):
            raise DomainError('access_denied')
    intent = {'source_sha256': hashlib.sha256(data).hexdigest(), 'mime': mime}
    with store.connection() as db:
        op = service._replay(db, actor, ACTION, intent, {'request_key': key}, implicit=False)
        if op:
            return _response(db, actor, json.loads(store.private_operation(db, actor, op)['result'])['resource_id'], key)
    image = verify_image(data, mime)
    with store.tx() as db:
        actor = store.current(db, actor)
        if not actor.scopes.intersection({'publish', 'visual'}):
            raise DomainError('access_denied')
        op = service._replay(db, actor, ACTION, intent, {'request_key': key}, implicit=False)
        if op:
            return _response(db, actor, json.loads(store.private_operation(db, actor, op)['result'])['resource_id'], key)
        ident = insert_verified_image(store, db, actor, image)
        result = {'resource_id': ident}
        op = service._new_operation(db, actor, ACTION, intent, complete=True, result=result)
        service._key(db, actor, key, digest([ACTION, intent]), op)
        return _response(db, actor, ident, key)


def _response(db, actor, ident, key):
    row = db.execute('SELECT * FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                     (ident, actor.tenant_id, actor.principal_id)).fetchone()
    if not row:
        raise DomainError('asset_not_available')
    return {'asset_id': ident, 'sha256': row['sha256'], 'source_sha256': row['source_sha256'],
            'mime': row['mime'], 'width': row['width'], 'height': row['height'], 'idempotency_key': key}
