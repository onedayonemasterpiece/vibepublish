"""Exact permission wording from frozen plans; private edit preparation only."""
from __future__ import annotations

import json
from datetime import datetime
from difflib import unified_diff
from zoneinfo import ZoneInfo

from .domain import DomainError, canonical, digest, new_id, normalize_intent


def _content_view(text, entities):
    lines = [text]
    if entities:
        lines.append('Ссылки и оформление (позиции UTF-16):')
        encoded = text.encode('utf-16-le')
        for entity in entities:
            offset, length = entity['offset'], entity['length']
            label = encoded[2 * offset:2 * (offset + length)].decode('utf-16-le', errors='replace')
            line = f"{entity['type']} [{offset}:{length}] {json.dumps(label, ensure_ascii=False)}"
            for key in ('url', 'document_id', 'language'):
                if entity.get(key):
                    line += f"; {key}={entity[key]}"
            lines.append(line)
    return '\n'.join(lines)


def _media_view(assets):
    lines = []
    for position, asset in enumerate(assets, 1):
        lines.append(f"{position}. {asset.get('provider_ref') or asset['ref']} ({asset.get('role', 'image')})")
        for key in ('caption', 'alt_text'):
            if asset.get(key):
                lines.append(f"{key}: {asset[key]}")
    return '\n'.join(lines) or 'Нет вложений.'


def _native_media_view(existing):
    media = existing.get('provider_media') or []
    if media:
        return '\n'.join(f'{position}. {reference}' for position, reference in enumerate(media, 1))
    hashes = existing.get('media_hashes') or []
    if hashes:
        return 'Native ID не предоставлены; известные SHA-256 в порядке вложений:\n' + '\n'.join(hashes)
    return 'Нет вложений.'


def permission_result(plans, *, timezone, revision, publication_id=None, source_revision=None, item_ref=None):
    """Project only content and destination identity, never credentials or a whole plan."""
    lines = ['Разрешаете выполнить следующие действия с указанным содержимым?']
    if publication_id:
        lines.append(f'Публикация: {publication_id}.')
    if source_revision is not None:
        lines.append(f'Основание: исходная ревизия {source_revision}; подготовленная ревизия {revision}.')
    else:
        lines.append(f'Подготовленная ревизия: {revision}.')
    if item_ref:
        lines.append(f'Прочитанный пост: {item_ref}.')
    previews = []
    for position, plan in enumerate(plans, 1):
        action = plan['action']
        verb = {'publish': 'Опубликовать', 'edit': 'Изменить пост', 'forward': 'Переслать'}.get(action, action)
        lines.append(f"\n{position}. {verb}: {plan['provider']} / {plan['alias']}, назначение {plan['native_target']}, {plan['surface']}.")
        existing = plan.get('existing') or {}
        if existing:
            lines.append(f"Пост: {existing['native_id']} ({existing['namespace']})" +
                         (f"; {existing['url']}" if existing.get('url') else '') + '.')
            if existing.get('member_ids'):
                lines.append('Сообщения альбома по порядку: ' + ', '.join(existing['member_ids']) + '.')
        if plan.get('topic_root_id'):
            lines.append(f"Тред: {plan['topic_root_id']}.")
        if plan.get('vk_primary_attachments_mode'):
            lines.append(f"Режим вложений VK: {plan['vk_primary_attachments_mode']}.")
        if plan.get('source'):
            lines.append(f"Источник: {plan['source']['canonical_url']}.")
        if plan.get('story_link_json'):
            link = json.loads(plan['story_link_json'])
            lines.append(f"Ссылка истории: {link.get('text', '')} {link['url']}.")
        scheduled = plan.get('scheduled_at')
        when = datetime.fromisoformat(scheduled.replace('Z', '+00:00')).astimezone(ZoneInfo(timezone)).isoformat(sep=' ') if scheduled else 'сейчас'
        if action == 'edit':
            lines.append(f'Время правки: сейчас ({timezone}).')
            lines.append(f'Время публикации не меняется: {when} ({timezone}).' if scheduled
                         else 'Пост уже опубликован; дата публикации не меняется.')
        else:
            lines.append(f'Время публикации: {when} ({timezone}).')
        content = json.loads(plan['content_json'])
        text, entities = content.get('text', ''), content.get('entities', [])
        previews.append({'destination': plan['alias'], 'provider': plan['provider'], 'text': text, 'entities': entities})
        after = _content_view(text, entities)
        media = _media_view(plan['assets'])
        if action == 'edit':
            before = _content_view(existing.get('text', ''), json.loads(existing.get('entities_json') or '[]'))
            native_media = _native_media_view(existing)
            if not plan['assets']:
                media = native_media
                lines.append('Вложения сохранить без изменений в прежнем порядке.')
            before += '\nВложения по порядку:\n' + native_media
            after += '\nВложения по порядку:\n' + media
            lines.extend(('До:\n' + before, 'После (полный текст, ссылки и футер):\n' + after))
            difference = '\n'.join(unified_diff(before.splitlines(), after.splitlines(), fromfile='до', tofile='после', lineterm=''))
            lines.append('Точные изменения:\n' + (difference or 'Текст, оформление и вложения не меняются.'))
        else:
            lines.extend(('Полный текст, ссылки и футер:\n' + after, 'Вложения по порядку:\n' + media))
    return {'dry_run': True, 'permission_request': '\n'.join(lines), 'content_previews': previews}


