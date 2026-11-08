"""Permission text is the frozen payload; preparing it never edits a native post."""
from __future__ import annotations

import asyncio
import concurrent.futures
import io
import threading
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest

from adapters.fake import FakeProvider
from adapters.port import Capability
from social_operations.assets import import_image, reclaim_asset_bytes, retired_asset_rows
from social_operations.domain import canonical
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.runtime.test_managed_item_media_edits import env, published, call, receipt, update_args
from tests.emoji.test_runtime import runtime as emoji_runtime, register, select, rule


class SemanticPreviewProvider(FakeProvider):
    """The offline fixture accepts semantic text without contacting a provider."""

    async def prepare(self, request, hooks):
        content = json.loads(request.content_json)
        content.pop('format', None)
        prepared = await super().prepare(replace(request, content_json=canonical(content)), hooks)
        return replace(prepared, request=request)

    async def inspect(self, request):
        if request.surface == 'story':
            return Capability('supported', 'Offline story fixture; no live evidence')
        return await super().inspect(request)


class PublicationPermissionPreviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = Store(root / 'ledger.sqlite')
        self.actor = self.store.authenticate(self.store.create_principal('tenant', 'owner', owner=True))
        self.providers, self.bindings = {}, {}
        for provider, native in (('telegram', '-1000000000101'), ('vk', '-101')):
            self.store.add_connection(self.actor, 'conn_' + provider, provider, account_type='fake',
                                      secret_ref='VIBEPUBLISH_TEST_SECRET_' + provider.upper(), shared=True)
            self.bindings[provider] = self.store.bind(self.actor, 'owner', provider, 'conn_' + provider, native)
            self.providers[provider] = SemanticPreviewProvider(root / 'remote.sqlite', provider)
        self.store.bind(self.actor, 'owner', 'lovekenig_tg', 'conn_telegram', '-1000000000102', handle='@frozen_footer')
        self.store.bind(self.actor, 'owner', 'lovekenig_vk', 'conn_vk', '-102')
        self.app, self.worker = Application(self.store), Worker(self.store, self.providers)

    async def call(self, name, args):
        return await self.app.call(self.actor, 'vibepublish_' + name, args)

    def asset(self, color):
        image = io.BytesIO()
        Image.new('RGB', (3, 3), color).save(image, format='PNG')
        return import_image(self.store, self.actor, image.getvalue(), 'image/png')


    async def ready_preview_to_cancel(self, **options):
        accepted = await self.call('publish', {
            'to': ['vk'], 'content': {'text': 'Private preview; do not publish'},
            'delivery': {'kind': 'at', 'at': '2030-07-04T14:30:00+03:00'},
            'mode': 'preview', **options})
        self.assertEqual(accepted['state'], 'accepted', accepted)
        self.assertTrue(await self.worker.run_once(operation_id=accepted['operation_id']))
        preview = self.store.receipt(self.actor, accepted['operation_id'])
        self.assertEqual(preview['state'], 'needs_approval', preview)
        self.assertEqual(self.providers['vk'].count('effect'), 0)
        return accepted, preview

    async def test_private_preview_cancel_is_durable_terminal_and_not_approvable(self):
        assets = [self.asset(color) for color in
                  ('red', 'orange', 'yellow', 'green', 'blue', 'purple', 'black')]
        accepted, preview = await self.ready_preview_to_cancel(
            vk={'primary_attachments_mode': 'carousel'},
            media=[{'source': {'kind': 'asset', 'id': asset}} for asset in reversed(assets)])
        with self.store.connection() as db:
            before_assets = [tuple(row) for row in db.execute(
                'SELECT id,sha256,length(bytes) FROM assets ORDER BY id')]
        args = {'publication_id': accepted['resource_id'], 'expected_revision': 1,
                'change': {'kind': 'cancel'}, 'request_key': 'cancel-private-preview'}
        cancelled = await self.call('publication_update', args)
        self.assertNotIn('error', cancelled, cancelled)
        self.assertEqual(cancelled['state'], 'cancelled', cancelled)
        self.assertEqual(cancelled['revision'], 2)
        self.assertTrue(cancelled['operation_complete'])
        self.assertEqual(cancelled['next_action'], 'none')
        self.assertNotIn('review_token', cancelled)
        self.assertNotIn('permission_request', cancelled)

        reopened = Store(self.store.path)
        app = Application(reopened)
        status = await app.call(self.actor, 'vibepublish_status',
                                {'ids': [accepted['resource_id']]})
        current, = status['receipts']
        self.assertEqual(current['operation_id'], cancelled['operation_id'])
        self.assertEqual(current['state'], 'cancelled')
        self.assertTrue(current['operation_complete'])
        delivery, = current['deliveries']
        self.assertEqual(delivery['state'], 'cancelled')
        self.assertEqual(delivery['observed'], 'not_attempted')
        self.assertEqual(delivery['sync_status'], 'current')
        self.assertIsNone(delivery['applied_revision'])
        self.assertEqual(delivery['desired_revision'], 2)
        self.assertNotIn('item_ref', delivery)
        self.assertNotIn('queue_ref', delivery)
        self.assertFalse(await Worker(reopened, self.providers).run_once(
            operation_id=cancelled['operation_id']))

        replay = await app.call(self.actor, 'vibepublish_publication_update', args)
        self.assertEqual(replay['operation_id'], cancelled['operation_id'])
        self.assertEqual(replay['revision'], 2)
        conflict = await app.call(self.actor, 'vibepublish_publication_update',
                                  {**args, 'change': {'kind': 'delete'}})
        self.assertEqual(conflict['error']['code'], 'idempotency_conflict')
        stale = await app.call(self.actor, 'vibepublish_publication_update',
                               {**args, 'request_key': 'different-cancel-key'})
        self.assertEqual(stale['error']['code'], 'revision_conflict')
        for revision, code in ((1, 'revision_conflict'), (2, 'approval_invalid')):
            approval = await app.call(self.actor, 'vibepublish_publication_update', {
                'publication_id': accepted['resource_id'], 'expected_revision': revision,
                'change': {'kind': 'approve', 'token': preview['review_token']}})
            self.assertEqual(approval['error']['code'], code, approval)
        with reopened.connection() as db:
            self.assertEqual(db.execute(
                'SELECT revision FROM publications WHERE id=?',
                (accepted['resource_id'],)).fetchone()[0], 2)
            self.assertEqual(db.execute(
                'SELECT count(*) FROM operations WHERE publication_id=?',
                (accepted['resource_id'],)).fetchone()[0], 2)
            decision, = db.execute(
                'SELECT consumed_by FROM decisions WHERE publication_id=?',
                (accepted['resource_id'],)).fetchall()
            self.assertEqual(decision['consumed_by'], cancelled['operation_id'])
            attempt, = db.execute(
                'SELECT dispatched,checkpoint FROM attempts WHERE operation_id=?',
                (cancelled['operation_id'],)).fetchall()
            self.assertEqual(attempt['dispatched'], 0)
            self.assertEqual(json.loads(attempt['checkpoint']), {})
            self.assertEqual([tuple(row) for row in db.execute(
                'SELECT id,sha256,length(bytes) FROM assets ORDER BY id')], before_assets)
        self.assertEqual(self.providers['vk'].count('execute'), 0)
        self.assertEqual(self.providers['vk'].count('effect'), 0)

    async def test_private_preview_cancel_and_approve_serialize_on_real_store(self):
        accepted, preview = await self.ready_preview_to_cancel()
        barrier = threading.Barrier(2)

        def submit(change, key):
            store = Store(self.store.path)
            app = Application(store)
            barrier.wait(timeout=10)
            return asyncio.run(app.call(self.actor, 'vibepublish_publication_update', {
                'publication_id': accepted['resource_id'], 'expected_revision': 1,
                'change': change, 'request_key': key}))

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            cancel_future = pool.submit(submit, {'kind': 'cancel'}, 'race-cancel')
            approve_future = pool.submit(
                submit, {'kind': 'approve', 'token': preview['review_token']}, 'race-approve')
            results = [cancel_future.result(), approve_future.result()]
        winners = [result for result in results if 'error' not in result]
        losers = [result for result in results if 'error' in result]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(losers), 1, results)
        self.assertEqual(losers[0]['error']['code'], 'revision_conflict', results)
        winner, = winners
        self.assertEqual(winner['revision'], 2)
        worked = await self.worker.run_once(operation_id=winner['operation_id'])
        cancelled = winner['state'] == 'cancelled'
        self.assertEqual(worked, not cancelled)
        self.assertEqual(self.providers['vk'].count('effect'), 0 if cancelled else 1)

    async def test_private_preview_cancel_rechecks_cancel_right(self):
        accepted, preview = await self.ready_preview_to_cancel()
        with self.store.tx() as db:
            rights = json.loads(db.execute(
                'SELECT rights FROM bindings WHERE id=?', (self.bindings['vk'],)).fetchone()[0])
            db.execute('UPDATE bindings SET rights=? WHERE id=?',
                       (canonical([right for right in rights if right != 'cancel']),
                        self.bindings['vk']))
        denied = await self.call('publication_update', {
            'publication_id': accepted['resource_id'], 'expected_revision': 1,
            'change': {'kind': 'cancel'}, 'request_key': 'cancel-without-right'})
        self.assertEqual(denied['error']['code'], 'access_denied', denied)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT revision FROM publications WHERE id=?',
                                        (accepted['resource_id'],)).fetchone()[0], 1)
            self.assertIsNone(db.execute('SELECT consumed_by FROM decisions WHERE publication_id=?',
                                        (accepted['resource_id'],)).fetchone()[0])
            self.assertEqual(db.execute('SELECT count(*) FROM operations WHERE publication_id=?',
                                        (accepted['resource_id'],)).fetchone()[0], 1)
        self.assertEqual(self.providers['vk'].count('effect'), 0)

    async def test_private_preview_cancel_cannot_win_after_approval_admission(self):
        accepted, preview = await self.ready_preview_to_cancel()
        approved = await self.call('publication_update', {
            'publication_id': accepted['resource_id'], 'expected_revision': 1,
            'change': {'kind': 'approve', 'token': preview['review_token']},
            'request_key': 'approve-before-cancel'})
        self.assertEqual(approved['state'], 'accepted', approved)
        cancelled = await self.call('publication_update', {
            'publication_id': accepted['resource_id'], 'expected_revision': 1,
            'change': {'kind': 'cancel'}, 'request_key': 'cancel-after-approve'})
        self.assertEqual(cancelled['error']['code'], 'revision_conflict', cancelled)
        self.assertTrue(await self.worker.run_once(operation_id=approved['operation_id']))
        self.assertEqual(self.providers['vk'].count('effect'), 1)


    async def test_private_preview_cancel_hook_preserves_native_item_ref_cancel(self):
        native = self.providers['vk'].seed(
            '-101', 'Scheduled outside this publication',
            scheduled_at='2030-07-04T14:30:00+03:00')
        read = await self.call('read', {
            'query': {'kind': 'scheduled', 'destination': 'vk'}})
        self.assertTrue(await self.worker.run_once(operation_id=read['operation_id']))
        current = self.store.receipt(self.actor, read['operation_id'])
        item, = current['items']
        self.assertEqual(item['source'], 'provider')
        accepted = await self.call('publication_update', {
            'item_ref': item['ref'], 'change': {'kind': 'cancel'},
            'request_key': 'native-item-ref-cancel'})
        self.assertEqual(accepted['state'], 'accepted', accepted)
        self.assertTrue(await self.worker.run_once(operation_id=accepted['operation_id']))
        cancelled = self.store.receipt(self.actor, accepted['operation_id'])
        self.assertEqual(cancelled['state'], 'cancelled', cancelled)
        delivery, = cancelled['deliveries']
        self.assertEqual(delivery['observed'], 'cancelled')
        self.assertEqual(self.providers['vk'].count('effect'), 1)
        with self.providers['vk'].db() as db:
            rows = db.execute('SELECT id,snapshot FROM items').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], native.native_id)
        self.assertEqual(json.loads(rows[0]['snapshot'])['namespace'], 'cancelled')

    async def test_async_brief_status_returns_exact_frozen_publish_permission(self):
        assets = [self.asset(color) for color in ('blue', 'red', 'green')]
        ordered = [assets[2], assets[0], assets[1]]
        args = {'to': ['lovekenig_tg'], 'mode': 'preview',
                'content': {'text': 'История 🖼\n' + 'Полный текст. ' * 30},
                'delivery': {'kind': 'at', 'at': '2030-07-04T14:30:00+03:00'},
                'media': [{'source': {'kind': 'asset', 'id': asset}} for asset in ordered]}
        accepted = await self.call('publish', args)
        self.assertEqual(accepted['state'], 'accepted', accepted)
        with self.store.tx() as db:
            plan = json.loads(db.execute('SELECT plan FROM attempts WHERE operation_id=?',
                                         (accepted['operation_id'],)).fetchone()[0])
            db.execute("UPDATE destinations SET native_id='-999' WHERE native_id='-102'")
        frozen = json.loads(plan['content_json'])
        args['content']['text'] = 'Changed after admission'
        await self.worker.run_once()
        status = await self.call('status', {'ids': [accepted['operation_id']]})
        result = status['receipts'][0]
        self.assertTrue(result.get('dry_run'), result)
        self.assertEqual(result['content_previews'][0]['text'], frozen['text'])
        self.assertEqual(result['content_previews'][0]['entities'], frozen['entities'])
        request = result['permission_request']
        self.assertIn(frozen['text'], request)
        self.assertIn('https://t.me/frozen_footer', request)
        self.assertIn('https://vk.com/club102', request)
        self.assertNotIn('club999', request)
        self.assertIn('2030-07-04 13:30:00+02:00', request)
        self.assertIn('Europe/Kaliningrad', request)
        self.assertIn('-1000000000102', request)
        self.assertEqual(sorted(ordered, key=request.index), ordered)
        self.assertNotIn('VIBEPUBLISH_TEST_SECRET', request)
        self.assertNotIn('connection_id', request)
        self.assertIn('review_token', result)  # Existing publish approval contract is retained.
        self.assertTrue(all(provider.count('effect') == 0 for provider in self.providers.values()))

    async def test_publish_approval_keeps_frozen_footer_media_order_and_schedule(self):
        ordered = [self.asset(color) for color in ('green', 'red')]
        accepted = await self.call('publish', {
            'to': ['lovekenig_tg'], 'content': {'text': 'Утверждённый текст'}, 'mode': 'preview',
            'delivery': {'kind': 'at', 'at': '2030-07-04T14:30:00+03:00'},
            'media': [{'source': {'kind': 'asset', 'id': asset}} for asset in ordered]})
        await self.worker.run_once()
        preview = self.store.receipt(self.actor, accepted['operation_id'])
        with self.store.tx() as db:
            frozen = json.loads(db.execute('SELECT plan FROM attempts WHERE operation_id=?',
                                           (accepted['operation_id'],)).fetchone()[0])
            db.execute("UPDATE destinations SET native_id='-999' WHERE native_id='-102'")
        approved = await self.call('publication_update', {
            'publication_id': accepted['resource_id'], 'expected_revision': 1,
            'change': {'kind': 'approve', 'token': preview['review_token']}})
        self.assertEqual(approved['state'], 'accepted', approved)
        with self.store.connection() as db:
            executing = json.loads(db.execute('SELECT plan FROM attempts WHERE operation_id=?',
                                              (approved['operation_id'],)).fetchone()[0])
        self.assertEqual(executing, {**frozen, 'mode': 'execute'})
        self.assertEqual(self.providers['telegram'].count('effect'), 0)

    async def assert_native_options_frozen(self, args):
        photo = self.asset('blue')
        accepted = await self.call('publish', {
            **args, 'mode': 'preview', 'media': [{'source': {'kind': 'asset', 'id': photo}}]})
        self.assertEqual(accepted['state'], 'accepted', accepted)
        await self.worker.run_once()
        preview = self.store.receipt(self.actor, accepted['operation_id'])
        with self.store.connection() as db:
            frozen = json.loads(db.execute('SELECT plan FROM attempts WHERE operation_id=?',
                                           (accepted['operation_id'],)).fetchone()[0])
        approved = await self.call('publication_update', {
            'publication_id': accepted['resource_id'], 'expected_revision': 1,
            'change': {'kind': 'approve', 'token': preview['review_token']}})
        self.assertEqual(approved['state'], 'accepted', approved)
        with self.store.connection() as db:
            executing = json.loads(db.execute('SELECT plan FROM attempts WHERE operation_id=?',
                                              (approved['operation_id'],)).fetchone()[0])
        self.assertEqual(executing, {**frozen, 'mode': 'execute'})

    async def test_publish_approval_keeps_frozen_vk_carousel_mode(self):
        await self.assert_native_options_frozen({'to': ['vk'], 'vk': {'primary_attachments_mode': 'carousel'},
                                                 'content': {'text': 'Карусель'}})

    async def test_publish_approval_keeps_frozen_story_link(self):
        await self.assert_native_options_frozen({'to': ['telegram'], 'surface': 'story', 'content': {'text': ''},
                                                 'story_link': {'url': 'https://example.com/story'}})

    async def test_publish_approval_rechecks_current_rights_without_dispatch(self):
        accepted = await self.call('publish', {'to': ['telegram'], 'mode': 'preview', 'content': {'text': 'Текст'}})
        await self.worker.run_once()
        preview = self.store.receipt(self.actor, accepted['operation_id'])
        with self.store.tx() as db:
            rights = json.loads(db.execute('SELECT rights FROM bindings WHERE id=?', (self.bindings['telegram'],)).fetchone()[0])
            db.execute('UPDATE bindings SET rights=? WHERE id=?',
                       (canonical([right for right in rights if right != 'publish']), self.bindings['telegram']))
        denied = await self.call('publication_update', {
            'publication_id': accepted['resource_id'], 'expected_revision': 1,
            'change': {'kind': 'approve', 'token': preview['review_token']}})
        self.assertEqual(denied['error']['code'], 'access_denied')
        self.assertEqual(self.providers['telegram'].count('effect'), 0)
        self.assertFalse(await self.worker.run_once())

    async def test_edit_preview_keeps_head_and_sibling_then_normal_execute_works(self):
        posted = await self.call('publish', {'to': ['telegram', 'vk'], 'content': {'text': 'До\nВторая строка'}})
        await self.worker.run_once()
        args = {'publication_id': posted['resource_id'], 'expected_revision': 1, 'request_key': 'preview-edit',
                'change': {'kind': 'edit', 'mode': 'preview', 'destinations': ['telegram'],
                           'content': {'text': 'После\nВторая строка'}}}
        preview = await self.call('publication_update', args)
        self.assertTrue(preview.get('dry_run'), preview)
        self.assertTrue(preview['operation_complete'])
        self.assertNotIn('review_token', preview)
        self.assertNotIn('resource_id', preview)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT revision FROM publications WHERE id=?', (posted['resource_id'],)).fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM revisions WHERE publication_id=?', (posted['resource_id'],)).fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM decisions').fetchone()[0], 0)
            operation = db.execute('SELECT * FROM operations WHERE id=?', (preview['operation_id'],)).fetchone()
            self.assertIsNone(operation['publication_id'])
            self.assertEqual(operation['work_state'], 'done')
            child = db.execute('SELECT * FROM attempts WHERE operation_id=?', (preview['operation_id'],)).fetchone()
            self.assertEqual(child['dispatched'], 0)
            remote = json.loads(child['plan'])['existing']
        request = preview['permission_request']
        self.assertIn(remote['native_id'], request)
        self.assertIn('До\nВторая строка', request)
        self.assertIn('После\nВторая строка', request)
        self.assertIn('-До', request)
        self.assertIn('+После', request)
        self.assertIn('исходная ревизия 1', request)
        self.assertNotIn('VIBEPUBLISH_TEST_SECRET', request)
        self.assertEqual(preview['operation_id'], (await self.call('publication_update', args))['operation_id'])
        self.assertFalse(await self.worker.run_once())
        self.assertEqual([provider.count('effect') for provider in self.providers.values()], [1, 1])
        status = await self.call('status', {'ids': [preview['operation_id']]})
        self.assertEqual(status['receipts'][0]['permission_request'], request)

        execute = {**args, 'request_key': 'execute-edit',
                   'change': {key: value for key, value in args['change'].items() if key != 'mode'}}
        accepted = await self.call('publication_update', execute)
        self.assertEqual(accepted['state'], 'accepted', accepted)
        await self.worker.run_once()
        executed = self.store.receipt(self.actor, accepted['operation_id'])
        selected = next(item for item in executed['deliveries'] if item['destination'] == 'telegram')
        sibling = next(item for item in executed['deliveries'] if item['destination'] == 'vk')
        self.assertEqual(selected['state'], 'verified', executed)
        self.assertEqual(selected['applied_revision'], 2)
        self.assertEqual(sibling['applied_revision'], 1)
        self.assertEqual([provider.count('effect') for provider in self.providers.values()], [2, 1])
        with self.store.tx() as db:
            db.execute('UPDATE bindings SET epoch=epoch+1 WHERE id=?', (self.bindings['telegram'],))
        denied = await self.call('status', {'ids': [preview['operation_id']]})
        self.assertEqual(denied['error']['code'], 'access_revoked')

    def test_edit_diff_includes_link_only_change_and_actual_native_media_order(self):
        from social_operations.permission_preview import permission_result

        before_entities = [{'type': 'text_link', 'offset': 3, 'length': 6, 'url': 'https://example.com/old'}]
        after_entities = [{**before_entities[0], 'url': 'https://example.com/new'}]
        plan = {'action': 'edit', 'provider': 'vk', 'alias': 'vk', 'native_target': '-101', 'surface': 'post',
                'content_json': canonical({'text': '🖼 Ссылка', 'entities': after_entities}), 'scheduled_at': None,
                'secret_ref': 'NEVER_SHOW_THIS',
                'existing': {'native_id': '77', 'namespace': 'published', 'url': 'https://vk.com/wall-101_77',
                             'text': '🖼 Ссылка', 'entities_json': canonical(before_entities),
                             'provider_media': ['photo-101_3', 'photo-101_8']},
                'assets': [{'ref': 'photo-101_8', 'provider_ref': 'photo-101_8'}, {'ref': 'asset_chosen'}]}
        result = permission_result([plan], timezone=self.actor.timezone, revision=2, source_revision=1)
        request = result['permission_request']
        self.assertIn('https://vk.com/wall-101_77', request)
        self.assertIn('1. photo-101_8 (image)\n2. asset_chosen (image)', request)
        difference = request.split('Точные изменения:\n', 1)[1]
        self.assertIn('https://example.com/old', difference)
        self.assertIn('https://example.com/new', difference)
        self.assertIn('"Ссылка"', difference)  # UTF-16 offsets survive the leading emoji.
        self.assertEqual(result['content_previews'][0]['entities'], after_entities)
        self.assertNotIn('NEVER_SHOW_THIS', request)

    async def test_bound_edit_rejects_wrong_target_publish_and_foreign_previews(self):
        previews, posts = [], []
        for number in (1, 2):
            post = await self.call('publish', {'to': ['telegram'], 'content': {'text': f'Пост {number}'}})
            await self.worker.run_once()
            posts.append(post)
            previews.append(await self.call('publication_update', {
                'publication_id': post['resource_id'], 'expected_revision': 1,
                'change': {'kind': 'edit', 'mode': 'preview', 'content': {'text': 'Правка'}}}))
        foreign = self.store.authenticate(self.store.create_principal('other', 'foreign', owner=True))
        self.store.add_connection(foreign, 'conn_foreign', 'telegram', account_type='fake', shared=True)
        self.store.bind(foreign, 'foreign', 'telegram', 'conn_foreign', '-1000000000202')
        foreign_post = await self.app.call(foreign, 'vibepublish_publish',
                                           {'to': ['telegram'], 'content': {'text': 'Чужой пост'}})
        await self.worker.run_once()
        foreign_preview = await self.app.call(foreign, 'vibepublish_publication_update', {
            'publication_id': foreign_post['resource_id'], 'expected_revision': 1,
            'change': {'kind': 'edit', 'mode': 'preview', 'content': {'text': 'Чужая правка'}}})
        effects = self.providers['telegram'].count('effect')
        execute = previews[0]['execute_args']
        self.assertNotIn('VIBEPUBLISH_TEST_SECRET', canonical(execute))
        for reference, error in (
            (previews[1]['operation_id'], 'permission_preview_changed'),
            (posts[0]['operation_id'], 'permission_preview_invalid'),
            (foreign_preview['operation_id'], 'not_found'),
        ):
            with self.subTest(reference=reference):
                rejected = await self.call('publication_update', {
                    **execute, 'change': {**execute['change'], 'preview_operation_id': reference}})
                self.assertEqual(rejected['error']['code'], error, rejected)
                with self.store.connection() as db:
                    self.assertEqual(db.execute('SELECT revision FROM publications WHERE id=?',
                                                (posts[0]['resource_id'],)).fetchone()[0], 1)
                    self.assertEqual(db.execute('SELECT count(*) FROM revisions WHERE publication_id=?',
                                                (posts[0]['resource_id'],)).fetchone()[0], 1)
        self.assertFalse(await self.worker.run_once())
        self.assertEqual(self.providers['telegram'].count('effect'), effects)


