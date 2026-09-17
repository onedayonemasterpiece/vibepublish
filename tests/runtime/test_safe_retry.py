"""Explicit retries are possible only before the original durable dispatch boundary."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from adapters.fake import FakeProvider
from social_operations.domain import DomainError, OutcomeUnknown, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class BeforeEffectBlocked(FakeProvider):
    blocked = False
    lose_receipt = False
    async def execute(self, prepared, hooks):
        if self.blocked:
            raise DomainError('observed_dialog_heading_changed')
        result = await super().execute(prepared, hooks)
        if self.lose_receipt:
            raise OutcomeUnknown('receipt_lost')
        return result


class SafeRetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1800000000.0
        self.store = Store(self.root/'ledger.sqlite', clock=lambda: self.now)
        self.token = self.store.create_principal('t', 'owner', owner=True)
        self.actor = self.store.authenticate(self.token)
        self.store.add_connection(self.actor, 'max', 'max', account_type='fake')
        self.binding = self.store.bind(self.actor, 'owner', 'max', 'max', 'target')
        self.provider = BeforeEffectBlocked(self.root/'remote.sqlite', 'max', clock=lambda: self.now)
        self.worker = Worker(self.store, {'max':self.provider})
        self.app = Application(self.store)

    async def call(self, method, args, actor=None):
        return await self.app.call(actor or self.actor, 'vibepublish_'+method, args)

    async def blocked_edit(self, targets=None):
        original = await self.call('publish', {'to':targets or ['max'], 'content':{'text':'Original'}})
        await self.worker.run_once()
        self.provider.blocked = True
        edit = await self.call('publication_update', {'publication_id':original['resource_id'], 'expected_revision':1,
            'change':{'kind':'edit','content':{'text':'Edited'}}, 'request_key':'edit'})
        await self.worker.run_once()
        return edit

    def retry_args(self, receipt, destinations=None):
        return {'publication_id':receipt['resource_id'], 'expected_revision':receipt['revision'],
                'change':{'kind':'retry_failed','destinations':destinations or ['max']}, 'request_key':'retry'}

    async def test_failed_edit_resumes_original_attempt_plan_revision_and_native_identity(self):
        edit = await self.blocked_edit()
        with self.store.connection() as db:
            before = dict(db.execute('SELECT * FROM attempts WHERE operation_id=?', (edit['operation_id'],)).fetchone())
        assert before['dispatched'] == 0 and before['state'] == 'blocked'
        self.provider.blocked = False
        retry = await self.call('publication_update', self.retry_args(edit))
        self.assertEqual(retry['operation_id'], edit['operation_id'])
        self.assertEqual(retry['revision'], 2)
        await self.worker.run_once()
        result = self.store.receipt(self.actor, edit['operation_id'])
        self.assertEqual(result['state'], 'verified')
        self.assertEqual(result['deliveries'][0]['observed'], 'published')
        with self.store.connection() as db:
            after = dict(db.execute('SELECT * FROM attempts WHERE id=?',(before['id'],)).fetchone())
            self.assertEqual(after['plan'], before['plan'])
            self.assertEqual(after['plan_digest'], before['plan_digest'])
            self.assertEqual(json.loads(after['checkpoint'])['remote']['native_id'], json.loads(before['plan'])['existing']['native_id'])
            self.assertEqual(db.execute('SELECT count(*) FROM operations').fetchone()[0], 2)
        self.assertEqual(self.provider.count('effect'), 2)  # Publish + one edit.
        self.assertEqual((await self.call('publication_update', self.retry_args(edit)))['state'], 'verified')
        self.assertFalse(await self.worker.run_once())

    async def test_same_key_can_retry_another_predispatch_failure_but_never_unknown(self):
        edit = await self.blocked_edit()
        args = self.retry_args(edit)
        await self.call('publication_update', args)
        await self.worker.run_once()
        self.assertEqual(self.store.receipt(self.actor, edit['operation_id'])['state'], 'blocked')
        self.provider.blocked, self.provider.lose_receipt = False, True
        await self.call('publication_update', args)
        await self.worker.run_once()
        result = await self.call('publication_update', args)
        self.assertEqual(result['error']['code'], 'retry_not_proven_safe')
        self.assertEqual(self.provider.count('effect'), 2)

    async def test_expired_immediate_deadline_refreshes_but_frozen_native_time_does_not(self):
        edit = await self.blocked_edit()
        self.now += 1000
        self.provider.blocked = False
        await self.call('publication_update', self.retry_args(edit))
        await self.worker.run_once()
        self.assertEqual(self.store.receipt(self.actor, edit['operation_id'])['state'], 'verified')
        scheduled = await self.call('publish', {'to':['max'],'content':{'text':'Future'},
            'delivery':{'kind':'at','at':timestamp(self.now+300)},'request_key':'future'})
        self.provider.blocked = True
        await self.worker.run_once()
        self.now += 400
        self.provider.blocked = False
        args=self.retry_args(scheduled);args['request_key']='retry-expired-native'
        await self.call('publication_update', args)
        await self.worker.run_once()
        result=self.store.receipt(self.actor,scheduled['operation_id'])
        self.assertEqual(result['state'],'blocked')
        self.assertEqual(result['deliveries'][0]['missing_checks'],['native_lead_time'])
        self.assertEqual(self.provider.count('effect'),2)

    async def test_partial_success_sibling_and_receipt_are_preserved(self):
        self.store.add_connection(self.actor,'telegram','telegram',account_type='fake')
        self.store.bind(self.actor,'owner','telegram','telegram','other')
        other=FakeProvider(self.root/'remote.sqlite','telegram',clock=lambda:self.now)
        self.worker.adapters['telegram']=other
        edit=await self.blocked_edit(['max','telegram'])
        before=self.store.receipt(self.actor,edit['operation_id'])
        self.assertEqual(before['state'],'partial')
        sibling=next(d for d in before['deliveries'] if d['provider']=='telegram')
        self.provider.blocked=False
        await self.call('publication_update',self.retry_args(edit))
        await self.worker.run_once()
        after=self.store.receipt(self.actor,edit['operation_id'])
        self.assertEqual(after['state'],'verified')
        self.assertEqual(next(d for d in after['deliveries'] if d['provider']=='telegram'),sibling)
        self.assertEqual(other.count('effect'),2)

    async def test_revision_actor_and_binding_epoch_guards(self):
        edit=await self.blocked_edit()
        args=self.retry_args(edit)
        self.assertEqual((await self.call('publication_update',{**args,'expected_revision':1}))['error']['code'],'revision_conflict')
        self.assertEqual((await self.call('publication_update',self.retry_args(edit,['not-bound'])))['error']['code'],'retry_destination_mismatch')
        self.store.revoke_binding(self.actor,self.binding)
        self.assertEqual((await self.call('publication_update',args,self.store.authenticate(self.token)))['error']['code'],'access_revoked')
        self.assertEqual(self.provider.count('effect'),1)

    async def test_revocation_after_retry_admission_prevents_effect(self):
        edit=await self.blocked_edit()
        await self.call('publication_update',self.retry_args(edit))
        self.store.revoke_binding(self.actor,self.binding)
        self.provider.blocked=False
        await self.worker.run_once()
        self.assertEqual(self.provider.count('effect'),1)

    async def test_external_change_is_not_overwritten_and_dispatched_success_cannot_retry(self):
        edit=await self.blocked_edit()
        with self.provider.db() as db:
            row=db.execute('SELECT id,snapshot FROM items').fetchone()
            snapshot=json.loads(row['snapshot']);snapshot['text']='Externally changed';snapshot['fingerprint']='external'
            db.execute('UPDATE items SET snapshot=? WHERE id=?',(json.dumps(snapshot),row['id']))
        self.provider.blocked=False
        await self.call('publication_update',self.retry_args(edit))
        await self.worker.run_once()
        self.assertEqual(self.store.receipt(self.actor,edit['operation_id'])['state'],'blocked')
        self.assertEqual(self.provider.count('effect'),1)
        original=await self.call('publish',{'to':['max'],'content':{'text':'Second'},'request_key':'second'})
        await self.worker.run_once()
        args=self.retry_args(original);args['request_key']='cannot-repeat-success'
        self.assertEqual((await self.call('publication_update',args))['error']['code'],'retry_not_proven_safe')
