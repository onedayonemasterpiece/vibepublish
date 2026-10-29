"""Offline tracked Telegram media edits preserve original and sibling evidence."""
from dataclasses import replace
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from adapters.native import identity, verify_assets
from adapters.port import Capability, Observation, Prepared, ReadPage, RemoteItem
from social_operations.assets import import_image
from social_operations.domain import DomainError, OutcomeUnknown, canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


TARGET = "-1000000000101"
NATIVE = "731"
TABLES = ("publications", "revisions", "operations", "attempts", "request_keys", "events")


class OfflineMediaProvider:
    """Small native-port fixture; never contacts Telegram or VK."""
    def __init__(self, clock, *, unknown=False):
        self.clock = clock
        self.unknown = unknown
        self.remote = None
        self.effects = []
        self.reads = 0
        self.lose_edit_receipt = False

    async def prepare(self, request, hooks):
        verify_assets(request, allow_video=True)
        if request.existing and identity(request.existing) != identity(self.remote):
            raise DomainError("remote_revision_conflict")
        return Prepared(request, Capability("supported", "offline managed-media fixture"))

    async def execute(self, prepared, hooks):
        request = prepared.request
        await hooks.before_effect(request.attempt_id, request.plan_digest)
        self.effects.append(request)
        if self.unknown:
            raise OutcomeUnknown("fixture_vk_receipt_lost")
        content = json.loads(request.content_json)
        media = tuple(("document:" if a.role == "video" else "photo:") + a.sha256[:12]
                      for a in request.assets)
        if not media and request.existing:
            media = request.existing.provider_media
        item = RemoteItem(
            request.existing.native_id if request.existing else NATIVE,
            "published", content["text"], "", timestamp(self.clock()),
            native_target=request.native_target,
            media_hashes=tuple(a.sha256 for a in request.assets),
            provider_media=media,
            media_check="provider_binding" if media else "not_applicable",
            entities_json=canonical(content.get("entities", [])),
        )
        self.remote = replace(item, fingerprint=identity(item))
        if self.lose_edit_receipt and request.action == "edit":
            raise OutcomeUnknown("fixture_edit_receipt_lost")
        return Observation("edited" if request.action == "edit" else "published", (self.remote,))

    async def read(self, request, hooks):
        self.reads += 1
        return ReadPage((self.remote,))


@pytest.fixture
def env(tmp_path):
    now = [1800000000.0]
    store = Store(tmp_path / "managed.sqlite", clock=lambda: now[0])
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    bindings = {}
    for provider, account, target in (
        ("telegram", "mtproto_user", TARGET), ("vk", "vk_user", "-101")
    ):
        store.add_connection(actor, provider, provider, account_type=account)
        bindings[provider] = store.bind(
            actor, actor.principal_id, provider, provider, target,
            rights=("publish", "edit", "cancel"))
    tg = OfflineMediaProvider(store.clock)
    vk = OfflineMediaProvider(store.clock, unknown=True)
    app = Application(store)
    worker = Worker(store, {"telegram": tg, "vk": vk})
    assets = []
    for color in ("red", "blue"):
        output = io.BytesIO()
        Image.new("RGB", (8, 8), color).save(output, format="PNG")
        assets.append(import_image(store, actor, output.getvalue(), "image/png"))
    return SimpleNamespace(store=store, actor=actor, app=app, worker=worker, tg=tg,
                           vk=vk, now=now, bindings=bindings, assets=assets)


def media(ref, role="image"):
    return {"source": {"kind": "asset", "id": ref}, "role": role}


async def call(env, method, args, actor=None):
    return await env.app.call(actor or env.actor, "vibepublish_" + method, args)


def receipt(env, accepted):
    return env.store.receipt(env.actor, accepted["operation_id"])


def ledger(env):
    with env.store.connection() as db:
        return {table: [tuple(row) for row in db.execute("SELECT * FROM " + table + " ORDER BY rowid")]
                for table in TABLES}


def old_evidence(env, original):
    with env.store.connection() as db:
        return {
            "operation": dict(db.execute("SELECT * FROM operations WHERE id=?",
                                        (original["operation_id"],)).fetchone()),
            "attempts": [dict(row) for row in db.execute(
                "SELECT * FROM attempts WHERE operation_id=? ORDER BY id", (original["operation_id"],))],
            "revision": tuple(db.execute(
                "SELECT * FROM revisions WHERE publication_id=? AND revision=1",
                (original["resource_id"],)).fetchone()),
            "events": [tuple(row) for row in db.execute(
                "SELECT * FROM events WHERE operation_id=? ORDER BY seq", (original["operation_id"],))],
        }


