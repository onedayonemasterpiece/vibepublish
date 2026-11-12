"""Owner-only outgoing proposals to third-party VK public pages.

This is not VKAdapter.publish: posting to a foreign page as its administrator
would change a public wall, whereas a user-token proposal enters moderation.
"""
from __future__ import annotations

import json
import re

from .domain import DomainError, canonical, digest, timestamp


def _source(app, db, actor, command, *, require_sender=True):
    row = app.resolve_item(db, actor, command["source_item_ref"])
    binding = app.store.binding(db, actor, binding_id=row["binding_id"])
    if binding["provider"] != "vk":
        raise DomainError("vk_proposal_vk_source_required")
    # Preview is entirely local and must remain available before the owner
    # connects a VK user credential; submission resolves and checks the sender.
    sender = None
    if require_sender:
        if command.get("sender_alias"):
            sender = app.store.binding(db, actor, alias=command["sender_alias"])
        elif binding["account_type"] == "vk_user":
            sender = binding
        else:
            candidates = [
                other for other in app.store.bindings(db, actor)
                if other["provider"] == "vk" and other["account_type"] == "vk_user"
                and "publish" in json.loads(other["rights"])
            ]
            if len(candidates) != 1:
                raise DomainError("vk_proposal_user_connection_required", next_action="reauthorize")
            sender = candidates[0]
        if (sender["provider"] != "vk" or sender["account_type"] != "vk_user"
                or "publish" not in json.loads(sender["rights"])):
            raise DomainError("vk_proposal_user_token_required", next_action="reauthorize")
    if row["namespace"] != "published":
        raise DomainError("vk_proposal_published_source_required")
    remote = json.loads(row["snapshot"])
    media = remote.get("provider_media") or []
    if (not isinstance(media, list) or not 2 <= len(media) <= 10
            or any(not isinstance(item, str) or not re.fullmatch(r"photo-?[1-9][0-9]*_[1-9][0-9]*(?:_[a-zA-Z0-9]+)?", item)
                   for item in media)):
        raise DomainError("vk_proposal_carousel_photos_required")
    text = command.get("message", remote.get("text") or "")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 16000:
        raise DomainError("vk_proposal_text_required")
    target = command.get("target_group_id")
    name = command.get("target_screen_name")
    if target is not None and binding["native_id"] == "-" + target:
        raise DomainError("vk_proposal_foreign_target_required")
    target_url = f"https://vk.com/club{target}" if target else f"https://vk.com/{name}"
    return {
        "source_item_ref": command["source_item_ref"],
        "source_url": f"https://vk.com/wall{binding['native_id']}_{row['native_id']}",
        **({"target_group_id": target} if target else {"target_screen_name": name}),
        "target_url": target_url,
        "text": text,
        "attachments": media,
        "moderation_status": "unverified",
    }, {
        **({"_connection_id": sender["connection_id"],
            "_binding_id": sender["id"],
            "_binding_epoch": sender["epoch"]} if sender is not None else {}),
        "_source_target": binding["native_id"],
        "_source_native_id": row["native_id"],
    }


def command(app, actor, args):
    c = args["command"]
    kind = c["kind"]
    if not actor.owner or "publish" not in actor.scopes:
        raise DomainError("access_denied", next_action="contact_owner")
    with app.store.tx() as db:
        actor = app.store.current(db, actor)
        if kind == "list":
            limit = args.get("limit", 25)
            rows = db.execute(
                "SELECT * FROM operations WHERE tenant_id=? AND principal_id=? "
                "AND action='vk_proposals' AND json_extract(request,'$.kind')='submit' "
                "ORDER BY created DESC LIMIT ?",
                (actor.tenant_id, actor.principal_id, limit + 1),
            ).fetchall()
            items = []
            for row in rows[:limit]:
                original = json.loads(row["request"])
                receipt = dict(json.loads(row["result"]).get("vk_proposal") or original["proposal"])
                receipt["status"] = ("submitted" if receipt.get("post_id") else
                    "outcome_unknown" if row["state"] == "outcome_unknown" else
                    "failed" if row["complete"] else "sending")
                receipt["operation_id"] = row["id"]
                receipt["attempted_at"] = timestamp(row["created"])
                if row["error"] and row["state"] != "outcome_unknown":
                    receipt["error_code"] = json.loads(row["error"]).get("error", {}).get("code", "error")
                items.append(receipt)
            operation_id = app._new_operation(db, actor, "vk_proposals", {"kind": "list"},
                complete=True, result={"vk_proposals": items, "truncated": len(rows) > limit})
        else:
            # Public input is the stable request-key identity. Internal binding
            # IDs are frozen only after authorization.
            intent = dict(c)
            replay = (app._replay(db, actor, "vk_proposals", intent, args, implicit=False)
                      if kind == "submit" else None)
            if replay:
                operation_id = replay
            else:
                proposal, binding = _source(app, db, actor, c, require_sender=(kind == "submit"))
                if kind == "preview":
                    operation_id = app._new_operation(db, actor, "vk_proposals", intent,
                        complete=True, result={"vk_proposal": {**proposal, "status": "preview"}})
                else:
                    # A different key for the same source/target does not
                    # duplicate a prior pending or accepted submission.
                    prior = db.execute(
                        "SELECT id FROM operations WHERE tenant_id=? AND principal_id=? "
                        "AND action='vk_proposals' AND json_extract(request,'$.kind')='submit' "
                        "AND json_extract(request,'$._source_target')=? "
                        "AND json_extract(request,'$._source_native_id')=? "
                        "AND json_extract(request,'$.proposal.target_url')=? "
                        "AND state IN ('accepted','running','verified','outcome_unknown') "
                        "ORDER BY created DESC LIMIT 1",
                        (actor.tenant_id, actor.principal_id, binding["_source_target"],
                         binding["_source_native_id"], proposal["target_url"]),
                    ).fetchone()
                    if prior:
                        operation_id = prior["id"]
                    else:
                        frozen = {**intent, **binding, "proposal": proposal}
                        operation_id = app._new_operation(db, actor, "vk_proposals",
                                                          frozen, command_timeout=120)
                    app._key(db, actor, args["request_key"],
                             digest(["vk_proposals", intent]), operation_id)
    return app.store.receipt(actor, operation_id)


