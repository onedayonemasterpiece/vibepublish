"""Passive discovery never becomes proof of runtime availability."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('imagegen_inventory', Path(__file__).resolve().parents[2] / 'scripts/inspect/probe_imagegen_plugin.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def put(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data)
    return target


def test_empty_host_does_not_disprove_owner_installation(tmp_path):
    report = MODULE.inventory(tmp_path)
    assert report['tool_callable'] == 'not_probed'
    assert report['owner_installation_identity'] == 'not_verified'
    assert report['generation_invoked'] is False
    assert report['canary'] == 'not_run'


def test_codex_skill_is_not_a_callable_tool(tmp_path):
    put(tmp_path, '.codex/skills/.system/imagegen/SKILL.md', '---\nname: "imagegen"\n---\nUse image_gen')
    report = MODULE.inventory(tmp_path)
    assert report['codex_skills'][0]['imagegen_name_declared']
    assert report['codex_skills'][0]['builtin_tool_mentioned']
    assert report['codex_skills'][0]['evidence'] == 'file_only'
    assert report['tool_callable'] == 'not_probed'


def test_jsonc_registrations_and_sensitive_options(tmp_path):
    put(tmp_path, '.config/opencode/opencode.jsonc', '''{
      // comment
      "$schema": "https://opencode.ai/config.json",
      "plugin": ["opencode-gpt-imagegen@0.1.12", "other-plugin",],
      "provider": {"apiKey": "PRIVATE_TOKEN"}, /* other config */
    }''')
    report = MODULE.inventory(tmp_path)
    assert [x['package'] for x in report['opencode_registrations']] == ['opencode-gpt-imagegen@0.1.12']
    assert 'PRIVATE_TOKEN' not in json.dumps(report)


def test_installed_package_and_its_origin(tmp_path):
    put(tmp_path, '.cache/opencode/node_modules/opencode-gpt-imagegen/package.json', json.dumps({
        'name': 'opencode-gpt-imagegen', 'version': '0.1.12',
        'repository': {'url': 'git+https://github.com/yuji-hatakeyama/opencode-gpt-imagegen.git'},
        'scripts': {'postinstall': 'DO_NOT_EXECUTE'},
    }))
    report = MODULE.inventory(tmp_path)
    entry = report['opencode_packages'][0]
    assert entry['version'] == '0.1.12'
    assert entry['repository'] == 'yuji-hatakeyama/opencode-gpt-imagegen'
    assert entry['evidence'] == 'manifest_only_not_loaded'
    assert 'DO_NOT_EXECUTE' not in json.dumps(report)


def test_auth_files_are_not_opened(tmp_path, monkeypatch):
    for path in ('.codex/auth.json', '.local/share/opencode/auth.json'):
        put(tmp_path, path, 'VERY_PRIVATE_AUTH')
    original = os.open
    def guarded(path, flags, *args, **kwargs):
        assert Path(path).name != 'auth.json'
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guarded)
    report = MODULE.inventory(tmp_path)
    assert report['auth_files_read'] is False
    assert 'VERY_PRIVATE_AUTH' not in json.dumps(report)


def test_local_plugin_is_hashed_not_executed_or_dumped(tmp_path):
    put(tmp_path, '.config/opencode/plugins/imagegen.ts', 'throw new Error("PRIVATE_VALUE"); // gpt_imagegen')
    report = MODULE.inventory(tmp_path)
    assert report['local_plugin_sources'][0]['evidence'] == 'lexical_only_not_loaded'
    assert 'PRIVATE_VALUE' not in json.dumps(report)


def test_project_registration_detected(tmp_path):
    project = tmp_path/'project'
    put(project, 'opencode.json', '{"plugin":["@mine/imagegen"]}')
    report = MODULE.inventory(tmp_path/'home', project)
    assert report['opencode_registrations'][0]['package'] == '@mine/imagegen'


@pytest.mark.parametrize('contents', ['{"plugin": [', '[]', '{"plugin": {}}', '/* unclosed', '\ufeff{"plugin":42}'])
def test_malformed_config_sanitized(tmp_path, contents):
    put(tmp_path, '.config/opencode/opencode.jsonc', contents)
    report = MODULE.inventory(tmp_path)
    assert any(x['result'] == 'invalid_config' for x in report['checks'])


@pytest.mark.parametrize('reference', ['https://PRIVATE_TOKEN@example.com/imagegen', 'file:///PRIVATE/imagegen.ts', 'imagegen;touch /tmp/BAD'])
def test_non_package_registration_not_echoed(tmp_path, reference):
    put(tmp_path, '.config/opencode/opencode.json', json.dumps({'plugin': [reference]}))
    report = MODULE.inventory(tmp_path)
    assert not report['opencode_registrations']
    assert reference not in json.dumps(report)


def test_symlink_and_hardlink_skipped(tmp_path):
    secret = put(tmp_path, 'auth.json', 'PRIVATE_TOKEN')
    target = tmp_path/'.config/opencode/opencode.json'
    target.parent.mkdir(parents=True)
    target.symlink_to(secret)
    report = MODULE.inventory(tmp_path)
    assert any(x['result'] == 'symlink_skipped' for x in report['checks'])
    target.unlink()
    os.link(secret, target)
    report = MODULE.inventory(tmp_path)
    assert any(x['result'] == 'nonregular_or_hardlink_skipped' for x in report['checks'])
    assert 'PRIVATE_TOKEN' not in json.dumps(report)


def test_oversized_file_is_bounded(tmp_path):
    put(tmp_path, '.config/opencode/opencode.json', 'x'*(MODULE.MAX_BYTES+1))
    assert any(x['result'] == 'oversized' for x in MODULE.inventory(tmp_path)['checks'])


def test_repository_credentials_and_version_injection_not_exported(tmp_path):
    put(tmp_path, '.cache/opencode/node_modules/opencode-gpt-imagegen/package.json', json.dumps({
        'name': 'opencode-gpt-imagegen', 'version': 'PRIVATE_TOKEN',
        'repository': 'https://PRIVATE_TOKEN@github.com/owner/repo',
    }))
    report = MODULE.inventory(tmp_path)
    assert report['opencode_packages'][0]['repository'] is None
    assert report['opencode_packages'][0]['version'] is None
    assert 'PRIVATE_TOKEN' not in json.dumps(report)


@pytest.mark.parametrize('value', ['https://x/y//z', 'bracket ,] comma ,}', 'quote \\" // kept'])
def test_jsonc_strings_preserved(value):
    assert MODULE._jsonc(json.dumps({'value': value}).encode())['value'] == value
