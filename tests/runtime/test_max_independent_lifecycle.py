"""A historical MAX dispatch cannot quarantine another immutable command."""
import json
from types import SimpleNamespace

import pytest

from adapters.fake import FakeProvider
from adapters.max.live import RealMaxDriver
from adapters.max.profile import ProfileLane
from adapters.native import saved_checkpoint
from adapters.port import Capability
from social_operations.domain import OutcomeUnknown
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


@pytest.mark.asyncio
@pytest.mark.parametrize('fresh_receipt', [True, False])
async def test_max_lost_receipt_finishes_without_global_quarantine_or_duplicate(tmp_path, fresh_receipt):
    now = [1800000000.]
    store = Store(tmp_path / 'ledger.sqlite', clock=lambda: now[0])
    actor = store.authenticate(store.create_principal('t', 'owner', owner=True))
    store.add_connection(actor, 'max', 'max', account_type='max_web', secret_ref='VIBEPUBLISH_MAX_PROFILE')
    store.bind(actor, 'owner', 'max', 'max', 'target')
    app = Application(store)
    profile = tmp_path / 'profile'

    class Native(FakeProvider):
        original = None
        lost = True

        async def inspect(self, request):
            with ProfileLane(profile) as lane:
                driver = SimpleNamespace(lane=lane, live_writes=True,
                    targets={'target': SimpleNamespace(policy='publish_channel')})
                await RealMaxDriver.mutation_preflight(driver, 'target', 'publish')
            return Capability('supported', 'Offline native receipt regression')

        async def reconcile(self, request, checkpoint, hooks):
            observed = await super().reconcile(request, checkpoint, hooks)
            if self.original is None:
                self.original = request.attempt_id
            if request.attempt_id == self.original and self.lost:
                await hooks.checkpoint('MAX_NATIVE_REFERENCE', saved_checkpoint(request,
                    driver={'native_id': observed.items[0].native_id}))
                # Retained historical artifact; the current provider must neither
                # consult nor delete this obsolete cross-operation quarantine.
                profile.joinpath('.vibepublish-uncertain').write_text(json.dumps({
                    'attempt_id': request.attempt_id, 'plan_digest': request.plan_digest}))
                raise OutcomeUnknown('receipt_lost')
            return observed

    provider = Native(tmp_path / 'remote.sqlite', 'max', clock=lambda: now[0])
    worker = Worker(store, {'max': provider})
    first = await app.call(actor, 'vibepublish_publish', {
        'to': ['max'], 'content': {'text': 'Original lost receipt'}, 'request_key': 'first'})
    await worker.run_once(operation_id=first['operation_id'])
    assert provider.count('effect') == 1
    assert not store.receipt(actor, first['operation_id'])['operation_complete']
    with store.connection() as db:
        mutation_deadline = db.execute('SELECT deadline FROM operations WHERE id=?',
                                       (first['operation_id'],)).fetchone()[0]

    second = await app.call(actor, 'vibepublish_publish', {
        'to': ['max'], 'content': {'text': 'Independent publication'}, 'request_key': 'second'})
    await worker.run_once(operation_id=second['operation_id'])
    assert store.receipt(actor, second['operation_id'])['state'] == 'verified'
    assert provider.count('effect') == 2

    provider.lost = not fresh_receipt
    now[0] += 60
    await worker.run_once(operation_id=first['operation_id'])
    if not fresh_receipt:
        now[0] += 900
        await worker.run_once(operation_id=first['operation_id'])
    if not fresh_receipt:
        pending = store.receipt(actor, first['operation_id'])
        assert not pending['operation_complete'], pending
        assert pending['state'] == 'running', pending
        assert now[0] > mutation_deadline
        with store.connection() as db:
            operation = db.execute('SELECT * FROM operations WHERE id=?',
                                   (first['operation_id'],)).fetchone()
            assert operation['work_state'] == 'working'
            assert operation['lease_until'] > now[0]
            assert operation['deadline'] == mutation_deadline
        with store.connection() as db:
            original = dict(db.execute('SELECT * FROM attempts WHERE operation_id=?',
                                       (first['operation_id'],)).fetchone())
        provider.lost = False
        now[0] += 61
        # Ordinary worker claim after backoff: no external reconcile command.
        await worker.run_once(operation_id=first['operation_id'])
        with store.connection() as db:
            recovered = dict(db.execute('SELECT * FROM attempts WHERE operation_id=?',
                                        (first['operation_id'],)).fetchone())
        assert recovered['id'] == original['id']
        assert recovered['plan_digest'] == original['plan_digest']
    final = store.receipt(actor, first['operation_id'])
    assert final['operation_complete'], final
    assert final['state'] == 'verified', final
    assert provider.count('effect') == 2
    replay = await app.call(actor, 'vibepublish_publish', {
        'to': ['max'], 'content': {'text': 'Original lost receipt'}, 'request_key': 'first'})
    assert replay['operation_id'] == first['operation_id']
    assert provider.count('effect') == 2
    assert profile.joinpath('.vibepublish-uncertain').exists()
    with provider.db() as db:
        assert db.execute("SELECT count(*) FROM calls WHERE kind='effect' AND attempt=?",
                          (provider.original,)).fetchone()[0] == 1
