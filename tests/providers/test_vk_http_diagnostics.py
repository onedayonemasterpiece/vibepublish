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
@pytest.mark.parametrize("status", [301, 400, 403, 413, 429, 500, 503])
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
    assert error.message == f"VK {phase} HTTP status {status}"
    assert error.output()["error"]["message"] == error.message
    assert "secret" not in str(error.output())
    assert "example.invalid" not in str(error.output())
    assert error.output()["retry_safe"] is False
    assert events[-1]["http_status"] == status
    assert events[-1]["retry_after_s"] == 13
    assert events[-1]["status"] == "failed"
    assert "secret" not in str(events)
