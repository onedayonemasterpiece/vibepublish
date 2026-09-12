"""Bounded public-HTTPS image ingress and owner direct Telegram link routing.

Public image URLs are imported into private assets before normal admission.
For the owner only, a Telegram chat/message/topic link may select any chat
visible to the configured Telegram account without a pre-created VibePublish
destination binding. Provider preflight still proves the actual account access
before any external effect.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from jsonschema import Draft202012Validator

from .assets import insert_verified_image, verify_image
from .domain import DomainError, canonical, new_id, parse_source
from .service import Application, FORMATS

_MAX_SOURCE_BYTES = 20 * 1024 * 1024
_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}
_REDIRECTS = {301, 302, 303, 307, 308}
_DIRECT_ALIAS_PREFIX = "vp_direct_tg_"
_DIRECT_RIGHTS = ("publish", "edit", "reschedule", "cancel", "delete", "forward")
# Owner direct targets accept the normal t.me chat/message/forum-topic forms,
# including Telegram's three-component <topic>/<message> forum permalinks.
_DIRECT_THREAD_PATTERN = (
    r"^https://t\.me/(?:"
    r"c/[1-9][0-9]*(?:/[1-9][0-9]*(?:/[1-9][0-9]*)?)?|"
    r"(?:s/)?[A-Za-z][A-Za-z0-9_]{3,31}(?:/[1-9][0-9]*(?:/[1-9][0-9]*)?)?"
    r")/?(?:\?[^#]{1,512})?$"
)
_ALLOWED_TELEGRAM_QUERY = {
    "single", "thread", "t", "task", "option",
    "utm_source", "utm_medium", "utm_campaign",
}


@dataclass(frozen=True, slots=True)
class PublicImage:
    data: bytes
    mime: str
    final_url: str


@dataclass(frozen=True, slots=True)
class DirectTelegramTarget:
    selector: str
    item: str | None
    public_candidate: bool
    canonical_url: str


def _parse_direct_telegram_target(url: str) -> DirectTelegramTarget:
    """Parse a stable chat root or normal Telegram message/topic permalink."""
    # Keep the established canonical parser as the first path for its exact forms.
    try:
        source = parse_source(url)
    except DomainError as exc:
        if exc.code != "unsupported_source_url":
            raise
    else:
        if source.provider != "telegram":
            raise DomainError("telegram_thread_reference_required")
        return DirectTelegramTarget(
            source.channel, source.item, source.public_candidate, source.canonical_url
        )

    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.fragment
            or "\\" in url
            or any(char.isspace() or ord(char) < 32 for char in url)
            or (parsed.hostname or "").lower() != "t.me"
        ):
            raise ValueError()
        query = parse_qs(parsed.query, keep_blank_values=True)
        if any(key not in _ALLOWED_TELEGRAM_QUERY for key in query):
            raise ValueError()
        if "thread" in query:
            values = query["thread"]
            if len(values) != 1 or not re.fullmatch(r"[1-9][0-9]*", values[0]):
                raise ValueError()

        public = re.fullmatch(
            r"/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})"
            r"(?:/([1-9][0-9]*)(?:/([1-9][0-9]*))?)?/?",
            parsed.path,
        )
        if public:
            handle, first, second = public.groups()
            item = second or first
            if "thread" in query and item is None:
                raise ValueError()
            handle = handle.lower()
            canonical = f"https://t.me/{handle}" + (f"/{item}" if item else "")
            return DirectTelegramTarget(handle, item, True, canonical)

        private = re.fullmatch(
            r"/c/([1-9][0-9]*)(?:/([1-9][0-9]*)(?:/([1-9][0-9]*))?)?/?",
            parsed.path,
        )
        if private:
            channel, first, second = private.groups()
            item = second or first
            if "thread" in query and item is None:
                raise ValueError()
            peer = str(-1_000_000_000_000 - int(channel))
            canonical = f"https://t.me/c/{channel}" + (f"/{item}" if item else "")
            return DirectTelegramTarget(peer, item, False, canonical)
    except ValueError:
        pass
    raise DomainError(
        "telegram_target_url_invalid",
        "Use a Telegram chat, message or forum-topic link; invite/share/comment links are not direct destinations",
    )


class _PinnedResolver(AbstractResolver):
    """Resolve one already-validated hostname only to prevalidated public IPs."""

    def __init__(self, hostname: str, addresses: tuple[str, ...]):
        self.hostname = hostname
        self.addresses = addresses

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_UNSPEC):
        if host.lower().rstrip(".") != self.hostname:
            raise OSError("resolver host mismatch")
        result = []
        for address in self.addresses:
            ip = ipaddress.ip_address(address)
            af = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
            if family not in (socket.AF_UNSPEC, af):
                continue
            result.append({
                "hostname": host,
                "host": address,
                "port": port,
                "family": af,
                "proto": socket.IPPROTO_TCP,
                "flags": 0,
            })
        if not result:
            raise OSError("no validated address")
        return result

    async def close(self):
        return None


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global


async def resolve_public_https(url: str) -> tuple[str, tuple[str, ...]]:
    """Validate URL syntax and pin every DNS answer to a public address."""
    if not isinstance(url, str) or not 1 <= len(url) <= 4096:
        raise DomainError("image_url_invalid")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise DomainError("image_url_invalid") from None
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.fragment
        or not parsed.hostname
        or "\\" in url
        or any(char.isspace() or ord(char) < 32 for char in url)
    ):
        raise DomainError("image_url_invalid")
    hostname = parsed.hostname.lower().rstrip(".")
    if not hostname or hostname == "localhost":
        raise DomainError("image_url_not_public")

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise DomainError("image_url_not_public")
        return hostname, (str(literal),)

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, hostname, 443, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except OSError:
        raise DomainError("image_url_unreachable", next_action="refresh") from None
    addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
    if not addresses or not all(_public_address(address) for address in addresses):
        raise DomainError("image_url_not_public")
    return hostname, addresses


async def fetch_public_image(url: str) -> PublicImage:
    """Fetch a small public image with DNS pinning and bounded redirects/body."""
    current = url
    for redirect_count in range(4):
        hostname, addresses = await resolve_public_https(current)
        resolver = _PinnedResolver(hostname, addresses)
        connector = aiohttp.TCPConnector(
            resolver=resolver, use_dns_cache=False, ttl_dns_cache=0
        )
        timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=False,
                auto_decompress=False,
                headers={
                    "Accept": "image/png,image/jpeg,image/webp",
                    "User-Agent": "VibePublish/0.1 public-image-ingress",
                },
            ) as session:
                async with session.get(current, allow_redirects=False) as response:
                    if response.status in _REDIRECTS:
                        location = response.headers.get("Location")
                        if not location or redirect_count >= 3:
                            raise DomainError("image_url_redirect_invalid")
                        current = urljoin(current, location)
                        continue
                    if response.status != 200:
                        raise DomainError("image_url_fetch_failed", next_action="refresh")
                    encoding = response.headers.get("Content-Encoding", "").strip().lower()
                    if encoding not in {"", "identity"}:
                        raise DomainError("image_url_content_encoding_unsupported")
                    mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if mime not in _ALLOWED_MIME:
                        raise DomainError("image_url_media_type_unsupported")
                    declared = response.headers.get("Content-Length")
                    if declared:
                        try:
                            declared_size = int(declared)
                        except ValueError:
                            raise DomainError("image_url_size_invalid") from None
                        if declared_size <= 0 or declared_size > _MAX_SOURCE_BYTES:
                            raise DomainError("asset_size_limit")
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        body.extend(chunk)
                        if len(body) > _MAX_SOURCE_BYTES:
                            raise DomainError("asset_size_limit")
                    if not body:
                        raise DomainError("invalid_image")
                    return PublicImage(bytes(body), mime, current)
        except DomainError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            raise DomainError("image_url_unreachable", next_action="refresh") from None
    raise DomainError("image_url_redirect_invalid")


def _widen_owner_telegram_links(value):
    """Widen only the authenticated owner's projected MCP schema."""
    if isinstance(value, list):
        for item in value:
            _widen_owner_telegram_links(item)
    elif isinstance(value, dict):
        pattern = value.get("pattern")
        if isinstance(pattern, str) and pattern.startswith(r"^https://t\.me/c/"):
            value["pattern"] = _DIRECT_THREAD_PATTERN
        for item in value.values():
            _widen_owner_telegram_links(item)


