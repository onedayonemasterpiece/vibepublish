"""Durable one-parent Story continuation: real core, SQLite and VK adapter."""
import asyncio
import copy
import json
import sqlite3

import pytest

from adapters.vk_transport import VKHTTPTransport, VKToken
from social_operations.domain import DomainError, timestamp
from social_operations.storage import Store
from social_operations.assets import retired_asset_rows
from social_operations.worker import Worker
from social_operations.vk_story_dependencies import ingest_events, RECOVERY_WINDOW
from .test_vk_story_links import runtime




@pytest.mark.asyncio
@pytest.mark.parametrize('origin', [123, None, 0, True, '123'])
async def test_authorized_read_exposes_only_explicit_native_mapping(tmp_path, origin):
    store, actor, app, worker, transport, args = runtime(tmp_path)
    post = transport.posts[(-101, 42)]
    if origin is not None:post['postponed_id'] = origin
    accepted = await app.call(actor, 'vibepublish_read', {'query': {'kind': 'feed', 'destination': 'vk-story'}, 'limit': 10})
    assert accepted['state'] == 'accepted', accepted
    assert await worker.run_once()
    result = await app.call(actor, 'vibepublish_status', {'ids': [accepted['operation_id']]})
    item = result['receipts'][0]['items'][0]
    if type(origin) is int and origin > 0:
        assert item['native_schedule_origin'] == {'owner_id':'-101', 'postponed_id':'123', 'published_id':'42', 'evidence':'vk_postponed_id'}
    else:
        assert 'native_schedule_origin' not in item
    assert transport.effects == 0 and not transport.uploads


def setup(tmp_path, *, scheduled=True):
    store, actor, app, worker, transport, story = runtime(tmp_path)
    now = [1800000000.0]
    store.clock = lambda: now[0]
    args = {'to': ['vk-story'], 'content': {'text': 'Approved parent'},
            'linked_story': {'media': story['media'], 'text': 'read'},
            'request_key': 'parent-with-story'}
    if scheduled:
        args['delivery'] = {'kind': 'at', 'at': timestamp(now[0] + 180)}
    return store, actor, app, worker, transport, now, args


def dep(store):
    with store.connection() as db:
        return dict(db.execute('SELECT * FROM vk_story_dependencies').fetchone())


async def admit(env):
    store, actor, app, worker, transport, now, args = env
    receipt = await app.call(actor, 'vibepublish_publish', args)
    assert receipt['state'] == 'accepted', receipt
    assert receipt['linked_story']['state'] == 'waiting'
    assert await worker.run_once()
    parent = store.receipt(actor, receipt['operation_id'])
    assert parent['state'] in {'scheduled', 'verified'}, parent
    ident = transport.next_id
    return receipt, ident


def published(env, ident):
    store, actor, app, worker, transport, now, args = env
    transport.posts[(-101, ident)]['post_type'] = 'post'
    transport.posts[(-101, ident)]['postponed_id'] = ident
    now[0] += 181


def event(ident, *, event_id='native-1', group=101):
    return {'type': 'wall_post_new', 'group_id': group, 'event_id': event_id,
            'object': {'id': ident, 'postponed_id': ident, 'owner_id': -group, 'text': 'untrusted event body'}}


@pytest.mark.asyncio
async def test_linked_story_awaiting_native_parent_holds_asset_bytes(tmp_path):
    env = setup(tmp_path)
    store, actor, app, worker, transport, now, args = env
    _, ident = await admit(env)
    with store.connection() as db:
        source = db.execute("SELECT json_extract(story_plan,'$.assets[0].ref') FROM vk_story_dependencies").fetchone()[0]
        reasons = {row['id']: row['reason'] for row in retired_asset_rows(db, now[0])}
        assert reasons[source] == 'pending_linked_story'
    assert await worker.run_once()  # clean-up tick must not consume the future child input
    with store.connection() as db:
        assert db.execute('SELECT 1 FROM assets WHERE id=?', (source,)).fetchone()
    published(env, ident)
    assert await worker.run_once()
    assert dep(store)['state'] == 'queued'


@pytest.mark.asyncio
@pytest.mark.parametrize('with_event', [True, False])
async def test_publish_after_exact_parent_event_or_missed_event(tmp_path, with_event):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    receipt, ident = await admit(env)
    assert await worker.run_once()
    assert transport.effects == 1 and not transport.stories
    published(env, ident)
    if with_event:
        assert ingest_events(store, 'vk-connection', '-101', [event(ident)] * 2, '11') == 1
    assert await worker.run_once()
    assert dep(store)['state'] == 'queued'
    # Process restart retains frozen intent, source and exactly one child.
    worker = Worker(Store(store.path, clock=store.clock), worker.adapters)
    assert await worker.run_once()
    now[0] += 61
    assert await worker.run_once()
    assert dep(store)['state'] == 'verified'
    assert transport.effects == 2 and len(transport.stories) == 1
    story = next(iter(transport.stories.values()))
    assert story['link'] == {'url': f'https://vk.com/wall-101_{ident}', 'text': 'read'}
    final = await app.call(actor, 'vibepublish_status', {'ids': [receipt['operation_id']]})
    assert 'error' not in final, final
    assert final['receipts'][0]['linked_story']['state'] == 'verified'
    for _ in range(3):
        ingest_events(store, 'vk-connection', '-101', [event(ident)], '12')
        now[0] += 61
        await worker.run_once()
    assert transport.effects == 2


