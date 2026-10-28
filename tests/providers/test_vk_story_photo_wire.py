"""VK story photos use the compact JPEG wire copy (VK story limit is 10 MB)."""
import io

import pytest
from PIL import Image

import adapters.vk_transport as vk_transport
from adapters.vk_transport import VKHTTPTransport, VKToken


@pytest.mark.asyncio
async def test_large_png_story_photo_is_uploaded_as_jpeg(monkeypatch):
    stream = io.BytesIO()
    Image.effect_noise((2200, 2000), 60).convert('RGB').save(stream, format='PNG')
    png = stream.getvalue()
    assert len(png) > 10 * 1024 * 1024
    sent = {}
    monkeypatch.setattr(vk_transport, 'upload_payload',
                        lambda data, mime, kind, **_: sent.update(data=data, mime=mime, kind=kind))
    transport = VKHTTPTransport(tokens={'media': VKToken('fixture')})

    async def post(url, form, *, api=False):
        return {'upload_result': 'opaque'}

    transport._post = post
    assert await transport.upload_story_photo('https://pu.vk.com/story', png, 'image/png') == 'opaque'
    assert sent['mime'] == 'image/jpeg' and len(sent['data']) <= 10 * 1024 * 1024
    with Image.open(io.BytesIO(sent['data'])) as image:
        assert max(image.size) == 1920
