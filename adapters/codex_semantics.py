"""Sanitized Codex app-server quota and error semantics.

This module deliberately keeps raw provider messages out of durable/public state.
Only documented typed fields are classified. Unknown shapes fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from social_operations.domain import DomainError, timestamp


REACHED_TYPES = {
    'rate_limit_reached': ('codex_rate_limited', 'retry_later'),
    'workspace_owner_credits_depleted': ('codex_credits_exhausted', 'contact_owner'),
    'workspace_member_credits_depleted': ('codex_credits_exhausted', 'contact_owner'),
    'workspace_owner_usage_limit_reached': ('codex_usage_limit_reached', 'retry_later'),
    'workspace_member_usage_limit_reached': ('codex_usage_limit_reached', 'retry_later'),
}


def _token(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return re.sub(r'[^a-z0-9]', '', value.lower())[:80] or None


def _codex_info(value: Any) -> tuple[str | None, int | None]:
    """Extract only the documented error discriminator and optional HTTP status."""
    if isinstance(value, str):
        return _token(value), None
    if not isinstance(value, dict):
        return None, None
    kind = value.get('type', value.get('kind', value.get('code')))
    status = value.get('httpStatusCode')
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    return _token(kind), status


class AppServerRPCError(RuntimeError):
    """A received JSON-RPC error response, stripped of provider free text."""

    def __init__(self, method: str, error: Any):
        payload = error if isinstance(error, dict) else {}
        rpc_code = payload.get('code')
        self.rpc_code = rpc_code if type(rpc_code) is int else None
        data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
        candidates = (
            payload.get('codexErrorInfo'), data.get('codexErrorInfo'),
            data.get('error', {}).get('codexErrorInfo') if isinstance(data.get('error'), dict) else None,
        )
        kind = status = None
        for candidate in candidates:
            kind, status = _codex_info(candidate)
            if kind or status:
                break
        self.method = method
        self.codex_error_info = kind
        self.http_status_code = status
        super().__init__('sanitized app-server request error')


@dataclass(frozen=True, slots=True)
class ClassifiedFailure:
    code: str
    next_action: str
    retry_safe: bool
    retry_at: str | None = None

    def domain_error(self) -> DomainError:
        messages = {
            'codex_rate_limited': 'Codex rate limit is currently reached',
            'codex_usage_limit_reached': 'Codex usage limit is currently reached',
            'codex_credits_exhausted': 'Codex workspace credits are exhausted',
            'codex_spend_limit_reached': 'Codex spend control currently blocks generation',
            'codex_quota_exhausted': 'Codex generation quota is currently unavailable',
            'codex_capacity_unavailable': 'Codex generation capacity is temporarily unavailable',
            'codex_rate_limit_preflight_unavailable': 'Codex quota status could not be read safely',
            'codex_thread_start_not_observed': 'Codex thread creation was not observed after bounded recovery',
            'codex_turn_start_not_observed': 'Codex generation turn was not observed after bounded recovery',
        }
        return DomainError(self.code, messages.get(self.code, 'Codex request failed safely'),
                           self.next_action, retry_safe=self.retry_safe, retry_at=self.retry_at)


def _reset_at(snapshot: dict[str, Any]) -> str | None:
    values = []
    for key in ('primary', 'secondary'):
        window = snapshot.get(key)
        if isinstance(window, dict):
            value = window.get('resetsAt')
            if type(value) is int and value > 0:
                values.append(value)
    limit = snapshot.get('individualLimit')
    if isinstance(limit, dict):
        value = limit.get('resetsAt')
        if type(value) is int and value > 0:
            values.append(value)
    return timestamp(min(values)) if values else None


def classify_rate_limits(payload: Any) -> ClassifiedFailure | None:
    """Classify only typed account/rateLimits/read fields; never infer from prose."""
    if not isinstance(payload, dict):
        raise DomainError('codex_rate_limit_status_invalid', next_action='contact_owner')
    snapshot = payload.get('rateLimits')
    by_id = payload.get('rateLimitsByLimitId')
    if isinstance(by_id, dict) and isinstance(by_id.get('codex'), dict):
        snapshot = by_id['codex']
    if not isinstance(snapshot, dict):
        raise DomainError('codex_rate_limit_status_invalid', next_action='contact_owner')
    reset_at = _reset_at(snapshot)
    reached = snapshot.get('rateLimitReachedType')
    if reached in REACHED_TYPES:
        code, action = REACHED_TYPES[reached]
        return ClassifiedFailure(code, action, True, reset_at)
    if snapshot.get('spendControlReached') is True:
        return ClassifiedFailure('codex_spend_limit_reached', 'contact_owner', True, reset_at)
    ordinary = payload.get('ordinaryUsageAllowed')
    if ordinary is False:
        return ClassifiedFailure('codex_quota_exhausted', 'retry_later', True, reset_at)
    if ordinary not in (None, True):
        raise DomainError('codex_rate_limit_status_invalid', next_action='contact_owner')
    return None


def classify_rpc_error(error: AppServerRPCError) -> ClassifiedFailure | None:
    """A JSON-RPC error response is definitive; only documented typed causes are retryable."""
    kind = error.codex_error_info
    if kind == 'usagelimitexceeded':
        return ClassifiedFailure('codex_usage_limit_reached', 'retry_later', True)
    # These are transient before acceptance only when app-server itself returned
    # the structured request error. Transport disconnects never enter this path.
    if kind in {'responseconnectionfailed', 'httpconnectionfailed'} and error.http_status_code in {429, 503}:
        return ClassifiedFailure('codex_capacity_unavailable', 'retry_later', True)
    return None


def classify_turn_failure(turn: Any) -> ClassifiedFailure | None:
    """Classify a terminal saved turn only when typed evidence proves the cause."""
    if not isinstance(turn, dict) or turn.get('status') != 'failed':
        return None
    error = turn.get('error')
    if not isinstance(error, dict):
        return None
    kind, status = _codex_info(error.get('codexErrorInfo'))
    if kind == 'usagelimitexceeded':
        return ClassifiedFailure('codex_usage_limit_reached', 'retry_later', True)
    if kind == 'httpconnectionfailed' and status in {429, 503}:
        return ClassifiedFailure('codex_capacity_unavailable', 'retry_later', True)
    return None
