"""Canonical ProviderAdapter bridge for the EXISTING loopback FixtureDriver.

No production factory/locators. Import requires the actual core port and native
helpers; neither is vendored here. Core owns auth, dispatch, identity and ledger.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace

from adapters.native import bind_media, identity, load_checkpoint, plain_text, saved_checkpoint, schedule_guard, verify_assets
from adapters.port import Capability, Hooks, Observation, Prepared, ProviderRequest, ReadPage, ReadRequest, RemoteItem
from social_operations.domain import DomainError, OutcomeUnknown, canonical, digest

from .driver import FixtureDriver, fingerprint
from .profile import MaxBlocked


class MaxAdapter:
    """Explicit trusted dependency injection, not automatic/live MAX wiring."""

    def __init__(self, driver: FixtureDriver, *, connection_id: str):
        if not isinstance(driver, FixtureDriver):
            raise DomainError('max_fixture_driver_required')
        self.driver, self.connection_id = driver, connection_id

    def _binding(self, request):
        if request.connection_id != self.connection_id or request.native_target not in self.driver.targets:
            raise DomainError('max_connection_or_target_denied')

    def _validate(self, request: ProviderRequest, *, check_time=True):
        self._binding(request)
        if request.account_type != 'fake' or request.secret_ref:
            raise DomainError('max_live_factory_not_implemented')
        if request.action not in {'publish', 'edit', 'reschedule', 'cancel', 'delete'} or request.source:
            raise DomainError('max_action_unsupported')
        if request.surface not in {'post', 'album'}:
            raise DomainError('max_surface_unsupported')
        text = plain_text(request, limit=4000)
        verify_assets(request)
        if any(a.mime not in {'image/png', 'image/jpeg'} for a in request.assets):
            raise DomainError('max_media_unsupported')
        if check_time:
            schedule_guard(request, time.time(), lead=self.driver.min_lead)
        if request.action != 'publish':
            if not request.existing or request.existing.native_target != request.native_target:
                raise DomainError('max_exact_existing_required')
        elif request.existing:
            raise DomainError('max_publish_existing_conflict')
        return text

    async def inspect(self, request: ProviderRequest) -> Capability:
        try:
            self._validate(request)
            await self.driver.read(request.native_target, 'scheduled' if request.scheduled_at else 'feed')
            await self.driver._scope(request.native_target, write=True)
        except (DomainError, MaxBlocked):
            return Capability('needs_review', 'MAX request/profile capability not verified', evidence='offline_fixture',
                              min_lead_seconds=self.driver.min_lead)
        return Capability('supported', 'Explicit loopback fixture only; NOT live MAX evidence',
                          min_lead_seconds=self.driver.min_lead, evidence='offline_fixture')

    async def prepare(self, request: ProviderRequest, hooks: Hooks) -> Prepared:
        self._validate(request)
        capability = await self.inspect(request)
        if capability.status != 'supported':
            raise DomainError('max_preflight_needs_review')
        await hooks.emit_progress('validating', 'completed', 'MAX offline preflight complete')
        return Prepared(request, capability, saved_checkpoint(request))

    @staticmethod
    def _existing(remote):
        if remote is None:
            return None
        item = dict(id=remote.native_id, target=remote.native_target,
                    namespace='feed' if remote.namespace == 'published' else remote.namespace,
                    text=remote.text, media=list(remote.provider_media), scheduled_at=remote.scheduled_at)
        return dict(item, fingerprint=fingerprint(item))

    @staticmethod
    def _remote(item):
        remote = RemoteItem(native_id=item['id'], namespace='published' if item['namespace'] == 'feed' else item['namespace'],
                            native_target=item['target'], text=item['text'], fingerprint='', observed_at=item['observed_at'],
                            scheduled_at=item['scheduled_at'], provider_media=tuple(item['media']),
                            member_ids=(item['id'],), media_check='provider_identity_only' if item['media'] else 'not_applicable')
        return replace(remote, fingerprint=identity(remote))

    def _state(self, request, checkpoint):
        state = load_checkpoint(request, checkpoint).get('driver')
        try:
            kind = ('feed' if request.existing.namespace == 'published' else request.existing.namespace) if request.existing else ('scheduled' if request.scheduled_at else 'feed')
            if (state['target'] != request.native_target or state['text'] != plain_text(request, limit=4000)
                    or state['action'] != request.action or state['scheduled_at'] != request.scheduled_at
                    or state['kind'] != kind or len(state['media']) != len(request.assets)
                    or state['existing_id'] != (request.existing.native_id if request.existing else None)):
                raise ValueError()
        except (TypeError, KeyError, ValueError):
            raise OutcomeUnknown('max_checkpoint_intent_mismatch') from None
        return state

    def _observation(self, request, items, state):
        if len(items) != 1:
            raise OutcomeUnknown('max_ambiguous_readback')
        item = self._remote(items[0])
        if item.native_target != request.native_target:
            raise OutcomeUnknown('max_wrong_target_readback')
        # These SHA values describe the validated INPUT assets bound to observed
        # upload IDs, never hashes calculated from transcoded provider bytes.
        item = bind_media(request, item, state['media'])
        observed = 'provider_scheduled' if item.namespace == 'scheduled' else 'edited' if request.action == 'edit' else 'published'
        return Observation(observed, (item,))

    async def execute(self, prepared: Prepared, hooks: Hooks) -> Observation:
        request = prepared.request
        text = self._validate(request)
        load_checkpoint(request, prepared.state_json)
        if prepared.capability.status != 'supported' or prepared.capability.evidence != 'offline_fixture':
            raise DomainError('max_prepared_capability_invalid')
        state = None

        async def checkpoint(transition, raw):
            nonlocal state
            if transition == 'MAX_PREPARED':
                state = json.loads(raw)
            if state is None:
                raise DomainError('max_missing_prepare_checkpoint')
            envelope = saved_checkpoint(request, driver=state)
            self._state(request, envelope)
            # Preserve the reconcile baseline even after observation and before
            # core.finish_child commits. Never overwrite it with composer/toast.
            await hooks.checkpoint(transition, envelope)

        async def progress(stage, status, _evidence):
            # Driver-local "running" is not a valid durable core event status.
            # Translate vocabulary, not event persistence or authorization.
            await hooks.emit_progress(stage, 'started' if status == 'running' else status,
                                      'MAX fixture stage: ' + stage)

        try:
            items = await self.driver.mutate(target=request.native_target, text=text,
                media=tuple({'name': f'{i}.png' if a.mime == 'image/png' else f'{i}.jpg',
                             'mimeType': a.mime, 'buffer': a.data} for i, a in enumerate(request.assets)),
                scheduled_at=request.scheduled_at, action=request.action,
                attempt_id=request.attempt_id, plan_digest=request.plan_digest,
                existing=self._existing(request.existing),
                hooks=Hooks(progress, checkpoint, hooks.before_effect))
            return self._observation(request, items, state)
        except MaxBlocked as exc:
            # Only the trusted worker decides dispatched vs not_attempted state.
            if str(exc) == 'outcome_unknown':
                raise OutcomeUnknown('max_outcome_unknown') from None
            raise DomainError('max_' + str(exc)) from None

    async def reconcile(self, request: ProviderRequest, checkpoint: str, hooks: Hooks) -> Observation:
        self._validate(request, check_time=False)
        state = self._state(request, checkpoint)
        await hooks.emit_progress('reading_back', 'started', 'MAX observation only; no submit')
        try:
            items = await self.driver.reconcile(state)
        except MaxBlocked:
            raise OutcomeUnknown('max_outcome_unknown') from None
        result = self._observation(request, items, state)
        await hooks.checkpoint('MAX_RECONCILED', saved_checkpoint(request, driver=state))
        if self.driver.lane.marker.exists():
            marker = json.loads(self.driver.lane.marker.read_text())
            if marker != {'attempt_id': request.attempt_id, 'plan_digest': request.plan_digest}:
                raise OutcomeUnknown('max_profile_other_uncertain_attempt')
            self.driver.lane.resolve_observed()
        return result

    async def read(self, request: ReadRequest, hooks: Hooks) -> ReadPage:
        self._binding(request)
        if not 1 <= request.limit <= 100:
            raise DomainError('max_read_limit')
        kind = request.kind
        if kind == 'item':
            if not request.native_item or request.namespace not in {'published', 'scheduled'}:
                raise DomainError('max_exact_item_required')
            kind = 'feed' if request.namespace == 'published' else 'scheduled'
        if kind not in {'feed', 'scheduled'}:
            raise DomainError('max_read_unsupported')
        binding = digest([request.connection_id, request.native_target, request.kind,
                          request.native_item, request.namespace, request.text])
        cursor = None
        if request.cursor:
            try:
                cursor = json.loads(request.cursor)
                if cursor['binding'] != binding or type(cursor['offset']) is not int or cursor['offset'] < 0:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise DomainError('max_cursor_scope') from None
        await hooks.emit_progress('reading_back', 'started', 'Reading the bound MAX fixture channel')
        try:
            rows = await self.driver.read(request.native_target, kind)
        except MaxBlocked:
            raise DomainError('max_read_unavailable') from None
        items = [self._remote(row) for row in rows]
        if request.kind == 'item':
            items = [x for x in items if x.native_id == request.native_item]
        if request.text:
            items = [x for x in items if request.text.casefold() in x.text.casefold()]
        snapshot = digest([x.fingerprint for x in items])
        if cursor and cursor.get('snapshot') != snapshot:
            raise DomainError('max_cursor_changed', next_action='refresh')
        start = cursor['offset'] if cursor else 0
        end = start + request.limit
        next_cursor = canonical(dict(binding=binding, snapshot=snapshot, offset=end)) if end < len(items) else None
        return ReadPage(tuple(items[start:end]), next_cursor)
