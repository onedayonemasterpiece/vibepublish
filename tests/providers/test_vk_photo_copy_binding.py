"""Offline copied-ID fixtures; no VK calls or real generated imagery."""
import copy
import hashlib

import pytest

from adapters.vk import VKAdapter
from adapters.vk_transport import VKHTTPTransport
from social_operations.assets import verify_image
from social_operations.domain import DomainError, OutcomeUnknown, timestamp
from .scripted import VKTransport
from .test_native_adapters import Journal, NOW, asset, request


class Copies(VKTransport):
    def __init__(self):
        super().__init__()
        self.photos, self.blobs, self.downloads = {}, {}, []
        self.sabotage = None

    async def image_fingerprint(self, url):
        self.downloads.append(url)
        data = self.blobs[url]
        image = verify_image(data, 'image/png')
        return {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
                'mime': 'image/png', 'width': image.width, 'height': image.height}

    async def invoke(self, **args):
        method = args['method']
        result = await super().invoke(**args)
        if method == 'photos.saveWallPhoto':
            photo = result[0]
            photo['owner_id'] = 81
            url = f'https://cdn.userapi.com/saved/{photo["id"]}?private_signature=source'
            self.blobs[url] = self.uploads[-1]
            photo['sizes'] = [{'url': url, 'width': 4, 'height': 4}]
            self.photos[photo['id']] = copy.deepcopy(photo)
        if method in {'wall.post', 'wall.edit'}:
            for post in self.posts.values():
                for attachment in post['attachments']:
                    if attachment['photo']['owner_id'] != 81:
                        continue
                    old = attachment['photo']['id']
                    photo = copy.deepcopy(self.photos[old])
                    source = photo['sizes'][0]['url']
                    url = f'https://cdn.userapi.com/copied/{old}?private_signature=copy'
                    self.blobs[url] = self.blobs[source]
                    photo.update(owner_id=post['owner_id'], id=old+10000,
                                 sizes=[{'url': url, 'width': 4, 'height': 4}])
                    photo.pop('access_key', None)
                    attachment['photo'] = photo
                if self.sabotage == 'reorder':
                    post['attachments'].reverse()
                if self.sabotage == 'bytes':
                    self.blobs[post['attachments'][0]['photo']['sizes'][0]['url']] = asset(9).data
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
async def test_user_photo_ids_rebind_by_exact_ordered_provider_bytes():
    a, t, j, r = setup_copy()
    result = await a.execute(await a.prepare(r, j.hooks), j.hooks)
    item, = result.items
    assert result.observed == 'provider_scheduled'
    assert item.provider_media == ('photo-101_11001', 'photo-101_11002')
    assert item.media_hashes == tuple(x.sha256 for x in r.assets)
    assert item.media_check == 'provider_binding'
    assert t.effects == 1 and len(t.downloads) == 4
    assert j.checkpoints[-1][0] == 'vk_media_bound'
    proof = j.checkpoints[-1][1]
    assert [x['saved'] for x in proof['media_bindings']] == ['photo81_1001', 'photo81_1002']
    assert 'private_signature' not in j.checkpoint_json and 'https://' not in j.checkpoint_json
    again = await a.reconcile(r, j.checkpoint_json, j.hooks)
    assert again.items[0].provider_media == item.provider_media
    assert t.effects == 1 and len(t.uploads) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('sabotage', ['reorder', 'bytes', 'owner'])
async def test_remapping_does_not_accept_changed_images_order_or_owner(sabotage):
    a, t, j, r = setup_copy()
    t.sabotage = sabotage
    with pytest.raises(OutcomeUnknown) as error:
        await a.execute(await a.prepare(r, j.hooks), j.hooks)
    assert error.value.code == 'media_identity_or_order_mismatch'
    assert t.effects == 1


@pytest.mark.asyncio
async def test_copy_read_failure_recovery_never_uploads_or_posts_again():
    a, t, j, r = setup_copy()
    prepared = await a.prepare(r, j.hooks)
    t.after_mutation = lambda _: setattr(t, 'fail_read', True)
    with pytest.raises(OSError):
        await a.execute(prepared, j.hooks)
    checkpoint = j.checkpoint_json
    assert j.checkpoints[-1][0] == 'vk_response'
    t.fail_read = False
    result = await a.reconcile(r, checkpoint, j.hooks)
    assert result.items[0].provider_media == ('photo-101_11001', 'photo-101_11002')
    assert t.effects == 1 and len(t.uploads) == 2


