"""Outgoing VK suggestions: provider-shaped fake, actual SQLite and worker routing."""
import json

import pytest

from adapters.vk import VKAdapter
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import VKTransport

OWNER = -241261191
TARGET = 123456789
MEDIA = [f"photo-241261191_{457239100 + i}" for i in range(6)]


def setup(tmp_path, *, account_type="vk_user"):
    store = Store(tmp_path / "outgoing.sqlite", clock=lambda: 1800000000)
    owner = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(owner, "conn", "vk", account_type=account_type)
    store.bind(owner, "owner", "lovekenig_vk", "conn", str(OWNER),
               rights=("publish", "edit", "reschedule", "cancel", "delete"))
    transport = VKTransport()
    transport.groups[-OWNER] = {"id": -OWNER, "is_admin": 1, "admin_level": 3, "is_closed": 0}
    transport.groups[TARGET] = {"id": TARGET, "type": "page", "is_admin": 0, "is_closed": 0,
                                "screen_name": "eto_koenig"}
    transport.posts[(OWNER, 270)] = {
        "id": 270, "owner_id": OWNER, "text": "Наши шесть карточек", "date": 1799999999,
        "post_type": "post", "attachments": [
            {"type": "photo", "photo": {"owner_id": OWNER, "id": 457239100 + i}}
            for i in range(6)],
    }
    app = Application(store)
    adapter = VKAdapter(transport, connection_id="conn", account_type=account_type,
                        clock=lambda: 1800000000)
    worker = Worker(store, {"conn": adapter}, connection_ids=("conn",),
                    include_unrouted=False)
    return store, owner, app, worker, transport


async def item_ref(store, actor, app, worker):
    accepted = await app.call(actor, "vibepublish_read", {
        "query": {"kind": "item", "item_ref": "https://vk.com/wall-241261191_270"}})
    assert "error" not in accepted, accepted
    assert await worker.run_once(operation_id=accepted["operation_id"])
    result = store.receipt(actor, accepted["operation_id"])
    assert result["state"] == "verified", result
    return result["items"][0]["ref"]


def cmd(kind, ref=None, *, key="proposal-once"):
    result = {"command": {"kind": kind}}
    if kind != "list":
        result["command"].update(source_item_ref=ref, target_group_id=str(TARGET))
    if kind == "submit":
        result["request_key"] = key
    return result


@pytest.mark.asyncio
async def test_published_carousel_is_proposed_once_as_user_and_visible_in_history(tmp_path):
    store, owner, app, worker, transport = setup(tmp_path)
    ref = await item_ref(store, owner, app, worker)
    before = json.dumps(transport.posts[(OWNER, 270)], sort_keys=True)
    preview = await app.call(owner, "vibepublish_vk_proposals", cmd("preview", ref))
    assert preview["state"] == "verified", preview
    assert preview["vk_proposal"]["status"] == "preview"
    assert preview["vk_proposal"]["attachments"] == MEDIA
    assert not any(name == "wall.post" for name, _, _ in transport.calls)
    result = await app.call(owner, "vibepublish_vk_proposals", cmd("submit", ref))
    assert result["state"] == "accepted", result
    assert await worker.run_once(operation_id=result["operation_id"])
    status = store.receipt(owner, result["operation_id"])
    assert status["state"] == "verified", status
    assert status["vk_proposal"]["status"] == "submitted"
    assert status["vk_proposal"]["moderation_status"] == "unverified"
    assert status["vk_proposal"]["post_id"].isdigit()
    assert json.dumps(transport.posts[(OWNER, 270)], sort_keys=True) == before
    sends = [params for name, _, params in transport.calls if name == "wall.post"]
    assert len(sends) == 1
    assert sends[0]["owner_id"] == -TARGET
    assert sends[0]["from_group"] == 0
    assert sends[0]["signed"] == 0
    assert sends[0]["attachments"] == ",".join(MEDIA)
    assert sends[0]["primary_attachments_mode"] == "carousel"
    repeat = await app.call(owner, "vibepublish_vk_proposals", cmd("submit", ref))
    different_key = await app.call(owner, "vibepublish_vk_proposals", cmd("submit", ref, key="new-key"))
    assert repeat["operation_id"] == different_key["operation_id"] == result["operation_id"]
    assert len([call for call in transport.calls if call[0] == "wall.post"]) == 1
    listed = await app.call(owner, "vibepublish_vk_proposals", {"command": {"kind": "list"}})
    assert listed["vk_proposals"][0]["operation_id"] == result["operation_id"]
    assert listed["vk_proposals"][0]["status"] == "submitted"
    assert len(listed["vk_proposals"]) == 1
    # The history is a durable owner-only ledger, not a temporary runtime cache.
    reopened = Application(Store(tmp_path / "outgoing.sqlite", clock=lambda: 1800000000))
    after_restart = await reopened.call(owner, "vibepublish_vk_proposals", {"command": {"kind": "list"}})
    assert after_restart["vk_proposals"][0]["operation_id"] == result["operation_id"]
    assert after_restart["vk_proposals"][0]["status"] == "submitted"


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction", ["group_token", "admin", "ordinary_group", "closed"])
async def test_foreign_wall_proposal_refuses_public_publishing_or_group_token(tmp_path, restriction):
    store, owner, app, worker, transport = setup(tmp_path,
        account_type="vk_group" if restriction == "group_token" else "vk_user")
    ref = await item_ref(store, owner, app, worker)
    if restriction == "group_token":
        preview = await app.call(owner, "vibepublish_vk_proposals", cmd("preview", ref))
        assert preview["vk_proposal"]["status"] == "preview"
        assert len(preview["vk_proposal"]["attachments"]) == 6
        refused = await app.call(owner, "vibepublish_vk_proposals", cmd("submit", ref))
        assert refused["error"]["code"] == "vk_proposal_user_connection_required"
        assert not any(call[0] == "wall.post" for call in transport.calls)
        return
    group = transport.groups[TARGET]
    if restriction == "admin":
        group["is_admin"] = 1
    elif restriction == "ordinary_group":
        group["type"] = "group"
    else:
        group["is_closed"] = 1
    admitted = await app.call(owner, "vibepublish_vk_proposals", cmd("submit", ref))
    assert "error" not in admitted
    await worker.run_once(operation_id=admitted["operation_id"])
    status = store.receipt(owner, admitted["operation_id"])
    assert status["state"] == "blocked"
    assert status["vk_proposal"]["status"] == "failed"
    assert not any(call[0] == "wall.post" for call in transport.calls)


