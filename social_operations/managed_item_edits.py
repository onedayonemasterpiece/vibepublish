"""Managed native-item media edits retain one publication and its sibling evidence."""
import json

from .domain import DomainError, canonical, digest, parse_time


def latest_attempts(db, op):
    """Read existing target heads at this revision; never copy effect attempts."""
    if not op['publication_id']:
        return [dict(row) for row in db.execute(
            'SELECT a.*,? AS target_revision,a.operation_id AS target_operation_id '
            'FROM attempts a WHERE operation_id=? ORDER BY rowid', (op['revision'], op['id']))]
    rows = db.execute(
        'SELECT a.*,o.revision AS target_revision,o.id AS target_operation_id '
        'FROM attempts a JOIN operations o ON o.id=a.operation_id '
        'WHERE o.publication_id=? AND o.tenant_id=? AND o.principal_id=? AND o.revision<=? '
        'ORDER BY o.revision DESC,o.rowid DESC,a.rowid ASC LIMIT 1001',
        (op['publication_id'], op['tenant_id'], op['principal_id'], op['revision'])).fetchall()
    if len(rows) > 1000:
        raise DomainError('publication_history_limit', next_action='contact_owner')
    heads, applied = {}, {}
    for row in rows:
        if row['dispatched'] and row['state'] in {'verified', 'scheduled', 'cancelled'}:
            applied.setdefault(row['binding_id'], row['target_revision'])
        prior = heads.get(row['binding_id'])
        if prior is None:
            heads[row['binding_id']] = dict(row)
        elif prior['operation_id'] == row['operation_id']:
            raise DomainError('publication_target_ambiguous', next_action='contact_owner')
    if len(heads) > 20:
        raise DomainError('publication_history_limit', next_action='contact_owner')
    for binding_id, head in heads.items():
        verified_revision = applied.get(binding_id)
        successful = head['state'] in {'verified', 'scheduled', 'cancelled'}
        sync = ('unknown' if head['state'] == 'outcome_unknown' or head['observed'] == 'unknown'
                else 'current' if successful and verified_revision == op['revision']
                else 'outdated' if successful and head['target_revision'] < op['revision']
                else 'pending')
        head.update(applied_revision=verified_revision, desired_revision=op['revision'], sync_status=sync)
    return list(heads.values())


def selected_attempts(store, db, actor, args, heads):
    """Select only existing publication targets; a sibling cannot veto a safe edit."""
    aliases = args['change'].get('destinations')
    if aliases is None:
        return heads
    if args['change']['kind'] != 'edit' or not args.get('request_key'):
        raise DomainError('scoped_edit_request_key_required')
    selected = {store.binding(db, actor, alias=alias)['id'] for alias in aliases}
    if len(selected) != len(aliases):
        raise DomainError('publication_target_ambiguous', next_action='refresh')
    by_binding = {row['binding_id']: row for row in heads}
    if not selected <= by_binding.keys():
        raise DomainError('publication_target_not_found', next_action='refresh')
    children = [row for row in heads if row['binding_id'] in selected]
    for child in children:
        if child['state'] not in {'verified', 'scheduled'} or child['observed'] == 'unknown':
            raise DomainError('selected_target_not_verified', next_action='review_outcome')
        old = json.loads(child['plan'])
        binding = store.binding(db, actor, binding_id=child['binding_id'])
        if (digest(old) != child['plan_digest'] or child['binding_epoch'] != binding['epoch']
                or old.get('native_target') != binding['native_id']
                or any(old.get(key) != binding[key] for key in
                       ('connection_id', 'destination_id', 'account_type', 'secret_ref'))):
            raise DomainError('managed_media_target_not_verified', next_action='refresh')
    return children


def _fresh_read(db, actor, source, binding, remote, now):
    age = now - parse_time(remote['observed_at'])
    if not 0 <= age <= 300:
        raise DomainError('managed_media_reference_stale', next_action='refresh')
    row = db.execute(
        "SELECT o.request FROM operations o JOIN json_each(o.result,'$.items') i "
        "WHERE o.tenant_id=? AND o.principal_id=? AND o.actor_epoch=? "
        "AND o.action='read' AND o.state='verified' AND o.complete=1 AND o.work_state='done' "
        "AND o.created>=? AND json_extract(i.value,'$.ref')=? "
        "AND json_extract(i.value,'$.source')='provider' "
        "AND json_extract(i.value,'$.freshness')='current' LIMIT 1",
        (actor.tenant_id, actor.principal_id, actor.epoch, now-300, source['id'])).fetchone()
    request = json.loads(row['request']) if row else {}
    if not (request.get('query', {}).get('kind') == 'item'
            and request.get('_binding_id') == binding['id']
            and request.get('_binding_epoch') == binding['epoch']
            and request.get('_native_item') == remote['native_id']
            and request.get('_namespace') == 'published'):
        raise DomainError('managed_media_reference_unverified', next_action='refresh')


