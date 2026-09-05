"""Genuine archived MCP/SQLite/worker integration, LOCAL assembled tree only."""
import asyncio
import importlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import timedelta
from contextlib import asynccontextmanager

import pytest

pytestmark = pytest.mark.asyncio

if os.environ.get('VIBEPUBLISH_MAX_CORE_REQUIRED') == '1':
    importlib.import_module('social_operations.worker')
else:
    pytest.importorskip('social_operations.worker', reason='Full owner core archive required', exc_type=ModuleNotFoundError)

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image
from social_operations.assets import import_image
from social_operations.storage import Store


@asynccontextmanager
async def runtime(tmp_path, server):
    origin,state = server
    store = Store(tmp_path/'ledger.sqlite')
    token = store.create_principal('fixture-tenant','fixture-owner',owner=True)
    actor = store.authenticate(token)
    bindings = {}
    for provider in ('telegram','vk','max'):
        store.add_connection(actor,provider,provider,account_type='fake')
        bindings[provider] = store.bind(actor,actor.principal_id,provider,provider,'channel-a')
    payload = io.BytesIO()
    Image.new('RGB',(4,4),(10,20,30)).save(payload,format='PNG')
    asset = import_image(store,actor,payload.getvalue(),'image/png')
    source_root = Path(__file__).resolve().parents[4]
    processes,logs = [],[]
    def launch(command):
        stream=(tmp_path/f'process-{len(processes)}.log').open('wb')
        logs.append(stream)
        proc=subprocess.Popen([sys.executable,*command],cwd=source_root,
            env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LD_LIBRARY_PATH'}} | {'PYTHONPATH':str(source_root)},
            stdout=subprocess.DEVNULL,stderr=stream,start_new_session=True)
        processes.append(proc)
        return proc
    def worker(mode):
        return launch([str(Path(__file__).with_name('core_worker.py')),str(tmp_path),origin,mode])
    # A fixture effect observer reads the marker through its own SQLite connection
    # BEFORE the independent HTTP fixture commits the MAX side effect.
    marker_checks=[]
    def observe_marker(_request):
        with store.connection() as db:
            rows=db.execute("SELECT * FROM attempts WHERE provider='max' AND dispatched=1").fetchall()
            assert len(rows)==1
            row=rows[0]
            checkpoint=json.loads(row['checkpoint'])['adapter']
            assert checkpoint['attempt']==row['id'] and checkpoint['plan']==row['plan_digest']
            assert checkpoint['driver']['target']=='channel-a'
            marker_checks.append(row['id'])
    state.before_effect=observe_marker
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    proc=launch(['-m','social_operations.cli','--db',str(store.path),'serve','--port',str(port)])
    try:
        async with httpx.AsyncClient(trust_env=False) as probe:
            async with asyncio.timeout(15):
                while True:
                    assert proc.poll() is None, (tmp_path/'process-0.log').read_text()
                    try:
                        if (await probe.get(base+'/v1/bootstrap')).status_code==401:
                            break
                    except httpx.ConnectError:
                        pass
                    await asyncio.sleep(.05)
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},trust_env=False) as http:
            async with streamable_http_client(base+'/mcp/',http_client=http) as (read,write,_):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=30)) as session:
                    await session.initialize()
                    yield store,actor,bindings,asset,session,worker,marker_checks
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL)
            await asyncio.to_thread(process.wait,5)
        for stream in logs:
            stream.close()


async def tool(session,name,args):
    result=await session.call_tool('vibepublish_'+name,args)
    assert not result.isError, result.structuredContent
    return result.structuredContent


async def status(session,receipt):
    return (await tool(session,'status',{'ids':[receipt['operation_id']]}))['receipts'][0]


def states(receipt):
    return {x['provider']:x['state'] for x in receipt['deliveries']}


async def wait_until(condition,timeout=20):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(.025)


async def worker_done(process):
    assert await asyncio.to_thread(process.wait,25)==0


def fake_effects(root):
    with sqlite3.connect(root/'remote.sqlite') as db:
        return dict(db.execute("SELECT provider,count(*) FROM calls WHERE kind='effect' GROUP BY provider"))


