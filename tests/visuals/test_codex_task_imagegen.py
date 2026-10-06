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
SKILL_FIXTURE = '# Installed imagegen fixture\nUse built-in image_gen for image requests.\n'


def png():
    out = io.BytesIO()
    Image.new('RGB', (64, 80), 'blue').save(out, format='PNG')
    return out.getvalue()


class NativeFixture:
    def __init__(self, home):
        self.home = home
        skill = home / 'skills' / '.system' / 'imagegen' / 'SKILL.md'
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(SKILL_FIXTURE)
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
                    'approvalPolicy': 'never', 'sandbox': {'type': 'workspaceWrite'},
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

    async def test_verified_internal_source_may_exceed_upload_limit(self):
        data = png() + bytes(20 * 1024 * 1024)
        source = ImagegenSource('source', hashlib.sha256(data).hexdigest(), 'image/png',
                                64, 80, len(data), data)
        await self.adapter.submit(replace(self.request, mode='tune', sources=(source,)))
        params = next(p for m, p in self.native.calls if m == 'turn/start')
        self.assertEqual('localImage', params['input'][1]['type'])
        self.assertEqual(data, Path(params['input'][1]['path']).read_bytes())
        self.assertGreater(len(data), 20 * 1024 * 1024)
        self.assertLessEqual(len(data), 32 * 1024 * 1024)

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

    async def test_required_thread_profile_blocks_generation_with_safe_diagnostics(self):
        original = self.native.request
        cases = [('missing_response', None), ('missing_thread', {}), ('missing_id', {'thread': {}}),
                 ('wrong_model', {'model': 'PRIVATE_UNEXPECTED_MODEL'}),
                 ('wrong_cwd', {'cwd': '/PRIVATE_UNEXPECTED_DIRECTORY'}),
                 ('wrong_approval', {'approvalPolicy': 'on-request'}),
                 ('wrong_sandbox', {'sandbox': {'type': 'dangerFullAccess'}})]
        for name, change in cases:
            with self.subTest(profile=name):
                self.native.calls.clear()
                async def incompatible(method, params):
                    response = await original(method, params)
                    if method == 'thread/start':
                        if name == 'missing_response': return None
                        if name == 'missing_thread': return {}
                        return {**response, **change}
                    return response
                self.native.request = incompatible
                request = replace(self.request, job_key='visual_' + hashlib.md5(name.encode()).hexdigest())
                with self.assertLogs('adapters.codex_task_imagegen', level='WARNING') as captured:
                    key = await self.adapter.submit(request)
                receipt = self.adapter._load(self.adapter._directory(key))
                self.assertEqual('unknown', receipt['state'])
                self.assertEqual('thread_start_pending', receipt['phase'])
                self.assertIsNone(receipt['turn_id'])
                self.assertEqual('thread/start', receipt['protocol_failure']['method'])
                self.assertEqual('profile', receipt['protocol_failure']['stage'])
                self.assertIn(receipt['protocol_failure']['code'],
                    ('codex_task_protocol_invalid', 'codex_task_thread_profile_mismatch'))
                self.assertFalse(any(m == 'turn/start' for m, _ in self.native.calls))
                self.assertNotIn('PRIVATE_UNEXPECTED', json.dumps(receipt))
                self.assertNotIn('PRIVATE_UNEXPECTED', str(captured.output))
                await self.adapter.submit(request)
                self.assertEqual(1, len(self.native.calls), 'Unknown protocol failure must not resubmit')

    async def test_text_report_without_native_image_is_not_success(self):
        key = await self.adapter.submit(self.request)
        self.native.items = [{'type': 'agentMessage', 'text': '{"saved_paths":["fake.png"]}'}]
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)

    async def test_native_bytes_must_match_receipt(self):
        key = await self.adapter.submit(self.request)
        self.native.items[0]['result'] = base64.b64encode(b'not image').decode()
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)
        self.assertEqual(1, sum(m == 'thread/read' for m, _ in self.native.calls))

    async def test_interrupted_turn_is_reconciled_without_resubmit(self):
        key = await self.adapter.submit(self.request)
        self.native.status = 'interrupted'
        first = await self.adapter.inspect(key)
        self.assertEqual('running', first.state)
        self.native.status = 'completed'
        recovered = await self.adapter.inspect(key)
        self.assertEqual('succeeded', recovered.state)
        self.assertEqual(1, sum(m == 'thread/start' for m, _ in self.native.calls))
        self.assertEqual(1, sum(m == 'turn/start' for m, _ in self.native.calls))

    async def test_cached_failed_receipt_with_saved_turn_is_reconciled(self):
        key = await self.adapter.submit(self.request)
        directory = self.adapter._directory(key)
        record = self.adapter._load(directory)
        record['state'] = 'failed'
        record['phase'] = 'submitted'
        self.adapter._record(directory, record)
        self.native.status = 'completed'
        recovered = await self.adapter.inspect(key)
        self.assertEqual('succeeded', recovered.state)
        self.assertEqual(1, sum(m == 'turn/start' for m, _ in self.native.calls))

    async def test_executor_owned_interrupt_remains_terminal(self):
        key = await self.adapter.submit(self.request)
        self.native.status = 'inProgress'
        cancelled = await self.adapter.cancel(key)
        self.assertEqual('unknown', cancelled.state)
        self.assertEqual('interrupted', self.native.status)
        terminal = await self.adapter.inspect(key)
        self.assertEqual('failed', terminal.state)
        self.assertEqual(1, sum(m == 'turn/start' for m, _ in self.native.calls))

    async def test_transport_read_errors_retry_only_saved_thread(self):
        for error in (OSError, RuntimeError, asyncio.TimeoutError):
            with self.subTest(error=error.__name__):
                request = replace(self.request, job_key='visual_' + hashlib.md5(error.__name__.encode()).hexdigest())
                self.native.calls.clear()
                key = await self.adapter.submit(request)
                original = self.native.request
                attempts = []
                async def flaky(method, params):
                    attempts.append((method, params))
                    if len(attempts) == 1:
                        raise error('PRIVATE_TRANSIENT_ERROR')
                    return await original(method, params)
                self.native.request = flaky
                try:
                    observed = await self.adapter.inspect(key)
                finally:
                    self.native.request = original
                self.assertEqual('succeeded', observed.state)
                self.assertEqual([('thread/read', {'threadId': THREAD, 'includeTurns': True})] * 2, attempts)
                self.assertEqual(1, len(observed.artifacts))
                self.assertEqual(1, sum(m == 'turn/start' for m, _ in self.native.calls))
                record = self.adapter._load(self.adapter._directory(key))
                self.assertEqual(2, record['last_thread_read_attempts'])
                self.assertEqual(error.__name__, record['last_thread_read_error']['class'])
                self.assertNotIn('PRIVATE_TRANSIENT_ERROR', json.dumps(record))

    async def test_read_timeout_budget_and_exhaustion(self):
        from adapters.codex_task_imagegen import THREAD_READ_TIMEOUT, THREAD_READ_BACKOFF
        self.assertEqual(3, 1 + len(THREAD_READ_BACKOFF))
        self.assertLess(THREAD_READ_TIMEOUT * 3 + sum(THREAD_READ_BACKOFF), 15)
        key = await self.adapter.submit(self.request)
        attempts, cancelled = [], []
        async def blocked(method, params):
            attempts.append((method, params))
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.append(True)
        self.native.request = blocked
        started = time.monotonic()
        with patch('adapters.codex_task_imagegen.THREAD_READ_TIMEOUT', 0.01), patch(
                'adapters.codex_task_imagegen.THREAD_READ_BACKOFF', (0.001, 0.002)):
            observed = await self.adapter.inspect(key)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual('unknown', observed.state)
        self.assertEqual(3, len(cancelled))
        self.assertEqual([('thread/read', {'threadId': THREAD, 'includeTurns': True})] * 3, attempts)
        record = self.adapter._load(self.adapter._directory(key))
        self.assertEqual(3, record['last_thread_read_attempts'])
        self.assertEqual('TimeoutError', record['last_observation_error']['class'])

    async def test_binding_failure_does_not_retry_read(self):
        key = await self.adapter.submit(self.request)
        original = self.native.request
        async def wrong_thread(method, params):
            response = await original(method, params)
            response['thread']['id'] = 'different-thread'
            return response
        self.native.request = wrong_thread
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)
        self.assertEqual(1, sum(m == 'thread/read' for m, _ in self.native.calls))

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

    async def test_find_saves_only_sanitized_exception_frames(self):
        key = await self.adapter.submit(self.request)
        private_text = 'PRIVATE_PROMPT_OR_TOKEN_MUST_NOT_BE_SAVED'
        async def fail(method, params):
            raise RuntimeError(private_text)
        self.native.request = fail
        observed = await self.adapter.find(key)
        self.assertEqual('unknown', observed.state)
        record = self.adapter._load(self.adapter._directory(key))
        error = record['last_observation_error']
        self.assertEqual('RuntimeError', error['class'])
        self.assertTrue(error['frames'])
        for frame in error['frames']:
            self.assertEqual({'file', 'line', 'function'}, set(frame))
            self.assertNotIn('/', frame['file'])
            self.assertIsInstance(frame['line'], int)
        self.assertNotIn(private_text, json.dumps(record))
        self.assertNotIn('last_observation_error', observed.usage_json)

    async def test_malformed_thread_response_is_diagnosed(self):
        key = await self.adapter.submit(self.request)
        async def malformed(method, params):
            return {'thread': None}
        self.native.request = malformed
        self.assertEqual('unknown', (await self.adapter.inspect(key)).state)
        record = self.adapter._load(self.adapter._directory(key))
        self.assertEqual('AttributeError', record['last_observation_error']['class'])

    async def test_observation_conversion_failure_is_diagnosed_before_reraise(self):
        key = await self.adapter.submit(self.request)
        def conversion_failure(record):
            raise TypeError('PRIVATE_VALUES_NOT_DIAGNOSTICS')
        self.adapter._observation = conversion_failure
        with self.assertRaises(TypeError):
            await self.adapter.inspect(key)
        record = self.adapter._load(self.adapter._directory(key))
        self.assertEqual('TypeError', record['last_observation_error']['class'])
        self.assertNotIn('PRIVATE_VALUES_NOT_DIAGNOSTICS', json.dumps(record))

    async def test_inspection_cancellation_is_recorded_and_propagated(self):
        key = await self.adapter.submit(self.request)
        async def cancelled(method, params):
            raise asyncio.CancelledError('PRIVATE_CANCELLATION_TEXT')
        self.native.request = cancelled
        with self.assertRaises(asyncio.CancelledError):
            await self.adapter.inspect(key)
        record = self.adapter._load(self.adapter._directory(key))
        self.assertEqual('unknown', record['state'])
        self.assertEqual('CancelledError', record['last_observation_error']['class'])
        self.assertNotIn('PRIVATE_CANCELLATION_TEXT', json.dumps(record))

    async def test_trusted_top_level_codex_home_symlink_is_canonicalized(self):
        real = self.root / 'real-codex'
        real.mkdir(mode=0o700)
        skill = real / 'skills' / '.system' / 'imagegen' / 'SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text(SKILL_FIXTURE)
        alias = self.root / 'codex-alias'
        alias.symlink_to(real, target_is_directory=True)
        native = NativeFixture(real)
        adapter = CodexTaskImagegen(
            self.root / 'symlink-images',
            codex_home=alias,
            transport=native,
        )
        try:
            self.assertEqual(real.resolve(), adapter.codex_home)
            key = await adapter.submit(replace(
                self.request,
                job_key='visual_' + 'c' * 32,
            ))
            record = adapter._load(adapter._directory(key))
            self.assertEqual(
                str(real / 'skills/.system/imagegen/SKILL.md'),
                record['skill_snapshot']['path'],
            )
            self.assertTrue(any(m == 'thread/start' for m, _ in native.calls))
        finally:
            await adapter.close()

    def test_untrusted_resolved_codex_home_is_rejected(self):
        unsafe = self.root / 'unsafe-codex'
        unsafe.mkdir(mode=0o700)
        unsafe.chmod(0o755)
        alias = self.root / 'unsafe-alias'
        alias.symlink_to(unsafe, target_is_directory=True)
        with self.assertRaises(DomainError) as error:
            CodexTaskImagegen(
                self.root / 'unsafe-images',
                codex_home=alias,
                transport=self.native,
            )
        self.assertEqual('codex_task_home_untrusted', error.exception.code)

    async def test_preloads_fixed_skill_into_developer_context_with_private_hash(self):
        key = await self.adapter.submit(self.request)
        params = next(p for m, p in self.native.calls if m == 'thread/start')
        instructions = params['developerInstructions']
        self.assertIn(SKILL_FIXTURE, instructions)
        self.assertIn('already loaded', instructions)
        self.assertIn('localImage inputs are already visible', instructions)
        self.assertIn('No shell or filesystem commands are needed', instructions)
        self.assertIn('No CLI/API fallback', instructions)
        self.assertEqual('workspace-write', params['sandbox'])
        self.assertNotIn('use_legacy_landlock', json.dumps(params))
        record = self.adapter._load(self.adapter._directory(key))
        snapshot = record['skill_snapshot']
        self.assertEqual(hashlib.sha256(SKILL_FIXTURE.encode()).hexdigest(), snapshot['sha256'])
        self.assertEqual(len(SKILL_FIXTURE.encode()), snapshot['size'])
        self.assertEqual(str(self.home / 'skills/.system/imagegen/SKILL.md'), snapshot['path'])
        self.assertNotIn(SKILL_FIXTURE, json.dumps(record))

    async def test_missing_skill_blocks_before_any_native_dispatch(self):
        (self.home / 'skills/.system/imagegen/SKILL.md').unlink()
        with self.assertRaises(DomainError) as error:
            await self.adapter.submit(self.request)
        self.assertEqual('codex_task_skill_unavailable', error.exception.code)
        self.assertEqual([], self.native.calls)

    async def test_skill_symlink_is_not_trusted(self):
        skill = self.home / 'skills/.system/imagegen/SKILL.md'
        other = self.root / 'caller-skill'; other.write_text('caller content')
        skill.unlink(); skill.symlink_to(other)
        with self.assertRaises(DomainError): await self.adapter.submit(self.request)
        self.assertEqual([], self.native.calls)

    async def test_oversized_skill_blocks_before_any_native_dispatch(self):
        from adapters.codex_task_imagegen import MAX_SKILL
        (self.home / 'skills/.system/imagegen/SKILL.md').write_bytes(b'x' * (MAX_SKILL + 1))
        with self.assertRaises(DomainError): await self.adapter.submit(self.request)
        self.assertEqual([], self.native.calls)

    async def test_existing_job_keeps_original_skill_identity_without_resubmit(self):
        key = await self.adapter.submit(self.request)
        (self.home / 'skills/.system/imagegen/SKILL.md').unlink()
        self.assertEqual(key, await self.adapter.submit(self.request))
        record = self.adapter._load(self.adapter._directory(key))
        self.assertEqual(hashlib.sha256(SKILL_FIXTURE.encode()).hexdigest(), record['skill_snapshot']['sha256'])
        self.assertEqual(1, sum(m == 'turn/start' for m, _ in self.native.calls))

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
        await self._service_task()

    async def test_transient_read_error_becomes_one_candidate_without_resubmit(self):
        await self._service_task(read_failures=1)

    async def test_exhausted_read_errors_remain_unknown_without_resubmit(self):
        await self._service_task(read_failures=3)

    async def _service_task(self, read_failures=0):
        from social_operations.service import Application
        from social_operations.storage import Store
        from social_operations.worker import Worker

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / 'codex'; home.mkdir(mode=0o700)
            native = NativeFixture(home)
            native.status = 'completed' if read_failures else 'inProgress'
            original = native.request
            reads = []
            async def request(method, params):
                if method == 'thread/read' and len(reads) < read_failures:
                    reads.append('error')
                    native.calls.append((method, params))
                    raise RuntimeError('PRIVATE_TRANSIENT_READ_ERROR')
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
                self.assertEqual(1, sum(m == 'thread/start' for m, _ in native.calls))
                self.assertEqual(1, sum(m == 'turn/start' for m, _ in native.calls))
                self.assertFalse(any(m == 'turn/interrupt' for m, _ in native.calls))
                if read_failures == 3:
                    self.assertEqual('outcome_unknown', ready['state'], ready)
                    self.assertIn('imagegen_submit_outcome_unknown', json.dumps(ready))
                    self.assertEqual(['error'] * 3, reads)
                    with store.connection() as db:
                        self.assertEqual(0, db.execute('SELECT count(*) FROM visual_candidates').fetchone()[0])
                        self.assertEqual(0, db.execute('SELECT count(*) FROM publications').fetchone()[0])
                    return
                self.assertEqual('needs_selection', ready['state'], ready)
                self.assertEqual(['error', 'completed'] if read_failures else ['inProgress', 'completed'], reads)
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


class AppServerInitializationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def version_process(output=b'future-compatible-cli', code=0):
        from unittest.mock import AsyncMock, Mock
        return Mock(returncode=code, stdout=Mock(read=AsyncMock(side_effect=[output, b''])),
                    wait=AsyncMock(return_value=code))

    async def test_future_versions_and_reformatted_or_empty_metadata_initialize(self):
        from unittest.mock import AsyncMock, Mock

        for version, code in [('codex-cli 0.161.0', 0), ('codex-cli 0.160.1', 0),
                              ('future vendor format', 0), ('', 0), ('', 1), ('x' * 512, 0)]:
            with self.subTest(version=version, exit_code=code):
                client = AppServer(Path('/fixture/codex'))
                check = self.version_process(version.encode(), code)
                process = Mock(returncode=None, wait=AsyncMock(return_value=-15))
                process.terminate.side_effect = lambda: setattr(process, 'returncode', -15)
                client._exchange = AsyncMock(side_effect=[
                    {'codexHome': '/fixture/codex', 'unknownFutureField': {'accepted': True}},
                    {'thread': {'id': THREAD}},
                ])
                client._write = AsyncMock()
                async def drain(_process):
                    await asyncio.Event().wait()
                client._drain = drain
                with patch('adapters.codex_task_imagegen.asyncio.create_subprocess_exec',
                           side_effect=[check, process]) as spawn:
                    try:
                        result = await client.request('thread/read', {'threadId': THREAD})
                        self.assertEqual(THREAD, result['thread']['id'])
                        self.assertTrue(client.initialized)
                        self.assertLessEqual(len(client.cli_version or ''), 160)
                        self.assertEqual(['initialize', 'thread/read'],
                            [call.args[0] for call in client._exchange.await_args_list])
                        client._write.assert_awaited_once_with({'method': 'initialized', 'params': {}})
                        self.assertEqual(('app-server', '--stdio'), spawn.call_args.args[1:3])
                    finally:
                        await client.close()
                    process.terminate.assert_called_once()

    async def test_unavailable_or_timed_out_version_probe_does_not_block_protocol(self):
        from unittest.mock import AsyncMock, Mock

        for probe_error in [OSError(), asyncio.TimeoutError()]:
            with self.subTest(error=type(probe_error).__name__):
                client = AppServer(Path('/fixture/codex'))
                process = Mock(returncode=None, wait=AsyncMock(return_value=-15))
                process.terminate.side_effect = lambda: setattr(process, 'returncode', -15)
                version = self.version_process()
                version.returncode = None
                version.stdout.read.side_effect = probe_error
                version.kill.side_effect = lambda: setattr(version, 'returncode', -9)
                spawn_results = [probe_error, process] if type(probe_error) is OSError else [version, process]
                client._exchange = AsyncMock(side_effect=[{'codexHome': '/fixture/codex'}, {'thread': {'id': THREAD}}])
                client._write = AsyncMock()
                async def drain(_process):
                    await asyncio.Event().wait()
                client._drain = drain
                with patch('adapters.codex_task_imagegen.asyncio.create_subprocess_exec',
                           side_effect=spawn_results):
                    try:
                        self.assertEqual(THREAD, (await client.request('thread/read', {'threadId': THREAD}))['thread']['id'])
                        self.assertTrue(client.initialized)
                        self.assertIsNone(client.cli_version)
                        if isinstance(probe_error, asyncio.TimeoutError): version.kill.assert_called_once()
                    finally:
                        await client.close()

    async def test_malformed_initialize_never_sends_caller_request_and_cleans_owned_process(self):
        from unittest.mock import AsyncMock, Mock

        for response in [None, [], {}, {'codexHome': 12}, {'codexHome': ''}]:
            with self.subTest(response=response):
                client = AppServer(Path('/fixture/codex'))
                process = Mock(returncode=None, wait=AsyncMock(return_value=-15))
                process.terminate.side_effect = lambda: setattr(process, 'returncode', -15)
                client._exchange = AsyncMock(return_value=response)
                client._write = AsyncMock()
                async def drain(_process):
                    await asyncio.Event().wait()
                client._drain = drain
                with patch('adapters.codex_task_imagegen.asyncio.create_subprocess_exec',
                           side_effect=[self.version_process(), process]):
                    with self.assertRaises(DomainError) as error:
                        await client.request('thread/start', {})
                self.assertEqual('codex_task_protocol_invalid', error.exception.code)
                self.assertEqual({'code': 'codex_task_protocol_invalid', 'method': 'initialize', 'stage': 'handshake'}, client.last_protocol_failure)
                self.assertEqual(1, client._exchange.await_count)
                client._write.assert_not_awaited()
                self.assertFalse(client.initialized)
                self.assertIsNone(client.process)
                self.assertIsNone(client.reader)
                process.terminate.assert_called_once()

    async def test_malformed_stdio_notification_rejects_pending_request_without_hanging(self):
        from unittest.mock import AsyncMock, Mock
        client = AppServer(Path('/fixture/codex'))
        waiter = asyncio.get_running_loop().create_future()
        client.pending[1] = waiter
        process = Mock(stdout=Mock(readline=AsyncMock(side_effect=[b'[]\n'])))
        await client._drain(process)
        with self.assertRaises(ConnectionError):
            await waiter

    async def test_failed_initialize_cleans_owned_process_then_fresh_read_initializes(self):
        from unittest.mock import AsyncMock, Mock

        def version_process():
            return self.version_process()

        def server_process():
            process = Mock(returncode=None, wait=AsyncMock(return_value=-15))
            process.terminate.side_effect = lambda: setattr(process, 'returncode', -15)
            return process

        first, second = server_process(), server_process()
        client = AppServer(Path('/fixture/codex'))
        requests = []
        async def exchange(method, params):
            requests.append(method)
            if requests == ['initialize']:
                raise RuntimeError('fixture initialization rejection')
            if method == 'initialize': return {'codexHome': '/fixture/codex'}
            return {'thread': {'id': THREAD}}
        async def drain(process):
            await asyncio.Event().wait()
        client._exchange = exchange
        client._write = AsyncMock()
        client._drain = drain
        with patch('adapters.codex_task_imagegen.asyncio.create_subprocess_exec',
                   side_effect=[version_process(), first, version_process(), second]):
            try:
                with self.assertRaises(RuntimeError):
                    await client.request('turn/start', {'threadId': THREAD})
                self.assertIsNone(client.process)
                self.assertIsNone(client.reader)
                first.terminate.assert_called_once()
                result = await client.request('thread/read', {'threadId': THREAD})
                self.assertEqual(THREAD, result['thread']['id'])
                self.assertEqual(['initialize', 'initialize', 'thread/read'], requests)
            finally:
                await client.close()

    async def test_home_mismatch_notification_failure_and_cancellation_reset_ready(self):
        from unittest.mock import AsyncMock, Mock

        for stage, error in [('home', DomainError), ('notification', ConnectionError),
                             ('cancelled', asyncio.CancelledError), ('disconnected', ConnectionError)]:
            with self.subTest(stage=stage):
                client = AppServer(Path('/fixture/codex'))
                version = self.version_process()
                process = Mock(returncode=None, wait=AsyncMock(return_value=-15))
                process.terminate.side_effect = lambda: setattr(process, 'returncode', -15)
                client._exchange = AsyncMock(return_value={'codexHome':
                    '/wrong/home' if stage == 'home' else '/fixture/codex'})
                if stage == 'cancelled': client._exchange.side_effect = asyncio.CancelledError()
                if stage == 'disconnected': client._exchange.side_effect = ConnectionError()
                client._write = AsyncMock(side_effect=ConnectionError() if stage == 'notification' else None)
                async def drain(process):
                    await asyncio.Event().wait()
                client._drain = drain
                with patch('adapters.codex_task_imagegen.asyncio.create_subprocess_exec',
                           side_effect=[version, process]):
                    with self.assertRaises(error):
                        await client.request('thread/read', {'threadId': THREAD})
                self.assertFalse(client.initialized)
                self.assertIsNone(client.process)
                self.assertIsNone(client.reader)
                process.terminate.assert_called_once()
                self.assertEqual(1, client._exchange.await_count)


