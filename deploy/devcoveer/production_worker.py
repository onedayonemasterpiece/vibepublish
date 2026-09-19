"""Permanent DevCoveer native worker for VibePublish internal production.

This worker intentionally has no acceptance-only Telegram target probes or VK
postponed-only policy. Provider connections are provisioned in the durable
ledger and must use the production secret references below. Startup fails
closed when the selected provider topology is incomplete or ambiguous.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat

from dotenv import dotenv_values
from telethon import TelegramClient
from telethon.sessions import StringSession

from adapters.wiring import native_adapters
from social_operations.domain import DomainError
from social_operations.storage import Store
from social_operations.worker import Worker

TG_REFERENCE = "VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE"
VK_REFERENCE = "VIBEPUBLISH_VK_USER_AUTH_BUNDLE"
MAX_REFERENCE = "VIBEPUBLISH_MAX_PROFILE"


@contextmanager
def exclusive_session_owner(path: Path):
    """Hold one host-process owner for the production Telegram session."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise DomainError('telegram_session_lock_invalid', next_action='contact_owner')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DomainError(
                'telegram_session_already_owned',
                'telegram session already owned',
                'contact_owner',
            ) from None
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def telegram_credentials(path: Path, *, session_key="VIBE_PUBLISH_TG_SESSION",
                         api_id_key="TG_API_ID", api_hash_key="TG_API_HASH"):
    values = dotenv_values(path)
    supplied = values.get(session_key)
    if not supplied:
        raise DomainError("dedicated_telegram_session_missing")
    try:
        bundle = json.loads(base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4)))
        session = bundle["session"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        if supplied.startswith("1"):
            session = supplied
        else:
            raise DomainError("dedicated_telegram_session_invalid") from None
    api_id = values.get(api_id_key)
    api_hash = values.get(api_hash_key)
    if not api_id or not api_hash:
        raise DomainError("dedicated_telegram_api_credentials_missing")
    try:
        api_id_int = int(api_id)
    except (TypeError, ValueError):
        raise DomainError("dedicated_telegram_api_credentials_invalid") from None
    return {"api_id": api_id_int, "api_hash": api_hash, "session": session}


def vk_credentials(path: Path, token_key: str):
    values = dotenv_values(path)
    token = values.get(token_key)
    if not token:
        raise DomainError("approved_vk_user_token_missing")
    return {
        "roles": {
            role: {"token": token, "kind": "user"}
            for role in ("reader", "editor", "media")
        }
    }


def telegram_factory(credentials, **kwargs):
    return TelegramClient(
        StringSession(credentials["session"]),
        credentials["api_id"],
        credentials["api_hash"],
        **kwargs,
    )


def production_connections(store: Store, *, telegram_only=False, providers=None):
    expected = {
        "telegram": ("mtproto_user", TG_REFERENCE),
        "vk": ("vk_user", VK_REFERENCE),
        "max": ("max_web", MAX_REFERENCE),
    }
    if telegram_only and providers is not None:
        raise DomainError('production_provider_selection_conflict')
    selected_providers = tuple(providers) if providers is not None else (
        ('telegram',) if telegram_only else tuple(expected))
    if ('telegram' not in selected_providers
            or len(set(selected_providers)) != len(selected_providers)
            or any(provider not in expected for provider in selected_providers)):
        raise DomainError('production_provider_selection_invalid')
    expected = {provider: expected[provider] for provider in selected_providers}
    with store.connection() as db:
        rows = [
            dict(row)
            for row in db.execute(
                "SELECT id,provider,account_type,secret_ref,active "
                "FROM connections WHERE active=1"
            )
        ]
    if any(row['provider'] not in expected for row in rows):
        raise DomainError('production_connection_topology_invalid', next_action='contact_owner')
    selected = {}
    for provider, (account_type, secret_ref) in expected.items():
        provider_rows = [row for row in rows if row["provider"] == provider]
        matches = [
            row
            for row in provider_rows
            if row["account_type"] == account_type and row["secret_ref"] == secret_ref
        ]
        if len(matches) != 1 or len(provider_rows) != 1:
            raise DomainError(
                "production_connection_topology_invalid",
                next_action="contact_owner",
            )
        selected[provider] = matches[0]["id"]
    return selected


async def run(
    db: Path,
    telegram_env_file: Path,
    vk_env_file: Path | None,
    *,
    vk_token_key: str,
    codex_task_artifacts: Path | None = None,
    once: bool = False,
    telegram_only: bool = False,
    providers: tuple[str, ...] | None = None,
    telegram_session_key: str = "VIBE_PUBLISH_TG_SESSION",
    telegram_api_id_key: str = "TG_API_ID",
    telegram_api_hash_key: str = "TG_API_HASH",
):
    store = Store(db)
    selected = production_connections(store, telegram_only=telegram_only, providers=providers)
    bundles = {
        TG_REFERENCE: json.dumps(telegram_credentials(
            telegram_env_file, session_key=telegram_session_key,
            api_id_key=telegram_api_id_key, api_hash_key=telegram_api_hash_key)),
    }
    if 'vk' in selected:
        if vk_env_file is None or not vk_token_key:
            raise DomainError('approved_vk_configuration_missing')
        bundles[VK_REFERENCE] = json.dumps(vk_credentials(vk_env_file, vk_token_key))
    if 'max' in selected:
        max_profile = os.environ.get(MAX_REFERENCE)
        if not max_profile:
            raise DomainError("max_profile_config_missing")
        bundles[MAX_REFERENCE] = max_profile

    with exclusive_session_owner(db.parent / 'telegram-session.lock'):
        async with native_adapters(
            store,
            env=bundles,
            telegram_factory=telegram_factory,
        ) as wiring:
            imagegen = None
            if codex_task_artifacts is not None:
                from adapters.codex_task_imagegen import CodexTaskImagegen

                imagegen = CodexTaskImagegen(
                    codex_task_artifacts,
                    codex_home=Path("/home/dev/.codex"),
                )
            worker = Worker(store, wiring, imagegen=imagegen)
            try:
                while True:
                    worked = await worker.run_once()
                    if once:
                        return
                    if not worked:
                        await asyncio.sleep(0.25)
            finally:
                if imagegen is not None:
                    await imagegen.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--telegram-env-file", required=True, type=Path)
    parser.add_argument("--vk-env-file", type=Path)
    parser.add_argument("--vk-token-key", default="")
    topology = parser.add_mutually_exclusive_group()
    topology.add_argument("--telegram-only", action="store_true",
                        help="Explicit Telegram-only topology; rejects other active providers")
    topology.add_argument("--providers", nargs='+', choices=('telegram', 'vk', 'max'),
                          help="Exact provider topology; Telegram required; default all three")
    parser.add_argument("--telegram-session-key", default="VIBE_PUBLISH_TG_SESSION")
    parser.add_argument("--telegram-api-id-key", default="TG_API_ID")
    parser.add_argument("--telegram-api-hash-key", default="TG_API_HASH")
    parser.add_argument("--codex-task-artifacts", type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(
            run(
                args.db,
                args.telegram_env_file,
                args.vk_env_file,
                vk_token_key=args.vk_token_key,
                codex_task_artifacts=args.codex_task_artifacts,
                once=args.once,
                telegram_only=args.telegram_only,
                providers=tuple(args.providers) if args.providers is not None else None,
                telegram_session_key=args.telegram_session_key,
                telegram_api_id_key=args.telegram_api_id_key,
                telegram_api_hash_key=args.telegram_api_hash_key,
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error_type": type(exc).__name__,
                    "code": exc.code if isinstance(exc, DomainError) else "production_worker_failed",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
