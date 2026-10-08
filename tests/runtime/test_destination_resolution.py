"""Exact invite discovery, owner isolation and replay regression tests."""
from types import SimpleNamespace as NS
import pytest
from adapters.telegram_discovery import parse_destination_url, resolve, basic_publish_rights
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker

URL = "https://t.me/+abcdefgh12345678"
Chat = type("Chat", (), {})
Already = type("ChatInviteAlready", (), {})

def chat():
    value = Chat()
    value.id = 123456
    value.title = "Exact private group"
    value.creator = False
    return value

class Adapter:
    connection_id = "conn"
    account_type = "mtproto_user"
    def __init__(self, response=None, allowed=True, allowed_actions=None):
        self.entity = chat()
        self.response = response or Already()
        self.response.chat = self.entity
        self.allowed = allowed
        self.allowed_actions = set(allowed_actions or {"publish", "edit", "reschedule", "cancel", "delete", "forward"})
        self.calls = []
        self._entity_cache = {}
    async def _call(self, kind, **kwargs):
        self.calls.append(kind)
        assert kind == "check_invite"
        return self.response
    async def _entity(self, target):
        return self.entity
    async def _rights(self, request):
        if not self.allowed or request.action not in self.allowed_actions:
            raise DomainError("provider_access_denied")
        assert request.native_target == "-123456"
        return self.entity

@pytest.mark.parametrize("url", [URL, "https://t.me/joinchat/abcdefgh12345678"])
def test_invites(url):
    assert parse_destination_url(url) == ("invite", "abcdefgh12345678")

@pytest.mark.parametrize("url", ["http://t.me/+abcdefgh12345678", "https://t.me.evil/+abcdefgh12345678", "https://t.me@evil.test/group", "https://t.me:443/group", "https://evil.test/group", "https://t.me/+short"])
def test_invalid_urls(url):
    with pytest.raises(DomainError):
        parse_destination_url(url)

@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["ChatInvite", "ChatInvitePeek"])
async def test_preview_is_not_membership(name):
    adapter = Adapter(type(name, (), {})())
    with pytest.raises(DomainError, match="membership"):
        await resolve(adapter, URL)
    assert adapter.calls == ["check_invite"]

@pytest.mark.asyncio
async def test_read_only_exact_resolution():
    adapter = Adapter()
    result = await resolve(adapter, URL)
    assert result["native_id"] == "-123456"
    assert result["rights"] == ["publish", "edit", "reschedule", "cancel", "delete", "forward"]
    assert adapter.calls == ["check_invite"]

@pytest.mark.asyncio
@pytest.mark.parametrize("admin,default,ban,allowed", [(True,False,True,True),(False,True,False,True),(False,True,True,False),(False,False,False,False)])
async def test_basic_group_member_rights(admin, default, ban, allowed):
    entity = chat()
    entity.default_banned_rights = NS(send_messages=ban)
    async def permissions(entity, me):
        return NS(is_creator=admin, has_default_permissions=default)
    adapter = NS(account_type="mtproto_user", client=NS(get_permissions=permissions))
    request = NS(action="publish", surface="post", existing=None, scheduled_at=None, source=None, assets=())
    if allowed:
        await basic_publish_rights(adapter, request, entity, object())
    else:
        with pytest.raises(DomainError):
            await basic_publish_rights(adapter, request, entity, object())

@pytest.mark.asyncio
async def test_owner_worker_replay_no_join_no_duplicate_binding(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    owner = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(owner, "conn", "telegram", account_type="mtproto_user", secret_ref="VIBEPUBLISH_TEST")
    app = Application(store)
    adapter = Adapter()
    args = {"command": {"kind": "resolve", "provider": "telegram", "url": URL}, "request_key": "resolve-once"}
    first = await app.call(owner, "vibepublish_destinations", args)
    assert first["state"] == "accepted", first
    worker = Worker(store, {"conn": adapter})
    assert await worker.run_once()
    done = store.receipt(owner, first["operation_id"])
    assert done["state"] == "verified", done
    assert done["destinations"][0]["label"] == "Exact private group"
    replay = await app.call(owner, "vibepublish_destinations", args)
    assert replay["operation_id"] == first["operation_id"]
    assert adapter.calls == ["check_invite"]
    args["request_key"] = "resolve-again"
    await app.call(owner, "vibepublish_destinations", args)
    await worker.run_once()
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 1
        assert db.execute("SELECT rights FROM bindings").fetchone()[0] == '["publish","edit","reschedule","cancel","delete","forward"]'

@pytest.mark.asyncio
async def test_resolution_grants_only_provider_verified_lifecycle_rights():
    adapter = Adapter(allowed_actions={"publish", "delete"})
    result = await resolve(adapter, URL)
    assert result["rights"] == ["publish", "delete"]


@pytest.mark.asyncio
async def test_partner_cannot_discover(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "partner", owner=False))
    result = await Application(store).call(actor, "vibepublish_destinations", {"command": {"kind": "resolve", "provider": "telegram", "url": URL}})
    assert result["error"]["code"] in {"access_denied", "scope_denied"}
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0

@pytest.mark.asyncio
async def test_failed_permissions_do_not_bind(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(actor, "conn", "telegram", account_type="mtproto_user", secret_ref="VIBEPUBLISH_TEST")
    first = await Application(store).call(actor, "vibepublish_destinations", {"command": {"kind": "resolve", "provider": "telegram", "url": URL}})
    await Worker(store, {"conn": Adapter(allowed=False)}).run_once()
    assert store.receipt(actor, first["operation_id"])["state"] == "blocked"
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0

@pytest.mark.asyncio
async def test_owner_discovery_ignores_dedicated_knowledge_base_connection(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    owner = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(
        owner, "conn", "telegram", account_type="mtproto_user",
        secret_ref="VIBEPUBLISH_TEST",
    )
    store.add_connection(
        owner, "kb-conn", "telegram", account_type="mtproto_user",
        secret_ref="VIBEPUBLISH_KNOWLEDGE_BASE_AUTH_BUNDLE",
    )
    app = Application(store)
    result = await app.call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "telegram", "url": URL},
        "request_key": "tg-regular-not-kb",
    })
    assert result["state"] == "accepted", result
    adapter = Adapter()
    assert await Worker(store, {"conn": adapter}).run_once()
    verified = store.receipt(owner, result["operation_id"])
    assert verified["state"] == "verified", verified
    with store.connection() as db:
        assert db.execute(
            "SELECT connection_id FROM destinations"
        ).fetchone()[0] == "conn"

@pytest.mark.asyncio
async def test_owner_discovery_remains_ambiguous_with_two_regular_accounts(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    owner = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(
        owner, "first", "telegram", account_type="mtproto_user",
        secret_ref="VIBEPUBLISH_TEST_FIRST",
    )
    store.add_connection(
        owner, "second", "telegram", account_type="mtproto_user",
        secret_ref="VIBEPUBLISH_TEST_SECOND",
    )
    result = await Application(store).call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "telegram", "url": URL}
    })
    assert result["error"]["code"] == "telegram_discovery_connection_ambiguous"
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0
