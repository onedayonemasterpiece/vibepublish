"""The application entrypoint for MCP and HTTP; attachment import may fetch bytes."""
from __future__ import annotations
import asyncio
import hashlib
import json
import secrets
import sys
import sqlite3
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from contracts.social_mcp_v1 import VERSION, catalog, project_catalog
from .assets import AssetPreview, render_asset_preview
from .domain import DomainError, canonical, digest, new_id, normalize_intent, parse_source, parse_time, timestamp
from .network_footers import append_network_footer

CATALOG = {t['name']: t for t in catalog()['tools']}
FORMATS = FormatChecker()
SKILL = Path(__file__).resolve().parents[1] / 'docs/llm/vibepublish-social-skill.md'
if not SKILL.exists():
    SKILL = Path(sys.prefix) / 'share/vibepublish/vibepublish-social-skill.md'


class Application:
    def __init__(self, store, *, visual_dispatch_proof=None):
        self.store = store
        self.visual_dispatch_proof = visual_dispatch_proof
        from .visuals import VisualService
        self.visuals = VisualService(self)
        from .emojis import EmojiService
        self.emojis = EmojiService(self)

    def tools(self, actor):
        with self.store.connection() as db:
            actor = self.store.current(db, actor)
            aliases = [r['alias'] for r in self.store.bindings(db, actor) if 'publish' in json.loads(r['rights'])]
            return project_catalog(actor.scopes, publish_destinations=aliases, owner=actor.owner)

    async def call(self, actor, name: str, arguments: dict):
        try:
            tool = next((t for t in self.tools(actor) if t['name'] == name), None)
            if tool is None:
                raise DomainError('access_denied', 'Tool is not available', 'contact_owner')
            if list(Draft202012Validator(tool['inputSchema'], format_checker=FORMATS).iter_errors(arguments)):
                raise DomainError('invalid_input', 'Arguments do not match the scoped tool schema')
            short = name.removeprefix('vibepublish_')
            if short == 'get_started':
                result = self.bootstrap(actor, arguments)
            elif short == 'status':
                result = await self.status(actor, arguments)
            elif short == 'destinations':
                result = self.destinations(actor, arguments)
            elif short == 'read':
                result = self.read(actor, arguments)
            elif short == 'media_store':
                result = self.media_store(actor, arguments)
            elif short in ('publish', 'engage', 'publication_update'):
                result = self.accept(actor, short, arguments)
            elif short == 'visual':
                if arguments['command']['kind'] in {'import_begin', 'import_chunk', 'import_finish', 'import_status', 'import_abort'}:
                    from .workspace_asset_ingress import import_workspace_image
                    result = await import_workspace_image(self, actor, arguments)
                elif arguments['command']['kind'] == 'import':
                    from .chat_file_ingress import import_chat_file
                    result = await import_chat_file(self, actor, arguments)
                elif arguments['command']['kind'] == 'import_browser_artifact':
                    from .browser_artifact_ingress import import_browser_artifact
                    result = await import_browser_artifact(self, actor, arguments)
                else:
                    result = self.visuals.command(actor, arguments)
            elif short == 'asset_preview':
                resource_uri = arguments['resource_uri']
                ident = resource_uri.removeprefix('vibepublish://assets/')
                data, _mime, source_sha256 = self.read_asset(actor, ident)
                result = await asyncio.to_thread(render_asset_preview, data, source_sha256, resource_uri)
            else:
                raise DomainError('capability_not_implemented', next_action='contact_owner')
            # Validate outputs too; a malformed success must never escape to clients.
            validated_result = result.metadata if isinstance(result, AssetPreview) else result
            Draft202012Validator(CATALOG[name]['outputSchema'], format_checker=FORMATS).validate(validated_result)
            return result
        except DomainError as exc:
            return exc.output()
        except sqlite3.Error:
            return DomainError("store_unavailable", "No receipt could be returned. Recover using status or the same request key, never a new send", "contact_owner").output()

    def read_asset(self, actor, ident):
        with self.store.tx() as db:
            self._purge_media_store_assets(db)
        with self.store.connection() as db:
            actor = self.store.current(db, actor)
            if not actor.scopes.intersection({'visual', 'publish', 'media.store'}):
                raise DomainError('access_denied', next_action='contact_owner')
            row = db.execute('SELECT * FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                             (ident, actor.tenant_id, actor.principal_id)).fetchone()
            if not row:
                raise DomainError('asset_not_available', next_action='refresh')
            cache_binding = None
            shared_cache = db.execute(
                "SELECT m.publication_id,p.principal_id,g.grant_id FROM media_store_assets m "
                "JOIN publications p ON p.id=m.publication_id "
                "LEFT JOIN media_service_entry_assets g ON g.asset_id=m.asset_id "
                "WHERE m.asset_id=? AND m.purpose='download_cache'",
                (ident,)).fetchone()
            if shared_cache and shared_cache['principal_id'] != actor.principal_id:
                from .media_entry_grants import proof_sha256, require_grant
                if not shared_cache['grant_id']:
                    raise DomainError('access_denied', next_action='contact_owner')
                grant, cache_binding = require_grant(self.store, db, actor, shared_cache['publication_id'],
                                         grant_id=shared_cache['grant_id'])
                if row['sha256'] != proof_sha256(json.loads(grant['proof'])):
                    raise DomainError('asset_integrity')
            if not actor.owner and "media.store" in actor.scopes and not actor.scopes.intersection({"visual", "publish"}):
                cache = db.execute(
                    "SELECT m.publication_id,f.destination_id,f.snapshot FROM media_store_assets m "
                    "JOIN publications p ON p.id=m.publication_id "
                    "JOIN facts f ON f.publication_id=p.id "
                    "WHERE m.asset_id=? AND m.purpose='download_cache' "
                    "AND p.tenant_id=? "
                    "ORDER BY f.observed_at DESC LIMIT 1",
                    (ident, actor.tenant_id)
                ).fetchone()
                binding = cache_binding or next((b for b in self.store.bindings(db, actor)
                                if cache and b['destination_id'] == cache['destination_id']), None)
                if not cache or binding is None or not self.store.service_media_topic_allowed(
                        db, actor, binding,
                        str(json.loads(cache['snapshot']).get('reply_to_native_id') or '')):
                    raise DomainError('access_denied', next_action='contact_owner')
            origin = db.execute('SELECT job_id FROM visual_asset_origins WHERE asset_id=?', (ident,)).fetchone()
            if origin:
                self.visuals.job(db, actor, origin['job_id'])
            emoji_origin = db.execute('SELECT catalog_id FROM emoji_asset_origins WHERE asset_id=?', (ident,)).fetchone()
            if emoji_origin:
                self.emojis.catalog(db, actor, emoji_origin['catalog_id'], latest=True)
            if hashlib.sha256(row['bytes']).hexdigest() != row['sha256']:
                raise DomainError('asset_integrity')
            return row['bytes'], row['mime'], row['sha256']

    def media_store(self, actor, args):
        """Owner or explicit exact-topic service grants; provider-independent local reads."""
        if not actor.owner and "media.store" not in actor.scopes:
            raise DomainError('access_denied', next_action='contact_owner')
        with self.store.tx() as db:
            self._purge_media_store_assets(db)
        command = args['command']
        if command['kind'] == 'put':
            if not actor.owner:
                with self.store.connection() as db:
                    actor = self.store.current(db, actor)
                    binding, topic = self._telegram_thread(
                        db, actor, command['thread_ref'], alias=command['to'])
                    if (binding['alias'] != command['to'] or
                            not self.store.service_media_topic_allowed(db, actor, binding, topic)):
                        raise DomainError('access_denied', next_action='contact_owner')
            intent = {
                'to': [command['to']], 'thread_ref': command['thread_ref'],
                'content': command['content'], 'media': command['media'],
                'request_key': args['request_key']}
            if command.get('origin') is not None:
                origin = command['origin']
                intent['origin'] = origin
            return self.accept(actor, 'media_store', intent)
        get_ref = None
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            if command['kind'] == 'get':
                fact = db.execute(
                    "SELECT f.* FROM facts f JOIN publications p ON p.id=f.publication_id "
                    "WHERE p.id=? AND p.tenant_id=? AND p.principal_id=? AND p.kind='media_store' "
                    "ORDER BY f.observed_at DESC LIMIT 1",
                    (command['entry_ref'], actor.tenant_id, actor.principal_id)).fetchone()
                entry_grant = None
                grant_binding = None
                if not fact:
                    from .media_entry_grants import require_grant
                    allowed = db.execute(
                        "SELECT id FROM media_service_entry_grants WHERE tenant_id=? "
                        "AND principal_id=? AND entry_ref=?",
                        (actor.tenant_id, actor.principal_id, command['entry_ref'])).fetchone()
                    if not allowed:
                        raise DomainError('media_store_entry_not_found', next_action='refresh')
                    entry_grant, grant_binding = require_grant(self.store, db, actor, command['entry_ref'])
                    fact = db.execute(
                        "SELECT f.* FROM facts f JOIN publications p ON p.id=f.publication_id "
                        "WHERE p.id=? AND p.tenant_id=? AND p.kind='media_store' "
                        "ORDER BY f.observed_at DESC LIMIT 1",
                        (command['entry_ref'], actor.tenant_id)).fetchone()
                binding = grant_binding or next((b for b in self.store.bindings(db, actor)
                                if b['destination_id'] == fact['destination_id']), None)
                if binding is None:
                    raise DomainError('access_denied', next_action='contact_owner')
                remote = json.loads(fact['snapshot'])
                if not self.store.service_media_topic_allowed(
                        db, actor, binding, str(remote.get('reply_to_native_id') or '')):
                    raise DomainError('access_denied', next_action='contact_owner')
                if args.get('request_key') or entry_grant:
                    # Stable logical identity, never the fresh item_ref generated
                    # below. Admission and key binding commit in one transaction.
                    if 'publish' not in json.loads(binding['rights']) and not actor.owner:
                        raise DomainError('access_denied', next_action='contact_owner')
                    op = self._replay(db, actor, 'media_store_get', command, args, implicit=False)
                    if op:
                        previous = self.store.private_operation(db, actor, op)
                        saved = json.loads(previous['request'])
                        if (saved['_binding_id'] != binding['id'] or
                                saved['_binding_epoch'] != binding['epoch']):
                            raise DomainError('access_revoked', next_action='reauthorize')
                    else:
                        projected = self.project_item(db, actor, binding, remote, publication=command['entry_ref'])
                        intent = {'query': {'kind': 'item', 'item_ref': projected['ref']},
                                  '_media_store_get': True, '_media_store_entry_ref': command['entry_ref'],
                                  '_binding_id': binding['id'], '_binding_epoch': binding['epoch'],
                                  '_native_item': remote['native_id'], '_namespace': remote['namespace']}
                        if entry_grant:
                            intent['_media_store_grant_id'] = entry_grant['id']
                        op = self._new_operation(db, actor, 'read', intent)
                        if args.get('request_key'):
                            self._key(db, actor, args['request_key'], digest(['media_store_get', command]), op)
                else:
                    projected = self.project_item(db, actor, binding, remote, publication=command['entry_ref'])
                    get_ref = projected['ref']
            elif command['kind'] == 'list':
                try:
                    binding, topic = self._telegram_thread(db, actor, command['thread_ref'],alias=command.get('to'))
                except DomainError as error:
                    if command.get('to') is not None and error.code=='access_denied':
                        raise DomainError('media_store_destination_mismatch','The destination does not match thread_ref','fix_input') from None
                    raise
                if command.get('to') is not None and binding['alias'] != command['to']:
                    raise DomainError('media_store_destination_mismatch',
                                      'The destination does not match thread_ref', 'fix_input')
                if not self.store.service_media_topic_allowed(db, actor, binding, topic):
                    raise DomainError('access_denied', next_action='contact_owner')
                items = self._media_store_items(db, actor, binding=binding, topic=topic,
                                                text=command.get('text', ''))
                limit = args.get('limit', 25)
                result = {'media_store_items': items[:limit], 'truncated': len(items) > limit}
                op = self._new_operation(db, actor, 'media_store_list', args,
                                         complete=True, result=result)
            else:
                items = self._media_store_items(db, actor, text=command['text'])
                limit = args.get('limit', 25)
                result = {'media_store_items': items[:limit], 'truncated': len(items) > limit}
                op = self._new_operation(db, actor, 'media_store_search', args,
                                         complete=True, result=result)
        if get_ref:
            return self.read(actor, {'query': {'kind': 'item', 'item_ref': get_ref},
                                     '_media_store_get': True, '_media_store_entry_ref': command['entry_ref']})
        return self.store.receipt(actor, op)

    def _purge_media_store_assets(self, db):
        expired = [row['asset_id'] for row in db.execute(
            "SELECT asset_id FROM media_store_assets WHERE expires<?",
            (self.store.clock(),))]
        db.executemany('DELETE FROM assets WHERE id=?', [(ident,) for ident in expired])

    def _media_store_items(self, db, actor, *, publication_id=None, binding=None, topic=None, text=''):
        source_principal = actor.principal_id
        if publication_id:
            from .media_entry_grants import _entry, require_grant
            source = _entry(db, actor.tenant_id, publication_id)
            if source and source['principal_id'] != actor.principal_id:
                _, grant_binding = require_grant(self.store, db, actor, publication_id)
                binding = grant_binding
                source_principal = source['principal_id']
        params = [actor.tenant_id, source_principal]
        sql = ("SELECT f.*,p.id AS entry_ref,p.revision,r.intent AS revision_intent "
               "FROM facts f JOIN publications p ON p.id=f.publication_id "
               "JOIN revisions r ON r.publication_id=p.id AND r.revision=p.revision "
               "WHERE p.tenant_id=? AND p.principal_id=? AND p.kind='media_store'")
        if publication_id:
            sql += ' AND p.id=?'; params.append(publication_id)
        if binding:
            sql += ' AND f.destination_id=?'; params.append(binding['destination_id'])
        sql += ' ORDER BY f.observed_at DESC'
        output = []
        for row in db.execute(sql, params):
            remote = json.loads(row['snapshot'])
            if topic and remote.get('reply_to_native_id') != topic:
                continue
            if text.casefold() not in row['text'].casefold():
                continue
            item_binding = binding or next((b for b in self.store.bindings(db, actor)
                                            if b['destination_id'] == row['destination_id']), None)
            if item_binding is None:
                continue
            if not self.store.service_media_topic_allowed(
                    db, actor, item_binding, str(remote.get('reply_to_native_id') or '')):
                continue
            native_target = item_binding['native_id']
            if (not native_target.startswith('-100') or not native_target[1:].isdigit()
                    or not str(remote['native_id']).isdigit()
                    or not str(remote.get('reply_to_native_id', '')).isdigit()):
                continue
            channel = native_target[4:]
            origin = json.loads(row['revision_intent']).get('origin')
            output.append({'entry_ref': row['entry_ref'], 'text': row['text'],
                           'observed_at': remote['observed_at'], 'native_id': remote['native_id'],
                           'destination': item_binding['alias'],
                           'thread_ref': f"https://t.me/c/{channel}/{remote['reply_to_native_id']}",
                           'telegram_url': f"https://t.me/c/{channel}/{remote['native_id']}",
                           'sha256': list(remote['media_hashes']),
                           **({'origin': origin} if origin else {})})
        return output

    def aliases(self, db, actor):
        result = []
        for row in self.store.bindings(db, actor):
            result.append({'alias': row['alias'], 'kind': 'destination', 'label': row['label'],
                           'revision': row['epoch'], 'provider': row['provider'],
                           'native_id': row['native_id']})
        for row in db.execute('SELECT * FROM destination_sets WHERE tenant_id=? AND principal_id=?', (actor.tenant_id, actor.principal_id)):
            members = json.loads(row['members'])
            if all(any(d['alias'] == m for d in result) for m in members):
                result.append({'alias': row['alias'], 'kind': 'set', 'label': row['label'], 'revision': row['revision'], 'members': members})
        for destination in result:
            profile = db.execute('SELECT * FROM profiles WHERE tenant_id=? AND principal_id=? AND alias=?',
                                 (actor.tenant_id, actor.principal_id, destination['alias'])).fetchone()
            if profile:
                destination.update(profile=json.loads(profile['profile']), profile_revision=profile['revision'])
        return sorted(result, key=lambda d: (d.get('profile', {}).get('usage') != 'primary', d['alias']))

    def _recent_preview_preflight(self, db, actor, binding):
        """Fresh durable Telegram proof that native prepare succeeded without dispatch."""
        if binding['provider'] != 'telegram' or binding['account_type'] == 'fake':
            return False
        rows = db.execute(
            """SELECT a.plan FROM attempts a
               JOIN operations o ON o.id=a.operation_id
               WHERE a.binding_id=? AND a.binding_epoch=?
                 AND a.dispatched=0
                 AND a.state='needs_approval' AND a.stage='awaiting_approval'
                 AND o.tenant_id=? AND o.principal_id=? AND o.actor_epoch=?
                 AND o.action='publish' AND o.state='needs_approval'
                 AND o.complete=1 AND o.work_state='done' AND o.error IS NULL
                 AND o.created>=?
               ORDER BY o.created DESC LIMIT 8""",
            (binding['id'], binding['epoch'], actor.tenant_id, actor.principal_id,
             actor.epoch, self.store.clock()-3600),
        ).fetchall()
        for row in rows:
            try:
                plan = json.loads(row['plan'])
            except (TypeError, ValueError):
                continue
            if (plan.get('provider') == 'telegram'
                    and plan.get('mode') == 'preview'
                    and plan.get('action') == 'publish'
                    and plan.get('surface', 'post') == 'post'):
                return True
        return False

    def _recent_verified_capability(self, db, actor, binding, surface):
        """Durable provider-readback proof for the current binding epoch."""
        rows = db.execute(
            """SELECT a.plan,a.observed FROM attempts a
               JOIN operations o ON o.id=a.operation_id
               WHERE a.binding_id=? AND a.binding_epoch=?
                 AND a.state IN ('verified','scheduled')
                 AND a.observed IN ('published','provider_scheduled')
                 AND o.tenant_id=? AND o.principal_id=? AND o.actor_epoch=?
                 AND o.action='publish' AND o.error IS NULL
                 AND o.created>=?
               ORDER BY o.created DESC LIMIT 16""",
            (binding['id'], binding['epoch'], actor.tenant_id, actor.principal_id,
             actor.epoch, self.store.clock()-30*86400),
        ).fetchall()
        for row in rows:
            try:
                plan = json.loads(row['plan'])
            except (TypeError, ValueError):
                continue
            if (plan.get('provider') == binding['provider']
                    and plan.get('action') == 'publish'
                    and plan.get('surface', 'post') == surface):
                return True
        return False

    def bootstrap(self, actor, args):
        skill = SKILL.read_text()
        if args.get('section') == 'emoji':
            skill = skill.split('## Обычная публикация — короткий рецепт', 1)[0] + skill[skill.index('## Telegram custom emoji:'):]
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            scope = str(actor.routing_revision)
            offset = self.store.cursor_position(db, actor, args['cursor'], 'bootstrap', scope) if args.get('cursor') else 0
            all_dest = self.aliases(db, actor)
            page = all_dest[offset:offset+50]
            bindings = {r['alias']: r for r in self.store.bindings(db, actor)}
            result = {'version': '1.7.1-runtime-rkb-media-budget', 'schema_version': VERSION,
                      'skill_sha256': hashlib.sha256(skill.encode()).hexdigest(), 'skill': skill,
                      'estimated_tokens': (len(skill) + 2)//3, 'server_time': timestamp(self.store.clock()),
                      'timezone': actor.timezone, 'policy_epoch': actor.epoch, 'routing_revision': actor.routing_revision,
                      'scheduling': 'provider_native_only', 'read_policy': 'provider_visible_owner' if actor.owner else
                      'bound_publish_destinations' if bindings and 'publish' in actor.scopes else 'none',
                      'destinations': page, 'capabilities': []}
            for d in page:
                row = bindings.get(d['alias'])
                if row:
                    surfaces = ('post', 'story') if row['provider'] in {'vk', 'telegram'} else ('post',)
                    for surface in surfaces:
                        live_verified = self._recent_verified_capability(db, actor, row, surface)
                        preview_verified = surface == 'post' and self._recent_preview_preflight(db, actor, row)
                        if live_verified:
                            status = 'supported'
                            reason = 'Recent provider mutation was confirmed by exact provider readback for this binding epoch'
                        elif preview_verified:
                            status = 'supported'
                            reason = 'Recent preview completed Telegram provider/target preflight without provider dispatch'
                        else:
                            status = 'needs_review' if row['account_type'] in {'fake','mtproto_user','mtproto_bot','vk_user','vk_group'} else 'needs_auth'
                            reason = 'Offline fixture only; no live capability verified' if row['account_type'] == 'fake' else 'Native implementation requires explicit target preflight; no recent live readback verified'
                        result['capabilities'].append({'destination': row['alias'], 'operation': 'publish', 'surface': surface,
                            'status': status,
                            'observed_at': timestamp(self.store.clock()),
                            'reason': reason})
            if offset+50 < len(all_dest):
                result['next_cursor'] = self.store.cursor(db, actor, 'bootstrap', scope, offset+50)
            return result

    def _new_operation(self, db, actor, action, intent, *, publication=None, revision=1, complete=False, result=None, command_timeout=120):
        if not complete:
            active = db.execute("SELECT count(*) FROM operations WHERE tenant_id=? AND work_state!='done'", (actor.tenant_id,)).fetchone()[0]
            quota = db.execute('SELECT command_limit FROM tenants WHERE id=?', (actor.tenant_id,)).fetchone()[0]
            if active >= quota:
                raise DomainError('command_quota_exceeded')
        op = new_id('op')
        db.execute('INSERT INTO operations(id,tenant_id,principal_id,actor_epoch,publication_id,revision,action,request_digest,request,created,deadline,state,complete,work_state,result) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (op, actor.tenant_id, actor.principal_id, actor.epoch, publication, revision, action, digest([action, intent]), canonical(intent),
                    self.store.clock(), self.store.clock()+(30*86400 if action == 'media_store' else command_timeout),
                    'verified' if complete else 'accepted', int(complete), 'done' if complete else 'ready', canonical(result or {})))
        self.store.event(db, op, 'finished' if complete else 'accepted', 'completed' if complete else 'started',
                         'Local operation complete' if complete else 'Command durably accepted; no provider effect yet')
        return op

    def _replay(self, db, actor, action, intent, args, *, implicit=True):
        identity = digest([action, intent])
        key = args.get('request_key')
        if key:
            row = db.execute('SELECT * FROM request_keys WHERE tenant_id=? AND principal_id=? AND key=?', (actor.tenant_id, actor.principal_id, key)).fetchone()
            if row:
                if row['digest'] != identity:
                    raise DomainError('idempotency_conflict', 'Request key is already bound to different content')
                self.store.private_operation(db, actor, row['operation_id'])
                return row['operation_id']
        if not implicit:
            return None
        if not args.get('repeat_of'):
            # A finished operation that sent nothing anywhere is not a duplicate:
            # the same content may be submitted again after a refusal is fixed.
            row = db.execute('SELECT id FROM operations o WHERE tenant_id=? AND principal_id=? AND request_digest=? AND created>=? '
                             'AND NOT (o.complete=1 AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.operation_id=o.id AND a.dispatched=1)) '
                             'ORDER BY created LIMIT 1',
                             (actor.tenant_id, actor.principal_id, identity, self.store.clock()-86400)).fetchone()
            if row:
                self.store.private_operation(db, actor, row['id'])
                if key:
                    self._key(db, actor, key, identity, row['id'])
                return row['id']
        elif not key:
            raise DomainError('repeat_requires_new_key')
        else:
            previous = self.store.private_operation(db, actor, args['repeat_of'])
            if (previous['state'] == 'outcome_unknown' or not previous['complete']
                    or db.execute("SELECT 1 FROM attempts WHERE operation_id=? AND dispatched=1 "
                                  "AND state IN ('blocked','failed','partial') LIMIT 1",
                                  (previous['id'],)).fetchone()):
                raise DomainError('repeat_not_proven_safe')
        return None

    def _key(self, db, actor, key, identity, op):
        db.execute('INSERT INTO request_keys VALUES(?,?,?,?,?,?)', (actor.tenant_id, actor.principal_id, key, identity, op, self.store.clock()))

    def _targets(self, db, actor, aliases):
        result = {}
        for alias in aliases:
            group = db.execute('SELECT members FROM destination_sets WHERE tenant_id=? AND principal_id=? AND alias=?', (actor.tenant_id, actor.principal_id, alias)).fetchone()
            for name in json.loads(group['members']) if group else [alias]:
                b = self.store.binding(db, actor, alias=name)
                result.setdefault((b['provider'], b['native_id']), dict(b))
        if len(result) > 100:
            raise DomainError('too_many_destinations')
        return list(result.values())

    def _media(self, db, actor, items, *, allow_video=False, allow_document=False, existing=None, provider=None, action=None):
        output = []
        for entry in items:
            if entry['source']['kind'] == 'existing':
                if provider != 'vk' or action != 'edit' or not existing:
                    raise DomainError('native_attachment_not_enabled')
                media = existing.get('provider_media') or []
                position = entry['source']['position']
                if (position >= len(media) or not media[position].startswith('photo')
                        or entry.get('role', 'image') not in {'image', 'auto'}
                        or entry.get('caption') or entry.get('alt_text')):
                    raise DomainError('native_attachment_invalid', next_action='refresh')
                reference = media[position]
                output.append({'ref': reference, 'provider_ref': reference, 'sha256': '',
                               'mime': 'image/jpeg', 'size': 0, 'role': 'image',
                               'caption': '', 'alt_text': ''})
                continue
            if entry['source']['kind'] != 'asset':
                raise DomainError('media_ingress_not_enabled', 'Import a verified image with the owner CLI; URL/upload-ticket ingress is not enabled', 'contact_owner')
            row = db.execute('SELECT * FROM assets WHERE id=? AND tenant_id=? AND principal_id=?', (entry['source']['id'], actor.tenant_id, actor.principal_id)).fetchone()
            if not row:
                raise DomainError('asset_not_available')
            origin = db.execute('SELECT job_id FROM visual_asset_origins WHERE asset_id=?', (row['id'],)).fetchone()
            if origin:
                self.visuals.job(db, actor, origin['job_id'])
            emoji_origin = db.execute('SELECT catalog_id FROM emoji_asset_origins WHERE asset_id=?', (row['id'],)).fetchone()
            if emoji_origin:
                self.emojis.catalog(db, actor, emoji_origin['catalog_id'], latest=True)
            role = entry.get('role', 'image')
            if role == 'auto':
                role = 'video' if row['mime'] == 'video/mp4' else 'image'
            if role == 'video':
                if not allow_video or row['mime'] != 'video/mp4':
                    raise DomainError('media_role_not_enabled')
            elif role == 'document':
                if not allow_document or row['mime'] not in {'image/png', 'image/jpeg', 'image/webp', 'application/pdf', 'image/vnd.djvu'}:
                    raise DomainError('media_role_not_enabled')
            elif role != 'image' or not row['mime'].startswith('image/'):
                raise DomainError('media_role_not_enabled')
            output.append({'ref': row['id'], 'sha256': row['sha256'], 'mime': row['mime'], 'size': len(row['bytes']),
                           'role': role, 'caption': entry.get('caption', ''), 'alt_text': entry.get('alt_text', '')})
        return output

    def _plan(self, db, actor, binding, target, action, existing=None, *, pending_visual=False, topic_root_id=None):
        required = 'publish' if action in ('publish', 'approve') else action
        binding_rights = json.loads(binding['rights'])
        if required not in binding_rights:
            raise DomainError('access_denied', 'Binding does not allow this command', 'contact_owner')
        if target.get('visual') and not pending_visual:
            raise DomainError('visual_requires_visual_service')
        content = target.get('renderings', {}).get(binding['provider'], target.get('content', {'text': ''}))
        if action == 'edit' and 'media' in target and not target['media']:
            raise DomainError('media_removal_needs_review')
        assets = self._media(db, actor, target.get('media', []), allow_video=binding['provider'] in {'telegram', 'vk'} or (binding['provider'] == 'max' and binding['account_type'] == 'max_web'), allow_document=binding['provider'] == 'telegram', existing=existing, provider=binding['provider'], action=action)
        if binding['account_type'] != 'fake':
            for asset in assets:
                fixture = db.execute('SELECT fixture FROM visual_asset_origins WHERE asset_id=?', (asset['ref'],)).fetchone()
                if fixture and fixture[0]:
                    raise DomainError('fixture_asset_native_publish_forbidden', next_action='contact_owner')
        admission_error = None
        if action not in ('forward', 'cancel', 'delete', 'react'):
            try:
                content = self.emojis.compile(db, actor, content, binding, target)
            except DomainError as exc:
                if exc.code not in {'emoji_fallback_required', 'rich_fallback_needs_review'} or action != 'publish':
                    raise
                admission_error, content = exc.code, {'text': ''}
        if (action == 'publish' and actor.owner and not admission_error
                and target.get('surface', 'post') == 'post' and not target.get('thread_ref')):
            content = append_network_footer(
                binding['alias'], binding['provider'], content,
                lambda alias: self.store.binding(db, actor, alias=alias),
                has_media=bool(assets) or pending_visual,
                telegram_user=binding['provider'] == 'telegram' and binding['account_type'] == 'mtproto_user',
            )
        if action not in ('forward', 'cancel', 'delete', 'react') and not assets and not content.get('text', '').strip() and not pending_visual and not admission_error:
            raise DomainError('empty_publication')
        delivery = target.get('delivery', {'kind': 'now'})
        scheduled = timestamp(parse_time(delivery['at'])) if delivery.get('at') else None
        if scheduled and parse_time(scheduled) < self.store.clock()+60:
            raise DomainError('native_lead_time', 'Choose a later native publication time')
        story_link = self._story_link(db, actor, binding, target) if target.get('story_link') else None
        return {'binding_id': binding['id'], 'binding_epoch': binding['epoch'], 'alias': binding['alias'],
                'provider': binding['provider'], 'connection_id': binding['connection_id'], 'account_type': binding['account_type'],
                'secret_ref': binding['secret_ref'], 'destination_id': binding['destination_id'], 'native_target': binding['native_id'],
                'action': action, 'surface': target.get('surface', 'post'), 'content_json': canonical(content), 'assets': assets,
                'scheduled_at': scheduled, 'mode': target.get('mode', 'execute'), 'existing': existing,
                'selection': target.get('selection', 'post'), 'source': None, 'source_authorized': False,
                'basic_group_schedule_authorized': 'basic_group_schedule' in binding_rights,
                **(story_link or {}),
                **({'topic_root_id': topic_root_id} if topic_root_id else {}),
                **({'admission_error': admission_error} if admission_error else {})}

    def _story_link(self, db, actor, binding, target):
        """Freeze a Telegram HTTPS URL or resolve VK's already scoped wall post."""
        if binding['provider'] == 'telegram':
            if (target.get('surface') != 'story'
                    or target.get('delivery', {'kind': 'now'})['kind'] != 'now'):
                raise DomainError('telegram_story_link_requires_immediate_story')
            from urllib.parse import urlsplit
            url = target['story_link'].get('url', '')
            try:
                parts = urlsplit(url)
                if (parts.scheme != 'https' or not parts.hostname
                        or parts.username or parts.password or '\\' in url
                        or any(ord(ch) <= 32 for ch in url)):
                    raise ValueError()
            except (ValueError, TypeError):
                raise DomainError('telegram_story_link_invalid',
                                  'Telegram story link needs an absolute HTTPS URL') from None
            # MediaAreaUrl has no customizable text: the optional input label
            # remains in the frozen caller intent, not a claimed native sticker.
            return {'story_link_json': canonical({'url': url})}
        if (binding['provider'] != 'vk' or target.get('surface') != 'story'
                or target.get('delivery', {'kind': 'now'})['kind'] != 'now'):
            raise DomainError('story_link_requires_immediate_vk_story')
        link = target['story_link']
        reference = link['item_ref']
        if reference.startswith('https://'):
            source = parse_source(reference)
            if source.provider != 'vk':
                raise DomainError('vk_story_wall_link_required')
            channel, ident = source.channel, source.item
            matches = [row for row in self.store.bindings(db, actor)
                       if row['provider'] == 'vk' and row['connection_id'] == binding['connection_id']
                       and row['native_id'] == channel]
            if len(matches) != 1:
                raise DomainError('source_access_denied')
            source_binding = matches[0]
        else:
            item = self.resolve_item(db, actor, reference)
            source_binding = self.store.binding(db, actor, binding_id=item['binding_id'])
            if item['namespace'] != 'published':
                raise DomainError('vk_story_wall_link_required')
            channel, ident = source_binding['native_id'], item['native_id']
        if (source_binding['provider'] != 'vk'
                or source_binding['connection_id'] != binding['connection_id']
                or 'publish' not in json.loads(source_binding['rights'])):
            raise DomainError('source_access_denied')
        import re
        if not re.fullmatch(r'-[1-9][0-9]*', channel) or not re.fullmatch(r'[1-9][0-9]*', ident):
            raise DomainError('vk_story_wall_link_required')
        return {
            'story_link_json': canonical({'url': f'https://vk.com/wall{channel}_{ident}',
                                          'text': link['text'], 'target': channel, 'id': ident}),
            'story_link_binding_id': source_binding['id'],
            'story_link_binding_epoch': source_binding['epoch'],
        }

    def _telegram_thread(self, db, actor, ref, *, alias=None):
        """Resolve a topic through an existing scoped binding; never create a grant."""
        if ref.startswith('https://'):
            source = parse_source(ref)
            if source.provider != 'telegram' or source.public_candidate:
                raise DomainError('telegram_thread_reference_required')
            matches = [dict(row) for row in self.store.bindings(db, actor)
                       if row['provider'] == 'telegram' and row['native_id'] == source.channel and (alias is None or row['alias']==alias)]
            if alias is None and len(matches)>1:
                ordinary=[row for row in matches if row['secret_ref']!='VIBEPUBLISH_KNOWLEDGE_BASE_AUTH_BUNDLE']
                if len(ordinary)==1:matches=ordinary
            if len(matches) != 1:
                raise DomainError('access_denied', 'The Telegram group is not bound for this principal', 'contact_owner')
            import logging
            logging.getLogger(__name__).info(canonical({'event':'telegram_topic_connection_selected','connection_id':matches[0]['connection_id'],'explicit_alias':alias is not None}))
            return matches[0], source.item
        item = self.resolve_item(db, actor, ref)
        binding = dict(self.store.binding(db, actor, binding_id=item['binding_id']))
        if binding['provider'] != 'telegram':
            raise DomainError('telegram_thread_reference_required')
        snapshot = json.loads(item['snapshot'])
        topic = snapshot.get('reply_to_native_id') or item['native_id']
        if not isinstance(topic, str) or not topic.isdigit() or int(topic) <= 0:
            raise DomainError('telegram_thread_reference_required')
        return binding, topic

    def accept(self, actor, action, args):
        if action == 'publication_update':
            with self.store.connection() as db:
                actor = self.store.current(db, actor)
            if 'publication.manage' not in actor.scopes and (
                    'publish' not in actor.scopes or args['change']['kind'] not in {'retry_failed', 'supersede_failed'}):
                raise DomainError('access_denied', next_action='contact_owner')
        if action == 'publication_update' and args['change']['kind'] == 'reconcile_removed':
            from .unknown_resolution import accept_resolution
            return accept_resolution(self, actor, args)
        if action == 'publication_update' and args['change']['kind'] == 'retry_failed':
            from .recovery import retry_failed
            return retry_failed(self, actor, args)
        if action == 'publication_update' and args['change']['kind'] == 'supersede_failed':
            from .recovery import supersede_failed
            return supersede_failed(self, actor, args)
        if action == 'publication_update' and args['change']['kind'] == 'reconcile':
            from .recovery import admit
            return admit(self, actor, args)
        intent = normalize_intent(action, args)
        if action == 'publish' and intent.get('visual'):
            intent['visual'] = self.visuals.normalize_spec(intent['visual'])
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            op = self._replay(db, actor, action, intent, args)
            if not op:
                active = db.execute("SELECT count(*) FROM operations WHERE tenant_id=? AND work_state!='done'", (actor.tenant_id,)).fetchone()[0]
                maximum = db.execute('SELECT command_limit FROM tenants WHERE id=?', (actor.tenant_id,)).fetchone()[0]
                if active >= maximum:
                    raise DomainError('command_quota_exceeded')
                if args.get('routing_revision', actor.routing_revision) != actor.routing_revision:
                    raise DomainError('routing_stale', 'Refresh destination profiles before publishing', 'refresh')
                if action == 'publication_update':
                    publication, revision, plans = (self._adopt_plan(db, actor, args) if args.get('item_ref') else self._update_plan(db, actor, args))
                else:
                    target = intent if action in {'publish', 'media_store'} else intent['command']
                    actual = 'publish' if action in {'publish', 'media_store'} else target['kind']
                    if actual not in ('publish', 'forward', 'reply', 'react'):
                        raise DomainError('capability_not_implemented', next_action='contact_owner')
                    if actual in ('reply','react'):
                        reference=self.resolve_item(db,actor,target['item_ref'])
                        binding=self.store.binding(db,actor,binding_id=reference['binding_id'])
                        if binding['provider']!='max' or binding['account_type'] not in ('max_web','fake'):
                            raise DomainError('engagement_provider_not_enabled')
                        subject=json.loads(reference['snapshot']);subject['media_hashes']=[]
                        if subject['namespace']!='published':raise DomainError('engagement_requires_published_subject')
                        body=target.get('content',{'text':subject['text']})
                        intent_target={'content':body,'delivery':{'kind':'now'}}
                        plan=self._plan(db,actor,binding,intent_target,actual,subject if actual=='react' else None)
                        plan.update(subject=subject,subject_ref=target['item_ref'],reaction=target.get('reaction'),reaction_mode=target.get('mode'))
                        plans=[plan]
                    else:
                        if action == 'media_store':
                            staged = []
                            for item in target['media']:
                                if item.get('role', 'document') not in {'auto', 'document'}:
                                    raise DomainError('media_store_document_required')
                                source = item['source']
                                if source['kind'] != 'asset':
                                    raise DomainError('media_ingress_not_enabled')
                                row = db.execute(
                                    'SELECT * FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                                    (source['id'], actor.tenant_id, actor.principal_id)).fetchone()
                                if not row:
                                    raise DomainError('asset_not_available')
                                clone = new_id('asset')
                                db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
                                           (clone, row['tenant_id'], row['principal_id'], row['sha256'], row['mime'],
                                            row['width'], row['height'], row['bytes'], row['source_sha256'], self.store.clock()))
                                staged.append({**item, 'source': {'kind': 'asset', 'id': clone},
                                               'role': 'document'})
                            target = {**target, 'media': staged}
                        target_bindings = self._targets(db, actor, target['to'])
                        if actual == 'publish' and target.get('thread_ref'):
                            thread_binding, topic_root_id = self._telegram_thread(db, actor, target['thread_ref'],alias=target_bindings[0]['alias'] if len(target_bindings)==1 else None)
                            if (len(target_bindings) != 1 or target_bindings[0]['id'] != thread_binding['id']
                                    or 'publish' not in json.loads(thread_binding['rights'])):
                                raise DomainError('access_denied', 'Thread target must belong to the single authorized destination', 'contact_owner')
                            plans = [self._plan(db, actor, thread_binding, target, actual,
                                                pending_visual=bool(target.get('visual')), topic_root_id=topic_root_id)]
                        else:
                            plans = [self._plan(db, actor, b, target, actual, pending_visual=bool(target.get('visual')))
                                     for b in target_bindings]
                    if actual == 'forward':
                        from dataclasses import asdict
                        item = target['item_ref']
                        if item.startswith('https://'):
                            source = parse_source(item)
                        else:
                            from .domain import NativeSource
                            source_ref = self.resolve_item(db, actor, item)
                            source_binding = self.store.binding(db, actor, binding_id=source_ref['binding_id'])
                            if source_ref['namespace'] != 'published':
                                raise DomainError('forward_requires_published_source')
                            channel, native_id = source_binding['native_id'], source_ref['native_id']
                            if source_binding['provider'] == 'telegram':
                                if not channel.lstrip('-').isdigit() or int(channel) >= -1_000_000_000_000:
                                    raise DomainError('forward_source_kind_needs_review')
                                url = f'https://t.me/c/{-int(channel)-1_000_000_000_000}/{native_id}'
                            elif source_binding['provider']=='max' and source_binding['account_type'] in ('max_web','fake'):
                                import re
                                snapshot=json.loads(source_ref['snapshot'])
                                url=snapshot.get('url','')
                                if not re.fullmatch(r'https://max\.ru/c/-[1-9][0-9]*/[A-Za-z0-9_-]+',url) or url!=f'https://max.ru/c/{channel}/{native_id}':
                                    raise DomainError('max_forward_native_reference_required')
                                for plan in plans:
                                    plan['subject']={**snapshot,'media_hashes':[]}
                            elif source_binding['provider'] == 'vk':
                                url = f'https://vk.ru/wall{channel}_{native_id}'
                            else:
                                raise DomainError('forward_provider_needs_review')
                            source = NativeSource(source_binding['provider'], channel, native_id, False, url)
                        if any(p['provider'] != source.provider for p in plans):
                            raise DomainError('cross_provider_forward', 'Native forwarding requires matching source and every destination provider')
                        for plan in plans:
                            authorized = any(b['provider'] == source.provider and b['connection_id'] == plan['connection_id'] and
                                             source.channel in (b['native_id'], b['handle']) for b in self.store.bindings(db, actor))
                            if not source.public_candidate and not authorized:
                                raise DomainError('source_access_denied', next_action='contact_owner')
                            plan.update(source=asdict(source), source_authorized=authorized)
                    if action == 'media_store':
                        if len(plans) != 1 or plans[0]['provider'] != 'telegram' or plans[0].get('scheduled_at'):
                            raise DomainError('media_store_target_invalid')
                        plans[0]['workload'] = 'media_store'
                    publication, revision = new_id('pub'), 1
                    kind = 'media_store' if action == 'media_store' else actual
                    db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?)', (publication, actor.tenant_id, actor.principal_id, revision, kind, self.store.clock()))
                db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?)', (actor.tenant_id, actor.principal_id, publication, revision, canonical(intent), canonical(plans), digest(plans)))
                from .execution_budgets import command_seconds
                op = self._new_operation(db, actor, action, intent, publication=publication, revision=revision,
                                         command_timeout=command_seconds(plans))
                pending_visual = intent.get('visual') if action == 'publish' else None
                if pending_visual:
                    self.visuals.create(db, actor, pending_visual, op, plans, publication=publication, revision=revision)
                for plan in (() if pending_visual else plans):
                    db.execute('INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,plan,plan_digest) VALUES(?,?,?,?,?,?,?,?)',
                               (new_id('attempt'), op, plan['binding_id'], plan['binding_epoch'], plan['alias'], plan['provider'], canonical(plan), digest(plan)))
                if action == 'publish' and intent.get('linked_story') is not None:
                    from .vk_story_dependencies import register
                    register(self, db, actor, intent, op, plans)
                if action == 'media_store':
                    staging_expires = db.execute(
                        'SELECT deadline FROM operations WHERE id=?', (op,)).fetchone()['deadline'] + 3600
                    for plan in plans:
                        for asset in plan['assets']:
                            db.execute('INSERT INTO media_store_assets VALUES(?,?,?,?)',
                                       (asset['ref'], publication, 'staging', staging_expires))
                    for media in intent['media']:
                        original=db.execute('select mime from assets where id=?',(media['source']['id'],)).fetchone()
                        if original and original['mime'] in {'application/pdf','image/vnd.djvu'}:
                            from .asset_ingress import _response
                            ingress_keys=db.execute("SELECT o.id,k.key FROM operations o JOIN request_keys k ON k.operation_id=o.id WHERE o.tenant_id=? AND o.principal_id=? AND o.action='asset_ingress' AND json_extract(o.result,'$.resource_id')=?",(actor.tenant_id,actor.principal_id,media['source']['id'])).fetchall()
                            for ingress in ingress_keys:
                                receipt=_response(db,actor,media['source']['id'],ingress['key'])
                                db.execute("UPDATE operations SET result=json_set(result,'$.document_receipt',json(?)) WHERE id=?",(canonical(receipt),ingress['id']))
                            db.execute("INSERT INTO media_store_assets VALUES(?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET publication_id=excluded.publication_id,expires=excluded.expires WHERE media_store_assets.purpose='staging'",(media['source']['id'],publication,'staging',staging_expires))
                if args.get('request_key'):
                    self._key(db, actor, args['request_key'], digest([action, intent]), op)
        return self.store.receipt(actor, op)

    def _adopt_plan(self, db, actor, args):
        """A shared-channel read ref gives item CAS, never another author's draft."""
        source = self.resolve_item(db, actor, args['item_ref'])
        b = self.store.binding(db, actor, binding_id=source['binding_id'])
        remote = json.loads(source['snapshot'])
        if 'media' in args['change']:
            if b['provider'] == 'telegram':
                from .managed_item_edits import adopt
                return adopt(self, db, actor, args, source, b, remote)
            if b['provider'] != 'vk':
                raise DomainError('external_media_replace_needs_review', next_action='contact_owner')
            from .managed_item_edits import _fresh_read
            _fresh_read(db, actor, source, b, remote, self.store.clock())
        # Preserve native object IDs, not another principal's private asset hashes.
        remote['media_hashes'] = []
        change, kind = args['change'], args['change']['kind']
        if kind not in {'edit', 'reschedule', 'cancel', 'delete'}:
            raise DomainError('native_item_change_unsupported')
        if remote['namespace'] not in {'scheduled', 'published', 'story'}:
            raise DomainError('native_item_not_active', next_action='refresh')
        if kind in {'cancel', 'reschedule'} and remote['namespace'] != 'scheduled':
            raise DomainError('native_queue_item_required')
        if remote['namespace'] == 'story' and kind != 'delete':
            raise DomainError('vk_story_item_change_unsupported')
        if kind == 'delete' and remote['namespace'] not in {'published', 'story'}:
            raise DomainError('delete_requires_published')
        if remote.get('origin') and kind in {'edit', 'reschedule'}:
            raise DomainError('forward_lifecycle_not_enabled', next_action='contact_owner')
        target = {'content': {'text': remote['text']},
                  'surface': 'story' if remote['namespace'] == 'story' else 'post',
                  'delivery': {'kind': 'at', 'at': remote['scheduled_at']} if remote.get('scheduled_at') else {'kind': 'now'}}
        if (b['provider'] == 'telegram' or (b['provider'] == 'max' and b['account_type'] == 'max_web')) and remote.get('entities_json', '[]') != '[]':
            target['content'] = {'text': remote['text'], 'format': 'telegram_entities' if b['provider'] == 'telegram' else 'max_entities', 'entities': json.loads(remote['entities_json'])}
        if kind == 'edit':
            target.update({k: v for k, v in change.items() if k not in {'kind', 'destinations'}})
        elif kind == 'reschedule':
            target['delivery'] = change['delivery']
        if kind in {'cancel', 'delete'}:
            target['delivery'] = {'kind': 'now'}
        plan = self._plan(db, actor, b, target, kind, remote)
        publication = new_id('pub')
        db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?)',
                   (publication, actor.tenant_id, actor.principal_id, 1, 'forward' if remote.get('origin') else 'publish', self.store.clock()))
        return publication, 1, [plan]

    def _update_plan(self, db, actor, args):
        pub = db.execute('SELECT * FROM publications WHERE id=? AND tenant_id=? AND principal_id=?', (args['publication_id'], actor.tenant_id, actor.principal_id)).fetchone()
        if not pub or pub['revision'] != args['expected_revision']:
            raise DomainError('revision_conflict', 'Refresh the exact publication revision', 'refresh')
        previous = self.store.private_operation(db, actor, pub['id'])
        if json.loads(previous['request']).get('change', {}).get('kind') == 'reconcile_removed':
            raise DomainError('remote_item_not_bound', 'Removed object cannot be edited or retried; create a new explicit publication')
        if previous['state'] == 'needs_selection':
            raise DomainError('visual_selection_required', next_action='select_visual')
        if previous['work_state'] != 'done':
            raise DomainError('operation_in_progress', next_action='check_status')
        change = args['change']
        kind = change['kind']
        if kind == 'retry_failed' or (previous['state'] == 'outcome_unknown' and not change.get('destinations')):
            raise DomainError('retry_not_proven_safe')
        if kind == 'approve':
            token = db.execute('SELECT * FROM decisions WHERE publication_id=? AND revision=? AND token_hash=? AND consumed_by IS NULL',
                               (pub['id'], pub['revision'], self.store.token_hash(change['token']))).fetchone()
            if previous['state'] != 'needs_approval' or not token:
                raise DomainError('approval_invalid', next_action='refresh')
            db.execute('UPDATE decisions SET consumed_by=? WHERE id=?', (new_id('consumed'), token['id']))
        plans = []
        from .managed_item_edits import latest_attempts, selected_attempts
        heads = latest_attempts(db, previous)
        children = selected_attempts(self.store, db, actor, args, heads)
        for child in children:
            old = json.loads(child['plan'])
            observed = json.loads(child['checkpoint']).get('remote')
            if kind != 'approve' and not observed:
                raise DomainError('remote_item_not_bound')
            if kind == 'cancel' and observed['namespace'] != 'scheduled':
                raise DomainError('already_published', 'Cancel applies only to a native queued item; deletion needs an explicit command')
            if kind in ('edit', 'reschedule') and old['action'] == 'forward':
                raise DomainError('forward_lifecycle_not_enabled', next_action='contact_owner')
            if kind in ('edit', 'reschedule') and old['scheduled_at'] and parse_time(old['scheduled_at']) < self.store.clock()+60:
                # Telegram assigns new message ids on publication; the queued identity is gone.
                raise DomainError('native_item_published', 'The scheduled item is already published: read it and change it by item_ref', 'refresh')
            b = self.store.binding(db, actor, binding_id=child['binding_id'])
            target = {'content': json.loads(old['content_json']),
                      'surface': old['surface'], 'delivery': {'kind': 'at', 'at': old['scheduled_at']} if old['scheduled_at'] else {'kind': 'now'}, 'mode': 'execute'}
            if kind == 'approve':
                target['media'] = [{'source': {'kind': 'asset', 'id': a['ref']}, 'role': a.get('role', 'image'), 'caption': a['caption'], 'alt_text': a['alt_text']} for a in old['assets']]
            if kind == 'edit':
                target.update({k: v for k, v in change.items() if k not in {'kind', 'destinations'}})
            elif kind == 'reschedule':
                target['delivery'] = change['delivery']
            if kind in ('cancel', 'delete'):
                target['delivery'] = {'kind': 'now'}
            plan = self._plan(db, actor, b, target, 'publish' if kind == 'approve' else kind, observed,
                              topic_root_id=old.get('topic_root_id') if kind == 'approve' else None)
            if kind == 'approve':
                plan.update(action=old['action'], source=old['source'], source_authorized=old['source_authorized'])
            plans.append(plan)
        revision = pub['revision'] + 1
        db.execute('UPDATE publications SET revision=? WHERE id=? AND revision=?', (revision, pub['id'], pub['revision']))
        return pub['id'], revision, plans

    async def status(self, actor, args):
        with self.store.connection() as db:
            self.store.current(db, actor)
            if args.get('cursor'):
                raise DomainError('list_cursor_not_enabled', next_action='refresh')
            ids = args.get('ids') or [r[0] for r in db.execute('SELECT id FROM operations WHERE tenant_id=? AND principal_id=? ORDER BY created DESC LIMIT ?', (actor.tenant_id, actor.principal_id, args.get('limit', 20)))]
        deadline = asyncio.get_running_loop().time() + args.get('wait_seconds', 0)
        while True:
            ready = not ids if args.get('wait_final') else True
            kinds = {}
            with self.store.connection() as db:
                for ident in ids:
                    op = self.store.private_operation(db, actor, ident)
                    kinds[ident] = op['action']
                    if args.get('wait_final'):
                        ready = ready and bool(op['complete'])
                    elif args.get('after_event'):
                        seq = self.store.cursor_position(db, actor, args['after_event'], 'events', op['id'])
                        event = db.execute('SELECT 1 FROM events WHERE operation_id=? AND seq>? LIMIT 1', (op['id'], seq)).fetchone()
                        ready = ready and (event is not None or bool(op['complete']))
            if ready or asyncio.get_running_loop().time() >= deadline:
                return {'receipts': [self.store.receipt(
                    actor, ident, after=args.get('after_event'), event_limit=args.get('limit', 50),
                    brief=not args.get('after_event') and kinds[ident] == 'publish',
                ) for ident in ids]}
            await asyncio.sleep(0.1)  # Wait only for durable completion; never send or write here.

    def destinations(self, actor, args):
        intent = normalize_intent('destinations', args)
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            if args['command']['kind'] == 'binding_grant_edit':
                if not actor.owner or not {'destinations', 'publication.manage'} <= actor.scopes:
                    raise DomainError('access_denied', next_action='contact_owner')
                if list(Draft202012Validator(CATALOG['vibepublish_destinations']['inputSchema'],
                                             format_checker=FORMATS).iter_errors(args)):
                    raise DomainError('invalid_input')
                self.store.binding(db, actor, alias=args['command']['alias'])
            # Keyed replay precedes profile/set CAS, atomically with mutations.
            op = self._replay(db, actor, 'destinations', intent, args, implicit=False)
            if not op:
                op = self._destinations_mutation(db, actor, args['command'], intent)
                if args.get('request_key'):
                    self._key(db, actor, args['request_key'], digest(['destinations', intent]), op)
        return self.store.receipt(actor, op)

    def _destinations_mutation(self, db, actor, command, intent):
        action = command['kind']
        if action == 'binding_grant_edit':
            actor = self.store.current(db, actor)
            if not actor.owner or not {'destinations', 'publication.manage'} <= actor.scopes:
                raise DomainError('access_denied', next_action='contact_owner')
            binding = self.store.binding(db, actor, alias=command['alias'])
            if binding['epoch'] != command['expected_binding_epoch']:
                raise DomainError('binding_epoch_conflict', next_action='refresh')
            if actor.routing_revision != command['expected_routing_revision']:
                raise DomainError('routing_revision_conflict', next_action='refresh')
            before = {'rights': json.loads(binding['rights']), 'binding_epoch': binding['epoch'],
                      'actor_epoch': actor.epoch, 'routing_revision': actor.routing_revision}
            rights = self.store._grant_binding_rights(db, actor, binding['id'], ('edit',))
            current = self.store.current(db, actor)
            after = {**before, 'rights': rights, 'routing_revision': current.routing_revision}
            return self._new_operation(db, current, 'destinations', intent, complete=True,
                result={'binding_grant': {'binding_id': binding['id'], 'alias': binding['alias'],
                                         'right': 'edit', 'before': before, 'after': after}})
        if action.startswith('emoji_'):
            return self.emojis.commands(db, actor, command, intent)
        if action == 'resolve':
            from .destination_resolution import admit
            return admit(self, db, actor, command, intent)
        if action in ('search', 'rename_label'):
            raise DomainError('capability_not_implemented', next_action='contact_owner')
        if action == 'profile_update':
            if command['alias'] not in {d['alias'] for d in self.aliases(db, actor)}:
                raise DomainError('access_denied', next_action='contact_owner')
            row = db.execute('SELECT * FROM profiles WHERE tenant_id=? AND principal_id=? AND alias=?', (actor.tenant_id, actor.principal_id, command['alias'])).fetchone()
            revision = row['revision'] if row else 0
            if revision != command['expected_revision']:
                raise DomainError('profile_revision_conflict', next_action='refresh')
            profile = json.loads(row['profile']) if row else {'usage': 'secondary', 'selection': 'explicit_only'}
            profile.update(command['profile'])
            db.execute('INSERT INTO profiles VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,principal_id,alias) DO UPDATE SET revision=excluded.revision,profile=excluded.profile',
                       (actor.tenant_id, actor.principal_id, command['alias'], revision+1, canonical(profile)))
        elif action in ('set_put', 'set_delete'):
            row = db.execute('SELECT * FROM destination_sets WHERE tenant_id=? AND principal_id=? AND alias=?', (actor.tenant_id, actor.principal_id, command['alias'])).fetchone()
            if (row['revision'] if row else 0) != command['expected_revision']:
                raise DomainError('set_revision_conflict', next_action='refresh')
            if any(r['alias'] == command['alias'] for r in self.store.bindings(db, actor)):
                raise DomainError('alias_conflict')
            if action == 'set_delete':
                db.execute('DELETE FROM destination_sets WHERE tenant_id=? AND principal_id=? AND alias=?', (actor.tenant_id, actor.principal_id, command['alias']))
            else:
                for alias in command['members']:
                    self.store.binding(db, actor, alias=alias)  # No nested sets.
                db.execute('INSERT INTO destination_sets VALUES(?,?,?,?,?,?) ON CONFLICT(tenant_id,principal_id,alias) DO UPDATE SET label=excluded.label,revision=excluded.revision,members=excluded.members',
                           (actor.tenant_id, actor.principal_id, command['alias'], command['label'], command['expected_revision']+1, canonical(list(dict.fromkeys(command['members'])))))
        if action != 'list':
            db.execute('UPDATE principals SET routing_revision=routing_revision+1 WHERE id=?', (actor.principal_id,))
        return self._new_operation(db, actor, 'destinations', intent, complete=True,
                                   result={'destinations': self.aliases(db, actor)[:100]})

    def read(self, actor, args):
        query = args['query']
        if query['kind'].startswith('emoji_'):
            return self.emojis.read(actor, args)
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            kind = query['kind']
            if kind not in ('scheduled', 'feed', 'search', 'item', 'thread', 'history', 'analytics','reactions'):
                raise DomainError('capability_not_implemented', next_action='contact_owner')
            if kind in ('history', 'analytics'):
                if args.get('cursor'):
                    raise DomainError('history_cursor_not_enabled', next_action='refresh')
                bindings = self._targets(db, actor, [query['destination']]) if query.get('destination') else [dict(b) for b in self.store.bindings(db, actor)]
                items = []
                for b in bindings:
                    if 'publish' not in json.loads(b['rights']) and not actor.owner:
                        continue
                    rows = db.execute('SELECT * FROM facts WHERE destination_id=? ORDER BY observed_at DESC LIMIT 200', (b['destination_id'],)).fetchall()
                    for row in rows:
                        if query.get('author', 'mine') == 'mine' and row['initiator'] != actor.principal_id:
                            continue
                        if query.get('publication_ids') and row['publication_id'] not in query['publication_ids']:
                            continue
                        if query.get('text', '').casefold() not in row['text'].casefold():
                            continue
                        remote = json.loads(row['snapshot'])
                        if query.get('from') and parse_time(remote['observed_at']) < parse_time(query['from']):
                            continue
                        if query.get('to') and parse_time(remote['observed_at']) > parse_time(query['to']):
                            continue
                        if query.get('publication_kind') and query['publication_kind'] != ('forward' if remote.get('origin') else 'original'):
                            continue
                        if query.get('state') and query['state'] != ('provider_scheduled' if remote['namespace'] == 'scheduled' else remote['namespace']):
                            continue
                        items.append(self.project_item(db, actor, b, remote, source='local_history', publication=row['publication_id']))
                if kind == 'analytics' and query.get('freshness') == 'refresh':
                    raise DomainError('metrics_refresh_not_enabled', next_action='contact_owner')
                limit = args.get('limit', 25)
                op = self._new_operation(db, actor, 'read', args, complete=True, result={'items': items[:limit], 'truncated': len(items)>limit})
            else:
                intent = json.loads(canonical(args))
                if kind == 'thread':
                    b, topic_root_id = self._telegram_thread(db, actor, query['item_ref'])
                    intent['_topic_root_id'] = topic_root_id
                elif kind in {'item','reactions'}:
                    if kind == 'item' and query['item_ref'].startswith('https://'):
                        # Exact Telegram permalink inside an existing grant. Reading it
                        # produces a fresh native snapshot ref for safe in-place edits.
                        # A URL alone never creates a destination or authorization.
                        source = parse_source(query['item_ref'])
                        if source.provider == 'vk':
                            matches = [dict(row) for row in self.store.bindings(db, actor)
                                       if row['provider'] == 'vk' and row['native_id'] == source.channel]
                        elif source.provider == 'telegram':
                            matches = [dict(row) for row in self.store.bindings(db, actor)
                                       if row['provider'] == 'telegram' and (
                                           row['native_id'] == source.channel or
                                           str(row['handle'] or '').lstrip('@').casefold() == source.channel)]
                            if len(matches) > 1:
                                ordinary = [row for row in matches
                                            if row['secret_ref'] != 'VIBEPUBLISH_KNOWLEDGE_BASE_AUTH_BUNDLE']
                                if len(ordinary) == 1:
                                    matches = ordinary
                        else:
                            raise DomainError('item_link_provider_not_enabled')
                        if len(matches) != 1:
                            raise DomainError('item_link_not_bound', next_action='contact_owner')
                        b = matches[0]
                        intent['_native_item'] = source.item
                        intent['_namespace'] = 'published'
                    else:
                        ref = self.resolve_item(db, actor, query['item_ref'])
                        b = self.store.binding(db, actor, binding_id=ref['binding_id'])
                        intent['_native_item'] = ref['native_id']
                        intent['_namespace'] = ref['namespace']
                        if kind == 'reactions' and (b['provider'] != 'max' or ref['namespace'] != 'published'):
                            raise DomainError('reaction_read_surface_not_enabled')
                else:
                    b = self.store.binding(db, actor, alias=query['destination'])
                if 'publish' not in json.loads(b['rights']) and not actor.owner:
                    raise DomainError('access_denied', next_action='contact_owner')
                intent['_binding_id'] = b['id']
                intent['_binding_epoch'] = b['epoch']
                if args.get('cursor'):
                    intent['_provider_cursor'] = self.store.cursor_position(db, actor, args['cursor'], 'read', digest(query))
                op = self._new_operation(db, actor, 'read', intent)
        return self.store.receipt(actor, op)

    def resolve_item(self, db, actor, ref):
        self.store.current(db, actor)
        row = db.execute('SELECT * FROM item_refs WHERE id=? AND tenant_id=? AND principal_id=?', (ref, actor.tenant_id, actor.principal_id)).fetchone()
        if not row:
            raise DomainError('item_not_available', next_action='contact_owner')
        b = self.store.binding(db, actor, binding_id=row['binding_id'])
        if b['epoch'] != row['binding_epoch']:
            raise DomainError('access_revoked', next_action='reauthorize')
        return row

    def project_item(self, db, actor, binding, remote, *, source='provider', publication=None, media_assets=()):
        ref = new_id('item')
        db.execute('INSERT INTO item_refs VALUES(?,?,?,?,?,?,?,?)', (ref, actor.tenant_id, actor.principal_id, binding['id'], binding['epoch'], remote['native_id'], remote['namespace'], canonical(remote)))
        item = {'ref': ref, 'kind': 'story' if remote['namespace'] == 'story' else 'post',
                'destination': binding['alias'], 'observed_at': remote['observed_at'],
                'source': source, 'freshness': 'current' if source == 'provider' else 'cached',
                'origin': 'provider_client', 'publication_kind': 'forward' if remote.get('origin') else 'original'}
        if remote.get('native_schedule_origin_json', '{}') != '{}':
            item['native_schedule_origin'] = json.loads(remote['native_schedule_origin_json'])
        if remote.get('entities_json', '[]') != '[]':
            item['entities'] = json.loads(remote['entities_json'])
        if remote.get('text'):
            item['text'] = remote['text']
        if remote.get('scheduled_at'):
            item.update(scheduled_at=remote['scheduled_at'], queue_ref=ref)
        if publication and db.execute('SELECT 1 FROM publications WHERE id=? AND tenant_id=? AND principal_id=?',
                                      (publication, actor.tenant_id, actor.principal_id)).fetchone():
            item['publication_id'] = publication
        if remote.get('observed_media'):
            from dataclasses import asdict
            from adapters.port import downloaded_media
            evidence = [asdict(value) for value in downloaded_media(remote['observed_media'])]
            if media_assets:
                ordered = sorted(media_assets, key=lambda value: value['slot'])
                if [value['slot'] for value in ordered] != list(range(len(evidence))):
                    raise DomainError('download_media_order_invalid')
                item['media'] = []
                for row, asset in zip(evidence, ordered):
                    row.update(asset_ref=asset['asset_ref'], resource_uri='vibepublish://assets/' + asset['asset_ref'],
                               media_kind=asset['media_kind'])
                    item['media'].append({'source': {'kind': 'asset', 'id': asset['asset_ref']},
                                          'role': 'document' if asset['media_kind'] == 'document' else 'image'})
            item['media_evidence'] = evidence
        elif remote.get('media_hashes'):
            item['error'] = {'code': 'media_projection_not_enabled', 'message': 'This checkpoint returns text and timing; provider media downloads are not exposed'}
        if remote.get('own_reactions_observed'):
            item['own_reactions']=list(remote['own_reactions'])
        if remote.get('metrics'):
            item['metrics'] = [{'name': n, 'value': v, 'unit': u} for n,v,u in remote['metrics']]
            item['metrics_observed_at'] = remote['observed_at']
        return item
