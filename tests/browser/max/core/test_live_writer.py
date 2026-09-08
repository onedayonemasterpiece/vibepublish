"""Actual shared port + production-wired RealMaxDriver on observed replay."""
import importlib
import json
import os
import time
from dataclasses import asdict

import pytest
if os.environ.get('VIBEPUBLISH_MAX_CORE_REQUIRED')=='1':
    importlib.import_module('social_operations.worker')
else:
    pytest.importorskip('social_operations.worker',reason='Full shared core required',exc_type=ModuleNotFoundError)
from adapters.max.bridge import MaxAdapter
from adapters.port import ProviderRequest, ReadRequest
from tests.browser.max.observed.test_submit import writer, TEXT, effects
pytestmark=pytest.mark.asyncio

async def test_plain_production_bridge_retains_native_checkpoint_and_releases_after_commit(writer):
    d,page,state,h=writer
    d.live_writes=True
    adapter=MaxAdapter(d,connection_id='max')
    request=ProviderRequest('op','attempt','plan','max','max_web','VIBEPUBLISH_MAX_PROFILE',
        'destination','-101','publish','post',json.dumps({'text':TEXT}),(),None,time.time()+300)
    prepared=await adapter.prepare(request,h)
    assert prepared.capability.evidence=='max_web_dom'
    observed=await adapter.execute(prepared,h)
    assert observed.observed=='published' and len(effects(state))==1
    latest=state['checkpoints'][-1][1]
    assert latest['driver']['recovery_reference']==observed.items[0].url
    assert latest['driver']['transition']=={'clicks':1,'changed':True,'blocked':False}
    assert adapter._existing(observed.items[0])['url']==observed.items[0].url
    assert d.lane.marker.exists()
    final=json.dumps(dict(remote=asdict(observed.items[0]), original_checkpoint=latest,
        core_recovery=dict(operation_id='op',attempt_id='attempt',plan_digest='plan')))
    await adapter.finalize(request,final,h)
    assert not d.lane.marker.exists()
    await adapter.finalize(request,final,h)
    assert len(effects(state))==1

async def test_plain_delete_bridge_recovers_confirmed_removal_without_second_effect(writer):
    from dataclasses import replace
    d,page,state,h=writer
    d.live_writes=True
    state['messages']=[dict(id='owned',target='-101',text=TEXT,outgoing=True)]
    adapter=MaxAdapter(d,connection_id='max')
    existing=adapter._remote(dict(id='owned',target='-101',text=TEXT,url='https://max.ru/c/-101/owned',
        namespace='feed',media=[],scheduled_at=None,observed_at='2026-09-08T00:00:00Z'))
    request=ProviderRequest('op','attempt','plan','max','max_web','VIBEPUBLISH_MAX_PROFILE',
        'destination','-101','delete','post',json.dumps({'text':TEXT}),(),None,time.time()+300,existing=existing)
    prepared=await adapter.prepare(request,h)
    observed=await adapter.execute(prepared,h)
    assert observed.observed=='deleted' and observed.items[0].native_id=='owned'
    latest=state['checkpoints'][-1][1]
    recovered=await adapter.reconcile(request,json.dumps(latest),h)
    assert recovered.observed=='deleted' and len(effects(state))==1
    final=json.dumps(dict(remote=asdict(recovered.items[0]),original_checkpoint=latest,
        core_recovery=dict(operation_id='op',attempt_id='attempt',plan_digest='plan')))
    await adapter.finalize(request,final,h)
    assert not d.lane.marker.exists() and len(effects(state))==1

@pytest.mark.parametrize('config',[None,'not-json','{}',json.dumps(dict(profile='relative',executable='/bin/chromium',allowlist='/private/allowlist',live_writes=True)),json.dumps(dict(profile='/private/profile',executable='/bin/chromium',allowlist='/private/allowlist',live_writes=False))])
async def test_standard_factory_requires_explicit_existing_profile_config(config):
    from adapters.max.live_session import configured_adapter
    from social_operations.domain import DomainError
    with pytest.raises(DomainError,match='max profile config'):
        async with configured_adapter(connection_id='max',env={} if config is None else {'VIBEPUBLISH_MAX_PROFILE':config}):
            pytest.fail('Invalid config must not start a browser')

async def test_standard_factory_owns_session_and_exact_connection(writer,monkeypatch):
    from contextlib import asynccontextmanager
    from adapters.max import live_session
    d,page,state,h=writer
    d.live_writes=True
    calls=[]
    @asynccontextmanager
    async def session(**kwargs):
        calls.append(kwargs)
        try:yield d
        finally:calls.append('closed')
    monkeypatch.setattr(live_session,'existing_session',session)
    config=dict(profile='/private/profile',executable='/bin/chromium',allowlist='/private/allowlist',live_writes=True)
    async with live_session.configured_adapter(connection_id='only-this-connection',env={'VIBEPUBLISH_MAX_PROFILE':json.dumps(config)}) as adapter:
        assert adapter.connection_id=='only-this-connection' and adapter.driver is d and adapter.live_enabled
    assert calls[0]['explicit_live'] is True and calls[0]['live_writes'] is True and calls[-1]=='closed'


