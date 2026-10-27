"""Durable immediate command worker. Requested publication time is never eligibility."""
from __future__ import annotations
import asyncio
import fcntl
import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from adapters.port import Asset, Hooks, NativeSource, Observation, ProviderRequest, ReadRequest, RemoteItem, UnavailableAdapter
from .domain import DomainError, OutcomeUnknown, canonical, digest, new_id, parse_time, timestamp
from .service import Application
from .media_budget import MediaBudgetDeferred, reserve
from .provider_diagnostics import diagnostic_scope, provider_call, safe_diagnostic, budget_diagnostic

TERMINAL = {'verified', 'scheduled', 'blocked', 'failed', 'outcome_unknown', 'cancelled', 'partial'}

# Shared provider error policy: VK (including W2), Telegram and MAX report
# these codes to this one worker retry scheduler. All other errors are terminal.
TRANSIENT_ERRORS = frozenset({
    'provider_preflight_failed', 'provider_preflight_timeout',
    'provider_command_failed', 'provider_read_deadline', 'receipt_lost',
    'telegram_rpc_failed', 'telegram_cooldown', 'telegram_queue_response_invalid',
    'telegram_history_response_invalid', 'telegram_thread_response_invalid',
    'telegram_response_identity_missing',
    'vk_api_failed', 'vk_http_failed', 'vk_transport_failed', 'vk_cooldown',
    'vk_response_invalid', 'vk_response_identity_missing', 'vk_queue_response_invalid',
    'vk_event_response_invalid', 'vk_upload_failed', 'vk_story_upload_failed',
    'vk_upload_transient_empty_photo', 'vk_upload_response_invalid',
    'vk_story_upload_response_invalid', 'vk_video_upload_response_invalid',
    'vk_photo_read_failed', 'vk_upload_server_invalid', 'vk_queue_read_incomplete',
    'vk_readback_missing', 'vk_photo_binding_unavailable',
    'connection_review_limit', 'incomplete_readback', 'exact_identity_not_observed',
    'max_outcome_unknown', 'max_recovery_observation_unavailable',
})


