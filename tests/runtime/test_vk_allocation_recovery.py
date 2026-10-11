"""Allocation-only reconciliation preserves dispatch and never repeats provider effects."""
import copy
import hashlib
import json

import pytest
from jsonschema import Draft202012Validator

from adapters.fake import FakeProvider
from social_operations.assets import import_image
from social_operations.domain import OutcomeUnknown, canonical, new_id
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from social_operations.vk_allocation_recovery import candidate, resolve, resolved
from tests.providers.test_native_adapters import NOW, asset


TARGET = "-241261191"
ALLOCATION = "video-241261191_456239018"


class AllocationCase:
    def __init__(self, root):
        self.store = Store(root / "ledger.sqlite", clock=lambda: NOW)
        self.actor = self.store.authenticate(
            self.store.create_principal("t", "owner", owner=True))
        self.store.add_connection(self.actor, "vk", "vk", account_type="fake")
        self.binding = self.store.bind(self.actor, "owner", "vk", "vk", TARGET)
        self.app = Application(self.store)
        self.provider = FakeProvider(root / "remote.sqlite", "vk", clock=lambda: NOW)
        self.worker = Worker(self.store, {"vk": self.provider})
        self.receipt = self.seed("allocation-original")

    def seed(self, key):
        # The original command is never executed. Bytes are a private database
        # fixture; only the verified immutable plan shape is under test here.
        video = b"fixture-mp4-allocation-only"
        ident = new_id("asset")
        sha = hashlib.sha256(video).hexdigest()
        with self.store.tx() as db:
            db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (ident, self.actor.tenant_id, self.actor.principal_id,
                        sha, "video/mp4", 32, 24, video, sha, NOW))
        receipt = self.app.accept(self.actor, "publish", {
            "to": ["vk"], "content": {"text": key},
            "media": [{"source": {"kind": "asset", "id": ident}, "role": "video"}],
            "request_key": key,
        })
        with self.store.tx() as db:
            child = dict(db.execute("SELECT * FROM attempts WHERE operation_id=?",
                                    (receipt["operation_id"],)).fetchone())
            checkpoint = {
                "transition": "vk_video_allocated",
                "adapter": {
                    "version": 1, "attempt": child["id"], "plan": child["plan_digest"],
                    "target": TARGET, "id": None, "retryable_wall_post": False,
                    "media": [ALLOCATION],
                },
            }
            db.execute("UPDATE attempts SET state='outcome_unknown',stage='outcome_unknown',"
                       "observed='unknown',dispatched=1,dispatch_at=?,checkpoint=?,result=? WHERE id=?",
                       (NOW, canonical(checkpoint),
                        canonical({"missing_checks": ["vk_upload_url_invalid"]}), child["id"]))
            db.execute("UPDATE operations SET state='outcome_unknown',complete=1,work_state='done',"
                       "error=? WHERE id=?",
                       (canonical(OutcomeUnknown("vk_upload_url_invalid").output()), receipt["operation_id"]))
            correlation = {
                "provider": "vk", "action": "publish",
                "operation_id": receipt["operation_id"], "publication_id": receipt["resource_id"],
                "attempt_id": child["id"], "dispatched": True,
            }
            for details in (
                {"operation": "video.save", "status": "completed", "duration_ms": 12},
                {"operation": "execute", "status": "failed", "error_type": "DomainError",
                 "error_code": "vk_upload_url_invalid", "duration_ms": 14},
            ):
                self.store.event(db, receipt["operation_id"], "submitting", details["status"],
                                 "provider_diagnostic " + canonical({**correlation, **details}), "vk")
        return receipt

    def rows(self, receipt=None):
        receipt = receipt or self.receipt
        with self.store.connection() as db:
            op = dict(db.execute("SELECT * FROM operations WHERE id=?",
                                 (receipt["operation_id"],)).fetchone())
            child = dict(db.execute("SELECT * FROM attempts WHERE operation_id=?",
                                    (op["id"],)).fetchone())
        return op, child

    def proof(self):
        op, child = self.rows()
        with self.store.connection() as db:
            return candidate(db, op, child)

    def reconcile_args(self):
        op, child = self.rows()
        return {"publication_id": self.receipt["resource_id"], "expected_revision": 1,
                "change": {"kind": "reconcile", "operation_id": op["id"],
                           "attempt_id": child["id"]}, "request_key": "allocation-reconcile"}

    async def reconcile(self):
        result = await self.app.call(self.actor, "vibepublish_publication_update", self.reconcile_args())
        assert "error" not in result or result["state"] == "partial", result
        if not result["operation_complete"]:
            await self.worker.run_once()
        return self.store.receipt(self.actor, self.receipt["operation_id"])

    async def carousel(self, key):
        images = [import_image(self.store, self.actor, asset(n).data, "image/png") for n in (1, 2)]
        receipt = self.app.accept(self.actor, "publish", {
            "to": ["vk"], "content": {"text": key},
            "media": [{"source": {"kind": "asset", "id": ident}} for ident in images],
            "request_key": key,
        })
        await self.worker.run_once()
        return self.store.receipt(self.actor, receipt["operation_id"])


