"""Legacy false acceptance is withdrawn locally, never resolved as no effect."""
import copy
import json
from dataclasses import replace

import pytest

from adapters.port import Observation, RemoteItem
from adapters.vk import VKAdapter
from social_operations.assets import insert_verified_image, verify_image
from social_operations.domain import DomainError, canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import VKTransport
from tests.providers.test_native_adapters import asset


class LegacyRecoveredVK(VKAdapter):
    """Reproduce the retired text/time/count acceptance through real worker hooks."""
    false_remote = None

    async def execute(self, prepared, hooks):
        if self.false_remote is None:
            return await super().execute(prepared, hooks)
        request = prepared.request
        state = dict(version=1, attempt=request.attempt_id, plan=request.plan_digest,
                     target=request.native_target, id=None,
                     media=[f"photo-101_{9000+i}" for i in range(len(request.assets))])
        await hooks.checkpoint("vk_prepared", canonical(state))
        await hooks.before_effect(request.attempt_id, request.plan_digest)
        raise DomainError("vk_api_failed")

    async def reconcile(self, request, checkpoint_json, hooks):
        if self.false_remote is None:
            return await super().reconcile(request, checkpoint_json, hooks)
        false = replace(self.false_remote, observed_at=timestamp(self.clock()),
                        media_hashes=tuple(a.sha256 for a in request.assets))
        return Observation("provider_scheduled", (false,))


async def scenario(tmp_path, *, prior_kind="owned"):
    now = [1800000000.0]
    store = Store(tmp_path/"ledger.sqlite", clock=lambda: now[0])
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(actor, "vk", "vk", account_type="vk_user")
    store.bind(actor, "owner", "vk", "vk", "-101", rights=("publish", "edit", "cancel", "delete"))
    app, transport = Application(store), VKTransport()
    adapter = LegacyRecoveredVK(transport, connection_id="vk", clock=lambda: now[0])
    worker = Worker(store, {"vk": adapter})
    media = []
    with store.tx() as db:
        for i in range(1, 5):
            ref = insert_verified_image(store, db, actor, verify_image(asset(i).data, "image/png"))
            media.append({"source": {"kind": "asset", "id": ref}, "role": "image"})
    intent = {"to": ["vk"], "content": {"text": "The same night"},
              "delivery": {"kind": "at", "at": timestamp(now[0]+86400)}}
    old = await app.call(actor, "vibepublish_publish", {**intent, "media": media[:2], "request_key": "old"})
    await worker.run_once()
    old = store.receipt(actor, old["operation_id"])
    assert old["state"] == "scheduled", old
    old_ref = old["deliveries"][0]["item_ref"]
    with store.connection() as db:
        row = db.execute("SELECT checkpoint FROM attempts WHERE operation_id=?", (old["operation_id"],)).fetchone()
        adapter.false_remote = RemoteItem(**json.loads(row["checkpoint"])["remote"])
    if prior_kind != "same_time":
        now[0] += 10
    repeated = {"repeat_of": old["operation_id"]} if prior_kind == "same_media" else {}
    inputs = media[:2] if prior_kind == "same_media" else media[2:]
    new = await app.call(actor, "vibepublish_publish", {**intent, "media": inputs, **repeated, "request_key": "new"})
    await worker.run_once()
    assert store.receipt(actor, new["operation_id"])["state"] == "running"
    now[0] += 6
    await worker.run_once()
    new = store.receipt(actor, new["operation_id"])
    assert new["state"] == "scheduled", new
    false_ref = new["deliveries"][0]["item_ref"]
    now[0] += 1
    fresh_read = await app.call(actor, "vibepublish_read", {"query": {"kind": "item", "item_ref": old_ref}})
    await worker.run_once()
    fresh = store.receipt(actor, fresh_read["operation_id"])["items"][0]["ref"]
    args = {"publication_id": new["resource_id"], "expected_revision": 1,
            "change": {"kind": "reconcile", "operation_id": new["operation_id"],
                       "attempt_id": new["deliveries"][0]["attempt_id"], "native_reference": fresh},
            "request_key": "withdraw"}
    return store, actor, app, worker, transport, old, new, args, now, old_ref, false_ref, fresh