async def fresh_read(env, item_ref):
    read = await call(env, "read", {"query": {"kind": "item", "item_ref": item_ref}})
    assert "error" not in read, read
    assert await env.worker.run_once()
    result = receipt(env, read)
    assert result["state"] == "verified", result
    return result["items"][0]["ref"], read


async def published(env, *, siblings=True, role="image", asset_ref=None, settle_vk=False):
    original = await call(env, "publish", {
        "to": ["telegram", "vk"] if siblings else ["telegram"],
        "content": {"text": "Original caption"},
        "media": [media(asset_ref or env.assets[0], role)],
        "request_key": "original",
    })
    assert "error" not in original, original
    assert await env.worker.run_once()
    if settle_vk and siblings:
        # The original VK command now retries automatically until its fixed horizon.
        # Finish it before editing the same managed publication; never resend it.
        env.now[0] += 901
        assert await env.worker.run_once()
        assert receipt(env, original)["operation_complete"]
        env.tg.remote = replace(env.tg.remote, observed_at=timestamp(env.store.clock()))
    result = receipt(env, original)
    tg = next(item for item in result["deliveries"] if item["provider"] == "telegram")
    assert tg["state"] == "verified", result
    fresh, read = await fresh_read(env, tg["item_ref"])
    return original, fresh, read, tg["item_ref"]


def update_args(env, reference, *, key="replace-media", role="image", asset_ref=None):
    return {"item_ref": reference, "change": {"kind": "edit",
            "content": {"text": "Revised caption"},
            "media": [media(asset_ref or env.assets[1], role)]}, "request_key": key}


