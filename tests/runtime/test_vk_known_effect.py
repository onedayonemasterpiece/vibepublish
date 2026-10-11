"""Known VK effect with unverified media stays partial, never duplicate-retried."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from adapters.port import RemoteItem
from adapters.vk import VKAdapter
from social_operations.assets import import_image
from social_operations.domain import canonical, digest, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.test_native_adapters import NOW, asset
from tests.providers.test_vk_photo_copy_binding import Copies


class KnownVKEffectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'db', clock=lambda: NOW)
        self.actor = self.store.authenticate(
            self.store.create_principal('t', 'owner', owner=True))
        self.store.add_connection(self.actor, 'connection', 'vk', account_type='vk_user')
        self.store.bind(self.actor, 'owner', 'first', 'connection', '-101')
        self.store.bind(self.actor, 'owner', 'second', 'connection', '-202')
        self.app = Application(self.store)
        self.transport = Copies()
        self.transport.groups[202].update(is_admin=1, admin_level=3)
        self.transport.sabotage = 'bytes'
        self.adapter = VKAdapter(self.transport, connection_id='connection', clock=lambda: NOW)
        self.worker = Worker(self.store, {'vk': self.adapter})
        self.assets = [import_image(self.store, self.actor, asset(n).data, 'image/png') for n in (1, 2)]

    async def publish(self, alias='first', *, media=True, key='original'):
        result = await self.app.call(self.actor, 'vibepublish_publish', {
            'to': [alias], 'content': {'text': 'Frozen known effect'},
            **({'media': [{'source': {'kind': 'asset', 'id': value}} for value in self.assets]} if media else {}),
            'delivery': {'kind': 'at', 'at': timestamp(NOW + 3600)}, 'request_key': key})
        self.assertIn('operation_id', result, result)
        await self.worker.run_once()
        return self.store.receipt(self.actor, result['operation_id'])

    def child(self, operation):
        with self.store.connection() as db:
            return dict(db.execute('SELECT * FROM attempts WHERE operation_id=?',
                                   (operation,)).fetchone())

    async def test_known_effect_stays_partial_and_releases_only_connection_quarantine(self):
        result = await self.publish()
        self.assertEqual(result['state'], 'partial', result)
        self.assertTrue(result['operation_complete'])
        self.assertEqual(result['next_action'], 'review_outcome')
        delivery, = result['deliveries']
        self.assertEqual(delivery['state'], 'partial')
        self.assertEqual(delivery['observed'], 'provider_scheduled')
        self.assertEqual(delivery['media_check'], 'incomplete')
        self.assertEqual(delivery['missing_checks'], ['media_identity_or_order_mismatch'])
        self.assertFalse(delivery['retry_safe'])
        self.assertTrue(delivery['item_ref'])
        schema = next(tool for tool in self.app.tools(self.actor) if tool['name'] == 'vibepublish_publish')['outputSchema']
        Draft202012Validator(schema).validate(result)
        old = self.child(result['operation_id'])
        with self.store.connection() as db:
            self.assertTrue(self.worker.known_effect_resolved(db, old))
        # Original command and explicit retry never resend the known effect.
        self.assertFalse(await Worker(self.store, {'vk': self.adapter}).run_once())
        denied = await self.app.call(self.actor, 'vibepublish_publication_update', {
            'publication_id': result['resource_id'], 'expected_revision': result['revision'],
            'change': {'kind': 'retry_failed', 'destinations': ['first']},
            'request_key': 'no-duplicate'})
        self.assertIn('error', denied)
        self.assertEqual(self.transport.effects, 1)
        self.transport.sabotage = None
        fresh = await self.publish('second', media=False, key='unrelated')
        self.assertEqual(fresh['state'], 'scheduled', fresh)
        self.assertEqual(self.transport.effects, 2)
        self.assertEqual(self.child(result['operation_id'])['checkpoint'], old['checkpoint'])

    async def test_missing_or_wrong_identity_keeps_unknown_fence(self):
        exact = self.adapter._exact
        async def wrong_text(*args):
            from dataclasses import replace
            value = await exact(*args)
            return replace(value, text='Different intent') if value else value
        self.adapter._exact = wrong_text
        result = await self.publish()
        self.assertEqual(result['state'], 'outcome_unknown', result)
        self.assertNotIn('known_effect', json.loads(self.child(result['operation_id'])['checkpoint']))
        self.adapter._exact = exact
        self.transport.sabotage = None
        blocked = await self.publish('second', media=False, key='must-remain-fenced')
        self.assertEqual(blocked['state'], 'blocked')
        self.assertEqual(blocked['error']['code'], 'connection_outcome_unknown')
        self.assertEqual(self.transport.effects, 1)

    async def test_malformed_proof_never_releases_quarantine(self):
        result = await self.publish()
        original = self.child(result['operation_id'])
        cp = json.loads(original['checkpoint'])
        mutations = [
            lambda p: p['known_effect'].update(checkpoint_digest='0' * 64),
            lambda p: p['known_effect'].update(plan_digest='0' * 64),
            lambda p: p['known_effect'].update(attempt_id='attempt_other'),
            lambda p: p['known_effect'].update(operation_id='op_other'),
            lambda p: p['known_effect'].update(actor_epoch=99),
            lambda p: p['known_effect'].update(binding_epoch=99),
            lambda p: p['known_effect'].update(observed='published'),
            lambda p: p['known_effect']['remote'].update(native_id='999'),
            lambda p: p['known_effect']['remote'].update(native_target='-999'),
            lambda p: p['known_effect']['remote'].update(text='wrong'),
            lambda p: p['known_effect']['remote'].update(scheduled_at=timestamp(NOW + 7200)),
            lambda p: p['known_effect']['remote'].update(namespace='published'),
            lambda p: p['known_effect']['remote'].update(media_check='provider_binding'),
            lambda p: p.update(adapter={**p['adapter'], 'id': None}),
            lambda p: p.pop('known_effect'),
        ]
        with self.store.connection() as db:
            for mutate in mutations:
                changed = copy.deepcopy(cp)
                mutate(changed)
                with self.subTest(mutation=mutate):
                    self.assertFalse(self.worker.known_effect_resolved(
                        db, {**original, 'checkpoint': canonical(changed)}))
            self.assertFalse(self.worker.known_effect_resolved(db, {**original, 'state': 'blocked'}))
            # Current authority, not just the saved epochs, gates the exclusion.
        with self.store.tx() as db:
            db.execute('UPDATE bindings SET epoch=epoch+1 WHERE id=?', (original['binding_id'],))
        with self.store.connection() as db:
            self.assertFalse(self.worker.known_effect_resolved(db, original))

    async def test_core_rechecks_every_frozen_identity_component(self):
        result = await self.publish()
        child = self.child(result['operation_id'])
        cp = json.loads(child['checkpoint'])
        proof = cp.pop('known_effect')
        plan = json.loads(child['plan'])
        item = RemoteItem(**proof['remote'])
        self.assertTrue(Worker.known_vk_effect_identity(child, plan, item, cp, proof['observed']))
        from dataclasses import replace
        for field, value in [('native_id', '999'), ('native_target', '-999'),
                             ('text', ''), ('scheduled_at', None),
                             ('namespace', 'published')]:
            self.assertFalse(Worker.known_vk_effect_identity(
                child, plan, replace(item, **{field: value}), cp, proof['observed']))
        for field, value in [('id', None), ('id', 'wrong'), ('plan', '0' * 64),
                             ('target', '-999'), ('attempt', 'other')]:
            changed = copy.deepcopy(cp)
            changed['adapter'][field] = value
            self.assertFalse(Worker.known_vk_effect_identity(child, plan, item, changed, proof['observed']))

    async def test_incomplete_observation_does_not_inherit_old_verified_media(self):
        result = await self.publish()
        child = self.child(result['operation_id'])
        plan = json.loads(child['plan'])
        remote = RemoteItem(**json.loads(child['checkpoint'])['known_effect']['remote'])
        with self.store.tx() as db:
            row = db.execute('SELECT id,snapshot FROM facts WHERE destination_id=?',
                             (plan['destination_id'],)).fetchone()
            old = json.loads(row['snapshot'])
            old.update(media_check='provider_binding', media_hashes=['a' * 64])
            db.execute('UPDATE facts SET snapshot=? WHERE id=?', (canonical(old), row['id']))
            self.worker.save_fact(db, plan['destination_id'], remote,
                                  self.actor.principal_id, result['resource_id'])
            saved = json.loads(db.execute('SELECT snapshot FROM facts WHERE id=?',
                                          (row['id'],)).fetchone()[0])
            self.assertEqual(saved['media_check'], 'incomplete')
            self.assertEqual(saved['media_hashes'], [])

    async def test_connection_review_scan_is_bounded_and_fails_closed(self):
        result = await self.publish()
        original = self.child(result['operation_id'])
        with self.store.tx() as db:
            old_op = dict(db.execute('SELECT * FROM operations WHERE id=?',
                                     (result['operation_id'],)).fetchone())
            # Isolated database fixture: retained unresolved records, no provider effects.
            for index in range(100):
                operation = {**old_op, 'id': 'op_retained_' + str(index)}
                attempt = {**original, 'id': 'attempt_retained_' + str(index),
                           'operation_id': operation['id']}
                for table, row in [('operations', operation), ('attempts', attempt)]:
                    db.execute('INSERT INTO ' + table + '(' + ','.join(row) +
                               ') VALUES(' + ','.join('?' for _ in row) + ')', tuple(row.values()))
        self.transport.sabotage = None
        blocked = await self.publish('second', media=False, key='bounded-scan')
        self.assertEqual(blocked['state'], 'blocked')
        self.assertEqual(blocked['error']['code'], 'connection_review_limit')
        self.assertEqual(blocked['next_action'], 'review_outcome')
        self.assertFalse(blocked['deliveries'][0]['retry_safe'])
        self.assertEqual(self.transport.effects, 1)
