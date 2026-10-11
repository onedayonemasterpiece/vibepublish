"""Bounded provider-call metadata for the existing durable progress ledger.

No bodies, URLs, auth headers, credentials or exception messages.
Only explicitly allowlisted, bounded endpoint/response metadata is accepted.
The observer is task-local and must never change a provider outcome.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import math
import ipaddress
import json
import logging
import re
import time

_observer = ContextVar("provider_diagnostic_observer", default=None)
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,79}\Z")
_HOST = re.compile(r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z][A-Za-z0-9-]{0,62}\Z")
_HEADER_SECRET = re.compile(r"token|secret|password|authorization|cookie|bearer|api[-_]?key|access[-_]?key|credential|sessionid", re.I)
_HEADER_PATTERNS = {
    "response_server": re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,39}(?:/[A-Za-z0-9._-]{1,32})?\Z"),
    "response_via": re.compile(r"[12](?:\.[01])? [A-Za-z0-9][A-Za-z0-9._-]{0,100}(?::[0-9]{1,5})?\Z"),
    # Deliberately narrow IDs: no JWT/base64, URLs, query strings or free text.
    "response_request_id": re.compile(r"[A-Fa-f0-9][A-Fa-f0-9-]{7,79}\Z"),
    "response_vk_request_id": re.compile(r"[A-Fa-f0-9][A-Fa-f0-9-]{7,79}\Z"),
    "response_correlation_id": re.compile(r"[A-Fa-f0-9][A-Fa-f0-9-]{7,79}\Z"),
}


_URL_REJECTIONS = frozenset({
    "invalid_type", "invalid_length", "invalid_characters", "malformed_url",
    "scheme_not_https", "credentials_present", "fragment_present", "port_not_allowed",
    "api_host_not_allowed", "api_path_not_allowed", "api_query_present", "host_not_allowed",
})
_PROVIDER_ERROR_TEXT = {
    "access_denied": "Access denied",
    "authorization_failed": "Authorization failed",
    "rate_limited": "Rate limit exceeded",
    "captcha_required": "Captcha required",
    "invalid_parameters": "Invalid or missing parameters",
    "provider_error": "Provider internal error",
    "unclassified": "Provider error; message omitted",
}
_PROVIDER_ERROR_PREFIXES = (
    ("access denied", "access_denied"),
    ("permission to perform this action is denied", "access_denied"),
    ("user authorization failed", "authorization_failed"),
    ("too many requests per second", "rate_limited"),
    ("flood control", "rate_limited"),
    ("captcha needed", "captcha_required"),
    ("one of the parameters specified was missing or invalid", "invalid_parameters"),
    ("internal server error", "provider_error"),
    ("unknown error occurred", "provider_error"),
)


def provider_error_metadata(message):
    """Classify transient API text; persist only fixed templates, never its text.

    A regex scrub cannot prove an arbitrary provider message contains no secret.
    Unknown, non-string or oversized text therefore yields a fixed omission note.
    """
    category = "unclassified"
    if isinstance(message, str) and len(message) <= 2048:
        normalized = message.casefold().lstrip()
        for prefix, known in _PROVIDER_ERROR_PREFIXES:
            if (normalized == prefix or (normalized.startswith(prefix)
                    and normalized[len(prefix):len(prefix)+1] in " .:;,\t\r\n")):
                category = known
                break
    return {"provider_error_class": category, "provider_error_text": _PROVIDER_ERROR_TEXT[category]}


def _upload_metadata(value):
    clean = {}
    host = value.get("upload_host")
    if isinstance(host, str) and _HOST.fullmatch(host) and not _HEADER_SECRET.search(host):
        clean["upload_host"] = host.lower()
    peer = value.get("peer_ip")
    if isinstance(peer, str) and len(peer) <= 45 and "%" not in peer:
        try:
            address = ipaddress.ip_address(peer)
            clean.update(peer_ip=str(address), peer_family="ipv" + str(address.version))
        except ValueError:
            pass
    mime = value.get("upload_mime")
    if mime in ("image/jpeg", "image/png", "image/webp", "video/mp4"):
        clean["upload_mime"] = mime
    sha = value.get("asset_sha256")
    if isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha):
        clean["asset_sha256"] = sha
    framing = value.get("request_framing")
    if framing in ("content_length", "chunked"):
        clean["request_framing"] = framing
    for key, pattern in _HEADER_PATTERNS.items():
        item = value.get(key)
        if isinstance(item, str) and pattern.fullmatch(item) and not _HEADER_SECRET.search(item):
            clean[key] = item
    return clean


def safe_diagnostic(value):
    """Closed metadata vocabulary; reject rather than stringify unknown values."""
    clean = {}
    for key in ("provider", "operation", "phase", "status", "error_type", "error_code", "observed", "media_check"):
        item = value.get(key)
        if isinstance(item, str) and _NAME.fullmatch(item):
            clean[key] = item
    for key, low, high in (("duration_ms", 0, 86400000), ("http_status", 100, 599),
                           ("provider_code", -1000000, 1000000),
                           ("retry_after_s", 0, 86400), ("items_count", 0, 1000),
                           ("dns_ms", 0, 86400000), ("headers_wait_ms", 0, 86400000)):
        item = value.get(key)
        if type(item) in (int, float) and math.isfinite(item) and low <= item <= high:
            clean[key] = round(item, 3)
    for key in ("upload_bytes", "request_body_bytes"):
        item = value.get(key)
        if type(item) is int and 0 <= item <= 64 * 1024 * 1024:
            clean[key] = item
    clean.update(_upload_metadata(value))
    reason = value.get("url_rejection_reason")
    if isinstance(reason, str) and reason in _URL_REJECTIONS:
        clean["url_rejection_reason"] = reason
    category = value.get("provider_error_class")
    if isinstance(category, str) and category in _PROVIDER_ERROR_TEXT:
        clean.update(provider_error_class=category, provider_error_text=_PROVIDER_ERROR_TEXT[category])
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


def budget_diagnostic(record):
    """Fit one complete JSON record beneath Store.event's unchanged 1000-char cap."""
    required = ("operation_id", "publication_id", "attempt_id", "action", "provider",
                "dispatched", "operation", "status", "error_code", "error_type",
                "http_status", "duration_ms")
    # IDs/action are trusted worker context; all provider fields were sanitized.
    # Current fixed IDs and <=80-character names bound this core below 750 chars.
    clean = {key: record[key] for key in required if key in record}
    priority = ("url_rejection_reason", "provider_code", "provider_error_class", "provider_error_text",
                "upload_host", "peer_ip", "peer_family", "upload_bytes", "upload_mime",
                "asset_sha256", "request_framing", "request_body_bytes",
                "dns_ms", "headers_wait_ms", "response_server", "response_via",
                "response_request_id", "response_vk_request_id", "response_correlation_id")
    keys = [key for key in priority if key in record and key not in clean]
    keys += sorted(set(record) - set(required) - set(priority))
    omitted = 0
    for key in keys:
        candidate = {**clean, key: record[key]}
        # Reserve room for an explicit omission count; never cut JSON or strings.
        if len(json.dumps(candidate, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)) <= 950:
            clean[key] = record[key]
        else:
            omitted += 1
    if omitted:
        clean["metadata_omitted"] = omitted
    return clean