@pytest.mark.asyncio
async def test_scoped_edit_keeps_publication_native_identity_and_unknown_sibling(env):
    from social_operations.managed_item_edits import latest_attempts
    original, fresh, _, _ = await published(env, settle_vk=True)
    before = old_evidence(env, original)
    original_receipt = receipt(env, original)
    args = update_args(env, fresh)
    accepted = await call(env, "publication_update", args)
    assert "error" not in accepted, accepted
    assert accepted["resource_id"] == original["resource_id"] and accepted["revision"] == 2
    assert accepted["operation_id"] != original["operation_id"]
    with env.store.connection() as db:
        new = [dict(row) for row in db.execute(
            "SELECT * FROM attempts WHERE operation_id=?", (accepted["operation_id"],))]
        assert len(new) == 1 and new[0]["provider"] == "telegram"
        assert json.loads(new[0]["plan"])["existing"]["native_id"] == NATIVE
        op = db.execute("SELECT * FROM operations WHERE id=?", (accepted["operation_id"],)).fetchone()
        projection = {row["provider"]: row for row in latest_attempts(db, op)}
        assert set(projection) == {"telegram", "vk"}
        assert projection["telegram"]["target_revision"] == 2
        assert projection["telegram"]["target_operation_id"] == accepted["operation_id"]
        assert projection["vk"]["target_revision"] == 1
        assert projection["vk"]["target_operation_id"] == original["operation_id"]
        assert projection["vk"]["state"] == "blocked"
    assert old_evidence(env, original) == before
    assert await env.worker.run_once()
    done = receipt(env, accepted)
    assert done["state"] == "partial", done
    delivery = {item["provider"]: item for item in done["deliveries"]}
    assert delivery["telegram"]["state"] == "verified" and delivery["telegram"]["observed"] == "edited"
    assert delivery["vk"]["state"] == "blocked"
    assert env.tg.remote.native_id == NATIVE
    assert [request.action for request in env.tg.effects] == ["publish", "edit"]
    assert len(env.vk.effects) == 1
    assert env.tg.effects[-1].assets[0].ref == env.assets[1]
    assert old_evidence(env, original) == before
    observed_original = receipt(env, original)
    # Status calls mint a fresh cursor; all durable receipt facts must be stable.
    observed_original["progress"]["cursor"] = original_receipt["progress"]["cursor"]
    assert observed_original == original_receipt
    after = ledger(env)
    replay = await call(env, "publication_update", args)
    assert replay["operation_id"] == accepted["operation_id"]
    assert ledger(env) == after and not await env.worker.run_once()
    conflict = await call(env, "publication_update", {
        **args, "change": {**args["change"], "content": {"text": "Different intent"}}})
    assert conflict["error"]["code"] == "idempotency_conflict"
    assert ledger(env) == after and len(env.vk.effects) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [
    "stale", "receipt_only", "wrong_binding", "wrong_binding_epoch",
    "wrong_actor_epoch", "wrong_native", "wrong_connection", "wrong_target",
    "tracked_unverified", "missing_edit_right",
])
async def test_managed_edit_rejects_stale_unbound_or_unverified_evidence(env, tamper):
    original, fresh, reading, initial_ref = await published(env)
    reference = initial_ref if tamper == "receipt_only" else fresh
    if tamper == "stale":
        env.now[0] += 301
    elif tamper == "wrong_binding":
        other = env.store.bind(env.actor, "owner", "other", "telegram", "-1000000000202",
                               rights=("publish", "edit"))
        with env.store.tx() as db:
            db.execute("UPDATE item_refs SET binding_id=? WHERE id=?", (other, fresh))
    elif tamper == "wrong_connection":
        env.store.add_connection(env.actor, "other_tg", "telegram", account_type="mtproto_user")
        with env.store.tx() as db:
            db.execute("UPDATE destinations SET connection_id='other_tg' WHERE native_id=?", (TARGET,))
    elif tamper == "wrong_target":
        with env.store.tx() as db:
            db.execute("UPDATE destinations SET native_id='-1000000000303' WHERE native_id=?", (TARGET,))
    elif tamper == "missing_edit_right":
        with env.store.tx() as db:
            db.execute("UPDATE bindings SET rights='[\"publish\"]' WHERE id=?", (env.bindings["telegram"],))
    elif tamper not in {"receipt_only", "stale"}:
        statements = {
            "wrong_binding_epoch": ("UPDATE item_refs SET binding_epoch=binding_epoch+1 WHERE id=?", fresh),
            "wrong_actor_epoch": ("UPDATE operations SET actor_epoch=actor_epoch+1 WHERE id=?", reading["operation_id"]),
            "wrong_native": ("UPDATE item_refs SET native_id='999' WHERE id=?", fresh),
            "tracked_unverified": ("UPDATE attempts SET state='outcome_unknown',observed='unknown' WHERE operation_id=? AND provider='telegram'", original["operation_id"]),
        }
        statement, value = statements[tamper]
        with env.store.tx() as db:
            db.execute(statement, (value,))
    before = ledger(env)
    result = await call(env, "publication_update", update_args(env, reference))
    assert "error" in result, (tamper, result)
    assert ledger(env) == before
    assert len(env.tg.effects) == len(env.vk.effects) == 1


@pytest.mark.asyncio
async def test_other_principal_cannot_use_owner_reference(env):
    _, fresh, _, _ = await published(env)
    other = env.store.authenticate(env.store.create_principal("tenant", "other", owner=True))
    env.store.bind(env.actor, other.principal_id, "telegram", "telegram", TARGET,
                   rights=("publish", "edit"))
    before = ledger(env)
    result = await call(env, "publication_update", update_args(env, fresh), actor=other)
    assert "error" in result
    assert ledger(env) == before and len(env.tg.effects) == 1


@pytest.mark.asyncio
async def test_unmanaged_external_media_gate_stays_closed(env):
    item = RemoteItem("992", "published", "External caption", "", timestamp(env.now[0]),
                      native_target=TARGET, provider_media=("photo:external",),
                      media_check="provider_binding")
    env.tg.remote = replace(item, fingerprint=identity(item))
    fresh, _ = await fresh_read(env, "https://t.me/c/101/992")
    before = ledger(env)
    result = await call(env, "publication_update", update_args(env, fresh))
    assert result["error"]["code"] == "external_media_replace_needs_review"
    assert ledger(env) == before and not env.tg.effects and not env.vk.effects


