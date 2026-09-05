from __future__ import annotations
import asyncio
import hashlib
import io
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from adapters.fake import FakeProvider
from adapters.imagegen import FakeImagegen, ImagegenArtifact
from social_operations.assets import import_image
from social_operations.compositor import render, FORMATS
from social_operations.domain import DomainError, canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.visual_artifacts import verified_artifact
from social_operations.worker import Worker
from tests.providers.test_native_adapters import asset, NOW


@pytest.fixture
def runtime(tmp_path):
    clock = [float(NOW)]
    store = Store(tmp_path/'ledger.sqlite', clock=lambda: clock[0])
    token = store.create_principal('tenant', 'owner', owner=True)
    actor = store.authenticate(token)
    store.add_connection(actor, 'conn', 'telegram', account_type='fake', shared=True)
    binding = store.bind(actor, actor.principal_id, 'announcements', 'conn', 'fixture-target')
    provider = FakeProvider(tmp_path/'remote.sqlite', 'telegram', clock=store.clock)
    executor = FakeImagegen(tmp_path/'executor')
    app = Application(store)
    worker = Worker(store, {'telegram': provider}, imagegen=executor)
    return store, actor, app, worker, executor, provider, clock, binding, token


async def call(app, actor, name, args):
    result = await app.call(actor, 'vibepublish_'+name, args)
    assert 'operation_id' in result, result
    return result


def select_command(result, index=0):
    candidate = result['candidates'][index]
    return {'kind':'select', 'job_id':result['visual_job_id'], 'candidate_id':candidate['id'],
            'expected_revision':result['visual_revision'], 'token':candidate['selection_token']}


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['generate','tune','compose'])
async def test_shared_standalone_service_budget_lineage_and_private_selection(runtime, mode):
    store, actor, app, worker, executor, provider, *_ = runtime
    sources = [import_image(store, actor, asset(i).data, 'image/png') for i in [1,2]]
    command = {'kind':mode,'brief':'Offline fixture illustration','copy':{'title':'Сентябрь рядом'},'formats':['post_4_5','story_9_16']}
    if mode == 'tune': command['source'] = {'source':{'kind':'asset','id':sources[0]}}
    if mode == 'compose': command['sources'] = [{'source':{'kind':'asset','id':ident}} for ident in sources]
    receipt = await call(app, actor, 'visual', {'command':command,'request_key':'create'})
    assert receipt['state'] == 'accepted' and executor.calls == [] and provider.count('effect') == 0
    await worker.run_once()
    ready = store.receipt(actor, receipt['visual_job_id'])
    assert ready['state'] == 'needs_selection', ready
    assert [(c['width'],c['height']) for c in ready['candidates']] == list(FORMATS.values())
    assert ready['executor'] == {'requested_route':'gpt-5.6-luna','actual_executor':'fake-imagegen-v1','actual_model':None,'fixture':True}
    assert executor.calls[0].mode == mode
    assert len(executor.calls[0].sources) == {'generate':0,'tune':1,'compose':2}[mode]
    assert executor.calls[0].candidate_budget == 1  # 2 final derivatives / 2 formats.
    choice = select_command(ready)
    selected = await call(app, actor, 'visual', {'command':choice, 'request_key':'choose'})
    assert selected['operation_id'] == receipt['operation_id'] and selected['state'] == 'verified'
    assert selected['selected_sha256'] == ready['candidates'][0]['sha256']
    assert not await worker.run_once() and provider.count('effect') == 0
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM publications').fetchone()[0] == 0
        candidates = db.execute('SELECT * FROM visual_candidates').fetchall()
        assert len(candidates) == 2
        for candidate in candidates:
            data, _mime, sha = app.read_asset(actor, candidate['asset_ref'])
            assert hashlib.sha256(data).hexdigest() == sha == candidate['sha256']
            assert json.loads(candidate['recipe'])['copy'] == command['copy']
            assert json.loads(candidate['provenance'])['consent']['shared_training'] is False
        with pytest.raises(sqlite3.IntegrityError, match='immutable visual candidate'):
            db.execute("UPDATE visual_candidates SET sha256='changed'")
        with pytest.raises(sqlite3.IntegrityError, match='immutable visual input'):
            db.execute("UPDATE visual_jobs SET spec='{}'")
        with pytest.raises(sqlite3.IntegrityError, match='immutable asset'):
            db.execute("UPDATE assets SET bytes=X'00'")
    assert (await call(app, actor, 'visual', {'command':choice,'request_key':'choose'}))['operation_id'] == receipt['operation_id']
    different = await app.call(actor, 'vibepublish_visual', {'command':select_command(ready,1),'request_key':'choose-other'})
    assert different['error']['code'] == 'visual_selection_conflict'


