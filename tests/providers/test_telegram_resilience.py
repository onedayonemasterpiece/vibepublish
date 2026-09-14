from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from adapters.telegram_resilient import ResilientTelegramAdapter
from social_operations.domain import DomainError
from tests.providers.scripted import ScriptedTL, obj
from tests.providers.test_native_adapters import request

LIVE_TARGET = "-1004379835477"
CHANNEL_ID = 4_379_835_477


def live_channel():
    return obj(
        "Channel",
        id=CHANNEL_ID,
        broadcast=False,
        megagroup=True,
        forum=True,
        username="bound_forum",
        noforwards=False,
        left=False,
        kicked=False,
    )


class HydratingClient:
    def __init__(self, *, connected=False):
        self.connected = connected
        self.authorized = True
        self.connects = 0
        self.hydrated = False
        self.entity = live_channel()

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connects += 1
        self.connected = True

    async def is_user_authorized(self):
        return self.authorized

    async def get_entity(self, target):
        assert int(target) == int(LIVE_TARGET)
        if not self.hydrated:
            raise ValueError("entity cache miss")
        return self.entity

    async def iter_dialogs(self):
        self.hydrated = True
        yield NS(entity=self.entity)


@pytest.mark.asyncio
async def test_reconnect_then_hydrate_exact_active_binding_without_hardcoded_peer():
    client = HydratingClient(connected=False)
    adapter = ResilientTelegramAdapter(
        client,
        connection_id="connection",
        tl=ScriptedTL(),
        bound_targets=(LIVE_TARGET,),
    )
    entity = await adapter._entity(LIVE_TARGET)
    assert entity.id == CHANNEL_ID
    assert client.connects == 1
    assert client.hydrated

    # A later dead transport is reconnected before even a cached entity is used.
    client.connected = False
    client.hydrated = False
    entity = await adapter._entity(LIVE_TARGET)
    assert entity.id == CHANNEL_ID
    assert client.connects == 2


class BrokenRPCClient(HydratingClient):
    def __init__(self):
        super().__init__(connected=True)
        self.hydrated = True

    async def __call__(self, _request):
        raise ConnectionResetError("SESSION_MUST_NOT_LEAK")


@pytest.mark.asyncio
async def test_rpc_diagnostic_keeps_safe_type_stage_and_correlation_only():
    adapter = ResilientTelegramAdapter(
        BrokenRPCClient(),
        connection_id="connection",
        tl=ScriptedTL(),
        bound_targets=(LIVE_TARGET,),
    )
    with pytest.raises(DomainError) as caught:
        await adapter._call(
            "history",
            peer=live_channel(),
            offset_id=0,
            offset_date=None,
            add_offset=0,
            limit=1,
            max_id=0,
            min_id=0,
            hash=0,
        )
    error = caught.value
    assert error.code == "telegram_transport_unhealthy"
    assert "exception_type=ConnectionResetError" in error.message
    assert "stage=telegram_rpc:history" in error.message
    assert "correlation_id=tgdiag_" in error.message
    assert "SESSION_MUST_NOT_LEAK" not in error.message


class DeadClient(HydratingClient):
    async def connect(self):
        self.connects += 1
        raise ConnectionResetError("private transport detail")


@pytest.mark.asyncio
async def test_capability_is_not_supported_when_runtime_health_reconnect_fails():
    adapter = ResilientTelegramAdapter(
        DeadClient(),
        connection_id="connection",
        tl=ScriptedTL(),
        bound_targets=(LIVE_TARGET,),
    )
    provider_request = request("telegram", native_target=LIVE_TARGET)
    capability = await adapter.inspect(provider_request)
    assert capability.status == "temporarily_unavailable"
    assert capability.reason == "telegram_transport_unhealthy"
    assert capability.evidence == "runtime_health_failed"


@pytest.mark.asyncio
async def test_native_wiring_derives_hydration_targets_from_active_bindings(tmp_path):
    import json

    from adapters.wiring import native_adapters
    from social_operations.storage import Store

    store = Store(tmp_path / "ledger.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(
        actor,
        "native-tg",
        "telegram",
        account_type="mtproto_user",
        secret_ref="VIBEPUBLISH_TG",
    )
    store.bind(actor, "owner", "telegram", "native-tg", LIVE_TARGET)

    class Client:
        async def connect(self):
            return None

        async def is_user_authorized(self):
            return True

        async def disconnect(self):
            return None

    def factory(_credentials, **_options):
        return Client()

    env = {
        "VIBEPUBLISH_TG": json.dumps({
            "api_id": 1,
            "api_hash": "a" * 32,
            "session": "dedicated-fixture-session",
        })
    }
    async with native_adapters(
        store,
        env=env,
        telegram_factory=factory,
        tl=ScriptedTL(),
    ) as adapters:
        adapter = adapters["native-tg"]
        assert isinstance(adapter, ResilientTelegramAdapter)
        assert adapter.bound_targets == (LIVE_TARGET,)
