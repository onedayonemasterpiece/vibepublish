"""Resolve a proven VK allocation-only failure without inventing a wall effect."""
import json
import re
from .domain import canonical, digest

_KIND = 'vk_video_allocation_only'
_PREFIX = 'provider_diagnostic '

def _context(db, op, child, checkpoint):
    plan = json.loads(child['plan'])
    adapter = checkpoint.get('adapter', {})
    principal = db.execute('SELECT epoch,active FROM principals WHERE id=? AND tenant_id=?',
                           (op['principal_id'], op['tenant_id'])).fetchone()
    binding = db.execute('SELECT b.*,d.native_id,d.connection_id,c.account_type,c.secret_ref,'
                         'c.active AS connection_active,c.provider AS connection_provider FROM bindings b '
                         'JOIN destinations d ON d.id=b.destination_id '
                         'JOIN connections c ON c.id=d.connection_id WHERE b.id=?',
                         (child['binding_id'],)).fetchone()
    assets = plan.get('assets', [])
    media = adapter.get('media', [])
    if not (child['provider'] == 'vk' and child['dispatched'] == 1
            and plan.get('action') == 'publish' and plan.get('surface', 'post') == 'post'
            and not plan.get('scheduled_at') and plan.get('workload', 'publication') == 'publication'
            and len(assets) == 1 and assets[0].get('role') == 'video'
            and assets[0].get('mime') == 'video/mp4'
            and digest(plan) == child['plan_digest']
            and checkpoint.get('transition') == 'vk_video_allocated'
            and type(adapter.get('version')) is int and adapter.get('version') == 1 and adapter.get('id') is None
            and adapter.get('retryable_wall_post') is False
            and adapter.get('attempt') == child['id']
            and adapter.get('plan') == child['plan_digest']
            and adapter.get('target') == plan.get('native_target')
            and len(media) == 1 and isinstance(media[0], str)
            and re.fullmatch(r'video-[1-9][0-9]*_[1-9][0-9]*', media[0])
            and media[0].split('_')[0][5:] == str(plan['native_target'])
            and principal and principal['active'] and binding and binding['active']
            and binding['connection_active'] and binding['connection_provider'] == 'vk'
            and op['actor_epoch'] == principal['epoch']
            and child['binding_epoch'] == binding['epoch'] == plan['binding_epoch']
            and binding['tenant_id'] == op['tenant_id']
            and binding['principal_id'] == op['principal_id']
            and binding['native_id'] == plan['native_target']
            and all(binding[k] == plan[k] for k in
                    ('connection_id', 'destination_id', 'account_type', 'secret_ref'))
            and plan['action'] in json.loads(binding['rights'])):
        return None
    return plan

def _diagnostic(row, op, child):
    body = json.loads(row['body'])
    message = body.get('message', '')
    if not message.startswith(_PREFIX):
        return None
    record = json.loads(message[len(_PREFIX):])
    if not all(record.get(k) == v for k, v in (
            ('operation_id', op['id']), ('attempt_id', child['id']),
            ('publication_id', op['publication_id']), ('provider', 'vk'),
            ('action', 'publish'))):
        return None
    return record

def candidate(db, op, child):
    """Local validation failure is positive evidence; missing logs never suffice."""
    try:
        checkpoint = json.loads(child['checkpoint'])
        if (child['state'] != 'outcome_unknown'
                or json.loads(child['result']).get('missing_checks') != ['vk_upload_url_invalid']
                or not _context(db, op, child, checkpoint)):
            return None
        records = []
        for row in db.execute('SELECT seq,body FROM events WHERE operation_id=? ORDER BY seq', (op['id'],)):
            record = _diagnostic(row, op, child)
            if record is not None:
                records.append((row, record))
        if len(records) < 2:
            return None
        (saved_row, saved), (failed_row, failed) = records[-2:]
        if not (saved.get('operation') == 'video.save' and saved.get('status') == 'completed'
                and failed.get('operation') == 'execute' and failed.get('status') == 'failed'
                and failed.get('error_code') == 'vk_upload_url_invalid'):
            return None
        # _stage_video checkpoints the validated video.save allocation, then
        # synchronously validates its URL BEFORE upload. This exact local error
        # proves upload/wall submission unreachable, not absence of allocation.
        return dict(kind=_KIND, operation_id=op['id'], attempt_id=child['id'],
                    plan_digest=child['plan_digest'], actor_epoch=op['actor_epoch'],
                    binding_epoch=child['binding_epoch'], checkpoint_digest=digest(checkpoint),
                    allocation=checkpoint['adapter']['media'][0],
                    saved_seq=saved_row['seq'], saved_digest=digest(json.loads(saved_row['body'])),
                    failed_seq=failed_row['seq'], failed_digest=digest(json.loads(failed_row['body'])))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None

def resolve(store, db, op, child, proof):
    """Explicit reconciliation retains the original allocation and historical dispatch."""
    if not proof or proof != candidate(db, op, child):
        return False
    checkpoint = json.loads(child['checkpoint'])
    checkpoint['known_allocation'] = proof
    result = dict(reason=_KIND, retry_safe=False,
                  missing_checks=['video_upload_not_started'])
    db.execute("UPDATE attempts SET state='partial',stage='finished',observed='not_attempted',"
               "result=?,checkpoint=? WHERE id=? AND dispatched=1",
               (canonical(result), canonical(checkpoint), child['id']))
    store.event(db, op['id'], 'finished', 'completed',
                'Known VK video allocation retained; URL validation prevented upload and wall publication; no retry admitted',
                child['alias'])
    return True

def resolved(db, child):
    """Only the exact durable allocation proof exempts this attempt from quarantine."""
    try:
        if child['state'] != 'partial' or child['observed'] != 'not_attempted':
            return False
        checkpoint = json.loads(child['checkpoint'])
        proof = checkpoint.pop('known_allocation')
        result = json.loads(child['result'])
        op = db.execute('SELECT * FROM operations WHERE id=?', (child['operation_id'],)).fetchone()
        if not (_context(db, op, child, checkpoint) and proof['kind'] == _KIND
                and proof['operation_id'] == op['id'] and proof['attempt_id'] == child['id']
                and proof['plan_digest'] == child['plan_digest']
                and proof['actor_epoch'] == op['actor_epoch']
                and proof['binding_epoch'] == child['binding_epoch']
                and proof['checkpoint_digest'] == digest(checkpoint)
                and proof['allocation'] == checkpoint['adapter']['media'][0]
                and result == dict(reason=_KIND, retry_safe=False,
                                   missing_checks=['video_upload_not_started'])):
            return False
        records = []
        for prefix in ('saved', 'failed'):
            row = db.execute('SELECT seq,body FROM events WHERE operation_id=? AND seq=?',
                             (op['id'], proof[prefix+'_seq'])).fetchone()
            if not row or digest(json.loads(row['body'])) != proof[prefix+'_digest']:
                return False
            records.append(_diagnostic(row, op, child))
        saved, failed = records
        return (proof['saved_seq'] < proof['failed_seq']
                and saved.get('operation') == 'video.save' and saved.get('status') == 'completed'
                and failed.get('operation') == 'execute' and failed.get('status') == 'failed'
                and failed.get('error_code') == 'vk_upload_url_invalid')
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
