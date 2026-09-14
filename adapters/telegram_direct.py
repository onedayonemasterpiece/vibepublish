"""Generic Telegram direct-link routing for the owner's authenticated account.

The core ledger keeps the caller's stable route selector. This adapter resolves
that selector to the provider's numeric peer before an effect, derives the
actual forum topic (or ordinary chat root) from the referenced message, and
runs the existing Telegram adapter with the numeric peer. Recovery uses the
numeric peer already present in the durable adapter checkpoint; it never needs
to trust a mutable public username after an effect may have happened.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from adapters.native import identity, same_existing
from adapters.port import Capability, Observation, Prepared, ReadPage, ReadRequest
from social_operations.domain import DomainError, OutcomeUnknown, canonical

from .telegram import _topic_root, peer_key
from .telegram_resilient import ResilientTelegramAdapter, _diagnostic

_NUMERIC = re.compile(r"-?[1-9][0-9]*")
_HANDLE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")
_CACHE_MISS = {"ValueError", "KeyError", "TypeError"}


class DirectTargetTelegramAdapter(ResilientTelegramAdapter):
    """Resolve owner-selected Telegram links without a pre-bound chat allowlist."""

    async def _entity(self, target: str):
        if _NUMERIC.fullmatch(target or ""):
            if target not in self.bound_targets:
                self.bound_targets = (*self.bound_targets, target)
            return await super()._entity(target)
        if not _HANDLE.fullmatch(target or ""):
            raise DomainError("telegram_target_selector_invalid")

        await self._ensure_connected("direct_target_resolution")
        cached = self._entity_cache.get(target.lower())
        if cached is not None:
            return cached

        unresolved: BaseException | None = None
        try:
            entity = await self.client.get_entity(target)
        except Exception as exc:
            if type(exc).__name__ not in _CACHE_MISS:
                raise _diagnostic(
                    "telegram_transport_unhealthy", exc, "direct_target_resolution"
                ) from None
            unresolved = exc
        else:
            return self._remember_handle(target, entity)

        iterator_factory = getattr(self.client, "iter_dialogs", None)
        try:
            if callable(iterator_factory):
                iterator = iterator_factory()
                if hasattr(iterator, "__aiter__"):
                    async for dialog in iterator:
                        entity = getattr(dialog, "entity", dialog)
                        if (getattr(entity, "username", "") or "").lower() == target.lower():
                            return self._remember_handle(target, entity)
            getter = getattr(self.client, "get_dialogs", None)
            if callable(getter):
                for dialog in await getter(limit=None):
                    entity = getattr(dialog, "entity", dialog)
                    if (getattr(entity, "username", "") or "").lower() == target.lower():
                        return self._remember_handle(target, entity)
        except DomainError:
            raise
        except Exception as exc:
            raise _diagnostic(
                "telegram_transport_unhealthy", exc, "direct_target_hydration"
            ) from None

        try:
            entity = await self.client.get_entity(target)
        except Exception as exc:
            unresolved = exc
        else:
            return self._remember_handle(target, entity)
        if unresolved is not None and type(unresolved).__name__ not in _CACHE_MISS:
            raise _diagnostic(
                "telegram_transport_unhealthy", unresolved, "direct_target_resolution"
            ) from None
        raise DomainError(
            "telegram_peer_not_resolved",
            "Telegram link target is not visible to the authenticated account",
            "refresh",
        )

    def _remember_handle(self, target: str, entity: Any):
        username = (getattr(entity, "username", "") or "").lower()
        if username != target.lower():
            raise DomainError("telegram_peer_mismatch")
        numeric = peer_key(entity)
        if not (getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False)
                or type(entity).__name__.startswith(("Channel", "Chat"))):
            raise DomainError("telegram_direct_messages_needs_review", next_action="contact_owner")
        self._entity_cache[target.lower()] = entity
        self._entity_cache[numeric] = entity
        if numeric not in self.bound_targets:
            self.bound_targets = (*self.bound_targets, numeric)
        return entity

    async def _resolve_link(self, selector: str, link_item: str | None):
        entity = await self._entity(selector)
        numeric = peer_key(entity)
        if not link_item:
            return numeric, None
        if not isinstance(link_item, str) or not link_item.isdigit() or int(link_item) <= 0:
            raise DomainError("telegram_thread_reference_required")

        message = await self.client.get_messages(entity, ids=int(link_item))
        if (message is None or str(getattr(message, "id", "")) != link_item
                or peer_key(getattr(message, "peer_id", None)) != numeric):
            raise DomainError("telegram_target_link_not_found", next_action="refresh")

        if not (getattr(entity, "megagroup", False) and getattr(entity, "forum", False)):
            return numeric, None

        topic = _topic_root(message)
        if topic:
            await self._topic(entity, topic)
            return numeric, topic

        try:
            await self._topic(entity, link_item)
        except DomainError as exc:
            if exc.code != "telegram_topic_not_found":
                raise
            return numeric, None
        return numeric, link_item

    @staticmethod
    def _retarget_item(item, target: str):
        if item is None or item.native_target == target:
            return item
        value = replace(item, native_target=target, fingerprint="")
        return replace(value, fingerprint=identity(value))

    def _retarget_request(self, request, target: str, topic_root_id: str | None):
        return replace(
            request,
            native_target=target,
            existing=self._retarget_item(request.existing, target),
            topic_root_id=topic_root_id,
        )

    def _external_observation(self, observation: Observation, selector: str) -> Observation:
        return replace(
            observation,
            items=tuple(self._retarget_item(item, selector) for item in observation.items),
        )

    async def inspect(self, request) -> Capability:
        try:
            target, topic = await self._resolve_link(request.native_target, request.topic_root_id)
            canonical_request = self._retarget_request(request, target, topic)
            return await ResilientTelegramAdapter.inspect(self, canonical_request)
        except DomainError as exc:
            status = (
                "temporarily_unavailable"
                if exc.code in {"telegram_transport_unhealthy", "telegram_rpc_failed"}
                else "unsupported"
            )
            return Capability(status, exc.code, evidence="direct_target_preflight")

    async def prepare(self, request, hooks):
        target, topic = await self._resolve_link(request.native_target, request.topic_root_id)
        canonical_request = self._retarget_request(request, target, topic)
        capability = await ResilientTelegramAdapter.inspect(self, canonical_request)
        if capability.status != "supported":
            raise DomainError(capability.reason, next_action="contact_owner")

        state = {}
        if canonical_request.existing:
            current = await self._exact(
                await self._entity(canonical_request.native_target), canonical_request.existing
            )
            if current is None:
                raise DomainError("remote_item_missing", next_action="refresh")
            same_existing(canonical_request.existing, current)
        if canonical_request.source:
            await hooks.emit_progress(
                "resolving_source", "started", "Resolving the exact native source"
            )
            _, state["source"] = await self._source(canonical_request)

        wrapper = {
            "direct_target": target,
            "direct_topic_root_id": topic,
            "base": state,
        }
        return Prepared(request, capability, canonical(wrapper))

    async def execute(self, prepared: Prepared, hooks) -> Observation:
        try:
            state = json.loads(prepared.state_json)
            if set(state) != {"direct_target", "direct_topic_root_id", "base"}:
                raise ValueError()
            target = state["direct_target"]
            topic = state["direct_topic_root_id"]
            if not _NUMERIC.fullmatch(target or "") or not isinstance(state["base"], dict):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise DomainError("telegram_direct_target_state_invalid") from None
        canonical_request = self._retarget_request(prepared.request, target, topic)
        base = Prepared(canonical_request, prepared.capability, canonical(state["base"]))
        observation = await ResilientTelegramAdapter.execute(self, base, hooks)
        return self._external_observation(observation, prepared.request.native_target)

    @staticmethod
    def _checkpoint_target(checkpoint: str):
        try:
            payload = json.loads(checkpoint)
            payload = payload.get("adapter", payload)
            target = payload["target"]
            topic = payload.get("topic_root_id")
            if not _NUMERIC.fullmatch(target or ""):
                raise ValueError()
            if topic is not None and (not isinstance(topic, str) or not topic.isdigit()):
                raise ValueError()
            return target, topic
        except (ValueError, TypeError, KeyError, AttributeError):
            raise OutcomeUnknown("reconcile_checkpoint_invalid") from None

    async def reconcile(self, request, checkpoint, hooks) -> Observation:
        target, topic = self._checkpoint_target(checkpoint)
        canonical_request = self._retarget_request(request, target, topic)
        observation = await ResilientTelegramAdapter.reconcile(
            self, canonical_request, checkpoint, hooks
        )
        return self._external_observation(observation, request.native_target)

    async def read(self, request: ReadRequest, hooks) -> ReadPage:
        target = topic = None
        kind = request.kind
        if request.cursor:
            try:
                cursor = json.loads(request.cursor)
                candidate = cursor.get("target")
                if _NUMERIC.fullmatch(candidate or ""):
                    target = candidate
                    if cursor.get("kind") == "replies":
                        topic = cursor.get("topic_root_id")
                    elif cursor.get("kind") == "history":
                        topic = None
            except (ValueError, TypeError, AttributeError):
                pass
        if target is None:
            target, topic = await self._resolve_link(
                request.native_target, request.topic_root_id if request.kind == "thread" else None
            )
        if request.kind == "thread" and topic is None:
            kind = "feed"
        canonical_request = replace(
            request, native_target=target, kind=kind, topic_root_id=topic
        )
        page = await ResilientTelegramAdapter.read(self, canonical_request, hooks)
        return ReadPage(
            tuple(self._retarget_item(item, request.native_target) for item in page.items),
            page.cursor,
            page.downloads,
        )
