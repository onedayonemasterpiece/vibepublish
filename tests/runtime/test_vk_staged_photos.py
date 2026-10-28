"""Reuse only complete immutable staging from an earlier authorized edit."""
import copy
import json
from dataclasses import asdict

import pytest

from adapters.port import RemoteItem
from social_operations.assets import import_image
from social_operations.domain import DomainError, canonical, digest, new_id, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.vk_staged_photos import select
from tests.providers.test_native_adapters import NOW, asset


class StagingCase:
    def __init__(self, root, count=4):
        self.store = Store(root / "ledger.sqlite", clock=lambda: NOW)
        self.actor = self.store.authenticate(self.store.create_principal("t", "owner", owner=True))
        self.store.add_connection(self.actor, "vk", "vk", account_type="vk_user")
        self.store.bind(self.actor, "owner", "vk", "vk", "-101", rights=("publish", "edit"))
        self.app = Application(self.store)
        refs = [import_image(self.store, self.actor, asset(n).data, "image/png") for n in range(1, count + 1)]
        initial = self.app.accept(self.actor, "publish",
                                  {"to": ["vk"], "content": {"text": "Original"}, "request_key": "seed"})
        remote = asdict(RemoteItem("77", "published", "Original", "fixture", timestamp(NOW),
                                   native_target="-101"))
        with self.store.tx() as db:
            db.execute("UPDATE attempts SET state='verified',dispatched=1,observed='published',checkpoint=? "
                       "WHERE operation_id=?", (canonical({"remote": remote}), initial["operation_id"]))
            db.execute("UPDATE operations SET state='verified',complete=1,work_state='done' WHERE id=?",
                       (initial["operation_id"],))
        source = self.app.accept(self.actor, "publication_update", {
            "publication_id": initial["resource_id"], "expected_revision": 1,
            "change": {"kind": "edit", "content": {"text": "Authorized four photos"},
                       "media": [{"source": {"kind": "asset", "id": ref}, "role": "image"} for ref in refs]},
            "request_key": "first-edit",
        })
        with self.store.tx() as db:
            child = dict(db.execute("SELECT * FROM attempts WHERE operation_id=?",
                                    (source["operation_id"],)).fetchone())
            plan = json.loads(child["plan"])
            self.asset_hashes = [item["sha256"] for item in plan["assets"]]
            self.media = ["photo81_" + str(1001 + i) for i in range(count)]
            cp = {"transition": "vk_prepared", "adapter": {
                "version": 1, "attempt": child["id"], "plan": child["plan_digest"],
                "target": "-101", "id": "77", "retryable_wall_post": False,
                "source": None, "media": self.media,
            }}
            db.execute("UPDATE attempts SET state='blocked',stage='blocked',checkpoint=?,result=? WHERE id=?",
                       (canonical(cp), canonical({"missing_checks": ["connection_outcome_unknown"]}), child["id"]))
            db.execute("UPDATE operations SET state='blocked',complete=1,work_state='done' WHERE id=?",
                       (source["operation_id"],))
            self.source_operation = source["operation_id"]
            self.source_attempt = child["id"]
            self.publication = initial["resource_id"]
            # Isolated fixture for a NEW explicitly authorized edit revision.
            # It does not re-arm the previous request or alter its frozen plan.
            db.execute("UPDATE publications SET revision=3 WHERE id=?", (self.publication,))
            self.operation = self.app._new_operation(
                db, self.actor, "publication_update", {"item_ref": "fresh-fixture", "change": {"kind": "edit"}},
                publication=self.publication, revision=3, command_timeout=390)
            self.attempt = new_id("attempt")
            db.execute("INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,plan,plan_digest) "
                       "VALUES(?,?,?,?,?,?,?,?)",
                       (self.attempt, self.operation, child["binding_id"], child["binding_epoch"],
                        child["alias"], child["provider"], child["plan"], child["plan_digest"]))

    def rows(self):
        with self.store.connection() as db:
            op = dict(db.execute("SELECT * FROM operations WHERE id=?", (self.operation,)).fetchone())
            child = dict(db.execute("SELECT * FROM attempts WHERE id=?", (self.attempt,)).fetchone())
        return op, child

    def selected(self):
        op, child = self.rows()
        with self.store.connection() as db:
            return select(db, op, child)

    def checkpoint(self, mutation):
        with self.store.tx() as db:
            row = db.execute("SELECT checkpoint FROM attempts WHERE id=?", (self.source_attempt,)).fetchone()
            cp = json.loads(row["checkpoint"])
            mutation(cp)
            db.execute("UPDATE attempts SET checkpoint=? WHERE id=?", (canonical(cp), self.source_attempt))


