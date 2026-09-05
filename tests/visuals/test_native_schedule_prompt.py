"""Owner-authorized visual queue policy, using only offline provider doubles.

SimulatedNativeImagegen exercises nonfixture-shaped metadata, not real generation.
No generated fixture from these tests is sent to a live connection.
"""
from dataclasses import replace
import json

import pytest

from adapters.imagegen import FakeImagegen
from adapters.telegram import TelegramAdapter
from social_operations.assets import import_image
from social_operations.domain import timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import ScriptedTL, TelegramClient
from tests.providers.test_native_adapters import asset, NOW, TARGETS
from tests.visuals.test_visual_service import runtime, call, select_command

PROMPT = 'Создай афишу с надписью "Кто я?" и мягким вечерним светом.'


class SimulatedNativeImagegen(FakeImagegen):
    """Deliberately synthetic bytes and simulated nonfixture metadata, offline."""
    unknown = False
    on_submit = None

    async def submit(self, request):
        ref = await super().submit(request)
        if self.on_submit:
            self.on_submit()
        return ref

    async def find(self, job_key):
        observed = await super().find(job_key)
        if observed is None:
            return None
        return replace(observed, fixture=False, actual_executor='offline-native-metadata-shape',
                       actual_model=None, state='unknown' if self.unknown else observed.state)


@pytest.fixture
def native(tmp_path):
    clock = [float(NOW)]
    store = Store(tmp_path/'ledger.sqlite', clock=lambda: clock[0])
    token = store.create_principal('tenant', 'owner', owner=True)
    actor = store.authenticate(token)
    store.add_connection(actor, 'telegram', 'telegram', account_type='mtproto_user')
    binding = store.bind(actor, actor.principal_id, 'announcements', 'telegram', TARGETS['telegram'])
    transport = TelegramClient()
    adapter = TelegramAdapter(transport, connection_id='telegram', tl=ScriptedTL(), clock=store.clock)
    executor = SimulatedNativeImagegen(tmp_path/'executor')
    app = Application(store)
    worker = Worker(store, {'telegram': adapter}, imagegen=executor)
    return store, actor, app, worker, executor, transport, clock, binding, token


def scheduled(clock):
    return {'kind': 'at', 'at': timestamp(clock[0]+3600)}


