"""Exact public-channel resolution using the existing authenticated MAX UI."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from social_operations.domain import DomainError


def parse_destination_url(url):
    if (not isinstance(url, str) or len(url) > 512 or "\\" in url
            or any(c.isspace() or ord(c) < 32 for c in url)):
        raise DomainError("max_destination_url_invalid")
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise DomainError("max_destination_url_invalid") from None
    if (parsed.scheme != "https" or parsed.netloc != "max.ru"
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/[A-Za-z][A-Za-z0-9_]{2,127}/?", parsed.path)):
        raise DomainError("max_destination_url_invalid")
    handle = parsed.path.strip("/")
    if handle.lower() in {"join", "share", "login", "auth", "download", "privacy", "terms"}:
        raise DomainError("max_destination_url_invalid")
    return "https://max.ru/" + handle


async def resolve(adapter, url):
    url = parse_destination_url(url)
    if (getattr(adapter, "account_type", None) != "max_web"
            or not getattr(adapter, "live_enabled", False)
            or not callable(getattr(adapter, "resolve_destination", None))):
        raise DomainError("max_discovery_requires_live_connection")
    evidence = await adapter.resolve_destination(url)
    if (not isinstance(evidence, dict)
            or evidence.get("url") != url
            or evidence.get("kind") != "channel"
            or evidence.get("publish_verified") is not True
            or evidence.get("source") != "max_web_visible_channel"
            or not re.fullmatch(r"-[1-9][0-9]{0,19}", str(evidence.get("native_id", "")))
            or not isinstance(evidence.get("label"), str)
            or not 1 <= len(evidence["label"]) <= 200):
        raise DomainError("max_destination_evidence_unverified", next_action="contact_owner")
    return dict(evidence, handle=url.rsplit("/", 1)[1], rights=["publish"])
