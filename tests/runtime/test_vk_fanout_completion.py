"""Regression coverage for one-command Telegram+VK completion."""
import tempfile
import unittest
from pathlib import Path

from adapters.fake import FakeProvider
from social_operations.domain import DomainError, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class FlakyVKBeforeDispatch(FakeProvider):
    def __init__(self, *args, failures=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.failures = failures

    async def execute(self, prepared, hooks):
        if self.failures:
            self.failures -= 1
            self.record('execute', prepared.request.attempt_id)
            raise DomainError('vk_http_failed')
        return await super().execute(prepared, hooks)


class FlakyVKPreflight(FakeProvider):
    def __init__(self, *args, failures=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.failures = failures

    async def prepare(self, request, hooks):
        if self.failures:
            self.failures -= 1
            self.record('prepare', request.attempt_id)
            raise DomainError('vk_http_failed')
        return await super().prepare(request, hooks)


class VKFanoutCompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1_800_000_000.0
        self.store = Store(self.root / 'ledger.sqlite', clock=lambda: self.now)
        self.token = self.store.create_principal('t', 'owner', owner=True)
        self.actor = self.store.authenticate(self.token)
        self.store.add_connection(self.actor, 'telegram', 'telegram', account_type='fake')
        self.store.add_connection(self.actor, 'vk', 'vk', account_type='fake')
        self.store.bind(self.actor, 'owner', 'telegram', 'telegram', 'target_tg')
        self.store.bind(self.actor, 'owner', 'vk', 'vk', 'target_vk')
        self.telegram = FakeProvider(self.root / 'remote.sqlite', 'telegram', clock=lambda: self.now)
        self.vk = FlakyVKBeforeDispatch(self.root / 'remote.sqlite', 'vk', clock=lambda: self.now)
        self.app = Application(self.store)

    async def publish(self, request_key):
        return await self.app.call(
            self.actor,
            'vibepublish_publish',
            {
                'to': ['telegram', 'vk'],
                'content': {'text': 'Fan-out fixture'},
                'delivery': {'kind': 'at', 'at': timestamp(self.now + 3600)},
                'request_key': request_key,
            },
        )

    async def test_partial_tg_success_auto_resumes_same_vk_attempt_after_worker_restart(self):
        accepted = await self.publish('fanout-once')
        operation_id = accepted['operation_id']

        first_worker = Worker(self.store, {'telegram': self.telegram, 'vk': self.vk})
        self.assertTrue(await first_worker.run_once())

        midway = self.store.receipt(self.actor, operation_id)
        self.assertFalse(midway['operation_complete'])
        self.assertEqual(midway['state'], 'running')
        tg = next(d for d in midway['deliveries'] if d['provider'] == 'telegram')
        vk = next(d for d in midway['deliveries'] if d['provider'] == 'vk')
        self.assertEqual(tg['observed'], 'provider_scheduled')
        self.assertEqual(vk['observed'], 'not_attempted')
        self.assertEqual(self.telegram.count('effect'), 1)
        self.assertEqual(self.vk.count('effect'), 0)

        self.now += 2
        restarted = Worker(self.store, {'telegram': self.telegram, 'vk': self.vk})
        self.assertTrue(await restarted.run_once())

        final = self.store.receipt(self.actor, operation_id)
        self.assertTrue(final['operation_complete'])
        self.assertEqual(final['state'], 'scheduled')
        self.assertEqual({d['observed'] for d in final['deliveries']}, {'provider_scheduled'})
        self.assertEqual(self.telegram.count('effect'), 1)
        self.assertEqual(self.vk.count('effect'), 1)
        self.assertEqual(self.telegram.count('execute'), 1)
        self.assertEqual(self.vk.count('execute'), 2)

    async def test_transient_vk_preflight_reopens_all_never_dispatched_siblings(self):
        vk = FlakyVKPreflight(self.root / 'remote.sqlite', 'vk', clock=lambda: self.now)
        accepted = await self.publish('fanout-preflight')
        operation_id = accepted['operation_id']

        first_worker = Worker(self.store, {'telegram': self.telegram, 'vk': vk})
        self.assertTrue(await first_worker.run_once())

        midway = self.store.receipt(self.actor, operation_id)
        self.assertFalse(midway['operation_complete'])
        self.assertEqual(midway['state'], 'running')
        self.assertEqual(self.telegram.count('effect'), 0)
        self.assertEqual(vk.count('effect'), 0)

        self.now += 2
        restarted = Worker(self.store, {'telegram': self.telegram, 'vk': vk})
        self.assertTrue(await restarted.run_once())

        final = self.store.receipt(self.actor, operation_id)
        self.assertTrue(final['operation_complete'])
        self.assertEqual(final['state'], 'scheduled')
        self.assertEqual({d['observed'] for d in final['deliveries']}, {'provider_scheduled'})
        self.assertEqual(self.telegram.count('effect'), 1)
        self.assertEqual(vk.count('effect'), 1)


if __name__ == '__main__':
    unittest.main()
