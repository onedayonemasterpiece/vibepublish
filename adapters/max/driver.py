"""Deterministic UI state machine, currently bound ONLY to synthetic fixtures.

This is a driver, NOT a replacement ProviderAdapter contract. The archived core
port is required for production wiring. No MAX API, timer, auth or ledger here.
The synthetic data attributes are NOT asserted to exist in live MAX.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from playwright.async_api import expect

from .profile import MaxBlocked, ProfileLane


CAPABILITIES = {
    'text': 'fixture_only', 'images': 'fixture_only',
    'native_schedule': 'fixture_only', 'queue_read': 'fixture_only',
    'edit': 'fixture_only', 'reschedule': 'fixture_only',
    'cancel': 'effect_only_outcome_unknown', 'delete': 'effect_only_outcome_unknown',
    'video': 'unsupported', 'rich_content': 'unsupported',
    'stories': 'unsupported', 'forward': 'unsupported',
    'discovery': 'unsupported', 'analytics': 'unsupported',
}


def fingerprint(item):
    fields = {key: item[key] for key in ('id', 'target', 'namespace', 'text', 'media', 'scheduled_at')}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class FixtureDriver:
    """Explicitly offline driver; refuses every origin except its fixture origin.

    Hooks are passed through from core (awaitable emit_progress/checkpoint/
    before_effect), not redefined. Tests provide ordinary callback objects.
    All methods are bounded, account/target scoped and require exclusive lane
    ownership. Trusted integration must freeze inputs and supply allowed targets.
    """
    def __init__(self, page, lane: ProfileLane, *, origin: str, account: str,
                 allowed_targets: frozenset[str], timeout=8, min_lead=90):
        parsed = urlsplit(origin)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password:
            raise MaxBlocked('fixture_origin_required')
        self.page, self.lane = page, lane
        self.origin, self.account = origin.rstrip('/'), account
        self.targets = frozenset(allowed_targets)
        self.timeout, self.min_lead = timeout, min_lead
        self.page.set_default_timeout(timeout * 1000)
        self._busy = False

    def _enter(self, target):
        self.lane.owned()
        if self._busy:
            raise MaxBlocked('profile_busy')
        if target not in self.targets:
            raise MaxBlocked('target_denied')
        parsed = urlsplit(self.page.url)
        if f'{parsed.scheme}://{parsed.netloc}' != self.origin:
            raise MaxBlocked('fixture_origin_required')
        self._busy = True

    async def _scope(self, target, *, write=False):
        parsed = urlsplit(self.page.url)
        if f'{parsed.scheme}://{parsed.netloc}' != self.origin:
            raise MaxBlocked('fixture_origin_required')
        shell = self.page.get_by_test_id('session')
        if await shell.get_attribute('data-account') != self.account:
            raise MaxBlocked('needs_auth_or_wrong_account')
        channel = self.page.get_by_test_id('channel')
        if await channel.get_attribute('data-target') != target:
            raise MaxBlocked('wrong_target')
        if await channel.get_attribute('data-readable') != 'true':
            raise MaxBlocked('read_denied')
        if write and await channel.get_attribute('data-writable') != 'true':
            raise MaxBlocked('write_denied')
        return channel

    async def _open(self, target):
        if await self.page.get_by_test_id('session').get_attribute('data-account') != self.account:
            raise MaxBlocked('needs_auth_or_wrong_account')
        # Exact identity, never a display-name selector or account-wide search.
        await self.page.get_by_label('Exact destination').fill(target)
        await self.page.get_by_role('button', name='Open exact destination', exact=True).click()
        await expect(self.page.get_by_test_id('channel')).to_have_attribute('data-target', target)
        return await self._scope(target)

    def _time(self, value):
        if value is None:
            return
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None or parsed.timestamp() - time.time() < self.min_lead:
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            raise MaxBlocked('native_time_too_close_or_invalid') from None

    async def _items(self, target, kind):
        if kind not in {'feed', 'scheduled'}:
            raise MaxBlocked('unsupported_read')
        channel = await self._scope(target)
        await channel.get_by_role('button', name=kind, exact=True).click()
        found = {}
        # Bounded virtualized pages. Refuse silently incomplete baseline/readback.
        for _ in range(32):
            channel = await self._scope(target)
            await expect(channel.get_by_test_id('items')).to_have_attribute('data-ready', 'true')
            rows = channel.get_by_test_id('item')
            for row in await rows.all():
                item = json.loads(await row.get_attribute('data-item'))
                if item['target'] != target or item['namespace'] != kind:
                    raise MaxBlocked('read_scope_mismatch')
                if item['id'] in found and found[item['id']] != item:
                    raise MaxBlocked('queue_changed_during_read')
                found[item['id']] = item
            more = channel.get_by_role('button', name='Next page', exact=True)
            if await more.is_disabled():
                return list(found.values())
            await more.click()
        raise MaxBlocked('read_bound_exceeded')

    async def read(self, target, kind='scheduled'):
        self._enter(target)
        try:
            async with asyncio.timeout(self.timeout):
                await self._open(target)
                result = await self._items(target, kind)
                await self._scope(target)
                return self._observations(result)
        except MaxBlocked:
            raise
        except Exception:
            raise MaxBlocked('read_unavailable') from None
        finally:
            self._busy = False

    @staticmethod
    def _observations(items):
        now = datetime.now(timezone.utc).isoformat()
        return [dict(x, observed_at=now, fingerprint=fingerprint(x),
                     media_check='provider_identity_order' if x['media'] else 'not_applicable') for x in items]

    async def mutate(self, *, target, text, media, scheduled_at, action,
                     attempt_id, plan_digest, hooks, existing=None):
        """Perform ONE fixture mutation; never retry a click.

        media is a tuple of Playwright in-memory FilePayload dictionaries supplied
        by trusted wiring. No filesystem asset paths or remote downloads accepted.
        existing is a prior exact UI observation with a fingerprint for CAS.
        """
        self._enter(target)
        armed = False
        try:
            async with asyncio.timeout(self.timeout):
                self.lane.assert_clear()
                if action not in {'publish', 'edit', 'reschedule', 'cancel', 'delete'}:
                    raise MaxBlocked('unsupported_action')
                if not isinstance(text, str) or (action in {'publish', 'edit'} and not text and not media):
                    raise MaxBlocked('invalid_content')
                if len(media) > 10 or any(set(x) != {'name', 'mimeType', 'buffer'} or
                                        x['mimeType'] not in {'image/png', 'image/jpeg'} or
                                        not isinstance(x['buffer'], bytes) for x in media):
                    raise MaxBlocked('unsupported_media')
                if len({x['name'] for x in media}) != len(media):
                    raise MaxBlocked('ambiguous_upload_names')
                self._time(scheduled_at)
                if action == 'reschedule' and scheduled_at is None:
                    raise MaxBlocked('native_time_required')
                await hooks.emit_progress('waiting_connection', 'running', '{}')
                await self._open(target)
                await self._scope(target, write=True)
                kind = 'scheduled' if scheduled_at else 'feed'
                if action != 'publish':
                    if not existing or existing['target'] != target:
                        raise MaxBlocked('exact_existing_required')
                    kind = existing['namespace']
                    if action in {'reschedule', 'cancel'} and kind != 'scheduled':
                        raise MaxBlocked('not_scheduled')
                    if action == 'reschedule' and (text != existing['text'] or media or existing['media']):
                        raise MaxBlocked('reschedule_content_preservation_unverified')
                    if action == 'delete' and kind != 'feed':
                        raise MaxBlocked('not_published')
                    if action == 'edit' and existing['scheduled_at'] != scheduled_at:
                        raise MaxBlocked('edit_cannot_reschedule')
                baseline = await self._items(target, kind)
                if action != 'publish':
                    self._cas(baseline, existing)
                await self._scope(target, write=True)
                channel = self.page.get_by_test_id('channel')
                await channel.get_by_label('Action').select_option(action)
                await channel.get_by_label('Existing item').fill(existing['id'] if existing else '')
                await channel.get_by_role('button', name='Compose', exact=True).click()
                dialog = channel.get_by_role('dialog')
                await dialog.get_by_label('Text', exact=True).fill(text)
                if media:
                    await hooks.emit_progress('uploading', 'running', '{}')
                    await dialog.get_by_label('Images').set_input_files(list(media))
                await expect(dialog.get_by_test_id('uploads')).to_have_attribute('data-ready', 'true')
                uploads = json.loads(await dialog.get_by_test_id('uploads').get_attribute('data-media'))
                if [x['name'] for x in uploads] != [x['name'] for x in media] or len({x['id'] for x in uploads}) != len(media):
                    raise MaxBlocked('upload_order_or_count')
                await dialog.get_by_label('Native time').fill(scheduled_at or '')
                await expect(dialog.get_by_label('Text', exact=True)).to_have_value(text)
                await expect(dialog.get_by_label('Native time')).to_have_value(scheduled_at or '')
                provider_media = [x['id'] for x in uploads]
                # Reconcile uses provider-assigned identity only, not content similarity.
                # Baseline stays in protected core checkpoint; no local second ledger.
                state = dict(target=target, kind=kind, baseline=[x['id'] for x in baseline],
                             text=text, media=provider_media, scheduled_at=scheduled_at,
                             action=action, existing_id=existing['id'] if existing else None)
                await hooks.checkpoint('MAX_PREPARED', json.dumps(state))
                await hooks.emit_progress('submitting', 'running', '{}')
                # A callback may take time, revoke rights, or rerender the page.
                await self._scope(target, write=True)
                self._time(scheduled_at)
                if existing:
                    self._cas(await self._items(target, kind), existing)
                self.lane.arm(attempt_id, plan_digest)
                armed = True
                await hooks.before_effect(attempt_id, plan_digest)
                await self._scope(target, write=True)
                self._time(scheduled_at)
                if existing:
                    self._cas(await self._items(target, kind), existing)
                # Reacquire and verify after callbacks, never a stale element handle.
                dialog = self.page.get_by_test_id('channel').get_by_role('dialog')
                await expect(dialog.get_by_label('Text', exact=True)).to_have_value(text)
                await expect(dialog.get_by_label('Native time')).to_have_value(scheduled_at or '')
                await expect(dialog.get_by_test_id('uploads')).to_have_attribute('data-ready', 'true')
                if json.loads(await dialog.get_by_test_id('uploads').get_attribute('data-media')) != uploads:
                    raise MaxBlocked('composer_changed')
                channel = await self._scope(target, write=True)
                self._time(scheduled_at)
                await expect(channel.get_by_label('Action')).to_have_value(action)
                await expect(channel.get_by_label('Existing item', exact=True)).to_have_value(existing['id'] if existing else '')
                await dialog.get_by_role('button', name='Submit once', exact=True).click()
                await hooks.emit_progress('reading_back', 'running', '{}')
                result = await self._reconcile(state)
                await hooks.checkpoint('MAX_OBSERVED', json.dumps(result))
                self.lane.resolve_observed()
                return result
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            if armed:
                raise MaxBlocked('outcome_unknown') from None
            if isinstance(exc, MaxBlocked):
                raise
            raise MaxBlocked('prepare_unavailable') from None
        finally:
            self._busy = False

    @staticmethod
    def _cas(items, existing):
        exact = [x for x in items if x['id'] == existing['id']]
        if len(exact) != 1 or fingerprint(exact[0]) != existing['fingerprint']:
            raise MaxBlocked('external_change')

    async def reconcile(self, state):
        self._enter(state['target'])
        try:
            async with asyncio.timeout(self.timeout):
                await self._open(state['target'])
                return await self._reconcile(state)
        except MaxBlocked:
            raise
        except Exception:
            raise MaxBlocked('outcome_unknown') from None
        finally:
            self._busy = False

    async def _reconcile(self, state):
        items = await self._items(state['target'], state['kind'])
        if state['action'] in {'cancel', 'delete'}:
            # Absence is NOT deletion proof. Synthetic fixture deliberately has
            # no durable native tombstone: report unknown, never falsely cancel.
            raise MaxBlocked('outcome_unknown')
        candidates = [x for x in items if
                      (x['id'] not in state['baseline'] if state['action'] == 'publish'
                       else x['id'] == state['existing_id']) and
                      x['text'] == state['text'] and x['media'] == state['media'] and
                      x['scheduled_at'] == state['scheduled_at']]
        # Text-only creation cannot be attributed without native request identity:
        # even ONE new identical post could have been sent by another editor.
        if len(candidates) != 1 or (state['action'] == 'publish' and not state['media']):
            raise MaxBlocked('outcome_unknown')
        await self._scope(state['target'])
        return self._observations(candidates)
