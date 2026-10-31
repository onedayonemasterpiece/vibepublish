"""Three-day native command closure, short failed retention, and imagegen GC."""
import io
import json

import pytest
from PIL import Image

from adapters.port import RemoteItem
from social_operations.assets import import_image, retired_asset_rows, stale_unsent_attempts
from social_operations.domain import new_id, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


def pending(tmp_path):
    clock = [1_800_000_000.0]
    store = Store(tmp_path / "gc.sqlite", clock=lambda: clock[0])
    actor = store.authenticate(store.create_principal("t", "owner", owner=True))
    store.add_connection(actor, "max", "max", account_type="fake")
    store.bind(actor, actor.principal_id, "max", "max", "fixture-target",
               rights=("publish", "edit", "reschedule", "cancel"))
    stream = io.BytesIO()
    Image.new("RGB", (8, 10), "red").save(stream, "PNG")
    asset = import_image(store, actor, stream.getvalue(), "image/png")
    return store, actor, Application(store), Worker(store), clock, asset


@pytest.mark.asyncio
@pytest.mark.parametrize("scheduled", [False, True])
async def test_three_day_unsubmitted_operations_close_without_max_browser(tmp_path, scheduled):
    store, actor, app, worker, clock, asset = pending(tmp_path)
    delivery = {"kind": "at", "at": timestamp(clock[0] + 3600)} if scheduled else {"kind": "now"}
    admitted = await app.call(actor, "vibepublish_publish", {
        "to": ["max"], "content": {"text": "Time-limited digest"},
        "media": [{"source": {"kind": "asset", "id": asset}}],
        "delivery": delivery, "request_key": "digest"})
    assert "error" not in admitted, admitted
    clock[0] += (3600 if scheduled else 0) + 3 * 86400 + 1
    with store.connection() as db:
        candidates = stale_unsent_attempts(db, clock[0])
    assert len(candidates) == 1 and candidates[0]["provider"] == "max"
    assert candidates[0]["operation_id"] == admitted["operation_id"]
    # Adapter is intentionally absent; no native command can run on this test.
    assert not await worker.run_once()
    done = store.receipt(actor, admitted["operation_id"])
    assert done["state"] == "cancelled" and done["operation_complete"]
    with store.connection() as db:
        child = db.execute("SELECT dispatched,state,observed,result FROM attempts WHERE operation_id=?",
                           (admitted["operation_id"],)).fetchone()
        assert child["dispatched"] == 0 and child["state"] == "cancelled"
        assert child["observed"] == "not_attempted"
        assert json.loads(child["result"])["missing_checks"] == ["stale_not_dispatched"]
    replay = await app.call(actor, "vibepublish_publish", {
        "to": ["max"], "content": {"text": "Time-limited digest"},
        "media": [{"source": {"kind": "asset", "id": asset}}],
        "delivery": delivery, "request_key": "digest"})
    assert replay["operation_id"] == admitted["operation_id"]
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_future_native_schedule_not_expired_from_creation_time_alone(tmp_path):
    store, actor, app, worker, clock, asset = pending(tmp_path)
    admitted = await app.call(actor, "vibepublish_publish", {
        "to": ["max"], "content": {"text": "Future event"},
        "media": [{"source": {"kind": "asset", "id": asset}}],
        "delivery": {"kind": "at", "at": timestamp(clock[0] + 5 * 86400)}})
    assert "error" not in admitted, admitted
    clock[0] += 4 * 86400
    with store.tx() as db:
        assert stale_unsent_attempts(db, clock[0]) == []
        worker.expire_stale_unsent(db, clock[0])
        reasons = {row["id"]: row["reason"] for row in retired_asset_rows(db, clock[0])}
    assert reasons[asset] == "pending_action"
    assert not store.receipt(actor, admitted["operation_id"])["operation_complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason", [
    ("blocked", "recent_failure"), ("outcome_unknown", "recent_unknown")])
@pytest.mark.parametrize('future_schedule', [False, True])
async def test_failed_and_unknown_retain_three_days_but_not_forever(tmp_path, status, reason, future_schedule):
    store, actor, app, worker, clock, asset = pending(tmp_path)
    accepted = await app.call(actor, "vibepublish_publish", {
        "to": ["max"], "content": {"text": "Unsent"},
        "media": [{"source": {"kind": "asset", "id": asset}}],
        **({"delivery": {"kind": "at", "at": timestamp(clock[0] + 30 * 86400)}} if future_schedule else {})})
    assert "error" not in accepted, accepted
    with store.tx() as db:
        db.execute("UPDATE attempts SET state=?,dispatched=? WHERE operation_id=?",
                   (status, 1 if status == "outcome_unknown" else 0, accepted["operation_id"]))
        db.execute("UPDATE operations SET state=?,work_state='done',complete=1,worker_seen=? WHERE id=?",
                   (status, clock[0], accepted["operation_id"]))
    clock[0] += 2 * 86400
    with store.connection() as db:
        assert {r["id"]: r["reason"] for r in retired_asset_rows(db, clock[0])}[asset] == reason
    clock[0] += 86401
    with store.connection() as db:
        assert {r["id"]: r["reason"] for r in retired_asset_rows(db, clock[0])}[asset] == "reclaim"
    assert not await worker.run_once()
    with store.connection() as db:
        assert db.execute("SELECT 1 FROM assets WHERE id=?", (asset,)).fetchone() is None
        assert db.execute("SELECT state FROM operations WHERE id=?", (accepted["operation_id"],)).fetchone()[0] == status



