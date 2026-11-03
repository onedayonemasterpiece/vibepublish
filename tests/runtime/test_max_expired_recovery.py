"""MAX observation keeps its original effect and does not need expired input bytes."""
import base64
import json

import pytest

from adapters.fake import FakeProvider
from adapters.native import saved_checkpoint
from adapters.port import Capability
from social_operations.assets import import_image
from social_operations.domain import OutcomeUnknown
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


@pytest.mark.asyncio
async def test_original_max_recovery_reads_provider_after_asset_expiry_and_finalizes(tmp_path):
    now = [1800000000.0]
    store = Store(tmp_path / 'ledger.sqlite', clock=lambda: now[0])
    actor = store.authenticate(store.create_principal('t', 'owner', owner=True))
    store.add_connection(actor, 'max', 'max', account_type='max_web', secret_ref='VIBEPUBLISH_MAX_PROFILE')
    store.bind(actor, 'owner', 'max', 'max', 'target')
    app = Application(store)
    image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==')
    asset = import_image(store, actor, image, 'image/png')

    class NativeReceipt(FakeProvider):
        unknown = True
        finalized = False

        async def inspect(self, request):
            return Capability('supported', 'Explicit offline native-receipt regression')

        async def reconcile(self, request, checkpoint, hooks):
            self.record('native_read')
            observed = await super().reconcile(request, checkpoint, hooks)
            if self.unknown:
                await hooks.checkpoint('MAX_NATIVE_REFERENCE', saved_checkpoint(request,
                    driver={'native_id': observed.items[0].native_id}))
                raise OutcomeUnknown('receipt_lost')
            return observed

        async def finalize(self, request, checkpoint, hooks):
            self.finalized = True

    provider = NativeReceipt(tmp_path / 'remote.sqlite', 'max', clock=lambda: now[0])
    worker = Worker(store, {'max': provider})
    receipt = await app.call(actor, 'vibepublish_publish', {
        'to': ['max'], 'content': {'text': 'Frozen original'},
        'media': [{'source': {'kind': 'asset', 'id': asset}}]})
    await worker.run_once()
    with store.tx() as db:
        child = db.execute('SELECT * FROM attempts').fetchone()
        original = db.execute('SELECT original_checkpoint FROM attempt_recovery WHERE attempt_id=?', (child['id'],)).fetchone()
        if original:
            db.execute('UPDATE attempts SET checkpoint=? WHERE id=?', (original[0], child['id']))
        db.execute("UPDATE attempts SET state='outcome_unknown',observed='unknown'")
        db.execute("UPDATE operations SET state='outcome_unknown',complete=1,work_state='done'")
        db.execute('DELETE FROM assets WHERE id=?', (asset,))
    provider.finalized = False
    reads = provider.count('native_read')
    now[0] += 20 * 86400
    provider.unknown = False
    accepted = await app.call(actor, 'vibepublish_publication_update', {
        'publication_id': receipt['resource_id'], 'expected_revision': 1,
        'change': {'kind': 'reconcile', 'operation_id': receipt['operation_id']},
        'request_key': 'same-original-observation'})
    assert accepted['operation_id'] == receipt['operation_id']
    await worker.run_once()
    result = store.receipt(actor, receipt['operation_id'])
    assert provider.count('native_read') == reads + 1, result
    assert provider.finalized, result
    assert result['state'] == 'verified' and result['operation_complete'], result
    assert provider.count('effect') == 1