@pytest.mark.asyncio
async def test_ambiguous_managed_publications_never_choose_a_match(env):
    original, fresh, _, _ = await published(env)
    with env.store.tx() as db:
        pub = dict(db.execute("SELECT * FROM publications WHERE id=?", (original["resource_id"],)).fetchone())
        revision = dict(db.execute("SELECT * FROM revisions WHERE publication_id=?", (pub["id"],)).fetchone())
        op = dict(db.execute("SELECT * FROM operations WHERE id=?", (original["operation_id"],)).fetchone())
        child = dict(db.execute("SELECT * FROM attempts WHERE operation_id=? AND provider='telegram'", (op["id"],)).fetchone())
        pub["id"] = "pub_ambiguous_fixture"
        revision["publication_id"] = pub["id"]
        op.update(id="op_ambiguous_fixture", publication_id=pub["id"])
        child.update(id="attempt_ambiguous_fixture", operation_id=op["id"])
        for table, row in (("publications", pub), ("revisions", revision), ("operations", op), ("attempts", child)):
            db.execute("INSERT INTO " + table + " (" + ",".join(row) + ") VALUES (" +
                       ",".join("?" for _ in row) + ")", tuple(row.values()))
    before = ledger(env)
    result = await call(env, "publication_update", update_args(env, fresh))
    assert result["error"]["code"] == "managed_media_target_ambiguous"
    assert ledger(env) == before and len(env.tg.effects) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 2])
async def test_replacement_requires_exactly_one_asset(env, count):
    _, fresh, _, _ = await published(env)
    args = update_args(env, fresh)
    args["change"]["media"] = args["change"]["media"] * count
    before = ledger(env)
    result = await call(env, "publication_update", args)
    assert "error" in result
    assert ledger(env) == before and len(env.tg.effects) == 1


@pytest.mark.asyncio
async def test_changed_native_snapshot_blocks_before_edit_effect(env):
    original, fresh, _, _ = await published(env, settle_vk=True)
    before = old_evidence(env, original)
    accepted = await call(env, "publication_update", update_args(env, fresh))
    assert "error" not in accepted, accepted
    env.tg.remote = replace(env.tg.remote, text="Changed externally")
    env.tg.remote = replace(env.tg.remote, fingerprint=identity(env.tg.remote))
    assert await env.worker.run_once()
    result = receipt(env, accepted)
    tg = next(item for item in result["deliveries"] if item["provider"] == "telegram")
    assert tg["state"] == "blocked", result
    assert len(env.tg.effects) == len(env.vk.effects) == 1
    assert old_evidence(env, original) == before


@pytest.mark.asyncio
async def test_unknown_edit_replay_is_observation_only(env):
    original, fresh, _, _ = await published(env, settle_vk=True)
    args = update_args(env, fresh)
    accepted = await call(env, "publication_update", args)
    assert "error" not in accepted, accepted
    env.tg.lose_edit_receipt = True
    assert await env.worker.run_once()
    terminal = ledger(env)
    replay = await call(env, "publication_update", args)
    assert replay["operation_id"] == accepted["operation_id"]
    assert any(item["state"] == "running" for item in replay["deliveries"])
    assert ledger(env) == terminal and not await env.worker.run_once()
    assert len(env.tg.effects) == 2 and len(env.vk.effects) == 1
    assert env.tg.remote.native_id == NATIVE


@pytest.mark.asyncio
async def test_second_managed_revision_keeps_original_vk_projection(env):
    from social_operations.managed_item_edits import latest_attempts
    original, fresh, _, _ = await published(env, settle_vk=True)
    before = old_evidence(env, original)
    first = await call(env, "publication_update", update_args(env, fresh))
    assert "error" not in first, first
    await env.worker.run_once()
    target = next(item for item in receipt(env, first)["deliveries"] if item["provider"] == "telegram")
    fresh, _ = await fresh_read(env, target["item_ref"])
    second = await call(env, "publication_update",
                        update_args(env, fresh, key="second-replacement", asset_ref=env.assets[0]))
    assert "error" not in second, second
    assert second["resource_id"] == original["resource_id"] and second["revision"] == 3
    await env.worker.run_once()
    with env.store.connection() as db:
        op = db.execute("SELECT * FROM operations WHERE id=?", (second["operation_id"],)).fetchone()
        projection = {row["provider"]: row for row in latest_attempts(db, op)}
        assert projection["telegram"]["target_revision"] == 3
        assert projection["vk"]["target_revision"] == 1
        assert projection["vk"]["target_operation_id"] == original["operation_id"]
        assert db.execute("SELECT count(*) FROM attempts WHERE operation_id=?", (second["operation_id"],)).fetchone()[0] == 1
    assert old_evidence(env, original) == before
    assert len(env.tg.effects) == 3 and len(env.vk.effects) == 1
    assert env.tg.remote.native_id == NATIVE