@pytest.mark.asyncio
async def test_preview_media_survives_until_approval_or_three_day_orphan(tmp_path):
    """A preview did not send a photo; worker must not delete the future approval input."""
    from adapters.fake import FakeProvider
    store, actor, app, _, clock, asset = pending(tmp_path)
    worker = Worker(store, {"max": FakeProvider(tmp_path / "fake-provider.sqlite", "max", clock=store.clock)})
    preview = await app.call(actor, 'vibepublish_publish', {
        'to': ['max'], 'mode': 'preview',
        'content': {'text': 'Review this image'},
        'media': [{'source': {'kind': 'asset', 'id': asset}}]})
    assert 'error' not in preview, preview
    assert await worker.run_once()
    assert store.receipt(actor, preview['operation_id'])['state'] == 'needs_approval'
    clock[0] += 61
    assert not await worker.run_once()
    with store.connection() as db:
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (asset,)).fetchone()
    clock[0] += 3 * 86400
    assert not await worker.run_once()
    with store.connection() as db:
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (asset,)).fetchone() is None
        assert db.execute('SELECT state FROM operations WHERE id=?',
                          (preview['operation_id'],)).fetchone()[0] == 'needs_approval'


@pytest.mark.asyncio
async def test_maintenance_script_dry_run_then_apply_only_on_synthetic_db(tmp_path):
    """The operator script uses the same classifier as worker, without live writes."""
    from pathlib import Path
    import subprocess
    import sys
    import time

    store, actor, app, worker, clock, asset = pending(tmp_path)
    clock[0] = time.time() - 16 * 86400
    admitted = await app.call(actor, "vibepublish_publish", {
        "to": ["max"], "content": {"text": "Old undelivered digest"},
        "media": [{"source": {"kind": "asset", "id": asset}}]})
    assert "error" not in admitted, admitted
    script = Path(__file__).resolve().parents[2] / "scripts/inspect/vk_asset_retention.py"
    def command(*options):
        return json.loads(subprocess.run(
            [sys.executable, str(script), "--db", str(store.path), *options],
            check=True, capture_output=True, text=True, timeout=45,
        ).stdout)
    before = command()
    assert before["mode"] == "dry_run"
    assert before["would_close_operations"] == 1
    assert before["by_reason"]["reclaim"]["rows"] >= 1
    with store.connection() as db:
        assert db.execute("SELECT 1 FROM assets WHERE id=?", (asset,)).fetchone()
        assert db.execute("SELECT state FROM operations WHERE id=?",
                          (admitted["operation_id"],)).fetchone()[0] == "accepted"
    result = command("--apply")  # only fixture SQLite in pytest tmp_path
    assert result["mode"] == "apply"
    assert result["sqlite_file_bytes_after"] <= result["sqlite_file_bytes_before"]
    with store.connection() as db:
        assert db.execute("SELECT 1 FROM assets WHERE id=?", (asset,)).fetchone() is None
        assert db.execute("SELECT state,complete FROM operations WHERE id=?",
                          (admitted["operation_id"],)).fetchone()[:] == ("cancelled", 1)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.asyncio
async def test_imagegen_14_day_cleanup_preserves_visual_job_and_media_facts(tmp_path):
    from adapters.fake import FakeProvider
    from adapters.port import RemoteItem
    from adapters.imagegen import FakeImagegen
    from social_operations.domain import canonical

    store, actor, app, _unused, clock, asset = pending(tmp_path)
    # Existing fake MAX target has valid publication rights; standalone visual
    # generation needs no provider effect, only its original job and output.
    provider = FakeProvider(tmp_path / "provider.sqlite", "max", clock=store.clock)
    worker = Worker(store, {"max": provider}, imagegen=FakeImagegen(tmp_path / "imagegen"))
    command = await app.call(actor, "vibepublish_visual", {
        "command": {"kind": "generate", "brief": "Historic building",
                    "candidates": 1, "selection": "human"},
        "request_key": "generate"})
    assert "error" not in command, command
    assert await worker.run_once()
    with store.tx() as db:
        candidate = db.execute("SELECT id,asset_ref,art_ref,job_id FROM visual_candidates LIMIT 1").fetchone()
        assert candidate is not None
        candidate = dict(candidate)
        db.execute("INSERT INTO visual_feedback VALUES(?,?,?,?,?,?,?)",
                   (new_id("feedback"), candidate["job_id"], candidate["id"],
                    "good", "fixture", clock[0], 0))
        binding = db.execute("SELECT destination_id FROM bindings WHERE alias='max'").fetchone()[0]
        worker.save_fact(db, binding, RemoteItem(
            "fake-post", "published", "Media bank photo description",
            "test", timestamp(clock[0]), native_target="fixture-target"))
        before = tuple(db.execute("SELECT snapshot,text FROM facts").fetchone())
        fact_search = db.execute("SELECT COUNT(*) FROM fact_search").fetchone()[0]
        job = db.execute("SELECT spec FROM visual_jobs").fetchone()[0]
    clock[0] += 15 * 86400
    assert not await worker.run_once()
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM visual_candidates").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM visual_asset_origins").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM visual_feedback").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM visual_jobs").fetchone()[0] == 1
        assert db.execute("SELECT spec FROM visual_jobs").fetchone()[0] == job
        assert tuple(db.execute("SELECT snapshot,text FROM facts").fetchone()) == before
        assert db.execute("SELECT COUNT(*) FROM fact_search").fetchone()[0] == fact_search
        assert db.execute("SELECT 1 FROM assets WHERE id=?", (candidate["asset_ref"],)).fetchone() is None
