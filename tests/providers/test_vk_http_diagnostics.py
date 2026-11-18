"""Sanitized HTTP failures remain useful without exposing VK transport data."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from adapters.vk_transport import VKHTTPTransport
from social_operations.domain import DomainError
from social_operations.provider_diagnostics import diagnostic_scope


class Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


@pytest.mark.parametrize("api,phase", [(True, "api"), (False, "media_upload")])
@pytest.mark.parametrize("status", [301, 400, 403, 413, 429, 500, 502, 503, 504])
def test_http_failure_has_only_status_and_static_phase(api, phase, status):
    response = SimpleNamespace(status=status, headers={'Retry-After':'13', 'Set-Cookie':'secret'})
    events = []
    session = SimpleNamespace(post=lambda *args, **kwargs: Context(response))
    aiohttp = SimpleNamespace(
        TCPConnector=lambda **kwargs: None,
        ClientSession=lambda **kwargs: Context(session),
        DummyCookieJar=lambda: None,
        ClientTimeout=lambda **kwargs: None,
    )
    transport = VKHTTPTransport(tokens={})
    with patch.dict(sys.modules, {"aiohttp": aiohttp}), \
            patch("adapters.vk_transport.validated_url", return_value="example.invalid"), \
            patch("adapters.vk_transport.public_addresses", new=AsyncMock(return_value=[])):
        with diagnostic_scope(events.append), pytest.raises(DomainError) as raised:
            asyncio.run(transport._post(
                "https://example.invalid/private?access_token=secret",
                {"access_token": "secret", "photo": b"private"}, api=api))
    error = raised.value
    assert error.code == "vk_http_failed"
    assert error.http_status == status
    assert error.http_phase == phase
    assert error.message == f"VK {phase} HTTP status {status}"
    assert error.output()["error"]["message"] == error.message
    assert "secret" not in str(error.output())
    assert "example.invalid" not in str(error.output())
    assert error.output()["retry_safe"] is False
    assert events[-1]["http_status"] == status
    assert events[-1]["retry_after_s"] == 13
    assert events[-1]["status"] == "failed"
    assert "secret" not in str(events)


@pytest.mark.parametrize('phase', ['dns', 'headers', 'body', 'completed'])
def test_photo_download_cancellation_phase_and_privacy(phase):
    """An outer read timeout retains the interrupted boundary, never the URL."""
    import json

    async def addresses(_host):
        if phase == 'dns':
            raise asyncio.CancelledError('secret-dns')
        return []

    async def chunks(_size):
        if phase == 'body':
            raise asyncio.CancelledError('secret-body')
        yield b'photo-bytes'

    response = SimpleNamespace(status=200, headers={},
                               content=SimpleNamespace(iter_chunked=chunks))

    class PhotoResponse(Context):
        async def __aenter__(self):
            if phase == 'headers':
                raise asyncio.CancelledError('secret-headers')
            return await super().__aenter__()

    session = SimpleNamespace(get=lambda *a, **kw: PhotoResponse(response))
    aiohttp = SimpleNamespace(
        TCPConnector=lambda **kwargs: None,
        ClientSession=lambda **kwargs: Context(session),
        DummyCookieJar=lambda: None,
        ClientTimeout=lambda **kwargs: None,
    )
    events = []
    transport = VKHTTPTransport(tokens={})
    with patch.dict(sys.modules, {'aiohttp': aiohttp}), \
            patch('adapters.vk_transport.public_addresses', new=addresses), \
            diagnostic_scope(events.append):
        call = transport.download_photo('https://sun9.userapi.com/secret?access_key=secret')
        if phase == 'completed':
            assert asyncio.run(call) == b'photo-bytes'
        else:
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(call)
    assert len(events) == 2
    start, end = events
    assert start['operation'] == end['operation'] == 'photo_download'
    assert end['phase'] == ('body' if phase == 'completed' else phase)
    assert end['status'] == ('completed' if phase == 'completed' else 'failed')
    assert end['duration_ms'] >= 0
    if phase != 'dns':
        assert end['dns_ms'] >= 0
    if phase in ('body', 'completed'):
        assert end['http_status'] == 200 and end['headers_wait_ms'] >= 0
    serialized = json.dumps(events)
    assert 'secret' not in serialized and 'userapi.com' not in serialized
    assert 'photo-bytes' not in serialized