class SecureTraversalTests(unittest.TestCase):
    def test_read_pins_ancestors_with_opath_but_reads_final_file(self):
        from adapters.codex_task_imagegen import _read
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'file.bin'
            path.write_bytes(b'fixture')
            original = os.open
            calls = []
            def record_open(path, flags, *args, **kwargs):
                calls.append((str(path), flags))
                return original(path, flags, *args, **kwargs)
            with patch('adapters.codex_task_imagegen.os.open', side_effect=record_open):
                self.assertEqual(b'fixture', _read(path, 100))
            self.assertEqual('/', calls[0][0])
            for _path, flags in calls[:-1]:
                self.assertTrue(flags & os.O_PATH)
                self.assertTrue(flags & os.O_DIRECTORY)
                self.assertTrue(flags & os.O_NOFOLLOW)
            self.assertFalse(calls[-1][1] & os.O_PATH)
            self.assertTrue(calls[-1][1] & os.O_NOFOLLOW)

    @unittest.skipUnless(hasattr(os, 'O_PATH'), 'Linux O_PATH required')
    def test_execute_only_ancestor_needs_traversal_not_directory_listing(self):
        from adapters.codex_task_imagegen import _read
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / 'execute-only'
            parent.mkdir()
            path = parent / 'file.bin'; path.write_bytes(b'fixture')
            parent.chmod(0o111)
            try:
                try:
                    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                except PermissionError:
                    pass
                else:
                    os.close(descriptor)
                    self.skipTest('runtime privileges bypass execute-only directory restriction')
                self.assertEqual(b'fixture', _read(path, 100))
            finally:
                parent.chmod(0o700)