@pytest.mark.asyncio
@pytest.mark.parametrize('replace_media', (False, True))
async def test_item_preview_reuses_native_or_managed_plan_without_advancing_head(env, replace_media):
    original, fresh, _, _ = await published(env, siblings=False)
    before_effects, before_reads = len(env.tg.effects), env.tg.reads
    before_native = env.tg.remote.native_id
    with env.store.connection() as db:
        before = {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)]
                  for table in ('publications', 'revisions')}
    args = update_args(env, fresh, key='preview-native')
    if not replace_media:
        args['change'].pop('media')
    args['change']['mode'] = 'preview'
    result = await call(env, 'publication_update', args)
    assert result.get('dry_run'), result
    assert 'resource_id' not in result and 'review_token' not in result
    assert before_native in result['permission_request']
    assert len(env.tg.effects) == before_effects and env.tg.reads == before_reads
    assert not await env.worker.run_once()
    with env.store.connection() as db:
        after = {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)] for table in before}
    assert after == before
    execute = result['execute_args']
    assert execute['change']['preview_operation_id'] == result['operation_id']
    assert execute['request_key'] != args['request_key']
    accepted = await call(env, 'publication_update', execute)
    assert accepted.get('state') == 'accepted', accepted
    if replace_media:
        assert accepted['resource_id'] == original['resource_id'] and accepted['revision'] == 2
    assert await env.worker.run_once()
    assert receipt(env, accepted)['state'] == 'verified'
    assert len(env.tg.effects) == before_effects + 1 and env.tg.remote.native_id == before_native


