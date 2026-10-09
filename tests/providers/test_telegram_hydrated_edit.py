"""Native Telegram edit CAS when a read added downloaded-photo evidence."""
from dataclasses import replace

import pytest

from adapters.port import DownloadedMedia
from social_operations.domain import DomainError, canonical
from tests.providers.test_native_adapters import asset, request, setup


@pytest.mark.asyncio
async def test_published_photo_caption_edit_preserves_native_photo_after_read_hydration():
    adapter, client, journal = setup('telegram')
    original = asset(1)
    posted = (await adapter.execute(
        await adapter.prepare(request('telegram', assets=(original,)), journal.hooks),
        journal.hooks)).items[0]

    journal.markers.clear()  # Inspect the edit's own dispatch marker only.

    # Provider-backed read hydrates private downloaded bytes; exact MTProto
    # get_messages does not. This must not fake a remote revision change.
    evidence = DownloadedMedia(slot=0, sha256='b' * 64,
                               mime='image/jpeg', size=123)
    read_snapshot = replace(posted, media_hashes=(), observed_media=(evidence,))
    edit = request('telegram', action='edit', existing=read_snapshot,
                   content_json=canonical({'text': 'Edited caption, no bare URL'}))
    prepared = await adapter.prepare(edit, journal.hooks)
    result = await adapter.execute(prepared, journal.hooks)

    assert result.observed == 'edited'
    assert result.items[0].native_id == posted.native_id
    assert result.items[0].provider_media == posted.provider_media
    assert result.items[0].text == 'Edited caption, no bare URL'
    assert len(client.uploads) == 1  # Original only, no photo replacement.


@pytest.mark.asyncio
async def test_published_photo_native_media_replacement_still_conflicts():
    adapter, client, journal = setup('telegram')
    original = asset(2)
    posted = (await adapter.execute(
        await adapter.prepare(request('telegram', assets=(original,)), journal.hooks),
        journal.hooks)).items[0]
    journal.markers.clear()
    evidence = DownloadedMedia(slot=0, sha256='b' * 64,
                               mime='image/jpeg', size=123)
    read_snapshot = replace(posted, media_hashes=(), observed_media=(evidence,))
    client.messages[(101, int(posted.native_id))].media.photo.id += 1
    edit = request('telegram', action='edit', existing=read_snapshot,
                   content_json=canonical({'text': 'Must not edit changed photo'}))
    with pytest.raises(DomainError) as error:
        await adapter.prepare(edit, journal.hooks)
    assert error.value.code == 'remote_revision_conflict'
    assert not journal.markers  # Refused edit has no dispatch.
