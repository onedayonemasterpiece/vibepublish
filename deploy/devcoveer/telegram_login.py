"""Explicit owner QR login for a new dedicated VibePublish Telegram session.

Never loads another product's session. Writes credentials exclusively to a
private env file; stdout contains status words only. QR output is sensitive.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shlex
import time

from dotenv import dotenv_values
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


def private_write(path: Path, data: bytes, *, exclusive: bool = False):
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


async def login(args):
    import io
    import qrcode

    os.umask(0o077)
    if args.output.exists() or args.output.is_symlink():
        raise RuntimeError('credential_output_already_exists')
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.qr.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    values = dotenv_values(args.api_env)
    api_id = int(values['TELEGRAM_API_ID'])
    api_hash = values['TELEGRAM_API_HASH']
    client = TelegramClient(StringSession(), api_id, api_hash,
                            device_model='DevCoveer2 VibePublish',
                            app_version='recovery', connection_retries=1,
                            request_retries=0, flood_sleep_threshold=0)
    try:
        await client.connect()
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            qr = await client.qr_login()
            waiting = asyncio.create_task(qr.wait())
            try:
                # Register the event listener before exposing the QR.
                await asyncio.sleep(0)
                buffer = io.BytesIO()
                qrcode.make(qr.url).save(buffer, format='PNG')
                private_write(args.qr, buffer.getvalue())
                print('QR_READY', flush=True)
                await asyncio.wait_for(waiting, max(1, deadline-time.monotonic()))
                break
            except asyncio.TimeoutError:
                continue
            except SessionPasswordNeededError:
                print('TWO_FACTOR_PASSWORD_REQUIRED', flush=True)
                while not args.password_file.is_file():
                    if time.monotonic() >= deadline:
                        raise TimeoutError('owner_login_expired')
                    await asyncio.sleep(1)
                if args.password_file.is_symlink() or args.password_file.stat().st_mode & 0o077:
                    raise RuntimeError('password_file_must_be_private')
                password = args.password_file.read_text().rstrip('\r\n')
                await client.sign_in(password=password)
                del password
                break
            finally:
                if not waiting.done():
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
        else:
            raise TimeoutError('owner_login_expired')
        if not await client.is_user_authorized():
            raise RuntimeError('session_not_authorized')
        bundle = json.dumps({'api_id': api_id, 'api_hash': api_hash,
                             'session': client.session.save()}, separators=(',', ':'))
        private_write(args.output,
                      ('VIBEPUBLISH_TELEGRAM_AUTH_BUNDLE='+shlex.quote(bundle)+'\n').encode(),
                      exclusive=True)
        print('AUTHORIZED_CREDENTIAL_SAVED', flush=True)
    finally:
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-env', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--qr', required=True, type=Path)
    parser.add_argument('--password-file', required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    try:
        asyncio.run(login(args))
    except Exception as exc:
        print('LOGIN_FAILED:'+type(exc).__name__, flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