def _finish(worker, op, state, proposal, error=None):
    with worker.store.tx() as db:
        worker.store.fence(db, op["id"], worker.id, op["fence"])
        db.execute(
            "UPDATE operations SET state=?,complete=1,work_state='done',"
            "lease_owner=NULL,lease_until=0,result=?,error=? WHERE id=?",
            (state, canonical({"vk_proposal": proposal}), canonical(error.output()) if error else None, op["id"]),
        )
        worker.store.event(db, op["id"], "finished", "completed" if state == "verified" else "blocked",
                           "VK accepted outgoing suggestion" if state == "verified" else
                           ("VK proposal outcome uncertain" if state == "outcome_unknown" else "VK proposal refused"))


async def process(worker, op, actor):
    request = json.loads(op["request"])
    proposal = {**request["proposal"], "status": "sending", "operation_id": op["id"],
                "attempted_at": timestamp(op["created"])}
    dispatched = False
    try:
        with worker.store.connection() as db:
            binding = worker.store.binding(db, actor, binding_id=request["_binding_id"])
            if binding["epoch"] != request["_binding_epoch"] or binding["connection_id"] != request["_connection_id"]:
                raise DomainError("access_revoked", next_action="reauthorize")
            if binding["account_type"] != "vk_user" or binding["provider"] != "vk":
                raise DomainError("vk_proposal_user_token_required", next_action="reauthorize")
            dispatched = bool(db.execute(
                "SELECT 1 FROM events WHERE operation_id=? AND "
                "json_extract(body,'$.stage')='submitting' LIMIT 1", (op["id"],)
            ).fetchone())
        if dispatched:
            raise DomainError("vk_proposal_previous_dispatch_unconfirmed")
        adapter = worker.adapter("vk", request["_connection_id"])
        if getattr(adapter, "account_type", None) != "vk_user":
            raise DomainError("vk_proposal_user_token_required", next_action="reauthorize")
        selector = proposal.get("target_group_id") or proposal["target_screen_name"]
        async with worker.lane(request["_connection_id"]):
            groups = await adapter._call("groups.getById", role="editor",
                    group_ids=selector, fields="type,is_admin,is_closed,screen_name")
            rows = groups.get("groups") if isinstance(groups, dict) else groups
            if (not isinstance(rows, list) or len(rows) != 1 or
                    not isinstance(rows[0], dict) or
                    type(rows[0].get("id")) is not int or rows[0]["id"] <= 0):
                raise DomainError("vk_proposal_target_not_verified")
            group = rows[0]
            target = group["id"]
            if (proposal.get("target_group_id") and int(proposal["target_group_id"]) != target
                    or proposal.get("target_screen_name") and
                    group.get("screen_name", "").casefold() != proposal["target_screen_name"].casefold()):
                raise DomainError("vk_proposal_target_not_verified")
            if request["_source_target"] == "-" + str(target):
                raise DomainError("vk_proposal_foreign_target_required")
            if group.get("type") != "page" or group.get("is_closed") != 0 or group.get("is_admin") != 0:
                raise DomainError("vk_proposal_not_foreign_public_page")
            existing = await adapter._exact(
                request["_source_target"], request["_source_native_id"], "published")
            if (existing is None
                    or ("message" not in request and existing.text != proposal["text"])
                    or list(existing.provider_media) != proposal["attachments"]):
                raise DomainError("vk_proposal_source_changed", next_action="refresh")
            # The last safe boundary. If the worker dies during the request, the
            # durable event prevents another send; VK's guid remains fixed.
            with worker.store.tx() as db:
                worker.store.fence(db, op["id"], worker.id, op["fence"])
                worker.store.event(db, op["id"], "submitting", "started",
                                   "Submitting a VK user proposal with frozen guid")
            dispatched = True
            response = await adapter._call(
                "wall.post", role="editor", owner_id=-target,
                message=proposal["text"], from_group=0, signed=0,
                guid=digest(["vk_proposals", op["id"]]),
                attachments=",".join(proposal["attachments"]),
                primary_attachments_mode="carousel",
            )
        ident = response.get("post_id") if isinstance(response, dict) else None
        if type(ident) is not int or ident <= 0:
            raise DomainError("vk_proposal_response_unconfirmed")
        proposal.update(status="submitted", post_id=str(ident),
                        target_group_id=str(target), moderation_status="unverified")
        _finish(worker, op, "verified", proposal)
    except DomainError as error:
        uncertain = dispatched and error.code in {
            "vk_proposal_previous_dispatch_unconfirmed",
            "vk_proposal_response_unconfirmed",
            "vk_transport_failed", "vk_http_failed", "vk_response_invalid",
            "vk_cooldown",
        }
        state = "outcome_unknown" if uncertain else "blocked"
        proposal["status"] = "outcome_unknown" if uncertain else "failed"
        proposal["error_code"] = error.code
        _finish(worker, op, state, proposal, error)
    except Exception:
        error = DomainError("vk_proposal_provider_unavailable", next_action="contact_owner")
        proposal.update(status="outcome_unknown" if dispatched else "failed",
                        error_code=error.code)
        _finish(worker, op, "outcome_unknown" if dispatched else "blocked", proposal, error)