@pytest.mark.asyncio
@pytest.mark.parametrize('preview', [False, True])
async def test_inline_selected_first_not_sources_resume_exactly_once_and_preview_needs_approval(runtime, preview):
    store, actor, app, worker, executor, provider, *_ = runtime
    source = import_image(store, actor, asset(1).data, 'image/png')
    explicit = import_image(store, actor, asset(2).data, 'image/png')
    first = await call(app, actor, 'publish', {'to':['announcements'], 'content':{'text':'Exact caption'},
        'media':[{'source':{'kind':'asset','id':explicit}}], 'mode':'preview' if preview else 'execute',
        'visual':{'kind':'tune','source':{'source':{'kind':'asset','id':source}},'brief':'Fixture only'}, 'request_key':'parent'})
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
    await worker.run_once()
    ready = store.receipt(actor, first['operation_id'])
    assert ready['state'] == 'needs_selection' and provider.count('effect') == 0
    edit = await app.call(actor,'vibepublish_publication_update',{'publication_id':first['resource_id'],'expected_revision':1,'change':{'kind':'edit','content':{'text':'Changed'}}})
    assert edit['error']['code'] == 'visual_selection_required'
    command = select_command(ready)
    chosen = await call(app, actor, 'visual', {'command':command,'request_key':'choose'})
    assert chosen['operation_id'] == first['operation_id'] and chosen['revision'] == 2 and chosen['state'] == 'accepted'
    with store.connection() as db:
        plan = json.loads(db.execute('SELECT plan FROM attempts').fetchone()[0])
        assert [a['ref'] for a in plan['assets']] == [chosen['selected_asset_ref'],explicit]
        assert source not in [a['ref'] for a in plan['assets']]
        assert len(db.execute('SELECT * FROM publications').fetchall()) == 1
    await worker.run_once()
    done = store.receipt(actor, first['operation_id'])
    assert done['state'] == ('needs_approval' if preview else 'verified'), done
    if preview:
        assert provider.count('effect') == 0
        assert done['selected_sha256'] == chosen['selected_sha256']
        approved = await call(app, actor, 'publication_update', {'publication_id':first['resource_id'], 'expected_revision':2,
            'change':{'kind':'approve','token':done['review_token']}, 'request_key':'approve'})
        await worker.run_once()
        assert store.receipt(actor, approved['operation_id'])['state'] == 'verified'
    assert provider.count('effect') == 1
    await call(app, actor, 'visual', {'command':command,'request_key':'choose-again'})
    assert not await worker.run_once() and provider.count('effect') == 1


@pytest.mark.asyncio
async def test_automatic_fixture_selection_still_respects_preview(runtime):
    store, actor, app, worker, executor, provider, *_ = runtime
    first = await call(app, actor, 'publish', {'to':['announcements'], 'mode':'preview',
        'visual':{'kind':'generate','brief':'Offline fixture','selection':'automatic'}})
    await worker.run_once()
    selected = store.receipt(actor, first['operation_id'])
    assert selected['state'] == 'accepted' and selected['selected_sha256']
    await worker.run_once()
    assert store.receipt(actor, first['operation_id'])['state'] == 'needs_approval'
    assert provider.count('effect') == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['schedule','routing','revision','revocation'])
async def test_selection_rechecks_frozen_parent_time_routing_revision_and_binding(runtime, mutation):
    store, actor, app, worker, executor, provider, clock, binding, token = runtime
    first = await call(app, actor, 'publish', {'to':['announcements'], 'visual':{'kind':'generate','brief':'Fixture'},
        'delivery':{'kind':'at','at':timestamp(clock[0]+3600)}})
    await worker.run_once();ready=store.receipt(actor,first['operation_id'])
    if mutation == 'schedule': clock[0] += 3570
    elif mutation == 'routing':
        await call(app, actor, 'destinations', {'command':{'kind':'profile_update','alias':'announcements','expected_revision':0,'profile':{'notes':'Changed'}}})
    elif mutation == 'revision':
        with store.tx() as db: db.execute('UPDATE publications SET revision=2 WHERE id=?',(first['resource_id'],))
    else:
        store.revoke_binding(actor,binding);actor=store.authenticate(token)
    result = await app.call(actor,'vibepublish_visual',{'command':select_command(ready)})
    assert result['error']['code'] == {'schedule':'native_lead_time','routing':'routing_stale','revision':'visual_parent_revision_conflict','revocation':'access_revoked'}[mutation]
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
    assert provider.count('effect') == 0


