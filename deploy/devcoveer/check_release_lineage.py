#!/usr/bin/env python3
"""Refuse a production deploy that would silently drop running code.

Run before switching the VibePublish units to a new release:

  python3 deploy/devcoveer/check_release_lineage.py --candidate <sha> [--repo <checkout>]

Checks, against the freshly fetched remote:
  1. the candidate is contained in origin/main (production is deployed from main only);
  2. every release the server and worker run now is an ancestor of the candidate.
A failure exits 2 and names the commits that would be lost. See
docs/reports/incidents/INC-2026-10-18-main-deploy-dropped-street-story-original-frame.md.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

UNITS = ('vibepublish.service', 'vibepublish-worker.service')
RELEASE = re.compile(r'/vibepublish/releases/([0-9a-f]{40})/source')


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)


def running_releases() -> dict[str, str]:
    found = {}
    for unit in UNITS:
        out = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'MainPID', '--value'],
                             capture_output=True, text=True).stdout.strip()
        if not out or out == '0':
            continue
        cmdline = Path(f'/proc/{out}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
        match = RELEASE.search(cmdline)
        if match:
            found[unit] = match.group(1)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    if git(args.repo, 'fetch', '-q', 'origin', 'main').returncode != 0:
        print('lineage: cannot fetch origin/main', file=sys.stderr)
        return 2
    candidate = git(args.repo, 'rev-parse', '--verify', args.candidate + '^{commit}').stdout.strip()
    if not candidate:
        print(f'lineage: unknown candidate {args.candidate}', file=sys.stderr)
        return 2
    failed = False
    if git(args.repo, 'merge-base', '--is-ancestor', candidate, 'origin/main').returncode != 0:
        print(f'lineage: candidate {candidate[:7]} is not in origin/main; merge it first', file=sys.stderr)
        failed = True
    releases = running_releases()
    if not releases:
        print('lineage: no running VibePublish release found', file=sys.stderr)
        return 2
    for unit, sha in releases.items():
        if git(args.repo, 'merge-base', '--is-ancestor', sha, candidate).returncode != 0:
            lost = git(args.repo, 'log', '--oneline', f'{candidate}..{sha}').stdout.strip() or '(running commit unknown here)'
            print(f'lineage: {unit} runs {sha[:7]}, not contained in {candidate[:7]}; would drop:\n{lost}',
                  file=sys.stderr)
            failed = True
        else:
            print(f'lineage: {unit} {sha[:7]} is contained in {candidate[:7]}')
    if failed:
        return 2
    print(f'lineage: ok, {candidate[:7]} is in origin/main and keeps the running code')
    return 0


if __name__ == '__main__':
    sys.exit(main())
