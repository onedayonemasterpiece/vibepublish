"""Loopback-only stand launcher with exact operator-selected public Host admission."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
from social_operations.server import create_app
from social_operations.storage import Store


def public_host(value: str) -> str:
    if not re.fullmatch(r'(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', value):
        raise argparse.ArgumentTypeError('Expected one lowercase DNS hostname, not a URL or wildcard')
    return value


def build_app(path: Path, host: str | None = None):
    hosts = ('127.0.0.1', 'localhost') + ((public_host(host),) if host else ())
    return create_app(Store(path), allowed_hosts=hosts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--public-host', type=public_host)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(build_app(args.db, args.public_host), host='127.0.0.1', port=args.port,
                proxy_headers=False, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