def media(ident):
    return {'source': {'kind': 'asset', 'id': ident}}


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['generate', 'tune', 'compose'])
async def test_future_native_queue_defaults_auto_with_sources_quotes_and_exact_once(native, kind):
    store, actor, app, worker, executor, provider, clock, *_ = native
    sources = [import_image(store, actor, asset(i).data, 'image/png') for i in (1, 2)]
    explicit = import_image(store, actor, asset(3).data, 'image/png')
    spec = {'kind': kind, 'prompt': PROMPT, 'candidates': 2}
    if kind == 'tune':
        spec['source'] = media(sources[0])
    else:
        spec['sources'] = [media(i) for i in sources[:1 if kind == 'generate' else 2]]
    args = {'to': ['announcements'], 'content': {'text': 'Native queue caption'},
            'media': [media(explicit)], 'visual': spec, 'delivery': scheduled(clock), 'request_key': 'queued-visual'}
    accepted = await call(app, actor, 'publish', args)
    assert provider.effects == 0 and executor.calls == []
    assert await worker.run_once()
    selected = store.receipt(actor, accepted['operation_id'])
    assert selected['state'] == 'accepted' and selected['selected_sha256']
    assert provider.effects == 0 and len(executor.calls) == 1
    assert executor.calls[0].brief == PROMPT
    assert len(executor.calls[0].sources) == (2 if kind == 'compose' else 1)
    assert all(c['requires_review'] for c in selected['candidates'])  # Quality remains unverified.
    assert all('selection_token' not in c for c in selected['candidates'])
    with store.connection() as db:
        job = db.execute('SELECT * FROM visual_jobs').fetchone()
        frozen = json.loads(job['spec'])
        assert frozen['selection'] == 'automatic' and frozen['brief'] == PROMPT and frozen['copy'] == {}
        assert 'prompt' not in frozen
        plans = [json.loads(row['plan']) for row in db.execute('SELECT plan FROM attempts')]
        assert len(plans) == 1
        assert [a['ref'] for a in plans[0]['assets']] == [selected['selected_asset_ref'], explicit]
        assert not set(sources) & {a['ref'] for a in plans[0]['assets']}
        candidate = db.execute('SELECT provenance,recipe FROM visual_candidates LIMIT 1').fetchone()
        assert json.loads(candidate['provenance'])['typography_evidence'] == 'prompt_text_unverified'
        assert json.loads(candidate['recipe'])['copy'] == {}
    assert await worker.run_once()
    done = (await app.call(actor, 'vibepublish_status', {'ids': [accepted['operation_id']]}))['receipts'][0]
    assert done['state'] == 'scheduled' and done['deliveries'][0]['effective_at'] == args['delivery']['at']
    assert provider.effects == 1 and len(provider.scheduled) == 2 and not provider.messages
    # Alias normalization happens before idempotency, including after revision advancement.
    legacy = {**args, 'visual': {**spec, 'brief': spec['prompt']}}
    del legacy['visual']['prompt']
    assert (await call(app, actor, 'publish', legacy))['operation_id'] == accepted['operation_id']
    assert not await worker.run_once() and len(executor.calls) == 1 and provider.effects == 1
    conflict = await app.call(actor, 'vibepublish_visual', {'command': {
        'kind': 'select', 'job_id': selected['visual_job_id'], 'candidate_id': selected['candidates'][1]['id'],
        'expected_revision': 1, 'token': 'stale-choice'}})
    assert conflict['error']['code'] == 'visual_selection_conflict'
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM publications').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('context', ['immediate', 'preview', 'standalone', 'explicit_human'])
async def test_nonfixture_does_not_gain_other_automatic_authority(native, context):
    store, actor, app, worker, executor, provider, clock, *_ = native
    spec = {'kind': 'generate', 'prompt': PROMPT, 'selection': 'human' if context == 'explicit_human' else 'automatic', 'candidates': 1}
    if context == 'standalone':
        first = await call(app, actor, 'visual', {'command': spec})
    else:
        first = await call(app, actor, 'publish', {'to': ['announcements'], 'visual': spec,
            'mode': 'preview' if context == 'preview' else 'execute',
            'delivery': {'kind': 'now'} if context == 'immediate' else scheduled(clock)})
    await worker.run_once()
    ready = store.receipt(actor, first['operation_id'])
    assert ready['state'] == 'needs_selection' and 'selected_asset_ref' not in ready
    assert provider.effects == 0
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
        if context == 'standalone':
            assert db.execute('SELECT count(*) FROM publications').fetchone()[0] == 0
    if context == 'preview':
        await call(app, actor, 'visual', {'command': select_command(ready)})
        await worker.run_once()
        assert store.receipt(actor, first['operation_id'])['state'] == 'needs_approval'
        assert provider.effects == 0


@pytest.mark.asyncio
async def test_even_explicit_fixture_automatic_cannot_send_immediately(runtime):
    store, actor, app, worker, executor, provider, *_ = runtime
    first = await call(app, actor, 'publish', {'to': ['announcements'],
        'visual': {'kind': 'generate', 'prompt': PROMPT, 'selection': 'automatic', 'candidates': 1}})
    await worker.run_once()
    assert store.receipt(actor, first['operation_id'])['state'] == 'needs_selection'
    assert provider.count('effect') == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['expiry', 'routing', 'revision', 'revocation'])
async def test_queue_auto_rechecks_authority_after_generation_before_selection(native, mutation):
    store, actor, app, worker, executor, provider, clock, binding, _ = native
    first = await call(app, actor, 'publish', {'to': ['announcements'],
        'visual': {'kind': 'generate', 'prompt': PROMPT, 'candidates': 1}, 'delivery': scheduled(clock)})
    def change():
        if mutation == 'expiry':
            clock[0] += 3570
        elif mutation == 'revocation':
            store.revoke_binding(actor, binding)
        else:
            with store.tx() as db:
                if mutation == 'routing':
                    db.execute('UPDATE principals SET routing_revision=routing_revision+1 WHERE id=?', (actor.principal_id,))
                else:
                    db.execute('UPDATE publications SET revision=revision+1 WHERE id=?', (first['resource_id'],))
    executor.on_submit = change
    await worker.run_once()
    with store.connection() as db:
        op = db.execute('SELECT * FROM operations WHERE id=?', (first['operation_id'],)).fetchone()
        assert op['state'] == 'blocked'
        assert json.loads(op['error'])['error']['code'] == {
            'expiry': 'native_lead_time', 'routing': 'routing_stale',
            'revision': 'visual_parent_revision_conflict', 'revocation': 'access_revoked'}[mutation]
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
    assert provider.effects == 0 and len(executor.calls) == 1