@pytest.mark.asyncio
async def test_early_event_still_requires_published_exact_parent(tmp_path):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    _, ident = await admit(env)
    ingest_events(store, 'vk-connection', '-101', [event(ident)], '11')
    assert await worker.run_once()
    assert dep(store)['state'] == 'waiting' and transport.effects == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['content', 'media', 'revision', 'revoke', 'asset', 'expire', 'delete'])
async def test_parent_or_authority_change_never_sends_story(tmp_path, change):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    receipt, ident = await admit(env)
    published(env, ident)
    with store.tx() as db:
        if change == 'revision':
            db.execute('UPDATE publications SET revision=revision+1 WHERE id=?', (receipt['resource_id'],))
        elif change == 'revoke':
            db.execute('UPDATE bindings SET epoch=epoch+1')
        elif change == 'asset':
            db.execute("DELETE FROM assets WHERE id='asset_story'")
    if change == 'content':transport.posts[(-101, ident)]['text'] = 'Changed externally'
    if change == 'media':transport.posts[(-101, ident)]['attachments'] = [{'type':'photo','photo':{'owner_id':-101,'id':999}}]
    if change == 'expire':now[0] += RECOVERY_WINDOW
    if change == 'delete':transport.posts.pop((-101, ident))
    assert await worker.run_once()
    assert transport.effects == 1 and not transport.stories
    assert dep(store)['state'] != 'queued'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['revision', 'content', 'expire'])
async def test_change_between_admission_and_child_dispatch_blocks(tmp_path, change):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    receipt, ident = await admit(env);published(env, ident)
    assert await worker.run_once()
    assert dep(store)['state'] == 'queued'
    if change == 'revision':
        with store.tx() as db:db.execute('UPDATE publications SET revision=revision+1 WHERE id=?', (receipt['resource_id'],))
    if change == 'content':transport.posts[(-101, ident)]['text'] = 'Externally changed'
    if change == 'expire':now[0] += RECOVERY_WINDOW
    assert await worker.run_once()
    assert not transport.stories and transport.effects == 1


@pytest.mark.asyncio
async def test_concurrent_observation_admits_once(tmp_path):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    _, ident = await admit(env);published(env, ident)
    other = Worker(Store(store.path, clock=store.clock), worker.adapters)
    await asyncio.gather(worker.run_once(), other.run_once())
    await worker.run_once()
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM operations WHERE json_extract(request,'$.dependency_id') IS NOT NULL").fetchone()[0] == 1
    assert transport.effects == 2


@pytest.mark.asyncio
async def test_unknown_story_save_never_repeats(tmp_path):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    _, ident = await admit(env);published(env, ident)
    await worker.run_once()
    def lost(method):
        if method == 'stories.save': raise OSError('lost response')
    transport.after_mutation = lost
    await worker.run_once()
    for _ in range(3):
        now[0] += 61;await worker.run_once()
    assert dep(store)['state'] == 'queued'
    assert transport.effects == 2 and len(transport.stories) == 1


@pytest.mark.asyncio
async def test_idempotent_parent_and_immutable_dependency(tmp_path):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    receipt, _ = await admit(env)
    replay = await app.call(actor, 'vibepublish_publish', copy.deepcopy(args))
    assert replay['operation_id'] == receipt['operation_id']
    with store.tx() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE vk_story_dependencies SET link_text='more'")
    assert Store(store.path, clock=store.clock)


@pytest.mark.asyncio
async def test_event_batch_is_not_authority_and_cursor_is_durable(tmp_path):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    _, ident = await admit(env)
    assert ingest_events(store, 'vk-connection', '-101', [event(ident, group=202)], '77') == 0
    with store.connection() as db:
        assert db.execute('SELECT cursor FROM vk_story_event_cursors').fetchone()[0] == '77'
    with pytest.raises(DomainError):ingest_events(store, 'vk-connection', '-101', [], 'secret-invalid')
    assert not transport.stories


