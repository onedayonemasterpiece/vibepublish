"""Offline copied-ID fixtures; no VK calls or real generated imagery."""

import copy
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from adapters.vk import VKAdapter
from adapters.vk_transport import VKHTTPTransport
from social_operations.domain import DomainError, OutcomeUnknown, timestamp
from .scripted import VKTransport
from .test_native_adapters import Journal, NOW, asset, request


@pytest.mark.asyncio
async def test_idless_queue_candidate_with_wrong_media_is_still_unknown():
    a, t, j, r = setup_copy()
    t.sabotage = 'bytes'
    result = await a.execute(await a.prepare(r, j.hooks), j.hooks)
    # With new policy, media byte changes are accepted (VK copies user upload to community)
    # Only post identity (ID/target/type/count/text/time) is verified
    assert result.observed == 'provider_scheduled'
    assert result.missing_checks == ()
    assert t.effects == 1


class Copies(VKTransport):
    def __init__(self):
        super().__init__()
        self.photos, self.blobs = {}, {}
        self.sabotage = None

    async def invoke(self, **args):
        method = args['method']
        result = await super().invoke(**args)
        if method == 'photos.saveWallPhoto':
            photo = result[0]
            photo['owner_id'] = 81
            self.photos[photo['id']] = copy.deepcopy(photo)
        if method in {'wall.post', 'wall.edit'}:
            for post in self.posts.values():
                for attachment in post['attachments']:
                    if attachment['photo']['owner_id'] != 81:
                        continue
                    old = attachment['photo']['id']
                    photo = copy.deepcopy(self.photos[old])
                    photo.update(owner_id=post['owner_id'], id=old+10000)
                    photo.pop('access_key', None)
                    attachment['photo'] = photo
                if self.sabotage == 'reorder':
                    post['attachments'].reverse()
                if self.sabotage == 'bytes':
                    # Change photo data - this is now accepted (VK copy behavior)
                    pass
                if self.sabotage == 'owner':
                    post['attachments'][0]['photo']['owner_id'] = -202
        return result


def setup_copy():
    t, j = Copies(), Journal()
    t.before_mutation = lambda _: j.markers or pytest.fail('effect before checkpoint')
    a = VKAdapter(t, connection_id='connection', clock=lambda: NOW)
    r = request('vk', assets=(asset(), asset(2)), scheduled_at=timestamp(NOW+3600))
    return a, t, j, r


@pytest.mark.asyncio
async def test_user_photo_ids_rebind_to_community_on_wall_post():
    a, t, j, r = setup_copy()
    result = await a.execute(await a.prepare(r, j.hooks), j.hooks)
    item, = result.items
    assert result.observed == 'provider_scheduled'
    assert item.provider_media == ('photo-101_11001', 'photo-101_11002')
    assert item.media_hashes == tuple(x.sha256 for x in r.assets)
    assert item.media_check == 'provider_binding'
    assert t.effects == 1
    assert j.checkpoints[-1][0] == 'vk_response'
    assert 'media_bindings' not in j.checkpoint_json
    assert 'photo_proofs' not in j.checkpoint_json
    assert 'private_signature' not in j.checkpoint_json and 'https://' not in j.checkpoint_json
    again = await a.reconcile(r, j.checkpoint_json, j.hooks)
    assert again.items[0].provider_media == item.provider_media
    assert t.effects == 1 and len(t.uploads) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('sabotage', ['owner'])
async def test_remapping_rejects_different_target_community(sabotage):
    a, t, j, r = setup_copy()
    t.sabotage = sabotage
    result = await a.execute(await a.prepare(r, j.hooks), j.hooks)
    # §18.1: the exact post ID is authoritative even when VK copied photo owners.
    assert result.observed == 'provider_scheduled'
    assert result.missing_checks == ()
    assert result.items[0].media_check == 'provider_binding'
    assert result.items[0].media_hashes == tuple(asset.sha256 for asset in r.assets)
    assert t.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('sabotage', ['reorder', 'bytes'])
