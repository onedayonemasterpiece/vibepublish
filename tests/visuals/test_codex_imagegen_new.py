"""New adapter edge regressions; offline only, no model or live tool invocation."""
import asyncio
import json
from pathlib import Path

import pytest

from adapters.codex_imagegen import _json, _read, configured_codex
from social_operations.domain import DomainError
from tests.visuals.test_codex_imagegen import count, executor, request


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'candidate_budget': True}, {'deadline': float('nan')},
    {'deadline': float('inf')}, {'brief': ''}, {'input_digest': 'not-a-digest'},
])
async def test_new_validation_is_predispatch(tmp_path, change):
    ex = executor(tmp_path)
    with pytest.raises(DomainError):
        await ex.submit(request(**change))
    assert count(tmp_path) == 0


def test_duplicate_json_and_symlink_parent_rejected(tmp_path):
    with pytest.raises(ValueError):
        _json('{"command": [], "command": ["another"]}')
    real = tmp_path / 'real'
    real.mkdir()
    (real / 'file').write_bytes(b'bytes')
    link = tmp_path / 'linked'
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError):
        _read(link / 'file', 20)


class _Input:
    def write(self, data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass


class _Process:
    def __init__(self, events):
        self.stdin = _Input()
        self.stdout = asyncio.StreamReader()
        for event in events:
            self.stdout.feed_data(json.dumps(event).encode() + b'\n')
        self.stdout.feed_eof()
        self.returncode = 0

    async def wait(self):
        return 0


def events(report):
    return [
        {'type': 'thread.started', 'thread_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'},
        {'type': 'turn.started'},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Starting image task.'}},
        {'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'Never stored'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(report)}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 1}},
    ]


@pytest.mark.asyncio
async def test_only_final_completed_message_is_report_and_no_reasoning_persists(tmp_path):
    report = {'job_key': request().job_key, 'input_digest': request().input_digest, 'saved_paths': []}
    evidence = await executor(tmp_path)._collect(_Process(events(report)), 'offline')
    assert evidence['report'] == report
    assert 'Never stored' not in json.dumps(evidence)
    assert 'Starting image' not in json.dumps(evidence)


@pytest.mark.asyncio
async def test_unknown_native_event_is_not_fabricated_attestation(tmp_path):
    stream = events({})
    stream.insert(2, {'type': 'item.completed', 'item': {'type': 'image_generation', 'saved_path': '/somewhere'}})
    with pytest.raises(ValueError, match='unverified tool event'):
        await executor(tmp_path)._collect(_Process(stream), 'offline')


def test_private_config_cannot_enable_fixture_command_arguments(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({
        'command': ['/usr/bin/python', '-c', 'print(1)'], 'codex_home': str(tmp_path / 'home'),
        'expected_version': 'fixture', 'profile': 'image-only', 'allowed_routes': ['gpt-5.6-luna'],
        'attestation_ref': 'a' * 64, 'image_only_isolation_verified': True,
    }))
    config.chmod(0o600)
    with pytest.raises(DomainError, match='codex host config invalid'):
        configured_codex(tmp_path / 'outputs', config)
    assert not (tmp_path / 'outputs').exists()


@pytest.mark.asyncio
async def test_unknown_diagnostics_are_bounded_not_raw_provider_text(tmp_path):
    ex = executor(tmp_path, 'bad_json')
    ref = await ex.submit(request())
    assert (await ex.inspect(ref)).state == 'unknown'
    evidence = json.loads((ex.control_root / ref / 'events-evidence.json').read_text())
    assert set(evidence) == {'outcome', 'failure_class', 'local_exit_code'}
    assert evidence['outcome'] == 'unknown'
    assert evidence['failure_class'] == 'JSONDecodeError'
    assert 'not json' not in json.dumps(evidence)
