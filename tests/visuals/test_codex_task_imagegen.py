"""Offline protocol fixtures only: generated fixture pixels are not live art."""
import asyncio
import base64
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
from adapters.codex_task_imagegen import AppServer, CodexTaskImagegen, MODEL
from adapters.imagegen import ImagegenRequest, ImagegenSource
from social_operations.domain import DomainError
from social_operations.visual_artifacts import verified_artifact

THREAD = '01a07234-66ed-77d3-b42d-9645fd167d18'
TURN = '01a07234-7e26-79c1-ae63-4ea2e927786d'


def png():
    out = io.BytesIO()
    Image.new('RGB', (64, 80), 'blue').save(out, format='PNG')
    return out.getvalue()


class NativeFixture:
    def __init__(self, home):
        self.home = home
        self.calls = []
        self.status = 'completed'
        self.lose_start = False
        self.bad_model = False
        self.items = []
        self.marker_check = None

    async def request(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/start':
            return {'thread': {'id': THREAD}, 'cwd': params['cwd'],
                    'model': 'wrong-model' if self.bad_model else MODEL}
        if method == 'turn/start':
            if self.marker_check: self.marker_check()
            native = self.home / 'generated_images' / THREAD
            native.mkdir(parents=True, exist_ok=True)
            data = png(); path = native / 'exec-image.png'; path.write_bytes(data)
            self.items = [{'type': 'imageGeneration', 'id': 'exec-image', 'status': 'completed',
                'savedPath': str(path), 'result': base64.b64encode(data).decode(), 'failure': None}]
            if self.lose_start: raise ConnectionError('lost response')
            return {'turn': {'id': TURN, 'status': 'inProgress'}}
        if method == 'thread/read':
            return {'thread': {'id': THREAD, 'turns': [{'id': TURN,
                'status': self.status, 'items': self.items}]}}
        if method == 'turn/interrupt':
            self.status = 'interrupted'
            return {}
        raise AssertionError(method)

    async def close(self): pass


class CodexTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / 'codex'; self.home.mkdir(mode=0o700)
        self.native = NativeFixture(self.home)
        self.adapter = CodexTaskImagegen(self.root / 'images', codex_home=self.home,
                                        transport=self.native)
        self.request = ImagegenRequest('visual_' + 'a' * 32, 'b' * 64, 'generate',
            'Афиша с надписью "Кто я?"', (), 'art-v1', MODEL, 1, time.time() + 600)

    async def asyncTearDown(self):
        await self.adapter.close()
        self.tmp.cleanup()

    async def test_native_receipt_import_and_actual_identity(self):
        key = await self.adapter.submit(self.request)
        observation = await self.adapter.inspect(key)
        self.assertEqual('succeeded', observation.state)
        self.assertFalse(observation.fixture)
        self.assertEqual('codex-app-server-task', observation.actual_executor)
        self.assertIsNone(observation.actual_model)
        usage = json.loads(observation.usage_json)
        self.assertEqual({'candidate_limit': 1, 'native_images_completed': 1, 'imported_artifacts': 1}, usage)
        private = self.adapter._load(self.adapter._directory(key))
        self.assertEqual(THREAD, private['thread_id'])
        self.assertEqual(TURN, private['turn_id'])
        self.assertEqual(MODEL, private['task_model'])
        self.assertEqual('prompt_and_accepted_output_not_hard_upstream_call_cap', private['budget_policy'])
        self.assertEqual(hashlib.sha256(png()).hexdigest(), observation.artifacts[0].sha256)
        verified_artifact(self.adapter.artifact_root / key, observation.artifacts[0])

    async def test_durable_marker_precedes_turn_start(self):
        def check():
            receipt = self.adapter._load(self.adapter._directory(self.request.job_key))
            self.assertEqual('turn_start_pending', receipt['phase'])
            self.assertEqual(THREAD, receipt['thread_id'])
            self.assertIsNone(receipt['turn_id'])
        self.native.marker_check = check
        await self.adapter.submit(self.request)

    async def test_lost_start_response_recovers_without_resending(self):
        self.native.lose_start = True
        key = await self.adapter.submit(self.request)
        await self.adapter.close()
        self.adapter = CodexTaskImagegen(self.root / 'images', codex_home=self.home,
                                        transport=self.native)
        await self.adapter.submit(self.request)
        observed = await self.adapter.find(key)
        self.assertEqual('succeeded', observed.state)
        self.assertEqual(1, sum(m == 'turn/start' for m, _ in self.native.calls))
        self.assertEqual(1, sum(m == 'thread/start' for m, _ in self.native.calls))

    async def test_uncertain_thread_start_is_never_retried(self):
        original = self.native.request
        async def request(method, params):
            if method == 'thread/start':
                self.native.calls.append((method, params))
                raise ConnectionError('lost thread')
            return await original(method, params)
        self.native.request = request
        key = await self.adapter.submit(self.request)
        await self.adapter.submit(self.request)
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)
        self.assertEqual(1, len(self.native.calls))

    async def test_conflicting_digest_is_rejected(self):
        await self.adapter.submit(self.request)
        with self.assertRaises(DomainError):
            await self.adapter.submit(replace(self.request, input_digest='c' * 64))

    async def test_local_image_inputs_and_quoted_brief_preserved(self):
        data = png()
        source = ImagegenSource('source', hashlib.sha256(data).hexdigest(), 'image/png',
                                64, 80, len(data), data)
        await self.adapter.submit(replace(self.request, mode='tune', sources=(source,)))
        params = next(p for m, p in self.native.calls if m == 'turn/start')
        prompt = params['input'][0]['text']
        job = json.loads(prompt.split('Task data follows as JSON:\n')[1])
        self.assertEqual(self.request.brief, job['brief'])
        self.assertEqual('localImage', params['input'][1]['type'])
        self.assertEqual(data, Path(params['input'][1]['path']).read_bytes())
        self.assertIn('no API fallback', prompt)

    async def test_source_integrity_failure_never_starts(self):
        source = ImagegenSource('source', 'c' * 64, 'image/png', 64, 80, len(png()), png())
        with self.assertRaises(DomainError):
            await self.adapter.submit(replace(self.request, sources=(source,)))
        self.assertEqual([], self.native.calls)

    async def test_wrong_task_model_blocks_turn(self):
        self.native.bad_model = True
        key = await self.adapter.submit(self.request)
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)
        self.assertFalse(any(m == 'turn/start' for m, _ in self.native.calls))

    async def test_text_report_without_native_image_is_not_success(self):
        key = await self.adapter.submit(self.request)
        self.native.items = [{'type': 'agentMessage', 'text': '{"saved_paths":["fake.png"]}'}]
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)

    async def test_native_bytes_must_match_receipt(self):
        key = await self.adapter.submit(self.request)
        self.native.items[0]['result'] = base64.b64encode(b'not image').decode()
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)

    async def test_native_path_cannot_escape_saved_thread(self):
        key = await self.adapter.submit(self.request)
        outside = self.root / 'outside.png'; outside.write_bytes(png())
        self.native.items[0]['savedPath'] = str(outside)
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)

    async def test_symlink_native_file_rejected(self):
        key = await self.adapter.submit(self.request)
        path = Path(self.native.items[0]['savedPath'])
        outside = self.root / 'outside.png'; outside.write_bytes(png())
        path.unlink(); path.symlink_to(outside)
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)

    async def test_more_native_candidates_than_authorized_not_imported(self):
        key = await self.adapter.submit(self.request)
        self.native.items *= 2
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)

    async def test_cancel_interrupts_only_saved_turn_no_process_kill(self):
        key = await self.adapter.submit(self.request)
        self.native.status = 'inProgress'
        self.assertEqual('unknown', (await self.adapter.cancel(key)).state)
        self.assertEqual(('turn/interrupt', {'threadId': THREAD, 'turnId': TURN}), self.native.calls[-1])
        self.assertEqual('failed', (await self.adapter.inspect(key)).state)

    async def test_deadline_interrupts_without_another_generation(self):
        key = await self.adapter.submit(self.request)
        self.native.status = 'inProgress'
        directory = self.adapter._directory(key)
        record = self.adapter._load(directory); record['deadline'] = 0
        self.adapter._record(directory, record)
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)
        self.assertEqual('turn/interrupt', self.native.calls[-1][0])
        self.assertEqual(1, sum(m == 'turn/start' for m, _ in self.native.calls))

    async def test_completed_receipt_reads_without_remote_calls(self):
        key = await self.adapter.submit(self.request)
        await self.adapter.inspect(key)
        self.native.calls.clear()
        self.assertEqual('succeeded', (await self.adapter.find(key)).state)
        self.assertEqual([], self.native.calls)

    def test_environment_does_not_inherit_api_or_social_keys(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture', 'CODEX_API_KEY': 'fixture',
                                   'TELEGRAM_TOKEN': 'fixture'}):
            env = AppServer(self.home).environment()
        self.assertEqual(str(self.home), env['CODEX_HOME'])
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('CODEX_API_KEY', env)
        self.assertNotIn('TELEGRAM_TOKEN', env)


