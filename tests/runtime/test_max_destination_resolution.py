"""MAX exact registration, not live publishing; all provider observations are injected."""
from contextlib import contextmanager
import json

import pytest

from adapters.max_discovery import parse_destination_url, resolve
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker

URL = "https://max.ru/channel_uh_kaliningrad"
EVIDENCE = dict(url=URL, native_id="-123456", label="Ух ты, Калининград!",
                kind="channel", publish_verified=True, source="max_web_visible_channel")


class Adapter:
    account_type = "max_web"
    live_enabled = True
    connection_id = "conn"

    def __init__(self, evidence=None, after_read=None):
        self.evidence = dict(EVIDENCE if evidence is None else evidence)
        self.calls = 0
        self.registrations = 0
        self.persisted = False
        self.after_read = after_read

    async def resolve_destination(self, url):
        assert url == URL
        self.calls += 1
        if self.after_read:
            self.after_read()
        return self.evidence

    @contextmanager
    def register_resolved_destination(self, evidence):
        assert evidence["rights"] == ["publish"]
        self.registrations += 1
        before = self.persisted
        self.persisted = True
        try:
            yield
        except BaseException:
            self.persisted = before
            raise


def setup(tmp_path, *, owner=True, connections=1):
    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal("tenant", "owner", owner=owner)
    actor = store.authenticate(token)
    if owner:
        for i in range(connections):
            store.add_connection(actor, "conn" if i == 0 else "second", "max",
                account_type="max_web", secret_ref="VIBEPUBLISH_MAX_PROFILE")
    return store, actor, token


async def run(store, actor, adapter, key="exact-max"):
    receipt = await Application(store).call(actor, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "max", "url": URL},
        "request_key": key})
    assert receipt["state"] == "accepted", receipt
    assert await Worker(store, {"conn": adapter}).run_once()
    return store.receipt(actor, receipt["operation_id"])


@pytest.mark.parametrize("url", [
    "http://max.ru/channel_name", "https://max.ru.evil/channel_name",
    "https://max.ru:443/channel_name", "https://user@max.ru/channel_name",
    "https://user:pass@max.ru/channel_name", "https://web.max.ru/-123",
    "https://max.ru/channel_name?x=1", "https://max.ru/channel_name#part",
    "https://max.ru/join/token", "https://max.ru/share", "https://max.ru/a",
    "https://max.ru/channel_name/post", "https://max.ru/%63hannel_name",
    "https://max.ru/channel name", "https://max.ru/channel_name\n",
    "https://max.ru/channel_name\\evil", None,
])
def test_invalid_exact_urls(url):
    with pytest.raises(DomainError, match="max destination url invalid"):
        parse_destination_url(url)


def test_canonical_public_url():
    assert parse_destination_url(URL + "/") == URL


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"kind": "group"}, {"publish_verified": False}, {"native_id": "-0"},
    {"native_id": "123"}, {"url": URL + "_other"}, {"label": ""},
    {"source": "untrusted_title_search"},
])
async def test_unverified_provider_evidence_cannot_grant(change):
    with pytest.raises(DomainError):
        await resolve(Adapter(dict(EVIDENCE, **change)), URL)


@pytest.mark.asyncio
async def test_owner_exact_binding_replay_persist_and_publish_only(tmp_path):
    store, owner, _ = setup(tmp_path)
    adapter = Adapter()
    result = await run(store, owner, adapter)
    assert result["state"] == "verified", result
    destination = result["destinations"][0]
    assert destination["native_id"] == "-123456"
    assert destination["provider"] == "max"
    assert destination["label"] == EVIDENCE["label"]
    replay = await Application(store).call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "max", "url": URL},
        "request_key": "exact-max"})
    assert replay["operation_id"] == result["operation_id"]
    assert adapter.calls == 1
    again = await run(store, owner, adapter, "exact-max-again")
    assert again["destinations"] == result["destinations"]
    assert adapter.persisted
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 1
        assert json.loads(db.execute("SELECT rights FROM bindings").fetchone()[0]) == ["publish"]


@pytest.mark.asyncio
async def test_existing_alias_is_retained(tmp_path):
    store, owner, _ = setup(tmp_path)
    store.bind(owner, "owner", "max-kaliningrad", "conn", "-123456", rights=["publish"])
    result = await run(store, owner, Adapter())
    assert result["state"] == "verified", result
    assert result["destinations"][0]["alias"] == "max-kaliningrad"


@pytest.mark.asyncio
async def test_ambiguous_connection_and_partner_cannot_resolve(tmp_path):
    store, owner, _ = setup(tmp_path, connections=2)
    result = await Application(store).call(owner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "max", "url": URL}})
    assert result["error"]["code"] == "max_discovery_connection_ambiguous"
    partner = store.authenticate(store.create_principal("tenant", "partner", owner=False))
    result = await Application(store).call(partner, "vibepublish_destinations", {
        "command": {"kind": "resolve", "provider": "max", "url": URL}})
    assert result["error"]["code"] in {"access_denied", "scope_denied"}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"kind": "group"}, {"publish_verified": False}])
async def test_failed_provider_verification_has_no_binding(tmp_path, change):
    store, owner, _ = setup(tmp_path)
    adapter = Adapter(dict(EVIDENCE, **change))
    result = await run(store, owner, adapter)
    assert result["state"] == "blocked"
    assert adapter.registrations == 0
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_revoked_binding_stays_revoked(tmp_path):
    store, owner, token = setup(tmp_path)
    await run(store, owner, Adapter())
    with store.connection() as db:
        binding = db.execute("SELECT id FROM bindings").fetchone()[0]
    store.revoke_binding(owner, binding)
    owner = store.authenticate(token)
    adapter = Adapter()
    result = await run(store, owner, adapter, "after-revocation")
    assert result["state"] == "blocked"
    assert adapter.registrations == 0


@pytest.mark.asyncio
async def test_revocation_during_provider_read_prevents_persistence(tmp_path):
    store, owner, _ = setup(tmp_path)
    def revoke():
        with store.tx() as db:
            db.execute("UPDATE connections SET active=0 WHERE id='conn'")
    adapter = Adapter(after_read=revoke)
    result = await run(store, owner, adapter)
    assert result["state"] == "blocked"
    assert adapter.registrations == 0



@pytest.mark.asyncio
async def test_connection_replacement_during_read_prevents_persistence(tmp_path):
    store, owner, _ = setup(tmp_path)
    def replace_connection():
        with store.tx() as db:
            db.execute("UPDATE connections SET secret_ref='VIBEPUBLISH_OTHER_PROFILE' WHERE id='conn'")
    adapter = Adapter(after_read=replace_connection)
    result = await run(store, owner, adapter)
    assert result["state"] == "blocked"
    assert adapter.registrations == 0


@pytest.mark.asyncio
async def test_ledger_failure_rolls_back_runtime_registration(tmp_path, monkeypatch):
    store, owner, _ = setup(tmp_path)
    original = store.event
    def fail_completion(db, operation, stage, status, message, *args, **kwargs):
        if stage == "finished" and status == "completed" and message.startswith("max exact"):
            raise DomainError("injected_ledger_failure")
        return original(db, operation, stage, status, message, *args, **kwargs)
    monkeypatch.setattr(store, "event", fail_completion)
    adapter = Adapter()
    result = await run(store, owner, adapter)
    assert result["state"] == "blocked"
    assert adapter.registrations == 1
    assert not adapter.persisted
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0