from adapters import codex_task_imagegen as module

class ReadRpcFixture(module.AppServer):
    """Actual request/_exchange boundary, fake JSON-RPC replies; no subprocess."""
    def __init__(self, home, native, errors=1, malformed=None):
        super().__init__(home);self.native=native;self.errors=errors;self.malformed=malformed;self.calls=[]
    async def _start(self):pass
    async def _write(self,payload):
        assert payload['method']=='thread/read', 'read recovery cannot submit/start/resume/interrupt'
        self.calls.append((payload['method'],payload['params']))
        if self.malformed is not None:reply=self.malformed
        elif self.errors:
            self.errors-=1;reply={'error':{'code':-32600,'message':'PRIVATE_READ_REJECTION_FIXTURE'}}
        else:reply={'result':{'thread':{'id':THREAD,'turns':[{'id':TURN,'status':self.native.status,'items':self.native.items}]}}}
        self.pending[payload['id']].set_result(reply)
    async def close(self):pass

class NativeReadRpcContract(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=CodexTaskTests.asyncSetUp
    asyncTearDown=CodexTaskTests.asyncTearDown
    async def test_actual_request_rejection_retries_only_saved_read_then_imports(self):
        key=await self.adapter.submit(self.request)
        rpc=ReadRpcFixture(self.home,self.native);self.adapter.transport=rpc
        with patch.object(module,'THREAD_READ_BACKOFF',(.001,.002)):
            observed=await self.adapter.inspect(key)
        self.assertEqual(observed.state,'succeeded')
        self.assertEqual(rpc.calls,[('thread/read',{'threadId':THREAD,'includeTurns':True})]*2)
        self.assertEqual(sum(m=='turn/start' for m,_ in self.native.calls),1)
        self.assertEqual(len(observed.artifacts),1)
        self.assertNotIn('PRIVATE_READ_REJECTION',json.dumps(self.adapter._load(self.adapter._directory(key))))
    async def test_closed_rejections_remain_pending_until_later_same_turn_completed(self):
        key=await self.adapter.submit(self.request);directory=self.adapter._directory(key)
        initial=self.adapter._load(directory);rpc=ReadRpcFixture(self.home,self.native,errors=3);self.adapter.transport=rpc
        with patch.object(module,'THREAD_READ_BACKOFF',(.001,.002)):
            first=await self.adapter.inspect(key)
            self.assertEqual(first.state,'running')
            receipt=self.adapter._load(directory)
            self.assertEqual(receipt['deadline'],initial['deadline'])
            self.assertEqual(receipt['thread_id'],THREAD);self.assertEqual(receipt['turn_id'],TURN)
            await self.adapter.submit(self.request)
            recovered=await self.adapter.find(key)
        self.assertEqual(recovered.state,'succeeded')
        self.assertEqual(len(rpc.calls),4);self.assertTrue(all(m=='thread/read' for m,_ in rpc.calls))
        self.assertEqual(sum(m=='turn/start' for m,_ in self.native.calls),1)
        self.assertEqual(sum(m=='thread/start' for m,_ in self.native.calls),1)
    async def test_expired_or_interrupt_intent_rejection_never_remains_running(self):
        key=await self.adapter.submit(self.request);directory=self.adapter._directory(key)
        for field,value in [('deadline',0),('phase','interrupt_pending')]:
            original=self.adapter._load(directory);record=dict(original);record[field]=value;self.adapter._record(directory,record)
            rpc=ReadRpcFixture(self.home,self.native,errors=3);self.adapter.transport=rpc
            with patch.object(module,'THREAD_READ_BACKOFF',(.001,.002)):
                observed=await self.adapter.inspect(key)
            self.assertEqual(observed.state,'unknown')
            self.assertEqual(len(rpc.calls),3)
            self.adapter._record(directory,original)
    async def test_invalid_rpc_result_is_distinct_and_not_retried_or_pending(self):
        key=await self.adapter.submit(self.request)
        for malformed in [{'result':None},{'error':{'message':'malformed'}},{'result':{},'error':{'code':-1,'message':'ambiguous'}}]:
            rpc=ReadRpcFixture(self.home,self.native,malformed=malformed);self.adapter.transport=rpc
            observed=await self.adapter.inspect(key)
            self.assertEqual(observed.state,'unknown');self.assertEqual(len(rpc.calls),1)
            with self.assertRaises(DomainError) as rejected:await rpc.request('thread/read',{'threadId':THREAD,'includeTurns':True})
            self.assertEqual(rejected.exception.code,'codex_task_protocol_invalid')
