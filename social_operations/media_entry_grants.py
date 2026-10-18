"""Exact-entry read-only grants. No model-facing administration or list sharing."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict

from adapters.port import downloaded_media

from .domain import DomainError, canonical, new_id


def _denied():
    raise DomainError('access_denied', next_action='contact_owner')


def _entry(db, tenant, entry_ref):
    return db.execute(
        "SELECT p.*,r.intent,f.id AS fact_id,f.destination_id,f.snapshot FROM publications p "
        "JOIN revisions r ON r.publication_id=p.id AND r.revision=p.revision "
        "JOIN facts f ON f.publication_id=p.id "
        "WHERE p.id=? AND p.tenant_id=? AND p.kind='media_store' "
        "ORDER BY f.observed_at DESC LIMIT 1", (entry_ref, tenant)).fetchone()


def _legacy_origin(origin, topic):
    return (isinstance(origin, dict) and set(origin) == {'system', 'ref'}
            and origin.get('system') == 'regional_knowledge' and topic == '4'
            and isinstance(origin.get('ref'), str)
            and re.fullmatch(r'knowledge://illustrations/[0-9a-f]{8}-[0-9a-f]{4}-'
                             r'[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', origin['ref']))


def _single_image_evidence(values):
    if not isinstance(values, (list, tuple)) or len(values) != 1:
        _denied()
    if isinstance(values[0], dict) and set(values[0]) != {'kind', 'slot', 'sha256', 'mime', 'size'}:
        _denied()
    try:
        evidence, = downloaded_media(values)
    except (TypeError, ValueError, DomainError):
        _denied()
    if evidence.mime not in {'image/png', 'image/jpeg', 'image/webp'}:
        _denied()
    return asdict(evidence)


def proof_sha256(proof):
    """Explicit proof formats only; never guess a digest from a different role."""
    if 'proof_kind' not in proof:
        origin = proof.get('origin', {})
        sha = origin.get('sha256') if isinstance(origin, dict) else None
        if isinstance(sha, str) and re.fullmatch('[0-9a-f]{64}', sha):
            return sha
    elif (proof['proof_kind'] == 'legacy_origin_v1'
          and _legacy_origin(proof.get('origin'), proof.get('topic_id'))
          and isinstance(proof.get('source_fact_id'), str) and proof['source_fact_id']):
        return _single_image_evidence([proof.get('download_evidence')])['sha256']
    _denied()


def entry_proof(store, db, actor, binding, entry_ref):
    """Reconstruct a bounded proof from current authority and one immutable source."""
    actor = store.current(db, actor)
    current = store.binding(db, actor, binding_id=binding['id'])
    row = _entry(db, actor.tenant_id, entry_ref)
    if not row or actor.owner or 'media.store' not in actor.scopes:
        _denied()
    remote = json.loads(row['snapshot'])
    origin = json.loads(row['intent']).get('origin')
    topic = str(remote.get('reply_to_native_id') or '')
    attachments = remote.get('provider_media', [])
    if (current['provider'] != 'telegram' or current['destination_id'] != row['destination_id']
            or current['native_id'] != remote.get('native_target')
            or 'publish' not in json.loads(current['rights'])
            or not store.service_media_topic_allowed(db, actor, current, topic)
            or remote.get('namespace') != 'published'
            or not isinstance(origin, dict)
            or not all(isinstance(origin[key], str) and origin[key] for key in origin)
            or not isinstance(attachments, (list, tuple)) or len(attachments) != 1
            or not isinstance(attachments[0], str) or not attachments[0].startswith('document:')):
        _denied()
    extra = {}
    if set(origin) == {'system', 'ref', 'sha256'}:
        if not re.fullmatch('[0-9a-f]{64}', origin['sha256']):
            _denied()
    elif _legacy_origin(origin, topic):
        evidence = _single_image_evidence(remote.get('observed_media'))
        hashes = remote.get('media_hashes', [])
        if not isinstance(hashes, (list, tuple)) or (hashes and list(hashes) != [evidence['sha256']]):
            _denied()
        extra = {'proof_kind': 'legacy_origin_v1', 'source_fact_id': row['fact_id'],
                 'download_evidence': evidence}
    else:
        _denied()
    return {'tenant_id': actor.tenant_id, 'principal_id': actor.principal_id,
            'principal_epoch': actor.epoch, 'binding_id': current['id'],
            'binding_epoch': current['epoch'], 'destination_id': current['destination_id'],
            'connection_id': current['connection_id'], 'native_target': current['native_id'],
            'entry_ref': row['id'], 'source_principal_id': row['principal_id'],
            'revision': row['revision'], 'topic_id': topic, 'native_id': remote['native_id'],
            'namespace': remote['namespace'], 'provider_media': remote['provider_media'],
            'member_ids': remote.get('member_ids', []), 'origin': origin, **extra}


def require_grant(store, db, actor, entry_ref, *, grant_id=None, binding_id=None):
    """A replaced/revoked grant never authorizes an old operation or cache."""
    actor = store.current(db, actor)
    query = ('SELECT * FROM media_service_entry_grants WHERE tenant_id=? '
             'AND principal_id=? AND entry_ref=?')
    values = [actor.tenant_id, actor.principal_id, entry_ref]
    if grant_id is not None:
        query += ' AND id=?'; values.append(grant_id)
    if binding_id is not None:
        query += ' AND binding_id=?'; values.append(binding_id)
    rows = db.execute(query, values).fetchall()
    if len(rows) != 1:
        _denied()
    grant = rows[0]
    binding = store.binding(db, actor, binding_id=grant['binding_id'])
    proof = entry_proof(store, db, actor, binding, entry_ref)
    if canonical(proof) != grant['proof']:
        _denied()
    return grant, binding


def apply_entry_grants(store, db, owner, principal, alias, proofs):
    """Owner-only, exact-proof administration within the caller's transaction."""
    owner = store.current(db, owner)
    if not owner.owner or not proofs or len(proofs) > 4:
        _denied()
    target = db.execute('SELECT p.*,t.timezone FROM principals p JOIN tenants t ON t.id=p.tenant_id '
                        'WHERE p.tenant_id=? AND p.id=? AND p.active=1',
                        (owner.tenant_id, principal)).fetchone()
    if not target:
        _denied()
    actor = store.actor_row(target)
    binding = store.binding(db, actor, alias=alias)
    validated = []
    for expected in proofs:
        proof = entry_proof(store, db, actor, binding, expected.get('entry_ref'))
        if canonical(proof) != canonical(expected) or proof['source_principal_id'] != owner.principal_id:
            _denied()
        if proof['entry_ref'] in [row['entry_ref'] for row in validated]:
            _denied()
        validated.append(proof)
    ids = []
    for proof in validated:
        existing = db.execute('SELECT id,proof FROM media_service_entry_grants '
                              'WHERE tenant_id=? AND principal_id=? AND entry_ref=?',
                              (owner.tenant_id, principal, proof['entry_ref'])).fetchone()
        if existing:
            if existing['proof'] != canonical(proof):
                _denied()
            ids.append(existing['id'])
            continue
        ident = new_id('entrygrant')
        db.execute('INSERT INTO media_service_entry_grants VALUES(?,?,?,?,?,?,?)',
                   (ident, owner.tenant_id, principal, proof['entry_ref'], binding['id'],
                    canonical(proof), store.clock()))
        ids.append(ident)
    return ids


