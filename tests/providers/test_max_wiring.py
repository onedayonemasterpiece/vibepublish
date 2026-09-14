"""Optional MAX factory seam; entirely offline, no browser or profile access."""
import asyncio
import sys
import types
from contextlib import asynccontextmanager

import pytest
from adapters.fake import FakeProvider
from adapters.port import Capability
from adapters.wiring import native_adapters
from social_operations.cli import main, parser
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store


def setup(tmp_path, *, account='max_web', secret='VIBEPUBLISH_MAX_PROFILE'):
    store = Store(tmp_path/'ledger.sqlite')
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    store.add_connection(actor, 'max-test', 'max', account_type=account, secret_ref=secret)
    return store, actor


def install_fake_module(monkeypatch, factory):
    package = types.ModuleType('adapters.max'); package.__path__ = []
    module = types.ModuleType('adapters.max.live_session'); module.configured_adapter = factory
    monkeypatch.setitem(sys.modules, 'adapters.max', package)
    monkeypatch.setitem(sys.modules, 'adapters.max.live_session', module)


@pytest.mark.asyncio
async def test_injected_max_factory_owns_context_and_exact_connection(tmp_path):
    store, _ = setup(tmp_path)
    events, sentinel, env = [], object(), {'VIBEPUBLISH_MAX_PROFILE': 'offline-config'}
    @asynccontextmanager
    async def factory(*, connection_id, env):
        events.append(('enter', connection_id, dict(env)))
        try:
            yield sentinel
        finally:
            events.append(('close', connection_id))
    async with native_adapters(store, env=env, max_factory=factory) as wiring:
        assert wiring == {'max-test': sentinel}
        assert events == [('enter', 'max-test', env)]
    assert events[-1] == ('close', 'max-test')


@pytest.mark.asyncio
async def test_default_factory_is_lazily_imported_only_for_configured_max(tmp_path, monkeypatch):
    store, _ = setup(tmp_path)
    seen=[]
    @asynccontextmanager
    async def factory(*, connection_id, env):
        seen.append(connection_id)
        yield 'offline-adapter'
    install_fake_module(monkeypatch, factory)
    async with native_adapters(store, env={}) as wiring:
        assert wiring == {'max-test': 'offline-adapter'}
    assert seen == ['max-test']


@pytest.mark.asyncio
@pytest.mark.parametrize('account', ['fake', 'unconfigured'])
async def test_fake_unconfigured_max_do_not_invoke_factory(tmp_path, account):
    store, _ = setup(tmp_path, account=account, secret='')
    def forbidden(**kwargs):
        pytest.fail('MAX must not be opened')
    async with native_adapters(store, env={}, max_factory=forbidden) as wiring:
        assert wiring == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('account,secret,code', [
    ('vk_user', 'VIBEPUBLISH_MAX_PROFILE', 'native_account_type_needs_review'),
    ('max_web', 'VIBEPUBLISH_OTHER_PROFILE', 'native_secret_reference_invalid'),
])
async def test_wrong_max_account_or_reference_fails_before_factory(tmp_path, account, secret, code):
    store, _ = setup(tmp_path, account=account, secret=secret)
    def forbidden(**kwargs):
        pytest.fail('Unapproved binding reached factory')
    with pytest.raises(DomainError) as error:
        async with native_adapters(store, env={}, max_factory=forbidden):
            pytest.fail('Invalid MAX binding accepted')
    assert error.value.code == code


@pytest.mark.asyncio
async def test_missing_optional_max_package_has_precise_error(tmp_path, monkeypatch):
    import builtins
    store, _ = setup(tmp_path)
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == 'adapters.max.live_session':
            raise ModuleNotFoundError('missing optional MAX package', name='adapters.max')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing)
    with pytest.raises(DomainError) as error:
        async with native_adapters(store, env={}):
            pytest.fail('Missing adapter accepted')
    assert error.value.code == 'max_adapter_not_installed'


@pytest.mark.asyncio
async def test_context_closes_on_cancellation_and_sanitizes_unknown_failures(tmp_path):
    store, _ = setup(tmp_path)
    closed=[]
    @asynccontextmanager
    async def factory(**kwargs):
        try:
            yield object()
        finally:
            closed.append(True)
    with pytest.raises(asyncio.CancelledError):
        async with native_adapters(store, env={}, max_factory=factory):
            raise asyncio.CancelledError()
    assert closed == [True]
    with pytest.raises(DomainError) as error:
        async with native_adapters(store, env={}, max_factory=factory):
            raise RuntimeError('private-provider-detail')
    assert error.value.code == 'native_connection_failed'
    assert 'private-provider-detail' not in str(error.value)
    assert closed == [True, True]


@pytest.mark.asyncio
async def test_later_factory_failure_closes_previously_open_context(tmp_path):
    store, actor = setup(tmp_path)
    store.add_connection(actor, 'max-second', 'max', account_type='max_web', secret_ref='VIBEPUBLISH_MAX_PROFILE')
    closed=[]
    @asynccontextmanager
    async def factory(*, connection_id, env):
        if connection_id == 'max-second':
            raise DomainError('max_configuration_missing')
        try:
            yield object()
        finally:
            closed.append(connection_id)
    with pytest.raises(DomainError) as error:
        async with native_adapters(store, env={}, max_factory=factory):
            pytest.fail('Incomplete wiring yielded')
    assert error.value.code == 'max_configuration_missing'
    assert closed == ['max-test']


def test_standard_cli_native_worker_consumes_max_factory_without_custom_worker(tmp_path, monkeypatch):
    store, actor = setup(tmp_path)
    store.bind(actor, 'owner', 'max-test', 'max-test', 'fixture-target')
    accepted = asyncio.run(Application(store).call(actor, 'vibepublish_publish',
        {'to': ['max-test'], 'content': {'text': 'Offline MAX CLI'}, 'request_key': 'cli-native'}))
    events=[]
    class OfflineMax(FakeProvider):
        async def inspect(self, request):
            assert request.account_type == 'max_web'
            return Capability('supported', 'Explicit injected offline factory only')
    provider = OfflineMax(tmp_path/'remote.sqlite', 'max')
    @asynccontextmanager
    async def factory(*, connection_id, env):
        events.append('open')
        assert connection_id == 'max-test'
        try:
            yield provider
        finally:
            events.append('close')
    install_fake_module(monkeypatch, factory)
    monkeypatch.setattr(sys, 'argv', ['vibepublish', '--db', str(store.path), 'worker', '--native', '--once'])
    main()
    result = store.receipt(actor, accepted['operation_id'])
    assert result['state'] == 'verified' and result['operation_complete']
    assert provider.count('effect') == 1
    assert events == ['open', 'close']
    args = parser().parse_args(['--db',str(store.path),'connection','--id','configured-max','--provider','max','--account-type','max_web','--secret-ref','VIBEPUBLISH_MAX_PROFILE'])
    assert args.account_type == 'max_web'
