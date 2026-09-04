"""Canonical core/MAX boundary v1. No adapter owns auth, ledger or retry policy.

All objects are immutable snapshots. Secret references are resolved by trusted
wiring, never supplied by a tool caller. prepare/read/reconcile must not publish.
execute must await before_effect immediately before the single mutation. After
that boundary an exception is uncertain unless exact provider evidence resolves
it. Progress/checkpoints must be sanitized; do not include cookies, DOM or tokens.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

from social_operations.domain import NativeSource, OutcomeUnknown


@dataclass(frozen=True, slots=True)
class Asset:
    ref: str
    sha256: str
    mime: str
    size: int
    role: str = "image"
    caption: str = ""
    alt_text: str = ""
    data: bytes = field(default=b"", repr=False)


@dataclass(frozen=True, slots=True)
class RemoteItem:
    native_id: str = field(repr=False)
    namespace: str
    text: str
    fingerprint: str
    observed_at: str
    scheduled_at: str | None = None
    media_hashes: tuple[str, ...] = ()
    origin: str | None = None
    url: str | None = None
    metrics: tuple[tuple[str, float, str], ...] = ()
    # Provider object IDs prove binding, not equality of transcoded bytes.
    media_check: str = "not_applicable"


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    operation_id: str
    attempt_id: str
    plan_digest: str
    connection_id: str = field(repr=False)
    account_type: str
    secret_ref: str = field(repr=False)
    destination_id: str = field(repr=False)
    native_target: str = field(repr=False)
    action: str
    surface: str
    content_json: str
    assets: tuple[Asset, ...]
    scheduled_at: str | None
    deadline: float
    existing: RemoteItem | None = None
    source: NativeSource | None = None
    source_authorized: bool = False
    selection: str = "post"


@dataclass(frozen=True, slots=True)
class Capability:
    status: str
    reason: str
    min_lead_seconds: int = 60
    # "supported" is allowed only for this actual connection/surface evidence.
    evidence: str = "offline_fixture"


@dataclass(frozen=True, slots=True)
class Prepared:
    request: ProviderRequest
    capability: Capability
    state_json: str = "{}"


@dataclass(frozen=True, slots=True)
class Observation:
    observed: str
    items: tuple[RemoteItem, ...] = ()
    missing_checks: tuple[str, ...] = ()
    forward_origin_matched: bool = False


@dataclass(frozen=True, slots=True)
class ReadRequest:
    connection_id: str = field(repr=False)
    native_target: str = field(repr=False)
    kind: str
    limit: int = 25
    cursor: str | None = field(default=None, repr=False)
    native_item: str | None = field(default=None, repr=False)
    namespace: str | None = None
    text: str = ""


@dataclass(frozen=True, slots=True)
class ReadPage:
    items: tuple[RemoteItem, ...]
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class Hooks:
    emit_progress: Callable[[str, str, str], Awaitable[None]]
    checkpoint: Callable[[str, str], Awaitable[None]]
    before_effect: Callable[[str, str], Awaitable[None]]


class ProviderAdapter(Protocol):
    async def inspect(self, request: ProviderRequest) -> Capability: ...
    async def prepare(self, request: ProviderRequest, hooks: Hooks) -> Prepared: ...
    async def execute(self, prepared: Prepared, hooks: Hooks) -> Observation: ...
    async def read(self, request: ReadRequest, hooks: Hooks) -> ReadPage: ...
    async def reconcile(self, request: ProviderRequest, checkpoint: str, hooks: Hooks) -> Observation: ...


class UnavailableAdapter:
    """Default for unwired providers, especially the separately implemented MAX."""
    async def inspect(self, request: ProviderRequest) -> Capability:
        return Capability("needs_auth", "Provider connection is not configured", evidence="not_verified")

    async def prepare(self, request: ProviderRequest, hooks: Hooks) -> Prepared:
        from social_operations.domain import DomainError
        raise DomainError("needs_auth", "Provider connection is not configured", "reauthorize")

    async def execute(self, prepared: Prepared, hooks: Hooks) -> Observation:
        raise OutcomeUnknown("adapter_not_configured")

    async def read(self, request: ReadRequest, hooks: Hooks) -> ReadPage:
        from social_operations.domain import DomainError
        raise DomainError("needs_auth", "Provider connection is not configured", "reauthorize")

    async def reconcile(self, request: ProviderRequest, checkpoint: str, hooks: Hooks) -> Observation:
        raise OutcomeUnknown("provider_observation_unavailable")
