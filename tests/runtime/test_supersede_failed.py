"""Content-changing recovery only for explicitly selected never-dispatched publishes."""
import asyncio
import io
import json

import pytest
from PIL import Image

from adapters.fake import FakeProvider
from social_operations.assets import import_image
from social_operations.domain import DomainError, OutcomeUnknown, canonical, timestamp
from social_operations.recovery import retry_failed, supersede_failed
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class BlockedProvider(FakeProvider):
    blocked = True
    lose_receipt = False

    async def execute(self, prepared, hooks):
        if self.blocked:
            raise DomainError('fixture_before_dispatch')
        observation = await super().execute(prepared, hooks)
        if self.lose_receipt:
            raise OutcomeUnknown('fixture_receipt_lost')
        return observation


@pytest.fixture
def env(tmp_path):
    now = [1800000000.]
    store = Store(tmp_path / 'ledger.sqlite', clock=lambda: now[0])
    owner = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    actor = store.authenticate(store.create_principal('tenant', 'publisher', scopes={'publish', 'status'}))
    for provider in ('vk', 'telegram'):
        store.add_connection(owner, provider, provider, account_type='fake')
        store.bind(owner, 'publisher', provider, provider, 'target-' + provider, rights=('publish',))
    app = Application(store)
    vk = BlockedProvider(tmp_path / 'remote.sqlite', 'vk', clock=lambda: now[0])
    tg = FakeProvider(tmp_path / 'remote.sqlite', 'telegram', clock=lambda: now[0])
    worker = Worker(store, {'vk': vk, 'telegram': tg})
    return store, owner, actor, app, worker, vk, tg, now


def children(store, operation):
    with store.connection() as db:
        return {r['alias']: dict(r) for r in db.execute(
            'SELECT * FROM attempts WHERE operation_id=?', (operation,))}


def args(original, **changes):
    return {'publication_id': original['resource_id'], 'expected_revision': 1,
            'request_key': 'supersede', 'change': {'kind': 'supersede_failed',
                'destinations': ['vk'], 'content': {'text': 'Corrected text'}, **changes}}


async def blocked(env, *, media=False):
    store, _, actor, app, worker, vk, tg, now = env
    request = {'to': ['vk', 'telegram'], 'content': {'text': 'Original paragraph'},
               'delivery': {'kind': 'at', 'at': timestamp(now[0] + 3600)}, 'request_key': 'original'}
    if media:
        output = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(output, format='PNG')
        ident = import_image(store, actor, output.getvalue(), 'image/png')
        request['media'] = [{'source': {'kind': 'asset', 'id': ident}, 'role': 'image', 'alt_text': 'red'}]
    original = app.accept(actor, 'publish', request)
    assert await worker.run_once()
    before = children(store, original['operation_id'])
    assert before['vk']['state'] == 'blocked' and before['vk']['dispatched'] == 0
    assert before['telegram']['state'] == 'scheduled'
    return original


