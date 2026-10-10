"""Real MCP/HTTP contract for private, chunked workspace image ingress."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import random
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image, PngImagePlugin

from social_operations.assets import verify_image
from social_operations.storage import Store


class WorkspaceUploadTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'ledger.sqlite')
        # Deliberately no visual scope: processing existing bytes is not generation.
        self.credential = self.store.create_principal(
            'tenant', 'publisher', scopes=('bootstrap', 'publish', 'status'))
        self.post_sizes = []
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.base = 'http://127.0.0.1:' + str(port)
        self.server_log = (self.root / 'server.log').open('wb')
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'social_operations.cli', '--db',
             str(self.store.path), 'serve', '--port', str(port)],
            stdout=subprocess.DEVNULL, stderr=self.server_log)
        self.addAsyncCleanup(self.cleanup_server)
        async with httpx.AsyncClient(trust_env=False) as http:
            for _ in range(100):
                if self.process.poll() is not None:
                    self.fail((self.root / 'server.log').read_text())
                try:
                    if (await http.get(self.base + '/v1/bootstrap')).status_code == 401:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(.03)
            else:
                self.fail('Local MCP server did not start')

    async def cleanup_server(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.server_log.close()
        self.temp.cleanup()

    @asynccontextmanager
    async def client(self, credential=None):
        async def capture(request):
            if request.method == 'POST' and request.url.path.startswith('/mcp'):
                self.post_sizes.append(len(await request.aread()))
        async with httpx.AsyncClient(
                headers={'Authorization': 'Bearer ' + (credential or self.credential)},
                event_hooks={'request': [capture]}, trust_env=False) as http:
            async with streamable_http_client(
                    self.base + '/mcp/', http_client=http) as (read, write, _):
                async with ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    visual = next(tool for tool in (await session.list_tools()).tools
                                  if tool.name == 'vibepublish_visual')
                    yield session, http, visual

    async def call(self, session, visual, command, key):
        result = await session.call_tool(
            'vibepublish_visual', {'command': command, 'request_key': key})
        self.assertFalse(result.isError, result)
        Draft202012Validator(
            visual.outputSchema, format_checker=FormatChecker()
        ).validate(result.structuredContent)
        return result.structuredContent

    @staticmethod
    def image_bytes(*, large=False):
        image = (Image.frombytes('RGB', (512, 512), random.Random(731).randbytes(512 * 512 * 3))
                 if large else Image.new('RGB', (16, 12), 'green'))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('PrivateComment', 'must be stripped from the derivative')
        output = io.BytesIO()
        image.save(output, format='PNG', pnginfo=metadata)
        return output.getvalue()

    async def begin(self, session, visual, data, key='begin'):
        return await self.call(session, visual, {
            'kind': 'import_begin', 'source_sha256': hashlib.sha256(data).hexdigest(),
            'mime': 'image/png', 'size_bytes': len(data)}, key)

    async def upload(self, session, visual, data, prefix='image'):
        started = await self.begin(session, visual, data, prefix + '-begin')
        upload_id = started['workspace_upload']['upload_id']
        self.assertEqual(started['workspace_upload']['received_bytes'], 0)
        self.assertEqual(started['workspace_upload']['state'], 'receiving')
        for offset in range(0, len(data), 192 * 1024):
            chunk = data[offset:offset + 192 * 1024]
            progress = await self.call(session, visual, {
                'kind': 'import_chunk', 'upload_id': upload_id, 'offset': offset,
                'data_base64': base64.b64encode(chunk).decode('ascii')},
                prefix + '-chunk-' + str(offset))
            self.assertEqual(progress['workspace_upload']['received_bytes'], offset + len(chunk))
        return upload_id

    async def test_large_image_crosses_bounded_mcp_messages_and_survives_reconnect(self):
        data = self.image_bytes(large=True)
        self.assertGreater(len(data), 512 * 1024)
        expected = verify_image(data, 'image/png')
        async with self.client() as (session, _, visual):
            upload_id = await self.upload(session, visual, data)
        # Resume in a new SDK session instead of relying on in-memory transport state.
        async with self.client() as (session, http, visual):
            status = await self.call(session, visual, {
                'kind': 'import_status', 'upload_id': upload_id}, 'status')
            self.assertEqual(status['workspace_upload']['received_bytes'], len(data))
            finish = {'kind': 'import_finish', 'upload_id': upload_id}
            ready = await self.call(session, visual, finish, 'finish')
            self.assertEqual(ready['workspace_upload']['state'], 'completed')
            self.assertEqual(ready['workspace_upload']['source_sha256'],
                             hashlib.sha256(data).hexdigest())
            replay = await self.call(session, visual, finish, 'finish')
            # Progress cursors are fresh read capabilities, not operation identity.
            for field in ('operation_id', 'resource_id', 'workspace_upload', 'state'):
                self.assertEqual(ready[field], replay[field])
            asset_id = ready['resource_id']
            binary = await http.get(self.base + '/v1/assets/' + asset_id)
            self.assertEqual(binary.status_code, 200)
            self.assertEqual(binary.headers['Cache-Control'], 'no-store')
            self.assertEqual(binary.content, expected.data)
            with Image.open(io.BytesIO(binary.content)) as image:
                self.assertNotIn('PrivateComment', image.info)
                self.assertEqual(image.size, (512, 512))
            resource = await session.read_resource('vibepublish://assets/' + asset_id)
            self.assertEqual(base64.b64decode(resource.contents[0].blob), expected.data)
        self.assertGreater(len(self.post_sizes), 4)
        self.assertLess(max(self.post_sizes), 512 * 1024)
        with self.store.connection() as db:
            asset = db.execute('SELECT * FROM assets WHERE id=?', (asset_id,)).fetchone()
            self.assertEqual(asset['principal_id'], 'publisher')
            self.assertEqual(asset['source_sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(asset['sha256'], hashlib.sha256(expected.data).hexdigest())
            self.assertEqual(db.execute('SELECT count(*) FROM publications').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM visual_jobs').fetchone()[0], 0)

    async def test_publish_only_schema_advertises_imports_and_rejects_visual_authority(self):
        async with self.client() as (session, _, visual):
            validator = Draft202012Validator(visual.inputSchema)
            examples = [
                {'kind': 'import_begin', 'source_sha256': 'a' * 64,
                 'mime': 'image/png', 'size_bytes': 1},
                {'kind': 'import_chunk', 'upload_id': 'upload_fixture',
                 'offset': 0, 'data_base64': 'YQ=='},
                *({'kind': kind, 'upload_id': 'upload_fixture'}
                  for kind in ('import_finish', 'import_status', 'import_abort')),
            ]
            for command in examples:
                args = {'command': command, 'request_key': 'schema'}
                validator.validate(args)
                self.assertFalse(validator.is_valid({'command': command}))
            for command in [
                    {'kind': 'generate', 'brief': 'No authority'},
                    {'kind': 'tune', 'source': {'source': {'kind': 'asset', 'id': 'asset_fixture'}},
                     'brief': 'No authority'},
                    {'kind': 'import_browser_artifact',
                     'uri': 'artifact://12345678-1234-4123-8123-123456789abc'}]:
                args = {'command': command, 'request_key': 'denied-' + command['kind']}
                self.assertFalse(validator.is_valid(args))
                result = await session.call_tool('vibepublish_visual', args)
                self.assertTrue(result.isError)
                self.assertEqual(result.structuredContent['error']['code'], 'invalid_input')
                Draft202012Validator(visual.outputSchema).validate(result.structuredContent)

    async def test_invalid_commands_return_declared_errors_without_assets(self):
        valid = {'kind': 'import_begin', 'source_sha256': 'b' * 64,
                 'mime': 'image/png', 'size_bytes': 10}
        commands = [
            {**valid, 'source_sha256': 'not-a-hash'},
            {**valid, 'size_bytes': 0},
            {**valid, 'size_bytes': 20 * 1024 * 1024 + 1},
            {**valid, 'mime': 'image/svg+xml'},
            {'kind': 'import_chunk', 'upload_id': 'upload_missing',
             'offset': 0, 'data_base64': 'a' * 262148},
            {'kind': 'import_chunk', 'upload_id': 'upload_missing',
             'offset': -1, 'data_base64': 'YQ=='},
        ]
        async with self.client() as (session, _, visual):
            for index, command in enumerate(commands):
                result = await session.call_tool('vibepublish_visual', {
                    'command': command, 'request_key': 'invalid-' + str(index)})
                self.assertTrue(result.isError)
                self.assertEqual(result.structuredContent['error']['code'], 'invalid_input')
                Draft202012Validator(visual.outputSchema).validate(result.structuredContent)
            result = await session.call_tool('vibepublish_visual', {'command': valid})
            self.assertTrue(result.isError)
            self.assertEqual(result.structuredContent['error']['code'], 'invalid_input')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM assets').fetchone()[0], 0)

    async def test_upload_and_finished_asset_are_private_to_principal(self):
        data = self.image_bytes()
        async with self.client() as (session, _, visual):
            upload_id = await self.upload(session, visual, data)
            complete = await self.call(session, visual, {
                'kind': 'import_finish', 'upload_id': upload_id}, 'finish')
            pending = await self.begin(session, visual, data, 'pending')
            pending_id = pending['workspace_upload']['upload_id']
            aborted = await self.call(session, visual, {
                'kind': 'import_abort', 'upload_id': pending_id}, 'abort')
            self.assertEqual(aborted['workspace_upload']['state'], 'aborted')
            status = await self.call(session, visual, {
                'kind': 'import_status', 'upload_id': pending_id}, 'aborted-status')
            self.assertEqual(status['workspace_upload']['state'], 'aborted')
        for tenant, principal in [('tenant', 'peer'), ('other-tenant', 'outsider')]:
            credential = self.store.create_principal(
                tenant, principal, scopes=('bootstrap', 'publish', 'status'))
            async with self.client(credential) as (session, http, visual):
                for kind in ('import_status', 'import_finish', 'import_abort'):
                    denied = await session.call_tool('vibepublish_visual', {
                        'command': {'kind': kind, 'upload_id': upload_id},
                        'request_key': 'foreign-' + kind})
                    self.assertTrue(denied.isError)
                    self.assertEqual(denied.structuredContent['error']['code'],
                                     'workspace_upload_not_found')
                    Draft202012Validator(visual.outputSchema).validate(denied.structuredContent)
                response = await http.get(self.base + '/v1/assets/' + complete['resource_id'])
                self.assertEqual(response.status_code, 404)
                preview = await session.call_tool('vibepublish_asset_preview', {
                    'resource_uri': 'vibepublish://assets/' + complete['resource_id']})
                self.assertTrue(preview.isError)
                self.assertEqual(preview.structuredContent['error']['code'], 'asset_not_available')


if __name__ == '__main__':
    unittest.main(verbosity=2)
