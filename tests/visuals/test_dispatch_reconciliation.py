"""Offline no-turn fixtures: no native generation or publication is requested."""
import json
import time
from unittest.mock import patch

import pytest
import pytest_asyncio
import httpx

from adapters.codex_task_imagegen import CodexTaskImagegen, CodexTaskNoTurnProof
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class LostThreadResponse:
    def __init__(self):
        self.calls = []

    async def request(self, method, args):
        self.calls.append(method)
        assert method == 'thread/start'
        raise ConnectionError('offline lost settings-only thread response')

    async def close(self):
        pass


@pytest_asyncio.fixture
async def unknown(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite')
    token = store.create_principal('tenant', 'owner', owner=True)
    actor = store.authenticate(token)
    home = tmp_path / 'codex'
    home.mkdir(mode=0o700)
    skill = home / 'skills' / '.system' / 'imagegen' / 'SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('# Offline skill fixture')
    transport = LostThreadResponse()
    executor = CodexTaskImagegen(tmp_path / 'images', codex_home=home, transport=transport)
    app = Application(store, visual_dispatch_proof=CodexTaskNoTurnProof(executor.control_root))
    receipt = await app.call(actor, 'vibepublish_visual',
        {'command': {'kind': 'generate', 'brief': 'Offline fixture'}, 'request_key': 'original'})
    worker = Worker(store, imagegen=executor)
    assert await worker.run_once()
    receipt = store.receipt(actor, receipt['operation_id'])
    assert receipt['state'] == 'outcome_unknown' and receipt['operation_complete']
    with store.tx() as db:
        # Reproduce the historical retained expired lease, whose owner/fence
        # would still authorize a late storage.fence() call without sealing it.
        db.execute('UPDATE operations SET lease_owner=?,lease_until=? WHERE id=?',
            ('old_worker', time.time() - 10, receipt['operation_id']))
    command = {'kind': 'reconcile_dispatch', 'job_id': receipt['visual_job_id'],
        'operation_id': receipt['operation_id'], 'expected_revision': receipt['revision'],
        'expected_visual_revision': receipt['visual_revision']}
    yield store, actor, app, worker, executor, transport, receipt, command
    await executor.close()


async def reconcile(fixture, **overrides):
    _, actor, app, _, _, _, _, command = fixture
    return await app.call(actor, 'vibepublish_visual',
        {'command': {**command, **overrides}, 'request_key': 'seal-original'})


@pytest.mark.asyncio
async def test_original_terminal_unknown_sealed_without_transport_or_replay(unknown):
    store, actor, app, worker, executor, transport, original, command = unknown
    directory = executor._directory(original['visual_job_id'])
    private_before = (directory / 'receipt.json').read_bytes()
    with store.connection() as db:
        fence = db.execute('SELECT fence FROM operations WHERE id=?', (original['operation_id'],)).fetchone()[0]
    with patch('adapters.codex_task_imagegen.AppServer', side_effect=AssertionError('no transport')):
        result = await reconcile(unknown)
    assert result['operation_id'] == original['operation_id']
    assert result['state'] == 'failed' and result['retry_safe']
    assert result['generation_dispatch'] == 'not_sent'
    assert result['revision'] == original['revision'] + 1
    assert result['visual_revision'] == original['visual_revision'] + 1
    assert result['error']['code'] == 'imagegen_not_dispatched'
    assert result['deliveries'] == [] and not result.get('candidates')
    assert (directory / 'receipt.json').read_bytes() == private_before
    assert transport.calls == ['thread/start']
    with store.tx() as db:
        op = db.execute('SELECT * FROM operations WHERE id=?', (original['operation_id'],)).fetchone()
        assert op['fence'] == fence + 1 and op['lease_owner'] is None
        assert op['complete'] == 1 and op['work_state'] == 'done' and op['lease_until'] == 0
        with pytest.raises(DomainError, match='stale worker'):
            store.fence(db, op['id'], 'old_worker', fence)
        job = db.execute('SELECT * FROM visual_jobs WHERE id=?', (command['job_id'],)).fetchone()
        assert job['dispatched'] == 1 and job['execution_ref'] == command['job_id']
        proof = json.loads(job['observation'])['dispatch_reconciliation']
        assert proof['generation_dispatch'] == 'not_sent'
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0] == 1
    replay = await reconcile(unknown)
    assert replay['revision'] == result['revision'] and replay['retry_safe']
    assert not await worker.run_once()
    assert transport.calls == ['thread/start']


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'phase': 'turn_start_pending'}, {'thread_id': '01a07234-66ed-77d3-b42d-9645fd167d18'},
    {'turn_id': '01a07234-7e26-79c1-ae63-4ea2e927786d'}, {'input_digest': 'f' * 64},
    {'artifacts': [{}]}, {'native_image_items': [{}]}, {'state': 'succeeded'},
])
async def test_ambiguous_or_foreign_receipt_stays_unknown(unknown, change):
    store, actor, _, _, executor, transport, original, _ = unknown
    directory = executor._directory(original['visual_job_id'])
    record = executor._load(directory)
    executor._record(directory, {**record, **change})
    result = await reconcile(unknown)
    assert result['error']['code'] in {'imagegen_dispatch_not_proven', 'imagegen_dispatch_proof_unavailable'}
    assert store.receipt(actor, original['operation_id'])['state'] == 'outcome_unknown'
    assert transport.calls == ['thread/start']


