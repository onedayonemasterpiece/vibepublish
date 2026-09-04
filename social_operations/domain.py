"""Small, immutable application vocabulary and canonical identities."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit


class DomainError(Exception):
    """Only deliberately sanitized messages cross the application boundary."""

    def __init__(self, code: str, message: str | None = None, next_action: str = "fix_input"):
        self.code = code
        self.message = message or code.replace("_", " ")
        self.next_action = next_action
        super().__init__(self.message)

    def output(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message},
                "message": self.message, "next_action": self.next_action, "retry_safe": False}


class OutcomeUnknown(DomainError):
    def __init__(self, code: str = "outcome_unknown"):
        super().__init__(code, "Provider outcome requires observation; do not repeat the command", "review_outcome")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def new_id(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex


def timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> float:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("offset required")
        return result.timestamp()
    except (ValueError, TypeError, OverflowError) as exc:
        raise DomainError("invalid_time", "Use an RFC3339 timestamp with an explicit offset") from exc


@dataclass(frozen=True, slots=True)
class Actor:
    tenant_id: str
    principal_id: str
    epoch: int
    owner: bool
    scopes: frozenset[str]
    routing_revision: int
    timezone: str


@dataclass(frozen=True, slots=True)
class NativeSource:
    provider: str
    channel: str
    item: str
    # A public-looking URL is NOT proof of actual public visibility.
    public_candidate: bool
    canonical_url: str


def parse_source(url: str) -> NativeSource:
    """Parse exact native permalinks only. Never follow redirects or join chats."""
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
                or p.fragment or "\\" in url or any(c.isspace() or ord(c) < 32 for c in url)):
            raise ValueError()
        host = (p.hostname or "").lower()
        query = parse_qs(p.query, keep_blank_values=True)
        if any(k not in {"single", "utm_source", "utm_medium", "utm_campaign"} for k in query):
            raise ValueError()
        if host == "t.me":
            m = re.fullmatch(r"/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})/([1-9][0-9]*)/?", p.path)
            if m:
                channel, item = m.groups()
                return NativeSource("telegram", channel.lower(), item, True,
                                    f"https://t.me/{channel.lower()}/{item}")
            m = re.fullmatch(r"/c/([1-9][0-9]*)/([1-9][0-9]*)/?", p.path)
            if m:
                channel, item = m.groups()
                return NativeSource("telegram", "-100" + channel, item, False,
                                    f"https://t.me/c/{channel}/{item}")
        if host in {"vk.com", "vk.ru", "www.vk.com", "www.vk.ru"}:
            m = re.fullmatch(r"/wall(-?[1-9][0-9]*)_([1-9][0-9]*)/?", p.path)
            if m:
                channel, item = m.groups()
                return NativeSource("vk", channel, item, True, f"https://vk.ru/wall{channel}_{item}")
    except ValueError:
        pass
    raise DomainError("unsupported_source_url", "Use an exact Telegram message or VK wall post permalink")


def normalize_intent(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(canonical(args))
    for key in ("request_key", "repeat_of", "routing_revision"):
        result.pop(key, None)
    if tool in {"publish", "engage"}:
        target = result if tool == "publish" else result.get("command", {})
        if tool == "publish" or target.get("kind") == "forward":
            target.setdefault("delivery", {"kind": "now"})
            target.setdefault("mode", "execute")
            if target["delivery"]["kind"] == "at":
                target["delivery"]["at"] = timestamp(parse_time(target["delivery"]["at"]))
            if tool == "publish":
                target.setdefault("surface", "post")
                target.setdefault("media", [])
                target.setdefault("renderings", {})
            else:
                target.setdefault("selection", "post")
                source = target["item_ref"]
                if source.startswith("https://"):
                    target["item_ref"] = parse_source(source).canonical_url
    return result