@pytest.fixture
def case(tmp_path):
    return StagingCase(tmp_path)


def test_exact_prior_staging_selected_without_mutating_source(case):
    with case.store.connection() as db:
        before = tuple(db.execute("SELECT * FROM attempts WHERE id=?", (case.source_attempt,)).fetchone())
    result = case.selected()
    assert result == {
        "media": case.media,
        "source_attempt_id": case.source_attempt, "source_plan_digest": before[7],
        "target": "-101", "post_id": "77",
        "asset_hashes": case.asset_hashes,
    }
    with case.store.connection() as db:
        assert tuple(db.execute("SELECT * FROM attempts WHERE id=?", (case.source_attempt,)).fetchone()) == before


@pytest.mark.parametrize("field,value", [
    ("dispatched", 1), ("state", "outcome_unknown"), ("state", "partial"),
    ("state", "running"), ("state", "verified"), ("binding_epoch", 999),
])
def test_source_must_be_terminal_and_never_dispatched(case, field, value):
    with case.store.tx() as db:
        db.execute("UPDATE attempts SET " + field + "=? WHERE id=?", (value, case.source_attempt))
    assert case.selected() is None


@pytest.mark.parametrize("field,value", [
    ("complete", 0), ("actor_epoch", 999), ("revision", 4),
    ("publication_id", None),
])
def test_source_operation_scope_and_prior_revision_required(case, field, value):
    with case.store.tx() as db:
        db.execute("UPDATE operations SET " + field + "=? WHERE id=?", (value, case.source_operation))
    assert case.selected() is None


@pytest.mark.parametrize("field,value", [
    ("transition", "vk_response"), ("version", 2), ("attempt", "attempt_other"),
    ("plan", "0" * 64), ("target", "-202"), ("id", "78"),
    ("retryable_wall_post", True), ("source", {"untrusted": "forward"}),
    ("media", []), ("retryable_wall_post", "invalid"),
])
def test_incomplete_or_mismatched_checkpoint_is_not_reused(case, field, value):
    def mutate(cp):
        (cp if field == "transition" else cp["adapter"])[field] = value
    case.checkpoint(mutate)
    if field == "transition":
        assert case.selected() is None
    else:
        with pytest.raises(DomainError, match="vk staged photos invalid"):
            case.selected()


@pytest.mark.parametrize("mode", ["duplicate", "wrong_kind", "empty_id", "missing_owner",
                                  "zero_owner", "zero_photo", "bool_media", "access_key"])
def test_all_native_photo_ids_must_be_complete_and_sanitized(case, mode):
    def mutate(cp):
        data = cp["adapter"]
        if mode == "duplicate":
            data["media"][1] = data["media"][0]
        else:
            data["media"][0] = {
                "wrong_kind": "video81_1001",
                "empty_id": "",
                "missing_owner": "photo_1001",
                "zero_owner": "photo0_1001",
                "zero_photo": "photo81_0",
                "bool_media": True,
                "access_key": "photo81_1001_secret",
            }[mode]
    case.checkpoint(mutate)
    with pytest.raises(DomainError, match="vk staged photos invalid"):
        case.selected()


@pytest.mark.parametrize("mode", ["asset_order", "asset_sha", "asset_ref", "post_id",
                                  "provider", "action", "scheduled", "source", "plan_digest", "dispatched"])