@pytest.fixture
def case(tmp_path):
    return AllocationCase(tmp_path)


def test_exact_allocated_video_has_positive_correlated_proof(case):
    proof = case.proof()
    assert proof and proof["kind"] == "vk_video_allocation_only"
    assert proof["allocation"] == ALLOCATION
    assert proof["saved_seq"] < proof["failed_seq"]
    assert case.provider.count("execute") == case.provider.count("effect") == 0
    with case.store.connection() as db:
        assert not resolved(db, case.rows()[1])


@pytest.mark.parametrize("field,value", [
    ("transition", "vk_prepared"), ("transition", "vk_media_bound"),
    ("id", "999"), ("retryable_wall_post", True), ("version", 2),
    ("attempt", "attempt_wrong"), ("plan", "0" * 64), ("target", "-999"),
    ("media", []), ("media", [ALLOCATION, ALLOCATION]),
    ("media", ["video-999_456239018"]), ("media", ["photo-241261191_456239018"]),
])
def test_wrong_or_later_provider_phase_never_becomes_candidate(case, field, value):
    op, child = case.rows()
    checkpoint = json.loads(child["checkpoint"])
    (checkpoint if field == "transition" else checkpoint["adapter"])[field] = value
    child["checkpoint"] = canonical(checkpoint)
    with case.store.connection() as db:
        assert candidate(db, op, child) is None


@pytest.mark.parametrize("missing", [
    [], ["vk_upload_failed"], ["vk_http_failed"], ["vk_transport_failed"],
    ["vk_upload_url_invalid", "vk_upload_failed"],
])
def test_unknown_upload_wall_or_ambiguous_error_stays_unknown(case, missing):
    op, child = case.rows()
    child["result"] = canonical({"missing_checks": missing})
    with case.store.connection() as db:
        assert candidate(db, op, child) is None


@pytest.mark.parametrize("which,field,value", [
    (0, "operation", "stories.getVideoUploadServer"),
    (0, "status", "failed"),
    (1, "operation", "media_upload"),
    (1, "error_code", "vk_upload_failed"),
    (1, "attempt_id", "attempt_other"),
    (1, "publication_id", "pub_other"),
    (1, "operation_id", "op_other"),
    (1, "provider", "telegram"),
])
def test_exact_last_diagnostics_and_correlation_required(case, which, field, value):
    op, child = case.rows()
    with case.store.tx() as db:
        events = [dict(row) for row in db.execute("SELECT seq,body FROM events WHERE operation_id=? ORDER BY seq",
                                                  (op["id"],))
                  if json.loads(row["body"]).get("message", "").startswith("provider_diagnostic ")]
        row = events[which]
        body = json.loads(row["body"])
        details = json.loads(body["message"].split(" ", 1)[1])
        details[field] = value
        body["message"] = "provider_diagnostic " + canonical(details)
        db.execute("UPDATE events SET body=? WHERE operation_id=? AND seq=?",
                   (canonical(body), op["id"], row["seq"]))
        assert candidate(db, op, child) is None


@pytest.mark.parametrize("mutation", ["actor_epoch", "binding_epoch", "rights", "inactive", "plan_digest"])
def test_current_authority_and_plan_integrity_are_required(case, mutation):
    op, child = case.rows()
    with case.store.tx() as db:
        if mutation == "actor_epoch":
            db.execute("UPDATE principals SET epoch=epoch+1 WHERE tenant_id=? AND id=?",
                       (case.actor.tenant_id, case.actor.principal_id))
        elif mutation == "binding_epoch":
            db.execute("UPDATE bindings SET epoch=epoch+1 WHERE id=?", (child["binding_id"],))
        elif mutation == "rights":
            db.execute("UPDATE bindings SET rights='[]' WHERE id=?", (child["binding_id"],))
        elif mutation == "inactive":
            db.execute("UPDATE bindings SET active=0 WHERE id=?", (child["binding_id"],))
        else:
            child["plan_digest"] = "0" * 64
        assert candidate(db, op, child) is None


