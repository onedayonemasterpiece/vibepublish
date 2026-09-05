import argparse
import importlib.util
from pathlib import Path
import httpx
import pytest
from social_operations.storage import Store

spec = importlib.util.spec_from_file_location('stand_serve', Path(__file__).resolve().parents[2] / 'deploy/devcoveer/serve.py')
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


@pytest.mark.parametrize('value', ['https://example.com', '*.example.com', 'example.com:443', 'UPPER.example.com', 'evil.com/path', 'a..com', '-a.example.com', 'example.com\n'])
def test_no_wildcard_url_or_injected_host(value):
    with pytest.raises(argparse.ArgumentTypeError):
        serve.public_host(value)


@pytest.mark.asyncio
async def test_exact_domain_preserves_bearer_and_origin_boundary(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    token = Store(path).create_principal('test', 'owner', owner=True)
    app = serve.build_app(path, 'mcp-vibepublish.kenigevents.ru')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://mcp-vibepublish.kenigevents.ru') as client:
        assert (await client.get('/v1/bootstrap')).status_code == 401
        headers = {'Authorization': 'Bearer ' + token}
        assert (await client.get('/v1/bootstrap', headers=headers)).status_code == 200
        assert (await client.get('/v1/bootstrap', headers={**headers, 'Host': 'unapproved.example.com'})).status_code == 403
        assert (await client.get('/v1/bootstrap', headers={**headers, 'Origin': 'https://unapproved.example.com'})).status_code == 403
        assert (await client.get('/v1/bootstrap', headers={**headers, 'Origin': 'https://mcp-vibepublish.kenigevents.ru'})).status_code == 200

native_spec = importlib.util.spec_from_file_location('stand_native_worker', Path(__file__).resolve().parents[2] / 'deploy/devcoveer/native_worker.py')
native = importlib.util.module_from_spec(native_spec)
native_spec.loader.exec_module(native)


def test_only_dedicated_session_is_accepted(tmp_path):
    from social_operations.domain import DomainError
    env = tmp_path / 'owner.env'
    env.write_text('TELEGRAM_SESSION=old-session\nTG_API_ID=123\nTG_API_HASH=abc\n')
    with pytest.raises(DomainError, match='dedicated telegram session missing'):
        native.credentials(env)


def test_explicit_bundle_is_decoded_without_old_session_fallback(tmp_path):
    import base64
    import json
    env = tmp_path / 'owner.env'
    supplied = base64.urlsafe_b64encode(json.dumps({'session': '1explicit-test-only'}).encode()).decode()
    env.write_text(f'VIBE_PUBLISH_TG_SESSION={supplied}\nTELEGRAM_SESSION=old\nTG_API_ID=123\nTG_API_HASH=abc\n')
    assert native.credentials(env) == {'api_id': 123, 'api_hash': 'abc', 'session': '1explicit-test-only'}
