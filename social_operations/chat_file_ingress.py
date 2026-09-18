"""Client attachment import. Signed URLs are ephemeral and never checkpointed."""
from __future__ import annotations
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlsplit

import aiohttp
from yarl import URL
from adapters.vk_transport import PinnedResolver
from .assets import insert_verified_image, verify_image
from .asset_ingress import MAX_UPLOAD_BYTES
from .domain import DomainError, digest

ACTION = 'chat_file_import'
DOWNLOAD_SECONDS = 10


def validated_host(url):
    try:
        if not isinstance(url, str) or not 1 <= len(url) <= 8192 or any(ord(c) <= 32 or ord(c) >= 127 for c in url) or '\\' in url:
            raise ValueError()
        parts = urlsplit(url)
        host = parts.hostname or ''
        if (parts.scheme != 'https' or parts.username is not None or parts.password is not None
                or parts.fragment or parts.port not in {None, 443} or len(host) > 253
                or not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', host)
                or any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-') for label in host.split('.'))):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        return host.lower()
    except ValueError:
        raise DomainError('file_url_invalid') from None


async def pinned_addresses(host):
    records = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = []
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if (not address.is_global or address.is_multicast
                or isinstance(address, ipaddress.IPv6Address) and
                (address.ipv4_mapped or address.sixtofour or address.teredo
                 or address in ipaddress.ip_network('64:ff9b::/96'))):
            raise DomainError('file_nonpublic_address')
        if str(address) not in addresses:
            addresses.append(str(address))
    if not addresses or len(addresses) > 16:
        raise DomainError('file_dns_invalid')
    return tuple(addresses)


async def download_file(url):
    host = validated_host(url)
    try:
        async with asyncio.timeout(DOWNLOAD_SECONDS):
            addresses = await pinned_addresses(host)
            connector = aiohttp.TCPConnector(resolver=PinnedResolver(host, addresses),
                                             use_dns_cache=False, limit=1, force_close=True)
            async with aiohttp.ClientSession(connector=connector, trust_env=False,
                    cookie_jar=aiohttp.DummyCookieJar(), auto_decompress=False,
                    timeout=aiohttp.ClientTimeout(total=DOWNLOAD_SECONDS),
                    headers={'Accept-Encoding': 'identity'}) as session:
                async with session.get(URL(url, encoded=True), allow_redirects=False) as response:
                    if response.status != 200:
                        raise DomainError('file_download_failed')
                    if response.headers.get('Content-Encoding', '').lower() not in {'', 'identity'}:
                        raise DomainError('file_encoding_unsupported')
                    if response.content_length is not None and response.content_length > MAX_UPLOAD_BYTES:
                        raise DomainError('asset_size_limit')
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        if len(data) + len(chunk) > MAX_UPLOAD_BYTES:
                            raise DomainError('asset_size_limit')
                        data.extend(chunk)
                    return bytes(data)
    except DomainError:
        raise
    except TimeoutError:
        raise DomainError('file_download_timeout') from None
    except (aiohttp.ClientError, OSError, ValueError):
        raise DomainError('file_download_failed') from None


def sniff_mime(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    raise DomainError('invalid_image')


def authority(store, db, actor):
    actor = store.current(db, actor)
    if not actor.scopes.intersection({'publish', 'visual'}):
        raise DomainError('access_denied')
    return actor


async def import_chat_file(service, actor, args):
    if not hasattr(service, '_chat_file_slots'):
        service._chat_file_slots = asyncio.Semaphore(2)
    slots = service._chat_file_slots
    if slots.locked():
        raise DomainError('asset_ingress_busy')
    async with slots:
        return await _import_chat_file(service, actor, args)


async def _import_chat_file(service, actor, args):
    store, file, key = service.store, args['file'], args['request_key']
    # Hash identity only: never persist client filename, file ID or signed URL.
    intent = {'file_digest': digest([file['file_id'], file.get('mime_type')])}
    with store.connection() as db:
        actor = authority(store, db, actor)
        op = service._replay(db, actor, ACTION, intent, {'request_key': key}, implicit=False)
    if op:
        return store.receipt(actor, op)
    data = await download_file(file['download_url'])
    mime = sniff_mime(data)
    if file.get('mime_type', mime) != mime:
        raise DomainError('asset_format_or_dimensions')
    # Decode off-loop. A two-job process gate also bounds fetched image buffers.
    from starlette.concurrency import run_in_threadpool
    image = await run_in_threadpool(verify_image, data, mime)
    with store.tx() as db:
        actor = authority(store, db, actor)
        op = service._replay(db, actor, ACTION, intent, {'request_key': key}, implicit=False)
        if not op:
            ident = insert_verified_image(store, db, actor, image)
            op = service._new_operation(db, actor, ACTION, intent, complete=True, result={'resource_id': ident})
            service._key(db, actor, key, digest([ACTION, intent]), op)
    return store.receipt(actor, op)
