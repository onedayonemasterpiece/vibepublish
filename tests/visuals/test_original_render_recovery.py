"""Recover an actually dispatched artifact after an older renderer rejected Original."""
import json

import pytest

from adapters.imagegen import FakeImagegen
from social_operations.domain import DomainError
from tests.visuals.test_visual_service import runtime, call


async def blocked_original(runtime, monkeypatch, *, options=None, error='visual_preset_not_available'):
    store, actor, app, worker, _, provider, clock, *_ = runtime
    worker.imagegen = executor = FakeImagegen(store.path.parent/'original-art')
    first = await call(app, actor, 'visual', {'command': {'kind': 'generate',
        'brief': 'Original artwork', 'formats': ['original'], 'copy': {},
        'candidates': 1, 'selection': 'human', **(options or {})}, 'request_key': 'original-render'})
    def old_renderer(*_args, **_kwargs):
        raise DomainError(error)
    with monkeypatch.context() as patched:
        patched.setattr('social_operations.visuals.render', old_renderer)
        assert await worker.run_once()
    with store.connection() as db:
        op = dict(db.execute('SELECT * FROM operations WHERE id=?', (first['operation_id'],)).fetchone())
        job = dict(db.execute('SELECT * FROM visual_jobs WHERE operation_id=?', (op['id'],)).fetchone())
    assert op['state'] == job['state'] == 'blocked' and job['dispatched'] == 1
    assert len(executor.calls) == 1
    clock[0] += 31
    command = {'kind': 'reconcile_observation', 'operation_id': op['id'], 'job_id': job['id'],
        'expected_revision': op['revision'], 'expected_visual_revision': job['revision']}
    return store, actor, app, worker, executor, provider, op, job, command


@pytest.mark.asyncio
async def test_original_renderer_recovery_imports_existing_art_and_ignores_other_work(runtime, monkeypatch):
    store, actor, app, worker, executor, provider, old, job, command = await blocked_original(runtime, monkeypatch)
    other = await call(app, actor, 'visual', {'command': {'kind': 'generate', 'brief': 'Other task'},
        'request_key': 'other-task'})
    assert not await worker.run_once(operation_id='op_'+'f'*32)
    queued = await call(app, actor, 'visual', {'command': command, 'request_key': 'read-original-art'})
    assert queued['operation_id'] == old['id'] and queued['state'] == 'accepted'
    assert await worker.run_once(operation_id=old['id'])
    result = store.receipt(actor, old['id'])
    assert result['state'] == 'needs_selection' and len(result['candidates']) == 1
    assert len(executor.calls) == 1 and provider.count('effect') == 0
    assert not result.get('selected_asset_ref')
    with store.connection() as db:
        current = db.execute('SELECT * FROM operations WHERE id=?', (old['id'],)).fetchone()
        messages = [json.loads(row[0])['message'] for row in db.execute(
            'SELECT body FROM events WHERE operation_id=?', (old['id'],))]
        retained = [message for message in messages if message.startswith('Retained original renderer failure: ')]
        assert len(retained) == 1
        assert json.loads(retained[0].split(': ', 1)[1])['error']['error']['code'] == 'visual_preset_not_available'
        assert current['deadline'] == old['deadline']
        original = db.execute('SELECT * FROM visual_jobs WHERE id=?', (job['id'],)).fetchone()
        assert original['input_digest'] == job['input_digest'] and original['execution_ref'] == job['execution_ref']
        assert original['deadline'] == job['deadline']
        assert db.execute('SELECT work_state FROM operations WHERE id=?', (other['operation_id'],)).fetchone()[0] == 'ready'
    replay = await call(app, actor, 'visual', {'command': command, 'request_key': 'read-original-art'})
    assert replay['revision'] == result['revision']
    assert not await worker.run_once(operation_id=old['id'])
    assert len(executor.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['other_error', 'other_format', 'nonempty_copy'])
async def test_other_blocked_work_does_not_get_render_recovery(runtime, monkeypatch, fault):
    options = {'formats': ['post_4_5']} if fault == 'other_format' else (
        {'copy': {'title': 'Needs explicit layout'}} if fault == 'nonempty_copy' else {})
    _, actor, app, worker, executor, _, op, _, command = await blocked_original(runtime, monkeypatch,
        options=options, error='asset_integrity' if fault == 'other_error' else 'visual_preset_not_available')
    result = await app.call(actor, 'vibepublish_visual', {'command': command, 'request_key': 'forbidden-recovery'})
    assert result['error']['code'] == 'imagegen_observation_reconciliation_conflict'
    assert not await worker.run_once(operation_id=op['id'])
    assert len(executor.calls) == 1
