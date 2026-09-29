"""Owner-only provider-verified destination registration; no Telegram write/join."""
from __future__ import annotations

import asyncio
import json

from .domain import DomainError, canonical, digest, new_id


def admit(app, db, actor, command, intent):
    if not actor.owner:
        raise DomainError("access_denied", next_action="contact_owner")
    if command["provider"] != "telegram":
        raise DomainError("capability_not_implemented", next_action="contact_owner")
    from adapters.telegram_discovery import parse_destination_url
    parse_destination_url(command["url"])
    connections = db.execute(
        "SELECT id FROM connections WHERE tenant_id=? AND provider='telegram' "
        "AND account_type='mtproto_user' AND active=1", (actor.tenant_id,)).fetchall()
    if len(connections) != 1:
        raise DomainError("telegram_discovery_connection_ambiguous", next_action="contact_owner")
    request = dict(intent, _connection_id=connections[0]["id"])
    return app._new_operation(db, actor, "destinations", request)


async def process(worker, op, actor):
    from adapters.telegram_discovery import resolve
    args = json.loads(op["request"])
    connection_id = args["_connection_id"]
    with worker.store.connection() as db:
        actor = worker.store.current(db, actor)
        if not actor.owner:
            raise DomainError("access_denied", next_action="contact_owner")
        connection = db.execute(
            "SELECT * FROM connections WHERE id=? AND tenant_id=? AND active=1",
            (connection_id, actor.tenant_id)).fetchone()
        if not connection or connection["provider"] != "telegram" or connection["account_type"] != "mtproto_user":
            raise DomainError("access_revoked", next_action="reauthorize")
    await worker.hooks(op).emit_progress("accepted", "started", "Checking exact Telegram destination membership and send permission")
    budget = min(30, op["deadline"] - worker.store.clock())
    if budget <= 0:
        raise DomainError("command_expired")
    async with worker.lane(connection_id):
        try:
            async with asyncio.timeout(budget):
                evidence = await resolve(worker.adapter("telegram", connection_id), args["command"]["url"])
        except TimeoutError:
            raise DomainError("provider_read_deadline", next_action="refresh") from None
    with worker.store.tx() as db:
        worker.store.fence(db, op["id"], worker.id, op["fence"])
        worker.store.current(db, actor)
        if not db.execute("SELECT 1 FROM connections WHERE id=? AND tenant_id=? AND active=1",
                          (connection_id, actor.tenant_id)).fetchone():
            raise DomainError("access_revoked", next_action="reauthorize")
        destination = db.execute("SELECT * FROM destinations WHERE connection_id=? AND native_id=?",
                                 (connection_id, evidence["native_id"])).fetchone()
        dest_id = destination["id"] if destination else new_id("dest")
        binding = db.execute("SELECT * FROM bindings WHERE principal_id=? AND destination_id=?",
                             (actor.principal_id, dest_id)).fetchone()
        if binding and not binding["active"]:
            raise DomainError("access_revoked", next_action="reauthorize")
        if binding and "publish" not in json.loads(binding["rights"]):
            raise DomainError("access_denied", next_action="contact_owner")
        if not destination:
            db.execute("INSERT INTO destinations VALUES(?,?,?,?,?)",
                       (dest_id, connection_id, evidence["native_id"], evidence["handle"], evidence["label"]))
        if not binding:
            alias = "tg_" + digest([connection_id, evidence["native_id"]])[:20]
            if (db.execute("SELECT 1 FROM bindings WHERE principal_id=? AND alias=?", (actor.principal_id, alias)).fetchone()
                    or db.execute("SELECT 1 FROM destination_sets WHERE principal_id=? AND alias=?", (actor.principal_id, alias)).fetchone()):
                raise DomainError("alias_conflict")
            db.execute("INSERT INTO bindings(id,tenant_id,principal_id,alias,destination_id,rights) VALUES(?,?,?,?,?,?)",
                       (new_id("bind"), actor.tenant_id, actor.principal_id, alias, dest_id, canonical(["publish"])))
            db.execute("UPDATE principals SET routing_revision=routing_revision+1 WHERE id=?", (actor.principal_id,))
        else:
            alias = binding["alias"]
        result = {"destinations": [{"alias": alias, "kind": "destination", "label": evidence["label"],
                                   "revision": binding["epoch"] if binding else 1, "provider": "telegram"}]}
        db.execute("UPDATE operations SET state='verified',complete=1,work_state='done',result=? WHERE id=?",
                   (canonical(result), op["id"]))
        worker.store.event(db, op["id"], "finished", "completed",
                           "Telegram membership and send permission verified; exact native target " + evidence["native_id"])
