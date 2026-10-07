"""Worker must survive transient SQLite claim contention without losing work."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from adapters.fake import FakeProvider
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class LockOnceStore(Store):
    lock_claim_once = True

    def claim(self, *args, **kwargs):
        if self.lock_claim_once:
            self.lock_claim_once = False
            raise sqlite3.OperationalError('database is locked')
        return super().claim(*args, **kwargs)


class WorkerLockRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_locked_claim_returns_to_loop_and_same_operation_runs_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = LockOnceStore(root / 'ledger.sqlite')
            token = store.create_principal('t', 'owner', owner=True)
            actor = store.authenticate(token)
            store.add_connection(actor, 'telegram', 'telegram', account_type='fake')
            store.bind(actor, 'owner', 'telegram', 'telegram', 'target')
            provider = FakeProvider(root / 'remote.sqlite', 'telegram')
            app = Application(store)
            accepted = await app.call(
                actor,
                'vibepublish_publish',
                {'to': ['telegram'], 'content': {'text': 'lock recovery'}},
            )

            worker = Worker(store, {'telegram': provider})
            self.assertFalse(await worker.run_once())
            pending = store.receipt(actor, accepted['operation_id'])
            self.assertFalse(pending['operation_complete'])
            self.assertEqual(provider.count('effect'), 0)

            self.assertTrue(await worker.run_once())
            done = store.receipt(actor, accepted['operation_id'])
            self.assertTrue(done['operation_complete'])
            self.assertEqual(done['state'], 'verified')
            self.assertEqual(provider.count('effect'), 1)


if __name__ == '__main__':
    unittest.main()
