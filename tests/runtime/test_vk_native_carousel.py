"""VK native carousel edits and retained media; synthetic provider, no live network."""
import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from adapters.vk import VKAdapter
from social_operations.assets import import_image, retired_asset_rows
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from social_operations.domain import DomainError, timestamp
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
async def test_exact_vk_photo_read_downloads_bytes_and_keeps_native_edit_cas(tmp_path, scheduled):
    env = setup(tmp_path, scheduled=scheduled)
    photo = env.transport.posts[(OWNER, 223)]['attachments'][0]['photo']
    image = io.BytesIO()
    Image.new("RGB", (1200, 800), "green").save(image, format="PNG")
    wire = image.getvalue()
    signed = "https://sun9-12.userapi.com/source.jpg?access_key=never-persist"
    largest = "https://sun9-12.userapi.com/largest.jpg?access_key=never-persist"
    photo['sizes'] = [
        {'url': signed, 'width': 100, 'height': 100},
        {'url': largest, 'width': 1200, 'height': 800},
    ]
    if scheduled:
        photo['orig_photo'] = {'url': signed, 'width': 1600, 'height': 900}
    called = []

    async def download(url):
        called.append(url)
        return wire

    env.transport.download_photo = download
    listing = await env.app.call(env.actor, "vibepublish_read", {
        "query": {"kind": "scheduled" if scheduled else "feed", "destination": "lovekenig_vk"}})
    assert await env.worker.run_once()
    listed = env.store.receipt(env.actor, listing['operation_id'])
    assert listed['items'] and not called
    ref = listed['items'][0]['ref']
    with env.store.connection() as db:
        before_assets = db.execute('SELECT count(*) FROM assets').fetchone()[0]
    read = await env.app.call(env.actor, "vibepublish_read", {
        "query": {"kind": "item", "item_ref": ref}})
    assert await env.worker.run_once()
    done = env.store.receipt(env.actor, read['operation_id'])
    assert done['state'] == 'verified'
    item, = done['items']
    assert called == [signed if scheduled else largest]
    assert item['text'] == 'Исходный текст'
    if scheduled:
        assert item['scheduled_at'] == timestamp(NOW + 3600)
    assert item['media'][0]['source']['kind'] == 'asset'
    assert (item['media'][0]['width'], item['media'][0]['height']) == (1200, 800)
    asset_id = item['media'][0]['source']['id']
    assert item['media_evidence'][0]['resource_uri'] == 'vibepublish://assets/' + asset_id
    assert item['media_evidence'][0]['sha256'] == hashlib.sha256(wire).hexdigest()
    full, mime, _ = env.app.read_asset(env.actor, asset_id)
    assert full == wire and mime == 'image/png'
    with env.store.connection() as db:
        cache = db.execute('SELECT purpose,publication_id,expires FROM media_store_assets WHERE asset_id=?',
                           (asset_id,)).fetchone()
        assert cache['purpose'] == 'download_cache' and cache['publication_id'] is None
        assert cache['expires'] == NOW + 3600
        # VK source reads create one expiring copy, not a raw+sanitized pair.
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == before_assets + 1
    with Image.open(io.BytesIO(full)) as decoded:
        assert decoded.size == (1200, 800)  # Full-size asset, not the 768 px preview.
    assert 'never-persist' not in json.dumps(done)
    with env.store.connection() as db:
        assert 'never-persist' not in str(db.execute(
            'SELECT snapshot FROM item_refs ORDER BY rowid DESC LIMIT 1').fetchone()[0])
    accepted = await env.app.call(env.actor, "vibepublish_publication_update",
                                  edit(item['ref'], env.new_asset))
    assert 'error' not in accepted, accepted
    assert await env.worker.run_once()
    edited = env.store.receipt(env.actor, accepted['operation_id'])
    assert edited['state'] == ('scheduled' if scheduled else 'verified'), edited
    assert any(name == 'wall.edit' for name, _, _ in env.transport.calls)
    env.current[0] = NOW + 3601
    with pytest.raises(DomainError) as expired:
        env.app.read_asset(env.actor, asset_id)
    assert expired.value.code == 'asset_not_available'
    with env.store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets WHERE id=?', (asset_id,)).fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM media_store_assets WHERE asset_id=?', (asset_id,)).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_vk_photo_cache_is_held_only_for_an_unfinished_edit(tmp_path):
    env = setup(tmp_path)
    photo = env.transport.posts[(OWNER, 223)]['attachments'][0]['photo']
    photo['sizes'] = [{'url': 'https://sun9.userapi.com/source.jpg',
                       'width': 30, 'height': 40}]
    image = io.BytesIO()
    Image.new('RGB', (30, 40), 'blue').save(image, format='PNG')
    wire = image.getvalue()

    async def download(_url):
        return wire

    env.transport.download_photo = download
    ref = await fresh_item(env)
    with env.store.connection() as db:
        result = json.loads(db.execute(
            "SELECT result FROM operations WHERE action='read' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0])
    cached = result['items'][0]['media'][0]['source']['id']
    queued = await env.app.call(env.actor, 'vibepublish_publication_update',
                                edit(ref, cached))
    assert 'error' not in queued, queued
    env.current[0] += 3601
    assert env.app.read_asset(env.actor, cached)[0] == wire
    with env.store.connection() as db:
        assert db.execute('SELECT count(*) FROM media_store_assets WHERE asset_id=?',
                          (cached,)).fetchone()[0] == 1
    # The existing purge guards a plan's asset while the operation is unfinished.
    assert env.store.receipt(env.actor, queued['operation_id'])['state'] == 'accepted'


@pytest.mark.asyncio
@pytest.mark.parametrize("scheduled", [False, True])
async def test_vk_photo_download_failure_preserves_exact_item(tmp_path, scheduled, caplog):
    env = setup(tmp_path, scheduled=scheduled)
    photo = env.transport.posts[(OWNER, 223)]['attachments'][0]['photo']
    photo['sizes'] = [{'url': 'https://sun9-12.userapi.com/image?access_key=private-123',
                       'width': 800, 'height': 600}]

    async def fail_download(url):
        raise OSError("private-123 / " + url)

    env.transport.download_photo = fail_download
    ref = await fresh_item(env, scheduled=scheduled)
    # fresh_item confirms verified exact read even when photo bytes are unavailable.
    with env.store.connection() as db:
        item = json.loads(db.execute(
            'SELECT result FROM operations WHERE action=\'read\' ORDER BY rowid DESC LIMIT 1').fetchone()[0])['items'][0]
        snapshots = [row[0] for row in db.execute('SELECT snapshot FROM item_refs')]
    assert item['ref'] == ref and item['text'] == 'Исходный текст'
    assert item['error']['code'] == 'media_download_unavailable'
    assert 'vk_photo_transport_failed' in item['error']['message']
    assert not item.get('media')
    if scheduled:
        assert item['scheduled_at'] == timestamp(NOW + 3600)
    assert 'private-123' not in json.dumps(item) + ''.join(snapshots) + caplog.text
    accepted = await env.app.call(env.actor, 'vibepublish_publication_update',
                                  edit(ref, env.new_asset))
    assert 'error' not in accepted, accepted


@pytest.mark.asyncio
@pytest.mark.parametrize("gone", ["published", "deleted"])
async def test_scheduled_exact_item_gone_does_not_adopt_neighbor_or_write(tmp_path, gone):
    env = setup(tmp_path, scheduled=True)
    fresh = await fresh_item(env, scheduled=True)
    # Keep a different postponed item in the same queue; missing item must
    # never resolve to this neighbor, even when its ID is the only one left.
    env.transport.posts[(OWNER, 224)] = {
        **env.transport.posts[(OWNER, 223)], "id": 224, "text": "Another queued post",
    }
    if gone == "published":
        env.transport.posts[(OWNER, 223)]["post_type"] = "post"
    else:
        del env.transport.posts[(OWNER, 223)]
    lookup = await env.app.call(env.actor, "vibepublish_read", {
        "query": {"kind": "item", "item_ref": fresh}})
    assert "error" not in lookup, lookup
    assert await env.worker.run_once()
    empty = env.store.receipt(env.actor, lookup["operation_id"])
    assert empty["state"] == "verified" and empty["items"] == [], empty
    accepted = await env.app.call(env.actor, "vibepublish_publication_update",
                                  edit(fresh, env.new_asset))
    assert "error" not in accepted, accepted
    before = len(env.transport.uploads)
    assert await env.worker.run_once()
    result = env.store.receipt(env.actor, accepted["operation_id"])
    assert result["error"]["code"] == "remote_item_missing", result
    assert len(env.transport.uploads) == before
    assert not any(name == "wall.edit" for name, _, _ in env.transport.calls)


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
@pytest.mark.parametrize('scheduled', [False, True])
async def test_exact_vk_id_normalized_text_and_time_are_verified_with_warning(tmp_path, scheduled):
    env = setup(tmp_path, scheduled=scheduled)
    fresh = await fresh_item(env, scheduled=scheduled)

    def normalize_after_edit(method):
        if method == 'wall.edit':
            post = env.transport.posts[(OWNER, 223)]
            post['text'] = post['text'].replace('\n', '\r\n') + '  '
            if scheduled:
                post['date'] += 60

    env.transport.after_mutation = normalize_after_edit
    accepted = await env.app.call(env.actor, 'vibepublish_publication_update',
                                  edit(fresh, env.new_asset))
    assert 'error' not in accepted, accepted
    assert await env.worker.run_once()
    done = env.store.receipt(env.actor, accepted['operation_id'])
    assert done['state'] == ('scheduled' if scheduled else 'verified'), done
    assert done['operation_complete']
    with env.store.connection() as db:
        events = [json.loads(row[2]) for row in db.execute(
            'SELECT * FROM events WHERE operation_id=?', (accepted['operation_id'],))]
    assert any('differs in text or schedule; trusting its ID' in e['message'] for e in events)
    assert len([name for name, _, _ in env.transport.calls if name == 'wall.edit']) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('scheduled', [False, True])
async def test_vk_unsupported_attachment_is_readable_but_never_edited(tmp_path, scheduled):
    env = setup(tmp_path, scheduled=scheduled)
    env.transport.posts[(OWNER, 223)]['attachments'].append(
        {'type': 'poll', 'poll': {'owner_id': OWNER, 'id': 987}})
    fresh = await fresh_item(env, scheduled=scheduled)
    accepted = await env.app.call(env.actor, 'vibepublish_publication_update',
                                  edit(fresh, env.new_asset))
    assert 'error' not in accepted, accepted
    upload_count = len(env.transport.uploads)
    assert await env.worker.run_once()
    done = env.store.receipt(env.actor, accepted['operation_id'])
    assert done['operation_complete'] and done['state'] in {'blocked', 'failed'}, done
    assert done['error']['code'] == 'vk_attachment_edit_unsupported', done
    assert len(env.transport.uploads) == upload_count
    assert not any(name == 'wall.edit' for name, _, _ in env.transport.calls)
    assert env.transport.posts[(OWNER, 223)]['attachments'][-1]['type'] == 'poll'


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
