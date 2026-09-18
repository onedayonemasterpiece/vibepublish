"""No external effects: resolve only an exact externally removed queued object."""
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from adapters.port import ReadPage
from social_operations.domain import DomainError, canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class Reader:
    def __init__(self):
        self.calls = []
        self.collision = False
        self.queued = False
        self.cursor = None
        self.revoke = None
    async def read(self, request, hooks):
        self.calls.append(request)
        if self.revoke:
            self.revoke(); self.revoke = None
        if request.kind == 'scheduled' and self.queued:
            return ReadPage((SimpleNamespace(native_target='-241261191', namespace='scheduled', native_id='8'),))
        if request.kind == 'item' and self.collision:
            return ReadPage((object(),))
        return ReadPage((), self.cursor if request.kind == 'scheduled' else None)
    async def execute(self, *args):
        raise AssertionError('Resolution must never execute')
    async def prepare(self, *args):
        raise AssertionError('Resolution must never prepare/upload')


class UnknownResolutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/'db')
        self.token = self.store.create_principal('t', 'owner', owner=True)
        self.actor = self.store.authenticate(self.token)
        self.store.add_connection(self.actor, 'vkconn', 'vk', account_type='fake')
        self.binding = self.store.bind(self.actor, 'owner', 'vk', 'vkconn', '-241261191')
        self.app = Application(self.store); self.reader = Reader(); self.worker = Worker(self.store, {'vk': self.reader})

    async def seed(self):
        receipt = await self.app.call(self.actor, 'vibepublish_publish', {'to':['vk'], 'content':{'text':'test'}, 'delivery':{'kind':'at', 'at':timestamp(self.store.clock()+172800)}})
        with self.store.tx() as db:
            row = dict(db.execute('SELECT * FROM attempts WHERE operation_id=?', (receipt['operation_id'],)).fetchone())
            cp = canonical({'transition':'vk_response', 'adapter':{'version':1, 'attempt':row['id'], 'plan':row['plan_digest'], 'target':'-241261191','id':'8'}})
            db.execute("UPDATE attempts SET state='outcome_unknown', dispatched=1, checkpoint=? WHERE id=?", (cp,row['id']))
            db.execute("UPDATE operations SET state='outcome_unknown',complete=1,work_state='done' WHERE id=?", (receipt['operation_id'],))
        self.old = row['id']; self.old_op=receipt['operation_id']
        self.args={'publication_id':receipt['resource_id'],'expected_revision':1,'change':{'kind':'reconcile_removed','attempt_id':self.old},'request_key':'resolve-8'}
        with self.store.connection() as db:
            self.snapshot=tuple(db.execute('SELECT * FROM attempts WHERE id=?',(self.old,)).fetchone())
        return receipt

    async def run_resolution(self):
        accepted=await self.app.call(self.actor, 'vibepublish_publication_update', self.args)
        self.assertIn('operation_id', accepted, accepted)
        await self.worker.run_once()
        return self.store.receipt(self.actor, accepted['operation_id'])

    async def test_absence_proof_preserves_original_and_replays(self):
        await self.seed(); result=await self.run_resolution()
        self.assertEqual(result['state'],'verified',result)
        self.assertIn('Externally removed',result['message'])
        self.assertEqual([(r.kind,r.namespace,r.native_item) for r in self.reader.calls], [('scheduled',None,None),('item','published','8')])
        with self.store.connection() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM attempts WHERE id=?',(self.old,)).fetchone()), self.snapshot)
            proof=json.loads(db.execute('SELECT proof FROM attempt_resolutions').fetchone()[0])
            self.assertEqual(proof['native_target'],'-241261191'); self.assertTrue(proof['published_exact_absent'])
            self.assertEqual(db.execute('SELECT state FROM operations WHERE id=?',(self.old_op,)).fetchone()[0],'outcome_unknown')
        replay=await self.app.call(self.actor,'vibepublish_publication_update',self.args)
        self.assertEqual(replay['operation_id'],result['operation_id']); self.assertFalse(await self.worker.run_once())

    async def test_published_collision_keeps_quarantine(self):
        await self.seed(); self.reader.collision=True
        result=await self.run_resolution(); self.assertEqual(result['state'],'blocked')
        with self.store.connection() as db: self.assertEqual(db.execute('SELECT count(*) FROM attempt_resolutions').fetchone()[0],0)

    async def test_incomplete_queue_keeps_quarantine(self):
        await self.seed(); self.reader.cursor='same'
        result=await self.run_resolution(); self.assertEqual(result['error']['code'],'resolution_queue_incomplete')
        self.assertEqual(len(self.reader.calls),2)

    async def test_missing_checkpoint_is_not_accepted(self):
        await self.seed()
        with self.store.tx() as db: db.execute("UPDATE attempts SET checkpoint='{}' WHERE id=?",(self.old,))
        result=await self.app.call(self.actor,'vibepublish_publication_update',self.args)
        self.assertEqual(result['error']['code'],'resolution_checkpoint_invalid'); self.assertFalse(self.reader.calls)

    async def test_epoch_revoked_during_read_cannot_commit(self):
        await self.seed(); self.reader.revoke=lambda:self.store.revoke_binding(self.actor,self.binding)
        with self.assertRaises(DomainError):
            await self.run_resolution()
        with self.store.connection() as db: self.assertEqual(db.execute('SELECT count(*) FROM attempt_resolutions').fetchone()[0],0)

    async def test_nonowner_and_foreign_attempt_denied(self):
        await self.seed()
        actor=self.store.authenticate(self.store.create_principal('t','other'))
        result=await self.app.call(actor,'vibepublish_publication_update',self.args)
        self.assertEqual(result['error']['code'],'access_denied')
        other_owner=self.store.authenticate(self.store.create_principal('other','foreign',owner=True))
        result=await self.app.call(other_owner,'vibepublish_publication_update',self.args)
        self.assertEqual(result['error']['code'],'resolution_not_eligible')

    async def test_resolved_publication_is_not_a_new_publish_authority(self):
        await self.seed(); await self.run_resolution()
        args={**self.args, 'expected_revision':2, 'request_key':'edit-removed', 'change':{'kind':'edit','content':{'text':'no'}}}
        result=await self.app.call(self.actor,'vibepublish_publication_update',args)
        self.assertEqual(result['error']['code'],'remote_item_not_bound')

    async def test_corrupted_checkpoint_binding_is_rejected(self):
        await self.seed()
        with self.store.tx() as db:
            checkpoint=json.loads(db.execute('SELECT checkpoint FROM attempts WHERE id=?',(self.old,)).fetchone()[0])
            checkpoint['adapter']['plan']='tampered'
            db.execute('UPDATE attempts SET checkpoint=? WHERE id=?',(canonical(checkpoint),self.old))
        result=await self.app.call(self.actor,'vibepublish_publication_update',self.args)
        self.assertEqual(result['error']['code'],'resolution_checkpoint_invalid')

    async def test_queued_object_keeps_quarantine(self):
        await self.seed(); self.reader.queued=True
        result=await self.run_resolution()
        self.assertEqual(result['error']['code'],'resolution_object_present')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attempt_resolutions').fetchone()[0],0)

    async def test_only_exact_attempt_excluded(self):
        await self.seed(); resolved=self.old; await self.run_resolution()
        second=await self.app.call(self.actor,'vibepublish_publish',{'to':['vk'],'content':{'text':'another'}})
        with self.store.tx() as db:
            db.execute("UPDATE attempts SET dispatched=1,state='outcome_unknown' WHERE operation_id=?",(second['operation_id'],))
            unresolved=[r[0] for r in db.execute("SELECT a.id FROM attempts a WHERE a.dispatched=1 AND a.state NOT IN ('verified','scheduled','cancelled') AND NOT EXISTS (SELECT 1 FROM attempt_resolutions z WHERE z.attempt_id=a.id)")]
        self.assertEqual(len(unresolved),1); self.assertNotIn(resolved,unresolved)

    async def test_fresh_owner_cannot_resolve_previous_actor_epoch(self):
        await self.seed()
        with self.store.tx() as db:
            db.execute("UPDATE principals SET epoch=epoch+1 WHERE id='owner' AND tenant_id='t'")
        fresh = self.store.authenticate(self.token)
        self.assertGreater(fresh.epoch, self.actor.epoch)
        result = await self.app.call(fresh, 'vibepublish_publication_update', self.args)
        self.assertEqual(result['error']['code'], 'access_revoked')
        self.assertFalse(self.reader.calls)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attempt_resolutions').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT revision FROM publications WHERE id=?', (self.args['publication_id'],)).fetchone()[0], 1)
            self.assertEqual(tuple(db.execute('SELECT * FROM attempts WHERE id=?', (self.old,)).fetchone()), self.snapshot)

    async def seed_lifecycle(self, action, existing_changes=None):
        await self.seed()
        existing={'native_id':'8','native_target':'-241261191','namespace':'scheduled',
                  'text':'test','fingerprint':'fixture','observed_at':timestamp(self.store.clock()),
                  'scheduled_at':timestamp(self.store.clock()+172800),'media_hashes':[]}
        existing.update(existing_changes or {})
        with self.store.tx() as db:
            db.execute("UPDATE attempts SET state='scheduled',checkpoint=? WHERE id=?",(canonical({'remote':existing}),self.old))
            db.execute("UPDATE operations SET state='scheduled' WHERE id=?",(self.old_op,))
        change={'kind':action,'content':{'text':'edited'}} if action == 'edit' else {'kind':action,'delivery':{'kind':'at','at':timestamp(self.store.clock()+259200)}}
        accepted=await self.app.call(self.actor,'vibepublish_publication_update',{
            'publication_id':self.args['publication_id'],'expected_revision':1,'change':change,'request_key':'lifecycle'})
        self.assertIn('operation_id',accepted,accepted)
        with self.store.tx() as db:
            row=dict(db.execute('SELECT * FROM attempts WHERE operation_id=?',(accepted['operation_id'],)).fetchone())
            cp=canonical({'transition':'vk_response','adapter':{'version':1,'attempt':row['id'],'plan':row['plan_digest'],'target':'-241261191','id':'8'}})
            db.execute("UPDATE attempts SET state='outcome_unknown',dispatched=1,checkpoint=? WHERE id=?",(cp,row['id']))
            db.execute("UPDATE operations SET state='outcome_unknown',complete=1,work_state='done' WHERE id=?",(accepted['operation_id'],))
        self.old=row['id'];self.old_op=accepted['operation_id']
        self.args.update(expected_revision=2,change={'kind':'reconcile_removed','attempt_id':self.old})
        with self.store.connection() as db:
            self.snapshot=tuple(db.execute('SELECT * FROM attempts WHERE id=?',(self.old,)).fetchone())

    async def test_scheduled_edit_absence_resolves_without_repeating_edit(self):
        await self.seed_lifecycle('edit');result=await self.run_resolution()
        self.assertEqual(result['state'],'verified',result)
        with self.store.connection() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM attempts WHERE id=?',(self.old,)).fetchone()),self.snapshot)
            self.assertEqual(db.execute('SELECT state FROM operations WHERE id=?',(self.old_op,)).fetchone()[0],'outcome_unknown')

    async def test_scheduled_reschedule_absence_resolves(self):
        await self.seed_lifecycle('reschedule');result=await self.run_resolution()
        self.assertEqual(result['state'],'verified',result)

    async def test_lifecycle_existing_id_must_match_response(self):
        await self.seed_lifecycle('edit',{'native_id':'9'})
        result=await self.app.call(self.actor,'vibepublish_publication_update',self.args)
        self.assertEqual(result['error']['code'],'resolution_not_eligible');self.assertFalse(self.reader.calls)

    async def test_lifecycle_existing_namespace_must_be_scheduled(self):
        await self.seed_lifecycle('edit',{'namespace':'published'})
        result=await self.app.call(self.actor,'vibepublish_publication_update',self.args)
        self.assertEqual(result['error']['code'],'resolution_not_eligible');self.assertFalse(self.reader.calls)

    async def test_lifecycle_existing_target_must_match_response(self):
        await self.seed_lifecycle('edit',{'native_target':'-999'})
        result=await self.app.call(self.actor,'vibepublish_publication_update',self.args)
        self.assertEqual(result['error']['code'],'resolution_not_eligible');self.assertFalse(self.reader.calls)