@pytest.mark.asyncio
async def test_queue_unknown_generator_outcome_never_resubmits_or_publishes(native):
    store, actor, app, worker, executor, provider, clock, *_ = native
    executor.unknown = True
    first = await call(app, actor, 'publish', {'to': ['announcements'],
        'visual': {'kind': 'generate', 'prompt': PROMPT, 'candidates': 1}, 'delivery': scheduled(clock), 'request_key': 'unknown'})
    await worker.run_once()
    assert store.receipt(actor, first['operation_id'])['state'] == 'outcome_unknown'
    assert not await worker.run_once() and len(executor.calls) == 1 and provider.effects == 0


@pytest.mark.asyncio
async def test_offline_fixture_never_crosses_native_queue_guard(native, tmp_path):
    store, actor, app, worker, _executor, provider, clock, *_ = native
    worker.imagegen = FakeImagegen(tmp_path/'actual-fixture')
    first = await call(app, actor, 'publish', {'to': ['announcements'],
        'visual': {'kind': 'generate', 'prompt': PROMPT, 'candidates': 1}, 'delivery': scheduled(clock)})
    await worker.run_once()
    done = store.receipt(actor, first['operation_id'])
    assert done['state'] == 'blocked' and done['error']['code'] == 'fixture_asset_native_publish_forbidden'
    assert provider.effects == 0


@pytest.mark.asyncio
async def test_original_media_without_visual_never_invokes_generator(native):
    store, actor, app, worker, executor, provider, clock, *_ = native
    original = import_image(store, actor, asset().data, 'image/png')
    first = await call(app, actor, 'publish', {'to': ['announcements'], 'media': [media(original)], 'delivery': scheduled(clock)})
    await worker.run_once()
    assert store.receipt(actor, first['operation_id'])['state'] == 'scheduled'
    assert executor.calls == [] and provider.effects == 1
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM visual_jobs').fetchone()[0] == 0
        assert json.loads(db.execute('SELECT plan FROM attempts').fetchone()[0])['assets'][0]['ref'] == original


@pytest.mark.asyncio
async def test_legacy_copy_is_distinct_from_unchanged_prompt_and_alias_replay(runtime):
    store, actor, app, worker, executor, *_ = runtime
    command = {'kind': 'generate', 'prompt': PROMPT, 'copy': {'title': 'Exact title'}, 'candidates': 1}
    first = await call(app, actor, 'visual', {'command': command, 'request_key': 'copy'})
    legacy = {**command, 'brief': command['prompt']}
    del legacy['prompt']
    assert (await call(app, actor, 'visual', {'command': legacy, 'request_key': 'copy'}))['operation_id'] == first['operation_id']
    assert (await call(app, actor, 'visual', {'command': {**command, 'brief': PROMPT}, 'request_key': 'copy'}))['operation_id'] == first['operation_id']
    await worker.run_once()
    assert executor.calls[0].brief.endswith(PROMPT)
    assert 'without lettering or editorial text' in executor.calls[0].brief
    with store.connection() as db:
        candidate = db.execute('SELECT provenance,recipe FROM visual_candidates').fetchone()
        assert json.loads(candidate['recipe'])['copy'] == command['copy']
        assert json.loads(candidate['provenance'])['typography_evidence'] == 'explicit_copy_compositor_only'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['generate', 'tune', 'compose'])
async def test_prompt_alias_validation_source_bounds_and_conflict_before_admission(runtime, kind):
    store, actor, app, worker, executor, *_ = runtime
    original = import_image(store, actor, asset().data, 'image/png')
    descriptor = media(original)
    spec = {'kind': kind, 'prompt': PROMPT}
    if kind == 'tune':
        spec['source'] = descriptor
    elif kind == 'compose':
        spec['sources'] = [descriptor, descriptor]
    for bad in ({**spec, 'brief': 'different'}, {**spec, 'prompt': ''}, {k: v for k, v in spec.items() if k != 'prompt'}):
        response = await app.call(actor, 'vibepublish_visual', {'command': bad})
        assert response['error']['code'] in {'visual_prompt_conflict', 'invalid_input'}
    if kind == 'generate':
        for count in (0, 8):
            accepted = await call(app, actor, 'visual', {'command': {**spec, 'sources': [descriptor]*count}, 'request_key': f'refs-{count}'})
            assert accepted['state'] == 'accepted'
        denied = await app.call(actor, 'vibepublish_visual', {'command': {**spec, 'sources': [descriptor]*9}})
        assert denied['error']['code'] == 'invalid_input'
    else:
        missing = dict(spec)
        missing.pop('source' if kind == 'tune' else 'sources')
        assert (await app.call(actor, 'vibepublish_visual', {'command': missing}))['error']['code'] == 'invalid_input'
    assert executor.calls == []