@pytest.mark.asyncio
async def test_existing_group_events_readiness_and_reset():
    user = VKHTTPTransport(tokens={'reader': VKToken('fixture', 'user')})
    assert (await user.poll_wall_events('-101', None))['status'] == 'unavailable_existing_group_token_required'
    group = VKHTTPTransport(tokens={'reader': VKToken('fixture', 'group', 101)})
    calls = []
    async def invoke(**kw):
        calls.append(kw['method'])
        if kw['method'] == 'groups.getLongPollSettings':return {'is_enabled':1,'events':{'wall_post_new':1}}
        return {'server':'https://lp.vk.com/wh101','key':'ephemeral','ts':'20'}
    async def post(url, data, **kw):
        assert data['act'] == 'a_check' and data['ts'] == '19'
        return {'failed':1,'ts':21}
    group.invoke=invoke;group._post=post
    assert await group.poll_wall_events('-101','19') == {'status':'cursor_reset','cursor':'21','updates':[]}
    assert calls == ['groups.getLongPollSettings','groups.getLongPollServer']
    assert (await group.poll_wall_events('-202',None))['status'] == 'unavailable_existing_group_token_required'


@pytest.mark.asyncio
async def test_mutable_history_cannot_replace_parent_baseline(tmp_path):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    _, ident = await admit(env);published(env, ident)
    transport.posts[(-101, ident)]['text'] = 'Unapproved externally changed text'
    with store.tx() as db:
        row = db.execute("SELECT id,snapshot FROM facts WHERE native_id=?", (str(ident),)).fetchone()
        snapshot = json.loads(row['snapshot']);snapshot['text'] = transport.posts[(-101, ident)]['text']
        db.execute('UPDATE facts SET snapshot=? WHERE id=?', (json.dumps(snapshot),row['id']))
    await worker.run_once()
    assert dep(store)['state'] == 'cancelled' and transport.effects == 1


@pytest.mark.asyncio
async def test_external_parent_change_during_upload_stops_before_save(tmp_path):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    _, ident = await admit(env);published(env, ident)
    await worker.run_once()
    original = transport.upload_story_photo
    async def upload(*a, **kw):
        result = await original(*a, **kw)
        transport.posts[(-101, ident)]['text'] = 'Changed while staging'
        return result
    transport.upload_story_photo = upload
    await worker.run_once()
    assert transport.effects == 1 and not transport.stories


@pytest.mark.asyncio
async def test_immediate_parent_continuation(tmp_path):
    env = setup(tmp_path, scheduled=False)
    store, actor, app, worker, transport, now, args = env
    await admit(env)
    await worker.run_once();await worker.run_once()
    assert len(transport.stories) == 1 and transport.effects == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['preview', 'story', 'multiple_vk', 'label'])
async def test_dependency_admission_fails_closed(tmp_path, mutation):
    env = setup(tmp_path);store, actor, app, worker, transport, now, args = env
    if mutation == 'preview':args['mode'] = 'preview'
    if mutation == 'story':args['surface'] = 'story'
    if mutation == 'label':args['linked_story']['text'] = 'custom'
    if mutation == 'multiple_vk':
        store.bind(actor, 'owner', 'other-vk', 'vk-connection', '-202')
        args['to'].append('other-vk')
    result = await app.call(actor, 'vibepublish_publish', args)
    assert 'error' in result and transport.effects == 0
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM vk_story_dependencies').fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('with_event', [True, False])
async def test_changed_native_id_uses_explicit_mapping_and_new_link(tmp_path, with_event):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    _, ident = await admit(env);published(env, ident)
    new_id = ident + 100
    post = transport.posts.pop((-101, ident));post['id'] = new_id
    transport.posts[(-101,new_id)] = post
    if with_event:
        update = event(new_id);update['object']['postponed_id'] = ident
        # Event proof survives restart and cannot be reconstructed from text.
        ingest_events(store, 'vk-connection', '-101', [update, update], '30')
        post.pop('postponed_id')
    worker = Worker(Store(store.path, clock=store.clock), worker.adapters)
    await worker.run_once();await worker.run_once()
    assert next(iter(transport.stories.values()))['link']['url'] == f'https://vk.com/wall-101_{new_id}'
    assert transport.effects == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('mapping', ['missing', 'conflicting', 'wrong_parent'])
async def test_same_content_never_substitutes_for_native_mapping(tmp_path, mapping):
    env = setup(tmp_path); store, actor, app, worker, transport, now, args = env
    _, ident = await admit(env);published(env, ident)
    post = transport.posts.pop((-101,ident));post['id'] = ident+100
    transport.posts[(-101,ident+100)] = post
    if mapping == 'missing':post.pop('postponed_id')
    elif mapping == 'wrong_parent':post['postponed_id'] = ident+1
    else:
        second = copy.deepcopy(post);second['id'] += 1
        transport.posts[(-101,second['id'])] = second
    await worker.run_once();await worker.run_once()
    assert not transport.stories and transport.effects == 1
    assert dep(store)['reason'] in {'linked_story_parent_mapping_unproven','linked_story_parent_mapping_ambiguous'}
