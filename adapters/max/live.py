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