@pytest.mark.asyncio
async def test_managed_replacement_requires_request_key_before_revision_or_effect(env):
    _, fresh, _, _ = await published(env)
    args = update_args(env, fresh)
    args.pop("request_key")
    before = ledger(env)
    result = await call(env, "publication_update", args)
    assert "error" in result, result
    assert ledger(env) == before
    assert len(env.tg.effects) == len(env.vk.effects) == 1
    assert not await env.worker.run_once()


@pytest.mark.asyncio
async def test_partial_vk_sibling_keeps_opaque_proof_and_partial_aggregate(env):
    from social_operations.managed_item_edits import latest_attempts
    original, fresh, _, _ = await published(env, settle_vk=True)
    # Preservation fixture only. This opaque value is not allocation authority
    # and deliberately does not exercise or claim to validate the VK resolver.
    checkpoint = canonical({"adapter": {"allocation_proof": {
        "opaque": "retained-allocation-fixture"}}})
    result = canonical({"retry_safe": False, "media_check": "not_applicable",
                        "missing_checks": ["fixture_retained_allocation_unresolved"]})
    with env.store.tx() as db:
        db.execute(
            "UPDATE attempts SET state='partial',observed='not_attempted',"
            "stage='finished',result=?,checkpoint=? WHERE operation_id=? AND provider='vk'",
            (result, checkpoint, original["operation_id"]))
        db.execute("UPDATE operations SET state='partial',error=NULL WHERE id=?",
                   (original["operation_id"],))
    before = old_evidence(env, original)
    accepted = await call(env, "publication_update", update_args(env, fresh))
    assert "error" not in accepted, accepted
    assert accepted["resource_id"] == original["resource_id"] and accepted["revision"] == 2
    assert await env.worker.run_once()
    done = receipt(env, accepted)
    assert done["state"] == "partial", done
    delivery = {item["provider"]: item for item in done["deliveries"]}
    assert delivery["telegram"]["state"] == "verified"
    assert delivery["telegram"]["observed"] == "edited"
    assert delivery["vk"]["state"] == "partial"
    assert delivery["vk"]["observed"] == "not_attempted"
    assert delivery["vk"]["retry_safe"] is False
    with env.store.connection() as db:
        op = db.execute("SELECT * FROM operations WHERE id=?",
                        (accepted["operation_id"],)).fetchone()
        projection = {row["provider"]: row for row in latest_attempts(db, op)}
        sibling = projection["vk"]
        assert sibling["target_revision"] == 1
        assert sibling["target_operation_id"] == original["operation_id"]
        assert sibling["result"] == result and sibling["checkpoint"] == checkpoint
        new = list(db.execute("SELECT provider FROM attempts WHERE operation_id=?",
                              (accepted["operation_id"],)))
        assert [row["provider"] for row in new] == ["telegram"]
    assert old_evidence(env, original) == before
    assert len(env.tg.effects) == 2 and len(env.vk.effects) == 1
    assert env.tg.remote.native_id == NATIVE


@pytest.mark.asyncio
async def test_successful_untouched_vk_is_historical_verified_but_outdated(env):
    env.vk.unknown = False
    original, fresh, _, _ = await published(env)
    before = old_evidence(env, original)
    original_receipt = receipt(env, original)
    assert original_receipt["state"] == "verified", original_receipt
    old_vk = next(item for item in original_receipt["deliveries"] if item["provider"] == "vk")
    accepted = await call(env, "publication_update", update_args(env, fresh))
    assert "error" not in accepted, accepted
    assert accepted["resource_id"] == original["resource_id"] and accepted["revision"] == 2
    assert await env.worker.run_once()
    done = receipt(env, accepted)
    assert done["state"] == "partial", done
    delivery = {item["provider"]: item for item in done["deliveries"]}
    tg, vk = delivery["telegram"], delivery["vk"]
    assert tg["state"] == "verified" and tg["observed"] == "edited"
    assert tg["applied_revision"] == 2 and tg["desired_revision"] == 2
    assert tg["sync_status"] == "current"
    assert vk["state"] == "verified" and vk["observed"] == "published"
    assert vk["applied_revision"] == 1 and vk["desired_revision"] == 2
    assert vk["sync_status"] == "outdated"
    for field in ("attempt_id", "item_ref", "observed_at", "media_check"):
        assert vk[field] == old_vk[field]
    with env.store.connection() as db:
        new = list(db.execute("SELECT provider FROM attempts WHERE operation_id=?",
                              (accepted["operation_id"],)))
        assert [row["provider"] for row in new] == ["telegram"]
    assert old_evidence(env, original) == before
    observed_original = receipt(env, original)
    observed_original["progress"]["cursor"] = original_receipt["progress"]["cursor"]
    assert observed_original == original_receipt
    assert len(env.tg.effects) == 2 and len(env.vk.effects) == 1