@pytest.mark.asyncio
async def test_replacement_keeps_original_audit_and_successful_sibling(env):
    store, _, actor, app, worker, vk, tg, _ = env
    original = await blocked(env, media=True)
    before = children(store, original['operation_id'])
    with store.connection() as db:
        revision = tuple(db.execute('SELECT * FROM revisions WHERE publication_id=?',
                                   (original['resource_id'],)).fetchone())
        request = db.execute('SELECT request FROM operations WHERE id=?', (original['operation_id'],)).fetchone()[0]
    replacement = supersede_failed(app, actor, args(original))
    assert replacement['resource_id'] != original['resource_id'] and replacement['revision'] == 1
    after = children(store, original['operation_id'])
    assert after['telegram'] == before['telegram']
    assert after['vk']['state'] == 'cancelled' and after['vk']['dispatched'] == 0
    for field in ('plan', 'plan_digest', 'checkpoint', 'result'):
        assert after['vk'][field] == before['vk'][field]
    new = children(store, replacement['operation_id'])
    assert set(new) == {'vk'}
    plan, old = json.loads(new['vk']['plan']), json.loads(before['vk']['plan'])
    assert json.loads(plan['content_json'])['text'] == 'Corrected text'
    for field in ('assets', 'scheduled_at', 'surface', 'native_target', 'connection_id'):
        assert plan[field] == old[field]
    with store.connection() as db:
        assert tuple(db.execute('SELECT * FROM revisions WHERE publication_id=?',
                                (original['resource_id'],)).fetchone()) == revision
        assert db.execute('SELECT request FROM operations WHERE id=?',
                          (original['operation_id'],)).fetchone()[0] == request
        lineage = json.loads(db.execute('SELECT request FROM operations WHERE id=?',
                                       (replacement['operation_id'],)).fetchone()[0])['_supersedes']
        assert lineage['attempt_ids'] == [before['vk']['id']]
        assert lineage['operation_id'] == original['operation_id']
    vk.blocked = False
    assert await worker.run_once()
    assert store.receipt(actor, replacement['operation_id'])['state'] == 'scheduled'
    assert vk.count('effect') == 1 and tg.count('effect') == 1
    assert children(store, original['operation_id'])['telegram'] == before['telegram']
    with vk.db() as db:
        item = json.loads(db.execute("SELECT snapshot FROM items WHERE provider='vk'").fetchone()[0])
        assert item['text'] == 'Corrected text'


@pytest.mark.asyncio
async def test_old_intent_cannot_retry_or_supersede_twice_and_replay_never_resends(env):
    store, _, actor, app, worker, vk, tg, _ = env
    original = await blocked(env)
    replacement = supersede_failed(app, actor, args(original))
    retry = args(original)
    retry['change'] = {'kind': 'retry_failed', 'destinations': ['vk']}
    retry['request_key'] = 'old-retry'
    with pytest.raises(DomainError) as failure:
        retry_failed(app, actor, retry)
    assert failure.value.code == 'retry_not_proven_safe'
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, {**args(original), 'request_key': 'second-supersede'})
    assert failure.value.code == 'supersede_not_proven_safe'
    await worker.run_once()  # Replacement itself fails before dispatch.
    vk.blocked = False
    replay = supersede_failed(app, actor, args(original))
    assert replay['operation_id'] == replacement['operation_id'] and replay['state'] == 'blocked'
    assert not await worker.run_once()
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, args(original, content={'text': 'Different content'}))
    assert failure.value.code == 'idempotency_conflict'
    assert vk.count('effect') == 0 and tg.count('effect') == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('state,dispatched', [('outcome_unknown', 1), ('blocked', 1), ('failed', 1),
                                             ('verified', 1), ('scheduled', 1), ('accepted', 0)])
async def test_unsafe_originals_rejected_without_new_operation(env, state, dispatched):
    store, _, actor, app, _, _, _, _ = env
    original = await blocked(env)
    with store.tx() as db:
        db.execute('UPDATE attempts SET state=?,dispatched=? WHERE operation_id=? AND alias=?',
                   (state, dispatched, original['operation_id'], 'vk'))
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, args(original))
    assert failure.value.code == 'supersede_not_proven_safe'
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0] == 1


@pytest.mark.asyncio
async def test_strict_revision_destination_scope_and_actor_guards(env):
    store, owner, actor, app, _, _, _, _ = env
    original = await blocked(env)
    for request, code in [
        ({**args(original), 'expected_revision': 2}, 'revision_conflict'),
        (args(original, destinations=['missing']), 'retry_destination_mismatch'),
        (args(original, destinations=['telegram']), 'supersede_not_proven_safe'),
        (args(original, destinations=['vk', 'vk']), 'invalid_input'),
        ({**args(original), 'request_key': ''}, 'invalid_input'),
        (args(original, delivery={'kind': 'now'}), 'invalid_input'),
    ]:
        with pytest.raises(DomainError) as failure:
            supersede_failed(app, actor, request)
        assert failure.value.code == code
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, owner, args(original))
    assert failure.value.code == 'not_found'
    with store.tx() as db:
        db.execute("UPDATE principals SET scopes='[\"status\"]' WHERE id='publisher'")
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, args(original))
    assert failure.value.code == 'access_denied'


