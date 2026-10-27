"""SQLite/WAL, short transactions, current authority and durable event cursors."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from .domain import Actor, DomainError, canonical, new_id, timestamp
from contracts.social_mcp_v1 import STAGE

ALL_SCOPES = frozenset({"bootstrap", "publish", "publication.manage", "visual", "status",
                        "engage", "destinations", "forward", "destination.profile"})
SERVICE_SCOPES = ALL_SCOPES | {"media.store"}
DEFAULT_BINDING_RIGHTS = ("publish", "edit", "reschedule", "cancel", "delete", "forward")
ALL_BINDING_RIGHTS = frozenset((*DEFAULT_BINDING_RIGHTS, "reply", "react", "basic_group_schedule"))


def _validated_permissions(values, allowed, error_code):
    """Reject malformed authority before credential generation or database writes."""
    if not isinstance(values, (list, tuple, set, frozenset)) or any(
            not isinstance(value, str) or value not in allowed for value in values):
        raise DomainError(error_code)
    return tuple(dict.fromkeys(values))


def _valid_media_topic_id(value) -> bool:
    """Canonical positive Telegram topic/message id, bounded before parsing."""
    return (isinstance(value, str) and 1 <= len(value) <= 19
            and value[0] in "123456789"
            and all("0" <= digit <= "9" for digit in value)
            and int(value) <= 9223372036854775807)


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
            if version not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
                raise RuntimeError("Unsupported VibePublish database version")
            self._enable_wal(db)
            if version == 0:
                db.executescript(Path(__file__).with_name("schema.sql").read_text())
            if version < 2:
                db.executescript(Path(__file__).with_name("visual_schema.sql").read_text())

            if version < 3:
                db.executescript(Path(__file__).with_name("emoji_schema.sql").read_text())

            if version < 4:
                db.executescript(Path(__file__).with_name("resolution_schema.sql").read_text())

            if version < 5:
                db.executescript(Path(__file__).with_name("recovery_schema.sql").read_text())
            if version < 6:
                db.executescript(Path(__file__).with_name("media_store_schema.sql").read_text())
            if version < 7:
                db.executescript(Path(__file__).with_name("telegram_media_budget_schema.sql").read_text())
            if version < 8:
                db.executescript(Path(__file__).with_name("workspace_upload_schema.sql").read_text())
            if version < 9:
                db.executescript(Path(__file__).with_name("vk_story_dependencies.sql").read_text())
            if version < 10:
                db.executescript(Path(__file__).with_name("media_service_topic_schema.sql").read_text())
            if version < 11:
                db.executescript(Path(__file__).with_name("media_entry_grant_schema.sql").read_text())

    @staticmethod
    def _enable_wal(db: sqlite3.Connection) -> None:
        """Converge concurrent Store initializers on WAL without masking other DB errors."""
        deadline = time.monotonic() + 5.0
        while True:
            try:
                mode = str(db.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
                if mode == "wal":
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Unable to enable SQLite WAL mode: {mode}")
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                    raise
            time.sleep(0.01)

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
            # busy_timeout handles ordinary short contention. If another local
            # VibePublish process still owns the writer lock after that wait,
            # retry only BEGIN IMMEDIATE. No transaction/provider effect exists
            # yet, so this is safe and prevents the worker process from dying.
            deadline = time.monotonic() + 15.0
            while True:
                try:
                    db.execute("BEGIN IMMEDIATE")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def create_principal(self, tenant: str, principal: str, *, owner=False,
                         scopes=ALL_SCOPES, timezone="Europe/Kaliningrad") -> str:
        """Local owner CLI only. No model-facing account administration method."""
        scopes = _validated_permissions(scopes, SERVICE_SCOPES, "invalid_principal_scopes")
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
             label="Test destination", handle="", rights=DEFAULT_BINDING_RIGHTS):
        if not owner.owner:
            raise DomainError("access_denied", next_action="contact_owner")
        rights = _validated_permissions(rights, ALL_BINDING_RIGHTS, "invalid_binding_rights")
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

    def grant_binding_rights(self, owner: Actor, binding_id: str, rights):
        """Owner-only additive grant; never revokes epochs or clears quarantine."""
        if not isinstance(rights, (list, tuple)) or not rights:
            raise DomainError('invalid_binding_rights')
        rights = _validated_permissions(rights, ALL_BINDING_RIGHTS, 'invalid_binding_rights')
        with self.tx() as db:
            return self._grant_binding_rights(db, owner, binding_id, rights)

    def _grant_binding_rights(self, db, owner: Actor, binding_id: str, rights):
        """Shared grant domain inside the caller's transaction and audit receipt."""
        if not isinstance(rights, (list, tuple)) or not rights:
            raise DomainError('invalid_binding_rights')
        rights = _validated_permissions(rights, ALL_BINDING_RIGHTS, 'invalid_binding_rights')
        if not owner.owner:
            raise DomainError('access_denied', next_action='contact_owner')
        owner = self.current(db, owner)
        row = db.execute(
            'SELECT * FROM bindings WHERE id=? AND tenant_id=? AND active=1',
            (binding_id, owner.tenant_id)).fetchone()
        if not owner.owner or not row:
            raise DomainError('access_denied', next_action='contact_owner')
        old = json.loads(row['rights'])
        updated = list(dict.fromkeys(old + list(rights)))
        if updated != old:
            db.execute('UPDATE bindings SET rights=? WHERE id=?', (canonical(updated), binding_id))
            db.execute('UPDATE principals SET routing_revision=routing_revision+1 WHERE id=?',
                       (row['principal_id'],))
        return updated

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
    def service_media_topic_allowed(self, db, actor: Actor, binding, topic_id: str) -> bool:
        """Authorize an exact Telegram topic for a service, never by URL alone."""
        if actor.owner:
            return True
        if "media.store" not in actor.scopes:
            return False
        if not _valid_media_topic_id(topic_id):
            return False
        return db.execute(
            "SELECT 1 FROM media_service_topic_grants "
            "WHERE tenant_id=? AND principal_id=? AND binding_id=? AND topic_id=?",
            (actor.tenant_id, actor.principal_id, binding["id"], topic_id)
        ).fetchone() is not None

    def set_service_media_topic(self, owner: Actor, principal: str, alias: str,
                                topic_id: str, *, enabled=True):
        """Local owner administration; no model-facing endpoint or credential return."""
        if not owner.owner or not _valid_media_topic_id(topic_id):
            raise DomainError("access_denied", next_action="contact_owner")
        with self.tx() as db:
            self.current(db, owner)
            target = db.execute(
                "SELECT scopes,owner FROM principals WHERE tenant_id=? AND id=? AND active=1",
                (owner.tenant_id, principal)
            ).fetchone()
            binding = db.execute(
                "SELECT b.id,b.rights,c.provider FROM bindings b "
                "JOIN destinations d ON d.id=b.destination_id "
                "JOIN connections c ON c.id=d.connection_id "
                "WHERE b.tenant_id=? AND b.principal_id=? AND b.alias=? "
                "AND b.active=1 AND c.active=1",
                (owner.tenant_id, principal, alias)
            ).fetchone()
            if (not target or target["owner"] or "media.store" not in json.loads(target["scopes"])
                    or not binding or binding["provider"] != "telegram"
                    or "publish" not in json.loads(binding["rights"])):
                raise DomainError("access_denied", next_action="contact_owner")
            if enabled:
                db.execute(
                    "INSERT OR IGNORE INTO media_service_topic_grants VALUES(?,?,?,?)",
                    (owner.tenant_id, principal, binding["id"], topic_id)
                )
            else:
                result = db.execute(
                    "DELETE FROM media_service_topic_grants "
                    "WHERE tenant_id=? AND principal_id=? AND binding_id=? AND topic_id=?",
                    (owner.tenant_id, principal, binding["id"], topic_id)
                )
                if result.rowcount:
                    # Invalidate old permission snapshots and pending operations.
                    db.execute("UPDATE principals SET epoch=epoch+1,"
                               "routing_revision=routing_revision+1 WHERE id=?", (principal,))
        return {"principal": principal, "alias": alias, "topic_id": topic_id,
                "enabled": bool(enabled)}

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

    def claim(self, worker: str, *, connection_ids=None, include_unrouted=True, operation_id=None):
        with self.tx() as db:
            now = self.clock()
            query="SELECT o.* FROM operations o WHERE (work_state='ready' OR (work_state='working' AND lease_until<?))"
            values=[now]
            if operation_id is not None:
                query += ' AND o.id=?'
                values.append(operation_id)
            if connection_ids is not None:
                marks=','.join('?' for _ in connection_ids)
                routed="(SELECT json_extract(a.plan,'$.connection_id') FROM attempts a WHERE a.operation_id=o.id LIMIT 1)"
                read="(SELECT d.connection_id FROM bindings b JOIN destinations d ON d.id=b.destination_id WHERE b.id=json_extract(o.request,'$._binding_id'))"
                # Exact discovery precedes destination/binding creation, but its
                # owner-admitted connection still belongs to one provider lane.
                destination="CASE WHEN o.action='destinations' THEN json_extract(o.request,'$._connection_id') END"
                route=f'coalesce({routed},{read},{destination})'
                query+=f' AND ({route} IN ({marks})'+(f' OR {route} IS NULL' if include_unrouted else '')+')'
                values.extend(connection_ids)
            row=db.execute(query+' ORDER BY created,id LIMIT 1',values).fetchone()
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
        actor = self.current(db, actor)
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
        request = json.loads(row['request'])
        if request.get('_media_store_grant_id'):
            from .media_entry_grants import require_grant
            require_grant(self, db, actor, request['_media_store_entry_ref'],
                          grant_id=request['_media_store_grant_id'],
                          binding_id=request['_binding_id'])
        # Administrative receipts never replay through revoked or replaced bindings.
        grant = json.loads(row['result']).get('binding_grant')
        if grant:
            if not actor.owner or not {'destinations', 'publication.manage'} <= actor.scopes:
                raise DomainError('access_denied', next_action='contact_owner')
            binding = self.binding(db, actor, binding_id=grant['binding_id'])
            if (binding['alias'] != grant['alias']
                    or binding['epoch'] != grant['after']['binding_epoch']
                    or 'edit' not in json.loads(binding['rights'])):
                raise DomainError('access_revoked', next_action='reauthorize')
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
        from .managed_item_edits import latest_attempts
        for child in latest_attempts(db, row):
            binding = self.binding(db, actor, binding_id=child["binding_id"])
            if binding["epoch"] != child["binding_epoch"]:
                raise DomainError("access_revoked", next_action="reauthorize")
        from .emojis import EmojiService
        from types import SimpleNamespace
        EmojiService(SimpleNamespace(store=self)).receipt_access(db, actor, row)
        return row

    def receipt(self, actor: Actor, ident: str, *, after: str | None = None, event_limit=50, brief=False):
        # Ordinary publication status is a read: no write lock or cursor row.
        with (self.connection() if brief else self.tx()) as db:
            op = self.private_operation(db, actor, ident)
            if not brief:
                seq = self.cursor_position(db, actor, after, "events", op["id"]) if after else 0
                rows = db.execute("SELECT seq,body FROM events WHERE operation_id=? AND seq>? ORDER BY seq LIMIT ?",
                                  (op["id"], seq, event_limit + 1)).fetchall()
                page = rows[:event_limit]
            deliveries = []
            from .managed_item_edits import latest_attempts
            for child in latest_attempts(db, op):
                result = {"destination": child["alias"], "provider": child["provider"], "attempt_id": child["id"], "state": child["state"],
                          "stage": child["stage"], "observed": child["observed"], "revision": child["target_revision"],
                          "media_check": "not_applicable", "retry_safe": False}
                result.update(json.loads(child["result"]))
                if op["publication_id"]:
                    result.update(applied_revision=child["applied_revision"],
                                  desired_revision=child["desired_revision"], sync_status=child["sync_status"])
                if child['observed'] in ('cancelled', 'deleted'):
                    # Terminal removal: strip queue ownership metadata but
                    # preserve effective_at as historical schedule evidence.
                    for key in ('queue_ref', 'scheduling_owner', 'navigate_hint'):
                        result.pop(key, None)
                    result.pop('requested_at', None)
                else:
                    # Legacy cancel receipts persisted an absent optional timestamp as
                    # null. Project it as absent without rewriting durable evidence.
                    if result.get("requested_at") is None:
                        result.pop("requested_at", None)
                deliveries.append(result)
            if brief:
                outcomes = []
                delivered = 0
                operation_result = json.loads(op["result"])
                for item in deliveries:
                    success = item["observed"] in ("published", "provider_scheduled", "edited", "reacted")
                    state = "готово" if success else "отказ" if op["complete"] else "выполняется"
                    view = {"destination": item["destination"], "provider": item["provider"], "status": state}
                    if success:
                        delivered += 1
                        for key in ("url", "queue_ref", "item_ref"):
                            if item.get(key):
                                view[key] = item[key]
                        if not view.get("url") and str(item.get("navigate_hint", "")).startswith("https://"):
                            view["url"] = item["navigate_hint"]
                        if not any(key in view for key in ("url", "queue_ref", "item_ref")):
                            view["reason"] = "Сеть подтвердила публикацию без прямой ссылки"
                    elif state == "выполняется":
                        next_at = (item.get("next_attempt_at") or item.get("media_budget_retry_at")
                                   or (operation_result.get("vk_completion_retry_at") if item["provider"] == "vk" else None))
                        if isinstance(next_at, str):
                            view["next_attempt_at"] = next_at
                            try:
                                view["next_attempt_time"] = datetime.fromisoformat(
                                    next_at.replace("Z", "+00:00")
                                ).astimezone(ZoneInfo(actor.timezone)).strftime("%H:%M")
                            except (ValueError, KeyError):
                                pass
                    else:
                        reason = item.get("reason") or next(iter(item.get("missing_checks") or ()), None)
                        reasons = {"needs_auth": "Нет действующей авторизации сети",
                                   "access_revoked": "Нет прав на публикацию",
                                   "command_expired": "Истекло время отправки",
                                   "vk_upload_failed": "Не удалось загрузить изображение"}
                        view["reason"] = (reasons.get(reason, reason.replace("_", " ")[:200])
                                          if isinstance(reason, str) and "review" not in reason
                                          and "unknown" not in reason
                                          else "Сеть не смогла доставить публикацию")
                    outcomes.append(view)
                count = len(outcomes)
                if not op["complete"]:
                    overall = "выполняется"
                elif count and delivered == count:
                    overall = "доставлено во все сети"
                elif delivered:
                    overall = f"доставлено в {delivered} из {count}"
                else:
                    overall = "не доставлено"
                snapshot = {"operation_id": op["id"], "revision": op["revision"],
                            "action": op["action"], "state": op["state"] if op["state"] != "outcome_unknown" else "blocked",
                            "operation_complete": bool(op["complete"]), "deliveries": deliveries,
                            "summary": {"result": overall, "networks": outcomes}}
                if op["publication_id"]:
                    snapshot["resource_id"] = op["publication_id"]
                if operation_result.get("review_token"):
                    snapshot["review_token"] = operation_result["review_token"]
                dependency = db.execute(
                    "SELECT id,state,reason,event_status,child_operation_id,expires "
                    "FROM vk_story_dependencies WHERE parent_attempt_id IN "
                    "(SELECT id FROM attempts WHERE operation_id=?)", (op["id"],)
                ).fetchone()
                if dependency:
                    snapshot["linked_story"] = dict(dependency)
                if op["error"] and op["state"] != "outcome_unknown":
                    snapshot["error"] = json.loads(op["error"])["error"]
                return snapshot
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
            dependency = db.execute("SELECT id,state,reason,event_status,child_operation_id,expires FROM vk_story_dependencies WHERE parent_attempt_id IN (SELECT id FROM attempts WHERE operation_id=?)", (op['id'],)).fetchone()
            if dependency:
                result['linked_story'] = dict(dependency)
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
