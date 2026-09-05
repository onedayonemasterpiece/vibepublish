"""The only application entrypoint for MCP and HTTP. No provider I/O at admission."""
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
from .domain import DomainError, canonical, digest, new_id, normalize_intent, parse_source, parse_time, timestamp

CATALOG = {t['name']: t for t in catalog()['tools']}
FORMATS = FormatChecker()
SKILL = Path(__file__).resolve().parents[1] / 'docs/llm/vibepublish-social-skill.md'
if not SKILL.exists():
    SKILL = Path(sys.prefix) / 'share/vibepublish/vibepublish-social-skill.md'


class Application:
    def __init__(self, store):
        self.store = store
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
            elif short in ('publish', 'engage', 'publication_update'):
                result = self.accept(actor, short, arguments)
            elif short == 'visual':
                result = self.visuals.command(actor, arguments)
            else:
                raise DomainError('capability_not_implemented', next_action='contact_owner')
            # Validate outputs too; a malformed success must never escape to clients.
            Draft202012Validator(CATALOG[name]['outputSchema'], format_checker=FORMATS).validate(result)
            return result
        except DomainError as exc:
            return exc.output()
        except sqlite3.Error:
            return DomainError("store_unavailable", "No receipt could be returned. Recover using status or the same request key, never a new send", "contact_owner").output()

    def read_asset(self, actor, ident):
        with self.store.connection() as db:
            actor = self.store.current(db, actor)
            if not actor.scopes.intersection({'visual', 'publish'}):
                raise DomainError('access_denied', next_action='contact_owner')
            row = db.execute('SELECT * FROM assets WHERE id=? AND tenant_id=? AND principal_id=?',
                             (ident, actor.tenant_id, actor.principal_id)).fetchone()
            if not row:
                raise DomainError('asset_not_available', next_action='refresh')
            origin = db.execute('SELECT job_id FROM visual_asset_origins WHERE asset_id=?', (ident,)).fetchone()
            if origin:
                self.visuals.job(db, actor, origin['job_id'])
            emoji_origin = db.execute('SELECT catalog_id FROM emoji_asset_origins WHERE asset_id=?', (ident,)).fetchone()
            if emoji_origin:
                self.emojis.catalog(db, actor, emoji_origin['catalog_id'], latest=True)
            if hashlib.sha256(row['bytes']).hexdigest() != row['sha256']:
                raise DomainError('asset_integrity')
            return row['bytes'], row['mime'], row['sha256']

    def aliases(self, db, actor):
        result = []
        for row in self.store.bindings(db, actor):
            result.append({'alias': row['alias'], 'kind': 'destination', 'label': row['label'], 'revision': row['epoch']})
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

    def bootstrap(self, actor, args):
        skill = SKILL.read_text()
        if args.get('section') == 'emoji':
            skill = skill.split('## Start and choose a task', 1)[0] + skill[skill.index('## Telegram custom emoji:'):]
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            scope = str(actor.routing_revision)
            offset = self.store.cursor_position(db, actor, args['cursor'], 'bootstrap', scope) if args.get('cursor') else 0
            all_dest = self.aliases(db, actor)
            page = all_dest[offset:offset+50]
            bindings = {r['alias']: r for r in self.store.bindings(db, actor)}
            result = {'version': '1.5.0-runtime-emoji', 'schema_version': VERSION,
                      'skill_sha256': hashlib.sha256(skill.encode()).hexdigest(), 'skill': skill,
                      'estimated_tokens': (len(skill) + 2)//3, 'server_time': timestamp(self.store.clock()),
                      'timezone': actor.timezone, 'policy_epoch': actor.epoch, 'routing_revision': actor.routing_revision,
                      'scheduling': 'provider_native_only', 'read_policy': 'provider_visible_owner' if actor.owner else
                      'bound_publish_destinations' if bindings and 'publish' in actor.scopes else 'none',
                      'destinations': page, 'capabilities': []}
            for d in page:
                row = bindings.get(d['alias'])
                if row:
                    result['capabilities'].append({'destination': row['alias'], 'operation': 'publish', 'surface': 'post',
                        'status': 'needs_review' if row['account_type'] in {'fake','mtproto_user','mtproto_bot','vk_user','vk_group'} else 'needs_auth',
                        'observed_at': timestamp(self.store.clock()),
                        'reason': 'Offline fixture only; no live capability verified' if row['account_type'] == 'fake' else 'Native implementation requires explicit worker wiring and target preflight; no live canary verified'})
            if offset+50 < len(all_dest):
                result['next_cursor'] = self.store.cursor(db, actor, 'bootstrap', scope, offset+50)
            return result

    def _new_operation(self, db, actor, action, intent, *, publication=None, revision=1, complete=False, result=None):
        if not complete:
            active = db.execute("SELECT count(*) FROM operations WHERE tenant_id=? AND work_state!='done'", (actor.tenant_id,)).fetchone()[0]
            quota = db.execute('SELECT command_limit FROM tenants WHERE id=?', (actor.tenant_id,)).fetchone()[0]
            if active >= quota:
                raise DomainError('command_quota_exceeded')
        op = new_id('op')
        db.execute('INSERT INTO operations(id,tenant_id,principal_id,actor_epoch,publication_id,revision,action,request_digest,request,created,deadline,state,complete,work_state,result) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (op, actor.tenant_id, actor.principal_id, actor.epoch, publication, revision, action, digest([action, intent]), canonical(intent),
                    self.store.clock(), self.store.clock()+120, 'verified' if complete else 'accepted', int(complete), 'done' if complete else 'ready', canonical(result or {})))
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
            row = db.execute('SELECT id FROM operations WHERE tenant_id=? AND principal_id=? AND request_digest=? AND created>=? ORDER BY created LIMIT 1',
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
            if previous['state'] == 'outcome_unknown' or not previous['complete']:
                raise DomainError('repeat_not_proven_safe', next_action='review_outcome')
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

    def _media(self, db, actor, items):
        output = []
        for entry in items:
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
            if role not in ('image', 'auto'):
                raise DomainError('media_role_not_enabled')
            output.append({'ref': row['id'], 'sha256': row['sha256'], 'mime': row['mime'], 'size': len(row['bytes']),
                           'role': 'image', 'caption': entry.get('caption', ''), 'alt_text': entry.get('alt_text', '')})
        return output

    def _plan(self, db, actor, binding, target, action, existing=None, *, pending_visual=False):
        required = 'publish' if action in ('publish', 'approve') else action
        if required not in json.loads(binding['rights']):
            raise DomainError('access_denied', 'Binding does not allow this command', 'contact_owner')
        if target.get('visual') and not pending_visual:
            raise DomainError('visual_requires_visual_service')
        content = target.get('renderings', {}).get(binding['provider'], target.get('content', {'text': ''}))
        assets = self._media(db, actor, target.get('media', []))
        if binding['account_type'] != 'fake':
            for asset in assets:
                fixture = db.execute('SELECT fixture FROM visual_asset_origins WHERE asset_id=?', (asset['ref'],)).fetchone()
                if fixture and fixture[0]:
                    raise DomainError('fixture_asset_native_publish_forbidden', next_action='contact_owner')
        admission_error = None
        if action not in ('forward', 'cancel', 'delete'):
            try:
                content = self.emojis.compile(db, actor, content, binding, target)
            except DomainError as exc:
                if exc.code not in {'emoji_fallback_required', 'rich_fallback_needs_review'} or action != 'publish':
                    raise
                admission_error, content = exc.code, {'text': ''}
        if action not in ('forward', 'cancel', 'delete') and not assets and not content.get('text', '').strip() and not pending_visual and not admission_error:
            raise DomainError('empty_publication')
        delivery = target.get('delivery', {'kind': 'now'})
        scheduled = timestamp(parse_time(delivery['at'])) if delivery.get('at') else None
        if scheduled and parse_time(scheduled) < self.store.clock()+60:
            raise DomainError('native_lead_time', 'Choose a later native publication time')
        return {'binding_id': binding['id'], 'binding_epoch': binding['epoch'], 'alias': binding['alias'],
                'provider': binding['provider'], 'connection_id': binding['connection_id'], 'account_type': binding['account_type'],
                'secret_ref': binding['secret_ref'], 'destination_id': binding['destination_id'], 'native_target': binding['native_id'],
                'action': action, 'surface': target.get('surface', 'post'), 'content_json': canonical(content), 'assets': assets,
                'scheduled_at': scheduled, 'mode': target.get('mode', 'execute'), 'existing': existing,
                'selection': target.get('selection', 'post'), 'source': None, 'source_authorized': False,
                **({'admission_error': admission_error} if admission_error else {})}

    def accept(self, actor, action, args):
        intent = normalize_intent(action, args)
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
                    target = intent if action == 'publish' else intent['command']
                    actual = 'publish' if action == 'publish' else target['kind']
                    if actual not in ('publish', 'forward'):
                        raise DomainError('capability_not_implemented', next_action='contact_owner')
                    plans = [self._plan(db, actor, b, target, actual, pending_visual=bool(target.get('visual'))) for b in self._targets(db, actor, target['to'])]
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
                    publication, revision = new_id('pub'), 1
                    db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?)', (publication, actor.tenant_id, actor.principal_id, revision, actual, self.store.clock()))
                db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?)', (actor.tenant_id, actor.principal_id, publication, revision, canonical(intent), canonical(plans), digest(plans)))
                op = self._new_operation(db, actor, action, intent, publication=publication, revision=revision)
                pending_visual = intent.get('visual') if action == 'publish' else None
                if pending_visual:
                    self.visuals.create(db, actor, pending_visual, op, plans, publication=publication, revision=revision)
                for plan in (() if pending_visual else plans):
                    db.execute('INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,plan,plan_digest) VALUES(?,?,?,?,?,?,?,?)',
                               (new_id('attempt'), op, plan['binding_id'], plan['binding_epoch'], plan['alias'], plan['provider'], canonical(plan), digest(plan)))
                if args.get('request_key'):
                    self._key(db, actor, args['request_key'], digest([action, intent]), op)
        return self.store.receipt(actor, op)

    def _adopt_plan(self, db, actor, args):
        """A shared-channel read ref gives item CAS, never another author's draft."""
        source = self.resolve_item(db, actor, args['item_ref'])
        b = self.store.binding(db, actor, binding_id=source['binding_id'])
        remote = json.loads(source['snapshot'])
        # Preserve native object IDs, not another principal's private asset hashes.
        remote['media_hashes'] = []
        change, kind = args['change'], args['change']['kind']
        if kind not in {'edit', 'reschedule', 'cancel', 'delete'}:
            raise DomainError('native_item_change_unsupported')
        if remote['namespace'] not in {'scheduled', 'published'}:
            raise DomainError('native_item_not_active', next_action='refresh')
        if kind in {'cancel', 'reschedule'} and remote['namespace'] != 'scheduled':
            raise DomainError('native_queue_item_required')
        if kind == 'delete' and remote['namespace'] != 'published':
            raise DomainError('delete_requires_published')
        if remote.get('origin') and kind in {'edit', 'reschedule'}:
            raise DomainError('forward_lifecycle_not_enabled', next_action='contact_owner')
        if 'media' in change:
            raise DomainError('external_media_replace_needs_review', next_action='contact_owner')
        target = {'content': {'text': remote['text']}, 'media': [], 'surface': 'post',
                  'delivery': {'kind': 'at', 'at': remote['scheduled_at']} if remote.get('scheduled_at') else {'kind': 'now'}}
        if b['provider'] == 'telegram' and remote.get('entities_json', '[]') != '[]':
            target['content'] = {'text': remote['text'], 'format': 'telegram_entities', 'entities': json.loads(remote['entities_json'])}
        if kind == 'edit':
            target.update({k: v for k, v in change.items() if k != 'kind'})
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
        if previous['state'] == 'needs_selection':
            raise DomainError('visual_selection_required', next_action='select_visual')
        if previous['work_state'] != 'done':
            raise DomainError('operation_in_progress', next_action='check_status')
        change = args['change']
        kind = change['kind']
        if kind == 'retry_failed' or previous['state'] == 'outcome_unknown':
            raise DomainError('retry_not_proven_safe', next_action='review_outcome')
        if kind == 'approve':
            token = db.execute('SELECT * FROM decisions WHERE publication_id=? AND revision=? AND token_hash=? AND consumed_by IS NULL',
                               (pub['id'], pub['revision'], self.store.token_hash(change['token']))).fetchone()
            if previous['state'] != 'needs_approval' or not token:
                raise DomainError('approval_invalid', next_action='refresh')
            db.execute('UPDATE decisions SET consumed_by=? WHERE id=?', (new_id('consumed'), token['id']))
        plans = []
        for child in db.execute('SELECT * FROM attempts WHERE operation_id=?', (previous['id'],)).fetchall():
            old = json.loads(child['plan'])
            observed = json.loads(child['checkpoint']).get('remote')
            if kind != 'approve' and not observed:
                raise DomainError('remote_item_not_bound', next_action='review_outcome')
            if kind == 'cancel' and observed['namespace'] != 'scheduled':
                raise DomainError('already_published', 'Cancel applies only to a native queued item; deletion needs an explicit command')
            if kind in ('edit', 'reschedule') and old['action'] == 'forward':
                raise DomainError('forward_lifecycle_not_enabled', next_action='contact_owner')
            b = self.store.binding(db, actor, binding_id=child['binding_id'])
            target = {'content': json.loads(old['content_json']), 'media': [{'source': {'kind': 'asset', 'id': a['ref']}, 'caption': a['caption'], 'alt_text': a['alt_text']} for a in old['assets']],
                      'surface': old['surface'], 'delivery': {'kind': 'at', 'at': old['scheduled_at']} if old['scheduled_at'] else {'kind': 'now'}, 'mode': 'execute'}
            if kind == 'edit':
                target.update({k: v for k, v in change.items() if k != 'kind'})
            elif kind == 'reschedule':
                target['delivery'] = change['delivery']
            if kind in ('cancel', 'delete'):
                target['delivery'] = {'kind': 'now'}
            plan = self._plan(db, actor, b, target, 'publish' if kind == 'approve' else kind, observed)
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
        deadline = asyncio.get_running_loop().time()+args.get('wait_seconds', 0)
        while True:
            ready = not ids
            with self.store.connection() as db:
                for ident in ids:
                    op = self.store.private_operation(db, actor, ident)
                    seq = self.store.cursor_position(db, actor, args['after_event'], 'events', op['id']) if args.get('after_event') else 0
                    event = db.execute('SELECT 1 FROM events WHERE operation_id=? AND seq>? LIMIT 1', (op['id'], seq)).fetchone()
                    ready = ready or event is not None or bool(op['complete'])
            if ready or asyncio.get_running_loop().time() >= deadline:
                return {'receipts': [self.store.receipt(actor, ident, after=args.get('after_event'), event_limit=args.get('limit', 50)) for ident in ids]}
            await asyncio.sleep(0.025)  # Journal wait only; never a publication timer.

    def destinations(self, actor, args):
        intent = normalize_intent('destinations', args)
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            # Keyed replay precedes profile/set CAS, atomically with mutations.
            op = self._replay(db, actor, 'destinations', intent, args, implicit=False)
            if not op:
                op = self._destinations_mutation(db, actor, args['command'], intent)
                if args.get('request_key'):
                    self._key(db, actor, args['request_key'], digest(['destinations', intent]), op)
        return self.store.receipt(actor, op)

    def _destinations_mutation(self, db, actor, command, intent):
        action = command['kind']
        if action.startswith('emoji_'):
            return self.emojis.commands(db, actor, command, intent)
        if action in ('resolve', 'search', 'rename_label'):
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
            if kind not in ('scheduled', 'feed', 'search', 'item', 'history', 'analytics'):
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
                if kind == 'item':
                    ref = self.resolve_item(db, actor, query['item_ref'])
                    b = self.store.binding(db, actor, binding_id=ref['binding_id'])
                    intent['_native_item'] = ref['native_id']
                    intent['_namespace'] = ref['namespace']
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

    def project_item(self, db, actor, binding, remote, *, source='provider', publication=None):
        ref = new_id('item')
        db.execute('INSERT INTO item_refs VALUES(?,?,?,?,?,?,?,?)', (ref, actor.tenant_id, actor.principal_id, binding['id'], binding['epoch'], remote['native_id'], remote['namespace'], canonical(remote)))
        item = {'ref': ref, 'kind': 'post', 'destination': binding['alias'], 'observed_at': remote['observed_at'],
                'source': source, 'freshness': 'current' if source == 'provider' else 'cached',
                'origin': 'provider_client', 'publication_kind': 'forward' if remote.get('origin') else 'original'}
        if remote.get('entities_json', '[]') != '[]':
            item['entities'] = json.loads(remote['entities_json'])
        if remote.get('text'):
            item['text'] = remote['text']
        if remote.get('scheduled_at'):
            item.update(scheduled_at=remote['scheduled_at'], queue_ref=ref)
        if publication and db.execute('SELECT 1 FROM publications WHERE id=? AND tenant_id=? AND principal_id=?',
                                      (publication, actor.tenant_id, actor.principal_id)).fetchone():
            item['publication_id'] = publication
        if remote.get('media_hashes'):
            item['error'] = {'code': 'media_projection_not_enabled', 'message': 'This checkpoint returns text and timing; provider media downloads are not exposed'}
        if remote.get('metrics'):
            item['metrics'] = [{'name': n, 'value': v, 'unit': u} for n,v,u in remote['metrics']]
            item['metrics_observed_at'] = remote['observed_at']
        return item