def preview_edit(app, actor, args):
    """Reuse ordinary edit planning without advancing a head or dispatching a task."""
    intent = normalize_intent('publication_update', args)
    with app.store.tx() as db:
        actor = app.store.current(db, actor)
        operation = app._replay(db, actor, 'publication_update', intent, args, implicit=False)
        if not operation:
            planner = app._adopt_plan if args.get('item_ref') else app._update_plan
            publication, revision, plans = planner(db, actor, args, persist=False)
            result = permission_result(
                plans, timezone=actor.timezone, revision=revision, publication_id=publication,
                source_revision=args.get('expected_revision', revision - 1 if publication else None),
                item_ref=args.get('item_ref'))
            result['message'] = 'Приватный предпросмотр готов. Отправки и проверки через провайдера не было.'
            operation = app._new_operation(db, actor, 'publication_update', intent, revision=revision,
                                           complete=True, result=result)
            result['execute_args'] = {
                **intent, 'request_key': operation + ':execute',
                'change': {**intent['change'], 'mode': 'execute', 'preview_operation_id': operation}}
            db.execute('UPDATE operations SET result=? WHERE id=?', (canonical(result), operation))
            for plan in plans:
                # Existing receipt access checks revalidate these binding/emoji references.
                db.execute("INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,plan,plan_digest,state,stage) "
                           "VALUES(?,?,?,?,?,?,?,?,'verified','finished')",
                           (new_id('attempt'), operation, plan['binding_id'], plan['binding_epoch'],
                            plan['alias'], plan['provider'], canonical(plan), digest(plan)))
            if args.get('request_key'):
                app._key(db, actor, args['request_key'], digest(['publication_update', intent]), operation)
    return app.store.receipt(actor, operation)


def _edit_intent(args):
    intent = normalize_intent('publication_update', args)
    intent['change'] = {key: value for key, value in intent['change'].items()
                        if key not in {'mode', 'preview_operation_id'}}
    return intent


