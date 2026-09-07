"""Actual MCP SDK client/server over TCP, HTTP parity and separate worker process."""
from __future__ import annotations
import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from social_operations.storage import Store


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root/'ledger.sqlite')
        self.token = self.store.create_principal('tenant', 'owner', owner=True)
        self.actor = self.store.authenticate(self.token)
        self.store.add_connection(self.actor, 'conn', 'telegram', account_type='fake')
        self.store.bind(self.actor, 'owner', 'telegram', 'conn', 'fixture_target')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.base = 'http://127.0.0.1:'+str(port)
        self.server_log = (self.root/'server.log').open('wb')
        self.process = subprocess.Popen([sys.executable,'-m','social_operations.cli','--db',str(self.store.path),'serve','--port',str(port)],
                                        stdout=subprocess.DEVNULL,stderr=self.server_log)
        self.addAsyncCleanup(self.cleanup_server)
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(100):
                if self.process.poll() is not None:
                    self.fail((self.root/'server.log').read_text())
                try:
                    if (await client.get(self.base+'/v1/bootstrap')).status_code==401:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(.03)
            else:
                self.fail('Local server did not start')

    async def cleanup_server(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait,3)
            except subprocess.TimeoutExpired:
                self.process.kill();self.process.wait()
        self.server_log.close()
        self.temp.cleanup()

    async def run_worker(self, *, imagegen=False):
        result = await asyncio.to_thread(subprocess.run, [sys.executable,'-m','social_operations.cli','--db',str(self.store.path),
                    'worker','--once','--fake-remote',str(self.root/'remote.sqlite')]+(['--fake-imagegen',str(self.root/'imagegen')] if imagegen else []), capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr.decode())

    async def test_actual_sdk_eight_tools_skill_resource_prompt_and_reconnect(self):
        progress = []
        async def on_progress(value,total,message):
            progress.append(value)
        headers={'Authorization':'Bearer '+self.token}
        async with httpx.AsyncClient(headers=headers,trust_env=False) as http:
            async with streamable_http_client(self.base+'/mcp/',http_client=http) as (read,write,_):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=15)) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.protocolVersion,'2025-11-25')
                    tools = await session.list_tools()
                    self.assertEqual(len(tools.tools),8)
                    boot = (await session.call_tool('vibepublish_get_started',{'section':'all'})).structuredContent
                    self.assertIn('skill_sha256',boot)
                    self.assertTrue(boot['skill'])
                    resources = await session.list_resources()
                    skill = await session.read_resource(resources.resources[0].uri)
                    self.assertEqual(skill.contents[0].text,boot['skill'])
                    prompt = await session.get_prompt('vibepublish')
                    self.assertEqual(prompt.messages[0].content.text,boot['skill'])
                    accepted = (await session.call_tool('vibepublish_publish',{'to':['telegram'],'content':{'text':'MCP fixture'},'request_key':'mcp'},progress_callback=on_progress)).structuredContent
                    self.assertEqual(accepted['state'],'accepted')
            # The MCP connection is now gone; the durable business command must survive.
            await self.run_worker()
            async with streamable_http_client(self.base+'/mcp/',http_client=http) as (read,write,_):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    status = (await session.call_tool('vibepublish_status',{'ids':[accepted['operation_id']],'after_event':accepted['progress']['cursor']})).structuredContent
                    self.assertEqual(status['receipts'][0]['state'],'verified')
                    self.assertTrue(status['receipts'][0]['progress']['events'])
                    # Portable journal polling works without progress notifications.
                    self.assertEqual(progress,[])

    async def test_original_terminal_recovery_through_sdk_and_separate_workers(self):
        # Deliberately lose the receipt after the provider committed one effect.
        script = """
import asyncio, sys
from adapters.fake import FakeProvider
from social_operations.domain import OutcomeUnknown
from social_operations.storage import Store
from social_operations.worker import Worker
class LostReceipt(FakeProvider):
    async def execute(self, prepared, hooks):
        await super().execute(prepared, hooks)
        raise OutcomeUnknown('receipt_lost')
asyncio.run(Worker(Store(sys.argv[1]), {'telegram': LostReceipt(sys.argv[2], 'telegram')}).run_once())
"""
        headers = {'Authorization': 'Bearer '+self.token}
        async with httpx.AsyncClient(headers=headers, trust_env=False) as http:
            async with streamable_http_client(self.base+'/mcp/', http_client=http) as (read, write, _):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    original = (await session.call_tool('vibepublish_publish', {'to': ['telegram'], 'content': {'text': 'Recovery SDK'}, 'request_key': 'original'})).structuredContent
                    run = await asyncio.to_thread(subprocess.run, [sys.executable, '-c', script, str(self.store.path), str(self.root/'remote.sqlite')], capture_output=True, timeout=15)
                    self.assertEqual(run.returncode, 0, run.stderr.decode())
                    status = (await session.call_tool('vibepublish_status', {'ids': [original['operation_id']]})).structuredContent['receipts'][0]
                    self.assertEqual(status['state'], 'outcome_unknown')
                    args = {'publication_id': original['resource_id'], 'expected_revision': 1,
                            'change': {'kind': 'reconcile', 'operation_id': original['operation_id']}, 'request_key': 'recovery'}
                    admitted = (await session.call_tool('vibepublish_publication_update', args)).structuredContent
                    self.assertEqual(admitted['operation_id'], original['operation_id'])
                    self.assertFalse(admitted['operation_complete'])
            # Disconnect/restart both the session and worker before recovery.
            await self.run_worker()
            async with streamable_http_client(self.base+'/mcp/', http_client=http) as (read, write, _):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    result = (await session.call_tool('vibepublish_publication_update', args)).structuredContent
                    self.assertEqual(result['state'], 'verified', result)
                    self.assertEqual(result['operation_id'], original['operation_id'])
                    self.assertTrue(result['operation_complete'])
                    self.assertNotIn('error', result)
        from adapters.fake import FakeProvider
        remote = FakeProvider(self.root/'remote.sqlite', 'telegram')
        self.assertEqual(remote.count('effect'), 1)
        self.assertEqual(remote.count('execute'), 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM operations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT finalize_state FROM attempt_recovery').fetchone()[0], 'done')

    async def test_sdk_safe_retry_of_predispatch_edit_preserves_original_operation(self):
        script = """
import asyncio, sys
from adapters.fake import FakeProvider
from social_operations.domain import DomainError
from social_operations.storage import Store
from social_operations.worker import Worker
class BlockedEdit(FakeProvider):
    async def execute(self, prepared, hooks):
        raise DomainError('observed_heading_changed')
asyncio.run(Worker(Store(sys.argv[1]), {'telegram': BlockedEdit(sys.argv[2], 'telegram')}).run_once())
"""
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+self.token}, trust_env=False) as http:
            async with streamable_http_client(self.base+'/mcp/',http_client=http) as (read,write,_):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    original=(await session.call_tool('vibepublish_publish',{'to':['telegram'],'content':{'text':'Before edit'},'request_key':'retry-original'})).structuredContent
                    await self.run_worker()
                    edit=(await session.call_tool('vibepublish_publication_update',{'publication_id':original['resource_id'],'expected_revision':1,'change':{'kind':'edit','content':{'text':'After edit'}},'request_key':'blocked-edit'})).structuredContent
                    run=await asyncio.to_thread(subprocess.run,[sys.executable,'-c',script,str(self.store.path),str(self.root/'remote.sqlite')],capture_output=True,timeout=15)
                    self.assertEqual(run.returncode,0,run.stderr.decode())
                    blocked=(await session.call_tool('vibepublish_status',{'ids':[edit['operation_id']]})).structuredContent['receipts'][0]
                    self.assertEqual(blocked['state'],'blocked')
                    args={'publication_id':edit['resource_id'],'expected_revision':2,'change':{'kind':'retry_failed','destinations':['telegram']},'request_key':'safe-edit-retry'}
                    retry=(await session.call_tool('vibepublish_publication_update',args)).structuredContent
                    self.assertEqual(retry['operation_id'],edit['operation_id'])
                    self.assertEqual(retry['revision'],2)
                    self.assertFalse(retry['operation_complete'])
                    await self.run_worker()
                    result=(await session.call_tool('vibepublish_publication_update',args)).structuredContent
                    self.assertEqual(result['state'],'verified',result)
                    self.assertEqual(result['deliveries'][0]['attempt_id'],blocked['deliveries'][0]['attempt_id'])
                    self.assertTrue(result['operation_complete'])
        from adapters.fake import FakeProvider
        remote=FakeProvider(self.root/'remote.sqlite','telegram')
        self.assertEqual(remote.count('effect'),2)
        with remote.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM items').fetchone()[0],1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM operations').fetchone()[0],2)

    async def test_http_mcp_same_identity_and_direct_hidden_variant_denied(self):
        headers={'Authorization':'Bearer '+self.token,'Idempotency-Key':'cross-transport'}
        args={'to':['telegram'],'content':{'text':'Same intent'}}
        async with httpx.AsyncClient(headers=headers,trust_env=False) as http:
            response=await http.post(self.base+'/v1/publications',json=args)
            self.assertEqual(response.status_code,202,response.text)
            receipt=response.json()
            async with streamable_http_client(self.base+'/mcp/',http_client=http) as (read,write,_):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    result=await session.call_tool('vibepublish_publish',{**args,'request_key':'cross-transport'})
                    self.assertEqual(result.structuredContent['operation_id'],receipt['operation_id'])
            await self.run_worker()
            status=await http.get(self.base+'/v1/operations/'+receipt['operation_id'])
            self.assertEqual(status.json()['receipts'][0]['state'],'verified')
        partner_token=self.store.create_principal('tenant','partner',scopes={'bootstrap','publish','status','forward'})
        self.store.bind(self.actor,'partner','telegram','conn','fixture_target')
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+partner_token},trust_env=False) as http:
            async with streamable_http_client(self.base+'/mcp/',http_client=http) as (read,write,_):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    tools=await session.list_tools()
                    self.assertNotIn('vibepublish_destinations',[t.name for t in tools.tools])
                    denied=await session.call_tool('vibepublish_destinations',{'command':{'kind':'list'}})
                    self.assertTrue(denied.isError)
                    self.assertEqual(denied.structuredContent['error']['code'],'access_denied')
                    denied=await session.call_tool('vibepublish_read',{'query':{'kind':'dialogs','provider':'telegram'}})
                    self.assertTrue(denied.isError)

    async def test_transport_auth_origin_size_and_http_key_fail_before_acceptance(self):
        async with httpx.AsyncClient(trust_env=False) as http:
            response=await http.post(self.base+'/v1/publications',json={'to':['telegram'],'content':{'text':'No auth'}})
            self.assertEqual(response.status_code,401)
            headers={'Authorization':'Bearer '+self.token}
            response=await http.post(self.base+'/v1/publications',headers=headers,json={'to':['telegram'],'content':{'text':'No key'}})
            self.assertEqual(response.status_code,422)
            self.assertEqual(response.json()['error']['code'],'idempotency_key_required')
            response=await http.get(self.base+'/v1/bootstrap',headers={**headers,'Origin':'https://evil.invalid'})
            self.assertEqual(response.status_code,403)
            response=await http.post(self.base+'/v1/publications',headers=headers,content=b' '*(512*1024+1))
            self.assertEqual(response.status_code,413)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM operations').fetchone()[0],0)


    async def test_all_eight_mcp_methods_with_visual_http_asset_and_external_lifecycle_parity(self):
        import base64
        import hashlib
        from adapters.fake import FakeProvider
        from social_operations.domain import parse_source, timestamp
        headers={'Authorization':'Bearer '+self.token}
        remote=FakeProvider(self.root/'remote.sqlite','telegram')
        remote.add_source(parse_source('https://t.me/fixture/5'),text='Original fixture')
        async with httpx.AsyncClient(headers=headers,trust_env=False) as http:
            async with streamable_http_client(self.base+'/mcp/',http_client=http) as (read,write,_):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    async def tool(name,args):
                        result=(await session.call_tool('vibepublish_'+name,args)).structuredContent
                        self.assertNotIn('error',result,result)
                        return result
                    for section in ('all','forwarding','destinations','visuals'):
                        boot=await tool('get_started',{'section':section})
                        self.assertIn('Native forwarding',boot['skill'])
                    await tool('destinations',{'command':{'kind':'profile_update','alias':'telegram','expected_revision':0,'profile':{'notes':'Personal profile'}},'request_key':'profile'})
                    boot=await tool('get_started',{'section':'destinations'})
                    self.assertEqual(boot['destinations'][0]['profile']['notes'],'Personal profile')
                    args={'command':{'kind':'generate','brief':'Offline fixture only','candidates':1}}
                    first=await tool('visual',{**args,'request_key':'visual-http-mcp'})
                    same=await http.post(self.base+'/v1/visuals/commands',headers={'Idempotency-Key':'visual-http-mcp'},json=args)
                    self.assertEqual(same.status_code,202,same.text)
                    self.assertEqual(same.json()['operation_id'],first['operation_id'])
                    await self.run_worker(imagegen=True)
                    ready=(await tool('status',{'ids':[first['visual_job_id']]}))['receipts'][0]
                    self.assertEqual(ready['state'],'needs_selection',ready)
                    candidate=ready['candidates'][0]
                    binary=await http.get(self.base+'/v1/assets/'+candidate['asset_ref'])
                    self.assertEqual(binary.status_code,200,binary.text[:80] if binary.status_code!=200 else '')
                    self.assertEqual(binary.headers['Cache-Control'],'no-store')
                    self.assertEqual(hashlib.sha256(binary.content).hexdigest(),candidate['sha256'])
                    resource=await session.read_resource('vibepublish://assets/'+candidate['asset_ref'])
                    self.assertEqual(base64.b64decode(resource.contents[0].blob),binary.content)
                    choice={'command':{'kind':'select','job_id':first['visual_job_id'],'candidate_id':candidate['id'],
                            'expected_revision':ready['visual_revision'],'token':candidate['selection_token']}}
                    selected=await http.post(self.base+'/v1/visuals/commands',headers={'Idempotency-Key':'choose-http-mcp'},json=choice)
                    self.assertEqual(selected.status_code,200,selected.text)
                    same=await tool('visual',{**choice,'request_key':'choose-http-mcp'})
                    self.assertEqual(same['selected_sha256'],candidate['sha256'])
                    post=await tool('publish',{'to':['telegram'],'media':[{'source':{'kind':'asset','id':candidate['asset_ref']}}],
                            'delivery':{'kind':'at','at':timestamp(time.time()+3600)},'request_key':'scheduled'})
                    await self.run_worker()
                    queue=await tool('read',{'query':{'kind':'scheduled','destination':'telegram'}})
                    await self.run_worker()
                    queue=(await tool('status',{'ids':[queue['operation_id']]}))['receipts'][0]
                    self.assertEqual(len(queue['items']),1,queue)
                    item=queue['items'][0]
                    cancel=await tool('publication_update',{'item_ref':item['ref'],'change':{'kind':'cancel'},'request_key':'external-cancel'})
                    same=await http.post(self.base+'/v1/items/'+item['ref']+'/commands',headers={'Idempotency-Key':'external-cancel'},json={'change':{'kind':'cancel'}})
                    self.assertEqual(same.json()['operation_id'],cancel['operation_id'])
                    await self.run_worker()
                    done=(await tool('status',{'ids':[cancel['operation_id']]}))['receipts'][0]
                    self.assertEqual(done['state'],'cancelled',done)
                    forward=await tool('engage',{'command':{'kind':'forward','item_ref':'https://t.me/fixture/5','to':['telegram']},'request_key':'forward'})
                    await self.run_worker()
                    forwarded=(await tool('status',{'ids':[forward['operation_id']]}))['receipts'][0]
                    self.assertEqual(forwarded['deliveries'][0]['forward_origin']['origin_check'],'matched')
        # Direct hidden calls are denied, not just omitted from tool listing.
        partner_token=self.store.create_principal('tenant','scoped-partner',scopes={'bootstrap','publish','status','forward','destination.profile'})
        self.store.bind(self.actor,'scoped-partner','telegram','conn','fixture_target')
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+partner_token},trust_env=False) as http:
            self.assertEqual((await http.get(self.base+'/v1/assets/'+candidate['asset_ref'])).status_code,404)
            async with streamable_http_client(self.base+'/mcp/',http_client=http) as (read,write,_):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    tools=await session.list_tools()
                    self.assertNotIn('vibepublish_visual',[t.name for t in tools.tools])
                    hidden=await session.call_tool('vibepublish_visual',args)
                    self.assertTrue(hidden.isError)
                    hidden=await session.call_tool('vibepublish_publish',{'to':['telegram'],'visual':{'kind':'generate','brief':'No scope'}})
                    self.assertTrue(hidden.isError)
                    hidden=await session.call_tool('vibepublish_destinations',{'command':{'kind':'set_put','alias':'not-granted','label':'Denied','members':['telegram'],'expected_revision':0}})
                    self.assertTrue(hidden.isError)


if __name__ == '__main__':
    unittest.main(verbosity=2)
