"""Ordinary owner-authorized Codex tasks, not an image-only tool sandbox.

Uses native app-server image receipts and the user's Codex login/quota. Candidate
counts are prompt/output limits, not a guarantee about upstream billable calls.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time

from adapters.imagegen import ImagegenArtifact, ImagegenObservation, ImagegenRequest
from social_operations.assets import verify_image
from social_operations.domain import DomainError, OutcomeUnknown, canonical

MODEL = 'gpt-5.6-luna'
VERSION = 'codex-cli 0.153.0'
MAX_IMAGE = 20 * 1024 * 1024
MAX_SKILL = 64 * 1024
MAX_MESSAGE = 128 * 1024 * 1024
THREAD_READ_TIMEOUT = 3.0
THREAD_READ_BACKOFF = (0.25, 0.5)


def _private(path: Path):
    created = not path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    st = path.lstat()
    if path.resolve() != path or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise DomainError('codex_task_directory_not_private')
    if created:
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)


def _read(path: Path, limit: int) -> bytes:
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('unconfined path')
    # O_PATH pins directories without requiring listing/read permission.
    # Hardened systemd namespaces may expose execute-only ancestors.
    directory = os.open('/', os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory); directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as source:
            st = os.fstat(source.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid() or not 0 < st.st_size <= limit:
                raise ValueError('invalid file')
            data = source.read(limit + 1)
            if len(data) != st.st_size:
                raise ValueError('changed file')
            return data
    finally:
        os.close(directory)


def _save(path: Path, data: bytes):
    temporary = path.with_name('.' + path.name + '.' + secrets.token_hex(8))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def _exception_frames(exc):
    """Bounded private diagnostics: no exception text, locals or source lines."""
    frames = []
    current = exc.__traceback__
    while current is not None:
        frames.append({'file': Path(current.tb_frame.f_code.co_filename).name[:160],
            'line': current.tb_lineno, 'function': current.tb_frame.f_code.co_name[:160]})
        current = current.tb_next
    return {'class': type(exc).__name__[:160], 'frames': frames[-16:]}


class AppServer:
    """One owned, drained stdio process; never attaches to or kills a shared bot."""
    def __init__(self, codex_home: Path, binary='/home/dev/.local/bin/codex'):
        self.home, self.binary = Path(codex_home).absolute(), binary
        self.process = None
        self.reader = None
        self.pending = {}
        self.serial = 0
        self.start_lock = asyncio.Lock()
        self.initialized = False

    def environment(self):
        # Existing approved Codex auth is read by Codex, never by this adapter.
        # In particular OPENAI_API_KEY/CODEX_API_KEY and social env do not pass.
        return {'HOME': str(Path.home()), 'CODEX_HOME': str(self.home),
                'PATH': '/home/dev/.local/bin:/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'}

    async def _start(self):
        async with self.start_lock:
            if self.initialized and self.process is not None and self.process.returncode is None:
                return
            # An assigned process is not evidence of a successful handshake.
            # Clear stale or partly initialized owned state before a fresh call.
            if self.process is not None or self.reader is not None:
                await self.close()
            check = await asyncio.create_subprocess_exec(self.binary, '--version',
                env=self.environment(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                output, _ = await asyncio.wait_for(check.communicate(), 10)
            finally:
                if check.returncode is None:
                    check.kill(); await check.wait()
            if check.returncode or output.decode().strip() != VERSION:
                raise DomainError('codex_task_version_changed')
            self.process = await asyncio.create_subprocess_exec(self.binary, 'app-server', '--stdio',
                env=self.environment(), cwd=str(self.home), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=MAX_MESSAGE)
            self.reader = asyncio.create_task(self._drain(self.process))
            try:
                result = await self._exchange('initialize', {'clientInfo': {
                    'name': 'vibepublish-image-task', 'version': '1'},
                    'capabilities': {'experimentalApi': True}})
                if result.get('codexHome') != str(self.home):
                    raise DomainError('codex_task_home_mismatch')
                await self._write({'method': 'initialized', 'params': {}})
                self.initialized = True
            except BaseException:
                # Includes cancellation/timeouts during either handshake step.
                # Cleanup only our process, then propagate; never replay the
                # caller's request or silently restart an uncertain mutation.
                await self.close()
                raise

    async def _write(self, payload):
        if self.process is None or self.process.returncode is not None:
            raise ConnectionError('app-server unavailable')
        self.process.stdin.write((json.dumps(payload, ensure_ascii=False) + '\n').encode())
        await self.process.stdin.drain()

    async def _drain(self, process):
        try:
            while line := await process.stdout.readline():
                if len(line) > MAX_MESSAGE:
                    raise ValueError('oversize protocol message')
                message = json.loads(line)
                if 'id' in message and 'method' not in message:
                    waiter = self.pending.get(message['id'])
                    if waiter and not waiter.done(): waiter.set_result(message)
                elif 'id' in message:
                    # This ordinary task uses approvalPolicy=never and no client
                    # dynamic tools. Reject requests rather than silently hang.
                    await self._write({'id': message['id'], 'error': {
                        'code': -32601, 'message': 'Client request unsupported'}})
                # Always drain notifications, without storing private reasoning.
        except (OSError, ValueError, asyncio.CancelledError):
            pass
        finally:
            for waiter in list(self.pending.values()):
                if not waiter.done(): waiter.set_exception(ConnectionError('app-server disconnected'))

    async def _exchange(self, method, params):
        self.serial += 1
        ident = self.serial
        waiter = asyncio.get_running_loop().create_future()
        self.pending[ident] = waiter
        try:
            await self._write({'id': ident, 'method': method, 'params': params})
            response = await asyncio.wait_for(waiter, 30)
            if 'error' in response or not isinstance(response.get('result'), dict):
                raise RuntimeError('app-server request failed')
            return response['result']
        finally:
            self.pending.pop(ident, None)

    async def request(self, method, params):
        await self._start()
        # Never replay a request, especially thread/start or turn/start.
        return await self._exchange(method, params)

    async def close(self):
        self.initialized = False
        process, self.process = self.process, None
        if process and process.returncode is None:
            process.terminate()
            try: await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill(); await process.wait()
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
            self.reader = None


class CodexTaskImagegen:
    def __init__(self, root: Path, *, codex_home: Path | None = None,
                 timeout_seconds=600, transport=None):
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 1800:
            raise DomainError('codex_task_timeout_invalid')
        self.artifact_root = Path(root).absolute()
        self.control_root = self.artifact_root.parent / (self.artifact_root.name + '-tasks')
        _private(self.artifact_root); _private(self.control_root)
        self.codex_home = Path(codex_home or os.environ.get('CODEX_HOME', Path.home() / '.codex')).absolute()
        self.transport = transport or AppServer(self.codex_home)
        self.timeout = timeout_seconds
        self.timers = {}

    def _directory(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'visual_[a-f0-9]{32}', key):
            raise DomainError('imagegen_job_key_invalid')
        return self.control_root / key

    @contextmanager
    def _lock(self, directory):
        _private(directory)
        fd = os.open(directory / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise DomainError('codex_task_busy') from None
            yield
        finally: os.close(fd)

    def _record(self, directory, record):
        _save(directory / 'receipt.json', canonical(record).encode())

    def _load(self, directory):
        return json.loads(_read(directory / 'receipt.json', 65536))

    def _observation(self, record):
        return ImagegenObservation(record['job_key'], record['input_digest'], record['job_key'],
            record['state'], tuple(ImagegenArtifact(**x) for x in record.get('artifacts', [])),
            'codex-app-server-task', record.get('actual_model'),
            # VisualService's usage contract is numeric-only. Rich identities and
            # native path/hash receipts remain in the private task receipt.
            canonical({'candidate_limit': record['candidate_budget'],
                'native_images_completed': len(record.get('native_image_items', [])),
                'imported_artifacts': len(record.get('artifacts', []))}))

    def _validate(self, request):
        self._directory(request.job_key)
        if not re.fullmatch(r'[a-f0-9]{64}', request.input_digest):
            raise DomainError('imagegen_input_digest_invalid')
        if request.requested_route != MODEL:
            raise DomainError('imagegen_route_not_verified')
        if type(request.candidate_budget) is not int or not 1 <= request.candidate_budget <= 4:
            raise DomainError('imagegen_budget_invalid')
        if type(request.deadline) not in (int, float) or not math.isfinite(request.deadline) or request.deadline <= time.time():
            raise DomainError('imagegen_deadline_expired')
        if (request.mode not in ('generate', 'tune', 'compose') or not isinstance(request.brief, str)
                or not 1 <= len(request.brief) <= 32000 or len(request.sources) > 8
                or (request.mode == 'tune' and len(request.sources) != 1)
                or (request.mode == 'compose' and len(request.sources) < 2)):
            raise DomainError('imagegen_request_invalid')
        for source in request.sources:
            if len(source.data) != source.size or hashlib.sha256(source.data).hexdigest() != source.sha256:
                raise DomainError('imagegen_source_integrity')
            image = verify_image(source.data, source.mime)
            if (image.width, image.height) != (source.width, source.height):
                raise DomainError('imagegen_source_integrity')

    def _skill_context(self):
        path = self.codex_home / 'skills' / '.system' / 'imagegen' / 'SKILL.md'
        try:
            data = _read(path, MAX_SKILL)
            skill = data.decode('utf-8')
        except (OSError, ValueError):
            raise DomainError('codex_task_skill_unavailable', next_action='contact_owner') from None
        metadata = {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
        instructions = ('The trusted installed imagegen SKILL.md is fully preloaded below. '
            'It was read by the task executor, not supplied by the job caller.\n'
            '<installed_imagegen_skill>\n' + skill + '\n</installed_imagegen_skill>\n'
            'Task-specific execution context: the full skill above is already loaded. '
            'Use built-in image_gen directly on the existing Codex quota. Do not read the '
            'skill again or open supporting files. Attached localImage inputs are already '
            'visible in the conversation; use those visible references for tune/compose. '
            'No shell or filesystem commands are needed. Do not run shell reads or copies. '
            'The executor imports and verifies native saved images after completion, so '
            'leave outputs at their native generated_images paths. No CLI/API fallback, '
            'external provider, placeholder or programmatic replacement is authorized. '
            'Keep the existing sandbox unchanged. Follow the user brief and its quotations.')
        return instructions, metadata

    async def submit(self, request: ImagegenRequest):
        self._validate(request)
        directory = self._directory(request.job_key)
        with self._lock(directory):
            if (directory / 'receipt.json').exists():
                old = self._load(directory)
                if old['input_digest'] != request.input_digest:
                    raise DomainError('imagegen_idempotency_conflict')
                return request.job_key
            developer_instructions, skill_snapshot = self._skill_context()
            work = directory / 'work'; _private(work)
            source_inputs = []
            for index, source in enumerate(request.sources):
                extension = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[source.mime]
                path = work / f'source-{index}{extension}'
                _save(path, source.data)
                source_inputs.append({'type': 'localImage', 'path': str(path)})
            record = {'job_key': request.job_key, 'input_digest': request.input_digest,
                'candidate_budget': request.candidate_budget, 'state': 'unknown',
                'budget_policy': 'prompt_and_accepted_output_not_hard_upstream_call_cap',
                'skill_snapshot': skill_snapshot,
                'deadline': min(request.deadline, time.time() + self.timeout),
                'phase': 'thread_start_pending', 'thread_id': None, 'turn_id': None,
                'task_model': None, 'actual_model': None, 'artifacts': []}
            self._record(directory, record)  # durable before any uncertain remote write
            try:
                started = await self.transport.request('thread/start', {
                    'cwd': str(work), 'approvalPolicy': 'never', 'sandbox': 'workspace-write',
                    'threadSource': 'appServer', 'model': MODEL,
                    'developerInstructions': developer_instructions,
                    'config': {'forced_login_method': 'chatgpt', 'features.image_generation': True}})
                record['thread_id'] = started['thread']['id']
                if not isinstance(record['thread_id'], str) or not re.fullmatch(r'[a-f0-9-]{36}', record['thread_id']):
                    record['thread_id'] = None
                    raise ValueError('invalid thread identity')
                self._record(directory, record)
                if started.get('model') != MODEL or started.get('cwd') != str(work):
                    raise ValueError('unexpected task model or cwd')
                record['task_model'] = started['model']
                # Image model is not inferred from the orchestration model.
                if time.time() >= record['deadline']:
                    raise ValueError('deadline expired before turn start')
                record['phase'] = 'turn_start_pending'
                self._record(directory, record)
                prompt = ('Ordinary Codex image task. Use the built-in image_gen tool on the existing '
                    'Codex login/quota; no API fallback, external image provider, placeholder or '
                    'programmatically drawn replacement. Make exactly one image call per candidate, '
                    f'and {request.candidate_budget} candidates total. No retries or extra variants. '
                    'Use attached source images for the requested mode. Do not publish or access '
                    'social accounts. Follow the brief including quoted lettering; do not extract or '
                    'rewrite it. Stop after the requested images. Task data follows as JSON:\n' +
                    canonical({'mode': request.mode, 'brief': request.brief,
                        'preset_version': request.preset_version, 'candidate_budget': request.candidate_budget}))
                turn = await self.transport.request('turn/start', {'threadId': record['thread_id'],
                    'input': [{'type': 'text', 'text': prompt}, *source_inputs],
                    'cwd': str(work), 'approvalPolicy': 'never', 'model': MODEL})
                record['turn_id'] = turn['turn']['id']
                record['phase'], record['state'] = 'submitted', 'running'
            except asyncio.CancelledError:
                self._record(directory, record)
                raise
            except (OSError, RuntimeError, ValueError, TypeError, KeyError, DomainError, asyncio.TimeoutError):
                record['state'] = 'unknown'
            self._record(directory, record)
        if record['state'] == 'running':
            self.timers[request.job_key] = asyncio.create_task(self._expire(request.job_key, record['deadline']))
        return request.job_key

    async def _expire(self, key, deadline):
        await asyncio.sleep(max(0, deadline - time.time()))
        try: await self.cancel(key)
        except (OSError, RuntimeError, DomainError): pass

    def _import(self, record, turn):
        items = [x for x in turn.get('items', []) if x.get('type') == 'imageGeneration']
        if len(items) != record['candidate_budget']:
            raise ValueError('native candidate count mismatch')
        output = self.artifact_root / record['job_key']; _private(output)
        artifacts, receipts = [], []
        for index, item in enumerate(items):
            if item.get('status') != 'completed' or item.get('failure'):
                raise ValueError('native image not completed')
            native = self.codex_home / 'generated_images' / record['thread_id']
            path = Path(item.get('savedPath') or '')
            if not path.is_absolute() or path.parent != native or not re.fullmatch(r'[A-Za-z0-9_-]+\.png', path.name):
                raise ValueError('native image path outside saved thread')
            data = _read(path, MAX_IMAGE)
            result = item.get('result', '')
            if not isinstance(result, str) or len(result) > MAX_IMAGE * 4 // 3 + 8:
                raise ValueError('native result missing or oversized')
            native_bytes = base64.b64decode(result, validate=True)
            if data != native_bytes:
                raise ValueError('native receipt bytes mismatch')
            checked = verify_image(data, 'image/png')
            digest = hashlib.sha256(data).hexdigest()
            ref = f'{index}-{digest}.png'
            destination = output / ref
            if destination.exists():
                if _read(destination, MAX_IMAGE) != data: raise ValueError('changed imported image')
            else: _save(destination, data)
            artifacts.append(asdict(ImagegenArtifact(ref, digest, 'image/png', checked.width,
                checked.height, len(data))))
            receipts.append({'id': item['id'], 'saved_path': str(path), 'sha256': digest})
        record['artifacts'], record['native_image_items'] = artifacts, receipts

    async def find(self, job_key):
        directory = self._directory(job_key)
        if not (directory / 'receipt.json').exists(): return None
        return await self.inspect(job_key)

    async def _read_thread(self, directory, record):
        # Only this immutable-identity read is retried. Never retry submit,
        # turn/start, interruption, binding checks or artifact validation.
        for attempt in range(1 + len(THREAD_READ_BACKOFF)):
            record['last_thread_read_attempts'] = attempt + 1
            try:
                return await asyncio.wait_for(self.transport.request('thread/read', {
                    'threadId': record['thread_id'], 'includeTurns': True}), THREAD_READ_TIMEOUT)
            except (OSError, RuntimeError, asyncio.TimeoutError) as exc:
                record['last_thread_read_error'] = _exception_frames(exc)
                self._record(directory, record)
                if attempt == len(THREAD_READ_BACKOFF):
                    raise
                await asyncio.sleep(THREAD_READ_BACKOFF[attempt])

    async def inspect(self, execution_ref):
        directory = self._directory(execution_ref)
        if not (directory / 'receipt.json').exists(): raise OutcomeUnknown('imagegen_job_not_observed')
        with self._lock(directory):
            record = self._load(directory)
            if record['state'] in ('succeeded', 'failed') or not record.get('thread_id'):
                try:
                    return self._observation(record)
                except Exception as exc:
                    record['last_observation_error'] = _exception_frames(exc)
                    self._record(directory, record)
                    raise
            try:
                response = await self._read_thread(directory, record)
                thread = response['thread']
                if thread.get('id') != record['thread_id']: raise ValueError('thread mismatch')
                turns = thread.get('turns', [])
                if record.get('turn_id'):
                    turns = [t for t in turns if t.get('id') == record['turn_id']]
                # Dedicated newly created thread has exactly one authorized turn.
                if len(turns) != 1: raise ValueError('ambiguous or missing turn')
                turn = turns[0]
                record['turn_id'] = turn['id']
                if turn.get('status') == 'completed':
                    self._import(record, turn)
                    record['state'] = 'succeeded'
                elif turn.get('status') in ('failed', 'interrupted'):
                    record['state'] = 'failed'
                else:
                    record['state'] = 'running'
                if record['state'] == 'running' and time.time() >= record['deadline']:
                    self._record(directory, record)
                    await self.transport.request('turn/interrupt', {
                        'threadId': record['thread_id'], 'turnId': record['turn_id']})
                    record['state'] = 'unknown'
            except asyncio.CancelledError as exc:
                record['state'] = 'unknown'
                record['last_observation_error'] = _exception_frames(exc)
                self._record(directory, record)
                raise
            except Exception as exc:
                record['state'] = 'unknown'
                record['last_observation_error'] = _exception_frames(exc)
            self._record(directory, record)
            try:
                return self._observation(record)
            except Exception as exc:
                # Keep diagnostic evidence if dataclass/receipt conversion fails
                # after a successful native read; never substitute an artifact.
                record['last_observation_error'] = _exception_frames(exc)
                self._record(directory, record)
                raise

    async def cancel(self, execution_ref):
        observed = await self.inspect(execution_ref)
        if observed.state != 'running': return observed
        directory = self._directory(execution_ref)
        with self._lock(directory):
            record = self._load(directory)
            # Persist first: disconnect after dispatch never authorizes replay.
            record['state'] = 'unknown'; record['phase'] = 'interrupt_pending'
            self._record(directory, record)
            try:
                await self.transport.request('turn/interrupt', {
                    'threadId': record['thread_id'], 'turnId': record['turn_id']})
            except (OSError, RuntimeError, asyncio.TimeoutError): pass
            return self._observation(record)

    async def close(self):
        for timer in self.timers.values(): timer.cancel()
        await asyncio.gather(*self.timers.values(), return_exceptions=True)
        await self.transport.close()
