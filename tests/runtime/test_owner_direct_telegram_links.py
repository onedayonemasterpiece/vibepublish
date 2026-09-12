from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from social_operations.ingress import IngressApplication
from social_operations.storage import Store
from tests.providers.test_native_adapters import NOW


URL_A = "https://t.me/c/4379835477/5"
URL_B = "https://t.me/c/987654321/17"
URL_PUBLIC = "https://t.me/publicforum/23"
URL_PUBLIC_ROOT = "https://t.me/publicforum"
URL_PRIVATE_ROOT = "https://t.me/c/987654321"
TARGET_A = "-1004379835477"
TARGET_B = "-1000987654321"


def owner_app(*, connections=1):
    temp = tempfile.TemporaryDirectory()
    store = Store(Path(temp.name) / "ledger.sqlite", clock=lambda: NOW)
    token = store.create_principal("tenant", "owner", owner=True)
    actor = store.authenticate(token)
    for index in range(connections):
        store.add_connection(
            actor, f"conn_tg_{index}", "telegram", account_type="mtproto_user",
            secret_ref=f"VIBEPUBLISH_TELEGRAM_{index}", shared=True,
        )
    return temp, store, actor, IngressApplication(store)


def publish_tool(app, actor):
    return next(tool for tool in app.tools(actor) if tool["name"] == "vibepublish_publish")


@pytest.mark.asyncio
async def test_owner_thread_link_is_the_target_not_one_prebound_chat():
    temp, store, actor, app = owner_app()
    try:
        schema = publish_tool(app, actor)["inputSchema"]
        assert "to" not in schema.get("required", [])

        first = await app.call(actor, "vibepublish_publish", {
            "thread_ref": URL_A,
            "content": {"text": "First arbitrary chat"},
            "request_key": "direct-a",
        })
        second = await app.call(actor, "vibepublish_publish", {
            "thread_ref": URL_B,
            "content": {"text": "Second arbitrary chat"},
            "request_key": "direct-b",
        })
        assert first["state"] == second["state"] == "accepted"

        with store.connection() as db:
            rows = [
                json.loads(row["plan"])
                for row in db.execute(
                    "SELECT plan FROM attempts WHERE operation_id IN (?,?) ORDER BY operation_id",
                    (first["operation_id"], second["operation_id"]),
                )
            ]
            targets = {(row["native_target"], row["topic_root_id"]) for row in rows}
            assert targets == {(TARGET_A, "5"), (TARGET_B, "17")}
            assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 2
            assert app.aliases(db, actor) == []
    finally:
        temp.cleanup()


@pytest.mark.asyncio
async def test_owner_public_permalink_is_admitted_without_precreated_destination():
    temp, store, actor, app = owner_app()
    try:
        accepted = await app.call(actor, "vibepublish_publish", {
            "thread_ref": URL_PUBLIC,
            "content": {"text": "Public permalink target"},
            "request_key": "direct-public",
        })
        assert accepted["state"] == "accepted", accepted
        with store.connection() as db:
            plan = json.loads(db.execute(
                "SELECT plan FROM attempts WHERE operation_id=?", (accepted["operation_id"],)
            ).fetchone()[0])
            assert plan["native_target"] == "publicforum"
            assert plan["topic_root_id"] == "23"
            binding = store.binding(db, actor, binding_id=plan["binding_id"])
            assert binding["native_id"] == "publicforum"
            assert app.aliases(db, actor) == []
    finally:
        temp.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "target"),
    [(URL_PUBLIC_ROOT, "publicforum"), (URL_PRIVATE_ROOT, TARGET_B)],
)
async def test_owner_chat_root_link_needs_no_precreated_destination(url, target):
    temp, store, actor, app = owner_app()
    try:
        accepted = await app.call(actor, "vibepublish_publish", {
            "thread_ref": url,
            "content": {"text": "Chat root target"},
            "request_key": "root-" + target.replace("-", "n"),
        })
        assert accepted["state"] == "accepted", accepted
        with store.connection() as db:
            plan = json.loads(db.execute(
                "SELECT plan FROM attempts WHERE operation_id=?", (accepted["operation_id"],)
            ).fetchone()[0])
            assert plan["native_target"] == target
            assert "topic_root_id" not in plan
            assert app.aliases(db, actor) == []
    finally:
        temp.cleanup()


