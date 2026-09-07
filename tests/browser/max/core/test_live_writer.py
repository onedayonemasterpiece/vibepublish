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
