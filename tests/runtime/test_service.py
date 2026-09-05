"""Executable core acceptance: actual SQLite, processes, provider state and faults."""
from __future__ import annotations
import asyncio
import concurrent.futures
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from PIL import Image
from adapters.fake import FakeProvider
from adapters.port import UnavailableAdapter
from social_operations.assets import import_image
from social_operations.domain import DomainError, canonical, digest, parse_source, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root/'ledger.sqlite')
        self.token = self.store.create_principal('tenant', 'owner', owner=True)
        self.actor = self.store.authenticate(self.token)
        self.bindings = {}
        self.providers = {}
        for p in ('telegram', 'vk', 'max'):
            self.store.add_connection(self.actor, 'conn_'+p, p, account_type='fake', shared=True)
            self.bindings[p] = self.store.bind(self.actor, 'owner', p, 'conn_'+p, 'target_'+p)
            self.providers[p] = FakeProvider(self.root/'remote.sqlite', p)
        self.app = Application(self.store)
        self.worker = Worker(self.store, self.providers)

    async def call(self, tool, args, actor=None):
        return await self.app.call(actor or self.actor, 'vibepublish_'+tool, args)

    async def publish(self, **kwargs):
        return await self.call('publish', {'to': ['telegram'], 'content': {'text': 'Fixture'}, **kwargs})

    def result(self, receipt):
        return self.store.receipt(self.actor, receipt['operation_id'])

    def scheduled(self, seconds=3600):
        return {'kind': 'at', 'at': timestamp(time.time()+seconds)}

    async def test_profile_key_replay_is_atomic_and_does_not_increment_revision(self):
        args = {'command': {'kind': 'profile_update', 'alias': 'telegram',
                'expected_revision': 0, 'profile': {'notes': 'Fixture'}}, 'request_key': 'profile-once'}
        first = await self.call('destinations', args)
        second = await self.call('destinations', args)
        self.assertEqual(first['operation_id'], second['operation_id'])
        changed = json.loads(json.dumps(args)); changed['command']['profile']['notes'] = 'Different'
        self.assertEqual((await self.call('destinations', changed))['error']['code'], 'idempotency_conflict')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT revision FROM profiles').fetchone()[0], 1)
        no_key = {'command': args['command']}
        self.assertEqual((await self.call('destinations', no_key))['error']['code'], 'profile_revision_conflict')

    async def test_history_cursor_is_not_silently_ignored(self):
        result = await self.call('read', {'query': {'kind': 'history'}, 'cursor': 'guessed'})
        self.assertEqual(result['error']['code'], 'history_cursor_not_enabled')
        self.assertNotIn('operation_id', result)

    async def test_accepted_receipt_precedes_provider_and_restart_preserves_result(self):
        start = time.monotonic()
        r = await self.publish(to=['telegram', 'vk', 'max'], delivery=self.scheduled())
        self.assertLess(time.monotonic()-start, 2)
        self.assertEqual(r['state'], 'accepted')
        self.assertFalse(r['operation_complete'])
        self.assertTrue(all(p.count('effect') == 0 for p in self.providers.values()))
        await Worker(Store(self.store.path), self.providers).run_once()
        done = Application(Store(self.store.path))
        result = await done.call(self.actor, 'vibepublish_status', {'ids': [r['operation_id']]})
        receipt = result['receipts'][0]
        self.assertEqual(receipt['state'], 'scheduled')
        self.assertTrue(receipt['operation_complete'])
        self.assertEqual([d['observed'] for d in receipt['deliveries']], ['provider_scheduled']*3)
        self.assertFalse(await self.worker.run_once())
        self.assertTrue(all(p.count('effect') == 1 for p in self.providers.values()))

    async def test_idempotency_replay_and_conflict(self):
        r = await self.publish(request_key='one')
        self.assertEqual(r['operation_id'], (await self.publish(request_key='one'))['operation_id'])
        self.assertEqual(r['operation_id'], (await self.publish(request_key='two'))['operation_id'])
        conflict = await self.publish(request_key='one', content={'text': 'Different'})
        self.assertEqual(conflict['error']['code'], 'idempotency_conflict')
        self.assertNotIn('operation_id', conflict)
        await self.worker.run_once()
        self.assertEqual(self.providers['telegram'].count('effect'), 1)
        repeated = await self.publish(request_key='explicit-repeat', repeat_of=r['operation_id'])
        self.assertNotEqual(repeated['operation_id'], r['operation_id'])
        await self.worker.run_once()
        self.assertEqual(self.providers['telegram'].count('effect'), 2)

    async def test_sqlite_concurrent_identity_is_one_operation(self):
        def submit(_):
            store = Store(self.store.path)
            return asyncio.run(Application(store).call(store.authenticate(self.token), 'vibepublish_publish',
                {'to': ['telegram'], 'content': {'text': 'Concurrent'}, 'request_key': 'race'}))
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            receipts = list(pool.map(submit, range(12)))
        self.assertEqual(len({r['operation_id'] for r in receipts}), 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM operations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM attempts').fetchone()[0], 1)

    async def test_frozen_set_members_replay_precedes_reresolution(self):
        await self.call('destinations', {'command': {'kind': 'set_put', 'alias': 'all', 'label': 'All', 'expected_revision': 0, 'members': ['telegram']}})
        r = await self.publish(to=['all'], request_key='frozen')
        await self.call('destinations', {'command': {'kind': 'set_put', 'alias': 'all', 'label': 'All', 'expected_revision': 1, 'members': ['vk']}})
        again = await self.publish(to=['all'], request_key='frozen')
        self.assertEqual(again['operation_id'], r['operation_id'])
        await self.worker.run_once()
        self.assertEqual(self.providers['telegram'].count('effect'), 1)
        self.assertEqual(self.providers['vk'].count('effect'), 0)

    async def test_profile_cas_and_stale_routing_before_admission(self):
        bootstrap = await self.call('get_started', {})
        args = {'command': {'kind': 'profile_update', 'alias': 'telegram', 'expected_revision': 0,
                           'profile': {'usage': 'primary', 'purpose': 'Концерты', 'notes': 'Сохранять источник', 'selection': 'agent_may_choose'}}}
        r = await self.call('destinations', args)
        self.assertEqual(r['destinations'][0]['alias'], 'telegram')
        bad = await self.call('destinations', args)
        self.assertEqual(bad['error']['code'], 'profile_revision_conflict')
        stale = await self.publish(routing_revision=bootstrap['routing_revision'])
        self.assertEqual(stale['error']['code'], 'routing_stale')
        self.assertEqual(self.providers['telegram'].count('effect'), 0)

    async def test_partial_progress_does_not_wait_for_max(self):
        self.providers['max'].gate = asyncio.Event()
        r = await self.publish(to=['telegram', 'vk', 'max'])
        running = asyncio.create_task(self.worker.run_once())
        try:
            async with asyncio.timeout(3):
                cursor = r['progress']['cursor']
                while True:
                    partial = (await self.call('status', {'ids': [r['operation_id']], 'after_event': cursor, 'wait_seconds': 1}))['receipts'][0]
                    cursor = partial['progress']['cursor']
                    if partial['deliveries'][0]['state'] == 'verified':
                        break
            self.assertFalse(running.done())
            self.assertFalse(partial['operation_complete'])
            self.assertEqual(partial['deliveries'][2]['state'], 'running')
            seqs = [e['seq'] for e in partial['progress']['events']]
            self.assertEqual(seqs, sorted(set(seqs)))
        finally:
            self.providers['max'].gate.set()
            await running
        self.assertEqual(self.result(r)['state'], 'verified')

    async def test_progress_wait_returns_first_new_event_not_page_fill(self):
        r = await self.publish()
        waiting = asyncio.create_task(self.call('status', {'ids': [r['operation_id']], 'after_event': r['progress']['cursor'], 'wait_seconds': 2}))
        await asyncio.sleep(.05)
        with self.store.tx() as db:
            self.store.event(db, r['operation_id'], 'validating', 'started', 'One new event')
        start = time.monotonic()
        result = await asyncio.wait_for(waiting, .5)
        self.assertLess(time.monotonic()-start, .5)
        self.assertEqual(len(result['receipts'][0]['progress']['events']), 1)

    async def test_visible_preflight_barrier_no_mutation_when_max_unconfigured(self):
        r = await self.publish(to=['telegram', 'max'])
        await Worker(self.store, {'telegram': self.providers['telegram']}).run_once()
        result = self.result(r)
        self.assertEqual(result['state'], 'blocked')
        self.assertEqual(result['error']['code'], 'needs_auth')
        self.assertEqual(self.providers['telegram'].count('effect'), 0)
        self.assertTrue(any(e['destination'] == 'telegram' for e in result['progress']['events'] if 'destination' in e))

    async def test_ordered_owned_assets_and_hash_frozen(self):
        assets = []
        for size in ((10,20), (20,10)):
            image = io.BytesIO(); Image.new('RGB', size).save(image, format='PNG')
            assets.append(import_image(self.store, self.actor, image.getvalue(), 'image/png'))
        r = await self.publish(media=[{'source': {'kind': 'asset', 'id': a}} for a in assets])
        with self.store.connection() as db:
            child = db.execute('SELECT * FROM attempts WHERE operation_id=?', (r['operation_id'],)).fetchone()
            plan = json.loads(child['plan'])
            self.assertEqual([a['ref'] for a in plan['assets']], assets)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE attempts SET plan='{}' WHERE id=?", (child['id'],))
        await self.worker.run_once()
        with self.providers['telegram'].db() as db:
            remote = json.loads(db.execute('SELECT snapshot FROM items').fetchone()[0])
        self.assertEqual(remote['media_hashes'], [a['sha256'] for a in plan['assets']])

    async def test_wrong_tenant_asset_operation_cursor_and_hidden_variant(self):
        token = self.store.create_principal('partner', 'partner', scopes={'bootstrap','publish','status','forward','destination.profile'})
        self.store.bind(self.actor, 'partner', 'telegram', 'conn_telegram', 'target_telegram')
        partner = self.store.authenticate(token)
        r = await self.publish()
        result = await self.call('status', {'ids': [r['operation_id']]}, partner)
        self.assertEqual(result['error']['code'], 'not_found')
        denied = await self.call('engage', {'command': {'kind': 'react', 'item_ref': 'item_guess', 'reaction': 'like', 'mode': 'add'}}, partner)
        self.assertEqual(denied['error']['code'], 'invalid_input')
        denied = await self.call('destinations', {'command': {'kind': 'set_put', 'alias': 'all', 'label': 'All', 'expected_revision': 0, 'members': ['telegram']}}, partner)
        self.assertEqual(denied['error']['code'], 'invalid_input')
        image = io.BytesIO(); Image.new('RGB', (10,10)).save(image, format='PNG')
        asset = import_image(self.store, self.actor, image.getvalue(), 'image/png')
        denied = await self.call('publish', {'to': ['telegram'], 'media': [{'source': {'kind': 'asset', 'id': asset}}]}, partner)
        self.assertEqual(denied['error']['code'], 'asset_not_available')
        self.assertEqual(self.providers['telegram'].count('effect'), 0)

    async def test_bound_queue_includes_external_editors_and_revocation_denies_cache(self):
        self.providers['telegram'].seed('target_telegram', 'External editor', scheduled_at=self.scheduled()['at'])
        r = await self.call('read', {'query': {'kind': 'scheduled', 'destination': 'telegram'}})
        await self.worker.run_once()
        read = self.result(r)
        self.assertEqual(read['items'][0]['text'], 'External editor')
        self.assertEqual(read['items'][0]['source'], 'provider')
        self.assertEqual(self.providers['telegram'].count('read'), 1)
        before = self.providers['telegram'].count('read')
        denied = await self.call('read', {'query': {'kind': 'scheduled', 'destination': 'unbound'}})
        self.assertEqual(denied['error']['code'], 'access_denied')
        self.assertEqual(self.providers['telegram'].count('read'), before)
        self.store.revoke_binding(self.actor, self.bindings['telegram'])
        current = self.store.authenticate(self.token)
        denied = await self.call('status', {'ids': [r['operation_id']]}, current)
        self.assertEqual(denied['error']['code'], 'access_revoked')
        self.assertEqual(self.providers['telegram'].count('effect'), 0)

    async def test_native_queue_reads_are_not_local_history(self):
        r = await self.publish(delivery=self.scheduled())
        await self.worker.run_once()
        self.providers['telegram'].seed('target_telegram', 'Added in another client', scheduled_at=self.scheduled()['at'])
        history = await self.call('read', {'query': {'kind': 'history', 'author': 'mine'}})
        self.assertEqual(len(history['items']), 1)
        self.assertEqual(history['items'][0]['source'], 'local_history')
        r = await self.call('read', {'query': {'kind': 'scheduled', 'destination': 'telegram'}})
        await self.worker.run_once()
        self.assertEqual(len(self.result(r)['items']), 2)

    async def test_in_place_reschedule_edit_cancel_remote_identity(self):
        r = await self.publish(delivery=self.scheduled())
        await self.worker.run_once()
        pub = r['resource_id']
        with self.providers['telegram'].db() as db:
            original_id = db.execute('SELECT id FROM items').fetchone()[0]
        for revision, change in enumerate(({'kind':'reschedule','delivery':self.scheduled(7200)}, {'kind':'edit','content':{'text':'Edited'}}, {'kind':'cancel'}), 1):
            r = await self.call('publication_update', {'publication_id': pub, 'expected_revision': revision, 'change': change})
            await self.worker.run_once()
            self.assertNotIn('error', self.result(r))
        self.assertEqual(self.result(r)['state'], 'cancelled')
        with self.providers['telegram'].db() as db:
            rows = db.execute('SELECT * FROM items').fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['id'], original_id)
            self.assertEqual(json.loads(rows[0]['snapshot'])['namespace'], 'cancelled')

    async def test_cancel_published_is_not_delete_and_external_edit_conflicts(self):
        r = await self.publish()
        await self.worker.run_once()
        denied = await self.call('publication_update', {'publication_id': r['resource_id'], 'expected_revision':1, 'change':{'kind':'cancel'}})
        self.assertEqual(denied['error']['code'], 'already_published')
        with self.providers['telegram'].db() as db:
            row = db.execute('SELECT * FROM items').fetchone()
            data = json.loads(row['snapshot']); data['fingerprint'] = 'changed-by-other-client'
            db.execute('UPDATE items SET snapshot=? WHERE id=?', (canonical(data), row['id']))
        update = await self.call('publication_update', {'publication_id': r['resource_id'], 'expected_revision':1, 'change':{'kind':'edit','content':{'text':'Overwrite'}}})
        await self.worker.run_once()
        self.assertEqual(self.result(update)['error']['code'], 'external_change')
        self.assertEqual(self.providers['telegram'].count('effect'), 1)

    async def test_preview_approval_cas_and_expired_native_window(self):
        r = await self.publish(mode='preview', delivery=self.scheduled(90))
        await self.worker.run_once()
        preview = self.result(r)
        self.assertEqual(preview['state'], 'needs_approval')
        self.assertEqual(self.providers['telegram'].count('effect'), 0)
        # A later approval must not silently send immediately.
        self.store.clock = lambda: time.time()+40
        denied = await self.call('publication_update', {'publication_id': r['resource_id'], 'expected_revision':1, 'change':{'kind':'approve','token':preview['review_token']}})
        self.assertEqual(denied['error']['code'], 'native_lead_time')
        self.store.clock = time.time
        approved = await self.call('publication_update', {'publication_id': r['resource_id'], 'expected_revision':1, 'change':{'kind':'approve','token':preview['review_token']}, 'request_key':'approve-one'})
        await self.worker.run_once()
        self.assertEqual(self.result(approved)['state'], 'scheduled')
        self.assertEqual(self.providers['telegram'].count('effect'), 1)

    async def test_command_expiry_never_sends_at_publication_time(self):
        r = await self.publish(delivery=self.scheduled(3600))
        self.store.clock = lambda: time.time()+4000
        await self.worker.run_once()
        self.assertEqual(self.providers['telegram'].count('effect'), 0)
        self.assertEqual(self.result(r)['state'], 'blocked')
        self.assertFalse(await self.worker.run_once())

    async def test_native_forward_attribution_cross_provider_and_private_source(self):
        source = parse_source('https://t.me/venue/123')
        self.providers['telegram'].add_source(source, public=True)
        r = await self.call('engage', {'command': {'kind':'forward','item_ref':source.canonical_url,'to':['telegram']}})
        await self.worker.run_once()
        done = self.result(r)
        self.assertEqual(done['deliveries'][0]['forward_origin']['origin_check'], 'matched')
        self.assertEqual(done['state'], 'verified')
        denied = await self.call('engage', {'command': {'kind':'forward','item_ref':source.canonical_url,'to':['telegram','vk']}})
        self.assertEqual(denied['error']['code'], 'cross_provider_forward')
        denied = await self.call('engage', {'command': {'kind':'forward','item_ref':'https://t.me/c/987/1','to':['telegram']}})
        self.assertEqual(denied['error']['code'], 'source_access_denied')
        self.assertEqual(self.providers['telegram'].count('effect'), 1)

    async def test_protected_source_and_scheduled_vk_repost_do_not_fallback(self):
        source = parse_source('https://vk.ru/wall-123_4')
        self.providers['vk'].add_source(source, public=True)
        r = await self.call('engage', {'command': {'kind':'forward','item_ref':source.canonical_url,'to':['vk'],'delivery':self.scheduled()}})
        await self.worker.run_once()
        self.assertEqual(self.result(r)['state'], 'blocked')
        self.assertEqual(self.providers['vk'].count('effect'), 0)
        self.providers['vk'].add_source(source, public=True, protected=True)
        r = await self.call('engage', {'command': {'kind':'forward','item_ref':source.canonical_url,'to':['vk']}})
        await self.worker.run_once()
        self.assertEqual(self.result(r)['error']['code'], 'source_protected')
        self.assertEqual(self.providers['vk'].count('effect'), 0)

    async def crash_case(self, crash, exitcode, expected_state, effect_count):
        r = await self.publish(content={'text': crash})
        code = '''import asyncio,sys
from social_operations.storage import Store
from social_operations.worker import Worker
from adapters.fake import FakeProvider
s=Store(sys.argv[1]);p=FakeProvider(sys.argv[2],'telegram',crash=sys.argv[3])
asyncio.run(Worker(s,{'telegram':p}).run_once())
'''
        proc = subprocess.run([sys.executable,'-c',code,str(self.store.path),str(self.root/'remote.sqlite'),crash], timeout=15, capture_output=True)
        self.assertEqual(proc.returncode, exitcode, proc.stderr.decode())
        # Advance lease time, not requested delivery time; process really exited.
        restarted = Store(self.store.path, clock=lambda: time.time()+31)
        await Worker(restarted,self.providers).run_once()
        result = self.result(r)
        self.assertEqual(result['state'], expected_state, result)
        with self.store.connection() as db:
            attempt = db.execute('SELECT id FROM attempts WHERE operation_id=?',(r['operation_id'],)).fetchone()[0]
        with self.providers['telegram'].db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM calls WHERE kind='effect' AND attempt=?",(attempt,)).fetchone()[0],effect_count)
        if crash != 'before_marker':
            with self.providers['telegram'].db() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM calls WHERE kind='execute' AND attempt=?",(attempt,)).fetchone()[0],1)
        self.assertFalse(await Worker(restarted,self.providers).run_once())

    async def test_crash_before_marker_can_resume_without_duplicate_effect(self):
        await self.crash_case('before_marker',81,'verified',1)

    async def test_crash_after_effect_observes_without_second_execute(self):
        await self.crash_case('after_effect',83,'verified',1)

    async def test_crash_after_marker_is_unknown_and_quarantines_connection(self):
        await self.crash_case('after_marker',82,'outcome_unknown',0)
        r = await self.publish(content={'text':'Different command on uncertain connection'})
        await self.worker.run_once()
        self.assertEqual(self.result(r)['error']['code'],'connection_outcome_unknown')
        self.assertEqual(self.providers['telegram'].count('effect'),0)

    async def test_two_workers_one_claim_and_no_double_dispatch(self):
        r = await self.publish()
        p = self.providers['telegram'];p.gate=asyncio.Event()
        first = asyncio.create_task(self.worker.run_once())
        await asyncio.sleep(.05)
        self.assertFalse(await Worker(Store(self.store.path),self.providers).run_once())
        p.gate.set();await first
        self.assertEqual(p.count('effect'),1)
        self.assertEqual(self.result(r)['state'],'verified')

    async def test_backup_restoration_blocks_new_effects(self):
        r = await self.publish()
        backup = self.root/'restored.sqlite'
        self.store.backup(backup)
        restored = Store(backup)
        await Worker(restored,self.providers).run_once()
        result = restored.receipt(self.actor,r['operation_id'])
        self.assertEqual(result['error']['code'],'restore_requires_reconciliation')
        self.assertEqual(self.providers['telegram'].count('effect'),0)

    async def test_wrong_target_readback_is_unknown_not_success(self):
        class WrongTarget(FakeProvider):
            async def execute(adapter,prepared,hooks):
                result = await super().execute(prepared,hooks)
                return replace(result,items=(replace(result.items[0],native_target='wrong_channel'),))
        self.providers['telegram']=WrongTarget(self.root/'remote.sqlite','telegram')
        r=await self.publish()
        await self.worker.run_once()
        result=self.result(r)
        self.assertEqual(result['state'],'outcome_unknown')
        self.assertEqual(result['deliveries'][0]['missing_checks'],['wrong_target_readback'])
        self.assertEqual(self.providers['telegram'].count('effect'),1)
        repeated=await self.publish(request_key='unsafe-new-key',repeat_of=r['operation_id'])
        self.assertEqual(repeated['error']['code'],'repeat_not_proven_safe')

    async def test_expired_lease_cannot_duplicate_old_inflight_effect(self):
        done=asyncio.Event();release=asyncio.Event()
        class SlowReturn(FakeProvider):
            async def execute(adapter,prepared,hooks):
                result=await super().execute(prepared,hooks)
                done.set();await release.wait()
                return result
        self.providers['telegram']=SlowReturn(self.root/'remote.sqlite','telegram')
        r=await self.publish()
        old=asyncio.create_task(self.worker.run_once())
        await asyncio.wait_for(done.wait(),2)
        with self.store.tx() as db:
            db.execute('UPDATE operations SET lease_until=0 WHERE id=?',(r['operation_id'],))
        new=asyncio.create_task(Worker(Store(self.store.path),self.providers).run_once())
        await asyncio.sleep(.05)
        self.assertEqual(self.providers['telegram'].count('effect'),1)
        self.assertFalse(new.done())
        release.set()
        await asyncio.gather(old,new)
        self.assertEqual(self.providers['telegram'].count('effect'),1)
        self.assertEqual(self.providers['telegram'].count('execute'),1)
        self.assertEqual(self.result(r)['state'],'verified')

    async def test_real_independent_worker_processes_share_one_claim(self):
        r=await self.publish()
        code="import asyncio,sys;from social_operations.storage import Store;from social_operations.worker import Worker;from adapters.fake import FakeProvider;s=Store(sys.argv[1]);p=FakeProvider(sys.argv[2],'telegram',delay=.2);asyncio.run(Worker(s,{'telegram':p}).run_once())"
        argv=[sys.executable,'-c',code,str(self.store.path),str(self.root/'remote.sqlite')]
        processes=[subprocess.Popen(argv,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE) for _ in range(2)]
        try:
            for process in processes:
                _,err=await asyncio.to_thread(process.communicate,timeout=15)
                self.assertEqual(process.returncode,0,err.decode())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill();process.wait()
        self.assertEqual(self.providers['telegram'].count('effect'),1)
        self.assertEqual(self.result(r)['state'],'verified')

    async def test_readback_media_mismatch_does_not_omit_attachment(self):
        class WrongMedia(FakeProvider):
            async def execute(adapter,prepared,hooks):
                result=await super().execute(prepared,hooks)
                return replace(result,items=(replace(result.items[0],media_hashes=('unexpected',)),))
        self.providers['telegram']=WrongMedia(self.root/'remote.sqlite','telegram')
        r=await self.publish()
        await self.worker.run_once()
        self.assertEqual(self.result(r)['state'],'outcome_unknown')
        self.assertEqual(self.result(r)['deliveries'][0]['missing_checks'],['media_readback_mismatch'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