@pytest.mark.asyncio
async def test_old_checkpoint_cannot_invent_copy_proof():
    import json
    a, t, j, r = setup_copy()
    await a.execute(await a.prepare(r, j.hooks), j.hooks)
    old = json.loads(j.checkpoint_json)
    old['adapter'].pop('photo_proofs')
    with pytest.raises(OutcomeUnknown):
        await a.reconcile(r, json.dumps(old), j.hooks)
    assert t.effects == 1


@pytest.mark.asyncio
async def test_missing_preupload_rendition_blocks_before_wall_post():
    a, t, j, r = setup_copy()
    invoke = t.invoke
    async def stripped(**args):
        result = await invoke(**args)
        if args['method'] == 'photos.saveWallPhoto':
            result[0].pop('sizes')
        return result
    t.invoke = stripped
    with pytest.raises(DomainError) as error:
        await a.execute(await a.prepare(r, j.hooks), j.hooks)
    assert error.value.code == 'vk_photo_binding_unavailable'
    assert t.effects == 0


@pytest.mark.asyncio
async def test_copy_proof_detects_post_change_during_download():
    a, t, j, r = setup_copy()
    fingerprint = t.image_fingerprint
    async def changing(url):
        proof = await fingerprint(url)
        if '/copied/' in url:
            next(iter(t.posts.values()))['text'] = 'external edit'
        return proof
    t.image_fingerprint = changing
    with pytest.raises(OutcomeUnknown) as error:
        await a.execute(await a.prepare(r, j.hooks), j.hooks)

    assert error.value.code == 'vk_photo_binding_item_changed'


@pytest.mark.asyncio
async def test_cdn_reader_does_not_accept_arbitrary_urls():
    t = VKHTTPTransport(tokens={})
    for url in ('http://cdn.userapi.com/a', 'https://localhost/a', 'https://userapi.com.evil.test/a',
                'https://u:p@userapi.com/a', 'https://userapi.com:444/a'):
        with pytest.raises(DomainError):
            await t.image_fingerprint(url)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [None, 'redirect', 'encoding', 'mime', 'bytes'])
async def test_cdn_reader_bounds_and_credential_isolation(monkeypatch, failure):
    import aiohttp
    import adapters.vk_transport as module
    data = asset().data
    seen = {}
    class Content:
        async def iter_chunked(self, size):
            assert size == 65536
            if failure == 'bytes':
                for _ in range(321):
                    yield b'x' * 65536
            else:
                yield data
    class Response:
        status = 302 if failure == 'redirect' else 200
        headers = {'Content-Type': 'text/html' if failure == 'mime' else 'image/png',
                   'Content-Encoding': 'gzip' if failure == 'encoding' else 'identity'}
        content = Content()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Session:
        def __init__(self, **kwargs): seen.update(kwargs)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url, **kwargs):
            assert kwargs == {'allow_redirects': False}
            return Response()
    async def public(host):
        assert host == 'cdn.userapi.com'
        return ('1.1.1.1',)
    monkeypatch.setattr(module, 'public_addresses', public)
    monkeypatch.setattr(aiohttp, 'TCPConnector', lambda **kw: kw)
    monkeypatch.setattr(aiohttp, 'ClientSession', Session)
    t = VKHTTPTransport(tokens={})
    if failure:
        with pytest.raises(DomainError):
            await t.image_fingerprint('https://cdn.userapi.com/photo')
    else:
        proof = await t.image_fingerprint('https://cdn.userapi.com/photo')
        assert proof['sha256'] == hashlib.sha256(data).hexdigest()
        assert proof['size'] == len(data)
    assert seen['trust_env'] is False and seen['auto_decompress'] is False
    assert seen['headers'] == {'Accept-Encoding': 'identity'}
    assert isinstance(seen['cookie_jar'], aiohttp.DummyCookieJar)
    assert seen['timeout'].total == 10
