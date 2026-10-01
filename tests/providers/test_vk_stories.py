from __future__ import annotations

import hashlib
import io

import pytest
from PIL import Image

from adapters.vk import VKAdapter
from adapters.vk_discovery import resolve as resolve_vk
from adapters.vk_transport import VKHTTPTransport, VKToken
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from .scripted import VKTransport


def png_bytes(width=90, height=160):
    stream = io.BytesIO()
    Image.new("RGB", (width, height), (30, 60, 90)).save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.asyncio
async def test_vk_handle_discovery_uses_exact_provider_lookup_without_numeric_cast():
    transport = VKTransport()
    adapter = VKAdapter(transport, connection_id="connection", clock=lambda: 1_800_000_000)
    evidence = await resolve_vk(adapter, {"url": "https://vk.com/fixture_group"})
    assert evidence["native_id"] == "-101"
    assert evidence["label"] == "Fixture group"
    assert "publish" in evidence["rights"]
    assert transport.calls[0][0] == "groups.getById"
    assert transport.calls[0][2]["group_ids"] == "fixture_group"


@pytest.mark.asyncio
async def test_http_transport_accepts_exact_vk_handle_for_readonly_group_lookup(monkeypatch):
    transport = VKHTTPTransport(tokens={
        "reader": VKToken("reader-token", "user"),
        "editor": VKToken("editor-token", "user"),
        "media": VKToken("media-token", "user"),
    })
    seen = {}

    async def fake_post(url, data, *, api=False):
        seen.update(url=url, data=data, api=api)
        return {"response": [{"id": 101, "name": "Fixture", "screen_name": "fixture_group"}]}

    monkeypatch.setattr(transport, "_post", fake_post)
    response = await transport.invoke(
        role="reader", method="groups.getById",
        params={"group_ids": "fixture_group", "fields": "is_admin,admin_level"},
    )
    assert response[0]["id"] == 101
    assert seen["data"]["group_ids"] == "fixture_group"


@pytest.mark.asyncio
async def test_vk_story_publish_exact_readback_capability_and_delete_by_item_ref(tmp_path):
    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal("tenant", "owner", owner=True)
    actor = store.authenticate(token)
    store.add_connection(actor, "vk-connection", "vk", account_type="vk_user", secret_ref="VIBEPUBLISH_TEST")
    store.bind(actor, "owner", "vk-story", "vk-connection", "-101", label="Fixture group")

    data = png_bytes()
    sha = hashlib.sha256(data).hexdigest()
    with store.tx() as db:
        db.execute(
            "INSERT INTO assets(id,tenant_id,principal_id,sha256,mime,width,height,bytes,source_sha256,created) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("asset_story", actor.tenant_id, actor.principal_id, sha, "image/png", 90, 160, data, sha, store.clock()),
        )

    transport = VKTransport()
    worker = Worker(store, {"vk-connection": VKAdapter(
        transport, connection_id="vk-connection", clock=store.clock
    )})
    app = Application(store)

    accepted = await app.call(actor, "vibepublish_publish", {
        "to": ["vk-story"],
        "content": {"text": ""},
        "media": [{"source": {"kind": "asset", "id": "asset_story"}, "role": "image"}],
        "surface": "story",
        "request_key": "story-publish",
    })
    assert accepted["state"] == "accepted", accepted
    assert await worker.run_once()

    receipt = store.receipt(actor, accepted["operation_id"])
    assert receipt["state"] == "verified", receipt
    delivery = receipt["deliveries"][0]
    assert delivery["observed"] == "published"
    assert delivery["media_check"] == "provider_binding"
    assert transport.effects == 1
    assert [name for name, *_ in transport.calls if name.startswith("stories.")] == [
        "stories.getPhotoUploadServer", "stories.save", "stories.getById"
    ]

    bootstrap = await app.call(actor, "vibepublish_get_started", {})
    post_cap = next(row for row in bootstrap["capabilities"]
                    if row["destination"] == "vk-story" and row["surface"] == "post")
    story_cap = next(row for row in bootstrap["capabilities"]
                     if row["destination"] == "vk-story" and row["surface"] == "story")
    assert post_cap["status"] == "needs_review"
    assert story_cap["status"] == "supported"

    item_ref = delivery["item_ref"]
    deleted = await app.call(actor, "vibepublish_publication_update", {
        "item_ref": item_ref,
        "change": {"kind": "delete"},
        "request_key": "story-delete",
    })
    assert deleted["state"] == "accepted", deleted
    assert await worker.run_once()
    deletion = store.receipt(actor, deleted["operation_id"])
    assert deletion["state"] == "verified", deletion
    assert deletion["deliveries"][0]["observed"] == "deleted"
    assert transport.effects == 2
    assert not transport.stories


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"content": {"text": "caption"}},
    {"content": {"text": ""}, "media": []},
])
async def test_vk_story_contract_fails_closed_for_unsupported_payload(tmp_path, bad):
    store = Store(tmp_path / "ledger.sqlite")
    token = store.create_principal("tenant", "owner", owner=True)
    actor = store.authenticate(token)
    store.add_connection(actor, "vk-connection", "vk", account_type="vk_user", secret_ref="VIBEPUBLISH_TEST")
    store.bind(actor, "owner", "vk-story", "vk-connection", "-101")

    if bad.get("media") != []:
        data = png_bytes()
        sha = hashlib.sha256(data).hexdigest()
        with store.tx() as db:
            db.execute(
                "INSERT INTO assets(id,tenant_id,principal_id,sha256,mime,width,height,bytes,source_sha256,created) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("asset_story", actor.tenant_id, actor.principal_id, sha, "image/png", 90, 160, data, sha, store.clock()),
            )
        bad["media"] = [{"source": {"kind": "asset", "id": "asset_story"}, "role": "image"}]

    app = Application(store)
    accepted = await app.call(actor, "vibepublish_publish", {
        "to": ["vk-story"], "surface": "story", "request_key": "bad-story", **bad
    })
    if "error" in accepted:
        assert accepted["error"]["code"] in {"invalid_input", "empty_publication"}
        return
    worker = Worker(store, {"vk-connection": VKAdapter(
        VKTransport(), connection_id="vk-connection", clock=store.clock
    )})
    assert await worker.run_once()
    receipt = store.receipt(actor, accepted["operation_id"])
    assert receipt["state"] == "blocked"
