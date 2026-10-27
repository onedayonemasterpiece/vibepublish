"""Resume verified photo prefixes for the same attempt or a later authorized edit."""
import json
import re
from .domain import DomainError, digest


def select(db, op, child):
    try:
        plan = json.loads(child['plan'])
        existing = plan.get('existing') or {}
        assets = plan.get('assets', [])
        # Allow scheduled posts (remove scheduled_at check) and both publish/edit
        if not (child['provider'] == 'vk' and not child['dispatched']
                and plan.get('action') in {'publish', 'edit'} and plan.get('surface') == 'post'
                and (not existing if plan['action'] == 'publish' else existing.get('namespace') in {'published', 'scheduled'})
                and 1 <= len(assets) <= 10 and not plan.get('source')
                and all(a.get('role') == 'image' and a.get('mime') in
                        {'image/jpeg', 'image/png', 'image/webp'} for a in assets)
                and digest(plan) == child['plan_digest']):
            return None
        principal = db.execute('SELECT epoch,active FROM principals WHERE id=? AND tenant_id=?',
                               (op['principal_id'], op['tenant_id'])).fetchone()
        binding = db.execute('SELECT b.*,d.native_id,d.connection_id,c.account_type,c.secret_ref,'
                             'c.active AS connection_active FROM bindings b '
                             'JOIN destinations d ON d.id=b.destination_id '
                             'JOIN connections c ON c.id=d.connection_id WHERE b.id=?',
                             (child['binding_id'],)).fetchone()
        if not (principal and principal['active'] and principal['epoch'] == op['actor_epoch']
                and binding and binding['active'] and binding['connection_active']
                and binding['tenant_id'] == op['tenant_id'] and binding['principal_id'] == op['principal_id']
                and binding['epoch'] == child['binding_epoch'] == plan['binding_epoch']
                and binding['native_id'] == plan['native_target']
                and all(binding[k] == plan[k] for k in
                        ('connection_id', 'destination_id', 'account_type', 'secret_ref'))
                and plan['action'] in json.loads(binding['rights'])):
            return None
        # Current-attempt retry/restart first; prior revisions are only for a
        # separately admitted edit, never a new publish or an uncertain effect.
        sources = [dict(child, source_actor_epoch=op['actor_epoch'])]
        if plan['action'] == 'edit':
            sources.extend(db.execute(
                "SELECT a.*,o.actor_epoch AS source_actor_epoch FROM attempts a JOIN operations o ON o.id=a.operation_id "
                "WHERE o.publication_id=? AND o.tenant_id=? AND o.principal_id=? AND o.complete=1 AND o.revision<? "
                "AND a.binding_id=? AND a.binding_epoch=? AND a.dispatched=0 AND a.state IN ('blocked','failed') "
                "AND a.id!=? ORDER BY o.revision DESC LIMIT 20",
                (op['publication_id'], op['tenant_id'], op['principal_id'], op['revision'],
                 child['binding_id'], child['binding_epoch'], child['id'])))
        for source in sources:
            old = json.loads(source['plan'])
            saved = json.loads(source['checkpoint'])
            cp = saved.get('adapter', {})
            media = cp.get('media')
            old_existing = old.get('existing') or {}
            if not (source['provider'] == 'vk' and source['source_actor_epoch'] == op['actor_epoch']
                    and digest(old) == source['plan_digest']
                    and all(old.get(k) == plan.get(k) for k in (
                        'action', 'surface', 'assets', 'connection_id', 'destination_id',
                        'native_target', 'account_type', 'secret_ref', 'binding_epoch', 'scheduled_at', 'source'))
                    and all(old_existing.get(k) == existing.get(k) for k in
                            ('native_id', 'native_target', 'namespace'))
                    ):
                continue
            if saved.get('transition') not in {'vk_prepared', 'vk_photo_staging'}:
                continue
            # Accept checkpoints without photo_proofs (new policy: no CDN fingerprint verification)
            # Validate media IDs with support for negative owner_ids (community photos)
            if not (type(cp.get('version')) is int and cp.get('version') == 1
                    and cp.get('attempt') == source['id'] and cp.get('plan') == source['plan_digest']
                    and cp.get('target') == plan['native_target'] and cp.get('id') == existing.get('native_id')
                    and cp.get('source') is None
                    and (cp.get('retryable_wall_post') is False
                         or (plan['action'] == 'publish' and cp.get('retryable_wall_post') is True))
                    and isinstance(media, list) and 1 <= len(media) <= len(assets)
                    and (saved['transition'] != 'vk_prepared' or len(media) == len(assets))
                    and len(set(media)) == len(media)
                    and all(isinstance(m, str) and re.fullmatch(r'photo-?[1-9][0-9]*_[1-9][0-9]*', m) for m in media)):
                raise DomainError('vk_staged_photos_invalid')
            # photo_proofs is optional; if present, validate structure but don't require
            proofs = cp.get('photo_proofs')
            if proofs is not None:
                if not (isinstance(proofs, list) and len(proofs) == len(media)
                        and all(isinstance(p, dict) and set(p) == {'sha256','size','mime','width','height'}
                                and isinstance(p['sha256'], str) and re.fullmatch(r'[a-f0-9]{64}', p['sha256'])
                                and p['mime'] in {'image/jpeg','image/png','image/webp'}
                                and all(type(p[k]) is int and p[k] > 0 for k in ('size','width','height'))
                                for p in proofs)):
                    raise DomainError('vk_staged_photos_invalid')
            return dict(media=media, photo_proofs=proofs,
                        source_attempt_id=source['id'], source_plan_digest=source['plan_digest'],
                        target=plan['native_target'], post_id=existing.get('native_id'),
                        asset_hashes=[a['sha256'] for a in assets])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise DomainError('vk_staged_photos_invalid') from exc
    return None