def saved(store, operation, attempt):
    with store.connection() as db:
        return dict(
            operation=dict(db.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()),
            attempt=dict(db.execute("SELECT * FROM attempts WHERE id=?", (attempt,)).fetchone()),
            recovery=dict(db.execute("SELECT * FROM attempt_recovery WHERE attempt_id=?", (attempt,)).fetchone()),
            facts=[dict(r) for r in db.execute("SELECT * FROM facts ORDER BY id")],
            refs=[dict(r) for r in db.execute("SELECT * FROM item_refs ORDER BY id")],
            count=db.execute("SELECT count(*) FROM operations").fetchone()[0])


@pytest.mark.asyncio
async def test_withdraw_false_identity_preserves_dispatch_audit_and_old_post(tmp_path, monkeypatch):
    store, actor, app, worker, transport, old, new, args, now, old_ref, false_ref, fresh = await scenario(tmp_path)
    attempt = args["change"]["attempt_id"]
    before = saved(store, new["operation_id"], attempt)
    calls = list(transport.calls)
    assert before["facts"][0]["publication_id"] == old["resource_id"]
    with store.connection() as db:
        old_remote = json.loads(app.resolve_item(db, actor, old_ref)["snapshot"])
    assert json.loads(before["attempt"]["checkpoint"])["remote"]["media_hashes"] != old_remote["media_hashes"]
    result = await app.call(actor, "vibepublish_publication_update", args)
    assert result.get("state") == "outcome_unknown" and result["operation_complete"], result
    delivery = result["deliveries"][0]
    assert delivery["observed"] == "unknown"
    assert not {"item_ref", "queue_ref", "effective_at", "url"} & delivery.keys()
    assert result["next_action"] == "review_outcome"
    after = saved(store, new["operation_id"], attempt)
    def no_status_write():
        raise AssertionError("ordinary status must not acquire a writer")
    with monkeypatch.context() as patch:
        patch.setattr(store, "tx", no_status_write)
        status = (await app.call(actor, "vibepublish_status", {
            "ids": [new["operation_id"]],
        }))["receipts"][0]
    assert status["state"] == "outcome_unknown" and status["operation_complete"], status
    assert status["error"] == result["error"]
    assert status["deliveries"] == result["deliveries"]
    assert not {"progress", "next_action"} & status.keys()
    assert status["summary"]["result"] == "доставка подтверждена в 0 из 1; исход не установлен в 1; отказ в 0"
    network = status["summary"]["networks"][0]
    assert network["status"] == "исход неизвестен"
    assert network["reason"] == "Исход отправки не установлен"
    assert not {"item_ref", "queue_ref", "url"} & network.keys()
    assert saved(store, new["operation_id"], attempt) == after
    for field in ("request", "request_digest", "revision", "created", "publication_id"):
        assert after["operation"][field] == before["operation"][field]
    for field in ("plan", "plan_digest", "dispatched", "dispatch_at"):
        assert after["attempt"][field] == before["attempt"][field]
    assert after["attempt"]["dispatched"] == 1
    for field in ("original_checkpoint", "observation", "plan_digest", "finalize_state"):
        assert after["recovery"][field] == before["recovery"][field]
    assert after["facts"] == before["facts"] and after["count"] == before["count"]
    assert "remote" not in json.loads(after["attempt"]["checkpoint"])
    assert "adapter" not in json.loads(after["attempt"]["checkpoint"])
    proof = json.loads(after["recovery"]["hint"])["withdrawn_observation"]
    assert proof["native_reference"] == fresh and proof["invalidated_refs"] == [false_ref]
    assert proof["prior_publication_id"] == old["resource_id"]
    assert after["refs"] == [r for r in before["refs"] if r["id"] != false_ref]
    with store.connection() as db:
        assert app.resolve_item(db, actor, old_ref)
        assert app.resolve_item(db, actor, fresh)
        with pytest.raises(DomainError) as missing:
            app.resolve_item(db, actor, false_ref)
        assert missing.value.code == "item_not_available"
    unchanged = store.receipt(actor, old["operation_id"])
    assert all(unchanged[key] == old[key] for key in ("state", "revision", "deliveries"))
    assert transport.calls == calls and transport.effects == 1
    assert not await worker.run_once()
    now[0] += 301
    replay = await app.call(actor, "vibepublish_publication_update", args)
    assert replay["operation_id"] == new["operation_id"] and replay["state"] == "outcome_unknown"
    assert saved(store, new["operation_id"], attempt) == after


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["reconcile", "native_reconcile", "new_key", "retry", "supersede",
                                  "removed", "edit", "selected_edit", "cancel", "repeat"])