@pytest.mark.asyncio
async def test_owner_can_read_new_thread_link_without_precreated_destination():
    temp, store, actor, app = owner_app()
    try:
        accepted = await app.call(actor, "vibepublish_read", {
            "query": {"kind": "thread", "item_ref": URL_B},
            "limit": 10,
        })
        assert accepted["state"] == "accepted", accepted
        with store.connection() as db:
            request = json.loads(db.execute(
                "SELECT request FROM operations WHERE id=?", (accepted["operation_id"],)
            ).fetchone()[0])
            binding = store.binding(db, actor, binding_id=request["_binding_id"])
            assert binding["native_id"] == TARGET_B
            assert request["_topic_root_id"] == "17"
    finally:
        temp.cleanup()


@pytest.mark.asyncio
async def test_owner_can_read_public_permalink_without_precreated_destination():
    temp, store, actor, app = owner_app()
    try:
        accepted = await app.call(actor, "vibepublish_read", {
            "query": {"kind": "thread", "item_ref": URL_PUBLIC},
            "limit": 10,
        })
        assert accepted["state"] == "accepted", accepted
        with store.connection() as db:
            request = json.loads(db.execute(
                "SELECT request FROM operations WHERE id=?", (accepted["operation_id"],)
            ).fetchone()[0])
            binding = store.binding(db, actor, binding_id=request["_binding_id"])
            assert binding["native_id"] == "publicforum"
            assert request["_topic_root_id"] == "23"
    finally:
        temp.cleanup()


@pytest.mark.asyncio
async def test_owner_can_read_public_chat_root_without_precreated_destination():
    temp, store, actor, app = owner_app()
    try:
        accepted = await app.call(actor, "vibepublish_read", {
            "query": {"kind": "thread", "item_ref": URL_PUBLIC_ROOT},
            "limit": 10,
        })
        assert accepted["state"] == "accepted", accepted
        with store.connection() as db:
            request = json.loads(db.execute(
                "SELECT request FROM operations WHERE id=?", (accepted["operation_id"],)
            ).fetchone()[0])
            binding = store.binding(db, actor, binding_id=request["_binding_id"])
            assert binding["native_id"] == "publicforum"
            assert request["_topic_root_id"] is None
    finally:
        temp.cleanup()


@pytest.mark.asyncio
async def test_invalid_command_does_not_materialize_hidden_route():
    temp, store, actor, app = owner_app()
    try:
        rejected = await app.call(actor, "vibepublish_publish", {
            "thread_ref": URL_PUBLIC_ROOT,
            "content": {"not_text": "schema violation"},
        })
        assert rejected["error"]["code"] == "invalid_input"
        with store.connection() as db:
            assert db.execute("SELECT count(*) FROM destinations").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0
    finally:
        temp.cleanup()


@pytest.mark.asyncio
async def test_invite_link_is_not_treated_as_destination_identity():
    temp, store, actor, app = owner_app()
    try:
        rejected = await app.call(actor, "vibepublish_publish", {
            "thread_ref": "https://t.me/+AbCdEfGhIjKlMnOp",
            "content": {"text": "Do not join or infer"},
        })
        assert rejected["error"]["code"] == "invalid_input"
        with store.connection() as db:
            assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0
    finally:
        temp.cleanup()


@pytest.mark.asyncio
async def test_multiple_telegram_connections_require_selector_but_target_still_comes_from_link():
    temp, store, actor, app = owner_app(connections=2)
    try:
        ambiguous = await app.call(actor, "vibepublish_publish", {
            "thread_ref": URL_A,
            "content": {"text": "Ambiguous account"},
            "request_key": "ambiguous",
        })
        assert ambiguous["error"]["code"] == "telegram_connection_ambiguous"

        store.bind(actor, "owner", "telegram_account", "conn_tg_1", "-1001111111111")
        accepted = await app.call(actor, "vibepublish_publish", {
            "to": ["telegram_account"],
            "thread_ref": URL_A,
            "content": {"text": "Selected account, arbitrary chat"},
            "request_key": "selected-account",
        })
        assert accepted["state"] == "accepted", accepted
        with store.connection() as db:
            plan = json.loads(db.execute(
                "SELECT plan FROM attempts WHERE operation_id=?", (accepted["operation_id"],)
            ).fetchone()[0])
            assert plan["connection_id"] == "conn_tg_1"
            assert plan["native_target"] == TARGET_A
            assert plan["topic_root_id"] == "5"
    finally:
        temp.cleanup()


def test_partner_contract_still_requires_explicit_destination_binding():
    temp, store, owner, app = owner_app()
    try:
        token = store.create_principal("tenant", "partner", owner=False)
        partner = store.authenticate(token)
        schema = publish_tool(app, partner)["inputSchema"]
        assert schema.get("required") == ["to"]
    finally:
        temp.cleanup()
