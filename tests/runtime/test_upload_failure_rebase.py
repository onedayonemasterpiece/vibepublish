"""Explicit fresh-read recovery after a proven no-dispatch upload failure."""
import json
from unittest.mock import AsyncMock
import pytest
from social_operations.domain import DomainError
from .test_baseline_rebase import scenario


async def failed_upload(tmp_path):
    values = await scenario(tmp_path)
    store,actor,app,worker,t,native,desired,failed,args,now = values
    await app.call(actor, "vibepublish_publication_update", args)
    upload = t.upload_photo
    # Three bounded upload tries are tested in the provider suite. This fixture
    # returns the same safe failure directly to keep ledger tests quick.
    t.upload_photo = AsyncMock(side_effect=DomainError(
        "vk_http_failed", message="VK media_upload HTTP status 504"))
    edit = await app.call(actor, "vibepublish_publication_update", {
        "publication_id":args["publication_id"],"expected_revision":3,
        "change":desired,"request_key":"upload-failure"})
    await worker.run_once()
    retry_args = {"publication_id":args["publication_id"],"expected_revision":4,
        "change":{"kind":"retry_failed","destinations":["vk"]},"request_key":"one-recovery"}
    await app.call(actor,"vibepublish_publication_update",retry_args)
    await worker.run_once()
    receipt = store.receipt(actor,edit["operation_id"])
    assert receipt["state"] == "blocked", receipt
    with store.connection() as db:
        row = db.execute("SELECT checkpoint,dispatched FROM attempts WHERE operation_id=?",
                         (edit["operation_id"],)).fetchone()
        assert not json.loads(row["checkpoint"]).get("remote") and not row["dispatched"]
    read = await app.call(actor, "vibepublish_read", {"query":{
        "kind":"item","item_ref":args["change"]["native_reference"]}})
    await worker.run_once()
    fresh = store.receipt(actor,read["operation_id"])["items"][0]["ref"]
    rebase = {"publication_id":args["publication_id"],"expected_revision":4,
        "change":{"kind":"reconcile","operation_id":edit["operation_id"],
                  "attempt_id":receipt["deliveries"][0]["attempt_id"],"native_reference":fresh},
        "request_key":"upload-rebase"}
    t.upload_photo = upload
    return values, edit, retry_args, rebase


@pytest.mark.asyncio
async def test_terminal_upload_rebase_then_explicit_edit_preserves_receipt(tmp_path):
    values,edit,retry_args,args = await failed_upload(tmp_path)
    store,actor,app,worker,t,native,desired,_,_,now = values
    before = store.receipt(actor,edit["operation_id"])
    with store.connection() as db:
        frozen = tuple(db.execute("SELECT plan,checkpoint,result FROM attempts WHERE operation_id=?",
                                 (edit["operation_id"],)).fetchone())
    rebased = await app.call(actor,"vibepublish_publication_update",args)
    assert rebased["state"] == "verified" and rebased["revision"] == 5, rebased
    assert t.effects == 1
    replay = await app.call(actor,"vibepublish_publication_update",retry_args)
    assert replay["operation_id"] == edit["operation_id"] and replay["state"] == "blocked"
    with store.connection() as db:
        assert tuple(db.execute("SELECT plan,checkpoint,result FROM attempts WHERE operation_id=?",
                               (edit["operation_id"],)).fetchone()) == frozen
    new = await app.call(actor,"vibepublish_publication_update",{
        "publication_id":args["publication_id"],"expected_revision":5,
        "change":desired,"request_key":"new-authorized-edit"})
    await worker.run_once()
    assert store.receipt(actor,new["operation_id"])["state"] == "verified"
    assert list(t.posts) == [native] and len(t.posts[native]["attachments"]) == 4
    assert t.effects == 2
    assert store.receipt(actor,edit["operation_id"])["error"] == before["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", ["dispatched","unknown","api","timeout","stale"])
async def test_upload_rebase_requires_exact_proven_safe_failure(tmp_path,unsafe):
    values,edit,_,args = await failed_upload(tmp_path)
    store,actor,app,worker,t,native,desired,_,_,now = values
    if unsafe == "stale":
        now[0] += 301
    else:
        with store.tx() as db:
            if unsafe == "dispatched":
                db.execute("UPDATE attempts SET dispatched=1 WHERE operation_id=?",(edit["operation_id"],))
            elif unsafe == "unknown":
                db.execute("UPDATE attempts SET state='outcome_unknown' WHERE operation_id=?",(edit["operation_id"],))
            else:
                message = "VK api HTTP status 504" if unsafe == "api" else "Upload timed out"
                db.execute("UPDATE operations SET error=? WHERE id=?",
                    (json.dumps({"error":{"code":"vk_http_failed","message":message}}),edit["operation_id"]))
    result = await app.call(actor,"vibepublish_publication_update",args)
    assert "error" in result and t.effects == 1


@pytest.mark.asyncio
async def test_native_change_after_upload_rebase_still_blocks(tmp_path):
    values,edit,_,args = await failed_upload(tmp_path)
    store,actor,app,worker,t,native,desired,_,_,now = values
    await app.call(actor,"vibepublish_publication_update",args)
    t.posts[native]["text"] = "Changed after fresh read"
    new = await app.call(actor,"vibepublish_publication_update",{
        "publication_id":args["publication_id"],"expected_revision":5,
        "change":desired,"request_key":"new-edit-after-change"})
    await worker.run_once()
    assert store.receipt(actor,new["operation_id"])["error"]["code"] == "remote_revision_conflict"
    assert t.effects == 1