@pytest.mark.asyncio
async def test_busy_original_executor_lock_cannot_seal(unknown):
    _, _, _, _, executor, _, original, _ = unknown
    with executor._lock(executor._directory(original['visual_job_id'])):
        result = await reconcile(unknown)
    assert result['error']['code'] == 'imagegen_dispatch_proof_busy'


@pytest.mark.asyncio
@pytest.mark.parametrize('column,value', [('lease_until', 'future'), ('complete', 0), ('work_state', 'working')])
async def test_live_or_nonterminal_core_cannot_seal(unknown, column, value):
    store, _, _, _, _, _, original, _ = unknown
    if column == 'lease_until':
        value = time.time() + 600  # Compute when the test runs, not during slow suite collection.
    with store.tx() as db:
        db.execute(f'UPDATE operations SET {column}=? WHERE id=?', (value, original['operation_id']))
    assert (await reconcile(unknown))['error']['code'] == 'imagegen_dispatch_reconciliation_conflict'


@pytest.mark.asyncio
async def test_revision_authority_and_explicit_key_are_required(unknown):
    store, actor, app, _, executor, _, original, command = unknown
    assert (await reconcile(unknown, expected_revision=999))['error']['code'] == 'visual_revision_conflict'
    assert (await reconcile(unknown, expected_visual_revision=999))['error']['code'] == 'visual_revision_conflict'
    no_key = await app.call(actor, 'vibepublish_visual', {'command': command})
    assert no_key['error']['code'] == 'reconciliation_requires_request_key'
    other = store.authenticate(store.create_principal('tenant', 'other'))
    forbidden = await app.call(other, 'vibepublish_visual', {'command': command, 'request_key': 'other'})
    assert forbidden['error']['code'] in {'visual_not_available', 'access_denied'}
    await app.call(actor, 'vibepublish_visual', {'command': {**command, 'receipt_path': str(executor.control_root)}, 'request_key': 'path'})
    assert store.receipt(actor, original['operation_id'])['state'] == 'outcome_unknown'


@pytest.mark.asyncio
async def test_missing_or_symlink_lock_never_created_or_followed(unknown):
    _, _, _, _, executor, _, original, _ = unknown
    lock = executor._directory(original['visual_job_id']) / 'lock'
    lock.unlink()
    assert (await reconcile(unknown))['error']['code'] == 'imagegen_dispatch_proof_unavailable'
    assert not lock.exists()
    lock.symlink_to('/dev/null')
    assert (await reconcile(unknown))['error']['code'] == 'imagegen_dispatch_proof_unavailable'


@pytest.mark.asyncio
async def test_http_existing_command_route_uses_trusted_reader_and_same_key(unknown):
    from social_operations.server import create_app
    store, actor, _, _, executor, transport, original, command = unknown
    with patch('adapters.codex_task_imagegen.AppServer', side_effect=AssertionError('no transport')):
        app = create_app(store, authenticate=lambda _: actor,
            visual_dispatch_proof=CodexTaskNoTurnProof(executor.control_root))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver',
                headers={'Authorization': 'Bearer offline-fixture', 'Idempotency-Key': 'http-seal'}) as client:
            response = await client.post('/v1/visuals/commands', json={'command': command})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['operation_id'] == original['operation_id']
            assert result['retry_safe'] and result['generation_dispatch'] == 'not_sent'
            replay = await client.post('/v1/visuals/commands', json={'command': command})
            assert replay.json()['revision'] == result['revision']
    assert transport.calls == ['thread/start']