class VisualServiceTaskIntegration(unittest.IsolatedAsyncioTestCase):
    """Exercise the actual service contract, not just adapter-shaped fixtures."""
    async def test_running_native_task_becomes_service_candidates_without_resubmit(self):
        from social_operations.service import Application
        from social_operations.storage import Store
        from social_operations.worker import Worker

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / 'codex'; home.mkdir(mode=0o700)
            native = NativeFixture(home)
            native.status = 'inProgress'
            original = native.request
            reads = []
            async def request(method, params):
                response = await original(method, params)
                if method == 'thread/read':
                    reads.append(response['thread']['turns'][0]['status'])
                    native.status = 'completed'
                return response
            native.request = request
            executor = CodexTaskImagegen(root / 'images', codex_home=home, transport=native)
            store = Store(root / 'ledger.sqlite')
            token = store.create_principal('tenant', 'owner', owner=True)
            actor = store.authenticate(token)
            app = Application(store)
            worker = Worker(store, {}, imagegen=executor)
            try:
                submitted = await app.call(actor, 'vibepublish_visual', {'command': {
                    'kind': 'generate', 'prompt': 'Афиша "Кто я?"',
                    'candidates': 1, 'formats': ['post_4_5']}, 'request_key': 'native-task'})
                self.assertEqual('accepted', submitted['state'], submitted)
                await worker.run_once()
                ready = store.receipt(actor, submitted['operation_id'])
                self.assertEqual('needs_selection', ready['state'], ready)
                self.assertEqual(['inProgress', 'completed'], reads)
                self.assertEqual(1, len(ready['candidates']))
                self.assertEqual('codex-app-server-task', ready['executor']['actual_executor'])
                self.assertEqual(1, sum(m == 'turn/start' for m, _ in native.calls))
                with store.connection() as db:
                    row = db.execute('SELECT * FROM visual_candidates').fetchone()
                    provenance = json.loads(row['provenance'])
                    self.assertTrue(all(type(x) in (int, float) for x in provenance['usage'].values()))
                    self.assertEqual(0, db.execute('SELECT count(*) FROM publications').fetchone()[0])
                payload, _mime, sha = app.read_asset(actor, ready['candidates'][0]['asset_ref'])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), sha)
            finally:
                await executor.close()