def require_edit_preview(app, db, actor, args, plans):
    """A supplied private preview binds the whole effect; conflict rolls back admission."""
    reference = args['change'].get('preview_operation_id')
    if not reference:
        return
    preview = app.store.private_operation(db, actor, reference)
    request = json.loads(preview['request'])
    if (preview['id'] != reference or preview['action'] != 'publication_update'
            or not preview['complete'] or preview['publication_id'] is not None
            or not json.loads(preview['result']).get('dry_run')
            or request.get('change', {}).get('kind') != 'edit'
            or request['change'].get('mode') != 'preview'):
        raise DomainError('permission_preview_invalid', 'Нужен собственный завершённый предпросмотр этой правки', 'refresh')
    frozen = [json.loads(row['plan']) for row in db.execute(
        'SELECT plan FROM attempts WHERE operation_id=? ORDER BY rowid', (preview['id'],))]
    if (_edit_intent(args) != _edit_intent(request)
            or [{**plan, 'mode': 'execute'} for plan in plans]
            != [{**plan, 'mode': 'execute'} for plan in frozen]):
        raise DomainError('permission_preview_changed',
                          'Подготовленный payload изменился; нужен актуальный предпросмотр этой правки', 'refresh')


def cancel_preview(app, db, actor, args, intent):
    """Cancel a completed unsent preview in the admission transaction."""
    pub = db.execute(
        'SELECT * FROM publications WHERE id=? AND tenant_id=? AND principal_id=?',
        (args['publication_id'], actor.tenant_id, actor.principal_id)).fetchone()
    if not pub or pub['revision'] != args['expected_revision']:
        raise DomainError('revision_conflict', 'Refresh the exact publication revision', 'refresh')
    previous = app.store.private_operation(db, actor, pub['id'])
    if (previous['action'] != 'publish' or previous['state'] != 'needs_approval'
            or not previous['complete'] or previous['work_state'] != 'done'
            or json.loads(previous['request']).get('mode') != 'preview'):
        return None
    children = db.execute(
        'SELECT * FROM attempts WHERE operation_id=? ORDER BY rowid',
        (previous['id'],)).fetchall()
    if not children or any(
            child['dispatched'] or child['observed'] != 'not_attempted'
            or json.loads(child['checkpoint']).get('remote') for child in children):
        raise DomainError('remote_item_not_bound')
    plans = []
    for child in children:
        binding = app.store.binding(db, actor, binding_id=child['binding_id'])
        if 'cancel' not in json.loads(binding['rights']):
            raise DomainError('access_denied', 'Binding does not allow this command', 'contact_owner')
        plans.append({**json.loads(child['plan']), 'action': 'cancel', 'mode': 'execute',
                      'assets': [], 'scheduled_at': None})
    publication, revision = pub['id'], pub['revision'] + 1
    changed = db.execute(
        'UPDATE publications SET revision=? WHERE id=? AND revision=?',
        (revision, publication, args['expected_revision'])).rowcount
    if changed != 1:
        raise DomainError('revision_conflict', 'Refresh the exact publication revision', 'refresh')
    db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?)',
               (actor.tenant_id, actor.principal_id, publication, revision,
                canonical(intent), canonical(plans), digest(plans)))
    op = app._new_operation(
        db, actor, 'publication_update', intent, publication=publication,
        revision=revision, complete=True,
        result={'message': 'Приватный предпросмотр отменён. Публикации не было.'})
    db.execute("UPDATE operations SET state='cancelled' WHERE id=?", (op,))
    for child, plan in zip(children, plans):
        db.execute(
            "INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,"
            "plan,plan_digest,state,stage,observed,result) "
            "VALUES(?,?,?,?,?,?,?,?,'cancelled','finished','not_attempted',?)",
            (new_id('attempt'), op, child['binding_id'], child['binding_epoch'],
             child['alias'], child['provider'], canonical(plan), digest(plan),
             canonical({'compensation': 'intent_cancelled_without_effect',
                        'reason': 'preview_cancelled_without_effect'})))
    db.execute(
        'UPDATE decisions SET consumed_by=? WHERE publication_id=? AND revision=? AND consumed_by IS NULL',
        (op, publication, previous['revision']))
    if args.get('request_key'):
        app._key(db, actor, args['request_key'], digest(['publication_update', intent]), op)
    return op
