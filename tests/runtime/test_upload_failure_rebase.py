"""VK upload failure is retried by the original worker, not a manual rebase."""
from unittest.mock import AsyncMock

import pytest

from social_operations.domain import DomainError
from .test_baseline_rebase import scenario


async def prepared_edit(tmp_path, *, code='vk_http_failed'):
    store, actor, app, worker, transport, native, desired, failed, args, now = await scenario(tmp_path)
    rebased = await app.call(actor, 'vibepublish_publication_update', args)
    assert rebased['state'] == 'verified'
    original_upload = transport.upload_photo
    transport.upload_photo = AsyncMock(side_effect=DomainError(code))
    edit = await app.call(actor, 'vibepublish_publication_update', {
        'publication_id': args['publication_id'], 'expected_revision': 3,
        'change': desired, 'request_key': 'upload-failure'})
    assert 'operation_id' in edit, edit
    await worker.run_once()
    return store, actor, app, worker, transport, native, desired, edit, now, original_upload


@pytest.mark.asyncio
async def test_transient_vk_upload_auto_resumes_same_attempt_without_extra_post(tmp_path):
    store, actor, app, worker, transport, native, desired, edit, now, upload = await prepared_edit(tmp_path)
    first = store.receipt(actor, edit['operation_id'])
    assert first['state'] == 'running', first
    with store.connection() as db:
        child = db.execute('SELECT id,dispatched FROM attempts WHERE operation_id=?',
                           (edit['operation_id'],)).fetchone()
        assert child['dispatched'] == 0
        original_attempt = child['id']
    assert transport.effects == 1
    transport.upload_photo = upload
    now[0] += 5.001
    await worker.run_once()
    final = store.receipt(actor, edit['operation_id'])
    assert final['state'] == 'verified', final
    assert final['operation_complete']
    assert transport.effects == 2
    assert list(transport.posts) == [native]
    assert len(transport.posts[native]['attachments']) == 4
    with store.connection() as db:
        assert db.execute('SELECT id FROM attempts WHERE operation_id=?',
                          (edit['operation_id'],)).fetchone()[0] == original_attempt
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_continuous_transient_upload_expires_without_send_or_deadline_renewal(tmp_path):
    store, actor, app, worker, transport, native, desired, edit, now, upload = await prepared_edit(tmp_path)
    with store.connection() as db:
        deadline, created = db.execute('SELECT deadline,created FROM operations WHERE id=?',
                                       (edit['operation_id'],)).fetchone()
    now[0] += 901
    await worker.run_once()
    result = store.receipt(actor, edit['operation_id'])
    assert result['state'] == 'blocked', result
    assert result['operation_complete']
    assert result['deliveries'][0]['missing_checks'] == ['command_expired']
    assert transport.effects == 1
    with store.connection() as db:
        assert db.execute('SELECT deadline FROM operations WHERE id=?',
                          (edit['operation_id'],)).fetchone()[0] == deadline
        assert deadline - created == 390


@pytest.mark.asyncio
async def test_invalid_upload_target_is_permanent_and_never_resends(tmp_path):
    store, actor, app, worker, transport, native, desired, edit, now, upload = await prepared_edit(
        tmp_path, code='vk_upload_url_invalid')
    result = store.receipt(actor, edit['operation_id'])
    assert result['state'] == 'blocked', result
    assert result['operation_complete']
    assert result['deliveries'][0]['missing_checks'] == ['vk_upload_url_invalid']
    assert transport.effects == 1
    now[0] += 120
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_external_native_change_during_retry_is_not_overwritten(tmp_path):
    store, actor, app, worker, transport, native, desired, edit, now, upload = await prepared_edit(tmp_path)
    transport.posts[native]['text'] = 'Another owner change'
    transport.upload_photo = upload
    now[0] += 5.001
    await worker.run_once()
    result = store.receipt(actor, edit['operation_id'])
    assert result['state'] == 'blocked', result
    assert result['deliveries'][0]['missing_checks'] == ['remote_revision_conflict']
    assert transport.effects == 1
