import base64
import importlib.util
import json
from pathlib import Path

import pytest

from social_operations.domain import DomainError
from social_operations.storage import Store

spec = importlib.util.spec_from_file_location(
    'production_credentials', Path(__file__).resolve().parents[2] /
    'deploy/devcoveer/production_worker.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)


def test_explicit_existing_bundle_mapping(tmp_path):
    env = tmp_path / 'credentials.env'
    bundle = base64.urlsafe_b64encode(json.dumps({'session': '1fixture'}).encode()).decode()
    env.write_text(f'TELEGRAM_VIBE_PUBLISH={bundle}\nTELEGRAM_API_ID=123\n'
                   'TELEGRAM_API_HASH=abc\nVIBE_PUBLISH_TG_SESSION=1wrong\n')
    assert production.telegram_credentials(
        env, session_key='TELEGRAM_VIBE_PUBLISH', api_id_key='TELEGRAM_API_ID',
        api_hash_key='TELEGRAM_API_HASH') == {
            'session': '1fixture', 'api_id': 123, 'api_hash': 'abc'}


def test_missing_explicit_session_never_falls_back(tmp_path):
    env = tmp_path / 'credentials.env'
    env.write_text('VIBE_PUBLISH_TG_SESSION=1other\n')
    with pytest.raises(DomainError) as exc:
        production.telegram_credentials(env, session_key='TELEGRAM_VIBE_PUBLISH')
    assert exc.value.code == 'dedicated_telegram_session_missing'


def test_partial_topology_requires_opt_in_and_rejects_other_connections(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite')
    actor = store.authenticate(store.create_principal('test', 'owner', owner=True))
    with pytest.raises(DomainError):
        production.production_connections(store, telegram_only=True)
    store.add_connection(actor, 'tg', 'telegram', account_type='mtproto_user',
                         secret_ref=production.TG_REFERENCE)
    assert production.production_connections(store, telegram_only=True) == {'telegram': 'tg'}
    with pytest.raises(DomainError):
        production.production_connections(store)
    store.add_connection(actor, 'vk', 'vk', account_type='vk_user', secret_ref=production.VK_REFERENCE)
    with pytest.raises(DomainError):
        production.production_connections(store, telegram_only=True)


def test_default_full_topology_preserved(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite')
    actor = store.authenticate(store.create_principal('test', 'owner', owner=True))
    for provider, account, reference in [
        ('telegram', 'mtproto_user', production.TG_REFERENCE),
        ('vk', 'vk_user', production.VK_REFERENCE),
        ('max', 'max_web', production.MAX_REFERENCE),
    ]:
        store.add_connection(actor, provider, provider, account_type=account, secret_ref=reference)
    assert production.production_connections(store) == {p: p for p in ('telegram', 'vk', 'max')}


def test_explicit_telegram_vk_topology_without_max(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite')
    actor = store.authenticate(store.create_principal('test', 'owner', owner=True))
    store.add_connection(actor, 'tg', 'telegram', account_type='mtproto_user', secret_ref=production.TG_REFERENCE)
    store.add_connection(actor, 'vk', 'vk', account_type='vk_user', secret_ref=production.VK_REFERENCE)
    assert production.production_connections(store, providers=('telegram', 'vk')) == {'telegram': 'tg', 'vk': 'vk'}
    with pytest.raises(DomainError):
        production.production_connections(store)
    store.add_connection(actor, 'max', 'max', account_type='max_web', secret_ref=production.MAX_REFERENCE)
    with pytest.raises(DomainError):
        production.production_connections(store, providers=('telegram', 'vk'))


@pytest.mark.parametrize('providers', [(), ('vk',), ('telegram', 'other'), ('telegram', 'telegram')])
def test_invalid_provider_selection_rejected(tmp_path, providers):
    with pytest.raises(DomainError) as exc:
        production.production_connections(Store(tmp_path / 'ledger.sqlite'), providers=providers)
    assert exc.value.code == 'production_provider_selection_invalid'


def test_legacy_selection_conflict_rejected(tmp_path):
    with pytest.raises(DomainError) as exc:
        production.production_connections(Store(tmp_path / 'ledger.sqlite'),
                                          telegram_only=True, providers=('telegram',))
    assert exc.value.code == 'production_provider_selection_conflict'


def test_vk_exact_key_and_no_fallback(tmp_path):
    env = tmp_path / 'vk.env'
    env.write_text('APPROVED=fixture-selected\nVK_USER_TOKEN=fixture-other\n')
    bundle = production.vk_credentials(env, 'APPROVED')
    assert all(value['token'] == 'fixture-selected' for value in bundle['roles'].values())
    with pytest.raises(DomainError) as exc:
        production.vk_credentials(env, 'MISSING')
    assert exc.value.code == 'approved_vk_user_token_missing'
