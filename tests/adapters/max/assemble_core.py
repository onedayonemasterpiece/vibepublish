"""Verify the owner ZIP and assemble a LOCAL test tree; never pushes core code."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ZIP_SHA = '5651e09a046806b0bfd1fcfb7a92998c22fd9e1c902e1d7f28b53db5fdbe1933'
PORT_SHA = '4304a47116da01e267b0dd324b26e7fdae58a66c0bbd75617eb9cbb464015bf0'
CORE_HEAD = '870e2a4304c57ef5dd7152de63df1db6431a942b'


def assemble(archive, output):
    archive, output = Path(archive), Path(output)
    repo = Path(__file__).resolve().parents[3]
    # Never write core into a tracked checkout or any arbitrary user directory.
    if not output.resolve().is_relative_to((repo/'artifacts').resolve()) or output.exists():
        raise ValueError('Choose a NEW output directory under this MAX worktree artifacts/')
    data = archive.read_bytes()
    assert len(data) == 875577 and hashlib.sha256(data).hexdigest() == ZIP_SHA
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist()) == len(set(z.namelist()))
        m = json.loads(z.read('MANIFEST.json'))
        assert m['local_head'] == CORE_HEAD and len(m['files']) == 103
        assert hashlib.sha256(z.read('source/adapters/port.py')).hexdigest() == PORT_SHA
        assert hashlib.sha256(z.read('vibepublish-native-visual-20260905.patch')).hexdigest() == m['patch_sha256']
        for name, sha in m['payload_sha256'].items():
            assert hashlib.sha256(z.read(name)).hexdigest() == sha, name
        for name, sha in m['files'].items():
            assert hashlib.sha256(z.read('source/'+name)).hexdigest() == sha, name
            p = Path(name)
            assert not p.is_absolute() and '..' not in p.parts
        output.mkdir(parents=True)
        for name in m['files']:
            dest = output/name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read('source/'+name))
    for name in ('adapters/max', 'tests/adapters/max', 'tests/browser/max'):
        shutil.copytree(repo/name, output/name, ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
    # Every archived source stays byte-identical: only MAX-owned paths added.
    for name, sha in m['files'].items():
        assert hashlib.sha256((output/name).read_bytes()).hexdigest() == sha, name
    report = dict(zip_sha256=ZIP_SHA, core_head=CORE_HEAD, source_hashes_verified=103,
                  payload_hashes_verified=len(m['payload_sha256']), port_sha256=PORT_SHA,
                  patch_sha256=m['patch_sha256'], local_only=True)
    (output/'MAX_ASSEMBLY.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    print(json.dumps(assemble(args.archive, args.output), indent=2))
