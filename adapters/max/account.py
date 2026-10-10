"""Existing visible MAX account gate with one shared readiness budget."""
from __future__ import annotations

import asyncio
import time


ACCOUNT_PHASES = frozenset({'navigation', 'settings', 'phone'})


class VisibleAccountCheck:
    """Reads only the existing account settings in the runtime's own page.

    Phase is a closed diagnostic enum. The observed or expected account value is
    never stored in diagnostics. No auth state, alternate selector or login flow.
    """
    def __init__(self, page, phone, *, timeout):
        self.page = page
        self._phone = phone
        self.timeout = timeout
        self.phase = None

    async def __call__(self):
        self.phase = 'navigation'
        deadline = time.monotonic() + self.timeout

        def remaining_ms():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Playwright timeout=0 disables its timeout, so never pass zero.
                raise TimeoutError()
            return remaining * 1000

        # Callers may impose an earlier operation/driver deadline. Cancellation
        # propagates unchanged, while phase remains available to the caller.
        async with asyncio.timeout(self.timeout):
            await self.page.goto('https://web.max.ru/', wait_until='domcontentloaded',
                                 timeout=remaining_ms())
            self.phase = 'settings'
            settings = self.page.get_by_role('button', name='Настройки', exact=True)
            await settings.wait_for(state='visible', timeout=remaining_ms())
            await settings.click(timeout=remaining_ms())
            self.phase = 'phone'
            field = self.page.locator('aside .phone')
            await field.wait_for(state='visible', timeout=remaining_ms())
            return await field.inner_text(timeout=remaining_ms()) == self._phone
