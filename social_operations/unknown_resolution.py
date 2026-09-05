"""Owner-only observation proof; never retries or rewrites an unknown attempt."""
import asyncio
import json
from adapters.port import ReadRequest
from .domain import DomainError, canonical, digest, normalize_intent


def bound_attempt(app, db, actor, args):
    app.store.current(db, actor)
    if not actor.owner or not args.get('publication_id'):
        raise DomainError('access_denied')
    pub = db.execute('SELECT * FROM publications WHERE id=? AND tenant_id=? AND principal_id=?',
                     (args['publication_id'], actor.tenant_id, actor.principal_id)).fetchone()
    old = db.execute('SELECT a.*,o.actor_epoch AS original_actor_epoch FROM attempts a JOIN operations o ON o.id=a.operation_id WHERE a.id=? AND o.publication_id=? AND o.tenant_id=? AND o.principal_id=? AND o.work_state=\'done\' AND o.state=\'outcome_unknown\'',
                     (args['change']['attempt_id'], args['publication_id'], actor.tenant_id, actor.principal_id)).fetchone()
    if not pub or not old or old['state'] != 'outcome_unknown' or not old['dispatched']:
        raise DomainError('resolution_not_eligible')
    old = dict(old)
    if old['original_actor_epoch'] != actor.epoch:
        raise DomainError('access_revoked')
    plan = json.loads(old['plan'])
    if digest(plan) != old['plan_digest']:
        raise DomainError('resolution_checkpoint_invalid')
    binding = dict(app.store.binding(db, actor, binding_id=old['binding_id']))
    if binding['epoch'] != old['binding_epoch'] or plan['binding_epoch'] != binding['epoch']:
        raise DomainError('access_revoked')
    if (plan['action'] != 'publish' or not plan.get('scheduled_at') or plan['provider'] != 'vk'
            or plan['native_target'] != binding['native_id'] or plan['connection_id'] != binding['connection_id']):
        raise DomainError('resolution_not_eligible')
    try:
        checkpoint = json.loads(old['checkpoint'])
        cp = checkpoint['adapter']
        if (checkpoint['transition'] not in {'vk_response', 'vk_media_bound'} or cp['version'] != 1 or cp['attempt'] != old['id']
                or cp['plan'] != old['plan_digest'] or cp['target'] != plan['native_target']
                or not str(cp['id']).isdigit() or int(cp['id']) <= 0):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise DomainError('resolution_checkpoint_invalid') from None
    return pub, old, binding, str(cp['id'])


def accept_resolution(app, actor, args):
    intent = normalize_intent('publication_update', args)
    with app.store.tx() as db:
        app.store.current(db, actor)
        if not actor.owner:
            raise DomainError('access_denied')
        op = app._replay(db, actor, 'publication_update', intent, args)
        if not op:
            pub, old, binding, native = bound_attempt(app, db, actor, args)
            if pub['revision'] != args['expected_revision']:
                raise DomainError('revision_conflict')
            if db.execute('SELECT 1 FROM operations WHERE publication_id=? AND work_state!=\'done\'', (pub['id'],)).fetchone():
                raise DomainError('operation_in_progress')
            if db.execute('SELECT 1 FROM attempt_resolutions WHERE attempt_id=?', (old['id'],)).fetchone():
                raise DomainError('attempt_already_resolved')
            revision = pub['revision'] + 1
            db.execute('UPDATE publications SET revision=? WHERE id=? AND revision=?', (revision, pub['id'], pub['revision']))
            db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?)', (actor.tenant_id, actor.principal_id, pub['id'], revision, canonical(intent), '[]', digest([])))
            op = app._new_operation(db, actor, 'publication_update', intent, publication=pub['id'], revision=revision)
            if args.get('request_key'):
                app._key(db, actor, args['request_key'], digest(['publication_update', intent]), op)
    return app.store.receipt(actor, op)


async def run_resolution(worker, op, actor):
    args = json.loads(op['request'])
    with worker.store.connection() as db:
        pub, old, binding, native = bound_attempt(worker.app, db, actor, args)
    original_digest = digest(old['checkpoint'])
    adapter = worker.adapter(binding['provider'], binding['connection_id'])
    cursor, seen, queue_items = None, set(), []
    async with worker.lane(binding['connection_id']):
        async with asyncio.timeout(30):
            for _ in range(100):
                page = await adapter.read(ReadRequest(binding['connection_id'], binding['native_id'], 'scheduled', 100, cursor), worker.hooks(op))
                for item in page.items:
                    if item.native_target != binding['native_id'] or item.namespace != 'scheduled':
                        raise DomainError('resolution_invalid_queue')
                    if item.native_id == native:
                        raise DomainError('resolution_object_present')
                    queue_items.append([item.native_id, item.fingerprint])
                if page.cursor is None:
                    break
                if page.cursor in seen:
                    raise DomainError('resolution_queue_incomplete')
                seen.add(page.cursor)
                cursor = page.cursor
            else:
                raise DomainError('resolution_queue_incomplete')
            published = await adapter.read(ReadRequest(binding['connection_id'], binding['native_id'], 'item', native_item=native, namespace='published'), worker.hooks(op))
            if published.items or published.cursor is not None:
                raise DomainError('resolution_published_collision')
        with worker.store.tx() as db:
            worker.store.fence(db, op['id'], worker.id, op['fence'])
            current_pub, current, current_binding, current_native = bound_attempt(worker.app, db, actor, args)
            if (current_pub['revision'] != op['revision'] or digest(current['checkpoint']) != original_digest
                    or current_binding['epoch'] != binding['epoch'] or current_native != native):
                raise DomainError('resolution_evidence_changed')
            proof = {'kind': 'externally_removed', 'attempt_id': old['id'], 'original_operation_id': old['operation_id'],
                     'tenant_id': actor.tenant_id, 'principal_id': actor.principal_id, 'actor_epoch': actor.epoch,
                     'binding_id': binding['id'], 'binding_epoch': binding['epoch'], 'connection_id': binding['connection_id'],
                     'native_target': binding['native_id'], 'native_id': native, 'checkpoint_digest': original_digest,
                     'scheduled_queue_digest': digest(queue_items), 'scheduled_queue_complete': True,
                     'published_exact_absent': True, 'observed_at': worker.store.clock()}
            db.execute('INSERT INTO attempt_resolutions VALUES(?,?,?,?,?)', (old['id'], op['id'], original_digest, canonical(proof), worker.store.clock()))
            db.execute("UPDATE operations SET state='verified',complete=1,work_state='done',result=? WHERE id=?", (canonical({'message': 'Externally removed native object: absence verified; original publication outcome remains unknown. No publication retried.'}), op['id']))
            worker.store.event(db, op['id'], 'finished', 'completed', 'Complete native queue and exact published lookup prove absence; only this attempt quarantine resolved')