async def test_withdrawal_never_re_admits_provider_work(tmp_path, route):
    store, actor, app, worker, transport, old, new, args, now, *_ = await scenario(tmp_path)
    corrected = await app.call(actor, "vibepublish_publication_update", args)
    assert corrected["state"] == "outcome_unknown", corrected
    before = saved(store, new["operation_id"], args["change"]["attempt_id"])
    calls = list(transport.calls)
    followup = copy.deepcopy(args)
    followup["request_key"] = "later"
    if route in {"reconcile", "native_reconcile"}:
        followup["change"].pop("native_reference")
        if route == "native_reconcile":
            followup["change"]["native_reference"] = "11"
    elif route == "retry":
        followup["change"] = {"kind": "retry_failed", "destinations": ["vk"]}
    elif route == "supersede":
        followup["change"] = {"kind": "supersede_failed", "destinations": ["vk"], "content": {"text": "New"}}
    elif route == "removed":
        followup["change"] = {"kind": "reconcile_removed", "attempt_id": args["change"]["attempt_id"]}
    elif route in {"edit", "selected_edit"}:
        followup["change"] = {"kind": "edit", "content": {"text": "Do not mutate old post"}}
        if route == "selected_edit":
            followup["change"]["destinations"] = ["vk"]
    elif route == "cancel":
        followup["change"] = {"kind": "cancel"}
    if route == "repeat":
        result = await app.call(actor, "vibepublish_publish", {
            "to": ["vk"], "content": {"text": "The same night"}, "repeat_of": new["operation_id"],
            "request_key": "repeat"})
    else:
        result = await app.call(actor, "vibepublish_publication_update", followup)
    assert "error" in result, result
    if route == "removed":
        assert result["error"]["code"] == "resolution_checkpoint_invalid"
    elif route == "selected_edit":
        assert result["error"]["code"] == "selected_target_not_verified"
    assert saved(store, new["operation_id"], args["change"]["attempt_id"]) == before
    assert transport.calls == calls and transport.effects == 1 and not await worker.run_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", ["expired", "same_time", "same_media", "cross_owner", "wrong_post", "false_ref",
                                     "no_prior_fact", "wrong_fact_owner", "not_exact_read"])
async def test_withdrawal_requires_fresh_private_read_and_positive_prior_ownership(tmp_path, evidence):
    store, actor, app, worker, transport, old, new, args, now, old_ref, false_ref, fresh = await scenario(
        tmp_path, prior_kind=evidence)
    if evidence == "expired":
        now[0] += 301
    elif evidence == "false_ref":
        args["change"]["native_reference"] = false_ref
    elif evidence in {"cross_owner", "wrong_post", "not_exact_read"}:
        other = store.authenticate(store.create_principal("tenant", "other", owner=True)) if evidence == "cross_owner" else actor
        with store.tx() as db:
            binding = store.binding(db, actor, alias="vk")
            remote = json.loads(app.resolve_item(db, actor, fresh)["snapshot"])
            if evidence == "wrong_post":
                remote["native_id"] = "999"
            if evidence == "cross_owner":
                # Projection is intentionally private to another actor, not an exact owner read.
                args["change"]["native_reference"] = app.project_item(db, other, binding, remote)["ref"]
            else:
                args["change"]["native_reference"] = app.project_item(db, actor, binding, remote)["ref"]
    elif evidence in {"no_prior_fact", "wrong_fact_owner"}:
        with store.tx() as db:
            if evidence == "no_prior_fact":
                db.execute("DELETE FROM facts")
            else:
                db.execute("UPDATE facts SET initiator='someone_else'")
    before = saved(store, new["operation_id"], args["change"]["attempt_id"])
    calls = list(transport.calls)
    result = await app.call(actor, "vibepublish_publication_update", args)
    assert "error" in result, result
    assert saved(store, new["operation_id"], args["change"]["attempt_id"]) == before
    assert transport.calls == calls and transport.effects == 1 and not await worker.run_once()
