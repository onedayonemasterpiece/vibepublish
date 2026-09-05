"""Explicit existing-profile ownership for MAX. No QR/auth bootstrap or CDP scan.

Acquires the existing bridge's exclusive-create lock protocol (observed on the
host) AND ProfileLane AND Chromium's own SingletonLock. Does not reclaim locks,
copy sessions, kill existing owners, or close tabs in another running browser.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import uuid

from playwright.async_api import async_playwright
from .live import RealMaxDriver, Target
from .profile import ProfileLane, MaxBlocked


def private_json(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise MaxBlocked('unsafe_binding_path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
            raise MaxBlocked('unsafe_binding_permissions')
        with os.fdopen(fd, closefd=False) as stream:
            return json.load(stream)
    finally:
        os.close(fd)


@asynccontextmanager
async def existing_session(*, profile, executable, allowlist, explicit_live=False, timeout=30):
    if explicit_live is not True:
        raise MaxBlocked('explicit_live_required')
    profile = Path(profile).absolute()
    # Not onboarding: refuse an absent/empty browser profile.
    if (profile/'Default').is_symlink() or not (profile/'Default').is_dir():
        raise MaxBlocked('existing_profile_required')
    binding = private_json(allowlist)
    phone = binding['account_phone']
    if not isinstance(phone, str) or not phone.strip():
        raise MaxBlocked('account_binding_required')
    targets = tuple(Target(k, v['alias'], v['policy']) for k,v in binding['targets'].items())
    with ProfileLane(profile) as lane:
        lock = profile/'.my-browser-bridge.lock'
        token = 'vibepublish-' + uuid.uuid4().hex
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise MaxBlocked('browser_owner_busy') from None
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump(dict(pid=os.getpid(), sessionId=token, createdAt=datetime.now(timezone.utc).isoformat()), out)
                out.flush()
                os.fsync(out.fileno())
            async with async_playwright() as pw:
                try:
                    context = await pw.chromium.launch_persistent_context(str(profile),
                        executable_path=str(executable), headless=True, locale='ru-RU', timezone_id='Europe/Moscow')
                except Exception:
                    raise MaxBlocked('existing_browser_unavailable') from None
                try:
                    # Only pages created by this session are navigated. Never
                    # inspect recovered tabs or profile storage to infer account.
                    page, identity_page = await context.new_page(), await context.new_page()
                    async def account_check():
                        await identity_page.goto('https://web.max.ru/', wait_until='domcontentloaded')
                        await identity_page.get_by_role('button',name='Настройки',exact=True).click(timeout=10000)
                        field = identity_page.locator('aside .phone')
                        await field.wait_for(timeout=10000)
                        return await field.inner_text() == phone
                    yield RealMaxDriver(page, lane, targets=targets, account_check=account_check, timeout=timeout)
                finally:
                    await context.close()
        finally:
            # Remove only this exact ownership record. Unknown replacement stays.
            try:
                if private_json(lock).get('sessionId') == token:
                    lock.unlink()
            except (OSError, ValueError, MaxBlocked):
                pass


async def _read_command(args):
    """Separate explicit live command. Ordinary pytest never loads host bindings."""
    from dataclasses import asdict
    output = Path(args.output).absolute()
    parent = output.parent
    if any(p.is_symlink() for p in (parent, *parent.parents)):
        raise MaxBlocked('unsafe_output_path')
    info = parent.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise MaxBlocked('private_output_directory_required')
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd,'w') as stream:
        async with existing_session(profile=args.profile, executable=args.executable,
                                    allowlist=args.allowlist, explicit_live=args.live_read) as driver:
            for target in driver.targets:
                for namespace in ('feed','scheduled'):
                    try:
                        value = asdict(await driver.visible(target, namespace))
                    except MaxBlocked as exc:
                        value = dict(target=target, namespace=namespace, blocked=str(exc))
                    stream.write(json.dumps(value, ensure_ascii=False)+'\n')
                    stream.flush()
                    os.fsync(stream.fileno())


if __name__ == '__main__':
    import argparse
    import asyncio
    parser=argparse.ArgumentParser(description='Explicit MAX read-only probe; no login, submit or provider API')
    parser.add_argument('--live-read', action='store_true', required=True)
    for name in ('profile','executable','allowlist','output'):
        parser.add_argument('--'+name, required=True)
    try:
        asyncio.run(_read_command(parser.parse_args()))
    except MaxBlocked as exc:
        parser.exit(2, 'MAX blocked: '+str(exc)+'\n')
