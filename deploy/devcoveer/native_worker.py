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
from social_operations.domain import DomainError
from social_operations.storage import Store
from social_operations.worker import Worker

TG_REFERENCE = 'VIBEPUBLISH_ACCEPTANCE_TG'
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


async def run(db: Path, env_file: Path, once=False):
    store = Store(db)
    bundles = {TG_REFERENCE: json.dumps(credentials(env_file))}
    async with native_adapters(store, env=bundles, telegram_factory=telegram_factory) as wiring:
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
    args = p.parse_args()
    try:
        asyncio.run(run(args.db, args.telegram_env_file, args.once))
    except Exception as exc:
        # Never include provider messages, dotenv content, session or credential data.
        print(json.dumps({'error_type': type(exc).__name__, 'code': exc.code if isinstance(exc, DomainError) else 'native_worker_failed'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
