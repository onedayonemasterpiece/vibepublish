"""Explicit offline provider simulator with its own durable 'remote' SQLite store.

Never enabled by default. It deliberately does NOT deduplicate execute calls:
regression tests can detect a duplicate caused by an incorrect core recovery.
"""
from __future__ import annotations
import asyncio
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from .port import Capability, Observation, Prepared, ReadPage, RemoteItem
from social_operations.domain import DomainError, OutcomeUnknown, canonical, digest, new_id, parse_time, timestamp


class FakeProvider:
    def __init__(self, path, provider, *, clock=time.time, delay=0, crash=None):
        self.path = str(path)
        self.provider = provider
        self.clock = clock
        self.delay = delay
        self.crash = crash
        self.gate = None
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,provider TEXT,target TEXT,attempt TEXT,snapshot TEXT);
            CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,provider TEXT,kind TEXT,attempt TEXT);
            CREATE TABLE IF NOT EXISTS sources(provider TEXT,channel TEXT,item TEXT,public INTEGER,protected INTEGER,snapshot TEXT,PRIMARY KEY(provider,channel,item));
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=5000')
        try:
            yield db
        finally:
            db.close()

    def record(self, kind, attempt=''):
        with self.db() as db:
            db.execute('INSERT INTO calls(provider,kind,attempt) VALUES(?,?,?)', (self.provider, kind, attempt))

    def count(self, kind='execute'):
        with self.db() as db:
            return db.execute('SELECT count(*) FROM calls WHERE provider=? AND kind=?', (self.provider, kind)).fetchone()[0]

    def seed(self, target, text='Other editor', *, scheduled_at=None, attempt='', origin=None):
        ident = new_id('remote')
        item = self.item(ident, 'scheduled' if scheduled_at else 'published', text, scheduled_at, (), origin, target)
        with self.db() as db:
            db.execute('INSERT INTO items VALUES(?,?,?,?,?)', (ident, self.provider, target, attempt, canonical(asdict(item))))
        return item

    def item(self, ident, namespace, text, scheduled, hashes, origin, target):
        return RemoteItem(ident, namespace, text, digest([text, scheduled, hashes, origin]), timestamp(self.clock()),
                          scheduled, tuple(hashes), origin, metrics=(('views', 7, 'views'),),
                          media_check='source_bytes' if hashes else 'not_applicable', native_target=target)

    def add_source(self, source, *, public=True, protected=False, text='Original'):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?)', (source.provider, source.channel, source.item,
                        int(public), int(protected), canonical({'text': text, 'origin': source.canonical_url})))

    def source(self, request):
        s = request.source
        with self.db() as db:
            row = db.execute('SELECT * FROM sources WHERE provider=? AND channel=? AND item=?', (s.provider, s.channel, s.item)).fetchone()
        if not row or (not row['public'] and not request.source_authorized):
            raise DomainError('source_access_denied', next_action='contact_owner')
        if row['protected']:
            raise DomainError('source_protected', next_action='contact_owner')
        return json.loads(row['snapshot'])

    def existing(self, request):
        with self.db() as db:
            row = db.execute('SELECT * FROM items WHERE id=? AND provider=? AND target=?', (request.existing.native_id, self.provider, request.native_target)).fetchone()
        if not row:
            raise DomainError('remote_missing', next_action='review_outcome')
        item = RemoteItem(**json.loads(row['snapshot']))
        if item.fingerprint != request.existing.fingerprint or item.namespace != request.existing.namespace:
            raise DomainError('external_change', next_action='refresh')
        return item

    async def inspect(self, request):
        if request.account_type != 'fake':
            return Capability('needs_auth', 'Fake transport requires explicit fake account type')
        if request.surface not in ('post', 'album'):
            return Capability('unsupported', 'Fixture surface is not implemented')
        if self.provider == 'vk' and request.action == 'forward' and request.scheduled_at:
            return Capability('unsupported', 'VK scheduled native repost is unproved; no fallback')
        return Capability('supported', 'Explicit offline simulator, NOT live provider evidence')

    async def prepare(self, request, hooks):
        self.record('prepare', request.attempt_id)
        capability = await self.inspect(request)
        if capability.status != 'supported':
            raise DomainError('native_schedule_unsupported' if request.scheduled_at else 'capability_unsupported', capability.reason, 'contact_owner')
        if request.scheduled_at and parse_time(request.scheduled_at) < self.clock()+60:
            raise DomainError('native_lead_time')
        content = json.loads(request.content_json)
        if 'text' not in content or content.get('format', 'plain') != 'plain':
            raise DomainError('fixture_content_not_supported', next_action='contact_owner')
        state = {}
        if request.source:
            await hooks.emit_progress('resolving_source', 'started', 'Inspecting the exact source only')
            state['source'] = self.source(request)
            await hooks.emit_progress('checking_forward_rights', 'completed', 'Source access and protection checked')
        if request.existing:
            self.existing(request)
        await hooks.emit_progress('validating', 'completed', 'Offline provider preflight complete')
        return Prepared(request, capability, canonical(state))

    async def execute(self, prepared, hooks):
        r = prepared.request
        self.record('execute', r.attempt_id)
        await hooks.emit_progress('waiting_connection', 'started', 'Offline provider command started')
        if self.gate:
            await self.gate.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        for i, _asset in enumerate(r.assets):
            await hooks.emit_progress('uploading', 'completed', f'Prepared media {i+1}/{len(r.assets)}')
        old = self.existing(r) if r.existing else None
        source = self.source(r) if r.source else None
        if source != json.loads(prepared.state_json).get('source'):
            raise DomainError('external_source_change', next_action='refresh')
        if self.crash == 'before_marker':
            os._exit(81)
        await hooks.before_effect(r.attempt_id, r.plan_digest)
        if self.crash == 'after_marker':
            os._exit(82)
        if r.action in ('cancel', 'reschedule') and (not old or old.namespace != 'scheduled'):
            raise OutcomeUnknown('cancel_race')
        if r.action == 'delete' and (not old or old.namespace != 'published'):
            raise OutcomeUnknown('delete_race')
        ident = old.native_id if old else new_id('remote')
        namespace = ('cancelled' if r.action == 'cancel' else 'deleted' if r.action == 'delete' else
                     'scheduled' if r.scheduled_at else 'published')
        content = json.loads(r.content_json)
        if 'text' not in content:
            raise OutcomeUnknown('fixture_content_not_supported')
        text = source['text'] if source else content['text']
        item = self.item(ident, namespace, text, r.scheduled_at, [a.sha256 for a in r.assets], source['origin'] if source else None, r.native_target)
        with self.db() as db:
            db.execute('INSERT INTO calls(provider,kind,attempt) VALUES(?,?,?)', (self.provider, 'effect', r.attempt_id))
            db.execute('INSERT INTO items VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET attempt=excluded.attempt,snapshot=excluded.snapshot',
                       (ident, self.provider, r.native_target, r.attempt_id, canonical(asdict(item))))
        if self.crash == 'after_effect':
            os._exit(83)
        await hooks.emit_progress('reading_back', 'started', 'Reading exact offline remote identity')
        return await self.reconcile(r, '{}', hooks)

    async def reconcile(self, request, checkpoint, hooks):
        self.record('reconcile', request.attempt_id)
        with self.db() as db:
            rows = db.execute('SELECT snapshot FROM items WHERE provider=? AND target=? AND attempt=?',
                              (self.provider, request.native_target, request.attempt_id)).fetchall()
        if len(rows) != 1:
            raise OutcomeUnknown('exact_identity_not_observed')
        item = RemoteItem(**json.loads(rows[0]['snapshot']))
        observed = 'provider_scheduled' if item.namespace == 'scheduled' else item.namespace
        return Observation(observed, (item,), forward_origin_matched=bool(item.origin))

    async def read(self, request, hooks):
        self.record('read')
        with self.db() as db:
            rows = db.execute('SELECT snapshot FROM items WHERE provider=? AND target=? ORDER BY rowid',
                              (self.provider, request.native_target)).fetchall()
        items = [RemoteItem(**json.loads(row[0])) for row in rows]
        if request.kind == 'item':
            items = [i for i in items if i.native_id == request.native_item and i.namespace == request.namespace]
        else:
            items = [i for i in items if i.namespace == ('scheduled' if request.kind == 'scheduled' else 'published')]
        if request.text:
            items = [i for i in items if request.text.casefold() in i.text.casefold()]
        offset = int(request.cursor or 0)
        end = offset + request.limit
        return ReadPage(tuple(items[offset:end]), str(end) if end < len(items) else None)
