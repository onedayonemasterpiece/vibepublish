"""Owner-only provider absence proof; never retries or rewrites an unknown attempt."""
import asyncio
import json
from adapters.port import ReadRequest
from .domain import DomainError, canonical, digest, normalize_intent


def bound_attempt(app, db, actor, args):
    app.store.current(db, actor)
    if not actor.owner or not args.get('publication_id'):
        raise DomainError('access_denied')
    pub = db.execute(
        'SELECT * FROM publications WHERE id=? AND tenant_id=? AND principal_id=?',
        (args['publication_id'], actor.tenant_id, actor.principal_id),
    ).fetchone()
    old = db.execute(
        "SELECT a.*,o.actor_epoch AS original_actor_epoch FROM attempts a "
        "JOIN operations o ON o.id=a.operation_id WHERE a.id=? AND o.publication_id=? "
        "AND o.tenant_id=? AND o.principal_id=? AND o.work_state='done' "
        "AND o.state='outcome_unknown'",
        (args['change']['attempt_id'], args['publication_id'],
         actor.tenant_id, actor.principal_id),
    ).fetchone()
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
    if (plan['action'] not in {'publish', 'edit', 'reschedule'}
            or not plan.get('scheduled_at') or plan['provider'] != 'vk'
            or plan['native_target'] != binding['native_id']
            or plan['connection_id'] != binding['connection_id']):
        raise DomainError('resolution_not_eligible')

    try:
        checkpoint = json.loads(old['checkpoint'])
        cp = checkpoint['adapter']
        if (cp['version'] != 1 or cp['attempt'] != old['id']
                or cp['plan'] != old['plan_digest']
                or cp['target'] != plan['native_target']):
            raise ValueError()
        native = cp.get('id')
        if native is None:
            # Historical VK wall.post may have crossed the dispatch boundary but
            # lost its response before a native post ID was saved. Only a
            # scheduled publish with a frozen non-empty text intent and a
            # vk_prepared checkpoint is eligible for provider-wide absence proof.
            content = json.loads(plan['content_json'])
            media = cp.get('media')
            if (plan['action'] != 'publish'
                    or checkpoint['transition'] != 'vk_prepared'
                    or not isinstance(content, dict)
                    or not isinstance(content.get('text'), str)
                    or not content['text'].strip()
                    or not isinstance(media, list)
                    or len(media) != len(plan.get('assets', ()))):
                raise ValueError()
        else:
            if (checkpoint['transition'] not in {'vk_response', 'vk_media_bound'}
                    or not str(native).isdigit() or int(native) <= 0):
                raise ValueError()
            native = str(native)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise DomainError('resolution_checkpoint_invalid') from None

    if plan['action'] in {'edit', 'reschedule'}:
        existing = plan.get('existing')
        if (native is None or not isinstance(existing, dict)
                or existing.get('namespace') != 'scheduled'
                or existing.get('native_target') != plan['native_target']
                or existing.get('native_id') != native
                or not existing.get('scheduled_at')):
            raise DomainError('resolution_not_eligible')
    return pub, old, binding, native


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
            if db.execute(
                "SELECT 1 FROM operations WHERE publication_id=? AND work_state!='done'",
                (pub['id'],),
            ).fetchone():
                raise DomainError('operation_in_progress')
            if db.execute(
                'SELECT 1 FROM attempt_resolutions WHERE attempt_id=?', (old['id'],)
            ).fetchone():
                raise DomainError('attempt_already_resolved')
            revision = pub['revision'] + 1
            db.execute(
                'UPDATE publications SET revision=? WHERE id=? AND revision=?',
                (revision, pub['id'], pub['revision']),
            )
            db.execute(
                'INSERT INTO revisions VALUES(?,?,?,?,?,?,?)',
                (actor.tenant_id, actor.principal_id, pub['id'], revision,
                 canonical(intent), '[]', digest([])),
            )
            op = app._new_operation(
                db, actor, 'publication_update', intent,
                publication=pub['id'], revision=revision,
            )
            if args.get('request_key'):
                app._key(
                    db, actor, args['request_key'],
                    digest(['publication_update', intent]), op,
                )
    return app.store.receipt(actor, op)


