"""Runtime hardening for the native Telegram adapter.

The core Telegram adapter owns Telegram semantics. This wrapper only owns
connection liveness, reconnect, active-binding entity hydration and sanitized
runtime diagnostics. It never retries a mutation after an RPC has started.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import secrets
from typing import Any

from adapters.port import Capability
from social_operations.domain import DomainError

from .telegram import TelegramAdapter, peer_key

_CONNECTION_EXCEPTIONS = {
    "ConnectionError", "ConnectionResetError", "ConnectionAbortedError",
    "BrokenPipeError", "OSError", "TimeoutError", "EOFError",
}
_AUTH_EXCEPTIONS = {"AuthKeyUnregisteredError", "SessionRevokedError"}
_COOLDOWN_EXCEPTIONS = {"FloodWaitError", "SlowModeWaitError"}


def _diagnostic(code: str, exc: BaseException, stage: str, *,
                next_action: str = "contact_owner") -> DomainError:
    """Create a safe diagnostic without serializing provider/session payloads."""
    exception_type = type(exc).__name__
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", exception_type):
        exception_type = "Exception"
    if not re.fullmatch(r"[a-z][a-z0-9_:.-]{0,79}", stage):
        stage = "telegram_runtime"
    correlation_id = "tgdiag_" + secrets.token_hex(8)
    message = (
        f"{code.replace('_', ' ')}; exception_type={exception_type}; "
        f"stage={stage}; correlation_id={correlation_id}"
    )
    return DomainError(code, message, next_action)


class ResilientTelegramAdapter(TelegramAdapter):
    """Add transport liveness and generic bound-peer hydration to Telegram."""

    def __init__(self, client, *, connection_id: str, account_type="mtproto_user",
                 tl=None, clock=None, bound_targets=()):
        kwargs = dict(connection_id=connection_id, account_type=account_type, tl=tl)
        if clock is not None:
            kwargs["clock"] = clock
        super().__init__(client, **kwargs)
        self.bound_targets = tuple(dict.fromkeys(
            target for target in bound_targets
            if isinstance(target, str) and re.fullmatch(r"-?[1-9][0-9]*", target)
        ))
        self._entity_cache: dict[str, Any] = {}
        self._transport_lock = asyncio.Lock()

    async def _connected(self) -> bool:
        probe = getattr(self.client, "is_connected", None)
        if not callable(probe):
            # Scripted/unit clients predate the production liveness API.
            return True
        try:
            value = probe()
            if inspect.isawaitable(value):
                value = await value
            return bool(value)
        except Exception as exc:
            raise _diagnostic("telegram_transport_unhealthy", exc, "transport_health") from None

    async def _ensure_connected(self, stage: str) -> None:
        if await self._connected():
            return
        async with self._transport_lock:
            if await self._connected():
                return
            connect = getattr(self.client, "connect", None)
            if not callable(connect):
                raise DomainError(
                    "telegram_transport_unhealthy",
                    "telegram transport unhealthy; exception_type=MissingConnect; "
                    f"stage={stage}; correlation_id=tgdiag_{secrets.token_hex(8)}",
                    "contact_owner",
                )
            try:
                await connect()
                authorized = getattr(self.client, "is_user_authorized", None)
                if not callable(authorized) or not await authorized():
                    raise DomainError("telegram_auth_required", next_action="reauthorize")
            except DomainError:
                raise
            except Exception as exc:
                raise _diagnostic(
                    "telegram_transport_unhealthy", exc, "transport_reconnect"
                ) from None
            self._entity_cache.clear()

    async def _hydrate_bound_targets(self) -> None:
        """Hydrate only native peers already granted by active core bindings."""
        wanted = set(self.bound_targets) - set(self._entity_cache)
        if not wanted:
            return

        async def remember(dialog):
            entity = getattr(dialog, "entity", dialog)
            try:
                key = peer_key(entity)
            except DomainError:
                return
            if key in wanted:
                self._entity_cache[key] = entity

        iterator_factory = getattr(self.client, "iter_dialogs", None)
        try:
            if callable(iterator_factory):
                iterator = iterator_factory()
                if hasattr(iterator, "__aiter__"):
                    async for dialog in iterator:
                        await remember(dialog)
                        if wanted <= set(self._entity_cache):
                            break
                    return
            getter = getattr(self.client, "get_dialogs", None)
            if callable(getter):
                dialogs = await getter(limit=None)
                for dialog in dialogs:
                    await remember(dialog)
                    if wanted <= set(self._entity_cache):
                        break
        except DomainError:
            raise
        except Exception as exc:
            raise _diagnostic(
                "telegram_transport_unhealthy", exc, "entity_hydration"
            ) from None

    async def _entity(self, target: str):
        if not re.fullmatch(r"-?[1-9][0-9]*", target):
            raise DomainError("telegram_numeric_binding_required", next_action="contact_owner")
        await self._ensure_connected("entity_resolution")
        cached = self._entity_cache.get(target)
        if cached is not None:
            return cached

        unresolved = None
        try:
            entity = await self.client.get_entity(int(target))
            if peer_key(entity) != target:
                raise DomainError("telegram_peer_mismatch")
            self._entity_cache[target] = entity
            return entity
        except DomainError:
            raise
        except Exception as exc:
            if type(exc).__name__ not in {"ValueError", "KeyError", "TypeError"}:
                raise _diagnostic(
                    "telegram_transport_unhealthy", exc, "entity_resolution"
                ) from None
            unresolved = exc

        await self._hydrate_bound_targets()
        cached = self._entity_cache.get(target)
        if cached is not None:
            return cached

        # Dialog hydration also refreshes Telethon's entity cache. One read-only
        # resolution retry is safe; never retry a provider mutation here.
        try:
            entity = await self.client.get_entity(int(target))
        except Exception as exc:
            unresolved = exc
        else:
            if peer_key(entity) != target:
                raise DomainError("telegram_peer_mismatch")
            self._entity_cache[target] = entity
            return entity

        if unresolved is not None and type(unresolved).__name__ not in {
            "ValueError", "KeyError", "TypeError"
        }:
            raise _diagnostic(
                "telegram_transport_unhealthy", unresolved, "entity_resolution"
            ) from None
        raise DomainError(
            "telegram_peer_not_resolved",
            "Bound Telegram peer could not be hydrated from the active account dialogs",
            "refresh",
        )

    async def _call(self, kind: str, **values):
        # Health/reconnect happens before each RPC. The RPC itself is still
        # exactly-once: a transport exception after submission is never retried.
        await self._ensure_connected("telegram_rpc:" + kind)
        try:
            return await self.client(self.tl.request(kind, **values))
        except DomainError:
            raise
        except Exception as exc:
            name = type(exc).__name__
            code = (
                "telegram_cooldown" if name in _COOLDOWN_EXCEPTIONS else
                "telegram_auth_required" if name in _AUTH_EXCEPTIONS else
                "telegram_transport_unhealthy" if name in _CONNECTION_EXCEPTIONS else
                "telegram_rpc_failed"
            )
            action = "reauthorize" if code == "telegram_auth_required" else "contact_owner"
            raise _diagnostic(code, exc, "telegram_rpc:" + kind, next_action=action) from None

    async def inspect(self, request) -> Capability:
        try:
            await self._ensure_connected("inspect")
            await self._entity(request.native_target)
        except DomainError as exc:
            status = (
                "temporarily_unavailable"
                if exc.code in {"telegram_transport_unhealthy", "telegram_rpc_failed"}
                else "unsupported"
            )
            return Capability(status, exc.code, evidence="runtime_health_failed")
        try:
            return await super().inspect(request)
        except DomainError as exc:
            return Capability("unsupported", exc.code, evidence="runtime_preflight_failed")
        except Exception as exc:
            error = _diagnostic("telegram_transport_unhealthy", exc, "inspect")
            return Capability("temporarily_unavailable", error.code,
                              evidence="runtime_health_failed")

    async def prepare(self, request, hooks):
        # Preserve diagnostics before base inspect converts a capability failure
        # to an ordinary unsupported reason.
        await self._ensure_connected("prepare")
        entity = await self._entity(request.native_target)
        if request.topic_root_id:
            await self._topic(entity, request.topic_root_id)
        try:
            return await super().prepare(request, hooks)
        except DomainError:
            raise
        except Exception as exc:
            raise _diagnostic("telegram_transport_unhealthy", exc, "prepare") from None

    async def execute(self, prepared, hooks):
        await self._ensure_connected("execute")
        try:
            return await super().execute(prepared, hooks)
        except DomainError:
            raise
        except Exception as exc:
            raise _diagnostic("telegram_transport_unhealthy", exc, "execute") from None

    async def reconcile(self, request, checkpoint, hooks):
        await self._ensure_connected("reconcile")
        try:
            return await super().reconcile(request, checkpoint, hooks)
        except DomainError:
            raise
        except Exception as exc:
            raise _diagnostic("telegram_transport_unhealthy", exc, "reconcile") from None

    async def read(self, request, hooks):
        await self._ensure_connected("read")
        await self._entity(request.native_target)
        try:
            return await super().read(request, hooks)
        except DomainError:
            raise
        except Exception as exc:
            raise _diagnostic("telegram_transport_unhealthy", exc, "read") from None

    async def emoji_set(self, short_name: str, target: str):
        await self._ensure_connected("emoji_set")
        try:
            return await super().emoji_set(short_name, target)
        except DomainError:
            raise
        except Exception as exc:
            raise _diagnostic("telegram_transport_unhealthy", exc, "emoji_set") from None
