"""Canonical ProviderAdapter bridge: fixture or explicitly wired real MAX.

Observation-only bindings grant no mutation; core-admitted durable resolutions
release only their exact attempt fuse through the post-commit finalize hook.
Import requires the actual core port and native
helpers; neither is vendored here. Core owns auth, dispatch, identity and ledger.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace

from adapters.native import bind_media, identity, load_checkpoint, plain_text, saved_checkpoint, schedule_guard, verify_assets
from adapters.port import Capability, Hooks, Observation, Prepared, ProviderRequest, ReadPage, ReadRequest, RemoteItem
from social_operations.domain import DomainError, OutcomeUnknown, canonical, digest

from .driver import FixtureDriver, fingerprint
from .live import RealMaxDriver
from .profile import MaxBlocked


@dataclass(frozen=True)
class RecoveryBinding:
    """Trusted original-attempt evidence reference; never a mutation capability."""
    attempt_id: str
    plan_digest: str
    native_reference: str = field(repr=False)
    task_marker: str = field(repr=False)


class MaxAdapter:
    """Explicit trusted dependency injection, not automatic/live MAX wiring."""

    def __init__(self, driver: FixtureDriver, *, connection_id: str, recovery: RecoveryBinding | None = None):
        self.is_real = isinstance(driver, RealMaxDriver)
        self.live_enabled = self.is_real and driver.live_writes
        self.recovery_only = self.is_real and not self.live_enabled
        if self.recovery_only:
            if not isinstance(recovery, RecoveryBinding) or not all((recovery.attempt_id, recovery.plan_digest, recovery.native_reference, recovery.task_marker)):
                raise DomainError('max_explicit_recovery_binding_required')
        elif not self.live_enabled and (not isinstance(driver, FixtureDriver) or recovery is not None):
            raise DomainError('max_fixture_driver_required')
        self.recovery = recovery
        self.driver, self.connection_id = driver, connection_id

    def _binding(self, request):
        if request.connection_id != self.connection_id or request.native_target not in self.driver.targets:
            raise DomainError('max_connection_or_target_denied')

    def _content(self, request):
        if self.live_enabled and request.action=='react' and request.existing:
            from social_operations.rich_text import max_entities
            return request.existing.text,max_entities(request.existing.text,json.loads(request.existing.entities_json))
        if self.live_enabled:
            from social_operations.rich_text import max_content
            return max_content(request.content_json,4000)
        return plain_text(request,limit=4000), []

    def _text(self, request):
        return self._content(request)[0]

    def _validate(self, request: ProviderRequest, *, check_time=True):
        self._binding(request)
        if self.recovery_only:
            if (request.account_type != 'max_web' or request.secret_ref != 'VIBEPUBLISH_MAX_PROFILE'
                    or request.attempt_id != self.recovery.attempt_id
                    or request.plan_digest != self.recovery.plan_digest):
                raise DomainError('max_recovery_binding_mismatch')
            if request.action != 'publish' or request.assets or request.scheduled_at is not None:
                raise DomainError('max_recovery_surface_unsupported')
        elif self.live_enabled:
            if request.account_type != 'max_web' or request.secret_ref != 'VIBEPUBLISH_MAX_PROFILE':
                raise DomainError('max_live_binding_mismatch')
        elif request.account_type != 'fake' or request.secret_ref:
            raise DomainError('max_live_factory_not_implemented')
        if request.action not in ({'publish', 'edit', 'reschedule', 'cancel', 'delete','react'} if self.live_enabled else {'publish', 'edit', 'reschedule', 'cancel', 'delete'}) or request.source:
            raise DomainError('max_action_unsupported')
        if request.surface not in {'post', 'album'}:
            raise DomainError('max_surface_unsupported')
        if request.action=='react' and (not request.subject or request.subject!=request.existing
                or request.reaction_mode not in {'add','remove'} or not request.reaction):
            raise DomainError('max_reaction_subject_required')
        text = self._text(request)
        if self.live_enabled:
            from .rich import QUALIFIED
            if any(e['type'] not in QUALIFIED for e in self._content(request)[1]):
                raise DomainError('max_rich_recipe_not_qualified')
        verify_assets(request, allow_video=self.live_enabled)
        if any(a.mime not in ({'image/png', 'image/jpeg', 'video/mp4'} if self.live_enabled else {'image/png', 'image/jpeg'}) for a in request.assets):
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
        if self.recovery_only:
            return Capability('needs_review', 'Observation-only recovery binding; no execute capability', evidence='max_web_read_only')
        try:
            self._validate(request)
            if self.live_enabled:
                await self.driver.mutation_preflight(request.native_target, request.action,
                    media=request.assets, scheduled_at=request.scheduled_at)
                await self.driver.open(request.native_target)
            else:
                await self.driver.read(request.native_target, 'scheduled' if request.scheduled_at else 'feed')
                await self.driver._scope(request.native_target, write=True)
        except (DomainError, MaxBlocked):
            return Capability('needs_review', 'MAX request/profile capability not verified', evidence='offline_fixture',
                              min_lead_seconds=self.driver.min_lead)
        return Capability('supported', 'Native UI receipt path' if self.live_enabled else 'Explicit loopback fixture only; NOT live MAX evidence',
                          min_lead_seconds=self.driver.min_lead, evidence='max_web_dom' if self.live_enabled else 'offline_fixture')

    async def prepare(self, request: ProviderRequest, hooks: Hooks) -> Prepared:
        if self.recovery_only:
            raise DomainError('max_recovery_only')
        self._validate(request)
        capability = await self.inspect(request)
        if capability.status != 'supported':
            raise DomainError('max_preflight_needs_review')
        await hooks.emit_progress('validating', 'completed', 'MAX preflight complete')
        return Prepared(request, capability, saved_checkpoint(request))

    @staticmethod
    def _existing(remote):
        if remote is None:
            return None
        from social_operations.rich_text import max_entities
        item = dict(id=remote.native_id, target=remote.native_target,
                    namespace='feed' if remote.namespace == 'published' else remote.namespace, url=remote.url,
                    text=remote.text, entities=max_entities(remote.text,json.loads(remote.entities_json)), media=list(remote.provider_media), observed_media=[asdict(x) for x in getattr(remote,'observed_media',())], scheduled_at=remote.scheduled_at)
        return dict(item, fingerprint=fingerprint(item))

    @staticmethod
    def _remote(item):
        remote = RemoteItem(native_id=item['id'], namespace='published' if item['namespace'] == 'feed' else item['namespace'],
                            native_target=item['target'], text=item['text'], fingerprint='', observed_at=item['observed_at'],
                            scheduled_at=item['scheduled_at'], provider_media=tuple(item['media']),
                            **({'own_reactions':tuple(item['own_reactions']),'own_reactions_observed':True} if item.get('own_reactions_observed') else {}),
                            url=item.get('url'), entities_json=json.dumps(item.get('entities',[])), member_ids=tuple(item.get('member_ids',(item['id'],))), **({'observed_media':tuple(item['observed_media'])} if item.get('observed_media') else {}), media_check='download_binding' if item.get('observed_media') else 'provider_identity_only' if item['media'] else 'not_applicable')
        return replace(remote, fingerprint=identity(remote))

    def _state(self, request, checkpoint):
        state = load_checkpoint(request, checkpoint).get('driver')
        from social_operations.rich_text import max_entities
        try:
            kind = ('feed' if request.existing.namespace == 'published' else request.existing.namespace) if request.existing else ('scheduled' if request.scheduled_at else 'feed')
            if (state['target'] != request.native_target or state['text'] != self._text(request)
                    or max_entities(state['text'],state.get('entities',[])) != self._content(request)[1]
                    or state['action'] != request.action or state['scheduled_at'] != request.scheduled_at
                    or state['kind'] != kind or state.get('media_slots',len(state['media'])) != (len(request.assets) if request.assets else (len(getattr(request.existing,'observed_media',())) or len(request.existing.provider_media)) if request.existing else 0)
                    or (request.action=='react' and (state.get('reaction')!=request.reaction or state.get('reaction_mode')!=request.reaction_mode))
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
        replacement = None
        if request.existing and item.native_id != request.existing.native_id:
            from adapters.port import NativeReplacement
            evidence = state.get('replacement_evidence')
            if request.action != 'reschedule' or evidence not in {'trusted_ui_native_queue_replacement', 'stable_native_correlation'}:
                raise OutcomeUnknown('max_native_replacement_unproven')
            replacement = NativeReplacement(request.existing.native_id, item.native_id,
                request.existing.fingerprint, evidence)
        # These SHA values describe the validated INPUT assets bound to observed
        # upload IDs, never hashes calculated from transcoded provider bytes.
        if getattr(item,'observed_media',()):
            from adapters.native import bind_download_media
            item=bind_download_media(request,item,binding=state['download_binding'],replacement=replacement)
        else:
            item = bind_media(request, item, state['media'])
        observed = 'reacted' if request.action=='react' else 'deleted' if request.action == 'delete' else 'cancelled' if request.action == 'cancel' else 'provider_scheduled' if item.namespace == 'scheduled' else 'edited' if request.action == 'edit' else 'published'
        return Observation(observed, (item,), replacement=replacement)

    @staticmethod
    def _download_binding(request,state):
        observed=state.get('observed_media',[])
        if not observed:return state
        source_hashes=[a.sha256 for a in request.assets]
        if request.action=='publish' and state.get('source_hashes')!=source_hashes:
            raise OutcomeUnknown('max_uploaded_source_digest_mismatch')
        binding=dict(operation_id=request.operation_id,attempt_id=request.attempt_id,
            plan_digest=request.plan_digest,native_target=request.native_target,
            native_id=state.get('native_id') or state.get('existing_id'),
            namespace='published' if state['kind']=='feed' else state['kind'],
            source_hashes=source_hashes,observed_media=observed)
        return dict(state,download_binding=binding)

    async def execute(self, prepared: Prepared, hooks: Hooks) -> Observation:
        if self.recovery_only:
            raise DomainError('max_recovery_only')
        request = prepared.request
        text = self._validate(request)
        load_checkpoint(request, prepared.state_json)
        if prepared.capability.status != 'supported' or prepared.capability.evidence != ('max_web_dom' if self.live_enabled else 'offline_fixture'):
            raise DomainError('max_prepared_capability_invalid')
        state = None

        async def checkpoint(transition, raw):
            nonlocal state
            if self.live_enabled or transition == 'MAX_PREPARED':
                state = json.loads(raw)
            if state is None:
                raise DomainError('max_missing_prepare_checkpoint')
            if self.live_enabled:state=self._download_binding(request,state)
            envelope = saved_checkpoint(request, driver=state)
            self._state(request, envelope)
            # Preserve the reconcile baseline even after observation and before
            # core.finish_child commits. Never overwrite it with composer/toast.
            await hooks.checkpoint(transition, envelope)

        async def progress(stage, status, _evidence):
            # Driver-local "running" is not a valid durable core event status.
            # Translate vocabulary, not event persistence or authorization.
            await hooks.emit_progress(stage, 'started' if status == 'running' else status,
                                      'MAX stage: ' + stage)

        try:
            items = await self.driver.mutate(target=request.native_target, text=text,
                media=tuple({'name': f'{i}.mp4' if a.mime == 'video/mp4' else f'{i}.png' if a.mime == 'image/png' else f'{i}.jpg',
                             'mimeType': a.mime, 'buffer': a.data} for i, a in enumerate(request.assets)),
                scheduled_at=request.scheduled_at, action=request.action,
                attempt_id=request.attempt_id, plan_digest=request.plan_digest,
                existing=self._existing(request.existing),
                **({'entities':self._content(request)[1]} if self.live_enabled else {}),
                **({'reaction':request.reaction,'reaction_mode':request.reaction_mode} if request.action=='react' else {}),
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
        if self.live_enabled:
            envelope = json.loads(checkpoint)
            admitted = envelope.get('core_recovery', {})
            if state['kind']=='scheduled':
                if any(admitted.get(k)!=v for k,v in {
                    'operation_id':request.operation_id,'attempt_id':request.attempt_id,
                    'plan_digest':request.plan_digest}.items()):
                    raise OutcomeUnknown('max_core_recovery_binding_mismatch')
                from .queue import legacy_unreachable_guard
                evidence=await legacy_unreachable_guard(self.driver,state)
                if evidence is not None:
                    from adapters.port import NoEffectProof
                    original={k:v for k,v in envelope.items() if k!='core_recovery'}
                    return Observation('not_attempted',no_effect=NoEffectProof(
                        digest(original),'trusted_preinput_guard',canonical(evidence)))
                try:result=await self.driver.reconcile(state)
                except MaxBlocked as exc:raise OutcomeUnknown('max_'+str(exc)) from None
                state=self._download_binding(request,result['state'])
                self._state(request,saved_checkpoint(request,driver=state))
                await hooks.checkpoint('MAX_RECONCILED',saved_checkpoint(request,driver=state))
                return self._observation(request,[result['item']],state)
            reference = state.get('recovery_reference') or admitted.get('native_reference')
            if not reference:
                raise OutcomeUnknown('max_native_reference_required')
            try:
                result = await self.driver.reconcile(dict(state, recovery_reference=reference,
                    attempt_id=request.attempt_id, plan_digest=request.plan_digest))
            except MaxBlocked as exc:
                raise OutcomeUnknown('max_'+str(exc)) from None
            if state['media'] and any(x is None for x in state['media']):
                # The original uploaded input intent is immutable. A core-admitted
                # exact native observation may bind previously missing provider IDs;
                # it never uploads/sends again or rewrites the historical checkpoint.
                names=[f'{i}.mp4' if asset.mime=='video/mp4' else f'{i}.png' if asset.mime=='image/png' else f'{i}.jpg' for i,asset in enumerate(request.assets)]
                if (request.action!='publish' or any(x is not None for x in state['media'])
                        or [p.get('name') for p in state.get('upload_previews',[])]!=names
                        or not names or any(admitted.get(k)!=v for k,v in {
                            'operation_id':request.operation_id,'attempt_id':request.attempt_id,
                            'plan_digest':request.plan_digest}.items())):
                    raise OutcomeUnknown('max_original_upload_binding_required')
                state=dict(state,media=result['item']['media'],observed_media=result['item'].get('observed_media',[]),native_id=result['item']['id'],media_slots=len(request.assets),source_hashes=[a.sha256 for a in request.assets],recovery_reference=reference)
                state=self._download_binding(request,state)
                await hooks.checkpoint('MAX_RECOVERY_MEDIA_BOUND',saved_checkpoint(request,driver=state))
            return self._observation(request, [result['item']], state)
        if self.recovery_only:
            try:
                result = await self.driver.reconcile(dict(state,
                    recovery_reference=self.recovery.native_reference,
                    task_marker=self.recovery.task_marker,
                    attempt_id=request.attempt_id, plan_digest=request.plan_digest))
            except MaxBlocked:
                raise OutcomeUnknown('max_recovery_observation_unavailable') from None
            envelope = json.loads(checkpoint)
            admitted = envelope.get('core_recovery')
            if admitted is not None:
                self._recovery_admission(request, admitted)
                # The original pre-dispatch marked intent, exact trusted reference,
                # outgoing full content and repeated native reads are now bound to
                # this core-admitted recovery, not a matching newest feed row.
                return Observation('published', (self._remote(result['item']),))
            # Positive EXISTENCE evidence, not a fabricated resolution. Core
            # must validate historical attribution and commit before release.
            # Do not call checkpoint/before_effect or touch the fuse here.
            return Observation('outcome_unknown', (self._remote(result['item']),),
                missing_checks=('core_historical_attribution_resolution', 'history_completeness'))
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

    def _recovery_admission(self, request, admitted):
        if not isinstance(admitted, dict) or any(admitted.get(k) != v for k, v in {
                'operation_id': request.operation_id, 'attempt_id': request.attempt_id,
                'plan_digest': request.plan_digest,
                'native_reference': self.recovery.native_reference}.items()):
            raise OutcomeUnknown('max_core_recovery_binding_mismatch')
        text = self._text(request)
        marker = self.recovery.task_marker
        if len(marker) != 32 or any(c not in '0123456789abcdef' for c in marker) or text.count(marker) != 1:
            raise OutcomeUnknown('max_original_marked_intent_required')

    async def finalize(self, request: ProviderRequest, checkpoint: str, hooks: Hooks):
        """Core-only post-commit cleanup, idempotent and never a social effect."""
        if not self.is_real:
            return
        self._validate(request, check_time=False)
        envelope = json.loads(checkpoint)
        if envelope.get('no_effect') is not None:
            proof=envelope['no_effect'];original=envelope.get('original_checkpoint')
            state=self._state(request,canonical(original))
            admitted=envelope.get('core_recovery',{})
            if (proof.get('reason')!='trusted_preinput_guard' or proof.get('checkpoint_sha256')!=digest(original)
                    or any(admitted.get(k)!=v for k,v in {'operation_id':request.operation_id,
                        'attempt_id':request.attempt_id,'plan_digest':request.plan_digest}.items())):
                raise OutcomeUnknown('max_no_effect_finalize_binding')
            self.driver._enter(request.native_target)
            try:
                import os
                if os.path.lexists(self.driver.lane.marker):
                    self.driver._check_attempt_fuse(request.attempt_id,request.plan_digest)
                    self.driver.lane.resolve_observed()
            finally:self.driver._busy=False
            return
        remote = envelope.get('remote', {})
        admitted = envelope.get('core_recovery', {})
        if self.recovery_only:
            self._recovery_admission(request, admitted)
            expected_reference = self.recovery.native_reference
        else:
            if any(admitted.get(k) != v for k,v in {
                    'operation_id':request.operation_id,'attempt_id':request.attempt_id,
                    'plan_digest':request.plan_digest}.items()):
                raise OutcomeUnknown('max_finalize_binding_mismatch')
            original = envelope.get('original_checkpoint')
            if isinstance(original, str): original = json.loads(original)
            original_state = self._state(request, json.dumps(original))
            expected_reference = original_state.get('recovery_reference') or admitted.get('native_reference')
            if original_state.get('observed_media') and remote.get('observed_media',[]) != original_state['observed_media']:
                raise OutcomeUnknown('max_terminal_download_mismatch')
            if all(x is not None for x in original_state['media']) and remote.get('provider_media',[]) != original_state['media']:
                raise OutcomeUnknown('max_terminal_media_mismatch')
        if not self.recovery_only and original_state['kind']=='scheduled':
            native=original_state.get('native_id')
            committed=envelope.get('committed_observation',{})
            recovered_exact=(committed.get('items')==[remote] and committed.get('observed')=='provider_scheduled')
            replacement=committed.get('replacement') or {}
            replaced=(recovered_exact and request.action=='reschedule' and request.existing is not None
                and replacement.get('previous_native_id')==request.existing.native_id
                and replacement.get('native_id')==remote.get('native_id')
                and replacement.get('previous_fingerprint')==request.existing.fingerprint
                and replacement.get('evidence') in {'trusted_ui_native_queue_replacement','stable_native_correlation'})
            exact=(((remote.get('native_id')==native or replaced) if native is not None else recovered_exact)
                and remote.get('namespace')=='scheduled' and remote.get('scheduled_at')==(request.existing.scheduled_at if request.action=='cancel' else request.scheduled_at)
                and remote.get('url') is None)
        else:
            exact=(bool(expected_reference) and remote.get('url')==expected_reference and remote.get('namespace')=='published')
        if (not exact or remote.get('native_target')!=request.native_target or remote.get('text')!=self._text(request)):
            raise OutcomeUnknown('max_terminal_receipt_mismatch')
        self.driver._enter(request.native_target)
        try:
            # The worker's durable finalize outbox is authority. An absent marker
            # means a previous cleanup completed before its acknowledgement.
            import os
            if os.path.lexists(self.driver.lane.marker):
                self.driver._check_attempt_fuse(request.attempt_id, request.plan_digest)
                self.driver.lane.resolve_observed()
        finally:
            self.driver._busy = False

    async def read(self, request: ReadRequest, hooks: Hooks) -> ReadPage:
        if self.recovery_only:
            raise DomainError('max_use_bound_reconcile')
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
        await hooks.emit_progress('reading_back', 'started', 'Reading the bound MAX native target' if self.live_enabled else 'Reading the bound MAX fixture channel')
        try:
            rows = await self.driver.read(request.native_target, kind, **({'native_item':request.native_item} if self.live_enabled else {}))
        except MaxBlocked as exc:
            raise DomainError('max_'+str(exc)) from None
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