@pytest.mark.asyncio
async def test_expired_native_time_is_never_changed_to_now(env):
    store, _, actor, app, _, _, _, now = env
    original = await blocked(env)
    now[0] += 3600
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, args(original))
    assert failure.value.code == 'native_lead_time'
    assert children(store, original['operation_id'])['vk']['state'] == 'blocked'


@pytest.mark.asyncio
async def test_same_key_and_competing_keys_are_atomic_across_connections(env):
    store, _, actor, app, _, _, _, _ = env
    original = await blocked(env)
    def submit(key):
        try:
            return supersede_failed(Application(store), actor, {**args(original), 'request_key': key})
        except DomainError as error:
            return error.code
    first, second = await asyncio.gather(asyncio.to_thread(submit, 'same'), asyncio.to_thread(submit, 'same'))
    assert first['operation_id'] == second['operation_id']
    assert submit('different') == 'supersede_not_proven_safe'
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM publications').fetchone()[0] == 2


@pytest.mark.asyncio
async def test_retry_admission_and_stale_worker_are_fenced(env):
    store, _, actor, app, worker, _, _, _ = env
    original = await blocked(env)
    with store.connection() as db:
        old_operation = dict(db.execute('SELECT * FROM operations WHERE id=?', (original['operation_id'],)).fetchone())
    old_child = children(store, original['operation_id'])['vk']
    retry = args(original)
    retry['request_key'] = 'retry'
    retry['change'] = {'kind': 'retry_failed', 'destinations': ['vk']}
    retry_failed(app, actor, retry)
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, args(original))
    assert failure.value.code == 'operation_in_progress'
    assert await worker.run_once()
    supersede_failed(app, actor, args(original))
    hooks = worker.hooks(old_operation, old_child)
    with pytest.raises(DomainError) as failure:
        await hooks.before_effect(old_child['id'], old_child['plan_digest'])
    assert failure.value.code == 'stale_worker'


@pytest.mark.asyncio
async def test_uncertain_other_publication_does_not_fence_replacement(env):
    store, _, actor, app, worker, vk, tg, _ = env
    original = await blocked(env)
    vk.blocked, vk.lose_receipt = False, True
    unknown = app.accept(actor, 'publish', {'to': ['vk'], 'content': {'text': 'Different publication'},
                                          'request_key': 'uncertain-other'})
    await worker.run_once()
    assert store.receipt(actor, unknown['operation_id'])['state'] == 'running'
    replacement = supersede_failed(app, actor, args(original))
    vk.lose_receipt = False
    await worker.run_once()
    result = store.receipt(actor, replacement['operation_id'])
    assert result['state'] == 'scheduled', result
    assert vk.count('effect') == 2 and tg.count('effect') == 1
    assert store.receipt(actor, unknown['operation_id'])['state'] == 'running'


@pytest.mark.asyncio
async def test_revocation_after_admission_prevents_replacement_effect(env):
    store, owner, actor, app, worker, vk, tg, _ = env
    original = await blocked(env)
    replacement = supersede_failed(app, actor, args(original))
    new_child = children(store, replacement['operation_id'])['vk']
    store.revoke_binding(owner, new_child['binding_id'])
    vk.blocked = False
    await worker.run_once()
    assert vk.count('effect') == 0 and tg.count('effect') == 1


@pytest.mark.asyncio
async def test_competing_replacement_keys_admit_exactly_one(env):
    store, _, actor, app, _, _, _, _ = env
    original = await blocked(env)
    def submit(key):
        try:
            return supersede_failed(Application(store), actor, {**args(original), 'request_key': key})
        except DomainError as error:
            return error.code
    results = await asyncio.gather(asyncio.to_thread(submit, 'one'), asyncio.to_thread(submit, 'two'))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 'supersede_not_proven_safe' in results
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0] == 2


