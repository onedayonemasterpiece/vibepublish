"""Bounded public-HTTPS image ingress for MCP/HTTP publish commands.

Only publish media whose contract source.kind is ``url`` is imported here.
The fetched bytes are verified by the existing image pipeline and stored as a
private asset before the normal immutable publication plan is admitted.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from jsonschema import Draft202012Validator

from .assets import insert_verified_image, verify_image
from .domain import DomainError, canonical
from .service import Application, FORMATS

_MAX_SOURCE_BYTES = 20 * 1024 * 1024
_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}
_REDIRECTS = {301, 302, 303, 307, 308}


@dataclass(frozen=True, slots=True)
class PublicImage:
    data: bytes
    mime: str
    final_url: str


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


class IngressApplication(Application):
    """Application facade that turns public image URLs into private assets."""

    def __init__(self, store, *, fetcher=None):
        super().__init__(store)
        self._fetcher = fetcher or fetch_public_image

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
            def canonical_asset():
                return db.execute(
                    "SELECT id FROM assets WHERE tenant_id=? AND principal_id=? "
                    "AND sha256=? AND source_sha256=? AND mime='image/png' AND bytes=? "
                    "ORDER BY id LIMIT 1",
                    (actor.tenant_id, actor.principal_id, clean_sha, source_sha, verified.data),
                ).fetchone()
            existing = canonical_asset()
            if existing:
                return existing["id"]
            insert_verified_image(self.store, db, actor, verified)
            # If source bytes are already the canonical metadata-free PNG, the
            # immutable source row and derivative may be byte-identical. Always
            # select the same canonical row so retries keep one request digest.
            inserted = canonical_asset()
            if not inserted:
                raise DomainError("asset_integrity", next_action="contact_owner")
            return inserted["id"]

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
        # Validate scope and the original public contract before any network I/O.
        tool = next((item for item in self.tools(actor) if item["name"] == name), None)
        if tool is None or not isinstance(arguments, dict):
            return await super().call(actor, name, arguments)
        if list(Draft202012Validator(
            tool["inputSchema"], format_checker=FORMATS
        ).iter_errors(arguments)):
            return await super().call(actor, name, arguments)
        if name != "vibepublish_publish" or not any(
            entry.get("source", {}).get("kind") in {"url", "upload"}
            for entry in arguments.get("media", [])
        ):
            return await super().call(actor, name, arguments)
        try:
            rewritten = await self._rewrite_publish(actor, arguments)
            return await super().call(actor, name, rewritten)
        except DomainError as exc:
            return exc.output()
