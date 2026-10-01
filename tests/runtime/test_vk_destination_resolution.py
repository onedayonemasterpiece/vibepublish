"""VK exact destination resolution and persistence regressions."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from adapters.vk_discovery import parse_destination, resolve
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


URL = "https://vk.com/kenigeventsofficial"
GROUP_ID = 231828790


class Transport:
    account_type = "vk_user"

    def __init__(self, permitted=True):
        self.permitted = permitted

    def permits(self, role, method, *, group_id, scheduled=False):
        return self.permitted and group_id == GROUP_ID and not scheduled


class Adapter:
    account_type = "vk_user"

    def __init__(self, *, admin_level=3, permitted=True):
        self.transport = Transport(permitted)
        self.admin_level = admin_level
        self.calls = []

    async def _call(self, method, *, role=None, **params):
        self.calls.append((method, role, params))
        assert method == "groups.getById"
        return [{
            "id": GROUP_ID,
            "name": "Полюбить Калининград Анонсы",
            "screen_name": "kenigeventsofficial",
            "is_admin": 1 if self.admin_level else 0,
            "admin_level": self.admin_level,
            "is_closed": 0,
        }]


@pytest.mark.parametrize("value", [
    "http://vk.com/kenigeventsofficial",
    "https://vk.com/kenigeventsofficial?x=1",
    "https://vk.com/kenigeventsofficial#x",
    "https://vk.com/a/b",
    "https://evil.test/kenigeventsofficial",
])
def test_invalid_vk_urls(value):
    with pytest.raises(DomainError):
        parse_destination({"url": value})


def test_vk_url_and_id_parsing():
    assert parse_destination({"url": URL}) == "kenigeventsofficial"
    assert parse_destination({"provider_id": str(GROUP_ID)}) == str(GROUP_ID)
    assert parse_destination({"provider_id": f"-{GROUP_ID}"}) == str(GROUP_ID)


@pytest.mark.asyncio
async def test_vk_resolve_proves_admin_and_transport_rights():
    adapter = Adapter()
    evidence = await resolve(adapter, {"url": URL})
    assert evidence["native_id"] == f"-{GROUP_ID}"
    assert evidence["handle"] == "kenigeventsofficial"
    assert evidence["rights"] == ["publish", "edit", "reschedule", "cancel", "delete", "forward"]
    assert adapter.calls[0][2]["group_ids"] == "kenigeventsofficial"


@pytest.mark.asyncio
async def test_vk_owner_resolve_url_idempotent_id_and_persistent(tmp_path):
    path = tmp_path / "ledger.sqlite"
    store = Store(path)
    token = store.create_principal("tenant", "owner", owner=True)
    owner = store.authenticate(token)
    store.add_connection(owner, "conn", "vk", account_type="vk_user", secret_ref="VIBEPUBLISH_TEST")
    adapter = Adapter()
    app = Application(store)

    first = await app.call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "vk", "url": URL},
        "request_key": "vk-url",
    })
    assert first["state"] == "accepted", first
    assert await Worker(store, {"conn": adapter}).run_once()
    done = store.receipt(owner, first["operation_id"])
    assert done["state"] == "verified", done
    alias = done["destinations"][0]["alias"]
    assert alias.startswith("vk_")

    second = await app.call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "vk", "provider_id": str(GROUP_ID)},
        "request_key": "vk-id",
    })
    assert second["state"] == "accepted", second
    assert await Worker(store, {"conn": adapter}).run_once()
    repeated = store.receipt(owner, second["operation_id"])
    assert repeated["destinations"][0]["alias"] == alias

    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM destinations").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 1
        rights = db.execute("SELECT rights FROM bindings").fetchone()[0]
        assert rights == '["publish","edit","reschedule","cancel","delete","forward"]'

    reopened = Store(path)
    owner2 = reopened.authenticate(token)
    listed = await Application(reopened).call(owner2, "vibepublish_destinations", {"command": {"kind": "list"}})
    assert any(d["alias"] == alias and d["provider"] == "vk" for d in listed["destinations"])


@pytest.mark.asyncio
async def test_vk_unauthorized_group_fails_closed(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal("tenant", "owner", owner=True)
    owner = store.authenticate(token)
    store.add_connection(owner, "conn", "vk", account_type="vk_user", secret_ref="VIBEPUBLISH_TEST")
    first = await Application(store).call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "vk", "url": URL}
    })
    assert first["state"] == "accepted", first
    await Worker(store, {"conn": Adapter(admin_level=1)}).run_once()
    done = store.receipt(owner, first["operation_id"])
    assert done["state"] == "blocked"
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_vk_transport_without_publish_permission_fails_closed(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal("tenant", "owner", owner=True)
    owner = store.authenticate(token)
    store.add_connection(owner, "conn", "vk", account_type="vk_user", secret_ref="VIBEPUBLISH_TEST")
    first = await Application(store).call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "vk", "url": URL}
    })
    await Worker(store, {"conn": Adapter(permitted=False)}).run_once()
    assert store.receipt(owner, first["operation_id"])["state"] == "blocked"
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_vk_provider_mismatch_does_not_bind(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal("tenant", "owner", owner=True)
    owner = store.authenticate(token)
    store.add_connection(owner, "conn", "telegram", account_type="mtproto_user", secret_ref="VIBEPUBLISH_TEST")
    result = await Application(store).call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "vk", "url": URL}
    })
    assert result["error"]["code"] == "vk_discovery_connection_ambiguous"
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_vk_revoked_binding_is_not_silently_reactivated(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal("tenant", "owner", owner=True)
    owner = store.authenticate(token)
    store.add_connection(owner, "conn", "vk", account_type="vk_user", secret_ref="VIBEPUBLISH_TEST")
    app = Application(store)
    first = await app.call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "vk", "url": URL}
    })
    worker = Worker(store, {"conn": Adapter()})
    await worker.run_once()
    with store.connection() as db:
        binding_id = db.execute("SELECT id FROM bindings").fetchone()[0]
    store.revoke_binding(owner, binding_id)
    current = store.authenticate(token)

    retry = await Application(store).call(current, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "vk", "url": URL}
    })
    assert retry["state"] == "accepted", retry
    await Worker(store, {"conn": Adapter()}).run_once()
    assert store.receipt(current, retry["operation_id"])["state"] == "blocked"
    with store.connection() as db:
        row = db.execute("SELECT active FROM bindings WHERE id=?", (binding_id,)).fetchone()
        assert row[0] == 0
