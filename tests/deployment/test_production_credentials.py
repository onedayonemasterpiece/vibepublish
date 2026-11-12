import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from social_operations.domain import DomainError
from social_operations.storage import Store

spec = importlib.util.spec_from_file_location(
    'production_credentials', Path(__file__).resolve().parents[2] /
    'deploy/devcoveer/production_worker.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)


@pytest.mark.parametrize('mode', ['sqlite_failure', 'normal'])
def test_worker_sqlite_failure_exits_before_hanging_cleanup(tmp_path, mode):
    root = Path(__file__).resolve().parents[2]
    path = tmp_path / 'ledger.sqlite'
    store = Store(path)
    actor = store.authenticate(store.create_principal('test', 'owner', owner=True))
    store.add_connection(actor, 'tg', 'telegram', account_type='mtproto_user',
                         secret_ref=production.TG_REFERENCE)
    script = r'''
import asyncio
import importlib.util
from pathlib import Path
import sqlite3
import sys

root, db, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location(
    'production_worker_fixture', root / 'deploy/devcoveer/production_worker.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)

class Client:
    async def connect(self):
        pass
    async def is_user_authorized(self):
        return True
    async def disconnect(self):
        print('cleanup_entered', flush=True)
        if mode == 'sqlite_failure':
            await asyncio.Event().wait()

class Worker:
    def __init__(self, *args, **kwargs):
        pass
    async def run_once(self):
        if mode == 'sqlite_failure':
            error = sqlite3.OperationalError('disk I/O error')
            error.sqlite_errorcode = sqlite3.SQLITE_IOERR
            error.sqlite_errorname = 'SQLITE_IOERR'
            raise error
        return False

production.Worker = Worker
production.telegram_factory = lambda *args, **kwargs: Client()
production.telegram_credentials = lambda *args, **kwargs: {
    'api_id': 1, 'api_hash': 'a' * 32, 'session': 'fixture'}
asyncio.run(production.run(
    db, Path('unused'), None, vk_token_key='',
    providers=('telegram',), once=True))
'''
    result = subprocess.run(
        [sys.executable, '-B', '-c', script, str(root), str(path), mode],
        cwd=root, capture_output=True, text=True, timeout=10)
    if mode == 'sqlite_failure':
        assert result.returncode == 1, result.stderr
        assert 'production_worker_sqlite_fatal' in result.stderr
        assert 'SQLITE_IOERR' in result.stderr
        assert 'cleanup_entered' not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert 'cleanup_entered' in result.stdout


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


def test_knowledge_session_is_an_explicit_independent_lane(tmp_path):
    store=Store(tmp_path/'ledger.sqlite')
    actor=store.authenticate(store.create_principal('test','owner',owner=True))
    store.add_connection(actor,'ordinary','telegram',account_type='mtproto_user',secret_ref=production.TG_REFERENCE)
    store.add_connection(actor,'kb','telegram',account_type='mtproto_user',secret_ref=production.KB_REFERENCE)
    with pytest.raises(DomainError):production.production_connections(store,telegram_only=True)
    assert production.production_connections(store,telegram_only=True,knowledge_base=True)=={'telegram':'ordinary','knowledge_base':'kb'}


def test_same_chat_topic_selects_explicit_kb_or_preserved_ordinary_connection(tmp_path):
    from social_operations.ingress import IngressApplication as Application
    store=Store(tmp_path/'ledger.sqlite');actor=store.authenticate(store.create_principal('test','owner',owner=True))
    store.add_connection(actor,'ordinary','telegram',account_type='mtproto_user',secret_ref=production.TG_REFERENCE)
    store.add_connection(actor,'kb','telegram',account_type='mtproto_user',secret_ref=production.KB_REFERENCE)
    store.bind(actor,actor.principal_id,'ordinary','ordinary','-1004368830579')
    store.bind(actor,actor.principal_id,'kb','kb','-1004368830579')
    app=Application(store)
    with store.connection() as db:
        binding,topic=app._telegram_thread(db,actor,'https://t.me/c/4368830579/2',alias='kb')
        assert binding['connection_id']=='kb' and topic=='2'
        assert app._telegram_thread(db,actor,'https://t.me/c/4368830579/4')[0]['connection_id']=='ordinary'
        with pytest.raises(DomainError):app._telegram_thread(db,actor,'https://t.me/c/9999/2',alias='kb')
