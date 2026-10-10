"""Bounded private workspace bytes, with durable offsets and atomic asset admission."""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import threading

from starlette.concurrency import run_in_threadpool

from .assets import insert_verified_image, verify_image
from .chat_file_ingress import authority
from .domain import DomainError, digest, new_id, timestamp

ACTION = 'workspace_image_import'
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_CHUNK_BASE64 = 262144
PRINCIPAL_STAGED_BYTES = 40 * 1024 * 1024
GLOBAL_STAGED_BYTES = 128 * 1024 * 1024
MAX_ACTIVE_UPLOADS = 2
UPLOAD_TTL = 3600
TERMINAL_TTL = 3600
_DECODE_SLOTS = threading.BoundedSemaphore(2)


def _validate(args):
    command = args.get('command', {})
    kind = command.get('kind')
    key = args.get('request_key')
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise DomainError('invalid_input')
    kinds = {'import_begin', 'import_chunk', 'import_finish', 'import_status', 'import_abort'}
    if kind not in kinds:
        raise DomainError('invalid_input')
    allowed = {
        'import_begin': {'kind', 'source_sha256', 'mime', 'size_bytes'},
        'import_chunk': {'kind', 'upload_id', 'offset', 'data_base64'},
        'import_finish': {'kind', 'upload_id'},
        'import_status': {'kind', 'upload_id'},
        'import_abort': {'kind', 'upload_id'},
    }
    if set(command) != allowed[kind]:
        raise DomainError('invalid_input')
    intent = dict(command)
    data = None
    if kind == 'import_begin':
        if (not isinstance(command.get('source_sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', command['source_sha256'])
                or command.get('mime') not in {'image/png', 'image/jpeg', 'image/webp'}
                or type(command.get('size_bytes')) is not int
                or not 1 <= command['size_bytes'] <= MAX_UPLOAD_BYTES):
            raise DomainError('invalid_input')
    else:
        if not isinstance(command.get('upload_id'), str) or not 1 <= len(command['upload_id']) <= 200:
            raise DomainError('invalid_input')
    if kind == 'import_chunk':
        encoded = command.get('data_base64')
        if (type(command.get('offset')) is not int or command['offset'] < 0
                or not isinstance(encoded, str) or not 1 <= len(encoded) <= MAX_CHUNK_BASE64):
            raise DomainError('invalid_input')
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise DomainError('invalid_input') from None
        # Canonical encoding prevents equivalent ambiguous request representations.
        if not data or base64.b64encode(data).decode('ascii') != encoded:
            raise DomainError('invalid_input')
        intent.pop('data_base64')
        intent.update(chunk_sha256=hashlib.sha256(data).hexdigest(), chunk_size=len(data))
    # No bytes, filenames, URLs, or filesystem paths enter the operation ledger.
    return kind, key, intent, data


def purge_expired_uploads(db, now):
    db.execute("UPDATE workspace_uploads SET state='expired',bytes=X'' "
               "WHERE state='receiving' AND expires<=?", (now,))
    db.execute("UPDATE workspace_uploads SET bytes=X'' WHERE state!='receiving' AND length(bytes)>0")
    db.execute("DELETE FROM workspace_uploads WHERE expires<=?", (now - TERMINAL_TTL,))


def _owned(db, actor, ident):
    row = db.execute('SELECT id,tenant_id,principal_id,actor_epoch,source_sha256,mime,'
                     'size_bytes,received_bytes,state,created,expires,resource_id '
                     'FROM workspace_uploads WHERE id=? AND tenant_id=? AND principal_id=? AND actor_epoch=?',
                     (ident, actor.tenant_id, actor.principal_id, actor.epoch)).fetchone()
    if not row:
        raise DomainError('workspace_upload_not_found')
    return row


def _metadata(row):
    return {'upload_id': row['id'], 'received_bytes': row['received_bytes'],
            'size_bytes': row['size_bytes'], 'source_sha256': row['source_sha256'],
            'mime': row['mime'], 'expires_at': timestamp(row['expires']), 'state': row['state']}


def _record(service, db, actor, intent, key, row):
    result = {'workspace_upload': _metadata(row)}
    if row['resource_id']:
        result['resource_id'] = row['resource_id']
    op = service._new_operation(db, actor, ACTION, intent, complete=True, result=result)
    service._key(db, actor, key, digest([ACTION, intent]), op)
    return op


def _receiving(row, now):
    if row['state'] == 'expired' or row['expires'] <= now:
        raise DomainError('workspace_upload_expired')
    if row['state'] != 'receiving':
        raise DomainError('workspace_upload_closed')


async def import_workspace_image(service, actor, args):
    kind, key, intent, data = _validate(args)
    store = service.store
    # Cleanup is its own committed transaction: later rejection cannot restore bytes.
    with store.tx() as db:
        actor = authority(store, db, actor)
        purge_expired_uploads(db, store.clock())
    if kind == 'import_finish':
        return await _finish(service, actor, key, intent)
    with store.tx() as db:
        actor = authority(store, db, actor)
        op = service._replay(db, actor, ACTION, intent, {'request_key': key}, implicit=False)
        if not op:
            if kind == 'import_begin':
                count, used = db.execute(
                    "SELECT count(*),COALESCE(SUM(size_bytes),0) FROM workspace_uploads "
                    "WHERE tenant_id=? AND principal_id=? AND state='receiving'",
                    (actor.tenant_id, actor.principal_id)).fetchone()
                total = db.execute("SELECT COALESCE(SUM(size_bytes),0) FROM workspace_uploads "
                                   "WHERE state='receiving'").fetchone()[0]
                size = intent['size_bytes']
                if (count >= MAX_ACTIVE_UPLOADS or used + size > PRINCIPAL_STAGED_BYTES
                        or total + size > GLOBAL_STAGED_BYTES):
                    raise DomainError('workspace_upload_quota_exceeded')
                ident, now = new_id('upload'), store.clock()
                db.execute('INSERT INTO workspace_uploads '
                           '(id,tenant_id,principal_id,actor_epoch,source_sha256,mime,size_bytes,created,expires) '
                           'VALUES(?,?,?,?,?,?,?,?,?)',
                           (ident, actor.tenant_id, actor.principal_id, actor.epoch,
                            intent['source_sha256'], intent['mime'], size, now, now + UPLOAD_TTL))
            else:
                ident = intent['upload_id']
                row = _owned(db, actor, ident)
                if kind == 'import_chunk':
                    _receiving(row, store.clock())
                    offset, end = intent['offset'], intent['offset'] + len(data)
                    if offset == row['received_bytes'] and end <= row['size_bytes']:
                        db.execute("UPDATE workspace_uploads SET bytes=CAST(bytes || ? AS BLOB),received_bytes=? WHERE id=?",
                                   (data, end, ident))
                    elif end <= row['received_bytes']:
                        previous = db.execute('SELECT substr(bytes,?,?) FROM workspace_uploads WHERE id=?',
                                              (offset + 1, len(data), ident)).fetchone()[0]
                        if previous != data:
                            raise DomainError('workspace_upload_offset_conflict')
                    else:
                        raise DomainError('workspace_upload_offset_conflict')
                elif kind == 'import_abort':
                    if row['state'] == 'completed':
                        raise DomainError('workspace_upload_closed')
                    if row['state'] == 'receiving':
                        db.execute("UPDATE workspace_uploads SET state='aborted',bytes=X'' WHERE id=?", (ident,))
            row = _owned(db, actor, ident)
            op = _record(service, db, actor, intent, key, row)
    return store.receipt(actor, op)


async def _finish(service, actor, key, intent):
    store, ident = service.store, intent['upload_id']
    # Replay and completed-session recovery never need a decode slot or bytes.
    with store.tx() as db:
        actor = authority(store, db, actor)
        op = service._replay(db, actor, ACTION, intent, {'request_key': key}, implicit=False)
        if not op:
            row = _owned(db, actor, ident)
            if row['state'] == 'completed':
                op = _record(service, db, actor, intent, key, row)
            else:
                _receiving(row, store.clock())
                if row['received_bytes'] != row['size_bytes']:
                    raise DomainError('workspace_upload_incomplete')
    if op:
        return store.receipt(actor, op)
    if not _DECODE_SLOTS.acquire(blocking=False):
        raise DomainError('asset_ingress_busy')
    try:
        with store.tx() as db:
            actor = authority(store, db, actor)
            op = service._replay(db, actor, ACTION, intent, {'request_key': key}, implicit=False)
            if not op:
                row = _owned(db, actor, ident)
                if row['state'] == 'completed':
                    op = _record(service, db, actor, intent, key, row)
                else:
                    _receiving(row, store.clock())
                    data = db.execute('SELECT bytes FROM workspace_uploads WHERE id=?', (ident,)).fetchone()[0]
        if op:
            return store.receipt(actor, op)
        try:
            if len(data) != row['size_bytes'] or hashlib.sha256(data).hexdigest() != row['source_sha256']:
                raise DomainError('workspace_upload_integrity')
            image = await run_in_threadpool(verify_image, data, row['mime'])
        except DomainError:
            with store.tx() as db:
                db.execute("UPDATE workspace_uploads SET state='aborted',bytes=X'' "
                           "WHERE id=? AND state='receiving'", (ident,))
            raise
        with store.tx() as db:
            purge_expired_uploads(db, store.clock())
        with store.tx() as db:
            actor = authority(store, db, actor)
            op = service._replay(db, actor, ACTION, intent, {'request_key': key}, implicit=False)
            if not op:
                row = _owned(db, actor, ident)
                if row['state'] != 'completed':
                    _receiving(row, store.clock())
                    resource = insert_verified_image(store, db, actor, image)
                    db.execute("UPDATE workspace_uploads SET state='completed',bytes=X'',resource_id=? WHERE id=?",
                               (resource, ident))
                    row = _owned(db, actor, ident)
                op = _record(service, db, actor, intent, key, row)
        return store.receipt(actor, op)
    finally:
        _DECODE_SLOTS.release()