class IngressApplication(Application):
    """Application facade for safe public media and owner direct Telegram links."""

    def __init__(self, store, *, fetcher=None):
        super().__init__(store)
        self._fetcher = fetcher or fetch_public_image

    def aliases(self, db, actor):
        return [
            item for item in super().aliases(db, actor)
            if not item["alias"].startswith(_DIRECT_ALIAS_PREFIX)
        ]

    def tools(self, actor):
        tools = super().tools(actor)
        if actor.owner:
            _widen_owner_telegram_links(tools)
            for tool in tools:
                if tool["name"] != "vibepublish_publish":
                    continue
                schema = tool["inputSchema"]
                schema["required"] = [key for key in schema.get("required", []) if key != "to"]
                schema.setdefault("allOf", []).append({
                    "anyOf": [
                        {"required": ["to"]},
                        {
                            "required": ["thread_ref"],
                            "properties": {
                                "thread_ref": {"type": "string", "pattern": _DIRECT_THREAD_PATTERN}
                            },
                        },
                    ]
                })
        return tools

    def _owner_thread_alias(self, actor, ref: str, requested_to=()) -> str:
        target = _parse_direct_telegram_target(ref)
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            if not actor.owner:
                raise DomainError("access_denied", next_action="contact_owner")

            selector = None
            if requested_to:
                selected = self._targets(db, actor, list(requested_to))
                if len(selected) != 1 or selected[0]["provider"] != "telegram":
                    raise DomainError(
                        "telegram_connection_ambiguous",
                        "Use one Telegram destination to select the account connection",
                        "fix_input",
                    )
                selector = selected[0]

            sql = (
                "SELECT b.*,d.native_id,d.handle,d.label,d.connection_id,"
                "c.provider,c.account_type,c.secret_ref FROM bindings b "
                "JOIN destinations d ON d.id=b.destination_id "
                "JOIN connections c ON c.id=d.connection_id "
                "WHERE b.tenant_id=? AND b.principal_id=? AND b.active=1 "
                "AND c.active=1 AND c.provider='telegram' AND d.native_id=?"
            )
            params = [actor.tenant_id, actor.principal_id, target.selector]
            if selector is not None:
                sql += " AND d.connection_id=?"
                params.append(selector["connection_id"])
            existing = [dict(row) for row in db.execute(sql, params)]
            if len(existing) == 1:
                return existing[0]["alias"]
            if len(existing) > 1:
                raise DomainError(
                    "telegram_connection_ambiguous",
                    "The chat is visible through more than one Telegram connection",
                    "fix_input",
                )

            if selector is not None:
                connection_id = selector["connection_id"]
            else:
                connections = [dict(row) for row in db.execute(
                    "SELECT * FROM connections WHERE tenant_id=? AND provider='telegram' "
                    "AND account_type IN ('mtproto_user','mtproto_bot') AND active=1 ORDER BY id",
                    (actor.tenant_id,),
                )]
                if len(connections) != 1:
                    raise DomainError(
                        "telegram_connection_ambiguous" if connections else "telegram_connection_unavailable",
                        "Select one Telegram destination when more than one account connection is active"
                        if connections else "No active Telegram MTProto connection is available",
                        "fix_input" if connections else "reauthorize",
                    )
                connection_id = connections[0]["id"]

            stale = db.execute(
                "SELECT b.active FROM bindings b JOIN destinations d ON d.id=b.destination_id "
                "WHERE b.tenant_id=? AND b.principal_id=? AND d.connection_id=? AND d.native_id=?",
                (actor.tenant_id, actor.principal_id, connection_id, target.selector),
            ).fetchone()
            if stale and not stale["active"]:
                raise DomainError("access_revoked", next_action="reauthorize")

            destination = db.execute(
                "SELECT id FROM destinations WHERE connection_id=? AND native_id=?",
                (connection_id, target.selector),
            ).fetchone()
            destination_id = destination["id"] if destination else new_id("dest")
            if not destination:
                db.execute(
                    "INSERT INTO destinations VALUES(?,?,?,?,?)",
                    (
                        destination_id,
                        connection_id,
                        target.selector,
                        target.selector if target.public_candidate else "",
                        "Telegram direct target",
                    ),
                )

            alias = _DIRECT_ALIAS_PREFIX + hashlib.sha256(
                f"{connection_id}:{target.selector}".encode()
            ).hexdigest()[:20]
            collision = db.execute(
                "SELECT destination_id FROM bindings WHERE tenant_id=? AND principal_id=? AND alias=?",
                (actor.tenant_id, actor.principal_id, alias),
            ).fetchone()
            if collision and collision["destination_id"] != destination_id:
                raise DomainError("direct_target_alias_collision", next_action="contact_owner")
            if not collision:
                db.execute(
                    "INSERT INTO bindings(id,tenant_id,principal_id,alias,destination_id,rights) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        new_id("bind"), actor.tenant_id, actor.principal_id, alias,
                        destination_id, canonical(list(_DIRECT_RIGHTS)),
                    ),
                )
            return alias

    def _telegram_thread(self, db, actor, ref):
        """Owner-direct Telegram links are routes; they never grant partner access."""
        if ref.startswith("https://"):
            target = _parse_direct_telegram_target(ref)
            matches = [
                dict(row) for row in self.store.bindings(db, actor)
                if row["provider"] == "telegram"
                and target.selector in (row["native_id"], row["handle"])
            ]
            if len(matches) != 1:
                raise DomainError(
                    "access_denied",
                    "The Telegram group is not bound for this principal",
                    "contact_owner",
                )
            return matches[0], target.item
        return super()._telegram_thread(db, actor, ref)

    def _rewrite_direct_thread(self, actor, name: str, arguments: dict) -> dict:
        result = json.loads(canonical(arguments))
        if not actor.owner:
            return result
        if (
            name == "vibepublish_publish"
            and isinstance(result.get("thread_ref"), str)
            and result["thread_ref"].startswith("https://")
        ):
            alias = self._owner_thread_alias(actor, result["thread_ref"], result.get("to", ()))
            result["to"] = [alias]
        elif name == "vibepublish_read":
            query = result.get("query", {})
            if (
                query.get("kind") == "thread"
                and isinstance(query.get("item_ref"), str)
                and query["item_ref"].startswith("https://")
            ):
                self._owner_thread_alias(actor, query["item_ref"])
        return result

    async def _import_url(self, actor, url: str) -> str:
        fetched = await self._fetcher(url)
        if (
            not isinstance(fetched, PublicImage)
            or not isinstance(fetched.data, bytes)
            or fetched.mime not in _ALLOWED_MIME
        ):
            raise DomainError("image_url_fetch_invalid", next_action="contact_owner")
        verified = verify_image(fetched.data, fetched.mime)
        source_sha = hashlib.sha256(verified.original).hexdigest()
        clean_sha = hashlib.sha256(verified.data).hexdigest()
        with self.store.tx() as db:
            actor = self.store.current(db, actor)
            existing = db.execute(
                "SELECT id FROM assets WHERE tenant_id=? AND principal_id=? "
                "AND sha256=? AND source_sha256=? AND mime='image/png' "
                "ORDER BY rowid DESC LIMIT 1",
                (actor.tenant_id, actor.principal_id, clean_sha, source_sha),
            ).fetchone()
            if existing:
                return existing["id"]
            return insert_verified_image(self.store, db, actor, verified)

    async def _rewrite_publish(self, actor, arguments: dict) -> dict:
        result = json.loads(canonical(arguments))
        for entry in result.get("media", []):
            source = entry["source"]
            if source["kind"] == "asset":
                continue
            if source["kind"] == "upload":
                raise DomainError(
                    "media_ingress_not_enabled",
                    "Upload-ticket ingress is not enabled",
                    "contact_owner",
                )
            if source["kind"] != "url":
                raise DomainError("media_ingress_not_enabled", next_action="contact_owner")
            asset_ref = await self._import_url(actor, source["url"])
            entry["source"] = {"kind": "asset", "id": asset_ref}
        return result

    async def call(self, actor, name: str, arguments: dict):
        try:
            tool = next((item for item in self.tools(actor) if item["name"] == name), None)
            if tool is None or not isinstance(arguments, dict):
                return await super().call(actor, name, arguments)
            validator = Draft202012Validator(tool["inputSchema"], format_checker=FORMATS)
            if list(validator.iter_errors(arguments)):
                return await super().call(actor, name, arguments)

            prepared = self._rewrite_direct_thread(actor, name, arguments)
            if list(validator.iter_errors(prepared)):
                return await super().call(actor, name, prepared)
            if name == "vibepublish_publish" and any(
                entry.get("source", {}).get("kind") in {"url", "upload"}
                for entry in prepared.get("media", [])
            ):
                prepared = await self._rewrite_publish(actor, prepared)
            return await super().call(actor, name, prepared)
        except DomainError as exc:
            return exc.output()
