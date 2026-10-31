"""VK native carousel edits and retained media; synthetic provider, no live network."""
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from adapters.vk import VKAdapter
from social_operations.assets import import_image, retired_asset_rows
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from social_operations.domain import timestamp
from tests.providers.scripted import VKTransport


NOW = 1_800_000_000
OWNER = -241261191
ORIGINAL = "photo-241261191_457239112"
NOTE = "Если вы заметили неточность в колоризации, пожалуйста, напишите в комментариях"


def setup(tmp_path, *, scheduled=False):
    current = [float(NOW)]
    store = Store(tmp_path / "vk.sqlite", clock=lambda: current[0])
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(actor, "conn", "vk", account_type="vk_user")
    store.bind(actor, "owner", "lovekenig_vk", "conn", str(OWNER),
               rights=("publish", "edit", "reschedule", "cancel", "delete"))
    transport = VKTransport()
    transport.groups[-OWNER] = {"id": -OWNER, "is_admin": 1, "admin_level": 3, "is_closed": 0}
    transport.posts[(OWNER, 223)] = {
        "id": 223, "owner_id": OWNER, "text": "Исходный текст",
        "date": NOW + 3600 if scheduled else NOW - 3600,
        "post_type": "postpone" if scheduled else "post",
        "attachments": [{"type": "photo", "photo": {"owner_id": OWNER, "id": 457239112}}],
        "can_repost": 1,
    }
    adapter = VKAdapter(transport, connection_id="conn", clock=lambda: current[0])
    image = io.BytesIO()
    Image.new("RGB", (30, 40), "red").save(image, format="PNG")
    new_asset = import_image(store, actor, image.getvalue(), "image/png")
    return SimpleNamespace(store=store, actor=actor, app=Application(store),
                           worker=Worker(store, {"vk": adapter}), transport=transport,
                           current=current, new_asset=new_asset)


async def fresh_item(env, *, scheduled=False):
    if scheduled:
        queue = await env.app.call(env.actor, "vibepublish_read",
                                   {"query": {"kind": "scheduled", "destination": "lovekenig_vk"}})
        assert "error" not in queue, queue
        assert await env.worker.run_once()
        queued = env.store.receipt(env.actor, queue["operation_id"])
        ref = queued["items"][0]["ref"]
    else:
        ref = "https://vk.com/wall-241261191_223"
    read = await env.app.call(env.actor, "vibepublish_read",
                              {"query": {"kind": "item", "item_ref": ref}})
    assert "error" not in read, read
    assert await env.worker.run_once()
    done = env.store.receipt(env.actor, read["operation_id"])
    assert done["state"] == "verified", done
    return done["items"][0]["ref"]