from tests.providers.test_max_content_video import video_bytes


@pytest.mark.asyncio
async def test_owned_video_replacement_passes_normal_integrity_and_keeps_message(env, video_bytes):
    from social_operations.video_assets import import_video
    original_asset = import_video(env.store, env.actor, video_bytes, "video/mp4")
    original, fresh, _, _ = await published(env, siblings=False, role="video", asset_ref=original_asset)
    args = update_args(env, fresh, role="video", asset_ref=original_asset)
    accepted = await call(env, "publication_update", args)
    assert "error" not in accepted, accepted
    assert accepted["resource_id"] == original["resource_id"] and accepted["revision"] == 2
    await env.worker.run_once()
    result = receipt(env, accepted)
    assert result["state"] == "verified", result
    assert env.tg.remote.native_id == NATIVE
    assert env.tg.effects[-1].assets[0].role == "video"
    assert env.tg.effects[-1].assets[0].sha256
    assert len(env.tg.effects) == 2 and not env.vk.effects

@pytest.mark.asyncio
async def test_explicit_destination_edit_keeps_one_publication_and_unknown_sibling(env):
    original, _, _, _ = await published(env, settle_vk=True)
    before = old_evidence(env, original)
    args = {"publication_id": original["resource_id"], "expected_revision": 1,
            "change": {"kind": "edit", "destinations": ["telegram"],
                       "content": {"text": "Scoped desired caption"}},
            "request_key": "generic-scoped-edit"}
    accepted = await call(env, "publication_update", args)
    assert "error" not in accepted, accepted
    assert accepted["resource_id"] == original["resource_id"] and accepted["revision"] == 2
    assert await env.worker.run_once()
    done = receipt(env, accepted)
    deliveries = {item["provider"]: item for item in done["deliveries"]}
    assert deliveries["telegram"]["sync_status"] == "current"
    assert deliveries["telegram"]["applied_revision"] == 2
    assert deliveries["vk"]["state"] == "blocked"
    assert deliveries["vk"]["sync_status"] == "unknown"
    assert deliveries["vk"]["applied_revision"] is None
    assert done["state"] == "partial"
    assert old_evidence(env, original) == before
    after = ledger(env)
    assert (await call(env, "publication_update", args))["operation_id"] == accepted["operation_id"]
    assert ledger(env) == after
    assert len(env.tg.effects) == 2 and len(env.vk.effects) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [[], ["vk"], ["telegram", "vk"], ["missing"], ["telegram", "telegram"]])
async def test_scoped_edit_never_selects_unknown_or_invalid_targets(env, selection):
    original, _, _, _ = await published(env)
    before = ledger(env)
    result = await call(env, "publication_update", {
        "publication_id": original["resource_id"], "expected_revision": 1,
        "change": {"kind": "edit", "destinations": selection, "content": {"text": "Rejected"}},
        "request_key": "invalid-selection"})
    assert "error" in result, result
    assert ledger(env) == before
    assert len(env.tg.effects) == len(env.vk.effects) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["missing_key", "item_ref", "unrelated", "rights", "stale_revision"])
async def test_explicit_target_edit_requires_exact_scope_key_and_rights(env, tamper):
    original, fresh, _, _ = await published(env)
    args = {"publication_id": original["resource_id"], "expected_revision": 1,
            "change": {"kind": "edit", "destinations": ["telegram"], "content": {"text": "Rejected"}},
            "request_key": "exact-target"}
    if tamper == "missing_key":
        args.pop("request_key")
    elif tamper == "item_ref":
        args.pop("publication_id")
        args.pop("expected_revision")
        args["item_ref"] = fresh
    elif tamper == "unrelated":
        env.store.bind(env.actor, "owner", "other", "telegram", "-1000000000202", rights=("publish", "edit"))
        args["change"]["destinations"] = ["other"]
    elif tamper == "rights":
        with env.store.tx() as db:
            db.execute("UPDATE bindings SET rights='[\"publish\"]' WHERE id=?", (env.bindings["telegram"],))
    else:
        args["expected_revision"] = 99
    before = ledger(env)
    result = await call(env, "publication_update", args)
    assert "error" in result, result
    assert ledger(env) == before and len(env.tg.effects) == 1


