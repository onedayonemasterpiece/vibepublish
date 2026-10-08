"""Owner-only provider-verified exact destination registration; no implicit joins or enumeration."""
from __future__ import annotations

import asyncio
import json

from .domain import DomainError, canonical, digest, new_id


_ACCOUNT_TYPES = {
    "telegram": {"mtproto_user"},
    "vk": {"vk_user", "vk_group"},
}
_PREFIX = {"telegram": "tg", "vk": "vk"}


def admit(app, db, actor, command, intent):
    if not actor.owner:
        raise DomainError("access_denied", next_action="contact_owner")
    provider = command["provider"]
    if provider not in _ACCOUNT_TYPES:
        raise DomainError("capability_not_implemented", next_action="contact_owner")
    if provider == "telegram":
        if command.get("provider_id"):
            raise DomainError("telegram_destination_reference_invalid")
        from adapters.telegram_discovery import parse_destination_url
        parse_destination_url(command["url"])
    else:
        from adapters.vk_discovery import parse_destination
        parse_destination(command)
    placeholders = ",".join("?" for _ in _ACCOUNT_TYPES[provider])
    connections = db.execute(
        f"SELECT id,secret_ref FROM connections WHERE tenant_id=? AND provider=? AND account_type IN ({placeholders}) AND active=1",
        (actor.tenant_id, provider, *_ACCOUNT_TYPES[provider]),
    ).fetchall()
    if provider == "telegram" and len(connections) > 1:
        # A dedicated knowledge-base session is not a publishing account.
        # Mirror owner direct-link routing without broad account fallback.
        ordinary = [row for row in connections
                    if row["secret_ref"] != "VIBEPUBLISH_KNOWLEDGE_BASE_AUTH_BUNDLE"]
        if len(ordinary) == 1:
            connections = ordinary
    if len(connections) != 1:
        raise DomainError(f"{provider}_discovery_connection_ambiguous", next_action="contact_owner")
    request = dict(intent, _connection_id=connections[0]["id"])
    return app._new_operation(db, actor, "destinations", request)


async def process(worker, op, actor):
    args = json.loads(op["request"])
    provider = args["command"]["provider"]
    if provider not in _ACCOUNT_TYPES:
        raise DomainError("capability_not_implemented", next_action="contact_owner")
    connection_id = args["_connection_id"]
    with worker.store.connection() as db:
        actor = worker.store.current(db, actor)
        if not actor.owner:
            raise DomainError("access_denied", next_action="contact_owner")
        connection = db.execute(
            "SELECT * FROM connections WHERE id=? AND tenant_id=? AND active=1",
            (connection_id, actor.tenant_id),
        ).fetchone()
        if (not connection or connection["provider"] != provider
                or connection["account_type"] not in _ACCOUNT_TYPES[provider]):
            raise DomainError("access_revoked", next_action="reauthorize")
    await worker.hooks(op).emit_progress(
        "accepted", "started", f"Checking exact {provider} destination access and publish permission"
    )
    budget = min(30, op["deadline"] - worker.store.clock())
    if budget <= 0:
        raise DomainError("command_expired")
    adapter = worker.adapter(provider, connection_id)
    async with worker.lane(connection_id):
        try:
            async with asyncio.timeout(budget):
                if provider == "telegram":
                    from adapters.telegram_discovery import resolve
                    evidence = await resolve(adapter, args["command"]["url"])
                    rights = evidence["rights"]
                else:
                    from adapters.vk_discovery import resolve
                    evidence = await resolve(adapter, args["command"])
                    rights = evidence["rights"]
        except TimeoutError:
            raise DomainError("provider_read_deadline", next_action="refresh") from None

    with worker.store.tx() as db:
        worker.store.fence(db, op["id"], worker.id, op["fence"])
        actor = worker.store.current(db, actor)
        current = db.execute(
            "SELECT * FROM connections WHERE id=? AND tenant_id=? AND active=1",
            (connection_id, actor.tenant_id),
        ).fetchone()
        if (not current or current["provider"] != provider
                or current["account_type"] not in _ACCOUNT_TYPES[provider]):
            raise DomainError("access_revoked", next_action="reauthorize")
        destination = db.execute(
            "SELECT * FROM destinations WHERE connection_id=? AND native_id=?",
            (connection_id, evidence["native_id"]),
        ).fetchone()
        dest_id = destination["id"] if destination else new_id("dest")
        binding = db.execute(
            "SELECT * FROM bindings WHERE principal_id=? AND destination_id=?",
            (actor.principal_id, dest_id),
        ).fetchone()
        if binding and not binding["active"]:
            raise DomainError("access_revoked", next_action="reauthorize")
        if not destination:
            db.execute(
                "INSERT INTO destinations VALUES(?,?,?,?,?)",
                (dest_id, connection_id, evidence["native_id"], evidence["handle"], evidence["label"]),
            )
        else:
            db.execute(
                "UPDATE destinations SET handle=?,label=? WHERE id=?",
                (evidence["handle"], evidence["label"], dest_id),
            )
        changed = False
        if not binding:
            alias = _PREFIX[provider] + "_" + digest([connection_id, evidence["native_id"]])[:20]
            if (db.execute(
                    "SELECT 1 FROM bindings WHERE tenant_id=? AND principal_id=? AND alias=?",
                    (actor.tenant_id, actor.principal_id, alias),
                ).fetchone()
                    or db.execute(
                        "SELECT 1 FROM destination_sets WHERE tenant_id=? AND principal_id=? AND alias=?",
                        (actor.tenant_id, actor.principal_id, alias),
                    ).fetchone()):
                raise DomainError("alias_conflict")
            db.execute(
                "INSERT INTO bindings(id,tenant_id,principal_id,alias,destination_id,rights) VALUES(?,?,?,?,?,?)",
                (new_id("bind"), actor.tenant_id, actor.principal_id, alias, dest_id, canonical(rights)),
            )
            changed = True
            revision = 1
        else:
            alias = binding["alias"]
            existing_rights = json.loads(binding["rights"])
            if "publish" not in existing_rights:
                raise DomainError("access_denied", next_action="contact_owner")
            merged = list(dict.fromkeys(existing_rights + rights))
            if merged != existing_rights:
                db.execute("UPDATE bindings SET rights=? WHERE id=?", (canonical(merged), binding["id"]))
                changed = True
            revision = binding["epoch"]
        if changed:
            db.execute(
                "UPDATE principals SET routing_revision=routing_revision+1 WHERE id=?",
                (actor.principal_id,),
            )
        result = {
            "destinations": [{
                "alias": alias,
                "kind": "destination",
                "label": evidence["label"],
                "revision": revision,
                "provider": provider,
            }]
        }
        db.execute(
            "UPDATE operations SET state='verified',complete=1,work_state='done',result=? WHERE id=?",
            (canonical(result), op["id"]),
        )
        worker.store.event(
            db, op["id"], "finished", "completed",
            f"{provider} exact destination and publish authority verified; native target {evidence['native_id']}",
        )