def edit(fresh, asset):
    return {"item_ref": fresh, "request_key": "native-carousel-223",
            "change": {"kind": "edit",
                       "content": {"text": "Исходный текст\n\n" + NOTE},
                       "media": [{"source": {"kind": "asset", "id": asset}},
                                 {"source": {"kind": "existing", "position": 0}}]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("scheduled", [False, True])
async def test_unmanaged_vk_post_edits_native_carousel_without_original_bytes(tmp_path, scheduled):
    env = setup(tmp_path, scheduled=scheduled)
    fresh = await fresh_item(env, scheduled=scheduled)
    accepted = await env.app.call(env.actor, "vibepublish_publication_update",
                                  edit(fresh, env.new_asset))
    assert "error" not in accepted, accepted
    # An unmanaged post does not require a previous VibePublish publication.
    assert accepted["revision"] == 1
    with env.store.connection() as db:
        plan = db.execute("SELECT plan FROM attempts WHERE operation_id=?",
                          (accepted["operation_id"],)).fetchone()[0]
        assert ORIGINAL in plan and "provider_ref" in plan
    before = len(env.transport.uploads)
    assert await env.worker.run_once()
    done = env.store.receipt(env.actor, accepted["operation_id"])
    assert done["state"] in {"verified", "scheduled"}, done
    params = [params for name, _, params in env.transport.calls if name == "wall.edit"]
    assert len(params) == 1
    assert params[0]["post_id"] == 223 and params[0]["owner_id"] == OWNER
    assert params[0]["attachments"] == "photo-241261191_1001," + ORIGINAL
    assert params[0]["message"] == "Исходный текст\n\n" + NOTE
    assert len(env.transport.uploads) == before + 1
    assert env.transport.posts[(OWNER, 223)]["id"] == 223
    assert done["deliveries"][0]["state"] in {"verified", "scheduled"}



@pytest.mark.asyncio
async def test_vk_permalink_does_not_grant_another_group(tmp_path):
    env = setup(tmp_path)
    denied = await env.app.call(env.actor, "vibepublish_read", {
        "query": {"kind": "item", "item_ref": "https://vk.com/wall-241261192_223"}})
    assert denied["error"]["code"] == "item_link_not_bound"
    with env.store.connection() as db:
        assert db.execute("SELECT count(*) FROM bindings").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_old_vk_read_is_not_a_fresh_media_edit_reference(tmp_path):
    env = setup(tmp_path)
    fresh = await fresh_item(env)
    env.current[0] += 301
    denied = await env.app.call(env.actor, "vibepublish_publication_update",
                                edit(fresh, env.new_asset))
    assert denied["error"]["code"] == "managed_media_reference_stale"
    assert not any(name == "wall.edit" for name, _, _ in env.transport.calls)


@pytest.mark.asyncio
async def test_native_existing_selector_is_not_a_publish_media_ingress(tmp_path):
    env = setup(tmp_path)
    denied = await env.app.call(env.actor, "vibepublish_publish", {
        "to": ["lovekenig_vk"], "content": {"text": "Not an edit"},
        "media": [{"source": {"kind": "existing", "position": 0}}]})
    assert denied["error"]["code"] == "native_attachment_not_enabled"


@pytest.mark.asyncio
async def test_changed_vk_snapshot_blocks_edit_before_upload_or_wall_write(tmp_path):
    env = setup(tmp_path)
    fresh = await fresh_item(env)
    accepted = await env.app.call(env.actor, "vibepublish_publication_update",
                                  edit(fresh, env.new_asset))
    assert "error" not in accepted, accepted
    env.transport.posts[(OWNER, 223)]["text"] = "Changed from another client"
    before = len(env.transport.uploads)
    assert await env.worker.run_once()
    assert len(env.transport.uploads) == before
    assert not any(name == "wall.edit" for name, _, _ in env.transport.calls)


@pytest.mark.asyncio
async def test_scheduled_vk_due_guard_remains_in_force(tmp_path):
    env = setup(tmp_path, scheduled=True)
    fresh = await fresh_item(env, scheduled=True)
    accepted = await env.app.call(env.actor, "vibepublish_publication_update",
                                  edit(fresh, env.new_asset))
    assert "error" not in accepted, accepted
    env.current[0] = NOW + 3560
    assert await env.worker.run_once()
    assert not any(name == "wall.edit" for name, _, _ in env.transport.calls)


@pytest.mark.asyncio
async def test_vk_publication_edit_keeps_original_native_attachment_after_byte_purge(tmp_path):
    env = setup(tmp_path)
    # Native provider publication is verified, then local bytes are removed.
    started = await env.app.call(env.actor, "vibepublish_publish", {
        "to": ["lovekenig_vk"], "content": {"text": "Original managed"},
        "media": [{"source": {"kind": "asset", "id": env.new_asset}}],
        "request_key": "managed-post",
    })
    assert "error" not in started, started
    assert await env.worker.run_once()
    assert env.store.receipt(env.actor, started["operation_id"])["state"] == "verified"
    with env.store.tx() as db:
        db.execute("DELETE FROM assets WHERE id=?", (env.new_asset,))
    changed = await env.app.call(env.actor, "vibepublish_publication_update", {
        "publication_id": started["resource_id"], "expected_revision": 1,
        "change": {"kind": "edit", "destinations": ["lovekenig_vk"],
                   "content": {"text": "Updated without stored original"}},
        "request_key": "text-only-after-purge",
    })
    assert "error" not in changed, changed
    assert await env.worker.run_once()
    assert env.store.receipt(env.actor, changed["operation_id"])["state"] == "verified"
    call = [params for name, _, params in env.transport.calls if name == "wall.edit"][-1]
    assert call["attachments"] == "photo-241261191_1001"
    assert call["message"] == "Updated without stored original"


from tests.visuals.test_visual_service import runtime as visual_runtime


@pytest.mark.asyncio
async def test_retention_keeps_visual_candidate_lineage_until_proven_safe(visual_runtime):
    store, actor, app, worker, _, _, clock, *_ = visual_runtime
    queued = await app.call(actor, 'vibepublish_visual', {
        'command': {'kind': 'generate', 'brief': 'Protected lineage example', 'candidates': 1},
        'request_key': 'candidate-lineage'})
    assert 'error' not in queued, queued
    assert await worker.run_once()
    with store.connection() as db:
        candidate = db.execute('SELECT asset_ref FROM visual_candidates LIMIT 1').fetchone()
        assert candidate
        asset_id = candidate['asset_ref']
        reasons = {row['id']: row['reason'] for row in retired_asset_rows(db, clock[0])}
        assert reasons[asset_id] == 'recent_visual'
    clock[0] += 61
    assert not await worker.run_once()
    with store.connection() as db:
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (asset_id,)).fetchone()


@pytest.mark.asyncio
async def test_worker_retention_removes_verified_and_14_day_orphans(tmp_path):
    env = setup(tmp_path)
    first = await env.app.call(env.actor, "vibepublish_publish", {
        "to": ["lovekenig_vk"], "content": {"text": "Original managed"},
        "media": [{"source": {"kind": "asset", "id": env.new_asset}}],
    })
    assert "error" not in first, first
    with env.store.connection() as db:
        categories = {r["id"]: r["reason"] for r in retired_asset_rows(db, env.current[0])}
    assert categories[env.new_asset] == "pending_action"
    with env.store.connection() as db:
        quick = {r["id"]: r["reason"] for r in retired_asset_rows(db, env.current[0], include_sizes=False)}
        assert quick == categories  # Covering index avoids loading large local BLOB pages.
        plan = db.execute("EXPLAIN QUERY PLAN SELECT id,0,created FROM assets "
                          "INDEXED BY assets_retention_lookup").fetchall()
        assert any("COVERING INDEX" in row["detail"] for row in plan)
    assert await env.worker.run_once()
    env.current[0] += 61
    assert not await env.worker.run_once()
    with env.store.connection() as db:
        assert db.execute("SELECT 1 FROM assets WHERE id=?", (env.new_asset,)).fetchone() is None
        assert db.execute("SELECT count(*) FROM assets").fetchone()[0] >= 1  # unlinked ingress source
    env.current[0] += 15 * 86400
    assert not await env.worker.run_once()
    with env.store.connection() as db:
        assert db.execute("SELECT count(*) FROM assets").fetchone()[0] == 0