def test_resolution_preserves_allocation_dispatch_and_original_checkpoint(case):
    op, before = case.rows()
    original_checkpoint = json.loads(before["checkpoint"])
    with case.store.tx() as db:
        proof = candidate(db, op, before)
        assert proof
        assert not resolve(case.store, db, op, before, {**proof, "allocation": "video-241261191_999"})
        assert resolve(case.store, db, op, before, proof)
    _, after = case.rows()
    for name in ("id", "operation_id", "binding_id", "binding_epoch", "plan", "plan_digest",
                 "dispatched", "dispatch_at"):
        assert after[name] == before[name]
    checkpoint = json.loads(after["checkpoint"])
    assert checkpoint.pop("known_allocation") == proof
    assert checkpoint == original_checkpoint
    assert after["state"] == "partial" and after["observed"] == "not_attempted"
    assert json.loads(after["result"])["retry_safe"] is False
    with case.store.connection() as db:
        assert resolved(db, after)
        assert case.worker.known_effect_resolved(db, after)
    assert case.provider.count("execute") == case.provider.count("effect") == 0


@pytest.mark.parametrize("field,value", [
    ("allocation", "video-241261191_999"), ("checkpoint_digest", "0" * 64),
    ("plan_digest", "0" * 64), ("attempt_id", "attempt_other"),
    ("operation_id", "op_other"), ("actor_epoch", 999), ("binding_epoch", 999),
    ("saved_digest", "0" * 64), ("failed_digest", "0" * 64),
])
def test_tampered_durable_allocation_proof_never_releases_gate(case, field, value):
    op, child = case.rows()
    with case.store.tx() as db:
        proof = candidate(db, op, child)
        assert proof and resolve(case.store, db, op, child, proof)
    _, child = case.rows()
    checkpoint = json.loads(child["checkpoint"])
    checkpoint["known_allocation"][field] = value
    child["checkpoint"] = canonical(checkpoint)
    with case.store.connection() as db:
        assert not resolved(db, child)


@pytest.mark.asyncio
async def test_only_explicit_reconcile_releases_carousel_without_repeating_video(case):
    blocked = await case.carousel("before-explicit-reconcile")
    assert blocked["state"] == "blocked", blocked
    assert blocked["error"]["code"] == "connection_outcome_unknown"
    op_before, child_before = case.rows()
    executes_before = case.provider.count("execute")
    result = await case.reconcile()
    assert result["state"] == "partial", result
    assert result["operation_id"] == op_before["id"]
    assert result["resource_id"] == case.receipt["resource_id"]
    assert result["retry_safe"] is False
    assert result["deliveries"][0]["reason"] == "vk_video_allocation_only"
    schema = next(t for t in case.app.tools(case.actor)
                  if t["name"] == "vibepublish_publication_update")["outputSchema"]
    Draft202012Validator(schema).validate(result)
    assert case.provider.count("execute") == executes_before
    assert case.provider.count("effect") == 0
    replay = await case.app.call(case.actor, "vibepublish_publication_update", case.reconcile_args())
    assert replay["operation_id"] == result["operation_id"]
    assert not await case.worker.run_once()
    denied = await case.app.call(case.actor, "vibepublish_publication_update", {
        "publication_id": case.receipt["resource_id"], "expected_revision": 1,
        "change": {"kind": "retry_failed", "destinations": ["vk"]},
        "request_key": "must-not-retry-video",
    })
    assert "error" in denied
    fresh = await case.carousel("after-explicit-reconcile")
    assert fresh["state"] == "verified", fresh
    assert case.provider.count("effect") == 1
    _, child_after = case.rows()
    assert child_after["dispatched"] == child_before["dispatched"] == 1
    assert json.loads(child_after["checkpoint"])["adapter"] == json.loads(child_before["checkpoint"])["adapter"]


@pytest.mark.asyncio
async def test_unrelated_second_unknown_keeps_connection_fenced(case):
    second = case.seed("unrelated-unknown")
    _, other = case.rows(second)
    with case.store.tx() as db:
        checkpoint = json.loads(other["checkpoint"])
        checkpoint["transition"] = "vk_prepared"
        db.execute("UPDATE attempts SET checkpoint=? WHERE id=?",
                   (canonical(checkpoint), other["id"]))
    await case.reconcile()
    blocked = await case.carousel("still-blocked-by-second-unknown")
    assert blocked["state"] == "blocked", blocked
    assert blocked["error"]["code"] == "connection_outcome_unknown"
    assert case.provider.count("effect") == 0
    _, preserved = case.rows(second)
    assert preserved["state"] == "outcome_unknown"
    assert preserved["dispatched"] == 1


def insert_validation_before_execute(case, **changes):
    """Insert an additive fixture record without changing the final failure."""
    op, _ = case.rows()
    with case.store.tx() as db:
        row = [dict(row) for row in db.execute(
            "SELECT seq,body FROM events WHERE operation_id=? ORDER BY seq", (op["id"],))
            if json.loads(row["body"]).get("message", "").startswith("provider_diagnostic ")][-1]
        original = json.loads(row["body"])
        details = json.loads(original["message"].split(" ", 1)[1])
        details.update(operation="upload_url_validation", status="failed", phase="media",
                       error_code="vk_upload_url_invalid", url_rejection_reason="host_not_allowed",
                       upload_host="video.example.org")
        details.update(changes)
        replacement = {**original, "message": "provider_diagnostic " + canonical(details)}
        db.execute("UPDATE events SET body=? WHERE operation_id=? AND seq=?",
                   (canonical(replacement), op["id"], row["seq"]))
        case.store.event(db, op["id"], "submitting", "failed", original["message"], "vk")
    return row["seq"]


