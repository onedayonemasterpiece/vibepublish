"""Actual HTTP MCP boundaries for owner grants and never-dispatched supersession."""
import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from adapters.fake import FakeProvider
from social_operations.domain import DomainError, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


class BlockBeforeDispatch(FakeProvider):
    async def execute(self, prepared, hooks):
        raise DomainError('fixture_before_dispatch')


class EditRecoveryTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'ledger.sqlite')
        self.owner_token = self.store.create_principal('tenant', 'owner', owner=True)
        self.owner = self.store.authenticate(self.owner_token)
        self.partner_token = self.store.create_principal(
            'tenant', 'partner', scopes={'bootstrap', 'publish', 'status',
                                         'destinations', 'publication.manage'})
        self.partner = self.store.authenticate(self.partner_token)
        for provider in ('telegram', 'vk'):
            self.store.add_connection(self.owner, provider, provider, account_type='fake')
            self.store.bind(self.owner, 'owner', provider, provider, provider + '-target',
                            rights=('publish', 'cancel'))
            self.store.bind(self.owner, 'partner', provider, provider, provider + '-target',
                            rights=('publish',))
        self.app = Application(self.store)
        self.tg = FakeProvider(self.root / 'remote.sqlite', 'telegram')
        self.vk = BlockBeforeDispatch(self.root / 'remote.sqlite', 'vk')
        self.worker = Worker(self.store, {'telegram': self.tg, 'vk': self.vk})
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.base = 'http://127.0.0.1:' + str(port)
        self.log = (self.root / 'server.log').open('wb')
        self.proc = subprocess.Popen(
            [sys.executable, '-m', 'social_operations.cli', '--db',
             str(self.store.path), 'serve', '--port', str(port)],
            stdout=subprocess.DEVNULL, stderr=self.log)
        self.addAsyncCleanup(self.cleanup)
        async with httpx.AsyncClient(trust_env=False) as http:
            for _ in range(100):
                if self.proc.poll() is not None:
                    self.fail((self.root / 'server.log').read_text())
                try:
                    if (await http.get(self.base + '/v1/bootstrap')).status_code == 401:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(.03)
            else:
                self.fail('MCP server unavailable')

    async def cleanup(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                await asyncio.to_thread(self.proc.wait, 3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()
        self.tmp.cleanup()

    @asynccontextmanager
    async def client(self, token):
        async with httpx.AsyncClient(
                headers={'Authorization': 'Bearer ' + token},
                trust_env=False) as http:
            async with streamable_http_client(
                    self.base + '/mcp/', http_client=http) as (read, write, _):
                async with ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                    yield session, tools

    async def call(self, session, tool, args):
        Draft202012Validator(tool.inputSchema).validate(args)
        result = await session.call_tool(tool.name, args)
        data = result.structuredContent
        if data is None:
            data = json.loads(next(c.text for c in result.content if hasattr(c, 'text')))
        Draft202012Validator(tool.outputSchema).validate(data)
        return data

    async def test_owner_grant_is_scoped_atomic_and_replay_safe_over_mcp(self):
        with self.store.connection() as db:
            row = self.store.binding(db, self.owner, alias='telegram')
            binding = dict(row)
            routing = self.store.current(db, self.owner).routing_revision
        request = {'command': {'kind': 'binding_grant_edit', 'alias': 'telegram',
                               'expected_binding_epoch': binding['epoch'],
                               'expected_routing_revision': routing},
                   'request_key': 'grant-exact-tg'}
        async with self.client(self.owner_token) as (session, tools):
            tool = tools['vibepublish_destinations']
            first = await self.call(session, tool, request)
            self.assertFalse(first.get('error'), first)
            again = await self.call(session, tool, request)
            self.assertEqual(first['operation_id'], again['operation_id'])
        with self.store.connection() as db:
            after = dict(self.store.binding(db, self.owner, alias='telegram'))
            vk = dict(self.store.binding(db, self.owner, alias='vk'))
            partner = dict(self.store.binding(db, self.partner, alias='telegram'))
            self.assertEqual(set(json.loads(after['rights'])), {'publish', 'cancel', 'edit'})
            self.assertEqual(after['epoch'], binding['epoch'])
            self.assertEqual(self.store.current(db, self.owner).routing_revision, routing + 1)
            self.assertNotIn('edit', json.loads(vk['rights']))
            self.assertNotIn('edit', json.loads(partner['rights']))
        async with self.client(self.partner_token) as (session, tools):
            schema = tools['vibepublish_destinations'].inputSchema
            self.assertTrue(list(Draft202012Validator(schema).iter_errors(request)))
            rejected = await session.call_tool('vibepublish_destinations', request)
            self.assertTrue(rejected.isError)

    async def test_supersede_creates_only_revised_vk_and_preserves_scheduled_tg(self):
        original = self.app.accept(self.owner, 'publish', {
            'to': ['telegram', 'vk'], 'content': {'text': 'Keep. Remove paragraph.'},
            'delivery': {'kind': 'at', 'at': timestamp(self.store.clock() + 3600)},
            'request_key': 'original-mixed'})
        self.assertTrue(await self.worker.run_once())
        with self.store.connection() as db:
            old = {r['alias']: dict(r) for r in db.execute(
                'SELECT * FROM attempts WHERE operation_id=?', (original['operation_id'],))}
        self.assertEqual(old['telegram']['state'], 'scheduled')
        self.assertEqual(old['vk']['dispatched'], 0)
        request = {'publication_id': original['resource_id'], 'expected_revision': 1,
                   'change': {'kind': 'supersede_failed', 'destinations': ['vk'],
                              'content': {'text': 'Keep.'}}, 'request_key': 'replace-vk-content'}
        async with self.client(self.owner_token) as (session, tools):
            tool = tools['vibepublish_publication_update']
            replacement = await self.call(session, tool, request)
            self.assertFalse(replacement.get('error'), replacement)
            replay = await self.call(session, tool, request)
            self.assertEqual(replacement['operation_id'], replay['operation_id'])
        with self.store.connection() as db:
            after = {r['alias']: dict(r) for r in db.execute(
                'SELECT * FROM attempts WHERE operation_id=?', (original['operation_id'],))}
            new = [dict(r) for r in db.execute(
                'SELECT * FROM attempts WHERE operation_id=?', (replacement['operation_id'],))]
        self.assertEqual(after['telegram'], old['telegram'])
        self.assertEqual(after['vk']['state'], 'cancelled')
        self.assertEqual(after['vk']['plan'], old['vk']['plan'])
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]['alias'], 'vk')
        self.assertEqual(json.loads(json.loads(new[0]['plan'])['content_json'])['text'], 'Keep.')
        successful_vk = FakeProvider(self.root / 'remote.sqlite', 'vk')
        worker = Worker(self.store, {'telegram': self.tg, 'vk': successful_vk})
        self.assertTrue(await worker.run_once())
        self.assertEqual(self.store.receipt(self.owner, replacement['operation_id'])['state'], 'scheduled')
        self.assertEqual(self.tg.count('effect'), 1)
        self.assertEqual(successful_vk.count('effect'), 1)
