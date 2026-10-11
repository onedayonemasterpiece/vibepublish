"""Native Telegram replacement keeps the message identity and rechecks its CAS."""
from dataclasses import replace
import pytest

from adapters.telegram_direct import DirectTargetTelegramAdapter
from social_operations.domain import DomainError, OutcomeUnknown, canonical
from tests.providers.scripted import ScriptedTL, obj
from tests.providers.test_native_adapters import NOW, Journal, request, TARGETS
from tests.providers.test_native_video import VideoTG, video_asset
from tests.providers.test_max_content_video import video_bytes


class EditingVideoTG(VideoTG):
    bad_readback = False

    async def __call__(self, req):
        result = await super().__call__(req)
        kind = type(req).__name__
        if kind == 'UploadMediaRequest':
            result.document.id = 500 + len(self.uploads)
        elif kind in {'SendMediaRequest', 'EditMessageRequest'} and hasattr(req, 'media'):
            ident = req.id if kind == 'EditMessageRequest' else self.next_id
            self.messages[(req.peer.id, ident)].media = obj('MessageMediaDocument',
                document=obj('Document', id=req.media.id.id + int(self.bad_readback), mime_type='video/mp4'))
        return result


async def prepared_edit(data):
    client, journal = EditingVideoTG(), Journal()
    adapter = DirectTargetTelegramAdapter(client, connection_id='connection', tl=ScriptedTL(),
        clock=lambda: NOW, bound_targets=(TARGETS['telegram'],))
    initial = request('telegram', assets=(video_asset(data),))
    posted = (await adapter.execute(await adapter.prepare(initial, journal.hooks), journal.hooks)).items[0]
    edit = request('telegram', action='edit', existing=replace(posted, media_hashes=()),
        assets=(video_asset(data),), content_json=canonical({'text': 'Replacement video caption'}))
    journal.markers.clear()
    client.calls.clear()
    return adapter, client, journal, edit, posted


@pytest.mark.asyncio
async def test_managed_video_uses_one_native_edit_and_same_message(video_bytes):
    adapter, client, journal, edit, posted = await prepared_edit(video_bytes)
    result = await adapter.execute(await adapter.prepare(edit, journal.hooks), journal.hooks)
    assert result.observed == 'edited'
    assert result.items[0].native_id == posted.native_id
    assert result.items[0].provider_media == ('document:502',)
    assert result.items[0].media_hashes == (edit.assets[0].sha256,)
    mutations = [(name, req) for name, req in client.calls if name in client.MUTATIONS]
    assert [name for name, _ in mutations] == ['EditMessageRequest']
    assert mutations[0][1].id == int(posted.native_id)
    assert len(client.messages) == 1 and len(client.uploads) == 2
    assert len(journal.markers) == 1


@pytest.mark.asyncio
async def test_managed_video_native_change_during_upload_blocks_edit(video_bytes):
    adapter, client, journal, edit, posted = await prepared_edit(video_bytes)
    prepared = await adapter.prepare(edit, journal.hooks)
    upload = client.upload_file

    async def changed_during_upload(*args, **kwargs):
        result = await upload(*args, **kwargs)
        client.messages[(101, int(posted.native_id))].message = 'External change during staging'
        return result

    client.upload_file = changed_during_upload
    with pytest.raises(DomainError) as raised:
        await adapter.execute(prepared, journal.hooks)
    assert raised.value.code == 'remote_revision_conflict'
    assert not journal.markers
    assert not any(name in client.MUTATIONS for name, _ in client.calls)
    assert client.messages[(101, int(posted.native_id))].message == 'External change during staging'


@pytest.mark.asyncio
async def test_managed_video_wrong_native_media_never_verifies(video_bytes):
    adapter, client, journal, edit, posted = await prepared_edit(video_bytes)
    client.bad_readback = True
    with pytest.raises(OutcomeUnknown):
        await adapter.execute(await adapter.prepare(edit, journal.hooks), journal.hooks)
    assert len(journal.markers) == 1
    assert len(client.messages) == 1
    assert len([name for name, _ in client.calls if name == 'EditMessageRequest']) == 1