@pytest.mark.asyncio
async def test_lost_executor_response_is_found_by_key_without_second_submit(runtime):
    store, actor, app, worker, executor, provider, *_ = runtime
    executor.lost_response = True
    first=await call(app,actor,'visual',{'command':{'kind':'generate','brief':'Fixture'}})
    await worker.run_once()
    assert store.receipt(actor,first['operation_id'])['state']=='needs_selection'
    assert len(executor.calls)==1
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_unknown_executor_keeps_parent_unsent_without_blind_retry(runtime):
    store, actor, app, worker, executor, provider, *_ = runtime
    class Unknown(FakeImagegen):
        async def submit(self, request):
            self.calls.append(request);raise OSError('lost')
        async def find(self, key): return None
    executor=Unknown(executor.artifact_root);worker.imagegen=executor
    first=await call(app,actor,'publish',{'to':['announcements'],'visual':{'kind':'generate','brief':'Fixture'}})
    await worker.run_once()
    result=store.receipt(actor,first['operation_id'])
    assert result['state']=='outcome_unknown' and result['error']['code']=='imagegen_submit_outcome_unknown'
    assert not await worker.run_once() and len(executor.calls)==1 and provider.count('effect')==0


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['unwired','failed','overflow','quota'])
async def test_visual_failures_never_create_social_attempts(runtime, scenario):
    store, actor, app, worker, executor, provider, *_ = runtime
    spec={'kind':'generate','brief':'Fixture'}
    if scenario=='unwired': worker.imagegen=None
    elif scenario=='failed': executor.fail=True
    elif scenario=='overflow': spec['copy']={'title':'Длинный заголовок '*8,'body':'Текст '*200}
    else:
        with store.tx() as db: db.execute('UPDATE tenants SET storage_limit=100')
    first=await call(app,actor,'publish',{'to':['announcements'],'visual':spec})
    await worker.run_once()
    result=store.receipt(actor,first['operation_id'])
    assert result['state']=='blocked',result
    assert result['error']['code']=={'unwired':'imagegen_not_configured','failed':'imagegen_failed','overflow':'visual_text_overflow','quota':'storage_quota_exceeded'}[scenario]
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM visual_candidates').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0]==0
    assert provider.count('effect')==0


@pytest.mark.asyncio
async def test_cross_principal_visual_asset_and_token_denied(runtime):
    store, actor, app, worker, executor, provider, *_ = runtime
    first=await call(app,actor,'visual',{'command':{'kind':'generate','brief':'Fixture'}})
    await worker.run_once();ready=store.receipt(actor,first['operation_id'])
    other=store.authenticate(store.create_principal('other','partner'))
    result=await app.call(other,'vibepublish_visual',{'command':select_command(ready)})
    assert result['error']['code']=='visual_not_available'
    with pytest.raises(DomainError): app.read_asset(other,ready['candidates'][0]['asset_ref'])
    result=await app.call(other,'vibepublish_status',{'ids':[first['visual_job_id']]})
    assert result['error']['code']=='not_found'
    command=select_command(ready);command['candidate_id']=ready['candidates'][1]['id']
    result=await app.call(actor,'vibepublish_visual',{'command':command})
    assert result['error']['code']=='visual_selection_token_invalid'


@pytest.mark.asyncio
async def test_feedback_is_private_append_only_and_never_changes_selected_bytes(runtime):
    store, actor, app, worker, executor, provider, *_=runtime
    first=await call(app,actor,'visual',{'command':{'kind':'generate','brief':'Fixture'}})
    await worker.run_once();ready=store.receipt(actor,first['operation_id'])
    chosen=await call(app,actor,'visual',{'command':select_command(ready)})
    for rating in ['accepted','rejected']:
        await call(app,actor,'visual',{'command':{'kind':'feedback','job_id':ready['visual_job_id'],'candidate_id':ready['candidates'][0]['id'],'rating':rating,'reason':'Private fixture preference'},'request_key':rating})
    assert app.read_asset(actor,chosen['selected_asset_ref'])[2]==chosen['selected_sha256']
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM visual_feedback WHERE shared_training=0').fetchone()[0]==2


