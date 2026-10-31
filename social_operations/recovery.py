"""Original-operation reactivation: observation or explicitly proven zero-dispatch retry."""
import json
from .domain import DomainError, canonical, digest, normalize_intent


def admit(app, actor, args):
    store = app.store
    change = args['change']
    if str(change.get('native_reference', '')).startswith('item_'):
        from .baseline_rebase import rebase
        return rebase(app, actor, args)
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
            from . import vk_allocation_recovery
            unknown = [c for c in children if c['state'] == 'outcome_unknown' and c['dispatched']]
            pending = db.execute("SELECT 1 FROM attempt_recovery r JOIN attempts a ON a.id=r.attempt_id WHERE a.operation_id=? AND r.finalize_state='pending'", (op['id'],)).fetchone()
            if op['work_state'] == 'done' and not unknown and not pending:
                if not children or not all(c['state'] in ('verified', 'scheduled', 'cancelled')
                                              or vk_allocation_recovery.resolved(db, c) for c in children):
                    raise DomainError('recovery_not_available', next_action='review_outcome')
            if op['work_state'] == 'done' and (unknown or pending):
                for child in unknown:
                    b = store.binding(db, actor, binding_id=child['binding_id'])
                    plan = json.loads(child['plan'])
                    if b['epoch'] != child['binding_epoch'] or plan['action'] not in json.loads(b['rights']):
                        raise DomainError('access_revoked', next_action='reauthorize')
                    allocation = vk_allocation_recovery.candidate(db, op, child)
                    if allocation and vk_allocation_recovery.resolve(store, db, op, child, allocation):
                        continue
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