def revoke_entry_grant(store, db, owner, grant_id):
    owner = store.current(db, owner)
    if not owner.owner:
        _denied()
    db.execute('DELETE FROM media_service_entry_grants WHERE id=? AND tenant_id=?',
               (grant_id, owner.tenant_id))


def check_download(proof, page):
    """Verify exact provider identity AND actual bytes before any cache insertion."""
    if page.cursor is not None or len(page.items) != 1 or len(page.downloads) != 1:
        _denied()
    remote, media = page.items[0], page.downloads[0]
    if (remote.native_target != proof['native_target'] or remote.native_id != proof['native_id']
            or remote.namespace != proof['namespace'] or str(remote.reply_to_native_id or '') != proof['topic_id']
            or list(remote.provider_media) != proof['provider_media']
            or list(remote.member_ids) != proof['member_ids']
            or media.item_native_id != proof['native_id'] or media.slot != 0
            or media.provider_ref != proof['provider_media'][0] or media.media_kind != 'document'
            or hashlib.sha256(media.data).hexdigest() != proof_sha256(proof)):
        _denied()
    if proof.get('proof_kind') == 'legacy_origin_v1':
        evidence = _single_image_evidence(remote.observed_media)
        if (evidence != proof['download_evidence'] or media.mime != evidence['mime']
                or len(media.data) != evidence['size']
                or (remote.media_hashes and list(remote.media_hashes) != [evidence['sha256']])):
            _denied()
