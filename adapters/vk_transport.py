"""Role-bound VK HTTPS transport. Fixed methods, no redirects/proxies or retries.

Network addresses are checked and pinned while retaining TLS hostname validation.
No token, upload URL, provider body, cookies or access keys enter core checkpoints.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import zlib
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from social_operations.domain import DomainError

API_VERSION = '5.199'  # Donor-tested contract, not an assertion of latest API.
# Values are (role, required fields, allowed fields). There is no MCP passthrough.
POLICIES = {
    'groups.getById': ('reader', {'group_ids'}, {'group_ids', 'fields'}),
    'wall.getById': ('reader', {'posts'}, {'posts', 'extended'}),
    'wall.get': ('editor', {'owner_id', 'filter', 'count', 'offset'}, {'owner_id', 'filter', 'count', 'offset'}),
    'wall.search': ('reader', {'owner_id', 'query', 'count', 'offset'}, {'owner_id', 'query', 'count', 'offset'}),
    'photos.getWallUploadServer': ('media', {'group_id'}, {'group_id'}),
    'photos.saveWallPhoto': ('media', {'group_id', 'server', 'photo', 'hash'}, {'group_id', 'server', 'photo', 'hash'}),
    'wall.post': ('editor', {'owner_id', 'message', 'from_group', 'signed', 'guid'}, {'owner_id', 'message', 'from_group', 'signed', 'guid', 'attachments', 'publish_date'}),
    'wall.edit': ('editor', {'owner_id', 'post_id'}, {'owner_id', 'post_id', 'message', 'attachments', 'publish_date'}),
    'wall.delete': ('editor', {'owner_id', 'post_id'}, {'owner_id', 'post_id'}),
    'wall.repost': ('editor', {'object', 'group_id'}, {'object', 'group_id'}),
}


READ_ROLES = {'groups.getById', 'wall.getById', 'wall.get', 'wall.search'}


def role_allowed(role: str, method: str) -> bool:
    return role == POLICIES[method][0] or (method in READ_ROLES and role in {'reader', 'editor'})


@dataclass(frozen=True, slots=True)
class VKToken:
    value: str = field(repr=False)
    kind: str = 'user'
    group_id: int | None = None


def validated_url(url: str, *, api=False) -> str:
    if not isinstance(url, str) or not 1 <= len(url) <= 4096 or '\\' in url or any(c.isspace() or ord(c) < 32 for c in url):
        raise DomainError('vk_upload_url_invalid')
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
        if (parts.scheme != 'https' or parts.username is not None or parts.password is not None
                or parts.fragment or parts.port not in {None, 443}):
            raise ValueError()
        if api:
            if host != 'api.vk.com' or parts.path not in {'/method/' + name for name in POLICIES} or parts.query:
                raise ValueError()
        elif not any(host == root or host.endswith('.' + root) for root in ('vk.com', 'userapi.com', 'vkuser.net', 'vk.me')):
            raise ValueError()
    except ValueError:
        raise DomainError('vk_upload_url_invalid') from None
    return host


async def public_addresses(host: str) -> tuple[str, ...]:
    records = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = []
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if not address.is_global or address.is_multicast:
            raise DomainError('vk_nonpublic_address')
        if str(address) not in addresses:
            addresses.append(str(address))
    if not addresses or len(addresses) > 16:
        raise DomainError('vk_dns_invalid')
    return tuple(addresses)


class PinnedResolver:
    def __init__(self, host: str, addresses: tuple[str, ...]):
        self.host, self.addresses = host, addresses

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        if host != self.host or port != 443:
            raise OSError('unexpected resolver target')
        return [{'hostname': host, 'host': a, 'port': port,
                 'family': socket.AF_INET6 if ':' in a else socket.AF_INET,
                 'proto': 0, 'flags': socket.AI_NUMERICHOST} for a in self.addresses]

    async def close(self):
        pass


def decoded_json(wire: bytes, encoding: str) -> object:
    limit = 1024 * 1024
    if len(wire) > limit:
        raise DomainError('vk_response_too_large')
    if encoding in {'gzip', 'deflate'}:
        decoder = zlib.decompressobj(31 if encoding == 'gzip' else zlib.MAX_WBITS)
        try:
            wire = decoder.decompress(wire, limit + 1)
            if len(wire) > limit or decoder.unconsumed_tail or decoder.unused_data or not decoder.eof:
                raise ValueError()
        except (ValueError, zlib.error):
            raise DomainError('vk_response_invalid') from None
    elif encoding not in {'', 'identity'}:
        raise DomainError('vk_response_encoding_unsupported')
    try:
        return json.loads(wire)
    except (ValueError, UnicodeError):
        raise DomainError('vk_response_invalid') from None


class VKHTTPTransport:
    def __init__(self, *, tokens: dict[str, VKToken]):
        if set(tokens) - {'reader', 'editor', 'media'}:
            raise ValueError('unknown VK token role')
        self._tokens = dict(tokens)
        self.account_type = 'vk_' + tokens['editor'].kind if 'editor' in tokens else None

    def permits(self, role: str, method: str, *, group_id: int, scheduled=False) -> bool:
        token = self._tokens.get(role)
        if token is None or not role_allowed(role, method) or token.kind not in {'user', 'group'}:
            return False
        if token.kind == 'user':
            return True
        # No user-token fallback. Group token path stays narrowly text-now/read.
        return (token.group_id == group_id and not scheduled and
                method in {'wall.post', 'wall.getById', 'groups.getById'})

    async def _post(self, url, data, *, api=False):
        import aiohttp  # Optional production extra; no SDK/network needed by scripted tests.
        host = validated_url(url, api=api)
        addresses = await public_addresses(host)
        connector = aiohttp.TCPConnector(resolver=PinnedResolver(host, addresses), use_dns_cache=False, limit=1)
        async with aiohttp.ClientSession(connector=connector, trust_env=False,
                cookie_jar=aiohttp.DummyCookieJar(), auto_decompress=False,
                timeout=aiohttp.ClientTimeout(total=25), headers={'Accept-Encoding': 'identity'}) as session:
            async with session.post(url, data=data, allow_redirects=False) as response:
                if response.status != 200:
                    raise DomainError('vk_http_failed')
                chunks, length = [], 0
                async for chunk in response.content.iter_chunked(65536):
                    length += len(chunk)
                    if length > 1024 * 1024:
                        raise DomainError('vk_response_too_large')
                    chunks.append(chunk)
                return decoded_json(b''.join(chunks), response.headers.get('Content-Encoding', '').lower())

    async def invoke(self, *, role: str, method: str, params: dict):
        policy = POLICIES.get(method)
        if not policy or not role_allowed(role, method) or not policy[1] <= set(params) or set(params) - policy[2]:
            raise DomainError('vk_call_not_allowed')
        token = self._tokens.get(role)
        if token is None:
            raise DomainError('vk_token_role_missing')
        # Recheck token constraints in the transport, not only adapter preflight.
        group_id = int(params.get('group_id') or abs(int(params.get('owner_id', 0))))
        if method == 'groups.getById':
            group_id = int(params['group_ids'])
        if method == 'wall.getById':
            group_id = abs(int(str(params['posts']).split('_')[0]))
        if not self.permits(role, method, group_id=group_id, scheduled='publish_date' in params):
            raise DomainError('vk_token_role_not_permitted')
        try:
            response = await self._post('https://api.vk.com/method/' + method,
                {**params, 'access_token': token.value, 'v': API_VERSION}, api=True)
        except DomainError:
            raise
        except Exception:
            raise DomainError('vk_transport_failed') from None
        if not isinstance(response, dict) or 'response' not in response or 'error' in response:
            code = response.get('error', {}).get('error_code') if isinstance(response, dict) and isinstance(response.get('error'), dict) else None
            raise DomainError('vk_captcha_needs_human' if code == 14 else 'vk_cooldown' if code in {6, 9, 29} else 'vk_api_failed', next_action='contact_owner')
        return response['response']

    async def upload_photo(self, url: str, data: bytes, mime: str) -> dict:
        import aiohttp
        form = aiohttp.FormData()
        form.add_field('photo', data, filename='verified.' + {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[mime], content_type=mime)
        try:
            response = await self._post(url, form)
        except DomainError:
            raise
        except Exception:
            raise DomainError('vk_upload_failed') from None
        # Some upload servers return the receipt in a response envelope.
        if isinstance(response, dict) and isinstance(response.get('response'), dict):
            response = response['response']
        if (not isinstance(response, dict) or type(response.get('server')) is not int or response['server'] <= 0
                or not isinstance(response.get('photo'), str) or not 1 <= len(response['photo']) <= 65536
                or not isinstance(response.get('hash'), str) or not 1 <= len(response['hash']) <= 512 or 'error' in response):
            raise DomainError('vk_upload_response_invalid')
        return {k: response[k] for k in ('server', 'photo', 'hash')}