async def test_image_bridge_binds_native_downloads_and_reconciles_without_resend(writer):
    import base64
    import hashlib
    from adapters.port import Asset
    d,page,state,h=writer
    d.live_writes=True
    adapter=MaxAdapter(d,connection_id='max')
    data=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==')
    asset=Asset('asset',hashlib.sha256(data).hexdigest(),'image/png',len(data),data=data)
    request=ProviderRequest('op','attempt','plan','max','max_web','VIBEPUBLISH_MAX_PROFILE',
        'destination','-101','publish','post',json.dumps({'text':TEXT}),(asset,),None,time.time()+300)
    observed=await adapter.execute(await adapter.prepare(request,h),h)
    item=observed.items[0]
    assert item.provider_media==() and len(item.observed_media)==1
    assert item.media_hashes==(asset.sha256,) and item.media_check=='download_binding'
    latest=state['checkpoints'][-1][1]
    binding=latest['driver']['download_binding']
    assert binding['native_id']==item.native_id
    assert binding['source_hashes']==[asset.sha256]
    assert binding['observed_media']==[asdict(value) for value in item.observed_media]
    recovered=await adapter.reconcile(request,json.dumps(latest),h)
    assert recovered.items[0].observed_media==item.observed_media and len(effects(state))==1
    assert d.lane.marker.exists()
    final=json.dumps(dict(remote=asdict(recovered.items[0]),original_checkpoint=latest,
        core_recovery=dict(operation_id='op',attempt_id='attempt',plan_digest='plan')))
    await adapter.finalize(request,final,h)
    assert not d.lane.marker.exists() and len(effects(state))==1


async def test_video_bridge_downloads_exact_native_tile_not_nested_controls(writer):
    import hashlib
    from pathlib import Path
    from adapters.port import Asset
    d,page,state,h=writer
    d.live_writes=True
    adapter=MaxAdapter(d,connection_id='max')
    data=(Path(__file__).parents[1]/'observed'/'sample.mp4').read_bytes()
    asset=Asset('video-asset',hashlib.sha256(data).hexdigest(),'video/mp4',len(data),role='video',data=data)
    request=ProviderRequest('op','attempt','plan','max','max_web','VIBEPUBLISH_MAX_PROFILE',
        'destination','-101','publish','post',json.dumps({'text':TEXT}),(asset,),None,time.time()+300)
    observed=await adapter.execute(await adapter.prepare(request,h),h)
    item=observed.items[0]
    assert len(effects(state))==1 and item.provider_media==()
    assert len(item.observed_media)==1 and item.observed_media[0].mime=='video/mp4'
    assert item.media_hashes==(asset.sha256,) and item.media_check=='download_binding'
    latest=state['checkpoints'][-1][1]
    recovered=await adapter.reconcile(request,json.dumps(latest),h)
    assert recovered.items[0].observed_media==item.observed_media and len(effects(state))==1

    # Each subsequent action has a distinct operation/attempt and is admitted only
    # after the previous durable observation's finalize envelope releases its fuse.
    from dataclasses import replace
    current=request
    for index,action in enumerate(('edit','delete'),start=2):
        latest=state['checkpoints'][-1][1]
        final=json.dumps(dict(remote=asdict(item),original_checkpoint=latest,
            core_recovery=dict(operation_id=current.operation_id,attempt_id=current.attempt_id,plan_digest=current.plan_digest)))
        await adapter.finalize(current,final,h)
        assert not d.lane.marker.exists()
        state['expected_dispatch']=(f'attempt-{index}',f'plan-{index}')
        current=replace(request,operation_id=f'op-{index}',attempt_id=f'attempt-{index}',plan_digest=f'plan-{index}',
            action=action,content_json=json.dumps({'text':TEXT+' edited'}),assets=(),existing=item)
        result=await adapter.execute(await adapter.prepare(current,h),h)
        assert result.items[0].native_id==item.native_id
        assert result.items[0].observed_media==item.observed_media
        item=result.items[0]
    assert len(effects(state))==3 and not state['messages']
    latest=state['checkpoints'][-1][1]
    final=json.dumps(dict(remote=asdict(item),original_checkpoint=latest,
        core_recovery=dict(operation_id=current.operation_id,attempt_id=current.attempt_id,plan_digest=current.plan_digest)))
    await adapter.finalize(current,final,h)
    assert not d.lane.marker.exists()


@pytest.mark.parametrize('raster',[False,True])
async def test_rich_production_bridge_exact_entities_and_plain_edit(writer,raster):
    from dataclasses import replace
    from social_operations.rich_text import compile_content, max_content, normalized_entities
    d,page,state,h=writer
    d.live_writes=True
    adapter=MaxAdapter(d,connection_id='max')
    if raster:await page.add_init_script('window.REPLAY_RASTER_EMOJI=true')
    content=compile_content({'paragraphs':[[{'kind':'text','text':'😀 Bold','style':'bold'},
        {'kind':'text','text':' italic','style':'italic'},{'kind':'text','text':' '},
        {'kind':'link','label':'Exact link','url':'https://example.com/owned'}]]},lambda _:None,provider='max',max_native=True)
    request=ProviderRequest('op','attempt','plan','max','max_web','VIBEPUBLISH_MAX_PROFILE',
        'destination','-101','publish','post',json.dumps(content),(),None,time.time()+300)
    result=await adapter.execute(await adapter.prepare(request,h),h)
    item=result.items[0]
    assert normalized_entities(item.text,json.loads(item.entities_json))==max_content(request.content_json,4000)[1]
    assert len(effects(state))==1
    latest=state['checkpoints'][-1][1]
    await adapter.finalize(request,json.dumps(dict(remote=asdict(item),original_checkpoint=latest,
        core_recovery=dict(operation_id='op',attempt_id='attempt',plan_digest='plan'))),h)
    state['expected_dispatch']=('attempt-2','plan-2')
    edit=replace(request,operation_id='op-2',attempt_id='attempt-2',plan_digest='plan-2',action='edit',
        content_json=json.dumps({'text':'Edited plain text'}),existing=item)
    result=await adapter.execute(await adapter.prepare(edit,h),h)
    assert result.items[0].native_id==item.native_id and result.items[0].entities_json=='[]'
    assert len(effects(state))==2