def test_new_edit_must_match_the_original_frozen_media_intent(case, mode):
    op, child = case.rows()
    plan = json.loads(child["plan"])
    if mode == "asset_order":
        plan["assets"].reverse()
    elif mode == "asset_sha":
        plan["assets"][0]["sha256"] = "f" * 64
    elif mode == "asset_ref":
        plan["assets"][0]["ref"] = "asset_other"
    elif mode == "post_id":
        plan["existing"]["native_id"] = "78"
    elif mode == "provider":
        child["provider"] = plan["provider"] = "telegram"
    elif mode == "action":
        plan["action"] = "publish"
    elif mode == "scheduled":
        plan["scheduled_at"] = timestamp(NOW + 3600)
    elif mode == "source":
        plan["source"] = {"provider": "vk"}
    elif mode == "dispatched":
        child["dispatched"] = 1
    child["plan"] = canonical(plan)
    child["plan_digest"] = "0" * 64 if mode == "plan_digest" else digest(plan)
    with case.store.connection() as db:
        assert select(db, op, child) is None


@pytest.mark.parametrize("mode", ["actor_epoch", "binding_epoch", "rights", "binding_inactive", "connection_inactive"])
def test_current_authority_is_rechecked(case, mode):
    op, child = case.rows()
    with case.store.tx() as db:
        if mode == "actor_epoch":
            db.execute("UPDATE principals SET epoch=epoch+1 WHERE tenant_id=? AND id=?",
                       (case.actor.tenant_id, case.actor.principal_id))
        elif mode == "binding_epoch":
            db.execute("UPDATE bindings SET epoch=epoch+1 WHERE id=?", (child["binding_id"],))
        elif mode == "rights":
            db.execute("UPDATE bindings SET rights='[]' WHERE id=?", (child["binding_id"],))
        elif mode == "binding_inactive":
            db.execute("UPDATE bindings SET active=0 WHERE id=?", (child["binding_id"],))
        else:
            db.execute("UPDATE connections SET active=0 WHERE id='vk'")
        assert select(db, op, child) is None


@pytest.mark.parametrize("count", [1, 2, 4, 10])
def test_new_authorized_caption_reuses_same_ordered_assets(tmp_path, count):
    case = StagingCase(tmp_path, count=count)
    op, child = case.rows()
    plan = json.loads(child["plan"])
    plan["content_json"] = canonical({"text": "New explicitly authorized caption"})
    child["plan"] = canonical(plan)
    child["plan_digest"] = digest(plan)
    with case.store.connection() as db:
        selected = select(db, op, child)
    assert selected is not None
    assert selected["media"] == case.media and len(selected["media"]) == count
    assert selected["asset_hashes"] == [a["sha256"] for a in plan["assets"]]


async def partial_worker_case(root):
    """Actual worker failure after two verified saves, with no external network."""
    from adapters.vk import VKAdapter
    from social_operations.domain import DomainError
    from social_operations.worker import Worker
    from tests.providers.test_vk_staged_photo_reuse import SavedPhotos

    now = [NOW]
    store = Store(root / "partial.sqlite", clock=lambda: now[0])
    actor = store.authenticate(store.create_principal("t", "owner", owner=True))
    store.add_connection(actor, "vk", "vk", account_type="vk_user")
    store.bind(actor, "owner", "vk", "vk", "-101", rights=("publish", "edit"))
    app = Application(store)
    transport = SavedPhotos()
    adapter = VKAdapter(transport, connection_id="vk", clock=lambda: now[0])
    worker = Worker(store, {"vk": adapter})
    initial = app.accept(actor, "publish", {
        "to": ["vk"], "content": {"text": "Original"}, "request_key": "partial-original"})
    await worker.run_once()
    assert store.receipt(actor, initial["operation_id"])["state"] == "verified"
    refs = [import_image(store, actor, asset(n).data, "image/png") for n in range(1, 5)]
    failure = {"at": 3}
    upload = transport.upload_photo
    async def fail_selected_upload(*args):
        if failure["at"] == len(transport.uploads) + 1:
            failure["at"] = None
            raise DomainError("vk_http_failed", "VK media_upload HTTP status 504")
        return await upload(*args)
    transport.upload_photo = fail_selected_upload
    edited = await app.call(actor, "vibepublish_publication_update", {
        "publication_id": initial["resource_id"], "expected_revision": 1,
        "change": {"kind": "edit", "content": {"text": "Four photos"},
                   "media": [{"source": {"kind": "asset", "id": ref}, "role": "image"} for ref in refs]},
        "request_key": "partial-edit"})
    await worker.run_once()
    assert store.receipt(actor, edited["operation_id"])["state"] == "running"
    assert len(transport.uploads) == 2 and transport.effects == 1
    return store, actor, app, worker, transport, edited, failure, now


