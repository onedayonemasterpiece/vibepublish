from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from adapters.fake import FakeProvider
from adapters.port import Capability, Prepared
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class NativePreviewAdapter:
    def __init__(self):
        self.prepares = 0
        self.executes = 0

    async def prepare(self, request, hooks):
        self.prepares += 1
        await hooks.emit_progress('validating', 'completed', 'Native preview preflight complete')
        return Prepared(
            request,
            Capability('supported', 'Native preview preflight', evidence='provider_read_preflight_only'),
        )

    async def execute(self, prepared, hooks):
        self.executes += 1
        raise AssertionError('preview must never execute a provider effect')


@pytest.mark.asyncio
async def test_bootstrap_support_requires_fresh_native_telegram_preview_preflight():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        store = Store(root / 'ledger.sqlite')
        token = store.create_principal('tenant', 'owner', owner=True)
        actor = store.authenticate(token)

        store.add_connection(actor, 'fake-telegram', 'telegram', account_type='fake', shared=True)
        store.bind(actor, 'owner', 'fake-preview', 'fake-telegram', 'fake-target')
        fake = FakeProvider(root / 'remote.sqlite', 'telegram')
        app = Application(store)
        fake_worker = Worker(store, {'fake-telegram': fake})

        fake_preview = await app.call(actor, 'vibepublish_publish', {
            'to': ['fake-preview'], 'content': {'text': 'Fixture'},
            'mode': 'preview', 'request_key': 'fake-preview-proof',
        })
        assert await fake_worker.run_once()
        fake_receipt = store.receipt(actor, fake_preview['operation_id'])
        assert fake_receipt['state'] == 'needs_approval'
        assert fake_receipt['dry_run'] is True
        assert fake.count('execute') == 0
        fake_bootstrap = await app.call(actor, 'vibepublish_get_started', {})
        fake_cap = next(row for row in fake_bootstrap['capabilities'] if row['destination'] == 'fake-preview')
        assert fake_cap['status'] == 'needs_review'

        store.add_connection(actor, 'native-telegram', 'telegram', account_type='mtproto_user', shared=True)
        store.bind(actor, 'owner', 'native-preview', 'native-telegram', 'native-target')
        before = await app.call(actor, 'vibepublish_get_started', {})
        native_dest = next(row for row in before['destinations'] if row['alias'] == 'native-preview')
        native_cap = next(row for row in before['capabilities'] if row['destination'] == 'native-preview')
        assert native_dest['provider'] == 'telegram'
        assert native_cap['status'] == 'needs_review'

        adapter = NativePreviewAdapter()
        native_worker = Worker(store, {'native-telegram': adapter})
        preview = await app.call(actor, 'vibepublish_publish', {
            'to': ['native-preview'], 'content': {'text': 'Fixture'},
            'mode': 'preview', 'request_key': 'native-preview-proof',
        })
        assert await native_worker.run_once()
        assert adapter.prepares == 1
        assert adapter.executes == 0
        receipt = store.receipt(actor, preview['operation_id'])
        assert receipt['state'] == 'needs_approval'
        assert receipt['dry_run'] is True

        supported = await app.call(actor, 'vibepublish_get_started', {})
        cap = next(row for row in supported['capabilities'] if row['destination'] == 'native-preview')
        assert cap['status'] == 'supported'

        with store.tx() as db:
            db.execute(
                'UPDATE operations SET created=? WHERE id=?',
                (store.clock() - 3601, preview['operation_id']),
            )
        expired = await app.call(actor, 'vibepublish_get_started', {})
        cap = next(row for row in expired['capabilities'] if row['destination'] == 'native-preview')
        assert cap['status'] == 'needs_review'

        store.add_connection(actor, 'native-vk', 'vk', account_type='vk_user', shared=True)
        store.bind(actor, 'owner', 'native-vk-preview', 'native-vk', 'vk-target')
        vk_adapter = NativePreviewAdapter()
        vk_worker = Worker(store, {'native-vk': vk_adapter})
        vk_preview = await app.call(actor, 'vibepublish_publish', {
            'to': ['native-vk-preview'], 'content': {'text': 'Fixture'},
            'mode': 'preview', 'request_key': 'native-vk-preview-proof',
        })
        assert await vk_worker.run_once()
        assert vk_adapter.prepares == 1
        assert vk_adapter.executes == 0
        vk_receipt = store.receipt(actor, vk_preview['operation_id'])
        assert vk_receipt['state'] == 'needs_approval'
        after_vk = await app.call(actor, 'vibepublish_get_started', {})
        vk_dest = next(row for row in after_vk['destinations'] if row['alias'] == 'native-vk-preview')
        vk_cap = next(row for row in after_vk['capabilities'] if row['destination'] == 'native-vk-preview')
        assert vk_dest['provider'] == 'vk'
        assert vk_cap['status'] == 'needs_review'
