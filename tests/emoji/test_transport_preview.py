from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from datetime import timedelta
import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from playwright.async_api import async_playwright
from social_operations.emoji_preview import render_catalog
from .test_runtime import runtime, register
from .fixtures import PAIR


@pytest.mark.asyncio
@pytest.mark.parametrize('width,height',[(1440,900),(390,844)])
async def test_E12_browser_visual_selection_repeat_order_no_horizontal_overflow(runtime,tmp_path,width,height):
    catalog=await register(runtime)
    markup,_=render_catalog(runtime[2],runtime[1],catalog)
    errors=[]
    async with async_playwright() as p:
        executable=os.environ.get('VIBEPUBLISH_TEST_CHROMIUM') or shutil.which('chromium') or p.chromium.executable_path
        browser=await p.chromium.launch(executable_path=executable,headless=True,args=['--no-sandbox'])
        try:
            page=await browser.new_page(viewport={'width':width,'height':height})
            await page.route('**/*',lambda r:r.abort())
            page.on('pageerror',lambda e:errors.append(str(e)))
            await page.set_content(markup,wait_until='load')
            assert await page.locator('.cell img').evaluate_all('(items)=>items.every(i=>i.complete && i.naturalWidth>0)')
            for n in [2,3,2]:
                await page.get_by_role('button',name=f'Добавить эмодзи {n}',exact=True).click()
            await page.locator('#fallback').fill('Третьяковская галерея')
            command=json.loads(await page.locator('#command').inner_text())['command']
            assert command['cells']==[2,3,2]
            assert await page.locator('#chain img').count()==3
            assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            root=Path(os.environ.get('VIBEPUBLISH_TEST_EVIDENCE',tmp_path))
            root.mkdir(parents=True,exist_ok=True)
            await page.screenshot(path=str(root/f'emoji-fixture-{width}x{height}.png'),full_page=True)
            (root/f'emoji-browser-{width}.json').write_text(json.dumps({'viewport':[width,height],
                'browser_version':browser.version,'selection':command['cells'],'fixture_media':True,
                'page_errors':errors,'horizontal_overflow':False},indent=2))
            await page.locator('#clear').click()
            assert json.loads(await page.locator('#command').inner_text())['command']['cells']==[]
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_E12_actual_ClientSession_catalog_choice_and_native_worker(runtime,tmp_path):
    # Separate real MCP HTTP server process, real ClientSession, same durable DB.
    # Provider is a scripted MTProto client, NOT a mocked ProviderAdapter/MCP reply.
    store,actor,app,worker,client,_vk,token=runtime
    store.clock=time.time
    for adapter in worker.adapters.values(): adapter.clock=time.time
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    with (tmp_path/'server.log').open('wb') as log:
        process=subprocess.Popen([sys.executable,'-m','social_operations.cli','--db',str(store.path),'serve','--port',str(port)],stdout=log,stderr=log)
        try:
            async with httpx.AsyncClient(trust_env=False,headers={'Authorization':'Bearer '+token}) as http:
                for _ in range(150):
                    assert process.poll() is None,(tmp_path/'server.log').read_text()
                    try:
                        if (await http.get(base+'/v1/bootstrap')).status_code==200: break
                    except httpx.ConnectError: pass
                    await asyncio.sleep(.03)
                else: pytest.fail('MCP fixture did not start')
                async with streamable_http_client(base+'/mcp/',http_client=http) as (read,write,_):
                    async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=15)) as session:
                        await session.initialize()
                        assert len((await session.list_tools()).tools)==8
                        async def tool(name,args):
                            r=(await session.call_tool('vibepublish_'+name,args)).structuredContent
                            assert r and 'error' not in r,r
                            return r
                        boot=await tool('get_started',{'section':'emoji'})
                        assert boot['schema_version']=='1.5.0-runtime'
                        r=await tool('destinations',{'command':{'kind':'emoji_set_register','destination':'telegram','url':'https://t.me/addemoji/Example','expected_revision':0}})
                        assert r['state']=='accepted' and not client.calls
                        await worker.run_once()
                        status=await tool('status',{'ids':[r['operation_id']]})
                        c=status['receipts'][0]['emoji_catalog']
                        resource=await session.read_resource('vibepublish://assets/'+c['sheets'][0]['preview_ref'])
                        assert resource.contents[0].mimeType=='image/png'
                        chosen=await tool('destinations',{'command':{'kind':'emoji_alias_select','catalog_ref':c['catalog_ref'],'catalog_revision':c['revision'],
                            'selection_token':c['selection_token'],'cells':[2,3],'alias':'tretyakov','expected_revision':0,'fallback':'Третьяковская галерея'}})
                        assert [p['document_id'] for p in chosen['emoji_alias']['parts']]==PAIR
                        published=await tool('publish',{'to':['telegram'],'content':{'paragraphs':[[{'kind':'emoji','alias':'tretyakov'}]]}})
                        await worker.run_once()
                        result=await tool('status',{'ids':[published['operation_id']]})
                        assert result['receipts'][0]['state']=='verified',result
                        assert client.effects==1
                        html=await http.get(base+'/v1/emoji/catalogs/'+c['catalog_ref'])
                        assert html.status_code==200 and html.headers['cache-control']=='no-store'
        finally:
            process.terminate()
            try: await asyncio.to_thread(process.wait,5)
            except subprocess.TimeoutExpired: process.kill();process.wait()