def staged_row(store, operation):
    with store.connection() as db:
        return dict(db.execute("SELECT * FROM attempts WHERE operation_id=?", (operation,)).fetchone())


def retry_args(receipt, key):
    return {"publication_id": receipt["resource_id"], "expected_revision": receipt["revision"],
            "change": {"kind": "retry_failed", "destinations": ["vk"]}, "request_key": key}


def replacement_worker(store, transport, now):
    from adapters.vk import VKAdapter
    from social_operations.worker import Worker
    reopened = Store(store.path, clock=lambda: now[0])
    return Worker(reopened, {"vk": VKAdapter(transport, connection_id="vk", clock=lambda: now[0])})


@pytest.mark.asyncio
async def test_automatic_retry_new_worker_resumes_two_of_four_without_reupload(tmp_path):
    store, actor, app, worker, transport, edited, failure, now = await partial_worker_case(tmp_path)
    before = staged_row(store, edited["operation_id"])
    cp = json.loads(before["checkpoint"])
    assert cp["transition"] == "vk_photo_staging"
    assert len(cp["adapter"]["media"]) == 2
    assert cp["adapter"]["attempt"] == before["id"]
    assert cp["adapter"]["plan"] == before["plan_digest"]
    assert cp["adapter"]["target"] == "-101"
    assert "photo_proofs" not in cp["adapter"]
    start = len(transport.calls)
    now[0] += 5.001
    restarted = replacement_worker(store, transport, now)
    await restarted.run_once()
    result = store.receipt(actor, edited["operation_id"])
    assert result["state"] == "verified", result
    assert len(transport.uploads) == 4 and transport.effects == 2
    assert staged_row(store, edited["operation_id"])["id"] == before["id"]
    calls = transport.calls[start:]
    assert not any(method == "photos.getById" for method, _, _ in calls)
    assert sum(method == "upload_photo" for method, _, _ in calls) == 2
    assert sum(method == "photos.saveWallPhoto" for method, _, _ in calls) == 2
    assert sum(method == "wall.edit" for method, _, _ in calls) == 1
    assert not any(method == "wall.post" for method, _, _ in calls)
    final_checkpoint = json.loads(staged_row(store, edited["operation_id"])["checkpoint"])
    assert final_checkpoint["remote"]["provider_media"][:2] == ["photo-101_11001", "photo-101_11002"]
    assert not await restarted.run_once()
    assert len(transport.uploads) == 4 and transport.effects == 2


@pytest.mark.asyncio
async def test_later_suffix_failure_retries_without_new_key_or_manual_rebase(tmp_path):
    store, actor, app, worker, transport, edited, failure, now = await partial_worker_case(tmp_path)
    initial = json.loads(staged_row(store, edited["operation_id"])["checkpoint"])["adapter"]
    failure["at"] = 4
    now[0] += 5.001
    restarted = replacement_worker(store, transport, now)
    await restarted.run_once()
    result = store.receipt(actor, edited["operation_id"])
    assert result["state"] == "running", result
    cp = json.loads(staged_row(store, edited["operation_id"])["checkpoint"])
    assert cp["transition"] == "vk_photo_staging"
    assert len(cp["adapter"]["media"]) == 3
    assert cp["adapter"]["media"][:2] == initial["media"]
    assert cp["adapter"]["attempt"] == initial["attempt"]
    assert cp["adapter"]["plan"] == initial["plan"]
    assert cp["adapter"]["target"] == initial["target"]
    assert "photo_proofs" not in cp["adapter"]
    assert len(transport.uploads) == 3 and transport.effects == 1
    now[0] += 15.001
    await restarted.run_once()
    result = store.receipt(actor, edited["operation_id"])
    assert result["state"] == "verified", result
    assert len(transport.uploads) == 4 and transport.effects == 2
    assert sum(method == "photos.saveWallPhoto" for method, _, _ in transport.calls) == 4
    assert sum(method == "wall.edit" for method, _, _ in transport.calls) == 1
    assert not await restarted.run_once()


