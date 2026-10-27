"""Real Application/Worker keeps only bounded VK copy receipts after finish."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from adapters.port import Capability, Prepared, Observation, RemoteItem
from adapters.native import saved_checkpoint
from social_operations.assets import import_image
from social_operations.domain import canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class CopyAdapter:
    def __init__(self, malformed=False):
        self.malformed = malformed
    async def prepare(self, request, hooks):
        return Prepared(request, Capability('supported', 'fixture'))
    async def execute(self, prepared, hooks):
        r = prepared.request
        await hooks.before_effect(r.attempt_id, r.plan_digest)
        proof={'sha256':'a'*64,'size':123,'mime':'image/png','width':8,'height':8,'secret_url':'https://must-not-persist.invalid'}
        cp={'id':'8','media':['photo123_456'],'photo_proofs':[proof],
            'media_bindings':[{'ordinal':0,'saved':'photo123_456','current':'photo-241261191_789','provider_sha256':'a'*64}],
            'unknown_secret':'must-not-persist'}
        if self.malformed: cp['media_bindings'][0]['current']='photo-999_789'
        await hooks.checkpoint('vk_media_bound', saved_checkpoint(r, **cp))
        remote=RemoteItem('8','scheduled','test','f',timestamp(1000),r.scheduled_at,
                          media_hashes=tuple(a.sha256 for a in r.assets),native_target=r.native_target,
                          provider_media=('photo-241261191_789',),media_check='provider_binding')
        return Observation('provider_scheduled',(remote,))


class CopyCheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, malformed=False, provider='vk'):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        store=Store(Path(temp.name)/'db')
        actor=store.authenticate(store.create_principal('t','owner',owner=True))
        store.add_connection(actor,'vkconn',provider,account_type='fake')
        store.bind(actor,'owner','vk','vkconn','-241261191')
        image=io.BytesIO(); Image.new('RGB',(8,8),'blue').save(image,format='PNG')
        asset=import_image(store,actor,image.getvalue(),'image/png')
        app=Application(store)
        receipt=await app.call(actor,'vibepublish_publish',{'to':['vk'],'content':{'text':'test'},
            'media':[{'source':{'kind':'asset','id':asset}}], 'delivery':{'kind':'at','at':timestamp(store.clock()+3600)}})
        self.assertIn('operation_id',receipt,receipt)
        await Worker(store,{provider:CopyAdapter(malformed)}).run_once()
        with store.connection() as db:
            checkpoint=json.loads(db.execute('SELECT checkpoint FROM attempts').fetchone()[0])
        return store.receipt(actor,receipt['operation_id']),checkpoint

    async def test_native_copy_id_is_accepted_without_byte_proofs(self):
        receipt, cp = await self.run_case()
        self.assertEqual(receipt['state'], 'scheduled', receipt)
        self.assertEqual(cp['remote']['native_id'], '8')
        self.assertNotIn('provider_evidence', cp)
        self.assertNotIn('must-not-persist', canonical(cp))
        self.assertEqual(set(cp), {'remote', 'core_recovery'})

    async def test_malformed_obsolete_copy_proof_does_not_invalidate_vk_post(self):
        receipt, cp = await self.run_case(True)
        self.assertEqual(receipt['state'], 'scheduled', receipt)
        self.assertEqual(cp['remote']['native_id'], '8')
        self.assertNotIn('provider_evidence', cp)

    async def test_non_vk_final_checkpoint_never_carries_copy_proof(self):
        receipt, cp = await self.run_case(provider='telegram')
        self.assertEqual(receipt['state'], 'scheduled', receipt)
        self.assertNotIn('provider_evidence', cp)
