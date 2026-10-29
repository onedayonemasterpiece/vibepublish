"""Explicit one-parent continuations. Event bodies are hints, never authority.

The existing operation/attempt ledger owns every story effect. This module only
admits one ordinary immediate child after exact published-parent observation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re

from adapters.port import Hooks, ReadRequest
from contracts.social_mcp_v1 import VK_STORY_LINK_TEXTS
from .domain import DomainError, canonical, digest, new_id, parse_time

LOG = logging.getLogger(__name__)
CHECK_INTERVAL = 60
RECOVERY_WINDOW = 24 * 3600


def register(app, db, actor, intent, operation_id, plans):
    spec = intent.get('linked_story')
    if spec is None:
        return
    candidates = [p for p in plans if p['provider'] == 'vk']
    if (len(candidates) != 1 or intent.get('surface', 'post') != 'post'
            or intent.get('mode', 'execute') != 'execute' or intent.get('visual')
            or set(spec) != {'media', 'text'} or spec['text'] not in VK_STORY_LINK_TEXTS
            or intent.get('story_link')
            or not isinstance(spec['media'], list) or len(spec['media']) != 1):
        raise DomainError('linked_story_requires_one_vk_wall_and_image')
    parent = candidates[0]
    if parent['action'] != 'publish' or parent.get('admission_error'):
        raise DomainError('linked_story_parent_not_ready')
    binding = app.store.binding(db, actor, binding_id=parent['binding_id'])
    target = {'content': {'text': ''}, 'media': spec['media'],
              'surface': 'story', 'delivery': {'kind': 'now'}, 'mode': 'execute'}
    story = app._plan(db, actor, binding, target, 'publish')
    if len(story['assets']) != 1 or story['assets'][0]['role'] != 'image':
        raise DomainError('linked_story_requires_one_vk_wall_and_image')
    parent_attempt = db.execute('SELECT id FROM attempts WHERE operation_id=? AND binding_id=?',
                                (operation_id, parent['binding_id'])).fetchone()
    operation = db.execute('SELECT * FROM operations WHERE id=?', (operation_id,)).fetchone()
    if parent_attempt is None or operation is None:
        raise DomainError('linked_story_parent_not_ready')
    now = app.store.clock()
    expected = parse_time(parent['scheduled_at']) if parent['scheduled_at'] else now
    ident = new_id('vkdep')
    db.execute('''INSERT INTO vk_story_dependencies
        (id,parent_attempt_id,parent_publication_id,parent_revision,binding_id,binding_epoch,
         connection_id,native_target,story_plan,story_plan_digest,link_text,next_check,expires,created,updated)
         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (ident, parent_attempt['id'], operation['publication_id'], operation['revision'],
         parent['binding_id'], parent['binding_epoch'], parent['connection_id'], parent['native_target'],
         canonical(story), digest(story), spec['text'], now, expected + RECOVERY_WINDOW, now, now))
    app.store.event(db, operation_id, 'accepted', 'completed',
                    'Approved linked story retained; waiting for exact published VK parent', parent['alias'])


def _authority(store, db, dep, actor):
    store.current(db, actor)
    parent = db.execute('SELECT * FROM attempts WHERE id=?', (dep['parent_attempt_id'],)).fetchone()
    op = db.execute('SELECT * FROM operations WHERE id=?', (parent['operation_id'],)).fetchone()
    publication = db.execute('SELECT revision FROM publications WHERE id=?',
                             (dep['parent_publication_id'],)).fetchone()
    binding = store.binding(db, actor, binding_id=dep['binding_id'])
    if (op['actor_epoch'] != actor.epoch or binding['epoch'] != dep['binding_epoch']
            or 'publish' not in actor.scopes or 'publish' not in json.loads(binding['rights'])
            or binding['connection_id'] != dep['connection_id']
            or binding['native_id'] != dep['native_target']):
        raise DomainError('linked_story_access_changed', next_action='reauthorize')
    if not publication or publication['revision'] != dep['parent_revision']:
        raise DomainError('linked_story_parent_changed', next_action='review_outcome')
    restore = db.execute("SELECT value FROM settings WHERE key='restore_guard'").fetchone()
    if restore and restore[0] == '1':
        raise DomainError('restore_requires_reconciliation', next_action='contact_owner')
    plan = json.loads(dep['story_plan'])
    if digest(plan) != dep['story_plan_digest']:
        raise DomainError('plan_mismatch')
    for asset in plan['assets']:
        row = db.execute('SELECT sha256,bytes FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                         (asset['ref'], actor.tenant_id, actor.principal_id)).fetchone()
        if not row or row['sha256'] != asset['sha256'] or hashlib.sha256(row['bytes']).hexdigest() != asset['sha256']:
            raise DomainError('asset_integrity')
    return dict(parent), dict(op), plan


def assert_child_authority(store, db, actor, operation_id, plan):
    ident = plan.get('vk_story_dependency_id')
    if not ident:
        return
    dep = db.execute('SELECT * FROM vk_story_dependencies WHERE id=?', (ident,)).fetchone()
    if not dep or dep['state'] != 'queued' or dep['child_operation_id'] != operation_id:
        raise DomainError('linked_story_not_authorized')
    _authority(store, db, dep, actor)
    if store.clock() >= dep['expires']:
        raise DomainError('linked_story_recovery_expired')


def ingest_events(store, connection_id, native_target, updates, cursor):
    """Trusted Long Poll adapter only. Commit receipts before advancing cursor.

    No public unauthenticated webhook and no raw provider payload persistence.
    """
    if (not isinstance(updates, list) or len(updates) > 1000
            or not re.fullmatch(r'-[1-9][0-9]*', native_target)
            or not isinstance(cursor, str) or not re.fullmatch(r'[0-9]{1,32}', cursor)):
        raise DomainError('vk_event_batch_invalid')
    now = store.clock()
    with store.tx() as db:
        tracked = db.execute("SELECT 1 FROM vk_story_dependencies WHERE connection_id=? AND native_target=? AND state='waiting' LIMIT 1",
                             (connection_id, native_target)).fetchone()
        if not tracked:
            return 0
        received = 0
        for event in updates:
            if not isinstance(event, dict) or event.get('type') not in {
                    'wall_post_new', 'wall_schedule_post_new', 'wall_schedule_post_delete'}:
                continue
            if type(event.get('group_id')) is not int or event['group_id'] != -int(native_target):
                continue
            obj = event.get('object')
            if not isinstance(obj, dict) or type(obj.get('id')) is not int or obj['id'] <= 0:
                continue
            if obj.get('owner_id', int(native_target)) != int(native_target):
                continue
            native_id = str(obj['id'])
            queued_id = obj.get('postponed_id')
            if queued_id is not None and (type(queued_id) is not int or queued_id <= 0):
                continue
            source_native_id = str(queued_id) if queued_id is not None else None
            key = digest([event['type'], native_id, source_native_id, event.get('event_id')])
            inserted = db.execute('INSERT OR IGNORE INTO vk_story_events VALUES(?,?,?,?,?,?,?)',
                                  (connection_id, native_target, key, event['type'], native_id, source_native_id, now)).rowcount
            received += inserted
            if inserted:
                db.execute("UPDATE vk_story_dependencies SET next_check=?,updated=? WHERE connection_id=? AND native_target=? AND state='waiting' AND (parent_native_id=? OR parent_native_id=? OR parent_native_id IS NULL)",
                           (now, now, connection_id, native_target, native_id, source_native_id))
        db.execute('''INSERT INTO vk_story_event_cursors VALUES(?,?,?,?)
             ON CONFLICT(connection_id,native_target) DO UPDATE SET cursor=excluded.cursor,updated=excluded.updated''',
                   (connection_id, native_target, cursor, now))
        # Event hints have no approval value after the bounded recovery window.
        db.execute('DELETE FROM vk_story_events WHERE received<?', (now - 2 * RECOVERY_WINDOW,))
    return received


def _set_state(store, ident, state, reason=None):
    with store.tx() as db:
        db.execute('UPDATE vk_story_dependencies SET state=?,reason=?,updated=? WHERE id=?',
                   (state, reason, store.clock(), ident))
    LOG.info('vk_story_dependency state=%s dependency=%s reason=%s', state, ident, reason)


async def _poll_events(worker, dep):
    transport = getattr(worker.adapter('vk', dep['connection_id']), 'transport', None)
    poll = getattr(transport, 'poll_wall_events', None)
    status = 'unavailable_adapter'
    try:
        if poll:
            with worker.store.connection() as db:
                row = db.execute('SELECT cursor FROM vk_story_event_cursors WHERE connection_id=? AND native_target=?',
                                 (dep['connection_id'], dep['native_target'])).fetchone()
            async with asyncio.timeout(8):
                batch = await poll(dep['native_target'], row['cursor'] if row else None)
            status = batch['status']
            if status in {'ready', 'cursor_reset'}:
                ingest_events(worker.store, dep['connection_id'], dep['native_target'],
                              batch['updates'], batch['cursor'])
    except (DomainError, TimeoutError, OSError):
        status = 'temporarily_unavailable'
    with worker.store.tx() as db:
        db.execute('UPDATE vk_story_dependencies SET event_status=? WHERE id=?', (status, dep['id']))


async def advance(worker):
    """One bounded exact-parent observation; ordinary commands retain priority."""
    store = worker.store
    now = store.clock()
    with store.tx() as db:
        params = [now]
        where = ''
        if worker.connection_ids is not None:
            ids = tuple(worker.connection_ids)
            if not ids:
                return False
            where = ' AND connection_id IN (' + ','.join('?' for _ in ids) + ')'
            params.extend(ids)
        row = db.execute("SELECT * FROM vk_story_dependencies WHERE state IN ('waiting','queued') AND next_check<=?" + where + ' ORDER BY next_check LIMIT 1', params).fetchone()
        if not row:
            return False
        dep = dict(row)
        db.execute('UPDATE vk_story_dependencies SET next_check=?,updated=? WHERE id=?',
                   (now + CHECK_INTERVAL, now, dep['id']))
        parent_op = db.execute('SELECT o.* FROM operations o JOIN attempts a ON a.operation_id=o.id WHERE a.id=?',
                               (dep['parent_attempt_id'],)).fetchone()
    try:
        if dep['state'] == 'queued':
            with store.connection() as db:
                child = db.execute('SELECT * FROM operations WHERE id=?', (dep['child_operation_id'],)).fetchone()
                dispatched = db.execute('SELECT MAX(dispatched) FROM attempts WHERE operation_id=?', (dep['child_operation_id'],)).fetchone()[0]
            if child['complete']:
                state = 'verified' if child['state'] == 'verified' else 'outcome_unknown' if child['state'] == 'outcome_unknown' else 'blocked'
                _set_state(store, dep['id'], state, None if state == 'verified' else 'linked_story_child_' + child['state'])
                return True
            if dispatched:
                return True  # Only the original child ledger may reconcile its effect.
        actor = store.operation_actor(parent_op)
        with store.connection() as db:
            parent, op, story_plan = _authority(store, db, dep, actor)
            if dep['state'] == 'queued':
                return True
            if now >= dep['expires']:
                raise DomainError('linked_story_recovery_expired')
            if parent['state'] in {'blocked', 'failed', 'cancelled', 'partial', 'outcome_unknown'}:
                raise DomainError('linked_story_parent_' + parent['state'])
            if parent['state'] not in {'scheduled', 'verified'}:
                return True
            # General history can be refreshed by later reads. It must never
            # replace the original parent's durable accepted-effect baseline.
            baseline = json.loads(parent['checkpoint']).get('remote')
            if (not isinstance(baseline, dict)
                    or baseline.get('namespace') not in {'scheduled', 'published'}
                    or baseline.get('native_target') != dep['native_target']
                    or not re.fullmatch(r'[1-9][0-9]*', str(baseline.get('native_id', '')))):
                raise DomainError('linked_story_parent_identity_unproven')
            native_id = baseline['native_id']
            expected = json.loads(parent['plan']).get('scheduled_at')
        await _poll_events(worker, dep)
        with store.tx() as db:
            db.execute('UPDATE vk_story_dependencies SET parent_native_id=? WHERE id=?', (native_id, dep['id']))
            mappings = db.execute("SELECT DISTINCT native_id FROM vk_story_events WHERE connection_id=? AND native_target=? AND source_native_id=? AND event_type='wall_post_new' AND received>=?",
                                  (dep['connection_id'], dep['native_target'], native_id, dep['created'])).fetchall()
            event = bool(mappings)
            if expected and now < parse_time(expected) and not event:
                db.execute('UPDATE vk_story_dependencies SET next_check=? WHERE id=?', (min(parse_time(expected), now + CHECK_INTERVAL), dep['id']))
                return True
        async def no_effect(*args):
            raise DomainError('dependency_observation_only')
        async def noop(*args):
            return None
        adapter = worker.adapter('vk', dep['connection_id'])
        request = ReadRequest(dep['connection_id'], dep['native_target'], 'item', limit=1,
                              native_item=native_id, namespace='published')
        async with worker.lane(dep['connection_id']):
            async with asyncio.timeout(30):
                if expected:
                    resolver = getattr(adapter, 'resolve_story_parent', None)
                    if resolver is None:
                        raise DomainError('linked_story_parent_mapping_unproven')
                    observed = await resolver(dep['native_target'], native_id,
                                              [row['native_id'] for row in mappings])
                else:
                    page = await adapter.read(request, Hooks(noop, no_effect, no_effect))
                    if not page.items:
                        return True
                    if len(page.items) != 1:
                        raise DomainError('linked_story_parent_identity_unproven')
                    observed = page.items[0]
        if observed is None:
            return True
        if ((not expected and observed.native_id != native_id) or observed.native_target != dep['native_target']
                or observed.namespace != 'published' or observed.scheduled_at
                or observed.text != baseline['text']
                or tuple(observed.provider_media) != tuple(baseline.get('provider_media', []))):
            raise DomainError('linked_story_parent_changed')
        with store.tx() as db:
            current = db.execute('SELECT * FROM vk_story_dependencies WHERE id=?', (dep['id'],)).fetchone()
            if current['state'] != 'waiting':
                return True
            _authority(store, db, current, actor)
            if store.clock() >= current['expires']:
                raise DomainError('linked_story_recovery_expired')
            # Child creation and state transition are one transaction. No crash gap,
            # new request key, or repeat event can admit a second child.
            story_plan.update(story_link_json=canonical({
                'url': f'https://vk.com/wall{dep["native_target"]}_{observed.native_id}',
                'text': dep['link_text'], 'target': dep['native_target'], 'id': observed.native_id}),
                story_link_binding_id=dep['binding_id'], story_link_binding_epoch=dep['binding_epoch'],
                vk_story_dependency_id=dep['id'],
                story_parent_json=canonical({'native_target': observed.native_target,
                    'native_id': observed.native_id, 'text': observed.text,
                    'provider_media': list(observed.provider_media)}))
            publication = new_id('pub')
            intent = {'linked_story_parent': dep['parent_publication_id'], 'dependency_id': dep['id']}
            db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?)',
                       (publication, actor.tenant_id, actor.principal_id, 1, 'publish', store.clock()))
            db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?)',
                       (actor.tenant_id, actor.principal_id, publication, 1, canonical(intent), canonical([story_plan]), digest([story_plan])))
            child_op = worker.app._new_operation(db, actor, 'publish', intent, publication=publication)
            db.execute('INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,plan,plan_digest) VALUES(?,?,?,?,?,?,?,?)',
                       (new_id('attempt'), child_op, dep['binding_id'], dep['binding_epoch'], story_plan['alias'], 'vk', canonical(story_plan), digest(story_plan)))
            db.execute("UPDATE vk_story_dependencies SET state='queued',child_operation_id=?,updated=?,reason=NULL WHERE id=? AND state='waiting'",
                       (child_op, store.clock(), dep['id']))
            store.event(db, op['id'], 'reading_back', 'completed',
                        'Exact VK parent is published; approved linked story admitted once', story_plan['alias'])
        LOG.info('vk_story_dependency state=queued dependency=%s operation=%s', dep['id'], child_op)
    except asyncio.CancelledError:
        raise
    except DomainError as exc:
        transient = {'vk_http_failed', 'vk_transport_failed', 'vk_cooldown', 'vk_api_failed',
                     'needs_auth', 'provider_observation_unavailable', 'command_quota_exceeded',
                     'vk_queue_namespace_mismatch', 'linked_story_parent_mapping_unproven'}
        if exc.code == 'linked_story_parent_mapping_unproven':
            with store.tx() as db:
                db.execute('UPDATE vk_story_dependencies SET reason=? WHERE id=?', (exc.code, dep['id']))
        if exc.code not in transient:
            state = 'expired' if exc.code == 'linked_story_recovery_expired' else 'cancelled' if exc.code == 'linked_story_parent_changed' else 'blocked'
            _set_state(store, dep['id'], state, exc.code)
    except (TimeoutError, OSError):
        pass  # Observation can be repeated; no provider mutation occurred here.
    return True
