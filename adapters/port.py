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

from social_operations.domain import DomainError, NativeSource, OutcomeUnknown


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
class DownloadedMedia:
    """Observed downloaded bytes, never a native attachment ID or source digest."""
    slot: int
    sha256: str
    mime: str
    size: int
    kind: str = "download_sha256"

    def __post_init__(self):
        import re
        if (self.kind != 'download_sha256' or type(self.slot) is not int or not 0 <= self.slot < 10
                or not isinstance(self.sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', self.sha256)
                or self.mime not in {'image/png', 'image/jpeg', 'image/webp', 'video/mp4'}
                or type(self.size) is not int or not 0 < self.size <= 20*1024*1024):
            raise DomainError('download_media_evidence_invalid')


def downloaded_media(values):
    try:
        result = tuple(value if isinstance(value, DownloadedMedia) else DownloadedMedia(**value) for value in values)
    except (TypeError, ValueError):
        raise DomainError('download_media_evidence_invalid') from None
    if len(result) > 10 or tuple(value.slot for value in result) != tuple(range(len(result))):
        raise DomainError('download_media_order_invalid')
    return result


@dataclass(frozen=True, slots=True)
class MediaDownload:
    """Ephemeral provider bytes returned only to the trusted read worker."""
    item_native_id: str
    slot: int
    provider_ref: str
    media_kind: str
    mime: str
    data: bytes = field(repr=False)

    def __post_init__(self):
        if (not isinstance(self.item_native_id, str) or not self.item_native_id
                or type(self.slot) is not int or not 0 <= self.slot < 10
                or self.media_kind not in {'photo', 'document'}
                or not isinstance(self.provider_ref, str)
                or not self.provider_ref.startswith(self.media_kind + ':')
                or self.mime not in {'image/png', 'image/jpeg', 'image/webp'}
                or not isinstance(self.data, bytes) or not 0 < len(self.data) <= 20*1024*1024):
            raise DomainError('download_media_payload_invalid')


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
    native_target: str = field(default="", repr=False)
    # Ordered opaque provider object identities, NOT hashes of transcoded bytes.
    provider_media: tuple[str, ...] = field(default=(), repr=False)
    # One logical album can have multiple physical native messages.
    member_ids: tuple[str, ...] = field(default=(), repr=False)
    entities_json: str = "[]"  # Additive immutable semantic entity observation (MAX compatible).


    observed_media: tuple[DownloadedMedia, ...] = ()
    reply_to_native_id: str | None = field(default=None, repr=False)
    own_reactions: tuple[str, ...] = ()
    own_reactions_observed: bool = False

    def __post_init__(self):
        object.__setattr__(self, 'observed_media', downloaded_media(self.observed_media))
        for name in ('media_hashes', 'provider_media', 'member_ids', 'own_reactions'):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, 'metrics', tuple(tuple(metric) for metric in self.metrics))
        if type(self.own_reactions_observed) is not bool or (self.own_reactions and not self.own_reactions_observed):
            raise DomainError('reaction_evidence_invalid')
        if len(self.own_reactions)>100 or any(not isinstance(value,str) or not 1<=len(value)<=100 for value in self.own_reactions) or len(set(self.own_reactions))!=len(self.own_reactions):
            raise DomainError('reaction_evidence_invalid')


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
    subject: RemoteItem | None = None
    reaction: str | None = None
    reaction_mode: str | None = None
    topic_root_id: str | None = field(default=None, repr=False)


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
class NoEffectProof:
    """Trusted adapter proof of unreachable input, never provider absence alone.

    Cancels the original intent without an item or a claim of successful publish.
    Binding is to the immutable original adapter checkpoint retained by core.
    """
    checkpoint_sha256: str
    reason: str
    evidence_json: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class NativeReplacement:
    """Observed provider-native replacement within the same logical lifecycle."""
    previous_native_id: str
    native_id: str
    previous_fingerprint: str
    evidence: str

    def matches(self, old, new, *, action, provider, account_type):
        return (provider == 'max' and account_type == 'max_web' and action == 'reschedule'
            and old.namespace == new.namespace == 'scheduled'
            and self.previous_native_id == old.native_id and self.native_id == new.native_id
            and self.previous_fingerprint == old.fingerprint
            and old.native_target == new.native_target and old.text == new.text
            and self.evidence in {'trusted_ui_native_queue_replacement', 'stable_native_correlation'})


@dataclass(frozen=True, slots=True)
class Observation:
    observed: str
    items: tuple[RemoteItem, ...] = ()
    missing_checks: tuple[str, ...] = ()
    forward_origin_matched: bool = False
    no_effect: NoEffectProof | None = None
    replacement: NativeReplacement | None = None


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
    topic_root_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ReadPage:
    items: tuple[RemoteItem, ...]
    cursor: str | None = None
    downloads: tuple[MediaDownload, ...] = ()


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


class FinalizingProviderAdapter(ProviderAdapter, Protocol):
    """Optional additive hook, discovered via getattr; old providers need no change.

    Called only after the original outcome and complete observation are durable.
    checkpoint contains remote, original_checkpoint and core_recovery identity.
    Release only matching attempt/plan quarantine; already released is success.
    Never execute a social mutation here. Failures remain durably pending and are
    retried by a later worker, including after a crash following successful release.
    """
    async def finalize(self, request: ProviderRequest, checkpoint: str, hooks: Hooks) -> None: ...


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