@pytest.mark.asyncio
async def test_budget_and_visual_scope_fail_before_cost_reservation(runtime):
    store, actor, app, worker, executor, provider, *_=runtime
    denied=await app.call(actor,'vibepublish_visual',{'command':{'kind':'generate','brief':'Fixture','candidates':1,'formats':['post_4_5','story_9_16']}})
    assert denied['error']['code']=='visual_budget_too_small_for_formats'
    partner=store.authenticate(store.create_principal('tenant','partner',scopes={'publish','status'}))
    store.bind(actor,'partner','announcements','conn','fixture-target')
    tool=next(t for t in app.tools(partner) if t['name']=='vibepublish_publish')
    assert 'visual' not in tool['inputSchema']['properties']
    denied=await app.call(partner,'vibepublish_publish',{'to':['announcements'],'visual':{'kind':'generate','brief':'No scope'}})
    assert denied['error']['code']=='invalid_input'
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0]==0


@pytest.mark.parametrize('format', list(FORMATS))
def test_deterministic_svg_exact_copy_glyphs_safe_regions_and_reflow(format):
    text={'title':'Лекция о выборе','subtitle':'Почему мы выбираем','date_line':'6 сентября, 12:00','location_line':'Калининград'}
    a=render(asset().data,text,format);b=render(asset().data,text,format)
    assert a.png==b.png and a.svg==b.svg
    recipe=json.loads(a.recipe_json)
    assert recipe['copy']==text and recipe['font_sha256']
    assert b'<path ' in a.svg and b'<script' not in a.svg and b'file:' not in a.svg
    for line in recipe['lines']:
        assert line['x']>=72 and line['x']+line['width']<=a.width-72
        assert line['baseline']+line['font_size']*.25<=a.height-88
    with Image.open(io.BytesIO(a.png)) as image: assert image.size==FORMATS[format]


@pytest.mark.parametrize('mutation', ['path','symlink','hash','mime','dimensions','size'])
def test_actual_artifact_bytes_not_manifest_assertions(tmp_path,mutation):
    data=asset().data;path=tmp_path/'output.png';path.write_bytes(data)
    manifest=ImagegenArtifact('output.png',hashlib.sha256(data).hexdigest(),'image/png',4,4,len(data))
    if mutation=='path':manifest=replace(manifest,ref='../output.png')
    elif mutation=='symlink':path.unlink();path.symlink_to(tmp_path/'outside.png');(tmp_path/'outside.png').write_bytes(data)
    elif mutation=='hash':manifest=replace(manifest,sha256='0'*64)
    elif mutation=='mime':manifest=replace(manifest,mime='image/jpeg')
    elif mutation=='dimensions':manifest=replace(manifest,width=999)
    else:manifest=replace(manifest,size=len(data)+1)
    with pytest.raises(DomainError): verified_artifact(tmp_path,manifest)


@pytest.mark.parametrize('attack', ['job_directory_symlink', 'hardlink'])
def test_artifact_confines_job_directory_and_rejects_shared_inode(tmp_path, attack):
    import os
    raw = asset(1).data
    outside = tmp_path/'outside'
    outside.mkdir()
    source = outside/'art.png'
    source.write_bytes(raw)
    root = tmp_path/'job'
    if attack == 'job_directory_symlink':
        root.symlink_to(outside, target_is_directory=True)
    else:
        root.mkdir()
        os.link(source, root/'art.png')
    with Image.open(io.BytesIO(raw)) as image:
        width, height = image.size
    manifest = ImagegenArtifact('art.png', hashlib.sha256(raw).hexdigest(), 'image/png', width, height, len(raw))
    with pytest.raises(DomainError, match='available|size'):
        verified_artifact(root, manifest)


@pytest.mark.asyncio
async def test_unreviewed_nonfixture_automatic_request_remains_human_gated(runtime):
    store, actor, app, worker, executor, provider, *_ = runtime
    inspect = executor.inspect
    async def observed(ref):
        result = await inspect(ref)
        return replace(result, fixture=False, actual_executor='scripted-metadata-only', actual_model=None)
    executor.inspect = observed
    first = await call(app, actor, 'visual', {'command':{'kind':'generate','brief':'Offline metadata fixture','selection':'automatic'}})
    await worker.run_once()
    ready = store.receipt(actor, first['operation_id'])
    assert ready['state'] == 'needs_selection' and ready['candidates'][0]['requires_review'] is True
    assert 'selected_asset_ref' not in ready and ready['executor']['actual_model'] is None
    assert provider.count('effect') == 0 and len(executor.calls) == 1
