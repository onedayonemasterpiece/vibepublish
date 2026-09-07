"""Observation-only recovery admission. Reuses the original operation and dispatch."""
import json
from .domain import DomainError, canonical, digest, normalize_intent


def admit(app, actor, args):
    store = app.store
    change = args['change']
    if args.get('item_ref') or ('native_reference' in change and 'attempt_id' not in change):
        raise DomainError('recovery_original_attempt_required')
    intent_hash = digest(['reconcile', normalize_intent('publication_update', args)])
    with store.tx() as db:
        actor = store.current(db, actor)
        op = store.private_operation(db, actor, change['operation_id'])
        if op['id'] != change['operation_id'] or op['publication_id'] != args.get('publication_id'):
            raise DomainError('recovery_operation_mismatch')
        pub = db.execute('SELECT revision FROM publications WHERE id=?', (op['publication_id'],)).fetchone()
        if op['revision'] != args['expected_revision'] or pub['revision'] != args['expected_revision']:
            raise DomainError('revision_conflict', next_action='refresh')
        key = args.get('request_key')
        replay = db.execute('SELECT * FROM request_keys WHERE tenant_id=? AND principal_id=? AND key=?',
                            (actor.tenant_id, actor.principal_id, key)).fetchone() if key else None
        if replay:
            if replay['digest'] != intent_hash or replay['operation_id'] != op['id']:
                raise DomainError('idempotency_conflict')
        if not replay or op['work_state'] == 'done':
            children = list(db.execute('SELECT * FROM attempts WHERE operation_id=?', (op['id'],)))
            if change.get('attempt_id') and not any(c['id'] == change['attempt_id'] for c in children):
                raise DomainError('recovery_operation_mismatch')
            unknown = [c for c in children if c['state'] == 'outcome_unknown' and c['dispatched']]
            pending = db.execute("SELECT 1 FROM attempt_recovery r JOIN attempts a ON a.id=r.attempt_id WHERE a.operation_id=? AND r.finalize_state='pending'", (op['id'],)).fetchone()
            if op['work_state'] == 'done' and not unknown and not pending:
                if not children or not all(c['state'] in ('verified', 'scheduled', 'cancelled') for c in children):
                    raise DomainError('recovery_not_available', next_action='review_outcome')
            if op['work_state'] == 'done' and (unknown or pending):
                for child in unknown:
                    b = store.binding(db, actor, binding_id=child['binding_id'])
                    plan = json.loads(child['plan'])
                    if b['epoch'] != child['binding_epoch'] or plan['action'] not in json.loads(b['rights']):
                        raise DomainError('access_revoked', next_action='reauthorize')
                    hint = {'operation_id': op['id'], 'attempt_id': child['id'], 'plan_digest': child['plan_digest']}
                    if child['id'] == change.get('attempt_id') and change.get('native_reference'):
                        hint['native_reference'] = change['native_reference']
                    previous = db.execute('SELECT hint FROM attempt_recovery WHERE attempt_id=?', (child['id'],)).fetchone()
                    if previous:
                        old_hint = json.loads(previous['hint'])
                        if old_hint.get('native_reference') and hint.get('native_reference', old_hint['native_reference']) != old_hint['native_reference']:
                            raise DomainError('recovery_evidence_conflict')
                        hint = {**old_hint, **hint}
                    db.execute('INSERT INTO attempt_recovery(attempt_id,plan_digest,original_checkpoint,hint,created) VALUES(?,?,?,?,?) ON CONFLICT(attempt_id) DO UPDATE SET hint=excluded.hint',
                               (child['id'], child['plan_digest'], child['checkpoint'], canonical(hint), store.clock()))
                    db.execute("UPDATE attempts SET state='running',stage='verifying' WHERE id=?", (child['id'],))
                db.execute("UPDATE operations SET state='accepted',complete=0,work_state='ready',error=NULL WHERE id=?", (op['id'],))
                store.event(db, op['id'], 'verifying', 'started', 'Observation-only recovery admitted for the original dispatched intent')
            if key and not replay:
                app._key(db, actor, key, intent_hash, op['id'])
    return store.receipt(actor, op['id'])
