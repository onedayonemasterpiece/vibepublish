"""VK returned post IDs are final identities; legacy media-review fence is gone."""
import json
import tempfile
import unittest
from pathlib import Path

from adapters.port import RemoteItem
from adapters.vk import VKAdapter
from social_operations.assets import import_image
from social_operations.domain import canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.test_native_adapters import NOW, asset
from tests.providers.test_vk_photo_copy_binding import Copies


class KnownVKEffectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = NOW
        self.store = Store(Path(self.temp.name) / 'db', clock=lambda: self.now)
        self.actor = self.store.authenticate(
            self.store.create_principal('t', 'owner', owner=True))
        self.store.add_connection(self.actor, 'connection', 'vk', account_type='vk_user')
        self.store.bind(self.actor, 'owner', 'first', 'connection', '-101')
        self.store.bind(self.actor, 'owner', 'second', 'connection', '-202')
        self.app = Application(self.store)
        self.transport = Copies()
        self.transport.groups[202].update(is_admin=1, admin_level=3)
        self.transport.sabotage = 'bytes'
        self.adapter = VKAdapter(self.transport, connection_id='connection', clock=lambda: self.now)
        self.worker = Worker(self.store, {'vk': self.adapter})
        self.assets = [import_image(self.store, self.actor, asset(n).data, 'image/png') for n in (1, 2)]

    async def publish(self, alias='first', *, media=True, key='original'):
        result = await self.app.call(self.actor, 'vibepublish_publish', {
            'to': [alias], 'content': {'text': 'Frozen known effect'},
            **({'media': [{'source': {'kind': 'asset', 'id': value}}
                           for value in self.assets]} if media else {}),
            'delivery': {'kind': 'at', 'at': timestamp(NOW + 3600)}, 'request_key': key})
        self.assertIn('operation_id', result, result)
        await self.worker.run_once()
        return self.store.receipt(self.actor, result['operation_id'])

    def child(self, operation):
        with self.store.connection() as db:
            return dict(db.execute('SELECT * FROM attempts WHERE operation_id=?',
                                   (operation,)).fetchone())

    async def test_saved_native_vk_post_is_success_without_media_review(self):
        result = await self.publish()
        self.assertEqual(result['state'], 'scheduled', result)
        self.assertTrue(result['operation_complete'])
        self.assertEqual(result['next_action'], 'none')
        delivery, = result['deliveries']
        self.assertEqual(delivery['observed'], 'provider_scheduled')
        self.assertEqual(delivery['media_check'], 'incomplete')
        self.assertTrue(delivery['queue_ref'])
        saved = json.loads(self.child(result['operation_id'])['checkpoint'])
        self.assertEqual(saved['remote']['native_target'], '-101')
        self.assertTrue(saved['remote']['native_id'])
        self.assertNotIn('known_effect', saved)
        self.assertFalse(await Worker(self.store, {'vk': self.adapter}).run_once())
        self.assertEqual(self.transport.effects, 1)

    async def test_uncertain_first_post_cannot_block_independent_second_vk_post(self):
        exact = self.adapter._exact

        async def wrong_text(*args):
            from dataclasses import replace
            value = await exact(*args)
            return replace(value, text='Different intent') if value else value

        self.adapter._exact = wrong_text
        first = await self.publish()
        self.assertEqual(first['state'], 'running', first)
        self.assertEqual(self.transport.effects, 1)
        self.adapter._exact = exact
        self.transport.sabotage = None
        second = await self.publish('second', media=False, key='unrelated')
        self.assertEqual(second['state'], 'scheduled', second)
        self.assertEqual(self.transport.effects, 2)
        self.assertNotIn('connection_outcome_unknown', str(second))

    async def test_incomplete_native_media_does_not_inherit_old_verified_hashes(self):
        result = await self.publish()
        child = self.child(result['operation_id'])
        plan = json.loads(child['plan'])
        remote = RemoteItem(**json.loads(child['checkpoint'])['remote'])
        self.assertEqual(remote.media_check, 'incomplete')
        with self.store.tx() as db:
            row = db.execute('SELECT id,snapshot FROM facts WHERE destination_id=?',
                             (plan['destination_id'],)).fetchone()
            old = json.loads(row['snapshot'])
            old.update(media_check='provider_binding', media_hashes=['a' * 64])
            db.execute('UPDATE facts SET snapshot=? WHERE id=?',
                       (canonical(old), row['id']))
            self.worker.save_fact(db, plan['destination_id'], remote,
                                  self.actor.principal_id, result['resource_id'])
            saved = json.loads(db.execute('SELECT snapshot FROM facts WHERE id=?',
                                          (row['id'],)).fetchone()[0])
            self.assertEqual(saved['media_check'], 'incomplete')
            self.assertEqual(saved['media_hashes'], [])


if __name__ == '__main__':
    unittest.main()
