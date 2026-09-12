"""Generic Telegram target hydration for owner-selected direct links.

Core authorization decides whether a target is allowed. This adapter only makes
sure a newly selected numeric Telegram peer can be hydrated from the authenticated
account dialogs even when it was not present when the worker started.
"""
from __future__ import annotations

from .telegram_resilient import ResilientTelegramAdapter


class DirectTargetTelegramAdapter(ResilientTelegramAdapter):
    async def _entity(self, target: str):
        if target not in self.bound_targets:
            self.bound_targets = (*self.bound_targets, target)
        return await super()._entity(target)
