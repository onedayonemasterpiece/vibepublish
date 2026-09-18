#!/usr/bin/env python3
"""Passive imagegen installation inventory; never imports plugins or opens auth.

Run on the actual Codex/OpenCode host. A file/config match is installation
metadata, NOT a live tool/capability/canary result. Output contains only selected
names, versions, canonical repository identities and content hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

MAX_BYTES = 256 * 1024
MAX_ENTRIES = 64
PACKAGE = re.compile(r"(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+(?:@[a-zA-Z0-9_.^~+-]+)?\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]+)?\Z")
REPOSITORY = re.compile(r"(?:git\+)?https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?\Z")
SYMBOLS = ('imagegen', 'image_gen', 'gpt_imagegen', 'image_generation')


def _read(path: Path, root: Path) -> tuple[bytes | None, str]:
    """Bounded regular-file read, refusing symlink components and hardlinks."""
    try:
        relative = path.relative_to(root)
        if '..' in relative.parts or root.is_symlink():
            return None, 'unsafe_path'
        current = root
        for part in relative.parts:
            current = current / part
            if stat.S_ISLNK(current.lstat().st_mode):
                return None, 'symlink_skipped'
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                return None, 'nonregular_or_hardlink_skipped'
            if metadata.st_size > MAX_BYTES:
                return None, 'oversized'
            data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return None, 'oversized'
            return data, 'read'
    except FileNotFoundError:
        return None, 'absent'
    except (OSError, ValueError):
        # Never print exceptions: they can contain private paths or payloads.
        return None, 'unreadable'


def _jsonc(data: bytes) -> Any:
    """Strip comments/trailing commas outside strings, not URLs within strings."""
    text = data.decode('utf-8-sig')
    result: list[str] = []
    index = 0
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if char == '\\':
                index += 1
                if index < len(text):
                    result.append(text[index])
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            result.append(char)
        elif text.startswith('//', index):
            end = text.find('\n', index + 2)
            index = len(text) if end < 0 else end
            result.append('\n')
            continue
        elif text.startswith('/*', index):
            end = text.find('*/', index + 2)
            if end < 0:
                raise ValueError('invalid_jsonc')
            result.append(' ')
            index = end + 2
            continue
        else:
            result.append(char)
        index += 1
    clean = ''.join(result)
    result = []
    index = 0
    in_string = False
    while index < len(clean):
        char = clean[index]
        if in_string:
            result.append(char)
            if char == '\\':
                index += 1
                if index < len(clean):
                    result.append(clean[index])
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            if char == ',':
                rest = clean[index + 1:].lstrip()
                if rest.startswith(('}', ']')):
                    index += 1
                    continue
            result.append(char)
        index += 1
    return json.loads(''.join(result))


def _json_object(data: bytes) -> dict[str, Any]:
    value = _jsonc(data)
    if not isinstance(value, dict):
        raise ValueError('object_required')
    return value


def _name(value: Any) -> str | None:
    if isinstance(value, str) and len(value) <= 160 and PACKAGE.fullmatch(value):
        return value
    return None


def inventory(home: Path, project: Path | None = None) -> dict[str, Any]:
    """Observe only specified roots. No arbitrary glob/recursive home traversal."""
    home = Path(os.path.abspath(home))
    roots = [('home', home)]
    if project is not None:
        roots.append(('project', Path(os.path.abspath(project))))
    report: dict[str, Any] = {
        'format': 'vibepublish.imagegen.inventory.v1',
        'scope': 'current_host_only',
        'generation_invoked': False,
        'auth_files_read': False,
        'tool_callable': 'not_probed',
        'owner_installation_identity': 'not_verified',
        'canary': 'not_run',
        'codex_skills': [], 'opencode_registrations': [],
        'opencode_packages': [], 'local_plugin_sources': [], 'checks': [],
    }

    def read(label: str, root: Path, relative: str) -> bytes | None:
        data, outcome = _read(root / relative, root)
        report['checks'].append({'location': f'{label}/{relative}', 'result': outcome})
        return data

    for label, root in roots:
        skill_dirs = ('.codex/skills/.system/imagegen', '.agents/skills/imagegen') if label == 'home' else ('.agents/skills/imagegen', '.codex/skills/imagegen')
        for directory in skill_dirs:
            data = read(label, root, directory + '/SKILL.md')
            if data is not None:
                text = data.decode('utf-8', errors='replace')
                report['codex_skills'].append({
                    'location': f'{label}/{directory}/SKILL.md',
                    'sha256': hashlib.sha256(data).hexdigest(),
                    'imagegen_name_declared': bool(re.search(r'^name:\s*["\x27]?imagegen["\x27]?\s*$', text, re.M)),
                    'builtin_tool_mentioned': 'image_gen' in text,
                    'evidence': 'file_only',
                })
        config_dirs = ('.config/opencode',) if label == 'home' else ('.', '.opencode')
        for directory in config_dirs:
            for filename in ('opencode.json', 'opencode.jsonc'):
                relative = str(Path(directory) / filename)
                data = read(label, root, relative)
                if data is None:
                    continue
                try:
                    plugins = _json_object(data).get('plugin', [])
                    if not isinstance(plugins, list):
                        raise ValueError('invalid_plugin_list')
                    for entry in plugins[:MAX_ENTRIES]:
                        # Options may contain credentials. Deliberately ignore them.
                        name = _name(entry if isinstance(entry, str) else None)
                        if name and ('image' in name or 'codex' in name):
                            report['opencode_registrations'].append({
                                'location': f'{label}/{relative}', 'package': name,
                                'evidence': 'configuration_only',
                            })
                except (ValueError, UnicodeError, RecursionError):
                    report['checks'].append({'location': f'{label}/{relative}', 'result': 'invalid_config'})
        package_roots = ('.cache/opencode/node_modules', '.config/opencode/node_modules') if label == 'home' else ('.opencode/node_modules', 'node_modules')
        # Only the researched candidate. Other implementations are NOT identified
        # as this package just because their name or source contains imagegen.
        for package_root in package_roots:
            relative = package_root + '/opencode-gpt-imagegen/package.json'
            data = read(label, root, relative)
            if data is None:
                continue
            try:
                manifest = _json_object(data)
                if manifest.get('name') != 'opencode-gpt-imagegen':
                    raise ValueError('name_mismatch')
                version = manifest.get('version')
                repository = manifest.get('repository', {})
                url = repository.get('url') if isinstance(repository, dict) else repository
                match = REPOSITORY.fullmatch(url) if isinstance(url, str) else None
                report['opencode_packages'].append({
                    'location': f'{label}/{relative}',
                    'name': 'opencode-gpt-imagegen',
                    'version': version if isinstance(version, str) and VERSION.fullmatch(version) else None,
                    'repository': '/'.join(match.groups()) if match else None,
                    'manifest_sha256': hashlib.sha256(data).hexdigest(),
                    'evidence': 'manifest_only_not_loaded',
                })
            except (ValueError, UnicodeError, RecursionError):
                report['checks'].append({'location': f'{label}/{relative}', 'result': 'invalid_manifest'})
        plugin_directory = '.config/opencode/plugins' if label == 'home' else '.opencode/plugins'
        target = root / plugin_directory
        try:
            # No recurse, import, or evaluation of JavaScript/TypeScript.
            if not any(parent.is_symlink() for parent in (target, *target.parents)):
                for path in sorted(target.iterdir())[:MAX_ENTRIES]:
                    if path.suffix not in {'.ts', '.js', '.mjs'}:
                        continue
                    data, outcome = _read(path, root)
                    if data is None:
                        continue
                    text = data.decode('utf-8', errors='replace')
                    symbols = [symbol for symbol in SYMBOLS if symbol in text]
                    if symbols:
                        report['local_plugin_sources'].append({
                            # File names can be private too; export only a digest.
                            'location': f'{label}/{plugin_directory}/<matched-source>',
                            'sha256': hashlib.sha256(data).hexdigest(),
                            'symbols_seen': symbols, 'evidence': 'lexical_only_not_loaded',
                        })
        except OSError:
            pass
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home(), help='Actual host home; metadata only')
    parser.add_argument('--project', type=Path, help='Optional actual project root')
    args = parser.parse_args()
    print(json.dumps(inventory(args.home, args.project), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