@pytest.mark.parametrize('scheduled',[False,True])
async def test_mcp_early_progress_durable_marker_crash_reconcile_partial_success(tmp_path,server,scheduled):
    _,state=server
    async with runtime(tmp_path,server) as (store,actor,bindings,asset,session,worker,marker_checks):
        second_payload=io.BytesIO()
        Image.new('RGB',(4,4),(30,20,10)).save(second_payload,format='PNG')
        second_asset=import_image(store,actor,second_payload.getvalue(),'image/png')
        args={'to':['telegram','vk','max'],'content':{'text':'Real core / fixture MAX'},
              'media':[{'source':{'kind':'asset','id':a}} for a in (asset,second_asset)], 'request_key':'same-operation'}
        if scheduled:
            from social_operations.domain import timestamp
            args['delivery']={'kind':'at','at':timestamp(int(time.time())+3600)}
        accepted=await tool(session,'publish',args)
        assert accepted['state']=='accepted' and state['effects']==0
        # Real long-poll starts BEFORE the first worker event exists.
        first=asyncio.create_task(tool(session,'status',{'ids':[accepted['operation_id']],
            'after_event':accepted['progress']['cursor'],'wait_seconds':10}))
        await asyncio.sleep(.1)
        assert not first.done()
        process=worker('crash')
        first_receipt=(await asyncio.wait_for(first,5))['receipts'][0]
        assert first_receipt['progress']['events'] and not first_receipt['operation_complete']
        await wait_until(lambda:(tmp_path/'max-waiting').exists())
        expected='scheduled' if scheduled else 'verified'
        async with asyncio.timeout(10):
            while True:
                partial=await status(session,accepted)
                if states(partial).get('telegram')==expected and states(partial).get('vk')==expected:
                    break
                await asyncio.sleep(.025)
        assert states(partial)['max']=='running' and not partial['operation_complete']
        assert state['effects']==0
        assert fake_effects(tmp_path)=={'telegram':1,'vk':1}
        # Both completed providers are already visible while MAX is held.
        (tmp_path/'release-max').touch()
        await wait_until(lambda:state['effects']==1 and (tmp_path/'post-submit').exists())
        assert len(marker_checks)==1 and (tmp_path/'core-marker-observed').exists()
        os.killpg(process.pid,signal.SIGKILL)
        await asyncio.to_thread(process.wait,5)
        assert process.returncode==-signal.SIGKILL
        before=await status(session,accepted)
        assert states(before)['telegram']==expected and states(before)['vk']==expected
        replay=await tool(session,'publish',args)
        assert replay['operation_id']==accepted['operation_id']
        with store.connection() as db:
            assert db.execute('SELECT count(*) FROM operations').fetchone()[0]==1
            old_fence=db.execute('SELECT fence FROM operations').fetchone()[0]
        # Failure injection: expire the genuine core claim, not a replacement
        # adapter lease or retry implementation. Dispatch marker is unchanged.
        with store.tx() as db:
            db.execute('UPDATE operations SET lease_until=0 WHERE id=?',(accepted['operation_id'],))
        recovery=worker('recover')
        await worker_done(recovery)
        done=await status(session,accepted)
        assert done['state']==expected and done['operation_complete'], done
        assert states(done)==dict.fromkeys(['telegram','vk','max'],expected)
        assert state['effects']==1 and fake_effects(tmp_path)=={'telegram':1,'vk':1}
        assert len(marker_checks)==1
        assert not (tmp_path/'profile/.vibepublish-uncertain').exists()
        with store.connection() as db:
            assert db.execute('SELECT fence FROM operations').fetchone()[0] > old_fence
            assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==3
            maxrow=db.execute("SELECT * FROM attempts WHERE provider='max'").fetchone()
            remote=json.loads(maxrow['checkpoint'])['remote']
            assert remote['native_target']=='channel-a' and len(remote['provider_media'])==2
            assert len(remote['media_hashes'])==2
            assert remote['media_check']=='provider_binding'
        assert (await tool(session,'publish',args))['operation_id']==accepted['operation_id']
        await worker_done(worker('recover'))
        assert state['effects']==1


