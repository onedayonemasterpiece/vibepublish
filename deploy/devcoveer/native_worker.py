"""Owner-only acceptance wiring; resolve exact Telegram links before core dispatch.

Reads only the explicitly supplied dedicated session key. No old-session fallback.
No provider write is performed by discovery; core Worker owns every effect.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import json
from pathlib import Path
from dotenv import dotenv_values
from telethon import TelegramClient, functions, utils
from telethon.sessions import StringSession
from adapters.wiring import native_adapters
from adapters.vk import VKAdapter
from social_operations.domain import DomainError, parse_time
from social_operations.storage import Store
from social_operations.worker import Worker

TG_REFERENCE = 'VIBEPUBLISH_ACCEPTANCE_TG'
VK_REFERENCE = 'VIBEPUBLISH_ACCEPTANCE_VK'
VK_TARGET = '-241261191'  # Exact groups.getById(lovekenig), owner-approved URL.
TARGETS = {'lovekenig': -1002079710441, 'f4SHQsDVmjEyNTky': -5283030741}


def credentials(path: Path):
    values = dotenv_values(path)
    supplied = values.get('VIBE_PUBLISH_TG_SESSION')
    if not supplied:
        raise DomainError('dedicated_telegram_session_missing')
    try:
        bundle = json.loads(base64.urlsafe_b64decode(supplied + '=' * (-len(supplied) % 4)))
        session = bundle['session']
    except (ValueError, KeyError, TypeError):
        if supplied.startswith('1'):
            session = supplied
        else:
            raise DomainError('dedicated_telegram_session_invalid') from None
    return {'api_id': int(values['TG_API_ID']), 'api_hash': values['TG_API_HASH'], 'session': session}


class ExactTargetClient(TelegramClient):
    async def connect(self):
        await super().connect()
        if not await self.is_user_authorized():
            raise DomainError('telegram_session_needs_auth')
        channel = await self.get_entity('lovekenig')
        checked = await self(functions.messages.CheckChatInviteRequest('f4SHQsDVmjEyNTky'))
        group = getattr(checked, 'chat', None)
        if group is None:
            raise DomainError('telegram_test_group_not_joined')
        if utils.get_peer_id(channel) != TARGETS['lovekenig'] or utils.get_peer_id(group) != TARGETS['f4SHQsDVmjEyNTky']:
            raise DomainError('telegram_target_identity_changed')
        # The successful RPCs populate only this in-memory session's entity cache.
        self.resolved_targets = {'channel': channel, 'group': group}


def telegram_factory(creds, **kwargs):
    return ExactTargetClient(StringSession(creds['session']), creds['api_id'], creds['api_hash'], **kwargs)


def vk_credentials(path: Path):
    token = dotenv_values(path).get('VK_ACCESS_TOKEN4')
    if not token:
        raise DomainError('approved_vk_user_token_missing')
    return {'roles': {role: {'token': token, 'kind': 'user'}
                      for role in ('reader', 'editor', 'media')}}


class PostponedOnlyVK(VKAdapter):
    """Acceptance-only owner boundary, rechecked before provider execution."""
    def _connection(self, request):
        super()._connection(request)
        if request.native_target != VK_TARGET:
            raise DomainError('vk_acceptance_target_not_allowed')

    def _mutation_allowed(self, request):
        self._connection(request)
        action = getattr(request, 'action', None)
        if action is None:  # Native readback, not a mutation.
            return
        if action == 'cancel' and request.existing and request.existing.namespace == 'scheduled':
            return
        if action not in {'publish', 'edit', 'reschedule'} or not request.scheduled_at:
            raise DomainError('vk_acceptance_postponed_only')
        if parse_time(request.scheduled_at) < self.clock() + 86400:
            raise DomainError('vk_acceptance_minimum_24h')
        if request.existing and request.existing.namespace != 'scheduled':
            raise DomainError('vk_acceptance_postponed_only')

    async def _rights(self, request):
        self._mutation_allowed(request)
        return await super()._rights(request)


async def run(db: Path, env_file: Path, once=False, vk_env_file: Path | None = None):
    store = Store(db)
    bundles = {TG_REFERENCE: json.dumps(credentials(env_file))}
    if vk_env_file is not None:
        bundles[VK_REFERENCE] = json.dumps(vk_credentials(vk_env_file))
    async with native_adapters(store, env=bundles, telegram_factory=telegram_factory) as wiring:
        for key, adapter in list(wiring.items()):
            if isinstance(adapter, VKAdapter):
                wiring[key] = PostponedOnlyVK(adapter.transport, connection_id=key,
                                             account_type=adapter.account_type, clock=store.clock)
        worker = Worker(store, wiring)
        while True:
            worked = await worker.run_once()
            if once: return
            if not worked: await asyncio.sleep(.25)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', required=True, type=Path)
    p.add_argument('--telegram-env-file', required=True, type=Path)
    p.add_argument('--once', action='store_true')
    p.add_argument('--vk-env-file', type=Path)
    args = p.parse_args()
    try:
        asyncio.run(run(args.db, args.telegram_env_file, args.once, args.vk_env_file))
    except Exception as exc:
        # Never include provider messages, dotenv content, session or credential data.
        print(json.dumps({'error_type': type(exc).__name__, 'code': exc.code if isinstance(exc, DomainError) else 'native_worker_failed'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
