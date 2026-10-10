"""MAX preparation and post-dispatch observation have separate bounded budgets."""
import asyncio
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from adapters.fake import FakeProvider
from social_operations.domain import OutcomeUnknown, timestamp
from social_operations.worker import Worker
from tests.runtime import test_safe_retry as fixtures

_advance=None

async def elapse(seconds):
    if _advance is not None:await _advance(seconds)

class TimedProvider(FakeProvider):
    pre=0
    post=0
    mode=None
    async def execute(self,prepared,hooks):
        await elapse(self.pre)
        result=await super().execute(prepared,hooks)
        if self.mode=='missing_receipt':raise OutcomeUnknown('missing_receipt')
        if self.mode=='cancel':raise asyncio.CancelledError()
        await elapse(self.post)
        return result

@contextmanager
def short_budgets():
    """Deterministic phase clock, retaining actual asyncio timeout cancellation."""
    global _advance
    original=asyncio.timeout
    budgets=[];active=[];logical_now=0.0
    class Budget:
        def __init__(self,seconds):
            self.seconds=seconds;self.resets=[]
            self.deadline=logical_now+seconds
            self.inner=original(None)
            budgets.append(self)
        async def __aenter__(self):
            await self.inner.__aenter__()
            active.append(self)
            return self
        async def __aexit__(self,*args):
            active.remove(self)
            return await self.inner.__aexit__(*args)
        def reschedule(self,deadline):
            seconds=deadline-asyncio.get_running_loop().time()
            self.resets.append(seconds)
            self.deadline=logical_now+seconds
        def expire(self):
            self.inner.reschedule(asyncio.get_running_loop().time()-1)
    async def advance(seconds):
        nonlocal logical_now
        logical_now+=seconds
        for budget in active:
            if logical_now>=budget.deadline:budget.expire()
        await asyncio.sleep(0)
    previous=_advance;_advance=advance
    try:
        with patch('social_operations.worker.asyncio.timeout',Budget):
            yield budgets
    finally:_advance=previous

class MaxPhaseBudgetTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.SafeRetryTests.setUp
    call=fixtures.SafeRetryTests.call

    def timed(self):
        self.provider=TimedProvider(self.root/'timed.sqlite','max',clock=lambda:self.now)
        self.worker=Worker(self.store,{'max':self.provider})

    async def scheduled(self):
        return await self.call('publish',{'to':['max'],'content':{'text':'Future'},
            'delivery':{'kind':'at','at':timestamp(self.now+3600)}})

    def result(self,receipt):
        return self.store.receipt(self.actor,receipt['operation_id'])

    def attempt(self,receipt):
        with self.store.connection() as db:
            return dict(db.execute('SELECT * FROM attempts WHERE operation_id=?',(receipt['operation_id'],)).fetchone())

    async def test_publish_and_reschedule_receive_one_post_dispatch_budget(self):
        for action in ('publish','reschedule'):
            with self.subTest(action=action):
                self.timed()
                receipt=await self.scheduled()
                if action=='reschedule':
                    await self.worker.run_once()
                    receipt=await self.call('publication_update',{'publication_id':receipt['resource_id'],
                        'expected_revision':1,'change':{'kind':'reschedule','delivery':{'kind':'at','at':timestamp(self.now+7200)}}})
                self.provider.pre=60;self.provider.post=60
                before=self.provider.count('effect')
                with short_budgets() as budgets:
                    await self.worker.run_once()
                self.assertEqual(self.result(receipt)['state'],'scheduled')
                self.assertEqual(self.provider.count('effect')-before,1)
                resets=[r for b in budgets for r in b.resets]
                self.assertEqual(len(resets),1)
                self.assertAlmostEqual(resets[0],90,delta=.02)

    async def test_preparation_expiry_never_dispatches_or_extends(self):
        self.timed();receipt=await self.scheduled();self.provider.pre=120
        with short_budgets() as budgets:await self.worker.run_once()
        self.assertEqual(self.attempt(receipt)['dispatched'],0)
        self.assertEqual(self.provider.count('effect'),0)
        self.assertFalse(any(b.resets for b in budgets))

    async def test_post_dispatch_expiry_is_still_unknown_with_one_effect(self):
        self.timed();receipt=await self.scheduled();self.provider.post=120
        with short_budgets() as budgets:await self.worker.run_once()
        self.assertEqual(self.result(receipt)['state'],'outcome_unknown')
        self.assertEqual(self.attempt(receipt)['dispatched'],1)
        self.assertEqual(self.provider.count('effect'),1)
        self.assertEqual(sum(len(b.resets) for b in budgets),1)

    async def test_missing_receipt_does_not_become_success(self):
        self.timed();receipt=await self.scheduled();self.provider.mode='missing_receipt'
        with short_budgets():await self.worker.run_once()
        self.assertEqual(self.result(receipt)['state'],'outcome_unknown')
        self.assertEqual(self.provider.count('effect'),1)

    async def test_cancellation_restart_only_observes_existing_effect(self):
        self.timed();receipt=await self.scheduled();self.provider.mode='cancel'
        with short_budgets():
            with self.assertRaises(asyncio.CancelledError):await self.worker.run_once()
        self.assertEqual(self.attempt(receipt)['dispatched'],1)
        self.provider.mode=None;self.now+=200
        with short_budgets() as budgets:await self.worker.run_once()
        self.assertEqual(self.result(receipt)['state'],'scheduled')
        self.assertEqual(self.provider.count('effect'),1)
        self.assertFalse(any(b.resets for b in budgets))

    async def test_immediate_max_is_not_extended(self):
        self.timed();receipt=await self.call('publish',{'to':['max'],'content':{'text':'Now'}})
        self.provider.pre=60;self.provider.post=60
        with short_budgets() as budgets:await self.worker.run_once()
        self.assertEqual(self.result(receipt)['state'],'outcome_unknown')
        self.assertFalse(any(b.resets for b in budgets))