class Worker:
    def __init__(self, store, adapters=None, *, worker_id=None, imagegen=None, connection_ids=None, include_unrouted=True):
        self.store = store
        self.adapters = adapters or {}
        self.id = worker_id or new_id('worker')
        self.app = Application(store)
        self.imagegen = imagegen
        self.connection_ids=connection_ids;self.include_unrouted=include_unrouted
        self.next_media_store_purge = 0
        self.lock_root = store.path.parent / (store.path.name+'.locks')
        self.lock_root.mkdir(mode=0o700, exist_ok=True)

    def adapter(self, provider, connection):
        return self.adapters.get(connection, self.adapters.get(provider, UnavailableAdapter()))

    def deadline(self, op, child, *, min_lead=60):
        """Frozen acceptance-to-provider horizon; retries cannot move this time."""
        plan = json.loads(child['plan'])
        if op['action'] not in {'publish', 'publication_update'} or plan.get('workload') == 'media_store':
            return op['deadline']
        when = plan.get('scheduled_at')
        return parse_time(when) - min_lead if when else op['created'] + 900

    @staticmethod
    def transient(code):
        return code in TRANSIENT_ERRORS

    @staticmethod
    def saved_native_id(child):
        """An actual provider checkpoint ID, never a guessed text/time match."""
        try:
            saved = json.loads(child['checkpoint'])
            data = saved.get('adapter', saved)
            if (data.get('attempt') != child['id']
                    or data.get('plan') != child['plan_digest']
                    or data.get('target') != json.loads(child['plan'])['native_target']):
                return None
            state = data.get('driver', data)
            ident = state.get('native_id') or state.get('id') or (
                (state.get('ids') or [None])[0])
            if not isinstance(ident, (str, int)):
                return None
            ident = str(ident)
            return ident if ident and all(c.isalnum() or c in '_-' for c in ident) else None
        except (TypeError, ValueError, KeyError, IndexError):
            return None

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

    def diagnostic_observer(self, op, child=None):
        """Append bounded safe metadata to the existing cursor-readable ledger."""
        def observe(details):
            with self.store.tx() as db:
                self.store.fence(db, op['id'], self.id, op['fence'])
                count = db.execute("SELECT count(*) FROM events WHERE operation_id=? AND body LIKE '%provider_diagnostic %'", (op['id'],)).fetchone()[0]
                if count >= 512:
                    return
                row = db.execute('SELECT stage,dispatched FROM attempts WHERE id=?', (child['id'],)).fetchone() if child else None
                stage = row['stage'] if row else 'verifying'
                record = {**safe_diagnostic(details), 'operation_id': op['id'],
                          'action': op['action']}
                if op.get('publication_id'):
                    record['publication_id'] = op['publication_id']
                if child:
                    record.update(attempt_id=child['id'], provider=child['provider'],
                                  dispatched=bool(row['dispatched']))
                if count == 511:
                    record = {'operation_id': op['id'], 'status': 'completed',
                              'operation': 'diagnostic_limit_reached'}
                self.store.event(db, op['id'], stage,
                    details.get('status') if details.get('status') in {'started','completed','failed'} else 'failed',
                    'provider_diagnostic ' + canonical(budget_diagnostic(record)), child['alias'] if child else None)
        return observe

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
                from .vk_story_dependencies import assert_child_authority
                assert_child_authority(self.store, db, actor, op['id'], plan)
                required = 'publish' if plan['action'] == 'publish' else plan['action']
                current_rights = json.loads(b['rights'])
                if plan.get('story_link_binding_id'):
                    source_binding = self.store.binding(db, actor, binding_id=plan['story_link_binding_id'])
                    if (source_binding['epoch'] != plan['story_link_binding_epoch']
                            or 'publish' not in json.loads(source_binding['rights'])):
                        raise DomainError('source_access_revoked', next_action='reauthorize')
                special_schedule_revoked = (
                    bool(plan.get('basic_group_schedule_authorized'))
                    and 'basic_group_schedule' not in current_rights
                )
                if (b['epoch'] != child['binding_epoch'] or required not in current_rights
                        or special_schedule_revoked):
                    raise DomainError('access_revoked', next_action='reauthorize')
                if current['lease_until'] < self.store.clock():
                    raise DomainError('stale_worker', next_action='refresh')
                if self.store.clock() >= self.deadline(op, child, min_lead=min_lead):
                    raise DomainError('command_expired', 'The original publication window has expired')
                if plan.get('scheduled_at') and parse_time(plan['scheduled_at']) < self.store.clock()+min_lead:
                    raise DomainError('native_lead_time', 'Native submission window closed; no fallback send')
                restore = db.execute("SELECT value FROM settings WHERE key='restore_guard'").fetchone()
                if restore and restore[0] == '1':
                    raise DomainError('restore_requires_reconciliation', next_action='contact_owner')
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
            if plan.get('story_link_binding_id'):
                source_binding = self.store.binding(db, actor, binding_id=plan['story_link_binding_id'])
                if (source_binding['epoch'] != plan['story_link_binding_epoch']
                        or 'publish' not in json.loads(source_binding['rights'])):
                    raise DomainError('source_access_revoked', next_action='reauthorize')
            for a in plan['assets']:
                row = db.execute('SELECT bytes,sha256 FROM assets WHERE id=? AND tenant_id=? AND principal_id=?', (a['ref'], actor.tenant_id, actor.principal_id)).fetchone()
                if not row or hashlib.sha256(row['bytes']).hexdigest() != a['sha256']:
                    raise DomainError('asset_integrity')
                assets.append(Asset(**a, data=row['bytes']))
        return ProviderRequest(op['id'], child['id'], child['plan_digest'], plan['connection_id'], plan['account_type'], plan['secret_ref'],
                               plan['destination_id'], plan['native_target'], plan['action'], plan['surface'], plan['content_json'], tuple(assets),
                               plan['scheduled_at'], self.deadline(op, child), RemoteItem(**plan['existing']) if plan['existing'] else None,
                               NativeSource(**plan['source']) if plan['source'] else None, plan['source_authorized'], plan['selection'],
                               subject=RemoteItem(**plan['subject']) if plan.get('subject') else None,
                               reaction=plan.get('reaction'),reaction_mode=plan.get('reaction_mode'),
                               topic_root_id=plan.get('topic_root_id'),
                               basic_group_schedule_authorized=bool(plan.get('basic_group_schedule_authorized')),
                               story_link_json=plan.get('story_link_json', '{}'),
                               story_parent_json=plan.get('story_parent_json', '{}'))

    async def heartbeat(self, op):
        while True:
            await asyncio.sleep(5)
            with self.store.tx() as db:
                self.store.fence(db, op['id'], self.id, op['fence'])
                db.execute('UPDATE operations SET lease_until=?,worker_seen=? WHERE id=?', (self.store.clock()+30, self.store.clock(), op['id']))

    async def run_once(self, *, operation_id=None):
        try:
            if operation_id is None and self.store.clock() >= self.next_media_store_purge:
                with self.store.tx() as db:
                    self.app._purge_media_store_assets(db)
                self.next_media_store_purge = self.store.clock() + 60
            op = self.store.claim(
                self.id,
                connection_ids=self.connection_ids,
                include_unrouted=self.include_unrouted,
                operation_id=operation_id,
            )
        except sqlite3.OperationalError as exc:
            # BEGIN IMMEDIATE contention happens before a claim and therefore
            # before any provider effect. Do not crash the production worker;
            # the outer loop will retry the same durable work on its next pass.
            if 'locked' not in str(exc).lower():
                raise
            return False
        if not op:
            if operation_id is not None:
                return False
            from .vk_story_dependencies import advance
            return await advance(self)
        pulse = asyncio.create_task(self.heartbeat(op))
        try:
            actor = self.store.operation_actor(op)
            if await self.app.visuals.process(self, op, actor, self.imagegen):
                return True
            if await self.app.emojis.process(self, op, actor):
                return True
            if op['action'] == 'publication_update' and json.loads(op['request']).get('change', {}).get('kind') == 'reconcile_removed':
                from .unknown_resolution import run_resolution
                await run_resolution(self, op, actor)
                return True
            if op['action'] == 'destinations':
                from .destination_resolution import process
                await process(self, op, actor)
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
                remaining = self.deadline(op, child) - self.store.clock()
                if remaining <= 0:
                    raise DomainError('command_expired')
                hooks = self.hooks(op, child)
                async with asyncio.timeout(remaining):
                    async with self.lane(r.connection_id):
                        prepared[child['id']] = await self.adapter(child['provider'], r.connection_id).prepare(r, hooks)
                if prepared[child['id']].capability.status != 'supported':
                    raise DomainError('capability_unsupported', next_action='contact_owner')
                if prepared[child['id']].request != r:
                    raise DomainError('adapter_changed_request')
            async def observed_preflight(child):
                with diagnostic_scope(self.diagnostic_observer(op, child)):
                    with provider_call(child['provider'], 'preflight'):
                        return await preflight(child)
            admission = next((json.loads(c['plan']).get('admission_error') for c in pending
                              if json.loads(c['plan']).get('admission_error')), None)
            if admission:
                self.fail_operation(op, DomainError(admission))
                return True
            outcomes = await asyncio.gather(*(observed_preflight(c) for c in pending), return_exceptions=True)
            # Frozen deterministic admission precedes these independent provider checks.
            if pending and all(json.loads(c['plan'])['mode'] == 'preview' for c in pending) and not any(
                    isinstance(e, BaseException) for e in outcomes):
                self.preview(op, actor, pending)
                return True
            for child, outcome in zip(pending, outcomes):
                if isinstance(outcome, BaseException):
                    if isinstance(outcome, asyncio.CancelledError):
                        raise outcome
                    error = (outcome if isinstance(outcome, DomainError) else
                             DomainError('provider_preflight_timeout' if isinstance(outcome, TimeoutError)
                                         else 'provider_preflight_failed'))
                    if self.store.clock() >= self.deadline(op, child):
                        self.expire_child(op, child, actor)
                    else:
                        self.fail(op, child, error)
            await asyncio.gather(*(self.run_child(op, c, actor, prepared.get(c['id']))
                                   for c, outcome in zip(pending, outcomes)
                                   if not isinstance(outcome, BaseException)))
            await self.finalize_pending(op, actor)
            self.aggregate(op)
            self.schedule_retry(op)
        except asyncio.CancelledError:
            # A stopped worker leaves its durable claim for observation-only recovery.
            raise
        except DomainError as exc:
            if exc.code != 'stale_worker':
                self.fail_operation(op, exc)
        except Exception:
            self.fail_operation(op, DomainError('worker_failure', 'Worker failed before a confirmed result'))
        finally:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
        return True

    def expire_child(self, op, child, actor):
        """Finish an exhausted attempt from a checkpointed provider ID, otherwise refuse."""
        with self.store.connection() as db:
            child = dict(db.execute('SELECT * FROM attempts WHERE id=?', (child['id'],)).fetchone())
        plan = json.loads(child['plan'])
        ident = self.saved_native_id(child) if child['dispatched'] and plan['action'] == 'publish' else None
        if ident:
            try:
                with self.store.connection() as db:
                    self.recovery_authority(db, op, child, actor)
                scheduled = plan.get('scheduled_at')
                target = plan['native_target']
                saved = json.loads(child['checkpoint'])
                state = saved.get('adapter', saved).get('driver') or saved.get('adapter', saved)
                # The provider owns permalink construction; never guess an address.
                url = state.get('recovery_reference') or state.get('url')
                if not url and isinstance(state.get('item'), dict):
                    url = state['item'].get('url')
                if not isinstance(url, str) or not url.startswith('https://'):
                    url = None
                remote = RemoteItem(
                    ident, 'scheduled' if scheduled else 'published',
                    json.loads(plan['content_json'])['text'], digest([child['id'], ident]),
                    timestamp(self.store.clock()), scheduled,
                    native_target=target, url=url,
                    media_check='incomplete' if plan['assets'] else 'not_applicable',
                    entities_json=canonical(json.loads(plan['content_json']).get('entities', [])),
                )
                self.finish_child(op, child, actor, Observation(
                    'provider_scheduled' if scheduled else 'published', (remote,)))
                with self.store.tx() as db:
                    self.store.fence(db, op['id'], self.id, op['fence'])
                    row = db.execute('SELECT result FROM attempts WHERE id=?', (child['id'],)).fetchone()
                    result = json.loads(row['result'])
                    if url:
                        result['url'] = url
                    db.execute('UPDATE attempts SET result=? WHERE id=?', (canonical(result), child['id']))
                    self.store.event(db, op['id'], 'finished', 'completed',
                                     'Provider native ID '+ident+' accepted; readback unavailable within budget', child['alias'])
                return
            except DomainError as error:
                self.fail(op, child, error)
                return
        self.fail(op, child, DomainError(
            'publication_unconfirmed' if child['dispatched'] else 'command_expired',
            'Publication could not be confirmed before the fixed deadline' if child['dispatched']
            else 'Command expired before provider dispatch; no post was sent', 'none'))

    def schedule_retry(self, op):
        """One durable bounded backoff for every provider and the media-store lane."""
        with self.store.tx() as db:
            current = db.execute('SELECT * FROM operations WHERE id=?', (op['id'],)).fetchone()
            if not current:
                return
            result = json.loads(current['result'])
            now = self.store.clock()
            # Fixed backoff from command age, without counters or querying the event ledger.
            age = now - current['created']
            delay = 5 if age < 5 else 15 if age < 20 else 30 if age < 50 else 60
            waits = []
            for child in db.execute('SELECT * FROM attempts WHERE operation_id=?', (op['id'],)):
                if child['state'] == 'accepted' and child['stage'] == 'waiting_connection':
                    at = json.loads(child['result']).get('media_budget_retry_at')
                    if at is not None and now < self.deadline(op, child):
                        waits.append(min(float(at), self.deadline(op, child)))
                    continue
                if child['state'] != 'blocked':
                    continue
                code = (json.loads(child['result']).get('missing_checks') or [''])[0]
                if not self.transient(code) or now >= self.deadline(op, child):
                    continue
                waits.append(min(now + delay, self.deadline(op, child)))
                db.execute("UPDATE attempts SET state=?,stage='waiting_connection' WHERE id=?",
                           ('running' if child['dispatched'] else 'accepted', child['id']))
            if not waits:
                return
            retry_at = min(waits)
            result['poll_after_seconds'] = max(1, int(retry_at-now))
            db.execute("UPDATE operations SET state='running',complete=0,work_state='working',"
                       "lease_owner=NULL,lease_until=?,error=NULL,result=? WHERE id=?",
                       (retry_at, canonical(result), op['id']))
            self.store.event(db, op['id'], 'waiting_connection', 'started',
                             'Automatic provider retry within original acceptance horizon')

    async def run_child(self, op, child, actor, prepared):
        with diagnostic_scope(self.diagnostic_observer(op, child)):
            return await self._run_child(op, child, actor, prepared)

    async def _run_child(self, op, child, actor, prepared):
        try:
            request = self.request(op, child, actor)
            hooks = self.hooks(op, child, prepared.capability.min_lead_seconds if prepared else 60)
            adapter = self.adapter(child['provider'], request.connection_id)
            remaining = self.deadline(op, child, min_lead=prepared.capability.min_lead_seconds if prepared else 60) - self.store.clock()
            if remaining <= 0:
                self.expire_child(op, child, actor)
                return
            async with asyncio.timeout(remaining):
                async with self.lane(request.connection_id):
                    # A lease fence is NOT proof that an old remote request is gone.
                    with self.store.tx() as db:
                        self.store.fence(db, op['id'], self.id, op['fence'])
                        current = dict(db.execute('SELECT * FROM attempts WHERE id=?', (child['id'],)).fetchone())
                        if prepared and not current['dispatched'] and child['provider'] == 'vk':
                            from .vk_staged_photos import select
                            staging = select(db, op, current)
                            if staging:
                                prepared = replace(prepared, state_json=canonical({
                                    **json.loads(prepared.state_json), 'staged_photos': staging}))
                        if not current['dispatched'] and child['provider']=='telegram':
                            reserve(db, json.loads(child['plan']), child['id'], self.store.clock())
                        if current['dispatched']:
                            self.recovery_authority(db, op, child, actor)
                    checkpoint = current['checkpoint']
                    if current['dispatched']:
                        with self.store.tx() as db:
                            self.store.fence(db, op['id'], self.id, op['fence'])
                            db.execute('INSERT OR IGNORE INTO attempt_recovery(attempt_id,plan_digest,original_checkpoint,created) VALUES(?,?,?,?)',
                                       (child['id'], child['plan_digest'], checkpoint, self.store.clock()))
                            recovery = db.execute('SELECT * FROM attempt_recovery WHERE attempt_id=?', (child['id'],)).fetchone()
                            hint = {**json.loads(recovery['hint']), 'operation_id': op['id'], 'attempt_id': child['id'], 'plan_digest': child['plan_digest']}
                            checkpoint = canonical({**json.loads(checkpoint), 'core_recovery': hint})
                    from .execution_budgets import execution_seconds
                    execute_limit = execution_seconds(json.loads(child['plan']))
                    timeout = min(execute_limit, self.deadline(op, child)-self.store.clock()) if not current['dispatched'] else 90
                    async with asyncio.timeout(timeout) as execution_budget:
                        if (not current['dispatched'] and child['provider']=='max'
                                and request.action in {'publish','reschedule'} and request.scheduled_at):
                            original_before_effect=hooks.before_effect
                            async def before_effect(attempt_id,plan_digest):
                                await original_before_effect(attempt_id,plan_digest)
                                # One fresh bounded verification phase, only after
                                # the durable guard succeeds. Never replay an effect.
                                execution_budget.reschedule(asyncio.get_running_loop().time()+90)
                            hooks=Hooks(hooks.emit_progress,hooks.checkpoint,before_effect)
                        with provider_call(child['provider'], 'reconcile' if current['dispatched'] else 'execute') as diagnostic:
                            observation = (await adapter.reconcile(request, checkpoint, hooks) if current['dispatched'] else
                                           await adapter.execute(prepared, hooks))
                            diagnostic.update(observed=observation.observed, items_count=len(observation.items))
                            if observation.items:
                                diagnostic['media_check'] = observation.items[0].media_check
                    self.finish_child(op, child, actor, observation, needs_finalize=callable(getattr(adapter, 'finalize', None)))
        except MediaBudgetDeferred as deferred:
            with self.store.tx() as db:
                self.store.fence(db,op['id'],self.id,op['fence'])
                changed=db.execute("UPDATE attempts SET state='accepted',stage='waiting_connection',result=? WHERE id=? AND dispatched=0",(canonical({'media_budget_retry_at':deferred.until}),child['id'])).rowcount
                if changed!=1:raise OutcomeUnknown('media_budget_after_dispatch')
                self.store.event(db,op['id'],'waiting_connection','started','Telegram media capacity unavailable before provider upload',child['alias'])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                if self.store.clock() >= self.deadline(op, child):
                    self.expire_child(op, child, actor)
                else:
                    self.fail(op, child, exc if isinstance(exc, DomainError) else DomainError('provider_command_failed'))
            except DomainError as stale:
                if stale.code != 'stale_worker':
                    raise

    def recovery_authority(self, db, op, child, actor):
        self.store.current(db, actor)
        if op['actor_epoch'] != actor.epoch:
            raise DomainError('access_revoked', next_action='reauthorize')
        b = self.store.binding(db, actor, binding_id=child['binding_id'])
        plan = json.loads(child['plan'])
        if b['epoch'] != child['binding_epoch'] or plan['action'] not in json.loads(b['rights']):
            raise DomainError('access_revoked', next_action='reauthorize')
        if any(b[key] != plan[key] for key in ('connection_id', 'destination_id', 'account_type', 'secret_ref')) or b['native_id'] != plan['native_target']:
            raise DomainError('recovery_binding_changed', next_action='reauthorize')
        if digest(plan) != child['plan_digest']:
            raise DomainError('plan_mismatch')

    async def finalize_pending(self, op, actor):
        with self.store.connection() as db:
            children = [dict(r) for r in db.execute("SELECT a.* FROM attempts a JOIN attempt_recovery r ON r.attempt_id=a.id WHERE a.operation_id=? AND r.finalize_state='pending'", (op['id'],))]
        for child in children:
            request = self.request(op, child, actor)
            adapter = self.adapter(child['provider'], request.connection_id)
            # Missing hook after restart is not evidence that quarantine was released.
            finalize = getattr(adapter, 'finalize', None)
            try:
                async with self.lane(request.connection_id):
                    with self.store.connection() as db:
                        self.store.fence(db, op['id'], self.id, op['fence'])
                        self.recovery_authority(db, op, child, actor)
                    if not callable(finalize):
                        raise DomainError('provider_finalize_unavailable')
                    # The adapter may learn a native ID only during recovery;
                    # do not overwrite the immutable pre-effect checkpoint to
                    # carry it. Supply the already committed observation instead.
                    with self.store.connection() as db:
                        recovery=db.execute(
                            'SELECT observation,original_checkpoint FROM attempt_recovery WHERE attempt_id=?',
                            (child['id'],)).fetchone()
                    final=canonical({**json.loads(child['checkpoint']),
                        'committed_observation':json.loads(recovery['observation']),
                        'original_checkpoint':recovery['original_checkpoint']})
                    async with asyncio.timeout(30):
                        await finalize(request, final, self.finalization_hooks(op, child))
                    with self.store.tx() as db:
                        self.store.fence(db, op['id'], self.id, op['fence'])
                        self.recovery_authority(db, op, child, actor)
                        db.execute("UPDATE attempt_recovery SET finalize_state='done',finalized=? WHERE attempt_id=? AND finalize_state='pending'", (self.store.clock(), child['id']))
                        self.store.event(db, op['id'], 'finished', 'completed', 'Provider quarantine finalization acknowledged', child['alias'])
            except asyncio.CancelledError:
                raise
            except DomainError as exc:
                if exc.code == 'stale_worker':
                    raise
                self.finalization_deferred(op, child)
            except Exception:
                self.finalization_deferred(op, child)

    def finalization_hooks(self, op, child):
        hooks = self.hooks(op, child)
        async def no_checkpoint(*args):
            raise DomainError('resolved_checkpoint_immutable')
        async def no_effect(*args):
            raise DomainError('finalization_effect_forbidden')
        return Hooks(hooks.emit_progress, no_checkpoint, no_effect)

    def finalization_deferred(self, op, child):
        with self.store.tx() as db:
            self.store.fence(db, op['id'], self.id, op['fence'])
            self.store.event(db, op['id'], 'verifying', 'blocked', 'Effect is durably resolved; provider quarantine finalization will retry without an effect', child['alias'])

    def finish_no_effect(self,op,child,actor,observation,*,needs_finalize):
        from adapters.port import NoEffectProof
        proof=observation.no_effect
        if (not isinstance(proof,NoEffectProof) or observation.observed!='not_attempted'
                or observation.items or observation.missing_checks
                or proof.reason!='trusted_preinput_guard' or not needs_finalize):
            raise OutcomeUnknown('no_effect_proof_invalid')
        evidence=json.loads(proof.evidence_json)
        if (not isinstance(evidence,dict) or evidence.get('trusted_clicks')!=0
                or type(evidence.get('trusted_clicks')) is not int
                or evidence.get('input_unreachable') is not True
                or evidence.get('absence_only') is not False):
            raise OutcomeUnknown('no_effect_proof_invalid')
        with self.store.tx() as db:
            self.store.fence(db,op['id'],self.id,op['fence'])
            self.recovery_authority(db,op,child,actor)
            current=db.execute('SELECT * FROM attempts WHERE id=?',(child['id'],)).fetchone()
            recovery=db.execute('SELECT * FROM attempt_recovery WHERE attempt_id=?',(child['id'],)).fetchone()
            original=recovery['original_checkpoint'] if recovery else current['checkpoint']
            if not current['dispatched'] or digest(json.loads(original))!=proof.checkpoint_sha256:
                raise OutcomeUnknown('no_effect_checkpoint_mismatch')
            hint=dict(operation_id=op['id'],attempt_id=child['id'],plan_digest=child['plan_digest'])
            db.execute('INSERT OR IGNORE INTO attempt_recovery(attempt_id,plan_digest,original_checkpoint,hint,created) VALUES(?,?,?,?,?)',
                (child['id'],child['plan_digest'],original,canonical(hint),self.store.clock()))
            db.execute("UPDATE attempt_recovery SET observation=?,finalize_state='pending',resolved=? WHERE attempt_id=?",
                (canonical(asdict(observation)),self.store.clock(),child['id']))
            final=canonical(dict(no_effect=asdict(proof),original_checkpoint=json.loads(original),core_recovery=hint))
            result=canonical(dict(compensation='intent_cancelled_without_effect',reason=proof.reason))
            # Preserve historical dispatch=1. This intent is cancelled, never
            # re-admitted as a never-dispatched retry or projected as a fake item.
            db.execute("UPDATE attempts SET state='cancelled',stage='finished',observed='not_attempted',result=?,checkpoint=? WHERE id=?",(result,final,child['id']))
            self.store.event(db,op['id'],'finished','completed','Original intent cancelled: trusted input guard proves no effect; no item fabricated',child['alias'])

    def finish_child(self, op, child, actor, observation, *, needs_finalize=False):
        if (observation.items and json.loads(child['plan'])['action'] == 'publish'
                and observation.items[0].native_id):
            # The provider has identified the post; no media-review quarantine.
            observation = replace(observation, missing_checks=())
        if getattr(observation,'no_effect',None) is not None:
            return self.finish_no_effect(op,child,actor,observation,needs_finalize=needs_finalize)
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
        elif action=='react':
            if observation.observed!='reacted':raise OutcomeUnknown('reaction_outcome_mismatch')
        elif plan['scheduled_at']:
            if observation.observed != 'provider_scheduled':
                raise OutcomeUnknown('native_schedule_not_observed')
        elif observation.observed not in ({'published', 'edited'} if action == 'edit' else {'published'}):
            raise OutcomeUnknown('publication_outcome_mismatch')
        elif remote.namespace != ('story' if plan.get('surface') == 'story' else 'published'):
            raise OutcomeUnknown('published_namespace_mismatch')
        if action in ('reply','react'):
            subject=plan.get('subject')
            if not subject or plan['provider']!='max' or remote.namespace!='published':
                raise OutcomeUnknown('engagement_subject_missing')
            if action=='reply':
                if remote.reply_to_native_id!=subject['native_id'] or remote.native_id==subject['native_id']:
                    raise OutcomeUnknown('reply_subject_mismatch')
            else:
                if (not remote.own_reactions_observed or remote.native_id!=subject['native_id'] or remote.text!=subject['text']
                        or remote.observed_media!=RemoteItem(**subject).observed_media
                        or (plan['reaction'] in remote.own_reactions)!=(plan['reaction_mode']=='add')):
                    raise OutcomeUnknown('reaction_subject_or_state_mismatch')
        if plan['existing'] and remote.native_id != plan['existing']['native_id']:
            from adapters.port import NativeReplacement
            proof=observation.replacement
            old=plan['existing']
            if (not isinstance(proof,NativeReplacement) or plan['provider']!='max' or plan['account_type']!='max_web'
                    or action!='reschedule' or old['namespace']!='scheduled' or remote.namespace!='scheduled'
                    or proof.previous_native_id!=old['native_id'] or proof.native_id!=remote.native_id
                    or proof.previous_fingerprint!=old['fingerprint']
                    or proof.evidence not in {'trusted_ui_native_queue_replacement','stable_native_correlation'}
                    or remote.text!=old['text']):
                raise OutcomeUnknown('lifecycle_identity_changed')
        elif observation.replacement is not None:
            raise OutcomeUnknown('unexpected_native_replacement')
        if plan['action'] in ('publish', 'edit', 'reschedule', 'reply') and action != 'publish':
            if remote.text != json.loads(plan['content_json'])['text']:
                raise OutcomeUnknown('content_readback_mismatch')
            if plan['provider'] == 'max' and plan['account_type'] == 'max_web':
                from .rich_text import max_entities
                expected = json.loads(plan['content_json']).get('entities', [])
                actual = max_entities(remote.text, json.loads(remote.entities_json))
                if actual != max_entities(remote.text, expected):
                    raise OutcomeUnknown('entities_readback_mismatch')
            if plan['provider'] == 'max' and plan['account_type'] == 'max_web':
                from adapters.port import downloaded_media
                existing = plan.get('existing') or {}
                preserved = existing.get('observed_media', ())
                source_hashes = tuple(a['sha256'] for a in plan['assets'])
                if preserved and (not source_hashes or source_hashes == tuple(existing.get('media_hashes', ()))):
                    if remote.observed_media != downloaded_media(preserved):
                        raise OutcomeUnknown('download_media_lifecycle_changed')
                if remote.observed_media and (remote.provider_media or remote.media_check != 'download_binding'):
                    raise OutcomeUnknown('download_media_binding_missing')
            if tuple(remote.media_hashes) != tuple(a['sha256'] for a in plan['assets']):
                raise OutcomeUnknown('media_readback_mismatch')
        if observation.observed == 'provider_scheduled' and (remote.namespace != 'scheduled' or remote.scheduled_at != plan['scheduled_at']):
            raise OutcomeUnknown('native_time_mismatch')
        if plan['action'] == 'forward' and (not observation.forward_origin_matched or remote.origin != plan['source']['canonical_url']):
            raise OutcomeUnknown('forward_attribution_incomplete')
        if action=='forward' and plan['provider']=='max':
            from .rich_text import max_entities
            subject=RemoteItem(**plan['subject']) if plan.get('subject') else None
            if (not subject or not plan['source_authorized'] or remote.text!=subject.text
                    or remote.observed_media!=subject.observed_media
                    or max_entities(remote.text,json.loads(remote.entities_json))!=max_entities(subject.text,json.loads(subject.entities_json))):
                raise OutcomeUnknown('max_forward_content_or_media_mismatch')
        with self.store.tx() as db:
            self.store.fence(db, op['id'], self.id, op['fence'])
            current_child = db.execute('SELECT * FROM attempts WHERE id=?', (child['id'],)).fetchone()
            if not current_child['dispatched']:
                raise OutcomeUnknown('dispatch_not_recorded')
            recovery = db.execute('SELECT * FROM attempt_recovery WHERE attempt_id=?', (child['id'],)).fetchone()
            if recovery:
                self.recovery_authority(db, op, child, actor)
            original = recovery['original_checkpoint'] if recovery else current_child['checkpoint']
            hint = {**(json.loads(recovery['hint']) if recovery else {}), 'operation_id': op['id'], 'attempt_id': child['id'], 'plan_digest': child['plan_digest']}
            if recovery or needs_finalize:
                db.execute('INSERT OR IGNORE INTO attempt_recovery(attempt_id,plan_digest,original_checkpoint,hint,created) VALUES(?,?,?,?,?)',
                           (child['id'], child['plan_digest'], original, canonical(hint), self.store.clock()))
                db.execute('UPDATE attempt_recovery SET observation=?,finalize_state=?,resolved=? WHERE attempt_id=?',
                           (canonical(asdict(observation)), 'pending' if needs_finalize else 'done', self.store.clock(), child['id']))
            b = db.execute('SELECT * FROM bindings WHERE id=?', (child['binding_id'],)).fetchone()
            # Internal outcome persistence survives revocation; private receipt access still denies it.
            item = self.app.project_item(db, actor, b, asdict(remote), publication=op['publication_id'])
            self.save_fact(db, plan['destination_id'], remote, actor.principal_id, op['publication_id'])
            result = {'item_ref': item['ref'], 'observed_at': remote.observed_at, 'media_check': remote.media_check}
            if remote.scheduled_at:
                result['effective_at'] = remote.scheduled_at
            if observation.observed == 'provider_scheduled' and remote.scheduled_at:
                result.update(queue_ref=item['ref'], requested_at=plan['scheduled_at'], scheduling_owner='provider',
                              navigate_hint='Open the authorized channel native scheduled queue')
            if action=='react':
                result.update(reaction=plan['reaction'],reaction_mode=plan['reaction_mode'])
            if action=='reply':result['reply_to_ref']=plan['subject_ref']
            if plan['source']:
                result['forward_origin'] = {'source_ref': new_id('source'), 'provider': child['provider'], 'mode': 'native', 'origin_check': 'matched', 'original_url': remote.origin}
            state = 'scheduled' if observation.observed == 'provider_scheduled' else 'cancelled' if observation.observed == 'cancelled' else 'verified'
            final_checkpoint = {'remote': asdict(remote), 'core_recovery': hint}
            db.execute('UPDATE attempts SET state=?,stage=\'finished\',observed=?,result=?,checkpoint=? WHERE id=?',
                       (state, observation.observed, canonical(result), canonical(final_checkpoint), child['id']))
            if plan.get('workload') == 'media_store' and state == 'verified':
                staging = [row['asset_id'] for row in db.execute(
                    "SELECT asset_id FROM media_store_assets WHERE publication_id=? AND purpose='staging'",
                    (op['publication_id'],))]
                db.executemany('DELETE FROM assets WHERE id=?', [(ident,) for ident in staging])
            self.store.event(db, op['id'], 'finished', 'completed', 'Exact provider item observed: '+observation.observed, child['alias'])

    def save_fact(self, db, destination, remote, actor=None, publication=None):
        snapshot = asdict(remote)
        previous = db.execute(
            'SELECT snapshot FROM facts WHERE destination_id=? AND native_id=? AND namespace=?',
            (destination, remote.native_id, remote.namespace),
        ).fetchone()
        if (previous and not snapshot.get('observed_media')
                and snapshot.get('media_check') != 'incomplete'):
            prior = json.loads(previous['snapshot'])
            # A thread/feed read intentionally avoids downloading bytes. Preserve
            # earlier byte evidence only while the ordered provider attachments
            # and album membership still identify the exact same media item.
            if (tuple(snapshot.get('provider_media', ())) == tuple(prior.get('provider_media', ()))
                    and tuple(snapshot.get('member_ids', ())) == tuple(prior.get('member_ids', ()))):
                snapshot['observed_media'] = prior.get('observed_media', [])
                snapshot['media_hashes'] = prior.get('media_hashes', [])
                snapshot['media_check'] = prior.get('media_check', snapshot.get('media_check'))
        db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(destination_id,native_id,namespace) DO UPDATE SET snapshot=excluded.snapshot,text=excluded.text,observed_at=excluded.observed_at',
                   (new_id('fact'), destination, remote.native_id, remote.namespace, actor, publication, 'forward' if remote.origin else 'original', canonical(snapshot), remote.text, remote.observed_at))

    def fail(self, op, child, error):
        """A failed provider attempt is local; no terminal outcome_unknown or review action."""
        final = DomainError(error.code, error.message, 'none' if error.next_action == 'review_outcome' else error.next_action)
        with self.store.tx() as db:
            self.store.fence(db, op['id'], self.id, op['fence'])
            row = db.execute('SELECT dispatched FROM attempts WHERE id=?', (child['id'],)).fetchone()
            db.execute("UPDATE attempts SET state='blocked',stage='blocked',observed=?,result=? WHERE id=?",
                       ('unknown' if row['dispatched'] else 'not_attempted',
                        canonical({'missing_checks': [final.code], 'reason': final.message}), child['id']))
            db.execute('UPDATE operations SET error=? WHERE id=?', (canonical(final.output()), op['id']))
            self.store.event(db, op['id'], 'finished', 'blocked', final.message, child['alias'])

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
            own_states = [r[0] for r in db.execute('SELECT state FROM attempts WHERE operation_id=?', (op['id'],))]
            from .managed_item_edits import latest_attempts
            # Observation-only commands have no delivery attempts of their own.
            # Their failure state must not be replaced by historical uncertainty.
            projected = latest_attempts(db, op) if own_states else []
            states = [row['state'] for row in projected]
            if len(states) > len(own_states) and any(s not in TERMINAL for s in own_states):
                state = 'running'
            elif any(s not in TERMINAL for s in states):
                state = 'running'
            elif any(row.get('sync_status') == 'outdated' for row in projected):
                state = 'partial'
            elif states and all(s == 'scheduled' for s in states):
                state = 'scheduled'
            elif states and all(s == 'cancelled' for s in states):
                state = 'cancelled'
            elif 'partial' in states:
                state = 'partial'
            elif any(s in ('blocked', 'failed') for s in states):
                state = 'partial' if any(s in ('verified', 'scheduled') for s in states) else 'blocked'
            else:
                state = 'blocked' if error else 'verified'
            pending_finalize = db.execute("SELECT 1 FROM attempt_recovery r JOIN attempts a ON a.id=r.attempt_id WHERE a.operation_id=? AND r.finalize_state='pending'", (op['id'],)).fetchone()
            if pending_finalize:
                state = 'running'
                db.execute('UPDATE operations SET lease_until=? WHERE id=?', (self.store.clock()+30, op['id']))
            complete = state != 'running'
            db.execute('UPDATE operations SET state=?,complete=?,work_state=? WHERE id=?', (state, int(complete), 'done' if complete else 'working', op['id']))
            if state in ('verified', 'scheduled', 'cancelled'):
                db.execute('UPDATE operations SET error=NULL WHERE id=?', (op['id'],))
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
        entry_grant = None
        if args.get('_media_store_grant_id'):
            from .media_entry_grants import require_grant
            with self.store.connection() as db:
                entry_grant, _ = require_grant(
                    self.store, db, actor, args['_media_store_entry_ref'],
                    grant_id=args['_media_store_grant_id'], binding_id=b['id'])
                proof = json.loads(entry_grant['proof'])
                if (args.get('_native_item') != proof['native_id']
                        or args.get('_namespace') != proof['namespace']):
                    raise DomainError('access_denied', next_action='contact_owner')
        query = args['query']
        request = ReadRequest(b['connection_id'], b['native_id'], query['kind'], args.get('limit', 25), args.get('_provider_cursor'),
                              args.get('_native_item'), args.get('_namespace'), query.get('text', ''),
                              topic_root_id=args.get('_topic_root_id'))
        # Browser reads include account verification, native history and exact
        # media readback. Keep them bounded without applying the API-only 30s cap.
        budget = 120 if args.get('_media_store_get') else 90 if b['provider']=='max' and b['account_type']=='max_web' else 30
        budget = max(0.1, min(budget, op['deadline']-self.store.clock()))
        try:
            async with self.lane(b['connection_id']):
                if entry_grant:
                    with self.store.connection() as db:
                        require_grant(self.store, db, actor, args['_media_store_entry_ref'],
                                      grant_id=entry_grant['id'], binding_id=b['id'])
                async with asyncio.timeout(budget):
                    with diagnostic_scope(self.diagnostic_observer(op)):
                        with provider_call(b['provider'], 'read') as diagnostic:
                            page = await self.adapter(b['provider'], b['connection_id']).read(request, self.hooks(op))
                            diagnostic['items_count'] = len(page.items)
        except TimeoutError:
            raise DomainError('provider_read_deadline', 'Native read did not complete within the command deadline', 'refresh') from None
        if request.kind=='reactions' and (len(page.items)!=1 or not page.items[0].own_reactions_observed
                or page.items[0].native_id!=request.native_item or page.items[0].namespace!='published'):
            raise DomainError('reaction_read_unverified')
        with self.store.tx() as db:
            self.store.fence(db, op['id'], self.id, op['fence'])
            self.store.current(db, actor)
            self.store.binding(db, actor, binding_id=b['id'])
            if entry_grant:
                from .media_entry_grants import check_download
                current_grant, _ = require_grant(
                    self.store, db, actor, args['_media_store_entry_ref'],
                    grant_id=entry_grant['id'], binding_id=b['id'])
                check_download(json.loads(current_grant['proof']), page)
            downloads = {}
            if page.downloads:
                from social_operations.assets import insert_verified_image, verify_image
                remote_by_id = {remote.native_id: remote for remote in page.items}
                for media in page.downloads:
                    remote = remote_by_id.get(media.item_native_id)
                    if remote is None or media.slot >= len(remote.observed_media):
                        raise DomainError('download_media_binding_invalid')
                    evidence = remote.observed_media[media.slot]
                    if (media.provider_ref not in remote.provider_media
                            or evidence.slot != media.slot or evidence.sha256 != hashlib.sha256(media.data).hexdigest()
                            or evidence.mime != media.mime or evidence.size != len(media.data)):
                        raise DomainError('download_media_binding_invalid')
                    if media.mime in {'application/pdf','image/vnd.djvu'}:
                        if not args.get('_media_store_get'):
                            raise DomainError('document_download_private_store_only')
                        from types import SimpleNamespace
                        verified=SimpleNamespace(width=0,height=0)
                    else:
                        verified = verify_image(media.data, media.mime)
                    if args.get('_media_store_get'):
                        asset_ref = new_id('asset')
                        db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
                                   (asset_ref, actor.tenant_id, actor.principal_id, evidence.sha256,
                                    media.mime, verified.width, verified.height, media.data,
                                    evidence.sha256, self.store.clock()))
                        db.execute('INSERT INTO media_store_assets VALUES(?,?,?,?)',
                                   (asset_ref, args.get('_media_store_entry_ref'), 'download_cache', self.store.clock()+3600))
                        if entry_grant:
                            db.execute('INSERT INTO media_service_entry_assets VALUES(?,?)',
                                       (asset_ref, entry_grant['id']))
                    else:
                        sanitized_sha = hashlib.sha256(verified.data).hexdigest()
                        existing_asset = db.execute(
                            'SELECT id FROM assets WHERE tenant_id=? AND principal_id=? AND sha256=? AND source_sha256=? AND mime=\'image/png\' LIMIT 1',
                            (actor.tenant_id, actor.principal_id, sanitized_sha, evidence.sha256)).fetchone()
                        asset_ref = existing_asset['id'] if existing_asset else insert_verified_image(
                            self.store, db, actor, verified)
                    downloads.setdefault(media.item_native_id, []).append(
                        {'slot': media.slot, 'asset_ref': asset_ref, 'media_kind': media.media_kind})
            items = []
            for remote in page.items:
                if remote.native_target != b['native_id']:
                    raise DomainError('wrong_target_readback', next_action='contact_owner')
                self.save_fact(db, b['destination_id'], remote)
                item = self.app.project_item(db, actor, b, asdict(remote),
                                             media_assets=downloads.get(remote.native_id, ()))
                if request.kind == 'thread':
                    item['media'] = [{'role': 'document' if ref.startswith('document:') else 'image'}
                                     for ref in remote.provider_media]
                    item['media_evidence'] = []
                items.append(item)
            result = {'items': items, 'truncated': page.cursor is not None}
            if args.get('_media_store_entry_ref'):
                result['media_store_items']=self.app._media_store_items(db,actor,publication_id=args['_media_store_entry_ref'])
            if page.cursor:
                result['next_cursor'] = self.store.cursor(db, actor, 'read', digest(query), page.cursor)
            db.execute('UPDATE operations SET state=\'verified\',complete=1,work_state=\'done\',result=? WHERE id=?', (canonical(result), op['id']))
            self.store.event(db, op['id'], 'finished', 'completed', 'Current provider read complete; history was not used as a queue')