def retry_failed(app, actor, args):
    """Explicitly re-admit only proven zero-dispatch failures; never an uncertain effect."""
    import hashlib
    store = app.store
    if args.get('item_ref'):
        raise DomainError('retry_original_publication_required')
    if args.get('change', {}).get('kind') != 'retry_failed':
        raise DomainError('invalid_input')
    intent_hash = digest(['retry_failed', normalize_intent('publication_update', args)])
    with store.tx() as db:
        actor = store.current(db, actor)
        key = args.get('request_key')
        publish_only = 'publication.manage' not in actor.scopes
        media_only = (publish_only and 'media.store' in actor.scopes
                      and 'publish' not in actor.scopes)
        if publish_only and (not key or not media_only and 'publish' not in actor.scopes):
            raise DomainError('access_denied', next_action='contact_owner')
        replay = db.execute('SELECT * FROM request_keys WHERE tenant_id=? AND principal_id=? AND key=?',
                            (actor.tenant_id, actor.principal_id, key)).fetchone() if key else None
        if replay and replay['digest'] != intent_hash:
            raise DomainError('idempotency_conflict')
        op = store.private_operation(db, actor, replay['operation_id'] if replay else args['publication_id'])
        if op['publication_id'] != args['publication_id'] or op['revision'] != args['expected_revision']:
            raise DomainError('revision_conflict', next_action='refresh')
        pub = db.execute('SELECT revision,kind FROM publications WHERE id=?', (op['publication_id'],)).fetchone()
        # Application guard, independent of the projected public schema. A publish
        # grant cannot recover a later edit/delete/forward or an adopted native item.
        if publish_only and (
                (media_only and (op['action'] != 'media_store' or pub['kind'] != 'media_store'))
                or (not media_only and (op['action'] != 'publish' or pub['kind'] != 'publish'))):
            raise DomainError('access_denied', next_action='contact_owner')
        children = list(db.execute('SELECT * FROM attempts WHERE operation_id=?', (op['id'],)))
        aliases = set(args['change']['destinations'])
        selected = [c for c in children if c['alias'] in aliases]
        if len(selected) != len(aliases):
            raise DomainError('retry_destination_mismatch')
        if publish_only:
            for child in selected:
                binding = store.binding(db, actor, binding_id=child['binding_id'])
                plan = json.loads(child['plan'])
                if plan['action'] != 'publish' or 'publish' not in json.loads(binding['rights']):
                    raise DomainError('access_denied', next_action='contact_owner')
                if media_only and not store.service_media_topic_allowed(
                        db, actor, binding, str(plan.get('topic_root_id') or '')):
                    raise DomainError('access_denied', next_action='contact_owner')
        # A matching key authorizes one admission only. Even another terminal
        # zero-dispatch failure is observation-only on replay, never a new send.
        if not replay:
            from .assets import expired_native_intent
            if pub['kind'] != 'media_store' and any(
                expired_native_intent(op['created'], json.loads(c['plan']).get('scheduled_at'), store.clock())
                for c in selected
            ):
                raise DomainError('stale_not_dispatched', next_action='none')
            if pub['revision'] != op['revision']:
                raise DomainError('revision_conflict', next_action='refresh')
            if op['work_state'] != 'done':
                raise DomainError('operation_in_progress', next_action='check_status')
            if (any(c['state'] == 'outcome_unknown' for c in children)
                    or any(c['dispatched'] or c['state'] not in ('blocked', 'failed') for c in selected)):
                raise DomainError('retry_not_proven_safe', next_action='review_outcome')
            pending = db.execute("SELECT 1 FROM attempt_recovery r JOIN attempts a ON a.id=r.attempt_id WHERE a.operation_id=? AND r.finalize_state='pending'", (op['id'],)).fetchone()
            if pending:
                raise DomainError('operation_in_progress', next_action='check_status')
            active = db.execute("SELECT count(*) FROM operations WHERE tenant_id=? AND work_state!='done'", (actor.tenant_id,)).fetchone()[0]
            maximum = db.execute('SELECT command_limit FROM tenants WHERE id=?', (actor.tenant_id,)).fetchone()[0]
            if active >= maximum:
                raise DomainError('command_quota_exceeded')
            for child in selected:
                b = store.binding(db, actor, binding_id=child['binding_id'])
                plan = json.loads(child['plan'])
                if b['epoch'] != child['binding_epoch'] or plan['action'] not in json.loads(b['rights']):
                    raise DomainError('access_revoked', next_action='reauthorize')
                if (any(b[k] != plan[k] for k in ('connection_id', 'destination_id', 'account_type', 'secret_ref'))
                        or b['native_id'] != plan['native_target'] or digest(plan) != child['plan_digest']):
                    raise DomainError('retry_binding_changed', next_action='reauthorize')
                app.emojis.frozen_access(db, actor, json.loads(plan['content_json']))
                for asset in plan['assets']:
                    row = db.execute('SELECT bytes FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                                     (asset['ref'], actor.tenant_id, actor.principal_id)).fetchone()
                    if not row or hashlib.sha256(row['bytes']).hexdigest() != asset['sha256']:
                        raise DomainError('asset_integrity')
                # Original plan/existing CAS/checkpoint/attempt identity remain intact.
                db.execute("UPDATE attempts SET state='accepted',stage='accepted',observed='not_attempted',result='{}' WHERE id=? AND dispatched=0", (child['id'],))
                store.event(db, op['id'], 'accepted', 'started',
                            'Explicit retry admitted for a proven never-dispatched failure; frozen intent retained', child['alias'])
            # Renew only the immediate-command window. Native requested time is immutable.
            from .execution_budgets import command_seconds
            budget = command_seconds(json.loads(child['plan']) for child in selected)
            db.execute("UPDATE operations SET state='accepted',complete=0,work_state='ready',deadline=?,error=NULL WHERE id=?",
                       (store.clock()+budget, op['id']))
        if key and not replay:
            app._key(db, actor, key, intent_hash, op['id'])
    return store.receipt(actor, op['id'])


def supersede_failed(app, actor, args):
    """Replace selected zero-dispatch publish failures; never rewrite their frozen intent.

    The replacement has its own publication identity. Successful siblings remain
    on the original publication, with their native object and audit unchanged.
    """
    import hashlib
    from .domain import new_id
    from contracts.social_mcp_v1 import DEFS
    from jsonschema import Draft202012Validator, FormatChecker
    store = app.store
    change = args.get('change', {})
    key = args.get('request_key')
    aliases = change.get('destinations', [])
    if (args.get('item_ref') or change.get('kind') != 'supersede_failed'
            or not isinstance(key, str) or not key
            or not isinstance(aliases, list) or not aliases
            or any(not isinstance(alias, str) for alias in aliases)
            or len(set(aliases)) != len(aliases)
            or set(change) != {'kind', 'destinations', 'content'}):
        raise DomainError('invalid_input')
    content_schema = {'$ref': '#/$defs/content', '$defs': DEFS}
    if not Draft202012Validator(content_schema, format_checker=FormatChecker()).is_valid(change['content']):
        raise DomainError('invalid_input')
    intent_hash = digest(['supersede_failed', normalize_intent('publication_update', args)])
    with store.tx() as db:
        actor = store.current(db, actor)
        if not actor.scopes.intersection({'publish', 'publication.manage'}):
            raise DomainError('access_denied', next_action='contact_owner')
        replay = db.execute('SELECT * FROM request_keys WHERE tenant_id=? AND principal_id=? AND key=?',
                            (actor.tenant_id, actor.principal_id, key)).fetchone()
        if replay:
            if replay['digest'] != intent_hash:
                raise DomainError('idempotency_conflict')
            replacement = store.private_operation(db, actor, replay['operation_id'])
            # Epoch checks do not imply a right that an owner has since removed.
            for child in db.execute('SELECT * FROM attempts WHERE operation_id=?', (replacement['id'],)):
                binding = store.binding(db, actor, binding_id=child['binding_id'])
                if 'publish' not in json.loads(binding['rights']):
                    raise DomainError('access_denied', next_action='contact_owner')
            # Replay is observation only, including after a replacement failure.
            replacement_id = replacement['id']
        else:
            original = store.private_operation(db, actor, args['publication_id'])
            # private_operation already enforces this; keep the admission boundary explicit.
            if original['actor_epoch'] != actor.epoch:
                raise DomainError('access_revoked', next_action='reauthorize')
            pub = db.execute('SELECT * FROM publications WHERE id=?', (original['publication_id'],)).fetchone()
            if (original['publication_id'] != args['publication_id']
                    or original['revision'] != args['expected_revision']
                    or pub['revision'] != args['expected_revision']):
                raise DomainError('revision_conflict', next_action='refresh')
            if original['action'] != 'publish' or pub['kind'] != 'publish':
                raise DomainError('supersede_original_publish_required')
            if original['work_state'] != 'done' or not original['complete']:
                raise DomainError('operation_in_progress', next_action='check_status')
            children = list(db.execute('SELECT * FROM attempts WHERE operation_id=?', (original['id'],)))
            selected = [child for child in children if child['alias'] in aliases]
            if len(selected) != len(aliases):
                raise DomainError('retry_destination_mismatch')
            if (any(child['state'] == 'outcome_unknown' for child in children)
                    or any(child['dispatched'] or child['state'] not in ('blocked', 'failed') for child in selected)):
                raise DomainError('supersede_not_proven_safe', next_action='review_outcome')
            from .assets import expired_native_intent
            if any(expired_native_intent(original['created'], json.loads(child['plan']).get('scheduled_at'), store.clock()) for child in selected):
                raise DomainError('stale_not_dispatched', next_action='none')
            pending = db.execute(
                "SELECT 1 FROM attempt_recovery r JOIN attempts a ON a.id=r.attempt_id "
                "WHERE a.operation_id=? AND r.finalize_state='pending'", (original['id'],)).fetchone()
            if pending:
                raise DomainError('operation_in_progress', next_action='check_status')
            plans, replacement_targets = [], []
            for child in selected:
                binding = store.binding(db, actor, binding_id=child['binding_id'])
                old = json.loads(child['plan'])
                if (binding['epoch'] != child['binding_epoch'] or old['binding_epoch'] != child['binding_epoch']
                        or 'publish' not in json.loads(binding['rights'])
                        or old['action'] != 'publish'):
                    raise DomainError('access_revoked', next_action='reauthorize')
                if (any(binding[k] != old[k] for k in ('connection_id', 'destination_id', 'account_type', 'secret_ref'))
                        or binding['native_id'] != old['native_target'] or digest(old) != child['plan_digest']):
                    raise DomainError('retry_binding_changed', next_action='reauthorize')
                if old.get('existing') or old.get('source') or old.get('mode') != 'execute':
                    raise DomainError('supersede_original_publish_required')
                for asset in old['assets']:
                    row = db.execute('SELECT bytes FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                                     (asset['ref'], actor.tenant_id, actor.principal_id)).fetchone()
                    if not row or hashlib.sha256(row['bytes']).hexdigest() != asset['sha256']:
                        raise DomainError('asset_integrity')
                target = {
                    'content': change['content'],
                    'media': [{'source': {'kind': 'asset', 'id': asset['ref']},
                               'role': asset.get('role', 'image'), 'caption': asset.get('caption', ''),
                               'alt_text': asset.get('alt_text', '')} for asset in old['assets']],
                    'surface': old['surface'], 'mode': 'execute',
                    'delivery': {'kind': 'at', 'at': old['scheduled_at']} if old['scheduled_at'] else {'kind': 'now'},
                }
                replacement_targets.append({'destination': child['alias'], **target})
                # Ordinary compilation and admission checks apply. In particular,
                # old timing is never silently changed to immediate delivery.
                plans.append(app._plan(db, actor, binding, target, 'publish',
                                       topic_root_id=old.get('topic_root_id')))
            publication = new_id('pub')
            lineage = {'publication_id': pub['id'], 'operation_id': original['id'],
                       'revision': original['revision'], 'attempt_ids': [c['id'] for c in selected]}
            replacement_intent = {'to': [p['alias'] for p in plans], 'content': change['content'],
                                  'mode': 'execute', '_supersedes': lineage,
                                  '_replacement_targets': replacement_targets}
            db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?)',
                       (publication, actor.tenant_id, actor.principal_id, 1, 'publish', store.clock()))
            db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?)',
                       (actor.tenant_id, actor.principal_id, publication, 1,
                        canonical(replacement_intent), canonical(plans), digest(plans)))
            from .execution_budgets import command_seconds
            replacement_id = app._new_operation(db, actor, 'publish', replacement_intent,
                                                 publication=publication, revision=1,
                                                 command_timeout=command_seconds(plans))
            for plan in plans:
                db.execute('INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,plan,plan_digest) '
                           'VALUES(?,?,?,?,?,?,?,?)',
                           (new_id('attempt'), replacement_id, plan['binding_id'], plan['binding_epoch'],
                            plan['alias'], plan['provider'], canonical(plan), digest(plan)))
            # Invalidate any stale hooks retained by a worker after it finished.
            # BEGIN IMMEDIATE serializes this CAS with retry admission/worker claim.
            changed = db.execute(
                "UPDATE operations SET fence=fence+1,lease_owner=NULL,lease_until=0 "
                "WHERE id=? AND fence=? AND work_state='done' AND complete=1",
                (original['id'], original['fence'])).rowcount
            if changed != 1:
                raise DomainError('operation_in_progress', next_action='check_status')
            for child in selected:
                changed = db.execute(
                    "UPDATE attempts SET state='cancelled',stage='finished' "
                    "WHERE id=? AND state IN ('blocked','failed') AND dispatched=0 AND plan_digest=?",
                    (child['id'], child['plan_digest'])).rowcount
                if changed != 1:
                    raise DomainError('supersede_not_proven_safe', next_action='review_outcome')
                store.event(db, original['id'], 'finished', 'completed',
                            'Never-dispatched intent superseded by ' + replacement_id +
                            ' (' + publication + '); original plan retained and retry disabled', child['alias'])
            store.event(db, replacement_id, 'accepted', 'started',
                        'Replacement for selected never-dispatched failures of ' + original['id'] +
                        ' (' + pub['id'] + '); successful siblings remain unchanged')
            app._key(db, actor, key, intent_hash, replacement_id)
    return store.receipt(actor, replacement_id)
