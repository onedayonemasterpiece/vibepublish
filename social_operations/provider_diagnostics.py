"""Bounded provider-call metadata for the existing durable progress ledger.

No request/response text, URLs, headers, credentials or exception messages.
The observer is task-local and must never change a provider outcome.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import math
import logging
import re
import time

_observer = ContextVar("provider_diagnostic_observer", default=None)
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,79}\Z")


def safe_diagnostic(value):
    """Closed metadata vocabulary; reject rather than stringify unknown values."""
    clean = {}
    for key in ("provider", "operation", "phase", "status", "error_type", "error_code", "observed", "media_check"):
        item = value.get(key)
        if isinstance(item, str) and _NAME.fullmatch(item):
            clean[key] = item
    for key, low, high in (("duration_ms", 0, 86400000), ("http_status", 100, 599),
                           ("provider_code", -1000000, 1000000),
                           ("retry_after_s", 0, 86400), ("items_count", 0, 1000)):
        item = value.get(key)
        if type(item) in (int, float) and math.isfinite(item) and low <= item <= high:
            clean[key] = round(item, 3)
    return clean


def report(value):
    observer = _observer.get()
    if observer is not None:
        try:
            observer(safe_diagnostic(value))
        except Exception:
            # Observability must never turn a known effect into a second attempt.
            logging.getLogger(__name__).warning("provider diagnostic sink unavailable")


@contextmanager
def diagnostic_scope(observer):
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


@contextmanager
def provider_call(provider, operation):
    details = {}
    base = {"provider": provider, "operation": operation}
    started = time.monotonic()
    report({**base, "status": "started"})
    try:
        yield details
    except BaseException as exc:
        report({**details, **base, "status": "failed",
                "error_type": details.get("error_type", type(exc).__name__),
                "error_code": details.get("error_code", getattr(exc, "code", None)),
                "provider_code": details.get("provider_code", getattr(exc, "code", None)),
                "retry_after_s": details.get("retry_after_s", getattr(exc, "seconds", None)),
                "duration_ms": (time.monotonic() - started) * 1000})
        raise
    else:
        report({**details, **base, "status": "completed",
                "duration_ms": (time.monotonic() - started) * 1000})
