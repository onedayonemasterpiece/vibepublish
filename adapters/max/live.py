"""Observed MAX Web read/navigation recipe, not a publishing-capability claim.

This code runs unchanged against MAX and sanitized loopback replay. It deliberately
has no submit path until native causal receipts and stable queue refs are proved.
No API, storage-state reads, account-wide message search or synthetic selectors.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from playwright.async_api import expect

from .profile import MaxBlocked, ProfileLane

RECIPE = 'max-web-observed-20260905-v1'
MAIN = 'main[aria-labelledby="main-header-title"]'
COMPOSER = '[contenteditable][role="textbox"][data-lexical-editor="true"]'
TITLE = '.name > .text'
QUEUE_TITLE = 'Запланированные посты'


@dataclass(frozen=True)
class Target:
    native_id: str
    alias: str
    policy: str

    def __post_init__(self):
        if not re.fullmatch(r'-[1-9][0-9]{0,19}', self.native_id):
            raise MaxBlocked('invalid_native_target')
        if not self.alias or self.policy not in {'test_group', 'scheduled_only'}:
            raise MaxBlocked('invalid_target_binding')


@dataclass(frozen=True)
class VisibleSnapshot:
    """A bounded screen projection, NEVER an authoritative full provider queue.

    No fabricated native IDs, timestamps, media hashes or pagination cursors.
    Provider item identity is a separate gate, not a text/time fingerprint.
    """
    target: str
    namespace: str
    observed_at: str
    rows: tuple[dict, ...]
    complete: bool = False
    missing_checks: tuple[str, ...] = ('native_item_identity', 'pagination_completeness')


class RealMaxDriver:
    def __init__(self, page, lane: ProfileLane, *, targets: tuple[Target, ...],
                 account_check, origin='https://web.max.ru', timeout=10):
        parsed = urlsplit(origin)
        if not (origin == 'https://web.max.ru' or
                parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
                and parsed.port and parsed.path == '' and not parsed.query
                and not parsed.fragment and not parsed.username and not parsed.password):
            raise MaxBlocked('max_origin_denied')
        if len({t.native_id for t in targets}) != len(targets):
            raise MaxBlocked('duplicate_target_binding')
        self.page, self.lane, self.account_check = page, lane, account_check
        self.targets = {t.native_id: t for t in targets}
        self.origin, self.timeout, self._busy = origin, timeout, False

    def _enter(self, target):
        self.lane.owned()
        if self._busy:
            raise MaxBlocked('profile_busy')
        if target not in self.targets:
            raise MaxBlocked('target_denied')
        self._busy = True

    def _route(self, target):
        if self.page.url != self.origin + '/' + target:
            raise MaxBlocked('wrong_target_or_origin')

    async def _account(self):
        # Trusted explicit binding, not a boolean supplied by a model/request.
        # Live factory reads the existing account's settings in its OWN page.
        if await self.account_check() is not True:
            raise MaxBlocked('needs_auth_or_wrong_account')

    async def _scope(self, target, namespace='feed'):
        self._route(target)
        main = self.page.locator(MAIN)
        await expect(main).to_have_count(1, timeout=self.timeout*1000)
        if namespace == 'feed':
            # Fail closed on a rename pending read-only binding reconfirmation.
            # Never replace the ID with another chat carrying the previous name.
            header = main.get_by_role('button', name='Открыть профиль ' + self.targets[target].alias, exact=True)
            await expect(header).to_be_visible(timeout=self.timeout*1000)
            if await main.get_by_text(QUEUE_TITLE, exact=True).count():
                raise MaxBlocked('wrong_namespace')
        elif namespace == 'scheduled':
            await expect(main.get_by_text(QUEUE_TITLE, exact=True)).to_be_visible(timeout=self.timeout*1000)
        else:
            raise MaxBlocked('unsupported_namespace')
        self._route(target)
        return main

    async def open(self, target):
        self._enter(target)
        try:
            async with asyncio.timeout(self.timeout):
                await self._account()
                # Reordering/pinning/unread/search cannot affect this binding.
                # This route was obtained from actual owner-authorized UI.
                await self.page.goto(self.origin + '/' + target, wait_until='domcontentloaded')
                await self._scope(target)
                await self._account()
                await self._scope(target)
        except MaxBlocked:
            raise
        except Exception:
            raise MaxBlocked('unfamiliar_or_unavailable_ui') from None
        finally:
            self._busy = False

    async def visible(self, target, namespace='feed'):
        """Explicit incomplete read; unsuitable for deletion/absence assertions."""
        await self.open(target)
        self._enter(target)
        try:
            async with asyncio.timeout(self.timeout):
                main = await self._scope(target)
                if namespace == 'scheduled':
                    control = main.get_by_role('button', name='Открыть отложенные сообщения', exact=True)
                    if await control.count() != 1:
                        raise MaxBlocked('queue_entry_not_observed')
                    await control.click()
                    main = await self._scope(target, namespace)
                elif namespace != 'feed':
                    raise MaxBlocked('unsupported_namespace')
                # Read only this bound main pane, not sidebar snippets, app state,
                # cookies, local storage or unrelated search matches.
                rows = await main.locator('.messageWrapper').evaluate_all('''els => els.map(e => ({
                    text: e.querySelector('.bubbleContent > .text')?.textContent ?? '',
                    media: [...e.querySelectorAll('.media img')].map(i => i.getAttribute('src')),
                    displayed_time: e.querySelector('.meta .text')?.textContent ?? null,
                    outgoing: e.classList.contains('messageWrapper--isOut')
                }))''')
                if len(rows) > 100:
                    raise MaxBlocked('visible_read_bound_exceeded')
                await self._account()
                await self._scope(target, namespace)
                return VisibleSnapshot(target, namespace, datetime.now(timezone.utc).isoformat(), tuple(rows))
        except MaxBlocked:
            raise
        except Exception:
            raise MaxBlocked('unfamiliar_or_unavailable_ui') from None
        finally:
            self._busy = False

    async def discovery_titles(self):
        """Only visible CHAT titles. Never issue account-wide message search.

        Names remain untrusted discovery hints. This method neither clicks a row
        nor creates an allowlist binding, even if a title has exactly one match.
        """
        self.lane.owned()
        if self._busy:
            raise MaxBlocked('profile_busy')
        self._busy = True
        try:
            async with asyncio.timeout(self.timeout):
                await self._account()
                parsed = urlsplit(self.page.url)
                if f'{parsed.scheme}://{parsed.netloc}' != self.origin:
                    raise MaxBlocked('max_origin_denied')
                # h3 limits normal list; search has a separate observed title
                # wrapper. A highlighted name in a message excerpt is not one.
                names = await self.page.locator('h3 ' + TITLE + ', .searchResultsList > button[aria-haspopup="dialog"] .title ' + TITLE).all_text_contents()
                if len(names) > 100:
                    raise MaxBlocked('discovery_bound_exceeded')
                await self._account()
                return tuple(" ".join(name.split()) for name in names)
        except MaxBlocked:
            raise
        except Exception:
            raise MaxBlocked('discovery_unavailable') from None
        finally:
            self._busy = False

    async def mutation_preflight(self, target, action, *, media=(), scheduled_at=None):
        """No mutation capability until the causal receipt recipe is verified.

        A matching outgoing row and copied native URL establish a readable item,
        not its causal association with this attempt. Never discover a missing
        receipt implementation AFTER clicking Send. There is intentionally no
        runtime boolean/string that enables this unfinished path.
        """
        self.lane.assert_clear()
        raise MaxBlocked('causal_receipt_recipe_unverified')

    async def mutate(self, *, target, text, media, scheduled_at, action,
                     attempt_id, plan_digest, hooks, existing=None):
        await self.mutation_preflight(target, action, media=media, scheduled_at=scheduled_at)

    async def _copy_native_reference(self, row, target):
        """Observed message-menu recipe; never infer an ID from row position."""
        import uuid
        await self._scope(target)
        await expect(row).to_have_count(1)
        # A failed copy must not accidentally reuse a previous clipboard receipt.
        sentinel = 'vibepublish-copy-' + uuid.uuid4().hex
        await self.page.evaluate('(value)=>navigator.clipboard.writeText(value)', sentinel)
        await row.click(button='right')
        menu = self.page.get_by_role('menu')
        await expect(menu).to_have_count(1)
        await menu.get_by_role('menuitem', name='Скопировать ссылку на сообщение', exact=True).click()
        value = await self.page.evaluate('navigator.clipboard.readText()')
        match = re.fullmatch(r'https://max\.ru/c/(-[1-9][0-9]*)/([A-Za-z0-9_-]+)', value)
        if not match or match[1] != target:
            raise MaxBlocked('native_reference_scope_mismatch')
        await self._scope(target)
        return value, match[2]

    async def reconcile(self, state):
        """Observation only: no execute, checkpoint write, or fuse release.

        Accept an exact reference supplied by the trusted recovery caller, not
        text discovery as an attribution certificate. Core must independently
        validate the historical chain and persist its resolution before release.
        Missing historical receipt/evidence is NOT repaired by this method.
        """
        import json
        import os
        try:
            target, text = state['target'], state['text']
            reference, marker = state['recovery_reference'], state['task_marker']
            attempt, plan = state['attempt_id'], state['plan_digest']
            if (state['kind'] != 'feed' or state['action'] != 'publish'
                    or state['media'] or state['scheduled_at'] is not None
                    or not isinstance(text, str) or not text or len(text) > 4000
                    or not isinstance(marker, str) or len(marker) < 16
                    or text.count(marker) != 1 or not attempt or not plan):
                raise ValueError()
            match = re.fullmatch(r'https://max\.ru/c/(-[1-9][0-9]*)/([A-Za-z0-9_-]+)', reference)
            if not match or match[1] != target:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise MaxBlocked('recovery_evidence_required') from None
        self._enter(target)
        try:
            # Match, but NEVER clear, the original durable quarantine.
            def check_fuse():
                try:
                    fd = os.open(self.lane.marker, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(fd, 'rb') as stream:
                        raw = stream.read(4097)
                    if len(raw) > 4096:
                        raise ValueError()
                    saved = json.loads(raw)
                except (OSError, ValueError):
                    raise MaxBlocked('recovery_quarantine_required') from None
                if saved != {'attempt_id': attempt, 'plan_digest': plan}:
                    raise MaxBlocked('recovery_attempt_mismatch')
            check_fuse()
            observations = []
            async with asyncio.timeout(self.timeout):
                for _ in range(2):
                    await self._account()
                    await self.page.goto(self.origin + '/' + target, wait_until='domcontentloaded')
                    main = await self._scope(target)
                    # Search ONLY the intended pane, not account-wide snippets.
                    candidates = main.locator('.messageWrapper').filter(
                        has=self.page.locator('.bubbleContent > .text').filter(has_text=marker))
                    await expect(candidates).to_have_count(1, timeout=self.timeout*1000)
                    row = candidates
                    if 'messageWrapper--isOut' not in (await row.get_attribute('class') or '').split():
                        raise MaxBlocked('recovery_not_outgoing')
                    content = row.locator('.bubbleContent > .text')
                    await expect(content).to_have_count(1)
                    if await content.text_content() != text:
                        raise MaxBlocked('recovery_content_changed')
                    if await row.locator('.media, img, video, audio, .bubbleContent a').count():
                        raise MaxBlocked('recovery_media_not_verified')
                    value, native_id = await self._copy_native_reference(row, target)
                    if value != reference:
                        raise MaxBlocked('recovery_native_reference_mismatch')
                    await self._account()
                    await self._scope(target)
                    # Re-acquire after the awaited account callback/re-render.
                    await expect(candidates).to_have_count(1)
                    if await candidates.locator('.bubbleContent > .text').text_content() != text:
                        raise MaxBlocked('recovery_content_changed')
                    if 'messageWrapper--isOut' not in (await candidates.get_attribute('class') or '').split():
                        raise MaxBlocked('recovery_not_outgoing')
                    if await candidates.locator('.media, img, video, audio, .bubbleContent a').count():
                        raise MaxBlocked('recovery_media_not_verified')
                    second, _ = await self._copy_native_reference(candidates, target)
                    if second != reference:
                        raise MaxBlocked('recovery_native_reference_mismatch')
                    check_fuse()
                    observations.append(dict(id=native_id, url=reference, target=target,
                        namespace='feed', text=text, media=[], scheduled_at=None,
                        observed_at=datetime.now(timezone.utc).isoformat()))
                return dict(item=observations[-1], observations=observations,
                    attempt_id=attempt, plan_digest=plan, observation_only=True,
                    attribution='requires_core_historical_evidence_validation',
                    candidate_scope='loaded_target_rows_only', history_complete=False,
                    quarantine_released=False)
        except MaxBlocked:
            raise
        except TimeoutError:
            raise MaxBlocked('recovery_observation_deadline') from None
        except Exception:
            raise MaxBlocked('recovery_observation_unavailable') from None
        finally:
            self._busy = False