@pytest.mark.asyncio
async def test_bound_edit_refuses_changed_emoji_alias_without_advancing_revision(emoji_runtime):
    store, actor, app, worker, client, *_ = emoji_runtime
    catalog = await register(emoji_runtime)
    await select(emoji_runtime, catalog)
    await rule(emoji_runtime)
    post = await app.call(actor, 'vibepublish_publish', {'to': ['telegram'], 'content': {'text': 'До'}})
    await worker.run_once()
    preview_args = {'publication_id': post['resource_id'], 'expected_revision': 1,
                    'change': {'kind': 'edit', 'mode': 'preview', 'content': {'text': '🎭'}}}
    preview = await app.call(actor, 'vibepublish_publication_update', preview_args)
    assert preview.get('dry_run'), preview
    effects = client.effects
    before = preview['content_previews'][0]['entities']
    await select(emoji_runtime, catalog, (1, 1), revision=1)
    rejected = await app.call(actor, 'vibepublish_publication_update', preview['execute_args'])
    assert rejected['error']['code'] == 'permission_preview_changed', rejected
    with store.connection() as db:
        assert db.execute('SELECT revision FROM publications WHERE id=?', (post['resource_id'],)).fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM revisions WHERE publication_id=?', (post['resource_id'],)).fetchone()[0] == 1
    assert client.effects == effects and not await worker.run_once()
    refreshed = await app.call(actor, 'vibepublish_publication_update', preview_args)
    assert refreshed['content_previews'][0]['entities'] != before
    execute = await app.call(actor, 'vibepublish_publication_update', refreshed['execute_args'])
    assert execute.get('state') == 'accepted', execute
    await worker.run_once()
    assert store.receipt(actor, execute['operation_id'])['state'] == 'verified'
    assert client.effects == effects + 1


