#!/usr/bin/env python3
"""One-time local M2M archive admission; never output machine credential."""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import stat
import tempfile
from pathlib import Path
from social_operations.storage import Store

DB = Path("/home/dev/.local/state/vibepublish/vibepublish.sqlite3")
GRANT = Path("/home/dev/.local/state/regional-knowledge-base/vibepublish-mirror-grant.json")
OWNER = "recovery-owner-20260919"
CONNECTION = "devcoveer2-knowledge-base"
PRINCIPAL = "regional-knowledge-archive-service"
ALIAS = "regional_knowledge_archive"
PEER = "-1004368830579"
ISSUER = "https://mcp-vibepublish.kenigevents.ru"
LOOPBACK = "http://127.0.0.1:18765"
THREAD_SOURCE = "https://t.me/c/4368830579/2"
THREAD_IMAGES = "https://t.me/c/4368830579/4"


def _check_file(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("RKB private grant file missing or unsafe")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise RuntimeError("RKB grant file must be 0600")
    grant = json.loads(path.read_text())
    if (grant.get("issuer") != ISSUER or grant.get("rkb_owner_id") is None
            or grant.get("destination_alias") != ALIAS
            or grant.get("source_thread_ref") != THREAD_SOURCE
            or grant.get("thread_ref") != THREAD_IMAGES):
        raise RuntimeError("RKB grant metadata differs from frozen archive contract")
    return grant


def _preflight(grant: dict) -> tuple[str, bool]:
    # Read-only PRAGMA first: opening Store must not silently upgrade an old
    # ledger before its server and worker are deployed to version 11.
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != 11:
            raise RuntimeError("VibePublish schema v11 not active; do not provision")
        row = db.execute(
            "SELECT p.tenant_id,p.active,t.active "
            "FROM principals p JOIN tenants t ON t.id=p.tenant_id "
            "WHERE p.id=? AND p.owner=1", (OWNER,)).fetchone()
        if not row or not row[1] or not row[2]:
            raise RuntimeError("registered current operator owner missing")
        tenant = row[0]
        candidates = db.execute(
            "SELECT c.id FROM connections c JOIN destinations d ON d.connection_id=c.id "
            "WHERE c.id=? AND c.provider='telegram' AND c.active=1 AND d.native_id=?",
            (CONNECTION, PEER)
        ).fetchall()
        if len(candidates) != 1:
            raise RuntimeError("dedicated knowledge-base Telegram connection missing")
        existing = db.execute(
            "SELECT 1 FROM principals WHERE id=?", (PRINCIPAL,)).fetchone()
        if existing and grant.get("auth_mode") != "local_service":
            raise RuntimeError("service principal exists but grant migration incomplete; inspect safely")
        return tenant, bool(existing)


def _atomic_private(path: Path, value: dict) -> None:
    if path.is_symlink():
        raise RuntimeError("unsafe symlink")
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + ".")
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as fp:
            fp.write(json.dumps(value, ensure_ascii=False))
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    grant = _check_file(GRANT)
    tenant, existing = _preflight(grant)
    if grant.get("auth_mode") == "local_service":
        store = Store(DB)
        actor = store.authenticate(grant["service_token"])
        if (actor.principal_id != PRINCIPAL or actor.owner
                or actor.scopes != frozenset({"bootstrap", "status", "media.store"})):
            raise RuntimeError("active service identity is not the expected narrow principal")
        print({"state": "already_provisioned", "secret_printed": False})
        return 0
    if existing:
        raise RuntimeError("service grant requires manual recovery of existing principal")
    if not args.apply:
        print({"state": "ready_for_apply", "scope": "kb_topics_2_4",
               "secret_printed": False})
        return 0
    store = Store(DB)
    with store.connection() as db:
        row = db.execute(
            "SELECT p.*,t.timezone FROM principals p JOIN tenants t ON t.id=p.tenant_id "
            "WHERE p.id=? AND p.tenant_id=? AND p.owner=1 AND p.active=1",
            (OWNER, tenant)
        ).fetchone()
        if row is None:
            raise RuntimeError("owner admission has changed")
        actor = store.actor_row(row)
        store.current(db, actor)
    token = store.create_principal(tenant, PRINCIPAL,
                                   scopes={"bootstrap", "status", "media.store"})
    store.bind(actor, PRINCIPAL, ALIAS, CONNECTION, PEER,
               label="Regional Knowledge archive service", rights=("publish",))
    store.set_service_media_topic(actor, PRINCIPAL, ALIAS, "2")
    store.set_service_media_topic(actor, PRINCIPAL, ALIAS, "4")
    sanitized = {k: v for k, v in grant.items()
                 if k not in {"access_token", "refresh_token", "expires_at", "service_token"}}
    sanitized.update(auth_mode="local_service", local_endpoint=LOOPBACK,
                     service_token=token, client_id=PRINCIPAL)
    _atomic_private(GRANT, sanitized)
    print({"state": "provisioned", "principal": PRINCIPAL,
           "scoped_topics": [2, 4], "secret_printed": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
