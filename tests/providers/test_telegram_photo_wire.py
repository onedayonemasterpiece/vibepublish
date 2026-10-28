"""Telegram photos use the compact JPEG wire copy; a rejected file is a final refusal."""
import hashlib
import io

import pytest
from PIL import Image

from adapters.telegram import TelegramAdapter
from adapters.port import Asset
from social_operations.worker import Worker
from tests.providers.scripted import ScriptedTL, TelegramClient
from tests.providers.test_native_adapters import Journal, request


def noisy_png(size=(1200, 900)):
    stream = io.BytesIO()
    Image.effect_noise(size, 60).convert('RGB').save(stream, format='PNG')
    data = stream.getvalue()
    return Asset('asset_big', hashlib.sha256(data).hexdigest(), 'image/png', len(data), data=data)


@pytest.mark.asyncio
async def test_large_png_photo_is_uploaded_as_smaller_jpeg():
    client, journal = TelegramClient(), Journal()
    adapter = TelegramAdapter(client, connection_id='connection', tl=ScriptedTL())
    big = noisy_png()
    r = request('telegram', assets=(big,))
    await adapter.execute(await adapter.prepare(r, journal.hooks), journal.hooks)
    sent, = client.uploads
    assert sent[:3] == b'\xff\xd8\xff' and len(sent) < big.size
    assert any(call == ('upload_file', {'size': len(sent), 'filename': 'verified-1.jpg'}) for call in client.calls)


class PhotoSaveFileInvalidError(Exception):
    code = 400


def test_rejected_photo_file_is_not_retried():
    adapter = TelegramAdapter(TelegramClient(), connection_id='connection', tl=ScriptedTL())
    error = adapter._rpc_error('upload', PhotoSaveFileInvalidError('rejected'))
    assert error.code == 'telegram_media_invalid'
    assert not Worker.transient(error.code)