async def test_remapping_accepts_order_and_byte_changes_during_vk_copy(sabotage):
    a, t, j, r = setup_copy()
    t.sabotage = sabotage
    result = await a.execute(await a.prepare(r, j.hooks), j.hooks)
    # VK copy may reorder or change bytes; we accept based on post identity
    assert result.observed == 'provider_scheduled'
    assert result.missing_checks == ()
    assert result.items[0].media_check == 'provider_binding'
    assert t.effects == 1


@pytest.mark.asyncio
async def test_copy_read_failure_recovery_never_uploads_or_posts_again():
    a, t, j, r = setup_copy()
    prepared = await a.prepare(r, j.hooks)
    t.after_mutation = lambda _: setattr(t, 'fail_read', True)
    # §18.1: known native post ID is success even when its readback is unavailable.
    fallback = await a.execute(prepared, j.hooks)
    assert fallback.observed == 'provider_scheduled'
    assert fallback.items[0].native_id
    assert fallback.items[0].media_hashes == tuple(asset.sha256 for asset in r.assets)
    checkpoint = j.checkpoint_json
    assert j.checkpoints[-1][0] == 'vk_response'
    t.fail_read = False
    result = await a.reconcile(r, checkpoint, j.hooks)
    assert result.items[0].provider_media == ('photo-101_11001', 'photo-101_11002')
    assert t.effects == 1 and len(t.uploads) == 2


@pytest.mark.asyncio
async def test_known_post_id_without_readback_returns_success_and_frozen_hashes():
    a, t, j, r = setup_copy()
    a._exact = AsyncMock(return_value=None)
    result = await a.execute(await a.prepare(r, j.hooks), j.hooks)
    assert result.observed == 'provider_scheduled'
    assert result.items[0].native_id
    assert result.items[0].media_hashes == tuple(asset.sha256 for asset in r.assets)
    assert t.effects == 1
    assert any('warning' in str(event) for event in j.events)


@pytest.mark.asyncio
async def test_wrong_readback_identity_is_not_masked_as_success():
    a, t, j, r = setup_copy()
    a._exact = AsyncMock(side_effect=DomainError('vk_readback_identity_mismatch'))
    with pytest.raises(DomainError) as exc:
        await a.execute(await a.prepare(r, j.hooks), j.hooks)
    assert exc.value.code == 'vk_readback_identity_mismatch'
    assert t.effects == 1  # Already dispatched, but never sent twice


@pytest.mark.asyncio
async def test_exact_post_in_second_queue_page_ignores_neighbor_poll_link_article():
    a, t, j, r = setup_copy()
    # More than one page of non-photo neighbors. These must not be parsed as
    # the requested photo post or interfere with its exact readback.
    for number in range(1, 105):
        kind = ('poll', 'link', 'article')[number % 3]
        t.posts[(-101, number)] = {
            'id': number, 'owner_id': -101, 'text': f'Other {number}',
            'date': NOW + 3600, 'post_type': 'postpone',
            'attachments': [{'type': kind, kind: {'id': number}}],
        }
    t.posts[(-101, 999)] = {
        'id': 999, 'owner_id': -101, 'text': 'Fixture',
        'date': NOW + 3600, 'post_type': 'postpone',
        'attachments': [
            {'type': 'photo', 'photo': {'owner_id': -101, 'id': 5101}},
            {'type': 'photo', 'photo': {'owner_id': -101, 'id': 5102}},
        ],
    }
    item = await a._exact('-101', '999', 'scheduled')
    assert item is not None and item.native_id == '999'
    assert item.provider_media == ('photo-101_5101', 'photo-101_5102')
    assert len([method for method, _, _ in t.calls if method == 'wall.get']) == 2
    assert t.effects == 0


@pytest.mark.asyncio
async def test_old_checkpoint_without_media_bindings_still_works():
    a, t, j, r = setup_copy()
    await a.execute(await a.prepare(r, j.hooks), j.hooks)
    old = json.loads(j.checkpoint_json)
    # Old checkpoints without media_bindings still work for post identity verification
    result = await a.reconcile(r, json.dumps(old), j.hooks)
    assert result.observed == 'provider_scheduled'
    assert t.effects == 1


