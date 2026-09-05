"""SQLite/WAL, short transactions, current authority and durable event cursors."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from .domain import Actor, DomainError, canonical, new_id, timestamp
from contracts.social_mcp_v1 import STAGE

ALL_SCOPES = frozenset({"bootstrap", "publish", "publication.manage", "visual", "status",
                        "engage", "destinations", "forward", "destination.profile"})


class Store:
    def __init__(self, path: str | Path, *, clock=time.time):
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock = clock
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise RuntimeError("Unsupported VibePublish database version")
            db.execute("PRAGMA journal_mode=WAL")
            if version == 0:
                db.executescript(Path(__file__).with_name("schema.sql").read_text())
            if version < 2:
                db.executescript(Path(__file__).with_name("visual_schema.sql").read_text())

            if version < 3:
                db.executescript(Path(__file__).with_name("emoji_schema.sql").read_text())

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def create_principal(self, tenant: str, principal: str, *, owner=False,
                         scopes=ALL_SCOPES, timezone="Europe/Kaliningrad") -> str:
        """Local owner CLI only. No model-facing account administration method."""
        ZoneInfo(timezone)
        token = secrets.token_urlsafe(32)
        with self.tx() as db:
            db.execute("INSERT OR IGNORE INTO tenants(id,timezone) VALUES(?,?)", (tenant, timezone))
            db.execute("INSERT INTO principals(id,tenant_id,token_hash,scopes,owner) VALUES(?,?,?,?,?)",
                       (principal, tenant, self.token_hash(token), canonical(sorted(scopes)), int(owner)))
        return token

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def authenticate(self, token: str) -> Actor:
        if not isinstance(token, str) or not 20 <= len(token) <= 512:
            raise DomainError("unauthorized", "A valid service token is required", "reauthorize")
        with self.connection() as db:
            row = db.execute("SELECT p.*,t.timezone,t.active AS tenant_active FROM principals p "
                             "JOIN tenants t ON t.id=p.tenant_id WHERE token_hash=?", (self.token_hash(token),)).fetchone()
            if not row or not row["active"] or not row["tenant_active"]:
                raise DomainError("unauthorized", "A valid service token is required", "reauthorize")
            return self.actor_row(row)

    @staticmethod
    def actor_row(row) -> Actor:
        return Actor(row["tenant_id"], row["id"], row["epoch"], bool(row["owner"]),
                     frozenset(json.loads(row["scopes"])), row["routing_revision"], row["timezone"])

    def current(self, db, actor: Actor) -> Actor:
        row = db.execute("SELECT p.*,t.timezone,t.active AS tenant_active FROM principals p "
                         "JOIN tenants t ON t.id=p.tenant_id WHERE p.id=? AND p.tenant_id=?",
                         (actor.principal_id, actor.tenant_id)).fetchone()
        if not row or not row["active"] or not row["tenant_active"] or row["epoch"] != actor.epoch:
            raise DomainError("access_revoked", "Current authorization is required", "reauthorize")
        return self.actor_row(row)

    def operation_actor(self, operation) -> Actor:
        with self.connection() as db:
            row = db.execute("SELECT p.*,t.timezone FROM principals p JOIN tenants t ON t.id=p.tenant_id "
                             "WHERE p.id=? AND p.tenant_id=?", (operation["principal_id"], operation["tenant_id"])).fetchone()
            if not row:
                raise DomainError("access_denied", next_action="contact_owner")
            actor = self.actor_row(row)
            if actor.epoch != operation["actor_epoch"]:
                raise DomainError("access_revoked", next_action="reauthorize")
            return self.current(db, actor)

    def add_connection(self, owner: Actor, connection: str, provider: str, *, account_type="unconfigured",
                       secret_ref="", shared=False):
        if not owner.owner or (secret_ref and not secret_ref.startswith("VIBEPUBLISH_")):
            raise DomainError("access_denied", next_action="contact_owner")
        with self.tx() as db:
            self.current(db, owner)
            db.execute("INSERT INTO connections(id,tenant_id,provider,account_type,secret_ref,shared) VALUES(?,?,?,?,?,?)",
                       (connection, owner.tenant_id, provider, account_type, secret_ref, int(shared)))

    def bind(self, owner: Actor, principal: str, alias: str, connection: str, native_id: str, *,
             label="Test destination", handle="", rights=("publish", "edit", "reschedule", "cancel", "delete", "forward")):
        if not owner.owner:
            raise DomainError("access_denied", next_action="contact_owner")
        import re
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", alias):
            raise DomainError("invalid_alias")
        with self.tx() as db:
            self.current(db, owner)
            target = db.execute("SELECT * FROM principals WHERE id=?", (principal,)).fetchone()
            conn = db.execute("SELECT * FROM connections WHERE id=? AND tenant_id=?", (connection, owner.tenant_id)).fetchone()
            if not target or not conn or (target["tenant_id"] != conn["tenant_id"] and not conn["shared"]):
                raise DomainError("access_denied", next_action="contact_owner")
            if db.execute("SELECT 1 FROM destination_sets WHERE principal_id=? AND alias=?", (principal, alias)).fetchone():
                raise DomainError("alias_conflict")
            dest = db.execute("SELECT id FROM destinations WHERE connection_id=? AND native_id=?", (connection, native_id)).fetchone()
            dest_id = dest[0] if dest else new_id("dest")
            if not dest:
                db.execute("INSERT INTO destinations VALUES(?,?,?,?,?)", (dest_id, connection, native_id, handle, label))
            binding_id = new_id("bind")
            db.execute("INSERT INTO bindings(id,tenant_id,principal_id,alias,destination_id,rights) VALUES(?,?,?,?,?,?)",
                       (binding_id, target["tenant_id"], principal, alias, dest_id, canonical(list(rights))))
            db.execute("UPDATE principals SET routing_revision=routing_revision+1 WHERE id=?", (principal,))
        return binding_id

    def revoke_binding(self, owner: Actor, binding_id: str):
        with self.tx() as db:
            self.current(db, owner)
            row = db.execute("SELECT b.* FROM bindings b JOIN destinations d ON d.id=b.destination_id "
                             "JOIN connections c ON c.id=d.connection_id WHERE b.id=? AND c.tenant_id=?",
                             (binding_id, owner.tenant_id)).fetchone()
            if not owner.owner or not row:
                raise DomainError("access_denied", next_action="contact_owner")
            db.execute("UPDATE bindings SET active=0,epoch=epoch+1 WHERE id=?", (binding_id,))
            db.execute("UPDATE principals SET epoch=epoch+1,routing_revision=routing_revision+1 WHERE id=?", (row["principal_id"],))
            # Revocation never silently cancels already-native scheduled posts.

    def binding(self, db, actor: Actor, *, alias: str | None = None, binding_id: str | None = None):
        self.current(db, actor)
        rows = self.bindings(db, actor)
        row = next((r for r in rows if (alias is not None and r["alias"] == alias)
                    or (binding_id is not None and r["id"] == binding_id)), None)
        if not row:
            raise DomainError("access_denied", "Destination is not available", "contact_owner")
        return row

    def bindings(self, db, actor: Actor):
        return db.execute("SELECT b.*,d.native_id,d.handle,d.label,d.connection_id,c.provider,c.account_type,c.secret_ref "
                          "FROM bindings b JOIN destinations d ON d.id=b.destination_id JOIN connections c ON c.id=d.connection_id "
                          "WHERE b.tenant_id=? AND b.principal_id=? AND b.active=1 AND c.active=1",
                          (actor.tenant_id, actor.principal_id)).fetchall()

    def event(self, db, operation_id: str, stage: str, status: str, message: str, alias: str | None = None):
        if stage not in STAGE["enum"] or status not in {"started", "completed", "failed", "blocked", "unknown"}:
            raise DomainError("invalid_progress_event")
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE operation_id=?", (operation_id,)).fetchone()[0]
        body = {"operation_id": operation_id, "seq": seq, "at": timestamp(self.clock()),
                "stage": stage, "status": status, "message": message[:1000]}
        if alias:
            body["destination"] = alias
        db.execute("INSERT INTO events VALUES(?,?,?)", (operation_id, seq, canonical(body)))

    def fence(self, db, operation_id: str, worker: str, fence: int):
        row = db.execute("SELECT * FROM operations WHERE id=? AND lease_owner=? AND fence=?",
                         (operation_id, worker, fence)).fetchone()
        if not row:
            raise DomainError("stale_worker", next_action="refresh")
        return row

    def claim(self, worker: str):
        with self.tx() as db:
            now = self.clock()
            row = db.execute("SELECT * FROM operations WHERE work_state='ready' OR "
                             "(work_state='working' AND lease_until<?) ORDER BY created,id LIMIT 1", (now,)).fetchone()
            if not row:
                return None
            db.execute("UPDATE operations SET work_state='working',state='running',lease_owner=?,"
                       "fence=fence+1,lease_until=?,worker_seen=? WHERE id=?",
                       (worker, now + 30, now, row["id"]))
            self.event(db, row["id"], "validating", "started", "Worker claimed the immediate command")
            return dict(db.execute("SELECT * FROM operations WHERE id=?", (row["id"],)).fetchone())

    def cursor(self, db, actor: Actor, kind: str, scope: str, position) -> str:
        ident = new_id("cursor")
        db.execute("INSERT INTO cursors VALUES(?,?,?,?,?,?,?,?)",
                   (ident, actor.tenant_id, actor.principal_id, actor.epoch, kind, scope, canonical(position), self.clock() + 86400))
        return ident

    def cursor_position(self, db, actor: Actor, token: str, kind: str, scope: str):
        self.current(db, actor)
        row = db.execute("SELECT * FROM cursors WHERE id=? AND tenant_id=? AND principal_id=? AND epoch=? AND kind=? AND scope=?",
                         (token, actor.tenant_id, actor.principal_id, actor.epoch, kind, scope)).fetchone()
        if not row or row["expires"] < self.clock():
            raise DomainError("cursor_invalid", "Refresh the authorized view; cursor is invalid or expired", "refresh")
        return json.loads(row["position"])

    def private_operation(self, db, actor: Actor, ident: str):
        self.current(db, actor)
        if ident.startswith('visual_'):
            visual = db.execute('SELECT operation_id FROM visual_jobs WHERE id=? AND tenant_id=? AND principal_id=?',
                                (ident, actor.tenant_id, actor.principal_id)).fetchone()
            if not visual:
                raise DomainError('not_found', next_action='refresh')
            ident = visual[0]
        row = db.execute("SELECT * FROM operations WHERE tenant_id=? AND principal_id=? AND "
                         "(id=? OR publication_id=?) ORDER BY created DESC,rowid DESC LIMIT 1",
                         (actor.tenant_id, actor.principal_id, ident, ident)).fetchone()
        if not row:
            raise DomainError("not_found", "Resource is not available", "refresh")
        if row["actor_epoch"] != actor.epoch:
            raise DomainError("access_revoked", next_action="reauthorize")
        # A pending inline visual has no provider attempts yet, but still binds access.
        visual = db.execute('SELECT plans,actor_epoch FROM visual_jobs WHERE operation_id=?', (row['id'],)).fetchone()
        if visual:
            if visual['actor_epoch'] != actor.epoch:
                raise DomainError('access_revoked', next_action='reauthorize')
            for plan in json.loads(visual['plans']):
                binding = self.binding(db, actor, binding_id=plan['binding_id'])
                if binding['epoch'] != plan['binding_epoch']:
                    raise DomainError('access_revoked', next_action='reauthorize')
        # Every status/cache read rechecks current channel access, including old epochs.
        for child in db.execute("SELECT * FROM attempts WHERE operation_id=?", (row["id"],)):
            binding = self.binding(db, actor, binding_id=child["binding_id"])
            if binding["epoch"] != child["binding_epoch"]:
                raise DomainError("access_revoked", next_action="reauthorize")
        from .emojis import EmojiService
        from types import SimpleNamespace
        EmojiService(SimpleNamespace(store=self)).receipt_access(db, actor, row)
        return row

    def receipt(self, actor: Actor, ident: str, *, after: str | None = None, event_limit=50):
        with self.tx() as db:
            op = self.private_operation(db, actor, ident)
            seq = self.cursor_position(db, actor, after, "events", op["id"]) if after else 0
            rows = db.execute("SELECT seq,body FROM events WHERE operation_id=? AND seq>? ORDER BY seq LIMIT ?",
                              (op["id"], seq, event_limit + 1)).fetchall()
            page = rows[:event_limit]
            deliveries = []
            for child in db.execute("SELECT * FROM attempts WHERE operation_id=? ORDER BY rowid", (op["id"],)):
                result = {"destination": child["alias"], "provider": child["provider"], "state": child["state"],
                          "stage": child["stage"], "observed": child["observed"], "revision": op["revision"],
                          "media_check": "not_applicable", "retry_safe": False}
                result.update(json.loads(child["result"]))
                # Legacy cancel receipts persisted an absent optional timestamp as
                # null. Project it as absent without rewriting durable evidence.
                if result.get("requested_at") is None:
                    result.pop("requested_at", None)
                deliveries.append(result)
            state = op["state"]
            next_action = ("review_outcome" if state == "outcome_unknown" else "approve" if state == "needs_approval"
                           else "select_visual" if state == "needs_selection" else "none" if op["complete"] else "check_status")
            result = {"operation_id": op["id"], "revision": op["revision"], "action": op["action"], "state": state,
                      "message": "Command " + state.replace("_", " "), "operation_complete": bool(op["complete"]),
                      "progress": {"events": [json.loads(r["body"]) for r in page],
                                   "cursor": self.cursor(db, actor, "events", op["id"], page[-1]["seq"] if page else seq),
                                   "has_more": len(rows) > event_limit},
                      "next_action": next_action, "retry_safe": False, "receipt_ref": "receipt_" + op["id"],
                      "deliveries": deliveries}
            if op["publication_id"]:
                result["resource_id"] = op["publication_id"]
            if op["worker_seen"]:
                result["worker_seen_at"] = timestamp(op["worker_seen"])
            result.update(json.loads(op["result"]))
            if op["error"]:
                error = json.loads(op["error"])
                result["error"] = error["error"]
                result["next_action"] = "review_outcome" if state == "outcome_unknown" else error["next_action"]
            return result

    def backup(self, path: str | Path):
        """Consistent SQLite backup, including committed WAL pages."""
        path = Path(path).absolute()
        if path == self.path or path.exists():
            raise DomainError("backup_target_exists")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        with self.connection() as source:
            target = sqlite3.connect(path)
            try:
                source.backup(target)
                target.execute("UPDATE settings SET value='1' WHERE key='restore_guard'")
                target.commit()
            finally:
                target.close()
        os.chmod(path, 0o600)