def current_prefix(case, action, count):
    op, child = case.rows()
    plan = json.loads(child["plan"])
    if action == "publish":
        plan.update(action="publish", existing=None)
        op["action"] = "publish"
    child["plan"], child["plan_digest"] = canonical(plan), digest(plan)
    child["checkpoint"] = canonical({"transition": "vk_photo_staging", "adapter": {
        "version": 1, "attempt": child["id"], "plan": child["plan_digest"],
        "target": "-101", "id": "77" if action == "edit" else None,
        "source": None, "retryable_wall_post": False,
        "media": case.media[:count],
    }})
    return op, child


@pytest.mark.parametrize("action", ["publish", "edit"])
@pytest.mark.parametrize("count", [1, 2, 4])
def test_current_attempt_prefix_precedes_prior_complete_staging(case, action, count):
    op, child = current_prefix(case, action, count)
    with case.store.connection() as db:
        selected = select(db, op, child)
    assert selected["source_attempt_id"] == child["id"]
    assert selected["source_plan_digest"] == child["plan_digest"]
    assert selected["target"] == "-101"
    assert selected["post_id"] == ("77" if action == "edit" else None)
    assert selected["media"] == case.media[:count]
    assert selected["asset_hashes"] == case.asset_hashes


@pytest.mark.parametrize("field,value", [
    ("media", []), ("target", "-202"), ("version", True),
    ("attempt", "other"), ("plan", "0" * 64),
])
def test_corrupt_matching_current_staging_cannot_fall_back_to_prior(case, field, value):
    op, child = current_prefix(case, "edit", 2)
    cp = json.loads(child["checkpoint"])
    cp["adapter"][field] = value
    child["checkpoint"] = canonical(cp)
    with case.store.connection() as db, pytest.raises(DomainError) as error:
        select(db, op, child)
    assert error.value.code == "vk_staged_photos_invalid"


def test_prepared_phase_requires_complete_prefix(case):
    op, child = current_prefix(case, "edit", 2)
    cp = json.loads(child["checkpoint"])
    cp["transition"] = "vk_prepared"
    child["checkpoint"] = canonical(cp)
    with case.store.connection() as db, pytest.raises(DomainError):
        select(db, op, child)


def test_dispatched_unknown_never_reuses_current_or_previous_staging(case):
    op, child = current_prefix(case, "edit", 2)
    child.update(dispatched=1, state="outcome_unknown")
    with case.store.connection() as db:
        assert select(db, op, child) is None


def test_group_owned_photo_without_rendition_proof_is_reused(case):
    op, child = current_prefix(case, "publish", 2)
    cp = json.loads(child["checkpoint"])
    cp["adapter"]["media"] = ["photo-101_1001", "photo-101_1002"]
    child["checkpoint"] = canonical(cp)
    with case.store.connection() as db:
        selected = select(db, op, child)
    assert selected["media"] == ["photo-101_1001", "photo-101_1002"]
    assert selected["source_attempt_id"] == child["id"]
    assert selected["target"] == "-101" and selected["post_id"] is None
    assert selected["asset_hashes"] == case.asset_hashes


def test_full_never_dispatched_publish_may_reuse_retryable_wall_post_staging(case):
    op, child = current_prefix(case, "publish", 4)
    cp = json.loads(child["checkpoint"])
    cp["transition"] = "vk_prepared"
    cp["adapter"]["retryable_wall_post"] = True
    child["checkpoint"] = canonical(cp)
    with case.store.connection() as db:
        selected = select(db, op, child)
        assert selected["media"] == case.media
        assert selected["source_attempt_id"] == child["id"]
        assert select(db, op, {**child, "dispatched": 1, "state": "outcome_unknown"}) is None