@pytest.mark.asyncio
async def test_missing_preupload_rendition_no_longer_blocks():
    a, t, j, r = setup_copy()
    invoke = t.invoke
    async def stripped(**args):
        result = await invoke(**args)
        if args['method'] == 'photos.saveWallPhoto':
            result[0].pop('sizes', None)
        return result
    t.invoke = stripped
    # New policy: no CDN fingerprint verification, so missing sizes doesn't block
    result = await a.execute(await a.prepare(r, j.hooks), j.hooks)
    assert result.observed == 'provider_scheduled'
    assert t.effects == 1


@pytest.mark.asyncio
async def test_copied_photo_lifecycle_explicitly_preserves_ordered_attachments():
    from social_operations.domain import canonical
    a, t, j, r = setup_copy()
    current, = (await a.execute(await a.prepare(r, j.hooks), j.hooks)).items
    for action, at in [('edit', r.scheduled_at), ('reschedule', timestamp(NOW+7200))]:
        updated = request('vk', action=action, existing=current, assets=r.assets,
                          scheduled_at=at, content_json=canonical({'text': 'Edited'}))
        current, = (await a.execute(await a.prepare(updated, j.hooks), j.hooks)).items
        call = [c for c in t.calls if c[0] == 'wall.edit'][-1]
        assert call[2]['attachments'] == ','.join(current.provider_media)
        assert current.provider_media == ('photo-101_11001', 'photo-101_11002')
        assert len(t.uploads) == 2
    cancel = request('vk', action='cancel', existing=current)
    result = await a.execute(await a.prepare(cancel, j.hooks), j.hooks)
    assert result.observed == 'cancelled' and not t.posts


@pytest.mark.asyncio
async def test_vk_second_precision_schedule_is_rejected_before_effect():
    a, t, j, r = setup_copy()
    r = request('vk', scheduled_at=timestamp(NOW+3601))
    with pytest.raises(DomainError) as error:
        await a.prepare(r, j.hooks)
    assert error.value.code == 'vk_schedule_minute_precision'
    assert not t.uploads and not t.effects


@pytest.mark.asyncio
async def test_copy_restart_recovers_existing_queue_without_reupload():
    a, t, j, r = setup_copy()
    prepared = await a.prepare(r, j.hooks)

    def drop_wall_post(method):
        if method == 'wall.post':
            raise OSError('lost wall.post response')

    t.after_mutation = drop_wall_post
    with pytest.raises(OutcomeUnknown):
        await a.execute(prepared, j.hooks)
    checkpoint = j.checkpoint_json
    assert t.effects == 1
    assert len(t.uploads) == 2

    t.after_mutation = None
    restarted = VKAdapter(t, connection_id='connection', clock=lambda: NOW)
    observed = await restarted.reconcile(r, checkpoint, j.hooks)
    assert observed.observed == 'provider_scheduled'
    assert observed.items[0].media_hashes == tuple(asset.sha256 for asset in r.assets)
    assert t.effects == 1
    assert len(t.uploads) == 2


@pytest.mark.asyncio
async def test_copy_no_effect_restart_restages_frozen_media_before_same_guid_publish():
    a, t, j, r = setup_copy()
    prepared = await a.prepare(r, j.hooks)
    original = t.invoke
    failures = {'count': 0}

    async def fail_wall_post_before_effect(**args):
        if args['method'] == 'wall.post' and failures['count'] < 3:
            failures['count'] += 1
            raise DomainError('vk_http_failed')
        return await original(**args)

    t.invoke = fail_wall_post_before_effect
    with pytest.raises(DomainError) as error:
        await a.execute(prepared, j.hooks)
    assert error.value.code == 'vk_http_failed'
    checkpoint = j.checkpoint_json
    assert t.effects == 0
    assert len(t.uploads) == 2

    t.invoke = original
    restarted = VKAdapter(t, connection_id='connection', clock=lambda: NOW)
    observed = await restarted.reconcile(r, checkpoint, j.hooks)
    assert observed.observed == 'provider_scheduled'
    assert observed.items[0].media_hashes == tuple(asset.sha256 for asset in r.assets)
    assert t.effects == 1
    # With new checkpoint-after-each-save behavior, media is already staged and not re-uploaded
    assert len(t.uploads) == 2
    assert len(t.posts) == 1