"""W1 worker reliability: deterministic offline transports, zero real provider calls."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from adapters.fake import FakeProvider
from social_operations.domain import DomainError, canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class NativeIdReadbackDown(FakeProvider):
    """POST has a native response and durable checkpoint; GET cannot complete."""
    fail_read = True

    async def execute(self, prepared, hooks):
        request = prepared.request
        self.record('execute', request.attempt_id)
        await hooks.before_effect(request.attempt_id, request.plan_digest)
        self.record('effect', request.attempt_id)
        await hooks.checkpoint('vk_response', canonical(dict(
            attempt=request.attempt_id, plan=request.plan_digest,
            target=request.native_target, id='456')))
        raise DomainError('provider_read_deadline')

    async def reconcile(self, request, checkpoint, hooks):
        self.record('reconcile', request.attempt_id)
        if self.fail_read:
            raise DomainError('provider_read_deadline')
        item = self.item('456', 'scheduled' if request.scheduled_at else 'published',
                         json.loads(request.content_json)['text'], request.scheduled_at,
                         [a.sha256 for a in request.assets], None, request.native_target)
        from adapters.port import Observation
        return Observation('provider_scheduled' if request.scheduled_at else 'published', (item,))


class NoNativeId(FakeProvider):
    """The effect boundary was entered but no native identifier survived."""
    async def execute(self, prepared, hooks):
        request = prepared.request
        self.record('execute', request.attempt_id)
        await hooks.before_effect(request.attempt_id, request.plan_digest)
        raise DomainError('vk_http_failed')

    async def reconcile(self, request, checkpoint, hooks):
        self.record('reconcile', request.attempt_id)
        raise DomainError('vk_http_failed')


class TransientPrepare(FakeProvider):
    async def prepare(self, request, hooks):
        self.record('prepare', request.attempt_id)
        raise DomainError('provider_preflight_failed')


class TransientExecute(FakeProvider):
    async def execute(self, prepared, hooks):
        self.record('execute', prepared.request.attempt_id)
        raise DomainError('vk_http_failed')


class NeedsAuthPrepare(FakeProvider):
    async def prepare(self, request, hooks):
        self.record('prepare', request.attempt_id)
        raise DomainError('needs_auth')


class WorkerReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1_800_000_000.0
        self.store = Store(self.root / 'ledger.sqlite', clock=lambda: self.now)
        token = self.store.create_principal('t', 'owner', owner=True)
        self.actor = self.store.authenticate(token)
        for provider, target in (('telegram', '-1001234567890'), ('vk', '-123'), ('max', '-234')):
            self.store.add_connection(self.actor, provider, provider, account_type='fake')
            self.store.bind(self.actor, 'owner', provider, provider, target)
        self.app = Application(self.store)
        self.tg = FakeProvider(self.root / 'tg.sqlite', 'telegram', clock=lambda: self.now)
        self.vk = NativeIdReadbackDown(self.root / 'vk.sqlite', 'vk', clock=lambda: self.now)
        self.mx = FakeProvider(self.root / 'max.sqlite', 'max', clock=lambda: self.now)

    def worker(self, vk=None, mx=None):
        return Worker(self.store, {'telegram': self.tg, 'vk': vk or self.vk, 'max': mx or self.mx})

    async def publish(self, to=('telegram', 'vk'), delivery=None, key=None, text='Exact intended publication'):
        args = {'to': list(to), 'content': {'text': text}}
        if delivery is not None:
            args['delivery'] = delivery
        if key:
            args['request_key'] = key
        return await self.app.call(self.actor, 'vibepublish_publish', args)

    def receipt(self, accepted):
        return self.store.receipt(self.actor, accepted['operation_id'])

    def attempt(self, accepted, provider='vk'):
        with self.store.connection() as db:
            return dict(db.execute('SELECT * FROM attempts WHERE operation_id=? AND provider=?',
                                   (accepted['operation_id'], provider)).fetchone())

    async def test_known_id_readback_timeout_retries_only_reconcile_then_success(self):
        accepted = await self.publish()
        self.assertTrue(await self.worker().run_once())
        midway = self.receipt(accepted)
        self.assertFalse(midway['operation_complete'])
        self.assertEqual(self.tg.count('effect'), 1)
        self.assertEqual(self.vk.count('effect'), 1)
        self.assertEqual(self.vk.count('execute'), 1)
        self.vk.fail_read = False
        self.now += 3
        self.assertTrue(await self.worker().run_once())
        final = self.receipt(accepted)
        self.assertTrue(final['operation_complete'], final)
        self.assertEqual(final['state'], 'verified', final)
        self.assertEqual(self.tg.count('effect'), 1)
        self.assertEqual(self.tg.count('execute'), 1)
        self.assertEqual(self.vk.count('effect'), 1)
        self.assertEqual(self.vk.count('execute'), 1)
        self.assertEqual(self.vk.count('reconcile'), 1)

    async def test_known_id_readback_fails_until_deadline_is_success_with_link(self):
        accepted = await self.publish()
        await self.worker().run_once()
        for offset in (3, 310, 620, 901):
            self.now = 1_800_000_000.0 + offset
            await self.worker().run_once()
        result = self.receipt(accepted)
        self.assertEqual(result['state'], 'verified', result)
        vk = next(r for r in result['deliveries'] if r['provider'] == 'vk')
        self.assertEqual(vk['url'], 'https://vk.com/wall-123_456')
        self.assertTrue(any('native ID 456' in e['message'] for e in result['progress']['events']))
        self.assertEqual((await self.publish())['state'], 'verified')
        self.assertEqual(self.vk.count('effect'), 1)
        self.assertEqual(self.tg.count('effect'), 1)
        self.assertFalse(await self.worker().run_once())

    async def test_dispatched_without_id_finishes_with_refusal_and_no_second_send(self):
        vk = NoNativeId(self.root / 'no-id.sqlite', 'vk', clock=lambda: self.now)
        accepted = await self.publish(to=('vk',))
        await self.worker(vk=vk).run_once()
        self.now += 901
        await self.worker(vk=vk).run_once()
        result = self.receipt(accepted)
        self.assertTrue(result['operation_complete'], result)
        self.assertEqual(result['state'], 'blocked', result)
        self.assertEqual(result['deliveries'][0]['missing_checks'], ['publication_unconfirmed'])
        self.assertEqual(vk.count('execute'), 1)
        self.assertEqual(vk.count('reconcile'), 0)
        self.assertNotEqual(result['next_action'], 'review_outcome')

    async def test_transient_before_dispatch_exhausts_fixed_horizon(self):
        vk = TransientExecute(self.root / 'transient.sqlite', 'vk', clock=lambda: self.now)
        accepted = await self.publish(to=('vk',))
        self.assertEqual(self.attempt(accepted)['dispatched'], 0)
        deadline = self.attempt(accepted)['operation_id']
        await self.worker(vk=vk).run_once()
        first = self.receipt(accepted)
        self.assertFalse(first['operation_complete'])
        self.now += 901
        await self.worker(vk=vk).run_once()
        final = self.receipt(accepted)
        self.assertTrue(final['operation_complete'], final)
        self.assertEqual(final['state'], 'blocked')
        self.assertEqual(vk.count('effect'), 0)
        self.assertEqual(vk.count('execute'), 1)
        with self.store.connection() as db:
            op = db.execute('SELECT deadline,created FROM operations WHERE id=?',(deadline,)).fetchone()
            self.assertEqual(op['deadline'] - op['created'], 120)

    async def test_transient_max_prepare_does_not_block_telegram_or_vk(self):
        mx = TransientPrepare(self.root / 'max-down.sqlite', 'max', clock=lambda: self.now)
        vk = FakeProvider(self.root / 'vk-good.sqlite', 'vk', clock=lambda: self.now)
        accepted = await self.publish(to=('telegram','vk','max'))
        await self.worker(vk=vk, mx=mx).run_once()
        result = self.receipt(accepted)
        self.assertFalse(result['operation_complete'])
        self.assertEqual(self.tg.count('effect'), 1)
        self.assertEqual(vk.count('effect'), 1)
        self.assertEqual(mx.count('effect'), 0)
        self.assertEqual(mx.count('prepare'), 1)
        self.now += 901
        await self.worker(vk=vk, mx=mx).run_once()
        final = self.receipt(accepted)
        self.assertEqual(final['state'], 'partial', final)
        self.assertEqual(self.tg.count('effect'), 1)
        self.assertEqual(vk.count('effect'), 1)

    async def test_permanent_auth_failure_does_not_retry(self):
        vk = NeedsAuthPrepare(self.root / 'auth.sqlite', 'vk', clock=lambda: self.now)
        accepted = await self.publish(to=('vk',))
        await self.worker(vk=vk).run_once()
        result = self.receipt(accepted)
        self.assertTrue(result['operation_complete'])
        self.assertEqual(result['deliveries'][0]['missing_checks'], ['needs_auth'])
        self.assertNotEqual(result['next_action'], 'review_outcome')
        self.now += 100
        self.assertFalse(await self.worker(vk=vk).run_once())
        self.assertEqual(vk.count('prepare'), 1)

    async def test_unknown_attempt_never_blocks_other_publication_same_connection(self):
        vk = NoNativeId(self.root / 'vk-mixed.sqlite', 'vk', clock=lambda: self.now)
        first = await self.publish(to=('vk',), key='first')
        await self.worker(vk=vk).run_once()
        # A later publication with the same connection must not see a historical fence.
        good = FakeProvider(self.root / 'vk-good-next.sqlite', 'vk', clock=lambda: self.now)
        second = await self.publish(to=('vk',), key='second', text='Second independent publication')
        await self.worker(vk=good).run_once()
        self.assertEqual(self.receipt(second)['state'], 'verified')
        self.assertEqual(good.count('effect'), 1)
        self.assertEqual(vk.count('execute'), 1)
        self.assertEqual(self.receipt(first)['state'], 'running')

    async def test_held_lane_expires_before_any_provider_effect(self):
        accepted = await self.publish(to=('vk',))
        with self.store.tx() as db:
            db.execute('UPDATE operations SET created=? WHERE id=?',
                       (self.now - 899.91, accepted['operation_id']))
        lane_owner = self.worker()
        wk = self.worker(vk=FakeProvider(self.root / 'vk-lane.sqlite', 'vk', clock=lambda: self.now))
        async with lane_owner.lane('vk'):
            self.assertTrue(await asyncio.wait_for(wk.run_once(), timeout=2))
        self.assertEqual(wk.adapters['vk'].count('effect'), 0)
        self.now += 1
        await wk.run_once()
        result = self.receipt(accepted)
        self.assertEqual(result['state'], 'blocked', result)
        self.assertEqual(result['deliveries'][0]['missing_checks'], ['command_expired'])
        self.assertEqual(wk.adapters['vk'].count('execute'), 0)


if __name__ == '__main__':
    unittest.main()
