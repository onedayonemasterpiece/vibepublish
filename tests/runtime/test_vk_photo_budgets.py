"""Deterministic budget regressions; no real waiting or provider traffic."""
import json
from contextlib import asynccontextmanager
import pytest
from social_operations.execution_budgets import execution_seconds, command_seconds
from social_operations.domain import DomainError
from .test_baseline_rebase import scenario


def plan(count, **changes):
    return {"provider":"vk", "surface":"post", "action":"edit",
            "assets":[{"role":"image", "mime":"image/png"} for _ in range(count)], **changes}


@pytest.mark.parametrize("count,execute,command", [(0,90,120),(1,90,120),(2,180,210),(4,360,390),(10,600,630),(100,600,630)])
def test_photo_budgets_are_bounded(count,execute,command):
    assert execution_seconds(plan(count)) == execute
    assert command_seconds([plan(count)]) == command


@pytest.mark.parametrize("changes", [
    {"provider":"telegram"}, {"provider":"max"}, {"surface":"story"},
    {"action":"read"}, {"action":"delete"},
    {"assets":[{"role":"video","mime":"video/mp4"}]*4},
])
def test_unrelated_work_keeps_existing_budget(changes):
    assert execution_seconds(plan(4,**changes)) == 90
    assert command_seconds([plan(4,**changes)]) == 120


@pytest.mark.asyncio
async def test_four_photo_edit_can_stage_beyond_old_ninety_second_cap(tmp_path,monkeypatch):
    import social_operations.worker as module
    store,actor,app,worker,t,native,desired,failed,args,now = await scenario(tmp_path)
    await app.call(actor,"vibepublish_publication_update",args)
    edit = await app.call(actor,"vibepublish_publication_update",{
        "publication_id":args["publication_id"],"expected_revision":3,
        "change":desired,"request_key":"four-photo-budget"})
    with store.connection() as db:
        row = db.execute("SELECT created,deadline FROM operations WHERE id=?",(edit["operation_id"],)).fetchone()
        assert row["deadline"] - row["created"] == 390
    budgets, elapsed = [], [0]
    @asynccontextmanager
    async def measured_timeout(seconds):
        budgets.append(seconds)
        yield
    monkeypatch.setattr(module.asyncio,"timeout",measured_timeout)
    upload = t.upload_photo
    async def slow_upload(url,data,mime):
        elapsed[0] += 31
        # Deterministic virtual elapsed time: the old90s limit fails image4.
        if elapsed[0] > budgets[-1]:
            raise TimeoutError("simulated execution deadline")
        return await upload(url,data,mime)
    t.upload_photo = slow_upload
    await worker.run_once()
    result = store.receipt(actor,edit["operation_id"])
    assert result["state"] == "verified", result
    assert budgets[-1] == 360 and elapsed[0] == 124
    assert t.effects == 2 and list(t.posts) == [native]
    assert len(t.posts[native]["attachments"]) == 4


@pytest.mark.asyncio
async def test_automatic_retry_keeps_original_bounded_command_budget(tmp_path):
    store,actor,app,worker,t,native,desired,failed,args,now = await scenario(tmp_path)
    await app.call(actor,"vibepublish_publication_update",args)
    async def failed_upload(*args):
        raise DomainError("vk_http_failed",message="VK media_upload HTTP status 502")
    t.upload_photo = failed_upload
    edit = await app.call(actor,"vibepublish_publication_update",{
        "publication_id":args["publication_id"],"expected_revision":3,
        "change":desired,"request_key":"budget-failure"})
    await worker.run_once()
    with store.connection() as db:
        deadline = db.execute("SELECT deadline,created FROM operations WHERE id=?",
                              (edit["operation_id"],)).fetchone()
        assert deadline["deadline"] == deadline["created"] + 390
    assert store.receipt(actor,edit["operation_id"])["state"] == "running"
    now[0] += 5.001
    await worker.run_once()  # Same attempt retries; no explicit recovery command.
    with store.connection() as db:
        after = db.execute("SELECT deadline FROM operations WHERE id=?",
                           (edit["operation_id"],)).fetchone()[0]
        assert after == deadline["deadline"]


@pytest.mark.asyncio
async def test_supersede_and_auto_resume_keep_carousel_budget(tmp_path):
    store,actor,app,worker,t,native,desired,failed,args,now = await scenario(tmp_path)
    async def failed_upload(*args):
        raise DomainError("fixture_upload_failed")
    t.upload_photo = failed_upload
    initial = await app.call(actor,"vibepublish_publish",{
        "to":["vk"],"content":{"text":"New carousel"},"media":desired["media"],
        "request_key":"failed-carousel"})
    await worker.run_once()
    result = store.receipt(actor,initial["operation_id"])
    assert result["state"] == "blocked", result
    replacement = await app.call(actor,"vibepublish_publication_update",{
        "publication_id":initial["resource_id"],"expected_revision":1,
        "change":{"kind":"supersede_failed","destinations":["vk"],"content":{"text":"Corrected"}},
        "request_key":"replace-failed-carousel"})
    assert "error" not in replacement, replacement
    with store.connection() as db:
        row = db.execute("SELECT created,deadline FROM operations WHERE id=?",(replacement["operation_id"],)).fetchone()
        assert row["deadline"]-row["created"] == 390
    await worker.run_once()
    now[0] += 200
    # Model an eligible pre-dispatch provider failure after terminal observation.
    with store.tx() as db:
        db.execute("UPDATE attempts SET result=? WHERE operation_id=?",
                   (json.dumps({"missing_checks":["vk_http_failed"]}),replacement["operation_id"]))
        operation = dict(db.execute("SELECT * FROM operations WHERE id=?",(replacement["operation_id"],)).fetchone())
    worker.schedule_retry(operation)
    with store.connection() as db:
        row = db.execute("SELECT created,deadline,complete FROM operations WHERE id=?",
                         (replacement["operation_id"],)).fetchone()
        assert row["deadline"] == row["created"] + 390 and row["complete"] == 0
