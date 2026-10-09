"""A known Telegram permalink reads an exact native item inside existing rights.

No account-wide message lookup, source-channel adoption or provider mutation.
"""
from __future__ import annotations

import json
import pytest

from social_operations.service import Application
from social_operations.storage import Store


@pytest.mark.asyncio
async def test_bound_public_telegram_permalink_reads_exact_native_item(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(actor, "conn", "telegram", account_type="mtproto_user",
                         secret_ref="VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE")
    store.bind(actor, "owner", "announcements", "conn", "-1004444555566",
               handle="kenigevents")
    response = await Application(store).call(
        actor, "vibepublish_read",
        {"query": {"kind": "item", "item_ref": "https://t.me/kenigevents/5224"}})
    assert response["state"] == "accepted", response
    with store.connection() as db:
        request = json.loads(db.execute(
            "SELECT request FROM operations WHERE id=?", (response["operation_id"],)
        ).fetchone()[0])
        binding = store.binding(db, actor, binding_id=request["_binding_id"])
    assert binding["alias"] == "announcements"
    assert request["_native_item"] == "5224"
    assert request["_namespace"] == "published"


@pytest.mark.asyncio
async def test_bound_private_telegram_permalink_and_denied_foreign_link(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(actor, "conn", "telegram", account_type="mtproto_user",
                         secret_ref="VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE")
    store.bind(actor, "owner", "private_posts", "conn", "-1004379835477")
    app = Application(store)
    good = await app.call(actor, "vibepublish_read",
                          {"query": {"kind": "item",
                                     "item_ref": "https://t.me/c/4379835477/5224"}})
    assert good["state"] == "accepted", good
    for url in ("https://t.me/c/4379835478/5224",
                "https://t.me/notourchannel/5224",
                "https://vk.ru/wall-123_456"):
        denied = await app.call(actor, "vibepublish_read",
                                {"query": {"kind": "item", "item_ref": url}})
        assert denied.get("error", {}).get("code") in {
            "item_link_not_bound", "item_link_provider_not_enabled"
        }, denied
    with store.connection() as db:
        # No new binding or leaked channel from any URL.
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 1