@pytest.mark.parametrize("count", [1, 3])
def test_validated_read_only_diagnostics_preserve_positive_allocation_proof(case, count):
    sequences = [insert_validation_before_execute(case) for _ in range(count)]
    op, before = case.rows()
    with case.store.tx() as db:
        proof = candidate(db, op, before)
        assert proof
        assert [item["seq"] for item in proof["validation_diagnostics"]] == sequences
        assert all(len(item["digest"]) == 64 for item in proof["validation_diagnostics"])
        assert resolve(case.store, db, op, before, proof)
    _, after = case.rows()
    assert after["dispatched"] == before["dispatched"] == 1
    assert json.loads(after["checkpoint"])["adapter"] == json.loads(before["checkpoint"])["adapter"]
    with case.store.connection() as db:
        assert resolved(db, after)
    assert case.provider.count("effect") == case.provider.count("execute") == 0


@pytest.mark.parametrize("field,value", [
    ("phase", "api"), ("status", "completed"), ("error_code", "vk_upload_failed"),
    ("url_rejection_reason", "unknown_reason"), ("url_rejection_reason", None),
    ("operation", "media_upload"), ("operation", "wall.post"),
    ("operation", "wall.edit"), ("operation", "unrecognized_diagnostic"),
    ("attempt_id", "attempt_other"), ("publication_id", "pub_other"),
    ("operation_id", "op_other"), ("provider", "telegram"),
    ("action", "edit"), ("dispatched", False),
])
def test_only_closed_correlated_local_failure_can_be_filtered(case, field, value):
    insert_validation_before_execute(case)
    insert_validation_before_execute(case, **{field: value})
    insert_validation_before_execute(case)
    assert case.proof() is None


@pytest.mark.parametrize("mutation", ["body", "delete", "proof_digest", "proof_sequence", "omit_proof", "unknown_insert"])
def test_validation_evidence_is_durable_and_cannot_be_removed_or_altered(case, mutation):
    sequence = insert_validation_before_execute(case)
    op, before = case.rows()
    with case.store.tx() as db:
        proof = candidate(db, op, before)
        assert proof and resolve(case.store, db, op, before, proof)
    _, child = case.rows()
    checkpoint = json.loads(child["checkpoint"])
    with case.store.tx() as db:
        if mutation == "body":
            row = db.execute("SELECT body FROM events WHERE operation_id=? AND seq=?", (op["id"], sequence)).fetchone()
            body = json.loads(row["body"])
            details = json.loads(body["message"].split(" ", 1)[1])
            details["upload_host"] = "different.example.org"
            body["message"] = "provider_diagnostic " + canonical(details)
            db.execute("UPDATE events SET body=? WHERE operation_id=? AND seq=?", (canonical(body), op["id"], sequence))
        elif mutation == "delete":
            db.execute("DELETE FROM events WHERE operation_id=? AND seq=?", (op["id"], sequence))
        elif mutation == "proof_digest":
            checkpoint["known_allocation"]["validation_diagnostics"][0]["digest"] = "0" * 64
        elif mutation == "proof_sequence":
            checkpoint["known_allocation"]["validation_diagnostics"][0]["seq"] = proof["saved_seq"]
        elif mutation == "omit_proof":
            checkpoint["known_allocation"].pop("validation_diagnostics")
        else:
            row = db.execute("SELECT body FROM events WHERE operation_id=? AND seq=?", (op["id"], sequence)).fetchone()
            body = json.loads(row["body"])
            details = json.loads(body["message"].split(" ", 1)[1])
            details["operation"] = "wall.post"
            body["message"] = "provider_diagnostic " + canonical(details)
            db.execute("UPDATE events SET body=? WHERE operation_id=? AND seq=?", (canonical(body), op["id"], sequence))
        child["checkpoint"] = canonical(checkpoint)
        assert not resolved(db, child)


@pytest.mark.asyncio
async def test_multiple_safe_diagnostics_do_not_authorize_automatic_recovery(case):
    for _ in range(3):
        insert_validation_before_execute(case)
    assert case.proof()
    blocked = await case.carousel("diagnostics-before-explicit-reconcile")
    assert blocked["state"] == "blocked" and blocked["error"]["code"] == "connection_outcome_unknown"
    await case.reconcile()
    fresh = await case.carousel("diagnostics-after-explicit-reconcile")
    assert fresh["state"] == "verified"
    assert case.provider.count("effect") == 1