@pytest.mark.parametrize('mode',['callback_failure','revoke','marker_crash'])
async def test_core_refusal_and_uncertain_marker_never_resubmit(tmp_path,server,mode):
    _,state=server
    async with runtime(tmp_path,server) as (store,actor,bindings,asset,session,worker,checks):
        args={'to':['max'],'content':{'text':'No unsafe retry'},'media':[{'source':{'kind':'asset','id':asset}}],'request_key':'refusal'}
        accepted=await tool(session,'publish',args)
        process=worker(mode)
        if mode=='revoke':
            await wait_until(lambda:(tmp_path/'max-waiting').exists())
            store.revoke_binding(actor,bindings['max'])
            (tmp_path/'release-max').touch()
        elif mode=='marker_crash':
            await wait_until(lambda:(tmp_path/'post-marker').exists())
            os.killpg(process.pid,signal.SIGKILL)
            await asyncio.to_thread(process.wait,5)
            with store.tx() as db:
                db.execute('UPDATE operations SET lease_until=0 WHERE id=?',(accepted['operation_id'],))
            process=worker('recover')
        await worker_done(process)
        # Read internal evidence after revocation; do NOT serve revoked content.
        with store.connection() as db:
            child=dict(db.execute("SELECT * FROM attempts WHERE provider='max'").fetchone())
            assert child['dispatched']==(1 if mode=='marker_crash' else 0)
            assert child['state']==('outcome_unknown' if mode=='marker_crash' else 'blocked')
        assert (tmp_path/'before-effect-entered').exists()
        assert state['effects']==0 and not checks
        if mode=='marker_crash':
            done=await status(session,accepted)
            assert done['state']=='outcome_unknown'
            # New explicit intent cannot bypass the profile quarantine/core lane.
            newer=await tool(session,'publish',{**args,'content':{'text':'Different operation'},'request_key':'new-key'})
            await worker_done(worker('recover'))
            assert (await status(session,newer))['state']=='blocked'
            assert state['effects']==0


async def test_core_unknown_max_preserves_verified_telegram_vk(tmp_path,server):
    _,state=server
    async with runtime(tmp_path,server) as (store,actor,bindings,asset,session,worker,checks):
        args={'to':['telegram','vk','max'],'content':{'text':'Text attribution stays unknown'},'request_key':'text-only'}
        accepted=await tool(session,'publish',args)
        await worker_done(worker('normal'))
        done=await status(session,accepted)
        assert done['state']=='outcome_unknown'
        assert states(done)=={'telegram':'verified','vk':'verified','max':'outcome_unknown'}
        assert state['effects']==1 and fake_effects(tmp_path)=={'telegram':1,'vk':1}
        assert (await tool(session,'publish',args))['operation_id']==accepted['operation_id']
        await worker_done(worker('normal'))
        assert state['effects']==1


async def test_mcp_scoped_provider_queue_pagination_and_exact_external_item(tmp_path,server):
    _,state=server
    for target,ident in [('channel-a','external-1'),('channel-a','external-2'),('channel-b','private')]:
        state['items'].append(dict(id=ident,target=target,namespace='scheduled',text=ident,
                                   media=['provider-owned'],scheduled_at='2030-01-01T00:00:00Z'))
    async with runtime(tmp_path,server) as (store,actor,bindings,asset,session,worker,checks):
        query={'kind':'scheduled','destination':'max'}
        first=await tool(session,'read',{'query':query,'limit':1})
        await worker_done(worker('normal'))
        first=await status(session,first)
        assert first['state']=='verified' and len(first['items'])==1
        assert first['items'][0]['text']=='external-1' and first['items'][0]['freshness']=='current'
        assert first['truncated'] and first['next_cursor']
        second=await tool(session,'read',{'query':query,'limit':1,'cursor':first['next_cursor']})
        await worker_done(worker('normal'))
        second=await status(session,second)
        assert second['items'][0]['text']=='external-2' and not second['truncated']
        item=await tool(session,'read',{'query':{'kind':'item','item_ref':first['items'][0]['ref']}})
        await worker_done(worker('normal'))
        item=await status(session,item)
        assert len(item['items'])==1 and item['items'][0]['text']=='external-1'
        denied=await session.call_tool('vibepublish_read',{'query':{'kind':'scheduled','destination':'not-bound'}})
        assert denied.isError
        with store.connection() as db:
            snapshots=[json.loads(r[0]) for r in db.execute('SELECT snapshot FROM facts')]
            assert all(x['native_target']=='channel-a' and not x['media_hashes'] for x in snapshots)
            assert all(x['provider_media']==['provider-owned'] for x in snapshots)
        assert state['effects']==0 and not checks
