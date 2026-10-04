"""Authenticated original upload; no network fetching or image executor."""
from __future__ import annotations
import hashlib
import json
from .assets import verify_image, insert_verified_image
from .domain import DomainError, digest, new_id

MAX_UPLOAD_BYTES = 128 * 1024 * 1024
DOCUMENT_MIMES = {"application/pdf", "image/vnd.djvu"}
ACTION = 'asset_ingress'


def upload_image(service, actor, data: bytes, mime: str, key: str | None):
    if not key or len(key) > 200 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise DomainError('idempotency_key_required')
    if mime not in {'image/png', 'image/jpeg', 'image/webp'} | DOCUMENT_MIMES:
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
    document = mime in DOCUMENT_MIMES
    if document:
        if not (mime=='application/pdf' and data.startswith(b'%PDF-') or
                mime=='image/vnd.djvu' and data[:8]==b'AT&TFORM' and data[12:16] in (b'DJVU',b'DJVM')):
            raise DomainError('asset_container_invalid')
    else:
        image = verify_image(data, mime)
    with store.tx() as db:
        actor = store.current(db, actor)
        if not actor.scopes.intersection({'publish', 'visual'}):
            raise DomainError('access_denied')
        op = service._replay(db, actor, ACTION, intent, {'request_key': key}, implicit=False)
        if op:
            return _response(db, actor, json.loads(store.private_operation(db, actor, op)['result'])['resource_id'], key)
        if document:
            used=db.execute('SELECT COALESCE(SUM(length(bytes)),0) FROM assets WHERE tenant_id=?',(actor.tenant_id,)).fetchone()[0]
            quota=db.execute('SELECT storage_limit FROM tenants WHERE id=?',(actor.tenant_id,)).fetchone()[0]
            if used+len(data)>quota:
                raise DomainError('storage_quota_exceeded')
            ident=new_id('asset');sha=intent['source_sha256']
            db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (ident,actor.tenant_id,actor.principal_id,sha,mime,0,0,data,sha,store.clock()))
        else:
            ident = insert_verified_image(store, db, actor, image)
        result = {'resource_id': ident}
        if document:
            result['document_receipt']=_response(db,actor,ident,key)
            db.execute('INSERT INTO media_store_assets VALUES(?,?,?,?)',(ident,None,'staging',store.clock()+30*86400+3600))
        op = service._new_operation(db, actor, ACTION, intent, complete=True, result=result)
        service._key(db, actor, key, digest([ACTION, intent]), op)
        return _response(db, actor, ident, key)


def _response(db, actor, ident, key):
    row = db.execute('SELECT * FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                     (ident, actor.tenant_id, actor.principal_id)).fetchone()
    if not row:
        # Verified document staging may be gone; retain the immutable ingress receipt
        # so a lost put response can replay its original asset identity safely.
        replay=db.execute('SELECT o.result FROM request_keys k JOIN operations o ON o.id=k.operation_id WHERE k.tenant_id=? AND k.principal_id=? AND k.key=?',(actor.tenant_id,actor.principal_id,key)).fetchone()
        if replay:
            receipt=json.loads(replay['result']).get('document_receipt')
            if receipt and receipt['asset_id']==ident:return receipt
        raise DomainError('asset_not_available')
    return {'asset_id': ident, 'sha256': row['sha256'], 'source_sha256': row['source_sha256'],
            'mime': row['mime'], 'width': row['width'], 'height': row['height'], 'idempotency_key': key}
