"""Local owner administration and explicit offline wiring. No implicit live writes."""
from __future__ import annotations
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
from .domain import DomainError
from .storage import Store


def parser():
    p = argparse.ArgumentParser(prog='vibepublish')
    p.add_argument('--db', required=True, type=Path)
    sub = p.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('--tenant', required=True); init.add_argument('--principal', required=True)
    init.add_argument('--timezone', default='Europe/Kaliningrad')
    connect = sub.add_parser('connection'); connect.add_argument('--id', required=True)
    connect.add_argument('--provider', choices=('telegram','vk','max'), required=True)
    connect.add_argument('--shared', action='store_true'); connect.add_argument('--secret-ref', default='')
    connect.add_argument('--account-type', choices=('unconfigured','fake','mtproto_user','mtproto_bot','vk_user','vk_group'), default='unconfigured')
    bind = sub.add_parser('bind'); bind.add_argument('--principal', required=True); bind.add_argument('--alias', required=True)
    bind.add_argument('--connection', required=True); bind.add_argument('--native-id', required=True); bind.add_argument('--label', required=True)
    partner = sub.add_parser('principal'); partner.add_argument('--tenant', required=True); partner.add_argument('--principal', required=True)
    revoke = sub.add_parser('revoke'); revoke.add_argument('--binding-id', required=True)
    asset = sub.add_parser('image'); asset.add_argument('--file', required=True, type=Path); asset.add_argument('--mime', required=True)
    backup = sub.add_parser('backup'); backup.add_argument('--output', required=True, type=Path)
    serve = sub.add_parser('serve'); serve.add_argument('--port', type=int, default=8765)
    work = sub.add_parser('worker'); work.add_argument('--once', action='store_true'); work.add_argument('--fake-remote', type=Path)
    visual = work.add_mutually_exclusive_group()
    visual.add_argument('--fake-imagegen', type=Path, help='Explicit offline image fixture; forbidden with --native')
    visual.add_argument('--codex-imagegen-config', type=Path, help='Private operator-attested DevCoveer image-only Codex configuration; disabled by default')
    work.add_argument('--imagegen-artifacts', type=Path, help='Private local process artifact root; required with --codex-imagegen-config')
    work.add_argument('--native', action='store_true', help='Explicitly enable separately configured native provider connections')
    return p


def main():
    args = parser().parse_args()
    store = Store(args.db)
    try:
        if args.command == 'init':
            token = store.create_principal(args.tenant, args.principal, owner=True, timezone=args.timezone)
            print(json.dumps({'service_token': token, 'warning': 'Shown once. Store privately; never commit or send to a model.'}))
            return
        if args.command == 'serve':
            import uvicorn
            from .server import create_app
            uvicorn.run(create_app(store), host='127.0.0.1', port=args.port, access_log=False, log_level='warning')
            return
        if args.command == 'worker':
            from adapters.fake import FakeProvider
            from .worker import Worker
            adapters = {p: FakeProvider(args.fake_remote, p) for p in ('telegram','vk','max')} if args.fake_remote else {}
            if args.native and (args.fake_remote or args.fake_imagegen):
                raise DomainError('native_and_fake_wiring_are_exclusive')
            from adapters.imagegen import FakeImagegen
            imagegen = FakeImagegen(args.fake_imagegen) if args.fake_imagegen else None
            if bool(args.codex_imagegen_config) != bool(args.imagegen_artifacts):
                raise DomainError('codex_imagegen_config_and_artifacts_required')
            if args.codex_imagegen_config:
                from adapters.codex_imagegen import configured_codex
                imagegen = configured_codex(args.imagegen_artifacts, args.codex_imagegen_config)
            async def consume(wiring):
                worker = Worker(store, wiring, imagegen=imagegen)
                if args.once:
                    await worker.run_once()
                else:
                    while True:
                        if not await worker.run_once():
                            await asyncio.sleep(.25)  # Immediate-command backlog only, never send_at eligibility.
            async def run():
                if args.native:
                    from adapters.wiring import native_adapters
                    async with native_adapters(store) as wiring:
                        await consume(wiring)
                else:
                    await consume(adapters)
            asyncio.run(run())
            return
        token = os.environ.get('VIBEPUBLISH_SERVICE_TOKEN') or getpass.getpass('Owner service token: ')
        actor = store.authenticate(token)
        if not actor.owner:
            raise DomainError('owner_required')
        if args.command == 'connection':
            store.add_connection(actor, args.id, args.provider, account_type=args.account_type, secret_ref=args.secret_ref, shared=args.shared)
        elif args.command == 'bind':
            print(store.bind(actor, args.principal, args.alias, args.connection, args.native_id, label=args.label))
        elif args.command == 'principal':
            print(json.dumps({'service_token': store.create_principal(args.tenant, args.principal,
                scopes={'bootstrap','publish','publication.manage','visual','status','forward','destination.profile'})}))
        elif args.command == 'revoke':
            store.revoke_binding(actor, args.binding_id)
            print('Binding revoked. Existing provider-queued posts were NOT cancelled.')
        elif args.command == 'image':
            from .assets import import_image
            with args.file.open('rb') as source:
                data = source.read(20*1024*1024+1)
            print(import_image(store, actor, data, args.mime))
        elif args.command == 'backup':
            store.backup(args.output)
    except DomainError as exc:
        print(json.dumps(exc.output()))
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
