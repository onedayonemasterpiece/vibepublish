"""Offline dependency receipt and exact wheelhouse lock. No network or installs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename


def pins(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        req = Requirement(line)
        specs = list(req.specifier)
        name = canonicalize_name(req.name)
        if req.url or req.marker or req.extras or len(specs) != 1 or specs[0].operator != "==" or "*" in specs[0].version or name in result:
            raise ValueError("Expected one unique exact package pin per line")
        result[name] = specs[0].version
    if not result:
        raise ValueError("Empty dependency lock")
    return result


def wheel_lock(lock: Path, wheelhouse: Path) -> str:
    expected = pins(lock)
    found = {}
    for file in sorted(wheelhouse.glob("*.whl")):
        if file.is_symlink() or not file.is_file():
            raise ValueError("Not a regular wheel file")
        name, version, _, _ = parse_wheel_filename(file.name)
        if name not in expected or str(version) != expected[name] or name in found:
            raise ValueError("Unexpected, mismatched or duplicate wheel: " + file.name)
        found[name] = hashlib.sha256(file.read_bytes()).hexdigest()
    if set(expected) != set(found):
        raise ValueError("Missing wheel(s): " + ", ".join(sorted(set(expected)-set(found))))
    return "# Exact local wheelhouse only; built-wheel hashes are not public PyPI pins.\n" + "".join(
        f"{name}=={expected[name]} --hash=sha256:{found[name]}\n" for name in sorted(expected))


def check(lock: Path) -> dict:
    expected = pins(lock)
    observed = {canonicalize_name(d.metadata['Name']): d.version for d in metadata.distributions()}
    wrong = {name: dict(expected=version, actual=observed.get(name)) for name, version in expected.items()
             if observed.get(name) != version}
    extra = sorted(set(observed)-set(expected)-{'pip'})
    if wrong or extra:
        raise ValueError(json.dumps(dict(version_mismatches=wrong, unexpected_packages=extra)))
    return dict(packages=len(expected), lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
                versions={name: observed[name] for name in sorted(expected)},
                evidence="installed_versions_only_use_pip_check_for_dependency_consistency")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lock', type=Path)
    parser.add_argument('--wheelhouse', type=Path)
    args = parser.parse_args()
    if args.wheelhouse:
        print(wheel_lock(args.lock, args.wheelhouse), end='')
    else:
        print(json.dumps(check(args.lock), indent=2))


if __name__ == '__main__':
    main()
