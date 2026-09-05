"""Private, revisioned Telegram palette inside the existing SQLite operation ledger."""
from __future__ import annotations
import asyncio
import hashlib
import io
import json
import math
import re
import secrets
from PIL import Image, ImageDraw
from .assets import verify_image
from .domain import DomainError, canonical, digest, new_id, timestamp
from .rich_text import compile_content, document_id, valid_alt


def set_name(url):
    match = re.fullmatch(r'https://t\.me/addemoji/([A-Za-z][A-Za-z0-9_]{0,63})', url)
    if not match:
        raise DomainError('emoji_set_url_invalid')
    return match[1].lower()


class EmojiService:
    def __init__(self, app):
        self.app, self.store = app, app.store

    def binding(self, db, actor, *, alias=None, binding_id=None, epoch=None):
        b = self.store.binding(db, actor, alias=alias, binding_id=binding_id)
        if ('publish' not in actor.scopes or 'publish' not in json.loads(b['rights'])
                or b['provider'] != 'telegram' or (epoch is not None and b['epoch'] != epoch)):
            raise DomainError('emoji_access_denied', next_action='reauthorize')
        return b

    def catalog(self, db, actor, ident, *, latest=False):
        self.store.current(db, actor)
        row = db.execute('SELECT * FROM emoji_catalogs WHERE id=? AND tenant_id=? AND principal_id=?',
                         (ident, actor.tenant_id, actor.principal_id)).fetchone()
        if not row or row['actor_epoch'] != actor.epoch:
            raise DomainError('emoji_catalog_not_available', next_action='refresh')
        self.binding(db, actor, binding_id=row['binding_id'], epoch=row['binding_epoch'])
        if latest and self.latest_revision(db, actor, row['binding_id'], row['short_name']) != row['revision']:
            raise DomainError('emoji_catalog_stale', next_action='refresh')
        return row

    def latest_revision(self, db, actor, binding_id, name):
        return db.execute('SELECT COALESCE(MAX(revision),0) FROM emoji_catalogs WHERE tenant_id=? AND principal_id=? AND binding_id=? AND short_name=?',
                          (actor.tenant_id, actor.principal_id, binding_id, name)).fetchone()[0]

    def latest(self, db, actor, table, key, name):
        # All identifiers are fixed internal constants, not caller strings.
        assert (table, key) in {('emoji_aliases', 'alias'), ('emoji_rules', 'name')}
        return db.execute(f'SELECT * FROM {table} WHERE tenant_id=? AND principal_id=? AND {key}=? ORDER BY revision DESC LIMIT 1',
                          (actor.tenant_id, actor.principal_id, name)).fetchone()

    def alias(self, db, actor, name):
        row = self.latest(db, actor, 'emoji_aliases', 'alias', name)
        if not row:
            raise DomainError('emoji_alias_missing', next_action='refresh')
        value = json.loads(row['snapshot'])
        self.catalog(db, actor, value['catalog_ref'])
        return value

    def commands(self, db, actor, command, intent):
        kind = command['kind']
        table, maximum = {'emoji_set_register': ('emoji_catalogs', 100),
                          'emoji_alias_select': ('emoji_aliases', 1000),
                          'emoji_rule_put': ('emoji_rules', 1000)}[kind]
        if db.execute(f'SELECT COUNT(*) FROM {table} WHERE tenant_id=? AND principal_id=?', (actor.tenant_id, actor.principal_id)).fetchone()[0] >= maximum:
            raise DomainError('emoji_palette_quota')
        if kind == 'emoji_set_register':
            b = self.binding(db, actor, alias=command['destination'])
            name = set_name(command['url'])
            if self.latest_revision(db, actor, b['id'], name) != command['expected_revision']:
                raise DomainError('emoji_catalog_revision_conflict', next_action='refresh')
            return self.app._new_operation(db, actor, 'emoji_set_register',
                {**intent, '_binding_id': b['id'], '_binding_epoch': b['epoch'], '_short_name': name})
        if kind == 'emoji_alias_select':
            catalog = self.catalog(db, actor, command['catalog_ref'], latest=True)
            if command['catalog_revision'] != catalog['revision']:
                raise DomainError('emoji_catalog_stale', next_action='refresh')
            token = db.execute('SELECT * FROM emoji_choices WHERE token_hash=? AND catalog_id=? AND tenant_id=? AND principal_id=? AND actor_epoch=? AND expires>?',
                (self.store.token_hash(command['selection_token']), catalog['id'], actor.tenant_id, actor.principal_id,
                 actor.epoch, self.store.clock())).fetchone()
            if not token:
                raise DomainError('emoji_choice_invalid', next_action='refresh')
            old = self.latest(db, actor, 'emoji_aliases', 'alias', command['alias'])
            if old is None and db.execute('SELECT count(DISTINCT alias) FROM emoji_aliases WHERE tenant_id=? AND principal_id=?', (actor.tenant_id, actor.principal_id)).fetchone()[0] >= 100:
                raise DomainError('emoji_palette_quota')
            if (old['revision'] if old else 0) != command['expected_revision']:
                raise DomainError('emoji_alias_revision_conflict', next_action='refresh')
            entries = json.loads(catalog['snapshot'])['entries']
            if not all(1 <= n <= len(entries) for n in command['cells']):
                raise DomainError('emoji_cell_invalid')
            # No sort/dedup: an explicit repeated cell is an intentional repeated part.
            parts = [{k: entries[n-1][k] for k in ('document_id', 'alt', 'preview_sha256')}
                     for n in command['cells']]
            value = {'alias': command['alias'], 'revision': command['expected_revision']+1,
                     'catalog_ref': catalog['id'], 'catalog_revision': catalog['revision'],
                     'parts': parts, 'cells': command['cells'], 'fallback': command['fallback']}
            db.execute('INSERT INTO emoji_aliases VALUES(?,?,?,?,?)',
                (actor.tenant_id, actor.principal_id, value['alias'], value['revision'], canonical(value)))
            result = {'emoji_alias': value}
        elif kind == 'emoji_rule_put':
            self.alias(db, actor, command['alias'])
            old = self.latest(db, actor, 'emoji_rules', 'name', command['name'])
            if old is None and db.execute('SELECT count(DISTINCT name) FROM emoji_rules WHERE tenant_id=? AND principal_id=?', (actor.tenant_id, actor.principal_id)).fetchone()[0] >= 100:
                raise DomainError('emoji_palette_quota')
            if (old['revision'] if old else 0) != command['expected_revision']:
                raise DomainError('emoji_rule_revision_conflict', next_action='refresh')
            value = {k: command[k] for k in ('name', 'match', 'alias', 'enabled')}
            value.update(revision=command['expected_revision']+1, context=command.get('context', {}))
            # Duplicate active exact selectors are ambiguous even before a post exists.
            for other in self.rules(db, actor):
                if (other['name'] != value['name'] and other['match'] == value['match'] and
                        other.get('context', {}) == value['context'] and value['enabled']):
                    raise DomainError('emoji_rule_ambiguous')
            db.execute('INSERT INTO emoji_rules VALUES(?,?,?,?,?)',
                (actor.tenant_id, actor.principal_id, value['name'], value['revision'], canonical(value)))
            result = {'emoji_rule': value}
        else:
            raise DomainError('emoji_command_invalid')
        return self.app._new_operation(db, actor, 'destinations', intent, complete=True, result=result)

    def rules(self, db, actor, *, enabled_only=True):
        rows = db.execute('SELECT r.* FROM emoji_rules r WHERE tenant_id=? AND principal_id=? AND revision=(SELECT MAX(revision) FROM emoji_rules r2 WHERE r2.tenant_id=r.tenant_id AND r2.principal_id=r.principal_id AND r2.name=r.name)',
                          (actor.tenant_id, actor.principal_id))
        values = [json.loads(r['snapshot']) for r in rows]
        return [v for v in values if v['enabled'] or not enabled_only]

    def compile(self, db, actor, content, binding, target):
        self.frozen_access(db, actor, content)
        return compile_content(content, lambda name: self.alias(db, actor, name),
            self.rules(db, actor) if binding['provider'] == 'telegram' else (), provider=binding['provider'],
            fallback=target.get('emoji_fallback') == 'approved_text', context=target.get('emoji_context'))

    def _image(self, db, actor, ident, image):
        used = db.execute('SELECT COALESCE(SUM(length(bytes)),0) FROM assets WHERE tenant_id=?', (actor.tenant_id,)).fetchone()[0]
        quota = db.execute('SELECT storage_limit FROM tenants WHERE id=?', (actor.tenant_id,)).fetchone()[0]
        if used+len(image.data) > quota:
            raise DomainError('storage_quota_exceeded')
        ref, sha = new_id('asset'), hashlib.sha256(image.data).hexdigest()
        db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',
            (ref, actor.tenant_id, actor.principal_id, sha, 'image/png', image.width, image.height, image.data,
             hashlib.sha256(image.original).hexdigest(), self.store.clock()))
        db.execute('INSERT INTO emoji_asset_origins VALUES(?,?)', (ref, ident))
        return ref, sha

    def _save(self, db, actor, b, op, payload):
        args = json.loads(op['request']); command = args['command']; name = args['_short_name']
        if self.latest_revision(db, actor, b['id'], name) != command['expected_revision']:
            raise DomainError('emoji_catalog_revision_conflict', next_action='refresh')
        if (payload.get('short_name', '').lower() != name.lower() or not payload.get('is_emoji')
                or not 1 <= len(payload.get('entries', [])) <= 200):
            raise DomainError('emoji_set_metadata_invalid')
        if db.execute('SELECT count(*) FROM emoji_catalogs WHERE tenant_id=? AND principal_id=?', (actor.tenant_id, actor.principal_id)).fetchone()[0] >= 100:
            raise DomainError('emoji_palette_quota')
        if sum(len(e['preview']) for e in payload['entries']) > 16*1024*1024:
            raise DomainError('emoji_preview_total_limit')
        ident, revision = new_id('emoji'), command['expected_revision']+1
        db.execute('INSERT INTO emoji_catalogs VALUES(?,?,?,?,?,?,?,?,?,?)',
            (ident, actor.tenant_id, actor.principal_id, b['id'], b['epoch'], actor.epoch,
             name, revision, '{}', self.store.clock()))
        entries, images, seen = [], [], set()
        for n, entry in enumerate(payload['entries'], 1):
            document_id(entry['document_id']); valid_alt(entry['alt'])
            if entry['document_id'] in seen:
                raise DomainError('emoji_set_duplicate_id')
            seen.add(entry['document_id'])
            image = verify_image(entry['preview'], entry['preview_mime'])
            if image.width > 1024 or image.height > 1024:
                raise DomainError('emoji_preview_dimensions')
            ref, sha = self._image(db, actor, ident, image)
            entries.append({'cell': n, 'document_id': entry['document_id'], 'alt': entry['alt'],
                'preview_ref': ref, 'preview_sha256': sha, 'preview_kind': 'static_thumbnail',
                'free': bool(entry['free'])})
            images.append(image)
        sheets = []
        for offset in range(0, len(images), 50):
            batch = images[offset:offset+50]
            sheet = Image.new('RGB', (600, math.ceil(len(batch)/5)*120), 'white')
            draw = ImageDraw.Draw(sheet)
            for n, image in enumerate(batch):
                thumb = Image.open(io.BytesIO(image.data)); thumb.thumbnail((84, 84))
                x, y = (n % 5)*120, (n//5)*120
                sheet.paste(thumb, (x+(120-thumb.width)//2, y+6))
                draw.text((x+8, y+98), str(offset+n+1), fill='black')
            stream = io.BytesIO(); sheet.save(stream, format='PNG')
            ref, sha = self._image(db, actor, ident, verify_image(stream.getvalue(), 'image/png'))
            sheets.append({'first_cell': offset+1, 'preview_ref': ref, 'preview_sha256': sha})
        snapshot = {'catalog_ref': ident, 'revision': revision, 'short_name': name,
            'observed_at': timestamp(self.store.clock()), 'entries': entries, 'sheets': sheets,
            'preview_kind': 'static_thumbnail'}
        db.execute('UPDATE emoji_catalogs SET snapshot=? WHERE id=?', (canonical(snapshot), ident))
        return self.page(db, actor, ident, 0, 50)

    def page(self, db, actor, ident, offset=0, limit=50):
        row = self.catalog(db, actor, ident, latest=True)
        snapshot = json.loads(row['snapshot'])
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM emoji_choices WHERE expires<=?', (self.store.clock(),))
        if db.execute('SELECT count(*) FROM emoji_choices WHERE tenant_id=? AND principal_id=?', (actor.tenant_id, actor.principal_id)).fetchone()[0] >= 2000:
            raise DomainError('emoji_preview_rate_limit')
        db.execute('INSERT INTO emoji_choices VALUES(?,?,?,?,?,?)',
            (self.store.token_hash(token), ident, actor.tenant_id, actor.principal_id, actor.epoch, self.store.clock()+900))
        page = {k: v for k, v in snapshot.items() if k not in {'entries', 'sheets'}}
        page.update(entries=snapshot['entries'][offset:offset+limit], selection_token=token,
                    sheets=[s for s in snapshot['sheets'] if offset//50 <= (s['first_cell']-1)//50 <= (offset+limit-1)//50],
                    total=len(snapshot['entries']))
        result = {'emoji_catalog': page}
        if offset+limit < page['total']:
            result['next_cursor'] = self.store.cursor(db, actor, 'emoji_catalog', ident, offset+limit)
        return result

    def read(self, actor, args):
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            query = args['query']; kind = query['kind']
            if kind == 'emoji_catalog':
                ident = query['catalog_ref']
                offset = self.store.cursor_position(db, actor, args['cursor'], 'emoji_catalog', ident) if args.get('cursor') else 0
                result = self.page(db, actor, ident, offset, args.get('limit', 50))
            elif kind == 'emoji_palette':
                # Small bounded list, no cross-owner palettes; latest version only.
                rows = db.execute('SELECT alias FROM emoji_aliases WHERE tenant_id=? AND principal_id=? GROUP BY alias ORDER BY alias LIMIT 101',
                                  (actor.tenant_id, actor.principal_id)).fetchall()
                if len(rows) > 100 or args.get('cursor'):
                    raise DomainError('emoji_palette_limit')
                result = {'emoji_aliases': [self.alias(db, actor, r['alias']) for r in rows],
                          'emoji_rules': self.rules(db, actor, enabled_only=False)}
            else:
                raise DomainError('emoji_query_invalid')
            op = self.app._new_operation(db, actor, 'read', args, complete=True, result=result)
        return self.store.receipt(actor, op)

    def frozen_access(self, db, actor, content):
        for snapshot in content.get('emoji_snapshot', []):
            self.catalog(db, actor, snapshot['catalog_ref'])

    def receipt_access(self, db, actor, operation):
        for attempt in db.execute('SELECT plan FROM attempts WHERE operation_id=?', (operation['id'],)):
            self.frozen_access(db, actor, json.loads(json.loads(attempt['plan'])['content_json']))
        request, result = json.loads(operation['request']), json.loads(operation['result'])
        if operation['action'] == 'emoji_set_register':
            self.binding(db, actor, binding_id=request['_binding_id'], epoch=request['_binding_epoch'])
        if 'emoji_catalog' in result:
            self.catalog(db, actor, result['emoji_catalog']['catalog_ref'], latest=True)
        for alias in ([result['emoji_alias']] if 'emoji_alias' in result else result.get('emoji_aliases', [])):
            self.catalog(db, actor, alias['catalog_ref'])
        for rule in ([result['emoji_rule']] if 'emoji_rule' in result else result.get('emoji_rules', [])):
            self.alias(db, actor, rule['alias'])

    async def process(self, worker, op, actor):
        if op['action'] != 'emoji_set_register':
            return False
        args = json.loads(op['request'])
        with self.store.connection() as db:
            b = dict(self.binding(db, actor, binding_id=args['_binding_id'], epoch=args['_binding_epoch']))
        adapter = worker.adapter('telegram', b['connection_id'])
        if not hasattr(adapter, 'emoji_set'):
            raise DomainError('emoji_catalog_provider_not_configured', next_action='contact_owner')
        async with worker.lane(b['connection_id']):
            async with asyncio.timeout(60):
                payload = await adapter.emoji_set(args['_short_name'], b['native_id'])
        with self.store.tx() as db:
            self.store.fence(db, op['id'], worker.id, op['fence'])
            self.store.current(db, actor)
            self.binding(db, actor, binding_id=b['id'], epoch=b['epoch'])
            if self.store.clock() > op['deadline']:
                raise DomainError('command_expired')
            result = self._save(db, actor, b, op, payload)
            db.execute("UPDATE operations SET state='verified',complete=1,work_state='done',result=? WHERE id=?", (canonical(result), op['id']))
            self.store.event(db, op['id'], 'finished', 'completed', 'Actual provider metadata and static previews saved; no set subscription or message write')
        return True
