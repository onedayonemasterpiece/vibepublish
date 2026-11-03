"""Bounded public-HTTPS DOCUMENT ingress for a single authenticated owner command.

No client secret, private filesystem path, proxy, redirection or raw media-store
source URL is accepted. The resulting asset goes through ordinary binary
ingress and the existing private Telegram DOCUMENT publication ledger.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from urllib.parse import unquote, urlsplit

import aiohttp

from .asset_ingress import DOCUMENT_MIMES, MAX_UPLOAD_BYTES
from .domain import DomainError
from .ingress import _PinnedResolver, resolve_public_https


@dataclass(frozen=True, slots=True)
class PublicDocument:
    data: bytes
    mime: str
    final_url: str


def validate_archive_document_url(url: str, mime: str) -> str:
    if mime not in DOCUMENT_MIMES or not isinstance(url, str) or not 1 <= len(url) <= 4096:
        raise DomainError("document_url_invalid")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise DomainError("document_url_invalid") from None
    if (parsed.scheme != "https" or parsed.hostname != "prussia.online"
            or port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment or "\\" in url
            or any(c.isspace() or ord(c) < 32 for c in url)):
        raise DomainError("document_url_not_allowed")
    raw_path = parsed.path
    decoded = unquote(raw_path)
    if (not raw_path.startswith("/Data/Book/") or "//" in decoded
            or any(part in {"", ".", ".."} for part in decoded.split("/")[1:])
            or any(ord(c) < 32 or c == "\\" for c in decoded)
            or re.search("%(?:2f|5c|00)", raw_path, re.IGNORECASE)):
        raise DomainError("document_url_not_allowed")
    parts = decoded.split("/")
    if len(parts) != 6 or parts[1:3] != ["Data", "Book"]:
        raise DomainError("document_url_not_allowed")
    suffix = ".pdf" if mime == "application/pdf" else (".djvu", ".djv")
    if not decoded.lower().endswith(suffix):
        raise DomainError("document_url_media_type")
    return url


async def fetch_public_document(url: str, mime: str) -> PublicDocument:
    """Exact public original bytes; HTTPS pinned to verified global DNS answers."""
    url = validate_archive_document_url(url, mime)
    hostname, addresses = await resolve_public_https(url)
    connector = aiohttp.TCPConnector(
        resolver=_PinnedResolver(hostname, addresses),
        use_dns_cache=False, ttl_dns_cache=0)
    timeout = aiohttp.ClientTimeout(total=90, connect=10, sock_read=30)
    try:
        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout, trust_env=False,
            auto_decompress=False, headers={
                "Accept": "application/pdf,image/vnd.djvu,application/octet-stream",
                "User-Agent": "VibePublish/1.7 private-original-document-ingress"
            }) as session:
            async with session.get(url, allow_redirects=False) as response:
                if response.status != 200:
                    raise DomainError("document_url_fetch_failed", next_action="refresh")
                if response.headers.get("Content-Encoding", "").strip().lower() not in ("", "identity"):
                    raise DomainError("document_url_encoding_unsupported")
                length = response.headers.get("Content-Length")
                if length:
                    try:
                        n = int(length)
                    except ValueError:
                        raise DomainError("document_url_size_invalid") from None
                    if not 1 <= n <= MAX_UPLOAD_BYTES:
                        raise DomainError("asset_size_limit")
                data = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_UPLOAD_BYTES:
                        raise DomainError("asset_size_limit")
                if not data:
                    raise DomainError("asset_size_limit")
                return PublicDocument(bytes(data), mime, url)
    except DomainError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        raise DomainError("document_url_unreachable", next_action="refresh") from None