@pytest.mark.asyncio
async def test_lost_response_never_sends_second_proposal(tmp_path):
    store, owner, app, worker, transport = setup(tmp_path)
    ref = await item_ref(store, owner, app, worker)
    def drop_after_submit(method):
        if method == "wall.post":
            raise OSError("lost response after VK accepted")
    transport.after_mutation = drop_after_submit
    accepted = await app.call(owner, "vibepublish_vk_proposals", cmd("submit", ref))
    assert await worker.run_once(operation_id=accepted["operation_id"])
    result = store.receipt(owner, accepted["operation_id"])
    assert result["state"] == "outcome_unknown", result
    assert result["vk_proposal"]["status"] == "outcome_unknown"
    assert transport.effects == 1
    again = await app.call(owner, "vibepublish_vk_proposals", cmd("submit", ref, key="another-key"))
    assert again["operation_id"] == accepted["operation_id"]
    assert not await worker.run_once(operation_id=accepted["operation_id"])
    assert transport.effects == 1


@pytest.mark.asyncio
async def test_vk_short_name_target_resolution_and_approval_safety(tmp_path):
    store, owner, app, worker, transport = setup(tmp_path)
    ref = await item_ref(store, owner, app, worker)
    by_handle = {"command": {"kind": "preview", "source_item_ref": ref,
                              "target_screen_name": "eto_koenig"}}
    preview = await app.call(owner, "vibepublish_vk_proposals", by_handle)
    assert preview["vk_proposal"]["target_url"] == "https://vk.com/eto_koenig"
    assert "target_group_id" not in preview["vk_proposal"]
    by_handle["command"]["kind"] = "submit"
    by_handle["request_key"] = "by-screen-name"
    accepted = await app.call(owner, "vibepublish_vk_proposals", by_handle)
    await worker.run_once(operation_id=accepted["operation_id"])
    result = store.receipt(owner, accepted["operation_id"])
    assert result["vk_proposal"]["target_group_id"] == str(TARGET)
    assert result["vk_proposal"]["status"] == "submitted"
    assert transport.posts[(OWNER, 270)]["text"] == "Наши шесть карточек"


@pytest.mark.asyncio
async def test_source_vk_group_and_separate_user_sender(tmp_path):
    store, owner, app, worker, transport = setup(tmp_path, account_type="vk_group")
    store.add_connection(owner, "user_conn", "vk", account_type="vk_user")
    store.bind(owner, "owner", "user_sender", "user_conn", "-9000099", rights=("publish",))
    worker.adapters["user_conn"] = VKAdapter(transport, connection_id="user_conn",
                                            account_type="vk_user", clock=lambda: 1800000000)
    worker.connection_ids = ("conn", "user_conn")
    ref = await item_ref(store, owner, app, worker)
    accepted = await app.call(owner, "vibepublish_vk_proposals", {
        "command": {"kind": "submit", "source_item_ref": ref,
                    "target_screen_name": "eto_koenig", "sender_alias": "user_sender"},
        "request_key": "separate-sender"})
    assert accepted["state"] == "accepted", accepted
    await worker.run_once(operation_id=accepted["operation_id"])
    result = store.receipt(owner, accepted["operation_id"])
    assert result["vk_proposal"]["status"] == "submitted", result


@pytest.mark.asyncio
async def test_source_change_is_detected_before_proposal(tmp_path):
    store, owner, app, worker, transport = setup(tmp_path)
    ref = await item_ref(store, owner, app, worker)
    accepted = await app.call(owner, "vibepublish_vk_proposals", cmd("submit", ref))
    transport.posts[(OWNER, 270)]["attachments"].reverse()
    await worker.run_once(operation_id=accepted["operation_id"])
    result = store.receipt(owner, accepted["operation_id"])
    assert result["vk_proposal"]["error_code"] == "vk_proposal_source_changed"
    assert not any(call[0] == "wall.post" for call in transport.calls)
