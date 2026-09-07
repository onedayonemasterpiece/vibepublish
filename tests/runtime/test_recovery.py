"""Original-terminal recovery, durable resolution/release, no duplicate execute."""
import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from adapters.fake import FakeProvider
from social_operations.domain import OutcomeUnknown
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class RecoveringProvider(FakeProvider):
    unknown = True
    release_failures = 0
    crash_after_release = False
    wrong_target = False
    release_gate = None

    async def reconcile(self, request, checkpoint, hooks):
        self.last_checkpoint = json.loads(checkpoint)
        observation = await super().reconcile(request, checkpoint, hooks)
        if self.unknown:
            raise OutcomeUnknown('receipt_lost')
        if self.wrong_target:
            observation = replace(observation, items=(replace(observation.items[0], native_target='wrong'),))
        return observation

    async def finalize(self, request, checkpoint, hooks):
        self.record('finalize', request.attempt_id)
        saved = json.loads(checkpoint)
        assert saved['core_recovery']['attempt_id'] == request.attempt_id
        assert saved['core_recovery']['plan_digest'] == request.plan_digest
        with self.core.connection() as db:
            row = db.execute('SELECT * FROM attempt_recovery WHERE attempt_id=?', (request.attempt_id,)).fetchone()
            assert row['observation'] and row['finalize_state'] == 'pending'
            assert db.execute('SELECT state FROM attempts WHERE id=?', (request.attempt_id,)).fetchone()[0] == 'verified'
        if self.release_gate:
            await self.release_gate.wait()
        if self.release_failures:
            self.release_failures -= 1
            raise RuntimeError('release unavailable')
        self.record('released', request.attempt_id)
        if self.crash_after_release:
            self.crash_after_release = False
            raise asyncio.CancelledError()


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1800000000.0
        self.store = Store(self.root/'ledger.sqlite', clock=lambda: self.now)
        self.token = self.store.create_principal('t', 'owner', owner=True)
        self.actor = self.store.authenticate(self.token)
        self.store.add_connection(self.actor, 'max', 'max', account_type='fake')
        self.binding = self.store.bind(self.actor, 'owner', 'max', 'max', 'target')
        self.provider = RecoveringProvider(self.root/'remote.sqlite', 'max', clock=lambda: self.now)
        self.provider.core = self.store
        self.app = Application(self.store)
        self.worker = Worker(self.store, {'max': self.provider})

    async def call(self, method, args, actor=None):
        return await self.app.call(actor or self.actor, 'vibepublish_'+method, args)

    async def stuck(self, targets=None):
        receipt = await self.call('publish', {'to': targets or ['max'], 'content': {'text': 'Original'}})
        await self.worker.run_once()
        self.assertEqual(self.store.receipt(self.actor, receipt['operation_id'])['state'], 'outcome_unknown')
        return receipt

    def args(self, receipt, **change):
        return {'publication_id': receipt['resource_id'], 'expected_revision': 1,
                'change': {'kind': 'reconcile', 'operation_id': receipt['operation_id'], **change}, 'request_key': 'recover'}

    async def test_terminal_resolution_original_identity_and_durable_hint(self):
        receipt = await self.stuck()
        with self.store.connection() as db:
            attempt = dict(db.execute('SELECT * FROM attempts').fetchone())
        self.now += 9999  # An expired send deadline never prevents observation.
        self.provider.unknown = False
        args = self.args(receipt, attempt_id=attempt['id'], native_reference='https://max.ru/exact')
        accepted = await self.call('publication_update', args)
        self.assertEqual(accepted['operation_id'], receipt['operation_id'])
        self.assertFalse(accepted['operation_complete'])
        await self.worker.run_once()
        result = self.store.receipt(self.actor, receipt['operation_id'])
        self.assertEqual(result['state'], 'verified', result)
        self.assertNotIn('error', result)
        self.assertTrue(result['operation_complete'])
        self.assertEqual(self.provider.last_checkpoint['core_recovery']['native_reference'], 'https://max.ru/exact')
        self.assertEqual((await self.call('publication_update', args))['state'], 'verified')
        self.assertFalse(await self.worker.run_once())
        self.assertEqual(self.provider.count('execute'), 1)
        self.assertEqual(self.provider.count('effect'), 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM operations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM revisions').fetchone()[0], 1)
            row = db.execute('SELECT * FROM attempt_recovery').fetchone()
            self.assertEqual(row['original_checkpoint'], attempt['checkpoint'])
            self.assertEqual(row['finalize_state'], 'done')
            self.assertTrue(row['observation'])

    async def test_insufficient_or_mismatched_evidence_never_releases(self):
        receipt = await self.stuck()
        await self.call('publication_update', self.args(receipt))
        await self.worker.run_once()
        self.assertEqual(self.store.receipt(self.actor, receipt['operation_id'])['state'], 'outcome_unknown')
        self.provider.unknown, self.provider.wrong_target = False, True
        args = self.args(receipt); args['request_key'] = 'fresh-observation'
        await self.call('publication_update', args)
        await self.worker.run_once()
        self.assertEqual(self.store.receipt(self.actor, receipt['operation_id'])['state'], 'outcome_unknown')
        self.assertEqual(self.provider.count('finalize'), 0)
        self.assertEqual(self.provider.count('effect'), 1)

    async def test_partial_success_sibling_is_unchanged(self):
        self.store.add_connection(self.actor, 'telegram', 'telegram', account_type='fake')
        self.store.bind(self.actor, 'owner', 'telegram', 'telegram', 'other')
        other = FakeProvider(self.root/'remote.sqlite', 'telegram', clock=lambda: self.now)
        self.worker.adapters['telegram'] = other
        receipt = await self.stuck(['max', 'telegram'])
        before = self.store.receipt(self.actor, receipt['operation_id'])['deliveries'][1]
        self.provider.unknown = False
        await self.call('publication_update', self.args(receipt))
        await self.worker.run_once()
        after = self.store.receipt(self.actor, receipt['operation_id'])['deliveries'][1]
        self.assertEqual(before, after)
        self.assertEqual(other.count('execute'), 1)
        self.assertEqual(other.count('reconcile'), 1)

    async def test_release_failure_restart_and_connection_guard(self):
        receipt = await self.stuck()
        self.provider.unknown, self.provider.release_failures = False, 1
        await self.call('publication_update', self.args(receipt))
        await self.worker.run_once()
        result = self.store.receipt(self.actor, receipt['operation_id'])
        self.assertFalse(result['operation_complete'])
        self.assertEqual(result['deliveries'][0]['state'], 'verified')
        # New effect cannot bypass the pending-finalize journal.
        new = await self.call('publish', {'to': ['max'], 'content': {'text': 'Blocked until release'}})
        await self.worker.run_once()
        self.assertEqual(self.store.receipt(self.actor, new['operation_id'])['state'], 'blocked')
        self.now += 31
        restarted = Worker(Store(self.store.path, clock=lambda: self.now), {'max': self.provider})
        await restarted.run_once()
        self.assertEqual(self.store.receipt(self.actor, receipt['operation_id'])['state'], 'verified')
        self.assertEqual(self.provider.count('effect'), 1)
        self.assertEqual(self.provider.count('finalize'), 2)

    async def test_crash_after_release_before_ack_only_repeats_finalize(self):
        receipt = await self.stuck()
        self.provider.unknown, self.provider.crash_after_release = False, True
        await self.call('publication_update', self.args(receipt))
        with self.assertRaises(asyncio.CancelledError):
            await self.worker.run_once()
        self.now += 31
        await Worker(self.store, {'max': self.provider}).run_once()
        self.assertEqual(self.store.receipt(self.actor, receipt['operation_id'])['state'], 'verified')
        self.assertEqual(self.provider.count('effect'), 1)
        self.assertEqual(self.provider.count('finalize'), 2)

    async def test_auth_epoch_scope_revision_and_hint_guards(self):
        receipt = await self.stuck()
        args = self.args(receipt)
        wrong = {**args, 'expected_revision': 2}
        self.assertEqual((await self.call('publication_update', wrong))['error']['code'], 'revision_conflict')
        wrong = self.args(receipt, attempt_id='attempt_wrong')
        self.assertEqual((await self.call('publication_update', wrong))['error']['code'], 'recovery_operation_mismatch')
        token = self.store.create_principal('t', 'other', scopes={'publication.manage'})
        self.assertEqual((await self.call('publication_update', args, self.store.authenticate(token)))['error']['code'], 'not_found')
        self.store.revoke_binding(self.actor, self.binding)
        fresh = self.store.authenticate(self.token)
        self.assertEqual((await self.call('publication_update', args, fresh))['error']['code'], 'access_revoked')
        self.assertEqual(self.provider.count('effect'), 1)

    async def test_revocation_after_admission_prevents_observation(self):
        receipt = await self.stuck()
        await self.call('publication_update', self.args(receipt))
        self.provider.unknown = False
        self.store.revoke_binding(self.actor, self.binding)
        await self.worker.run_once()
        self.assertEqual(self.provider.count('reconcile'), 1)
        self.assertEqual(self.provider.count('finalize'), 0)

    async def test_stale_worker_cannot_finalize_or_resolve(self):
        receipt = await self.stuck()
        await self.call('publication_update', self.args(receipt))
        old = self.store.claim('old')
        self.now += 31
        self.store.claim('new')
        with self.store.connection() as db:
            child = dict(db.execute('SELECT * FROM attempts').fetchone())
        worker = Worker(self.store, {'max': self.provider}, worker_id='old')
        await worker.run_child(old, child, self.actor, None)
        self.assertEqual(self.provider.count('reconcile'), 1)
        self.assertEqual(self.provider.count('finalize'), 0)

    async def test_crash_after_durable_resolution_before_release(self):
        receipt = await self.stuck()
        self.provider.unknown = False
        await self.call('publication_update', self.args(receipt))
        class CrashAfterCommit(Worker):
            def finish_child(self, *args, **kwargs):
                super().finish_child(*args, **kwargs)
                raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await CrashAfterCommit(self.store, {'max': self.provider}).run_once()
        self.assertEqual(self.provider.count('finalize'), 0)
        self.now += 31
        await Worker(self.store, {'max': self.provider}).run_once()
        self.assertEqual(self.store.receipt(self.actor, receipt['operation_id'])['state'], 'verified')
        self.assertEqual(self.provider.count('execute'), 1)
        self.assertEqual(self.provider.count('finalize'), 1)

    async def test_readback_revocation_rejects_resolution_and_release(self):
        receipt = await self.stuck()
        await self.call('publication_update', self.args(receipt))
        self.provider.unknown = False
        original = self.provider.reconcile
        async def revoke_during_read(*args):
            observation = await original(*args)
            self.store.revoke_binding(self.actor, self.binding)
            return observation
        self.provider.reconcile = revoke_during_read
        await self.worker.run_once()
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT state FROM attempts').fetchone()[0], 'outcome_unknown')
            self.assertIsNone(db.execute('SELECT observation FROM attempt_recovery').fetchone()[0])
        self.assertEqual(self.provider.count('finalize'), 0)

    async def test_version_three_database_migrates_without_changing_original(self):
        receipt = await self.stuck()
        with self.store.tx() as db:
            before = dict(db.execute('SELECT * FROM attempts').fetchone())
            db.execute('DROP TRIGGER immutable_recovery_origin')
            db.execute('DROP TABLE attempt_recovery')
            db.execute('PRAGMA user_version=3')
        restored = Store(self.store.path, clock=lambda: self.now)
        with restored.connection() as db:
            self.assertEqual(dict(db.execute('SELECT * FROM attempts').fetchone()), before)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
        self.provider.unknown = False
        await self.call('publication_update', self.args(receipt))
        await Worker(restored, {'max': self.provider}).run_once()
        self.assertEqual(self.store.receipt(self.actor, receipt['operation_id'])['state'], 'verified')
