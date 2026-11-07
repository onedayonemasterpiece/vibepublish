#!/usr/bin/env python3
"""Install or extend the owner's private on-disk reference bank; never publish."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from PIL import Image
from social_operations.carousel_references import validate_reference_entries


def install(catalog, images, database, principal=None):
    database = Path(database).resolve(strict=True)
    # Read identities only. Installation does not migrate or modify the live DB.
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        owners = [(t, p) for t, p, scopes in db.execute(
            'SELECT p.tenant_id,p.id,p.scopes FROM principals p JOIN tenants t ON t.id=p.tenant_id '
            'WHERE p.owner=1 AND p.active=1 AND t.active=1')
            if 'visual' in json.loads(scopes) and (principal is None or p == principal)]
    if len(owners) != 1:
        raise ValueError('Specify --principal for one active owner with visual scope')
    owner = dict(zip(('tenant_id', 'principal_id'), owners[0]))
    root = database.parent / 'carousel-references'
    if root.is_symlink():
        raise ValueError('Reference directory must not be a symlink')
    root.mkdir(mode=0o700, exist_ok=True)
    target = root / 'catalog.json'
    if target.is_symlink():
        raise ValueError('Catalog must not be a symlink')
    previous = json.loads(target.read_text()) if target.exists() else {'owner': owner, 'references': []}
    if previous.get('owner') != owner:
        raise ValueError('Existing reference bank belongs to a different owner')
    incoming = validate_reference_entries(json.loads(Path(catalog).read_text())['references'])
    combined = {row['id']: row for row in validate_reference_entries(previous['references'])}
    combined.update({row['id']: row for row in incoming})
    rows = validate_reference_entries(list(combined.values()))
    serialized = json.dumps({'owner': owner, 'references': rows}, ensure_ascii=False, indent=2)
    if len(serialized.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('Reference catalog exceeds the runtime 2 MiB limit')
    verified = {}
    for row in incoming:
        name = row['file']
        if not name or Path(name).name != name or name in {'.', '..'}:
            raise ValueError('Reference file must be a basename')
        source, destination = Path(images) / name, root / name
        if source.is_symlink() or destination.is_symlink():
            raise ValueError('Reference file must not be a symlink')
        data = source.read_bytes()
        if not 0 < len(data) <= 20 * 1024 * 1024:
            raise ValueError('Reference image exceeds the private image limit')
        with Image.open(source) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > 25_000_000:
                raise ValueError('Unsupported reference image')
            image.verify()
        sha = hashlib.sha256(data).hexdigest()
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != sha:
            raise ValueError('Existing image differs; give the new reference a new filename')
        verified[name] = (data, sha)
    for name, (data, _) in verified.items():
        destination = root / name
        if not destination.exists():
            with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as out:
                out.write(data)
    pending = root / 'catalog.json.pending'
    with os.fdopen(os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
        out.write(serialized)
    os.replace(pending, target)
    return {'references': len(combined), 'files': len({r['file'] for r in combined.values()}),
            'verified_sha256': {name: sha for name, (_, sha) in verified.items()}, 'private': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--principal')
    args = parser.parse_args()
    print(json.dumps(install(args.catalog, args.images, args.db, args.principal)))
