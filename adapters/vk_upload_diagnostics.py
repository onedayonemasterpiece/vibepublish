"""Read-only upload metadata. Never inspect bodies, URL queries or auth headers."""
import hashlib
from urllib.parse import urlsplit

from social_operations.provider_diagnostics import report


def upload_payload(data, mime, kind, *, asset_sha256=None):
    """The existing observer adds operation/attempt identity to this ordered event."""
    try:
        report({"provider": "vk", "operation": "upload_payload", "status": "completed",
                "phase": kind, "upload_bytes": len(data), "upload_mime": mime,
                "asset_sha256": asset_sha256 or hashlib.sha256(data).hexdigest()})
    except Exception:
        # Metadata cannot change a provider outcome or create another attempt.
        pass


def upload_endpoint(details, url):
    try:
        if not isinstance(url, str) or not 1 <= len(url) <= 4096:
            return
        # Only the hostname is retained, even if URL validation later fails.
        host = urlsplit(url).hostname
        if host:
            details["upload_host"] = host.lower()
    except (TypeError, ValueError, AttributeError):
        pass


def upload_response(details, response):
    """All values still pass the closed sanitizer before reaching any observer."""
    try:
        for header, key in (
                ("Server", "response_server"), ("Via", "response_via"),
                ("X-Request-Id", "response_request_id"),
                ("X-VK-Request-Id", "response_vk_request_id"),
                ("X-Correlation-Id", "response_correlation_id")):
            value = response.headers.get(header)
            if isinstance(value, str) and len(value) <= 160:
                details[key] = value
        request = getattr(response, "request_info", None)
        headers = getattr(request, "headers", {})
        length = headers.get("Content-Length")
        if isinstance(length, str) and length.isdecimal() and len(length) <= 9:
            details["request_body_bytes"] = int(length)
        transfer = headers.get("Transfer-Encoding", "")
        if isinstance(transfer, str) and transfer.lower() == "chunked":
            details["request_framing"] = "chunked"
        elif "request_body_bytes" in details:
            details["request_framing"] = "content_length"
        connection = getattr(response, "connection", None)
        transport = getattr(connection, "transport", None)
        if transport is not None:
            peer = transport.get_extra_info("peername")
            if isinstance(peer, tuple) and peer and isinstance(peer[0], str):
                details["peer_ip"] = peer[0]
    except Exception:
        pass


def rejected_url(url, reason, *, api=False):
    """Emit validation evidence even when the adapter rejects before transport."""
    try:
        details = {"provider": "vk", "operation": "upload_url_validation",
                   "status": "failed", "phase": "api" if api else "media",
                   "error_code": "vk_upload_url_invalid", "url_rejection_reason": reason}
        upload_endpoint(details, url)
        report(details)
    except Exception:
        # The original validator still raises; logging never changes admission.
        pass