@pytest.mark.asyncio
@pytest.mark.parametrize('execute', (False, True))
async def test_private_edit_preview_keeps_fresh_replacement_until_normal_asset_ttl(env, execute):
    _, fresh, _, _ = await published(env, siblings=False)
    replacement = env.assets[1]
    with env.store.connection() as db:
        image = db.execute('SELECT bytes,mime FROM assets WHERE id=?', (replacement,)).fetchone()
        assert {row['id']: row['reason'] for row in retired_asset_rows(db, env.now[0])}[replacement] == 'recent_unlinked'
    foreign = env.store.authenticate(env.store.create_principal('other-tenant', 'other-owner'))
    current = env.now[0]
    env.now[0] -= 15 * 86400
    foreign_asset = import_image(env.store, foreign, image['bytes'], image['mime'])
    unused_image = io.BytesIO()
    Image.new('RGB', (8, 8), 'green').save(unused_image, format='PNG')
    unused = import_image(env.store, env.actor, unused_image.getvalue(), 'image/png')
    env.now[0] = current
    args = update_args(env, fresh, key='retained-preview')
    args['change']['mode'] = 'preview'
    preview = await call(env, 'publication_update', args)
    assert preview.get('dry_run'), preview
    with env.store.tx() as db:
        rows = retired_asset_rows(db, env.now[0], include_sizes=False)
        reclaim_asset_bytes(db, rows)
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (replacement,)).fetchone(), rows
        assert not db.execute('SELECT 1 FROM assets WHERE id IN (?,?)', (foreign_asset, unused)).fetchall()
    if execute:
        accepted = await call(env, 'publication_update', preview['execute_args'])
        assert accepted.get('state') == 'accepted', accepted
        assert await env.worker.run_once()
        assert receipt(env, accepted)['state'] == 'verified'
        assert len(env.tg.effects) == 2
    else:
        env.now[0] += 15 * 86400
        with env.store.tx() as db:
            rows = retired_asset_rows(db, env.now[0])
            assert {row['id']: row['reason'] for row in rows}[replacement] == 'reclaim'
            reclaim_asset_bytes(db, rows)
            assert not db.execute('SELECT 1 FROM assets WHERE id=?', (replacement,)).fetchone()
            assert db.execute('SELECT complete FROM operations WHERE id=?',
                              (preview['operation_id'],)).fetchone()[0] == 1
