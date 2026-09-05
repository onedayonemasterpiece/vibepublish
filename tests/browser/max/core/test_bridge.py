"""Actual port tests. Explicitly skipped in remote seed-only MAX CI."""
import importlib
import json
import os
import time
from dataclasses import replace

import pytest

pytestmark = pytest.mark.asyncio

if os.environ.get('VIBEPUBLISH_MAX_CORE_REQUIRED') == '1':
    importlib.import_module('social_operations.worker')
else:
    pytest.importorskip('social_operations.worker', reason='Full owner core archive required', exc_type=ModuleNotFoundError)

from adapters.port import Asset, Hooks, Observation, ProviderRequest, ReadRequest
from social_operations.domain import DomainError, OutcomeUnknown
MaxAdapter = importlib.import_module('adapters.max.bridge').MaxAdapter


def request(**values):
    r = ProviderRequest('op','attempt','digest','max','fake','','destination','channel-a',
                        'publish','post',json.dumps({'text':'fixture text'}),(),None,time.time()+300)
    return replace(r, **values)


def hooks():
    async def noop(*args):
        pass
    return Hooks(noop, noop, noop)


async def test_real_port_media_binding_and_checkpoint_recovery(browser_driver):
    driver, state, _ = browser_driver
    adapter = MaxAdapter(driver, connection_id='max')
    import hashlib
    data = b'fixture image bytes'
    asset = Asset('owned',hashlib.sha256(data).hexdigest(),'image/png',len(data),data=data)
    r = request(assets=(asset,))
    checkpoints = []
    async def checkpoint(transition, value):
        checkpoints.append(json.dumps({'transition':transition,'adapter':json.loads(value)}))
    h = replace(hooks(), checkpoint=checkpoint)
    prepared = await adapter.prepare(r,h)
    assert prepared.request is r and prepared.capability.evidence == 'offline_fixture'
    observed = await adapter.execute(prepared,h)
    assert isinstance(observed,Observation) and observed.observed == 'published'
    remote = observed.items[0]
    assert remote.namespace == 'published' and remote.native_target == 'channel-a'
    assert remote.media_hashes == (asset.sha256,) and remote.provider_media
    assert remote.media_check == 'provider_binding' and remote.url is None
    again = await adapter.reconcile(replace(r,deadline=0),checkpoints[-1],h)
    assert again.items[0].native_id == remote.native_id and state['effects'] == 1
    with pytest.raises(OutcomeUnknown):
        await adapter.reconcile(replace(r,attempt_id='different'),checkpoints[-1],h)
    with pytest.raises(DomainError):
        await adapter.execute(replace(prepared,request=replace(r,plan_digest='changed')),h)
    assert state['effects'] == 1


@pytest.mark.parametrize('changes', [
    {'connection_id':'wrong'}, {'native_target':'channel-b'}, {'account_type':'live'},
    {'secret_ref':'eventsbot:forbidden'}, {'action':'forward'}, {'surface':'story'},
    {'content_json':'{"text":"fixture","entities":[{"type":"custom_emoji"}]}'},
    {'content_json':'{"text":"fixture","format":"markdown"}'}, {'deadline':0},
])
async def test_unsupported_or_unbound_never_dispatches(browser_driver, changes):
    driver,state,_ = browser_driver
    a = MaxAdapter(driver,connection_id='max')
    r = request(**changes)
    assert (await a.inspect(r)).status != 'supported'
    with pytest.raises(DomainError):
        await a.prepare(r,hooks())
    assert state['effects'] == 0


async def test_real_port_scoped_live_queue_cursor_and_external_items(browser_driver):
    driver,state,_ = browser_driver
    a = MaxAdapter(driver,connection_id='max')
    for i in range(3):
        state['items'].append(dict(id=str(i),target='channel-a',namespace='scheduled',text='external editor',media=['provider-image'],scheduled_at='2030-01-01T00:00:00Z'))
    r = ReadRequest('max','channel-a','scheduled',limit=2)
    first = await a.read(r,hooks())
    assert len(first.items)==2 and first.cursor
    assert first.items[0].media_hashes == () and first.items[0].provider_media == ('provider-image',)
    assert len((await a.read(replace(r,cursor=first.cursor),hooks())).items)==1
    with pytest.raises(DomainError):
        await a.read(replace(r,cursor=first.cursor,kind='feed'),hooks())
    with pytest.raises(DomainError):
        await a.read(replace(r,native_target='channel-b'),hooks())
    state['items'][0]['text']='manual edit'
    with pytest.raises(DomainError,match='max cursor changed'):
        await a.read(replace(r,cursor=first.cursor),hooks())
