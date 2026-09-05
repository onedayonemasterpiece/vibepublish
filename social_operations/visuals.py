"""Single durable VisualService for standalone and inline publication work.

The core owns admission, cost reservation, dispatch markers, private assets,
selection CAS and parent resumption. Executors receive only image-work snapshots.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import secrets
from dataclasses import asdict

from adapters.imagegen import ImagegenRequest, ImagegenSource, UnavailableImagegen
from .assets import insert_verified_image, verify_image
from .compositor import PRESET, FORMATS, render
from .domain import DomainError, OutcomeUnknown, canonical, digest, new_id, parse_time
from .visual_artifacts import verified_artifact

REQUESTED_ROUTE = 'gpt-5.6-luna'


class VisualService:
    def __init__(self, app):
        self.app, self.store = app, app.store

    @staticmethod
    def normalize_spec(spec):
        spec = json.loads(canonical(spec))
        if 'prompt' in spec:
            if 'brief' in spec and spec['brief'] != spec['prompt']:
                raise DomainError('visual_prompt_conflict', 'prompt and legacy brief must match when both are supplied')
            spec['brief'] = spec.pop('prompt')
        return spec

    def _native_queue_automatic(self, plans):
        # This is authority for choosing an image, not a provider capability claim.
        # Actual native-queue support is still checked before the provider effect.
        return bool(plans) and all(
            p['action'] == 'publish' and p['mode'] == 'execute'
            and p['account_type'] != 'fake' and not p.get('admission_error')
            and p['scheduled_at'] and parse_time(p['scheduled_at']) >= self.store.clock()+60
            for p in plans)

    def _automatic_context(self, plans, fixture):
        if self._native_queue_automatic(plans):
            return True
        # Keep harmless fixture standalone/preview and scheduled-test semantics,
        # but an automatic choice may never become an immediate execute send.
        return fixture and all(p['mode'] == 'preview' or p['scheduled_at'] for p in plans)

    def _spec(self, spec, plans):
        spec = self.normalize_spec(spec)
        spec.setdefault('preset', PRESET)
        spec.setdefault('candidates', 2)
        spec.setdefault('selection', 'automatic' if self._native_queue_automatic(plans) else 'human')
        spec.setdefault('copy', {})
        surface = plans[0]['surface'] if plans else 'post'
        spec.setdefault('formats', ['story_9_16' if surface == 'story' else 'post_4_5'])
        if spec['preset'] != PRESET:
            raise DomainError('visual_preset_not_available')
        if not 1 <= spec['candidates'] <= 4 or len(spec['formats']) > spec['candidates']:
            raise DomainError('visual_budget_too_small_for_formats')
        if plans:
            required = 'story_9_16' if surface == 'story' else 'post_4_5'
            if required not in spec['formats']:
                raise DomainError('visual_surface_format_mismatch')
            maximum = 1 if surface == 'story' else 10
            if any(len(p['assets'])+1 > maximum for p in plans):
                raise DomainError('visual_media_limit', 'The selected visual is first; explicit media would exceed the surface limit')
        return spec

    def create(self, db, actor, spec, op, plans=(), *, publication=None, revision=None):
        if 'visual' not in actor.scopes:
            raise DomainError('visual_scope_required', next_action='contact_owner')
        spec = self._spec(spec, plans)
        descriptors = ([spec['source']] if spec['kind'] == 'tune' else spec.get('sources', []))
        sources = []
        for descriptor in self.app._media(db, actor, descriptors):
            row = db.execute('SELECT * FROM assets WHERE id=?', (descriptor['ref'],)).fetchone()
            if hashlib.sha256(row['bytes']).hexdigest() != descriptor['sha256']:
                raise DomainError('asset_integrity')
            sources.append({**descriptor, 'width': row['width'], 'height': row['height']})
        job = new_id('visual')
        frozen_plans = list(plans)
        identity = digest([actor.tenant_id, actor.principal_id, actor.epoch, actor.routing_revision,
                           publication, revision, spec, sources, frozen_plans, REQUESTED_ROUTE])
        deadline = db.execute('SELECT deadline FROM operations WHERE id=?', (op,)).fetchone()[0]
        db.execute('INSERT INTO visual_jobs(id,tenant_id,principal_id,actor_epoch,routing_revision,operation_id,parent_publication,parent_revision,spec,sources,plans,input_digest,created,deadline) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (job, actor.tenant_id, actor.principal_id, actor.epoch, actor.routing_revision, op, publication, revision,
                    canonical(spec), canonical(sources), canonical(frozen_plans), identity, self.store.clock(), deadline))
        result = {'visual_job_id': job, 'visual_revision': 1}
        if not publication:
            result['resource_id'] = job
        db.execute('UPDATE operations SET result=? WHERE id=?', (canonical(result), op))
        return job

    def job(self, db, actor, ident):
        self.store.current(db, actor)
        row = db.execute('SELECT * FROM visual_jobs WHERE id=? AND tenant_id=? AND principal_id=?',
                         (ident, actor.tenant_id, actor.principal_id)).fetchone()
        if not row:
            raise DomainError('visual_not_available', next_action='refresh')
        if row['actor_epoch'] != actor.epoch:
            raise DomainError('access_revoked', next_action='reauthorize')
        for plan in json.loads(row['plans']):
            binding = self.store.binding(db, actor, binding_id=plan['binding_id'])
            if binding['epoch'] != plan['binding_epoch']:
                raise DomainError('access_revoked', next_action='reauthorize')
        return row

    def _parent_authority(self, db, actor, job, *, generation=False):
        if not job['parent_publication']:
            return
        actor = self.store.current(db, actor)
        if 'publish' not in actor.scopes or 'visual' not in actor.scopes:
            raise DomainError('access_revoked', next_action='reauthorize')
        if actor.routing_revision != job['routing_revision']:
            raise DomainError('routing_stale', 'Routing changed while the visual awaited selection; targets were not re-expanded', 'refresh')
        pub = db.execute('SELECT revision FROM publications WHERE id=?', (job['parent_publication'],)).fetchone()
        if not pub or pub[0] != job['parent_revision']:
            raise DomainError('visual_parent_revision_conflict', next_action='refresh')
        for plan in json.loads(job['plans']):
            binding = self.store.binding(db, actor, binding_id=plan['binding_id'])
            if binding['epoch'] != plan['binding_epoch'] or 'publish' not in json.loads(binding['rights']):
                raise DomainError('access_revoked', next_action='reauthorize')
            if plan['scheduled_at'] and parse_time(plan['scheduled_at']) < self.store.clock()+60:
                raise DomainError('native_lead_time', 'The native schedule expired while waiting; never send now')
        if generation and self.store.clock() > job['deadline']:
            raise DomainError('command_expired')

    def command(self, actor, args):
        intent = json.loads(canonical(args))
        intent.pop('request_key', None)
        command = intent['command']
        if command['kind'] in {'generate', 'tune', 'compose'}:
            command = intent['command'] = self.normalize_spec(command)
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            op = self.app._replay(db, actor, 'visual', intent, args, implicit=not bool(args.get('request_key')))
            if not op:
                if command['kind'] in {'generate', 'tune', 'compose'}:
                    op = self.app._new_operation(db, actor, 'visual', intent)
                    self.create(db, actor, command, op)
                elif command['kind'] == 'select':
                    op = self.select(db, actor, command)
                else:
                    job = self.job(db, actor, command['job_id'])
                    candidate = db.execute('SELECT id FROM visual_candidates WHERE id=? AND job_id=?', (command['candidate_id'], job['id'])).fetchone()
                    if not candidate:
                        raise DomainError('visual_candidate_not_available')
                    db.execute('INSERT INTO visual_feedback VALUES(?,?,?,?,?,?,0)',
                               (new_id('feedback'), job['id'], candidate['id'], command['rating'], command.get('reason',''), self.store.clock()))
                    op = self.app._new_operation(db, actor, 'visual', intent, complete=True,
                            result={'resource_id': job['id'], 'visual_job_id': job['id'], 'visual_revision': job['revision']})
                if args.get('request_key'):
                    self.app._key(db, actor, args['request_key'], digest(['visual', intent]), op)
        return self.store.receipt(actor, op)

    def select(self, db, actor, command, *, automatic=False):
        job = self.job(db, actor, command['job_id'])
        selection_digest = digest(command)
        if job['selected_candidate']:
            if job['selection_digest'] != selection_digest:
                raise DomainError('visual_selection_conflict', 'Another immutable choice already resumed this job', 'refresh')
            return job['operation_id']
        if job['state'] != 'needs_selection' or job['revision'] != command['expected_revision']:
            raise DomainError('visual_revision_conflict', next_action='refresh')
        candidate = db.execute('SELECT * FROM visual_candidates WHERE id=? AND job_id=?',
                               (command['candidate_id'], job['id'])).fetchone()
        if not candidate or not secrets.compare_digest(candidate['selection_token_hash'], self.store.token_hash(command['token'])):
            raise DomainError('visual_selection_token_invalid', next_action='refresh')
        self._parent_authority(db, actor, job)
        plans = json.loads(job['plans'])
        if automatic and not self._automatic_context(plans, bool(candidate['fixture'])):
            raise DomainError('visual_human_review_required', next_action='select_visual')
        if automatic and candidate['requires_review'] and not self._native_queue_automatic(plans):
            raise DomainError('visual_human_review_required', next_action='select_visual')
        asset = db.execute('SELECT * FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                           (candidate['asset_ref'], actor.tenant_id, actor.principal_id)).fetchone()
        if not asset or hashlib.sha256(asset['bytes']).hexdigest() != candidate['sha256']:
            raise DomainError('asset_integrity')
        if plans:
            required = 'story_9_16' if plans[0]['surface'] == 'story' else 'post_4_5'
            if candidate['format'] != required:
                raise DomainError('visual_surface_format_mismatch')
            if candidate['fixture'] and any(p['account_type'] != 'fake' for p in plans):
                raise DomainError('fixture_asset_native_publish_forbidden', 'Fixture images cannot be dispatched to a native connection', 'contact_owner')
            selected = self.app._media(db, actor, [{'source': {'kind': 'asset', 'id': asset['id']}}])[0]
            for plan in plans:
                plan['assets'].insert(0, selected)
            revision = job['parent_revision']+1
            changed = db.execute('UPDATE publications SET revision=? WHERE id=? AND revision=?',
                                 (revision, job['parent_publication'], job['parent_revision'])).rowcount
            if changed != 1:
                raise DomainError('visual_parent_revision_conflict', next_action='refresh')
            parent = db.execute('SELECT * FROM operations WHERE id=?', (job['operation_id'],)).fetchone()
            db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?)',
                       (actor.tenant_id, actor.principal_id, job['parent_publication'], revision, parent['request'], canonical(plans), digest(plans)))
            for plan in plans:
                db.execute('INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,plan,plan_digest) VALUES(?,?,?,?,?,?,?,?)',
                           (new_id('attempt'), job['operation_id'], plan['binding_id'], plan['binding_epoch'], plan['alias'], plan['provider'], canonical(plan), digest(plan)))
            # Resume the SAME original operation exactly once, not a hidden publish call.
            db.execute("UPDATE operations SET revision=?,state='accepted',complete=0,work_state='ready',lease_owner=NULL,lease_until=0,deadline=?,error=NULL WHERE id=?",
                       (revision, self.store.clock()+120, job['operation_id']))
        else:
            db.execute("UPDATE operations SET state='verified',complete=1,work_state='done',error=NULL WHERE id=?", (job['operation_id'],))
        db.execute("UPDATE visual_jobs SET state='selected',revision=revision+1,selected_candidate=?,selection_digest=? WHERE id=?",
                   (candidate['id'], selection_digest, job['id']))
        result = json.loads(db.execute('SELECT result FROM operations WHERE id=?', (job['operation_id'],)).fetchone()[0])
        for item in result.get('candidates', []):
            item.pop('selection_token', None)
        result.update(visual_revision=job['revision']+1, selected_asset_ref=asset['id'], selected_sha256=candidate['sha256'])
        db.execute('UPDATE operations SET result=? WHERE id=?', (canonical(result), job['operation_id']))
        self.store.event(db, job['operation_id'], 'awaiting_selection', 'completed',
                         'Immutable candidate selected; original publication resumed once' if plans else 'Standalone visual selected; no publication was created')
        return job['operation_id']

    def _request(self, job, actor):
        sources = []
        with self.store.connection() as db:
            self.job(db, actor, job['id'])
            for source in json.loads(job['sources']):
                row = db.execute('SELECT bytes FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                                 (source['ref'], actor.tenant_id, actor.principal_id)).fetchone()
                if not row or hashlib.sha256(row['bytes']).hexdigest() != source['sha256']:
                    raise DomainError('asset_integrity')
                sources.append(ImagegenSource(source['ref'], source['sha256'], source['mime'], source['width'], source['height'], source['size'], row['bytes']))
        spec = json.loads(job['spec'])
        budget = (spec['candidates']+len(spec['formats'])-1)//len(spec['formats'])
        brief = spec['brief']
        if spec['copy']:
            brief = ('Create only the art layer, without lettering or editorial text. '
                     'Explicit structured copy is composed separately; do not bake it into the image.\n'
                     + brief)
        return ImagegenRequest(job['id'], job['input_digest'], spec['kind'], brief, tuple(sources),
                               spec['preset'], REQUESTED_ROUTE, budget, job['deadline'])

    async def process(self, worker, op, actor, executor=None):
        executor = executor or UnavailableImagegen()
        with self.store.connection() as db:
            found = db.execute('SELECT * FROM visual_jobs WHERE operation_id=?', (op['id'],)).fetchone()
            if not found or found['selected_candidate']:
                return False
            job = dict(found)
        try:
            request = self._request(job, actor)
            if not job['dispatched']:
                if isinstance(executor, UnavailableImagegen):
                    raise DomainError('imagegen_not_configured', 'No real $imagegen executor is configured; no substitution', 'contact_owner')
                with self.store.tx() as db:
                    current = self.store.fence(db, op['id'], worker.id, op['fence'])
                    actor = self.store.operation_actor(current)
                    row = self.job(db, actor, job['id'])
                    self._parent_authority(db, actor, row, generation=True)
                    if self.store.clock() > job['deadline']:
                        raise DomainError('command_expired')
                    if db.execute("SELECT value FROM settings WHERE key='restore_guard'").fetchone()[0] == '1':
                        raise DomainError('restore_requires_reconciliation', next_action='contact_owner')
                    changed = db.execute("UPDATE visual_jobs SET dispatched=1,state='running' WHERE id=? AND dispatched=0", (job['id'],)).rowcount
                    if changed != 1:
                        raise OutcomeUnknown('imagegen_already_dispatched')
                    self.store.event(db, op['id'], 'submitting', 'started', 'Core image-work dispatch marker committed before executor submit')
                try:
                    async with asyncio.timeout(max(.1, job['deadline']-self.store.clock())):
                        execution_ref = await executor.submit(request)
                    with self.store.tx() as db:
                        self.store.fence(db, op['id'], worker.id, op['fence'])
                        db.execute('UPDATE visual_jobs SET execution_ref=? WHERE id=?', (execution_ref, job['id']))
                except asyncio.CancelledError:
                    raise
                except DomainError as exc:
                    if exc.code == 'stale_worker':
                        raise
                    execution_ref = None
                except Exception:
                    execution_ref = None
            else:
                execution_ref = job['execution_ref']
            # Durable key lookup is a READ. Never submit again after a lost response.
            async def inspect(ref=None):
                async with asyncio.timeout(15):
                    return await executor.inspect(ref) if ref else await executor.find(job['id'])
            read_deadline = asyncio.get_running_loop().time()+max(.1, min(120, job['deadline']-self.store.clock()))
            observation = await inspect(execution_ref)
            if observation is None:
                raise OutcomeUnknown('imagegen_submit_outcome_unknown')
            while observation.state in {'queued','running'}:
                if self.store.clock() >= job['deadline'] or asyncio.get_running_loop().time() >= read_deadline:
                    raise OutcomeUnknown('imagegen_deadline_unknown')
                await asyncio.sleep(.1)
                observation = await inspect(observation.execution_ref)
            if observation.job_key != job['id'] or observation.input_digest != job['input_digest']:
                raise OutcomeUnknown('imagegen_observation_binding_mismatch')
            if (type(observation.fixture) is not bool or not isinstance(observation.execution_ref, str)
                    or not 1 <= len(observation.execution_ref) <= 512 or len(observation.usage_json) > 8192
                    or any(value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 160)
                           for value in (observation.actual_executor, observation.actual_model))):
                raise DomainError('imagegen_metadata_invalid')
            usage = json.loads(observation.usage_json)
            if not isinstance(usage, dict) or any(not isinstance(k,str) or len(k)>80 or type(v) not in (int,float) or v < 0 for k,v in usage.items()):
                raise DomainError('imagegen_usage_invalid')
            if observation.state == 'unknown':
                raise OutcomeUnknown('imagegen_submit_outcome_unknown')
            if observation.state != 'succeeded':
                raise DomainError('imagegen_failed', 'The executor reported failure; no publication was created')
            if not 1 <= len(observation.artifacts) <= request.candidate_budget:
                raise DomainError('imagegen_artifact_budget_mismatch')
            spec = json.loads(job['spec'])
            prepared = []
            await worker.hooks(op).emit_progress('rendering', 'started', 'Verifying image artifacts and composing explicit editorial text')
            for manifest in observation.artifacts:
                art = verified_artifact(executor.artifact_root/job['id'], manifest)
                for format in spec['formats']:
                    if len(prepared) == spec['candidates']:
                        break
                    composite = render(art.data, spec['copy'], format, spec['preset'])
                    final = verify_image(composite.png, 'image/png')
                    prepared.append((manifest, art, composite, final, format))
            if len(prepared) != spec['candidates']:
                raise DomainError('imagegen_candidate_count_mismatch')
            automatic = None
            with self.store.tx() as db:
                self.store.fence(db, op['id'], worker.id, op['fence'])
                row = self.job(db, actor, job['id'])
                self._parent_authority(db, actor, row)
                if db.execute('SELECT 1 FROM visual_candidates WHERE job_id=?', (job['id'],)).fetchone():
                    raise DomainError('visual_candidates_already_committed', next_action='refresh')
                candidates = []
                imported_arts = {}
                provenance = {'requested_route': REQUESTED_ROUTE, 'actual_executor': observation.actual_executor,
                              'actual_model': observation.actual_model, 'execution_ref': observation.execution_ref,
                              'fixture': observation.fixture, 'sources': json.loads(job['sources']), 'input_digest': job['input_digest'],
                              'usage': json.loads(observation.usage_json), 'consent': json.loads(job['consent'])}
                for ordinal, (manifest, art, composite, final, format) in enumerate(prepared):
                    if manifest.sha256 not in imported_arts:
                        art_ref = insert_verified_image(self.store, db, actor, art)
                        imported_arts[manifest.sha256] = art_ref
                        db.execute('INSERT INTO visual_asset_origins VALUES(?,?,?,?)', (art_ref, job['id'], int(observation.fixture), 'art'))
                    art_ref = imported_arts[manifest.sha256]
                    asset_ref = insert_verified_image(self.store, db, actor, final)
                    db.execute('INSERT INTO visual_asset_origins VALUES(?,?,?,?)', (asset_ref, job['id'], int(observation.fixture), 'final'))
                    sha = hashlib.sha256(final.data).hexdigest()
                    token, candidate_id = secrets.token_urlsafe(32), new_id('candidate')
                    requires_review = not observation.fixture  # Quality is unverified even when native-queue selection is authorized.
                    candidate_provenance = {**provenance, 'executor_artifact_sha256': manifest.sha256,
                                             'choice_binding': digest([job['input_digest'], candidate_id, sha, format, row['revision']]),
                                             'typography_evidence': 'explicit_copy_compositor_only' if spec['copy'] else 'prompt_text_unverified'}
                    db.execute('INSERT INTO visual_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               (candidate_id, job['id'], ordinal, asset_ref, sha, art_ref, hashlib.sha256(art.data).hexdigest(),
                                final.width, final.height, format, composite.recipe_json, canonical(candidate_provenance),
                                self.store.token_hash(token), int(observation.fixture), int(requires_review)))
                    candidate = {'id': candidate_id, 'asset_ref': asset_ref, 'sha256': sha, 'width': final.width, 'height': final.height,
                                 'format': format, 'selection_token': token, 'requires_review': requires_review}
                    candidates.append(candidate)
                    if automatic is None and (not job['parent_publication'] or format == ('story_9_16' if json.loads(job['plans'])[0]['surface']=='story' else 'post_4_5')):
                        automatic = {'kind': 'select', 'job_id': job['id'], 'candidate_id': candidate_id,
                                     'expected_revision': row['revision'], 'token': token}
                result = json.loads(db.execute('SELECT result FROM operations WHERE id=?', (op['id'],)).fetchone()[0])
                result.update(candidates=candidates, executor={'requested_route': REQUESTED_ROUTE, 'actual_executor': observation.actual_executor,
                              'actual_model': observation.actual_model, 'fixture': observation.fixture})
                db.execute("UPDATE visual_jobs SET state='needs_selection',execution_ref=?,observation=? WHERE id=?",
                           (observation.execution_ref, canonical(provenance), job['id']))
                db.execute("UPDATE operations SET state='needs_selection',complete=1,work_state='done',result=?,error=NULL WHERE id=?", (canonical(result), op['id']))
                self.store.event(db, op['id'], 'awaiting_selection', 'completed', 'Candidate hashes and private lineage committed; no social effect yet')
                if spec['selection'] == 'automatic' and self._automatic_context(json.loads(job['plans']), observation.fixture):
                    self.select(db, actor, automatic, automatic=True)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, DomainError) and exc.code == 'stale_worker':
                raise
            error = exc if isinstance(exc, DomainError) else OutcomeUnknown('imagegen_processing_unresolved')
            with self.store.tx() as db:
                self.store.fence(db, op['id'], worker.id, op['fence'])
                state = 'outcome_unknown' if isinstance(error, OutcomeUnknown) else 'blocked'
                db.execute('UPDATE visual_jobs SET state=? WHERE id=?', (state, job['id']))
                db.execute("UPDATE operations SET state=?,complete=1,work_state='done',error=? WHERE id=?", (state, canonical(error.output()), op['id']))
                self.store.event(db, op['id'], state, 'unknown' if state == 'outcome_unknown' else 'blocked', error.message)
            return True
