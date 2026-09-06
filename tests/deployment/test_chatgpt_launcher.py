import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('oauth_stand_serve', Path(__file__).resolve().parents[2] / 'deploy/devcoveer/serve.py')
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


def test_oauth_opt_in_requires_exact_public_host(tmp_path):
    with pytest.raises(ValueError, match='exact public hostname'):
        serve.build_app(tmp_path/'ledger', oauth_db=tmp_path/'oauth')


def test_oauth_opt_in_passes_only_validated_origin(monkeypatch, tmp_path):
    import social_operations.oauth as oauth
    seen = {}
    def create(store, **kwargs):
        seen.update(kwargs)
        return 'oauth-app'
    monkeypatch.setattr(oauth, 'create_oauth_app', create)
    result = serve.build_app(tmp_path/'ledger', 'mcp-vibepublish.kenigevents.ru', tmp_path/'oauth')
    assert result == 'oauth-app'
    assert seen == {'auth_db': tmp_path/'oauth', 'issuer': 'https://mcp-vibepublish.kenigevents.ru'}
