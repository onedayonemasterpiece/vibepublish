"""Public native media changes must not need copies of already published photos."""
from dataclasses import replace
import io
import json

import pytest
from PIL import Image

from adapters.native import identity
from adapters.port import Capability, Observation, Prepared, RemoteItem
from social_operations.assets import import_image
from social_operations.domain import DomainError, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class NativePhoto:
    def __init__(self, clock):
        self.clock = clock
        self.current = None
        self.effects = []

    async def prepare(self, request, hooks):
        if request.existing and identity(request.existing) != identity(self.current):
            raise DomainError('remote_revision_conflict')
        return Prepared(request, Capability('supported', 'native identity fixture'))

    async def execute(self, prepared, hooks):
        r = prepared.request
        await hooks.before_effect(r.attempt_id, r.plan_digest)
        self.effects.append(r)
        media = (tuple('photo:fixture' for _ in r.assets) if r.assets
                 else self.current.provider_media if self.current else ())
        item = RemoteItem(self.current.native_id if self.current else '100',
                          'scheduled' if r.scheduled_at else 'published',
                          json.loads(r.content_json)['text'], '', timestamp(self.clock()),
                          scheduled_at=r.scheduled_at, native_target=r.native_target,
                          provider_media=media, media_check='provider_binding' if media else 'not_applicable')
        self.current = replace(item, fingerprint=identity(item))
        observed = 'provider_scheduled' if r.scheduled_at else 'edited' if r.existing else 'published'
        return Observation(observed, (self.current,))


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['telegram', 'max'])
@pytest.mark.parametrize('scheduled', [False, True])
async def test_caption_and_queue_edits_reuse_native_media_after_byte_cleanup(tmp_path, provider, scheduled):
    clock = [1800000000.0]
    store = Store(tmp_path / 'post.sqlite', clock=lambda: clock[0])
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    store.add_connection(actor, provider, provider, account_type='fake')
    store.bind(actor, actor.principal_id, provider, provider, '-1001000000100',
               rights=('publish', 'edit', 'reschedule'))
    stream = io.BytesIO()
    Image.new('RGB', (10, 10), 'red').save(stream, 'PNG')
    asset_id = import_image(store, actor, stream.getvalue(), 'image/png')
    native = NativePhoto(store.clock)
    worker = Worker(store, {provider: native})
    app = Application(store)
    published = await app.call(actor, 'vibepublish_publish', {
        'to': [provider], 'content': {'text': 'Before'},
        'media': [{'source': {'kind': 'asset', 'id': asset_id}}],
        **({'delivery': {'kind': 'at', 'at': timestamp(clock[0]+3600)}} if scheduled else {}),
        'request_key': 'first'})
    assert 'error' not in published, published
    assert await worker.run_once()
    assert store.receipt(actor, published['operation_id'])['state'] in {'verified', 'scheduled'}
    # This is the real production worker cleanup, not manual deletion.
    clock[0] += 61
    assert not await worker.run_once()
    with store.connection() as db:
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (asset_id,)).fetchone() is None
    changed = await app.call(actor, 'vibepublish_publication_update', {
        'publication_id': published['resource_id'], 'expected_revision': 1,
        'change': {'kind': 'edit', 'content': {'text': 'After'}},
        'request_key': 'caption'})
    assert 'error' not in changed, changed
    assert await worker.run_once()
    assert store.receipt(actor, changed['operation_id'])['state'] in {'verified', 'scheduled'}
    assert native.current.provider_media == ('photo:fixture',)
    assert native.current.text == 'After'
    assert native.effects[-1].assets == ()
    if scheduled:
        rescheduled = await app.call(actor, 'vibepublish_publication_update', {
            'publication_id': published['resource_id'], 'expected_revision': 2,
            'change': {'kind': 'reschedule',
                       'delivery': {'kind': 'at', 'at': timestamp(clock[0]+7200)}},
            'request_key': 'later'})
        assert 'error' not in rescheduled, rescheduled
        assert await worker.run_once()
        assert store.receipt(actor, rescheduled['operation_id'])['state'] == 'scheduled'
        assert native.current.provider_media == ('photo:fixture',)
        assert native.effects[-1].assets == ()
    rejected = await app.call(actor, 'vibepublish_publication_update', {
        'publication_id': published['resource_id'], 'expected_revision': 3 if scheduled else 2,
        'change': {'kind': 'edit', 'media': []},
        'request_key': 'forbidden-remove'})
    assert rejected['error']['code'] == 'media_removal_needs_review'
    assert len(native.effects) == (3 if scheduled else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize('scheduled', [False, True])
async def test_telegram_native_caption_and_reschedule_keep_photo_without_upload(scheduled):
    from tests.providers.test_native_adapters import setup, asset, request, NOW
    from social_operations.domain import timestamp
    adapter, transport, journal = setup('telegram')
    first = request('telegram', assets=(asset(),),
                    scheduled_at=timestamp(NOW + 3600) if scheduled else None)
    remote = (await adapter.execute(await adapter.prepare(first, journal.hooks), journal.hooks)).items[0]
    uploads = len(transport.uploads)
    journal.markers.clear()
    edit = request('telegram', action='edit', existing=remote,
                   scheduled_at=remote.scheduled_at,
                   content_json=json.dumps({'text': 'New caption'}))
    changed = (await adapter.execute(await adapter.prepare(edit, journal.hooks), journal.hooks)).items[0]
    assert changed.provider_media == remote.provider_media
    assert len(transport.uploads) == uploads and len(journal.markers) == 1
    if scheduled:
        journal.markers.clear()
        later = request('telegram', action='reschedule', existing=changed,
                        scheduled_at=timestamp(NOW + 7200),
                        content_json=json.dumps({'text': 'New caption'}))
        changed = (await adapter.execute(await adapter.prepare(later, journal.hooks), journal.hooks)).items[0]
        assert changed.scheduled_at == later.scheduled_at
        assert changed.provider_media == remote.provider_media
        assert len(transport.uploads) == uploads and len(journal.markers) == 1
    calls = [call for call in transport.calls if call[0] == 'EditMessageRequest']
    assert len(calls) == (2 if scheduled else 1)
    assert all(getattr(call[1], 'media', None) is None for call in calls)
