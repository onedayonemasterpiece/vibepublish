"""Durable immediate command worker. Requested publication time is never eligibility."""
from __future__ import annotations
import asyncio
import fcntl
import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from adapters.port import Asset, Hooks, NativeSource, Observation, ProviderRequest, ReadRequest, RemoteItem, UnavailableAdapter
from .domain import DomainError, OutcomeUnknown, canonical, digest, new_id, parse_time
from .service import Application

TERMINAL = {'verified', 'scheduled', 'blocked', 'failed', 'outcome_unknown', 'cancelled'}


class Worker:
    def __init__(self, store, adapters=None, *, worker_id=None, imagegen=None):
        self.store = store
        self.adapters = adapters or {}
        self.id = worker_id or new_id('worker')
        self.app = Application(store)
        self.imagegen = imagegen
        self.lock_root = store.path.parent / (store.path.name+'.locks')
        self.lock_root.mkdir(mode=0o700, exist_ok=True)

    def adapter(self, provider, connection):
        return self.adapters.get(connection, self.adapters.get(provider, UnavailableAdapter()))

    @asynccontextmanager
    async def lane(self, connection):
        # Cross-process AND cross-task lock; never release a lane while an effect is in flight.
        name = hashlib.sha256(connection.encode()).hexdigest()+'.lock'
        fd = os.open(self.lock_root/name, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.025)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def hooks(self, op, child=None, min_lead=60):
        async def emit(stage, status, message):
            with self.store.tx() as db:
                self.store.fence(db, op['id'], self.id, op['fence'])
                db.execute('UPDATE operations SET worker_seen=?,lease_until=? WHERE id=?', (self.store.clock(), self.store.clock()+30, op['id']))
                if child:
                    db.execute("UPDATE attempts SET stage=?,state=CASE WHEN state='accepted' THEN 'running' ELSE state END WHERE id=?", (stage, child['id']))
                self.store.event(db, op['id'], stage, status, message, child['alias'] if child else None)
        async def checkpoint(transition, state):
            if len(state) > 8192:
                raise DomainError('checkpoint_too_large')
            json.loads(state)
            with self.store.tx() as db:
                self.store.fence(db, op['id'], self.id, op['fence'])
                db.execute('UPDATE attempts SET checkpoint=? WHERE id=?', (canonical({'transition': transition, 'adapter': json.loads(state)}), child['id']))
        async def before_effect(attempt_id, plan_digest):
            with self.store.tx() as db:
                current = self.store.fence(db, op['id'], self.id, op['fence'])
                actor = self.store.operation_actor(current)
                b = self.store.binding(db, actor, binding_id=child['binding_id'])
                plan = json.loads(child['plan'])
                self.app.emojis.frozen_access(db, actor, json.loads(plan['content_json']))
                required = 'publish' if plan['action'] == 'publish' else plan['action']
                if b['epoch'] != child['binding_epoch'] or required not in json.loads(b['rights']):
                    raise DomainError('access_revoked', next_action='reauthorize')
                if current['lease_until'] < self.store.clock():
                    raise DomainError('stale_worker', next_action='refresh')
                if self.store.clock() > op['deadline']:
                    raise DomainError('command_expired', 'The immediate command expired; choose a new time')
                if plan.get('scheduled_at') and parse_time(plan['scheduled_at']) < self.store.clock()+min_lead:
                    raise DomainError('native_lead_time', 'Native submission window closed; no fallback send')
                restore = db.execute("SELECT value FROM settings WHERE key='restore_guard'").fetchone()
                if restore and restore[0] == '1':
                    raise DomainError('restore_requires_reconciliation', next_action='contact_owner')
                unresolved = db.execute("SELECT 1 FROM attempts a JOIN bindings b ON b.id=a.binding_id JOIN destinations d ON d.id=b.destination_id WHERE d.connection_id=? AND a.id!=? AND a.dispatched=1 AND a.state NOT IN ('verified','scheduled','cancelled') LIMIT 1", (plan['connection_id'], child['id'])).fetchone()
                if unresolved:
                    raise DomainError('connection_outcome_unknown', next_action='review_outcome')
                if attempt_id != child['id'] or plan_digest != child['plan_digest']:
                    raise DomainError('plan_mismatch')
                changed = db.execute('UPDATE attempts SET dispatched=1,dispatch_at=?,state=\'running\',stage=\'submitting\' WHERE id=? AND dispatched=0', (self.store.clock(), attempt_id)).rowcount
                if changed != 1:
                    raise OutcomeUnknown('already_dispatched')
                self.store.event(db, op['id'], 'submitting', 'started', 'Durable dispatch marker committed before external effect', child['alias'])
        return Hooks(emit, checkpoint, before_effect)

    def request(self, op, child, actor):
        plan = json.loads(child['plan'])
        assets = []
        with self.store.connection() as db:
            for a in plan['assets']:
                row = db.execute('SELECT bytes,sha256 FROM assets WHERE id=? AND tenant_id=? AND principal_id=?', (a['ref'], actor.tenant_id, actor.principal_id)).fetchone()
                if not row or hashlib.sha256(row['bytes']).hexdigest() != a['sha256']:
                    raise DomainError('asset_integrity')
                assets.append(Asset(**a, data=row['bytes']))
        return ProviderRequest(op['id'], child['id'], child['plan_digest'], plan['connection_id'], plan['account_type'], plan['secret_ref'],
                               plan['destination_id'], plan['native_target'], plan['action'], plan['surface'], plan['content_json'], tuple(assets),
                               plan['scheduled_at'], op['deadline'], RemoteItem(**plan['existing']) if plan['existing'] else None,
                               NativeSource(**plan['source']) if plan['source'] else None, plan['source_authorized'], plan['selection'])

    async def heartbeat(self, op):
        while True:
            await asyncio.sleep(5)
            with self.store.tx() as db:
                self.store.fence(db, op['id'], self.id, op['fence'])
                db.execute('UPDATE operations SET lease_until=?,worker_seen=? WHERE id=?', (self.store.clock()+30, self.store.clock(), op['id']))

    async def run_once(self):
        op = self.store.claim(self.id)
        if not op:
            return False
        pulse = asyncio.create_task(self.heartbeat(op))
        try:
            actor = self.store.operation_actor(op)
            if await self.app.visuals.process(self, op, actor, self.imagegen):
                return True
            if await self.app.emojis.process(self, op, actor):
                return True
            if op['action'] == 'read':
                await self.run_read(op, actor)
                return True
            with self.store.connection() as db:
                children = [dict(c) for c in db.execute('SELECT * FROM attempts WHERE operation_id=?', (op['id'],))]
            pending = [c for c in children if c['state'] not in TERMINAL]
            prepared = {}
            async def preflight(child):
                r = self.request(op, child, actor)
                if json.loads(child['plan']).get('admission_error'):
                    raise DomainError(json.loads(child['plan'])['admission_error'])
                if child['dispatched']:
                    return
                if self.store.clock() > op['deadline']:
                    raise DomainError('command_expired')
                hooks = self.hooks(op, child)
                async with self.lane(r.connection_id):
                    prepared[child['id']] = await self.adapter(child['provider'], r.connection_id).prepare(r, hooks)
                if prepared[child['id']].capability.status != 'supported':
                    raise DomainError('capability_unsupported', next_action='contact_owner')
                if prepared[child['id']].request != r:
                    raise DomainError('adapter_changed_request')
            outcomes = await asyncio.gather(*(preflight(c) for c in pending), return_exceptions=True)
            errors = [e for e in outcomes if isinstance(e, BaseException)]
            if errors and all(isinstance(e, DomainError) and e.code in {'emoji_fallback_required', 'rich_fallback_needs_review'} for e in errors) and all(json.loads(c['plan'])['mode'] == 'execute' for c in pending):
                # Only explicit per-target rendering gates are independent; preserve existing global preflight policy for other failures.
                for child, outcome in zip(pending, outcomes):
                    if isinstance(outcome, BaseException):
                        self.fail(op, child, outcome)
                await asyncio.gather(*(self.run_child(op, c, actor, prepared.get(c['id'])) for c, outcome in zip(pending, outcomes) if not isinstance(outcome, BaseException)))
            elif errors:
                error = errors[0] if isinstance(errors[0], DomainError) else DomainError('provider_preflight_failed', next_action='contact_owner')
                # Already-attempted children must still be observed, not called "not attempted".
                for child in pending:
                    if not child['dispatched']:
                        self.fail(op, child, error)
                await asyncio.gather(*(self.run_child(op, c, actor, None) for c in pending if c['dispatched']))
            elif pending and all(json.loads(c['plan'])['mode'] == 'preview' for c in pending):
                self.preview(op, actor, pending)
                return True
            else:
                await asyncio.gather(*(self.run_child(op, c, actor, prepared.get(c['id'])) for c in pending))
            self.aggregate(op)
        except asyncio.CancelledError:
            # A stopped worker leaves its durable claim for observation-only recovery.
            raise
        except DomainError as exc:
            if exc.code != 'stale_worker':
                self.fail_operation(op, exc)
        except Exception:
            self.fail_operation(op, DomainError('worker_failure', 'Worker failed; inspect the durable operation', 'review_outcome'))
        finally:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
        return True

    async def run_child(self, op, child, actor, prepared):
        try:
            request = self.request(op, child, actor)
            hooks = self.hooks(op, child, prepared.capability.min_lead_seconds if prepared else 60)
            adapter = self.adapter(child['provider'], request.connection_id)
            async with self.lane(request.connection_id):
                # A lease fence is NOT proof that an old remote request is gone.
                with self.store.connection() as db:
                    self.store.fence(db, op['id'], self.id, op['fence'])
                    current = dict(db.execute('SELECT * FROM attempts WHERE id=?', (child['id'],)).fetchone())
                timeout = max(0.1, min(90, op['deadline']-self.store.clock())) if not current['dispatched'] else 30
                async with asyncio.timeout(timeout):
                    observation = (await adapter.reconcile(request, current['checkpoint'], hooks) if current['dispatched'] else
                                   await adapter.execute(prepared, hooks))
                self.finish_child(op, child, actor, observation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                self.fail(op, child, exc if isinstance(exc, DomainError) else DomainError('provider_command_failed', next_action='contact_owner'))
            except DomainError as stale:
                if stale.code != 'stale_worker':
                    raise

    def finish_child(self, op, child, actor, observation):
        if not observation.items or observation.missing_checks:
            raise OutcomeUnknown('incomplete_readback')
        plan = json.loads(child['plan'])
        # The first core slice has single logical remote items. Never silently drop album members.
        if len(observation.items) != 1:
            raise OutcomeUnknown('multi_item_mapping_not_enabled')
        remote = observation.items[0]
        if remote.native_target != plan['native_target']:
            raise OutcomeUnknown('wrong_target_readback')
        action = plan['action']
        if action in ('cancel', 'delete'):
            expected = 'cancelled' if action == 'cancel' else 'deleted'
            if observation.observed != expected:
                raise OutcomeUnknown('lifecycle_outcome_mismatch')
        elif plan['scheduled_at']:
            if observation.observed != 'provider_scheduled':
                raise OutcomeUnknown('native_schedule_not_observed')
        elif observation.observed not in ({'published', 'edited'} if action == 'edit' else {'published'}):
            raise OutcomeUnknown('publication_outcome_mismatch')
        elif remote.namespace != 'published':
            raise OutcomeUnknown('published_namespace_mismatch')
        if plan['existing'] and remote.native_id != plan['existing']['native_id']:
            raise OutcomeUnknown('lifecycle_identity_changed')
        if plan['action'] in ('publish', 'edit', 'reschedule'):
            if remote.text != json.loads(plan['content_json'])['text']:
                raise OutcomeUnknown('content_readback_mismatch')
            if plan['provider'] == 'telegram':
                from .rich_text import normalized_entities
                expected = json.loads(plan['content_json']).get('entities', [])
                actual = normalized_entities(remote.text, json.loads(remote.entities_json))
                if actual != normalized_entities(remote.text, expected):
                    raise OutcomeUnknown('entities_readback_mismatch')
            if tuple(remote.media_hashes) != tuple(a['sha256'] for a in plan['assets']):
                raise OutcomeUnknown('media_readback_mismatch')
        if observation.observed == 'provider_scheduled' and (remote.namespace != 'scheduled' or remote.scheduled_at != plan['scheduled_at']):
            raise OutcomeUnknown('native_time_mismatch')
        if plan['action'] == 'forward' and (not observation.forward_origin_matched or remote.origin != plan['source']['canonical_url']):
            raise OutcomeUnknown('forward_attribution_incomplete')
        with self.store.tx() as db:
            self.store.fence(db, op['id'], self.id, op['fence'])
            b = db.execute('SELECT * FROM bindings WHERE id=?', (child['binding_id'],)).fetchone()
            # Internal outcome persistence survives revocation; private receipt access still denies it.
            item = self.app.project_item(db, actor, b, asdict(remote), publication=op['publication_id'])
            self.save_fact(db, plan['destination_id'], remote, actor.principal_id, op['publication_id'])
            result = {'item_ref': item['ref'], 'observed_at': remote.observed_at, 'media_check': remote.media_check}
            if remote.scheduled_at:
                result.update(queue_ref=item['ref'], effective_at=remote.scheduled_at, requested_at=plan['scheduled_at'], scheduling_owner='provider',
                              navigate_hint='Open the authorized channel native scheduled queue')
            if plan['source']:
                result['forward_origin'] = {'source_ref': new_id('source'), 'provider': child['provider'], 'mode': 'native', 'origin_check': 'matched', 'original_url': remote.origin}
            state = 'scheduled' if observation.observed == 'provider_scheduled' else 'cancelled' if observation.observed == 'cancelled' else 'verified'
            db.execute('UPDATE attempts SET state=?,stage=\'finished\',observed=?,result=?,checkpoint=? WHERE id=?',
                       (state, observation.observed, canonical(result), canonical({'remote': asdict(remote)}), child['id']))
            self.store.event(db, op['id'], 'finished', 'completed', 'Exact provider item observed: '+observation.observed, child['alias'])

    def save_fact(self, db, destination, remote, actor=None, publication=None):
        db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(destination_id,native_id,namespace) DO UPDATE SET snapshot=excluded.snapshot,text=excluded.text,observed_at=excluded.observed_at',
                   (new_id('fact'), destination, remote.native_id, remote.namespace, actor, publication, 'forward' if remote.origin else 'original', canonical(asdict(remote)), remote.text, remote.observed_at))

    def fail(self, op, child, error):
        with self.store.tx() as db:
            self.store.fence(db, op['id'], self.id, op['fence'])
            row = db.execute('SELECT dispatched FROM attempts WHERE id=?', (child['id'],)).fetchone()
            uncertain = bool(row['dispatched'])
            state = 'outcome_unknown' if uncertain else 'blocked'
            db.execute('UPDATE attempts SET state=?,stage=?,observed=? WHERE id=?', (state, state, 'unknown' if uncertain else 'not_attempted', child['id']))
            if uncertain:
                db.execute("UPDATE operations SET state='outcome_unknown' WHERE id=?", (op['id'],))
            db.execute('UPDATE attempts SET result=? WHERE id=?', (canonical({'missing_checks': [error.code]}), child['id']))
            final = OutcomeUnknown(error.code) if uncertain else error
            db.execute('UPDATE operations SET error=? WHERE id=?', (canonical(final.output()), op['id']))
            self.store.event(db, op['id'], state, 'unknown' if uncertain else 'blocked', final.message, child['alias'])

    def fail_operation(self, op, error):
        with self.store.connection() as db:
            children = [dict(c) for c in db.execute('SELECT * FROM attempts WHERE operation_id=?', (op['id'],))]
        for child in children:
            if child['state'] not in TERMINAL:
                self.fail(op, child, error)
        self.aggregate(op, error=error)

    def aggregate(self, op, error=None):
        with self.store.tx() as db:
            self.store.fence(db, op['id'], self.id, op['fence'])
            states = [r[0] for r in db.execute('SELECT state FROM attempts WHERE operation_id=?', (op['id'],))]
            if 'outcome_unknown' in states:
                state = 'outcome_unknown'
            elif any(s not in TERMINAL for s in states):
                state = 'running'
            elif states and all(s == 'scheduled' for s in states):
                state = 'scheduled'
            elif states and all(s == 'cancelled' for s in states):
                state = 'cancelled'
            elif any(s in ('blocked', 'failed') for s in states):
                state = 'partial' if any(s in ('verified', 'scheduled') for s in states) else 'blocked'
            else:
                state = 'blocked' if error else 'verified'
            complete = state != 'running'
            db.execute('UPDATE operations SET state=?,complete=?,work_state=? WHERE id=?', (state, int(complete), 'done' if complete else 'working', op['id']))
            if error:
                db.execute('UPDATE operations SET error=? WHERE id=?', (canonical(error.output()), op['id']))
            self.store.event(db, op['id'], 'finished', 'completed', 'Automatic command work ended; future delivery remains provider-owned')

    def preview(self, op, actor, children):
        token = secrets.token_urlsafe(32)
        with self.store.tx() as db:
            self.store.fence(db, op['id'], self.id, op['fence'])
            db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?,NULL)', (new_id('decision'), actor.tenant_id, actor.principal_id, op['publication_id'], op['revision'], digest([c['plan_digest'] for c in children]), self.store.token_hash(token)))
            db.execute('UPDATE operations SET state=\'needs_approval\',complete=1,work_state=\'done\',result=? WHERE id=?', (canonical({**json.loads(db.execute('SELECT result FROM operations WHERE id=?',(op['id'],)).fetchone()[0]), 'review_token': token, 'dry_run': True, 'content_previews': [{'destination': c['alias'], 'provider': c['provider'], 'text': json.loads(json.loads(c['plan'])['content_json'])['text'], 'entities': json.loads(json.loads(c['plan'])['content_json']).get('entities', [])} for c in children]}), op['id']))
            for child in children:
                db.execute('UPDATE attempts SET state=\'needs_approval\',stage=\'awaiting_approval\' WHERE id=?', (child['id'],))
            self.store.event(db, op['id'], 'awaiting_approval', 'completed', 'Preview only; no provider mutation occurred')

    async def run_read(self, op, actor):
        args = json.loads(op['request'])
        with self.store.connection() as db:
            b = dict(self.store.binding(db, actor, binding_id=args['_binding_id']))
            if b['epoch'] != args['_binding_epoch']:
                raise DomainError('access_revoked', next_action='reauthorize')
        query = args['query']
        request = ReadRequest(b['connection_id'], b['native_id'], query['kind'], args.get('limit', 25), args.get('_provider_cursor'),
                              args.get('_native_item'), args.get('_namespace'), query.get('text', ''))
        async with self.lane(b['connection_id']):
            async with asyncio.timeout(30):
                page = await self.adapter(b['provider'], b['connection_id']).read(request, self.hooks(op))
        with self.store.tx() as db:
            self.store.fence(db, op['id'], self.id, op['fence'])
            self.store.current(db, actor)
            self.store.binding(db, actor, binding_id=b['id'])
            items = []
            for remote in page.items:
                if remote.native_target != b['native_id']:
                    raise DomainError('wrong_target_readback', next_action='contact_owner')
                self.save_fact(db, b['destination_id'], remote)
                items.append(self.app.project_item(db, actor, b, asdict(remote)))
            result = {'items': items, 'truncated': page.cursor is not None}
            if page.cursor:
                result['next_cursor'] = self.store.cursor(db, actor, 'read', digest(query), page.cursor)
            db.execute('UPDATE operations SET state=\'verified\',complete=1,work_state=\'done\',result=? WHERE id=?', (canonical(result), op['id']))
            self.store.event(db, op['id'], 'finished', 'completed', 'Current provider read complete; history was not used as a queue')
