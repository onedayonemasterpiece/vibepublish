"""Opt-in trusted native wiring; never called at MCP/HTTP command admission.

Only VIBEPUBLISH_* environment bundles explicitly named in the owner's database
are resolved. There are no EventsBot, file-path, URL or other-session fallbacks.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from .telegram import TelegramAdapter, TelethonTypes
from .vk import VKAdapter
from .vk_transport import VKHTTPTransport, VKToken
from social_operations.domain import DomainError


def _bundle(name, env):
    if not isinstance(name, str) or not re.fullmatch(r'VIBEPUBLISH_[A-Z0-9_]+', name):
        raise DomainError('native_secret_reference_invalid', next_action='contact_owner')
    value = env.get(name)
    if not isinstance(value, str) or not 1 <= len(value) <= 65536:
        raise DomainError('native_credentials_missing', next_action='reauthorize')
    try:
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise DomainError('native_credentials_invalid', next_action='reauthorize') from None
    return result


def telegram_credentials(bundle):
    if (set(bundle) != {'api_id', 'api_hash', 'session'} or type(bundle['api_id']) is not int or bundle['api_id'] <= 0
            or not isinstance(bundle['api_hash'], str) or not re.fullmatch(r'[a-fA-F0-9]{32}', bundle['api_hash'])
            or not isinstance(bundle['session'], str) or not 1 <= len(bundle['session']) <= 8192):
        raise DomainError('native_credentials_invalid', next_action='reauthorize')
    return bundle


def vk_credentials(bundle):
    if set(bundle) != {'roles'} or not isinstance(bundle['roles'], dict) or set(bundle['roles']) - {'reader', 'editor', 'media'}:
        raise DomainError('native_credentials_invalid', next_action='reauthorize')
    result = {}
    for role, value in bundle['roles'].items():
        if (not isinstance(value, dict) or set(value) - {'token', 'kind', 'group_id'}
                or not {'token', 'kind'} <= set(value) or value['kind'] not in {'user', 'group'}
                or not isinstance(value['token'], str) or not 1 <= len(value['token']) <= 8192):
            raise DomainError('native_credentials_invalid', next_action='reauthorize')
        if value['kind'] == 'group' and (type(value.get('group_id')) is not int or value['group_id'] <= 0):
            raise DomainError('native_credentials_invalid', next_action='reauthorize')
        if value['kind'] == 'user' and value.get('group_id') is not None:
            raise DomainError('native_credentials_invalid', next_action='reauthorize')
        result[role] = VKToken(value['token'], value['kind'], value.get('group_id'))
    if 'editor' not in result:
        raise DomainError('vk_editor_token_missing', next_action='reauthorize')
    return result


@asynccontextmanager
async def native_adapters(store, *, env=None, telegram_factory=None, tl=None, vk_factory=VKHTTPTransport):
    """A worker-only lifetime; caller must explicitly enable native connections."""
    env = os.environ if env is None else env
    clients, adapters = [], {}
    with store.connection() as db:
        connections = [dict(row) for row in db.execute('SELECT * FROM connections WHERE active=1')]
    try:
        for connection in connections:
            account = connection['account_type']
            if account in {'unconfigured', 'fake'} or connection['provider'] == 'max':
                continue
            bundle = _bundle(connection['secret_ref'], env)
            if connection['provider'] == 'telegram' and account in {'mtproto_user', 'mtproto_bot'}:
                credentials = telegram_credentials(bundle)
                compiler = tl or TelethonTypes()  # Version check before any connection.
                if telegram_factory is None:
                    from telethon import TelegramClient
                    from telethon.sessions import StringSession
                    client = TelegramClient(StringSession(credentials['session']), credentials['api_id'], credentials['api_hash'],
                        request_retries=0, connection_retries=0, flood_sleep_threshold=0,
                        auto_reconnect=False, receive_updates=False, raise_last_call_error=True)
                else:
                    client = telegram_factory(credentials, request_retries=0, connection_retries=0,
                        flood_sleep_threshold=0, auto_reconnect=False, receive_updates=False, raise_last_call_error=True)
                clients.append(client)
                await client.connect()
                if not await client.is_user_authorized():
                    # Do not call start(), send_code_request(), bot login or interactive auth.
                    raise DomainError('telegram_session_needs_auth', next_action='reauthorize')
                adapters[connection['id']] = TelegramAdapter(client, connection_id=connection['id'], account_type=account, tl=compiler, clock=store.clock)
            elif connection['provider'] == 'vk' and account in {'vk_user', 'vk_group'}:
                tokens = vk_credentials(bundle)
                if 'vk_' + tokens['editor'].kind != account:
                    raise DomainError('vk_account_type_mismatch')
                adapters[connection['id']] = VKAdapter(vk_factory(tokens=tokens), connection_id=connection['id'], account_type=account, clock=store.clock)
            else:
                raise DomainError('native_account_type_needs_review', next_action='contact_owner')
        yield adapters
    except DomainError:
        raise
    except Exception:
        raise DomainError('native_connection_failed', next_action='reauthorize') from None
    finally:
        for client in reversed(clients):
            try:
                await client.disconnect()
            except Exception:
                pass  # Never disclose a session/error payload during cleanup.