def adopt(app, db, actor, args, source, binding, remote):
    """An exact owned managed target may use the existing item-ref edit contract."""
    change = args['change']
    if not args.get('request_key'):
        raise DomainError('managed_media_request_key_required')
    if binding['provider'] != 'telegram' or change['kind'] != 'edit':
        raise DomainError('external_media_replace_needs_review', next_action='contact_owner')
    media = change.get('media')
    if (not isinstance(media, list) or len(media) != 1
            or media[0].get('role', 'image') not in {'image', 'video'}
            or remote.get('namespace') != 'published' or remote.get('origin')
            or remote.get('native_target') != binding['native_id']
            or source['native_id'] != remote.get('native_id')
            or source['namespace'] != 'published'
            or len(remote.get('member_ids') or [remote['native_id']]) != 1
            or len(remote.get('provider_media', [])) != 1):
        raise DomainError('managed_media_shape_unsupported', next_action='contact_owner')
    _fresh_read(db, actor, source, binding, remote, app.store.clock())
    publications = db.execute(
        "SELECT DISTINCT o.publication_id FROM attempts a JOIN operations o ON o.id=a.operation_id "
        "WHERE o.tenant_id=? AND o.principal_id=? AND o.actor_epoch=? "
        "AND o.publication_id IS NOT NULL AND a.provider='telegram' "
        "AND a.binding_id=? AND a.binding_epoch=? "
        "AND json_extract(a.checkpoint,'$.remote.native_id')=? "
        "AND json_extract(a.checkpoint,'$.remote.native_target')=? "
        "AND json_extract(a.checkpoint,'$.remote.namespace')='published' LIMIT 21",
        (actor.tenant_id, actor.principal_id, actor.epoch, binding['id'], binding['epoch'],
         remote['native_id'], binding['native_id'])).fetchall()
    if not publications:
        raise DomainError('external_media_replace_needs_review', next_action='contact_owner')
    if len(publications) != 1:
        raise DomainError('managed_media_target_ambiguous', next_action='contact_owner')
    publication = db.execute(
        'SELECT * FROM publications WHERE id=? AND tenant_id=? AND principal_id=?',
        (publications[0]['publication_id'], actor.tenant_id, actor.principal_id)).fetchone()
    if not publication or publication['kind'] != 'publish':
        raise DomainError('external_media_replace_needs_review', next_action='contact_owner')
    previous = app.store.private_operation(db, actor, publication['id'])
    if previous['work_state'] != 'done' or previous['revision'] != publication['revision']:
        raise DomainError('operation_in_progress', next_action='check_status')
    heads = latest_attempts(db, previous)
    matches = [row for row in heads if row['binding_id'] == binding['id']]
    if len(matches) != 1:
        raise DomainError('managed_media_target_ambiguous', next_action='contact_owner')
    child = matches[0]
    old = json.loads(child['plan'])
    tracked = json.loads(child['checkpoint']).get('remote', {})
    if not (child['state'] == 'verified' and child['observed'] in {'published', 'edited'}
            and child['binding_epoch'] == binding['epoch']
            and digest(old) == child['plan_digest']
            and old.get('provider') == 'telegram' and old.get('surface') == 'post'
            and old.get('action') in {'publish', 'edit'}
            and old.get('workload', 'publication') == 'publication'
            and old.get('binding_id') == binding['id']
            and old.get('binding_epoch') == binding['epoch']
            and all(old.get(key) == binding[key] for key in
                    ('connection_id', 'destination_id', 'account_type', 'secret_ref'))
            and old.get('native_target') == binding['native_id']
            and tracked.get('native_id') == remote['native_id']
            and tracked.get('native_target') == remote['native_target']
            and tracked.get('namespace') == 'published' and not tracked.get('origin')
            and tracked.get('provider_media') == remote['provider_media']
            and (tracked.get('member_ids') or [tracked.get('native_id')])
                == (remote.get('member_ids') or [remote['native_id']])):
        raise DomainError('managed_media_target_not_verified', next_action='review_outcome')
    if (len(old.get('assets', [])) != 1
            or old['assets'][0].get('role', 'image') not in {'image', 'video'}):
        raise DomainError('managed_media_shape_unsupported', next_action='contact_owner')
    # The fresh native read is the CAS. Never infer asset hashes from shared read access.
    existing = {**remote, 'media_hashes': []}
    content = {'text': remote['text']}
    if remote.get('entities_json', '[]') != '[]':
        content.update(format='telegram_entities', entities=json.loads(remote['entities_json']))
    target = {'content': content, 'media': media, 'surface': 'post',
              'delivery': {'kind': 'now'}, 'mode': 'execute'}
    target.update({key: value for key, value in change.items() if key != 'kind'})
    plan = app._plan(db, actor, binding, target, 'edit', existing)
    plan['managed_item_edit'] = {'source_attempt_id': child['id'],
                                 'source_revision': child['target_revision'], 'item_ref': source['id']}
    revision = publication['revision'] + 1
    changed = db.execute('UPDATE publications SET revision=? WHERE id=? AND revision=?',
                         (revision, publication['id'], publication['revision'])).rowcount
    if changed != 1:
        raise DomainError('revision_conflict', next_action='refresh')
    return publication['id'], revision, [plan]