async def _complete_search(adapter, binding, text, hooks):
    cursor, seen, observed = None, set(), []
    for _ in range(100):
        page = await adapter.read(
            ReadRequest(
                binding['connection_id'], binding['native_id'],
                'search', 100, cursor, text=text,
            ),
            hooks,
        )
        for item in page.items:
            if item.native_target != binding['native_id'] or item.namespace != 'published':
                raise DomainError('resolution_invalid_published_search')
            if item.text == text:
                raise DomainError('resolution_published_collision')
            observed.append([item.native_id, item.fingerprint])
        if page.cursor is None:
            return observed
        if page.cursor in seen:
            raise DomainError('resolution_search_incomplete')
        seen.add(page.cursor)
        cursor = page.cursor
    raise DomainError('resolution_search_incomplete')


async def run_resolution(worker, op, actor):
    args = json.loads(op['request'])
    with worker.store.connection() as db:
        pub, old, binding, native = bound_attempt(worker.app, db, actor, args)
    original_digest = digest(old['checkpoint'])
    plan = json.loads(old['plan'])
    adapter = worker.adapter(binding['provider'], binding['connection_id'])
    cursor, seen, queue_items = None, set(), []
    idless = native is None
    expected_text = json.loads(plan['content_json'])['text'] if idless else None
    expected_time = plan['scheduled_at'] if idless else None
    published_search = []

    async with worker.lane(binding['connection_id']):
        async with asyncio.timeout(30):
            for _ in range(100):
                page = await adapter.read(
                    ReadRequest(
                        binding['connection_id'], binding['native_id'],
                        'scheduled', 100, cursor,
                    ),
                    worker.hooks(op),
                )
                for item in page.items:
                    if item.native_target != binding['native_id'] or item.namespace != 'scheduled':
                        raise DomainError('resolution_invalid_queue')
                    if ((native is not None and item.native_id == native)
                            or (idless and item.text == expected_text
                                and item.scheduled_at == expected_time)):
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

            if native is not None:
                published = await adapter.read(
                    ReadRequest(
                        binding['connection_id'], binding['native_id'], 'item',
                        native_item=native, namespace='published',
                    ),
                    worker.hooks(op),
                )
                if published.items or published.cursor is not None:
                    raise DomainError('resolution_published_collision')
            else:
                published_search = await _complete_search(
                    adapter, binding, expected_text, worker.hooks(op)
                )

        with worker.store.tx() as db:
            worker.store.fence(db, op['id'], worker.id, op['fence'])
            current_pub, current, current_binding, current_native = bound_attempt(
                worker.app, db, actor, args
            )
            if (current_pub['revision'] != op['revision']
                    or digest(current['checkpoint']) != original_digest
                    or current_binding['epoch'] != binding['epoch']
                    or current_native != native):
                raise DomainError('resolution_evidence_changed')
            proof = {
                'kind': 'scheduled_intent_absent' if idless else 'externally_removed',
                'attempt_id': old['id'],
                'original_operation_id': old['operation_id'],
                'tenant_id': actor.tenant_id,
                'principal_id': actor.principal_id,
                'actor_epoch': actor.epoch,
                'binding_id': binding['id'],
                'binding_epoch': binding['epoch'],
                'connection_id': binding['connection_id'],
                'native_target': binding['native_id'],
                'native_id': native,
                'checkpoint_digest': original_digest,
                'scheduled_queue_digest': digest(queue_items),
                'scheduled_queue_complete': True,
                'published_exact_absent': native is not None,
                'published_search_digest': digest(published_search) if idless else None,
                'published_search_complete': idless,
                'observed_at': worker.store.clock(),
            }
            db.execute(
                'INSERT INTO attempt_resolutions VALUES(?,?,?,?,?)',
                (old['id'], op['id'], original_digest,
                 canonical(proof), worker.store.clock()),
            )
            message = (
                'Scheduled VK intent absent: complete native queue and published '
                'search prove no matching effect; original publication outcome '
                'remains unknown. No publication retried.'
                if idless else
                'Externally removed native object: absence verified; original '
                'publication outcome remains unknown. No publication retried.'
            )
            db.execute(
                "UPDATE operations SET state='verified',complete=1,work_state='done',result=? WHERE id=?",
                (canonical({'message': message}), op['id']),
            )
            worker.store.event(
                db, op['id'], 'finished', 'completed',
                ('Complete native queue and published search prove the idless '
                 'scheduled intent absent; only this attempt quarantine resolved'
                 if idless else
                 'Complete native queue and exact published lookup prove absence; '
                 'only this attempt quarantine resolved'),
            )