@pytest.mark.asyncio
async def test_all_target_edit_after_scoped_edit_uses_latest_heads_and_converges(env):
    env.vk.unknown = False
    original, _, _, _ = await published(env)
    scoped = await call(env, "publication_update", {
        "publication_id": original["resource_id"], "expected_revision": 1,
        "change": {"kind": "edit", "destinations": ["telegram"], "content": {"text": "Scoped"}},
        "request_key": "scope-first"})
    assert "error" not in scoped, scoped
    await env.worker.run_once()
    partial = receipt(env, scoped)
    assert partial["state"] == "partial"
    assert {d["provider"]: d["sync_status"] for d in partial["deliveries"]} == {
        "telegram": "current", "vk": "outdated"}
    final = await call(env, "publication_update", {
        "publication_id": original["resource_id"], "expected_revision": 2,
        "change": {"kind": "edit", "content": {"text": "Common final caption"}},
        "request_key": "all-targets-current"})
    assert "error" not in final, final
    await env.worker.run_once()
    done = receipt(env, final)
    assert done["state"] == "verified", done
    assert all(d["sync_status"] == "current" and d["applied_revision"] == 3
               and d["desired_revision"] == 3 for d in done["deliveries"])
    assert len(env.tg.effects) == 3 and len(env.vk.effects) == 2


@pytest.mark.asyncio
async def test_scoped_edit_after_refusal_without_send_edits_last_applied_item(env):
    env.vk.unknown = False
    original, _, _, _ = await published(env)
    prepare = env.tg.prepare

    async def refuse(request, hooks):
        raise DomainError("telegram_album_edit_needs_review")

    env.tg.prepare = refuse
    refused = await call(env, "publication_update", {
        "publication_id": original["resource_id"], "expected_revision": 1,
        "change": {"kind": "edit", "destinations": ["telegram"], "content": {"text": "Tickets"}},
        "request_key": "refused-first"})
    assert "error" not in refused, refused
    await env.worker.run_once()
    assert len(env.tg.effects) == 1  # The refusal sent nothing.
    env.tg.prepare = prepare
    again = await call(env, "publication_update", {
        "publication_id": original["resource_id"], "expected_revision": 2,
        "change": {"kind": "edit", "destinations": ["telegram"], "content": {"text": "Tickets"}},
        "request_key": "after-fix"})
    assert "error" not in again, again
    await env.worker.run_once()
    assert [request.action for request in env.tg.effects] == ["publish", "edit"]
    assert env.tg.effects[-1].existing.native_id == NATIVE
    assert env.tg.remote.text == "Tickets" and len(env.vk.effects) == 1


@pytest.mark.asyncio
async def test_publication_edit_after_scheduled_item_went_out_points_to_item_ref(env):
    execute = env.tg.execute

    async def queued(prepared, hooks):
        observation = await execute(prepared, hooks)
        env.tg.remote = replace(env.tg.remote, namespace="scheduled",
                                scheduled_at=prepared.request.scheduled_at)
        return Observation("provider_scheduled", (env.tg.remote,))

    env.tg.execute = queued
    at = timestamp(env.now[0] + 3600)
    original = await call(env, "publish", {
        "to": ["telegram"], "content": {"text": "Original caption"},
        "media": [media(env.assets[0])], "delivery": {"kind": "at", "at": at},
        "request_key": "scheduled"})
    assert "error" not in original, original
    assert await env.worker.run_once()
    env.now[0] += 7200  # The native queue has published the post.
    before = ledger(env)
    result = await call(env, "publication_update", {
        "publication_id": original["resource_id"], "expected_revision": 1,
        "change": {"kind": "edit", "destinations": ["telegram"], "content": {"text": "Tickets"}},
        "request_key": "after-publication"})
    assert result["error"]["code"] == "native_item_published", result
    assert result["next_action"] == "refresh"
    assert ledger(env) == before and len(env.tg.effects) == 1
