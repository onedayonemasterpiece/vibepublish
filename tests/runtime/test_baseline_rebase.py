"""Explicit no-effect rebase retains native identity and future edit CAS."""
import copy
import json
import pytest

from adapters.vk import VKAdapter
from social_operations.assets import insert_verified_image, verify_image
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import VKTransport
from tests.providers.test_native_adapters import asset


async def scenario(tmp_path):
    now = [1800000000.0]
    store = Store(tmp_path/"ledger.sqlite", clock=lambda:now[0])
    actor = store.authenticate(store.create_principal("tenant","owner",owner=True))
    store.add_connection(actor,"vk","vk",account_type="vk_user")
    store.bind(actor,"owner","vk","vk","-101",rights=("publish","edit"))
    app = Application(store)
    transport = VKTransport()
    worker = Worker(store, {"vk":VKAdapter(transport,connection_id="vk",clock=lambda:now[0])})
    media = []
    with store.tx() as db:
        for i in range(1,5):
            ref = insert_verified_image(store, db, actor, verify_image(asset(i).data,"image/png"))
            media.append({"source":{"kind":"asset","id":ref},"role":"image"})
    initial = await app.call(actor,"vibepublish_publish",{"to":["vk"],"content":{"text":"Original"}})
    await worker.run_once()
    assert store.receipt(actor,initial["operation_id"])["state"] == "verified"
    native = next(iter(transport.posts))
    transport.posts[native]["text"] = "Manual owner correction"
    desired = {"kind":"edit","content":{"text":"Authorized replacement"},"media":media}
    failed = await app.call(actor,"vibepublish_publication_update",{
        "publication_id":initial["resource_id"],"expected_revision":1,
        "change":desired,"request_key":"edit"})
    await worker.run_once()
    result = store.receipt(actor,failed["operation_id"])
    assert result["error"]["code"] == "remote_revision_conflict", result
    assert transport.effects == 1
    read = await app.call(actor,"vibepublish_read",{"query":{"kind":"item",
        "item_ref":store.receipt(actor,initial["operation_id"])["deliveries"][0]["item_ref"]}})
    await worker.run_once()
    fresh = store.receipt(actor,read["operation_id"])["items"][0]["ref"]
    args = {"publication_id":initial["resource_id"],"expected_revision":2,
        "change":{"kind":"reconcile","operation_id":failed["operation_id"],
                  "attempt_id":result["deliveries"][0]["attempt_id"],"native_reference":fresh},
        "request_key":"rebase"}
    return store, actor, app, worker, transport, native, desired, failed, args, now


@pytest.mark.asyncio
async def test_rebase_is_local_immutable_and_edit_keeps_post_and_four_photos(tmp_path):
    store,actor,app,worker,t,native,desired,failed,args,now = await scenario(tmp_path)
    with store.connection() as db:
        old = tuple(db.execute("SELECT plan,checkpoint FROM attempts WHERE operation_id=?",
                               (failed["operation_id"],)).fetchone())
    rebased = await app.call(actor,"vibepublish_publication_update",args)
    assert rebased["state"] == "verified" and rebased["revision"] == 3, rebased
    assert rebased["resource_id"] == args["publication_id"]
    assert t.effects == 1 and not await worker.run_once()
    replay = await app.call(actor,"vibepublish_publication_update",args)
    assert replay["operation_id"] == rebased["operation_id"] and replay["revision"] == 3
    with store.connection() as db:
        assert tuple(db.execute("SELECT plan,checkpoint FROM attempts WHERE operation_id=?",
                                (failed["operation_id"],)).fetchone()) == old
    edited = await app.call(actor,"vibepublish_publication_update",{
        "publication_id":args["publication_id"],"expected_revision":3,
        "change":desired,"request_key":"edit-after-rebase"})
    await worker.run_once()
    result = store.receipt(actor,edited["operation_id"])
    assert result["state"] == "verified", result
    assert t.effects == 2 and list(t.posts) == [native]
    assert t.posts[native]["text"] == "Authorized replacement"
    assert len(t.posts[native]["attachments"]) == 4
    assert result["deliveries"][0]["observed"] == "edited"


@pytest.mark.asyncio
async def test_second_remote_change_still_blocks_after_rebase(tmp_path):
    store,actor,app,worker,t,native,desired,failed,args,now = await scenario(tmp_path)
    await app.call(actor,"vibepublish_publication_update",args)
    t.posts[native]["text"] = "Another manual change"
    edited = await app.call(actor,"vibepublish_publication_update",{
        "publication_id":args["publication_id"],"expected_revision":3,
        "change":desired,"request_key":"changed-again"})
    await worker.run_once()
    assert store.receipt(actor,edited["operation_id"])["error"]["code"] == "remote_revision_conflict"
    assert t.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["stale","wrong_post","dispatched","wrong_attempt","revision","key"])
async def test_rebase_rejects_unsafe_or_mismatched_evidence(tmp_path,tamper):
    store,actor,app,worker,t,native,desired,failed,args,now = await scenario(tmp_path)
    if tamper == "stale":
        now[0] += 301
    elif tamper == "wrong_post":
        with store.tx() as db:
            db.execute("UPDATE item_refs SET native_id='999999' WHERE id=?",
                       (args["change"]["native_reference"],))
    elif tamper == "dispatched":
        with store.tx() as db:
            db.execute("UPDATE attempts SET dispatched=1 WHERE operation_id=?",
                       (failed["operation_id"],))
    elif tamper == "wrong_attempt":
        args["change"]["attempt_id"] = "attempt_" + "a"*32
    elif tamper == "revision":
        args["expected_revision"] = 1
    else:
        args.pop("request_key")
    result = await app.call(actor,"vibepublish_publication_update",args)
    assert "error" in result, result
    assert t.effects == 1
    with store.connection() as db:
        assert db.execute("SELECT revision FROM publications WHERE id=?",
                          (args["publication_id"],)).fetchone()[0] == 2