@pytest.mark.asyncio
async def test_retry_racing_supersede_has_one_admission(env):
    store, _, actor, app, _, _, _, _ = env
    original = await blocked(env)
    retry = args(original)
    retry['request_key'] = 'retry-race'
    retry['change'] = {'kind': 'retry_failed', 'destinations': ['vk']}
    def submit(function, request):
        try:
            return function(Application(store), actor, request)
        except DomainError as error:
            return error.code
    results = await asyncio.gather(
        asyncio.to_thread(submit, retry_failed, retry),
        asyncio.to_thread(submit, supersede_failed, args(original)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert any(result in ('operation_in_progress', 'retry_not_proven_safe')
               for result in results if isinstance(result, str))


@pytest.mark.asyncio
async def test_command_quota_rolls_back_replacement_and_original_changes(env):
    store, _, actor, app, _, _, _, _ = env
    original = await blocked(env)
    before = children(store, original['operation_id'])
    with store.tx() as db:
        db.execute('UPDATE tenants SET command_limit=0')
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, args(original))
    assert failure.value.code == 'command_quota_exceeded'
    assert children(store, original['operation_id']) == before
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM publications').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM revisions').fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM request_keys WHERE key='supersede'").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_failed_zero_dispatch_is_eligible_but_pending_recovery_is_not(env):
    store, _, actor, app, _, _, _, now = env
    original = await blocked(env)
    child = children(store, original['operation_id'])['vk']
    with store.tx() as db:
        db.execute("UPDATE attempts SET state='failed' WHERE id=?", (child['id'],))
        db.execute("INSERT INTO attempt_recovery(attempt_id,plan_digest,original_checkpoint,finalize_state,created) "
                   "VALUES(?,?,?,'pending',?)", (child['id'], child['plan_digest'], child['checkpoint'], now[0]))
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, args(original))
    assert failure.value.code == 'operation_in_progress'
    with store.tx() as db:
        db.execute("UPDATE attempt_recovery SET finalize_state='done' WHERE attempt_id=?", (child['id'],))
    assert supersede_failed(app, actor, args(original))['state'] == 'accepted'


@pytest.mark.asyncio
async def test_application_schema_and_publish_only_route(env):
    _, _, actor, app, _, _, _, _ = env
    original = await blocked(env)
    result = await app.call(actor, 'vibepublish_publication_update', args(original))
    assert 'error' not in result, result
    assert result['resource_id'] != original['resource_id']
    replay = await app.call(actor, 'vibepublish_publication_update', args(original))
    assert replay['operation_id'] == result['operation_id']
    for request in (
        {key: value for key, value in args(original).items() if key != 'request_key'},
        args(original, destinations=['unbound']),
        args(original, delivery={'kind': 'now'}),
        {**args(original), 'item_ref': 'item_fake'},
    ):
        response = await app.call(actor, 'vibepublish_publication_update', request)
        assert response['error']['code'] == 'invalid_input'


@pytest.mark.asyncio
async def test_actor_epoch_change_denies_both_stale_and_reauthenticated_actor(env):
    from dataclasses import replace
    store, _, actor, app, _, _, _, _ = env
    original = await blocked(env)
    with store.tx() as db:
        db.execute("UPDATE principals SET epoch=epoch+1 WHERE id='publisher'")
    for current in (actor, replace(actor, epoch=actor.epoch + 1)):
        with pytest.raises(DomainError) as failure:
            supersede_failed(app, current, args(original))
        assert failure.value.code == 'access_revoked'
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('content', [None, 'text', [], {'text': 1}, {}, {'text': 'x', 'unknown': True}])
async def test_direct_handler_rejects_malformed_content_without_mutation(env, content):
    store, _, actor, app, _, _, _, _ = env
    original = await blocked(env)
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, args(original, content=content))
    assert failure.value.code == 'invalid_input'
    assert children(store, original['operation_id'])['vk']['state'] == 'blocked'


@pytest.mark.asyncio
async def test_replay_rechecks_publish_right_without_epoch_change(env):
    store, _, actor, app, _, _, _, _ = env
    original = await blocked(env)
    replacement = supersede_failed(app, actor, args(original))
    before = children(store, replacement['operation_id'])
    with store.tx() as db:
        db.execute("UPDATE bindings SET rights='[\"edit\"]' WHERE id=?", (before['vk']['binding_id'],))
    with pytest.raises(DomainError) as failure:
        supersede_failed(app, actor, args(original))
    assert failure.value.code == 'access_denied'
    assert children(store, replacement['operation_id']) == before
