"""A service observes its own frozen MAX effect without lifecycle authority."""
import unittest
import httpx
from social_operations.server import create_app
from social_operations.domain import DomainError
from social_operations.recovery import admit
from tests.runtime import test_recovery as fixtures


class MaxPublisherObservationTests(unittest.IsolatedAsyncioTestCase):
    call = fixtures.RecoveryTests.call
    stuck = fixtures.RecoveryTests.stuck
    args = fixtures.RecoveryTests.args
    # Reuse setup, not the owner's broader recovery test cases.
    def setUp(self):
        fixtures.RecoveryTests.setUp(self)
        self.credential = self.store.create_principal(
            self.actor.tenant_id, 'publisher', scopes={'bootstrap', 'publish', 'status'})
        self.store.bind(self.actor, 'publisher', 'max', 'max', 'target', rights=('publish',))
        self.owner = self.actor
        self.actor = self.store.authenticate(self.credential)

    async def original(self):
        receipt = await self.stuck()
        with self.store.connection() as db:
            child = dict(db.execute('SELECT * FROM attempts WHERE operation_id=?',
                                    (receipt['operation_id'],)).fetchone())
        return receipt, self.args(receipt, attempt_id=child['id'])

    async def test_http_same_original_observation_has_one_effect_and_replays(self):
        receipt, args = await self.original()
        self.provider.unknown = False
        headers = {'Authorization': 'Bearer ' + self.credential,
                   'Idempotency-Key': args['request_key']}
        body = {k: v for k, v in args.items() if k not in ('publication_id', 'request_key')}
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(self.store)),
                base_url='http://testserver', headers=headers) as client:
            response = await client.post('/v1/publications/' + receipt['resource_id'] + '/commands',
                                         json=body)
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()['operation_id'], receipt['operation_id'])
            await self.worker.run_once()
            response = await client.post('/v1/publications/' + receipt['resource_id'] + '/commands',
                                         json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['state'], 'verified')
        self.assertEqual(self.provider.count('effect'), 1)
        self.assertEqual(self.provider.count('execute'), 1)
        self.assertNotIn('publication.manage', self.actor.scopes)

    async def test_hint_rebase_and_missing_attempt_are_denied_without_schema(self):
        receipt, args = await self.original()
        for change in ({**args['change'], 'native_reference': 'https://max.ru/other'},
                       {**args['change'], 'native_reference': 'item_other'},
                       {'kind': 'reconcile', 'operation_id': receipt['operation_id']}):
            with self.assertRaises(DomainError) as caught:
                admit(self.app, self.actor, {**args, 'change': change})
            self.assertEqual(caught.exception.code, 'access_denied')

    async def test_nonpublish_and_undispatched_are_denied(self):
        receipt, args = await self.original()
        with self.store.connection() as db:
            original = dict(db.execute('SELECT * FROM attempts').fetchone())
        for field, value in [('dispatched', 0)]:
            with self.store.tx() as db:
                db.execute('UPDATE attempts SET ' + field + '=?', (value,))
            with self.assertRaises(DomainError):
                admit(self.app, self.actor, args)
            with self.store.tx() as db:
                db.execute('UPDATE attempts SET ' + field + '=?', (original[field],))
        with self.store.tx() as db:
            db.execute("UPDATE operations SET action='publication_update'")
        with self.assertRaises(DomainError) as caught:
            admit(self.app, self.actor, args)
        self.assertEqual(caught.exception.code, 'access_denied')

    async def test_private_operation_and_current_binding_right_remain_required(self):
        receipt, args = await self.original()
        other = self.store.authenticate(self.store.create_principal(
            self.actor.tenant_id, 'other', scopes={'publish', 'status'}))
        for caller in (self.owner, other):
            with self.assertRaises(DomainError) as caught:
                admit(self.app, caller, args)
            self.assertEqual(caught.exception.code, 'not_found')
        with self.assertRaises(DomainError):
            admit(self.app, self.actor, {**args, 'change': {
                **args['change'], 'attempt_id': 'attempt_other'}})
        with self.store.tx() as db:
            db.execute("UPDATE bindings SET rights='[]' WHERE principal_id='publisher'")
        with self.assertRaises(DomainError):
            admit(self.app, self.actor, args)


    async def test_other_provider_and_binding_identity_drift_are_denied(self):
        receipt, args = await self.original()
        with self.store.tx() as db:
            db.execute("UPDATE destinations SET native_id='changed'")
        with self.assertRaises(DomainError) as caught:
            admit(self.app, self.actor, args)
        self.assertEqual(caught.exception.code, 'access_revoked')
        self.store.add_connection(self.owner, 'vk', 'vk', account_type='fake')
        self.store.bind(self.owner, 'publisher', 'vk', 'vk', 'vk-target', rights=('publish',))
        other = await self.call('publish', {'to': ['vk'], 'content': {'text': 'Other provider'} })
        with self.store.tx() as db:
            child = db.execute('SELECT id FROM attempts WHERE operation_id=?',
                               (other['operation_id'],)).fetchone()
            db.execute("UPDATE attempts SET dispatched=1 WHERE id=?", (child['id'],))
        with self.assertRaises(DomainError) as caught:
            admit(self.app, self.actor, self.args(other, attempt_id=child['id']))
        self.assertEqual(caught.exception.code, 'access_denied')

    async def test_revoked_epoch_and_current_scope_are_denied(self):
        receipt, args = await self.original()
        with self.store.tx() as db:
            db.execute("UPDATE bindings SET epoch=epoch+1 WHERE principal_id='publisher'")
        with self.assertRaises(DomainError) as caught:
            admit(self.app, self.actor, args)
        self.assertEqual(caught.exception.code, 'access_revoked')
        with self.store.tx() as db:
            db.execute("UPDATE principals SET scopes='[\"status\"]' WHERE id='publisher'")
        with self.assertRaises(DomainError) as caught:
            admit(self.app, self.actor, args)
        self.assertEqual(caught.exception.code, 'access_denied')
