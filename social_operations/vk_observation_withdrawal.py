"""Withdraw a contradicted scheduled VK identity without resolving dispatch."""
import json
import re

from .domain import DomainError, canonical, digest, normalize_intent, parse_time
from .managed_item_edits import _fresh_read

MARKER = "withdrawn_observation"


def withdraw(app, actor, args):
    """Return None for edit-baseline reconciliation; publishing is local only."""
    store, change = app.store, args["change"]
    with store.tx() as db:
        actor = store.current(db, actor)
        op = store.private_operation(db, actor, change["operation_id"])
        if op["action"] != "publish":
            return None
        if not actor.owner or "publication.manage" not in actor.scopes:
            raise DomainError("access_denied", next_action="contact_owner")
        key, reference = args.get("request_key"), change.get("native_reference", "")
        if (args.get("item_ref") or not key or not change.get("attempt_id")
                or not re.fullmatch(r"item_[0-9a-f]{32}", reference)):
            raise DomainError("observation_withdrawal_reference_required")
        pub = db.execute("SELECT revision FROM publications WHERE id=?", (op["publication_id"],)).fetchone()
        if (op["publication_id"] != args.get("publication_id")
                or op["revision"] != args["expected_revision"] or pub["revision"] != args["expected_revision"]):
            raise DomainError("revision_conflict", next_action="refresh")
        identity = digest([MARKER, normalize_intent("publication_update", args)])
        replay = db.execute("SELECT * FROM request_keys WHERE tenant_id=? AND principal_id=? AND key=?",
                            (actor.tenant_id, actor.principal_id, key)).fetchone()
        if replay:
            if replay["digest"] != identity or replay["operation_id"] != op["id"]:
                raise DomainError("idempotency_conflict")
        else:
            children = list(db.execute("SELECT * FROM attempts WHERE operation_id=?", (op["id"],)))
            if (op["state"] != "scheduled" or not op["complete"] or op["work_state"] != "done"
                    or len(children) != 1 or children[0]["id"] != change["attempt_id"]):
                raise DomainError("observation_withdrawal_not_available", next_action="review_outcome")
            child = children[0]
            plan, checkpoint = json.loads(child["plan"]), json.loads(child["checkpoint"])
            remote = checkpoint.get("remote", {})
            recovery = db.execute("SELECT * FROM attempt_recovery WHERE attempt_id=?", (child["id"],)).fetchone()
            original = json.loads(recovery["original_checkpoint"]) if recovery else {}
            adapter = original.get("adapter", {})
            if not (child["provider"] == plan["provider"] == "vk" and child["dispatched"] == 1
                    and child["state"] == "scheduled" and child["observed"] == "provider_scheduled"
                    and plan["action"] == "publish" and plan["surface"] == "post" and plan["scheduled_at"]
                    and not plan.get("existing") and not plan.get("source")
                    and digest(plan) == child["plan_digest"]
                    and recovery and recovery["plan_digest"] == child["plan_digest"]
                    and recovery["finalize_state"] == "done"
                    and original.get("transition") == "vk_prepared"
                    and type(adapter.get("version")) is int and adapter["version"] == 1 and adapter.get("id") is None
                    and adapter.get("attempt") == child["id"] and adapter.get("plan") == child["plan_digest"]
                    and adapter.get("target") == plan["native_target"]
                    and isinstance(adapter.get("media"), list) and adapter["media"]
                    and len(adapter["media"]) == len(plan["assets"]) == len(remote.get("provider_media", []))
                    and adapter["media"] != remote.get("provider_media")
                    and remote.get("namespace") == "scheduled" and remote.get("native_target") == plan["native_target"]
                    and remote.get("provider_media")
                    and json.loads(recovery["observation"] or "{}").get("items") == [remote]):
                raise DomainError("observation_withdrawal_not_available", next_action="review_outcome")
            binding = store.binding(db, actor, binding_id=child["binding_id"])
            if (binding["epoch"] != child["binding_epoch"] or binding["epoch"] != plan["binding_epoch"]
                    or "publish" not in json.loads(binding["rights"])
                    or binding["native_id"] != plan["native_target"]
                    or any(binding[k] != plan[k] for k in
                           ("connection_id", "destination_id", "account_type", "secret_ref"))):
                raise DomainError("access_revoked", next_action="reauthorize")
            source = app.resolve_item(db, actor, reference)
            fresh = json.loads(source["snapshot"])
            if (source["binding_id"] != child["binding_id"] or source["binding_epoch"] != child["binding_epoch"]
                    or source["native_id"] != remote["native_id"] or source["namespace"] != "scheduled"
                    or any(fresh.get(k) != remote.get(k) for k in
                           ("native_id", "native_target", "namespace", "provider_media", "member_ids"))
                    or fresh.get("origin")):
                raise DomainError("observation_withdrawal_reference_mismatch")
            _fresh_read(db, actor, source, binding, fresh, store.clock())
            # Positive older publication ownership, not absence in best-effort logs.
            prior = list(db.execute(
                "SELECT o.id,o.publication_id,a.id AS attempt_id,a.checkpoint,a.result FROM facts f "
                "JOIN operations o ON o.publication_id=f.publication_id JOIN attempts a ON a.operation_id=o.id "
                "WHERE f.destination_id=? AND f.native_id=? AND f.namespace='scheduled' AND f.initiator=? "
                "AND o.tenant_id=? AND o.principal_id=? AND o.actor_epoch=? AND o.publication_id!=? "
                "AND o.action='publish' AND o.state='scheduled' AND o.complete=1 AND o.work_state='done' "
                "AND o.created<? AND a.binding_id=? AND a.binding_epoch=? AND a.dispatched=1 "
                "AND a.state='scheduled' AND a.observed='provider_scheduled' LIMIT 2",
                (binding["destination_id"], remote["native_id"], actor.principal_id, actor.tenant_id,
                 actor.principal_id, actor.epoch, op["publication_id"], op["created"],
                 child["binding_id"], child["binding_epoch"])))
            old = json.loads(prior[0]["checkpoint"]).get("remote", {}) if len(prior) == 1 else {}
            if (not old or not parse_time(old["observed_at"]) < op["created"]
                    or any(old.get(k) != fresh.get(k) for k in
                           ("native_id", "native_target", "namespace", "provider_media", "member_ids"))):
                raise DomainError("observation_withdrawal_prior_publication_required")
            result = json.loads(child["result"])
            refs = sorted({result[k] for k in ("item_ref", "queue_ref") if result.get(k)})
            old_refs = json.loads(prior[0]["result"])
            if (not refs or reference in refs
                    or any(ref in old_refs.values() for ref in refs)):
                raise DomainError("observation_withdrawal_reference_mismatch")
            for ref in refs:
                false = app.resolve_item(db, actor, ref)
                if (false["binding_id"] != child["binding_id"] or false["binding_epoch"] != child["binding_epoch"]
                        or false["native_id"] != remote["native_id"] or false["namespace"] != "scheduled"
                        or json.loads(false["snapshot"]) != remote):
                    raise DomainError("observation_withdrawal_reference_mismatch")
            proof = dict(native_reference=reference, prior_operation_id=prior[0]["id"],
                         prior_publication_id=prior[0]["publication_id"], invalidated_refs=refs,
                         withdrawn_at=store.clock())
            hint = {**json.loads(recovery["hint"]), MARKER: proof}
            # observation/original_checkpoint remain audit; facts and trusted refs stay intact.
            db.execute("UPDATE attempt_recovery SET hint=? WHERE attempt_id=?", (canonical(hint), child["id"]))
            db.executemany("DELETE FROM item_refs WHERE id=? AND tenant_id=? AND principal_id=?",
                           [(ref, actor.tenant_id, actor.principal_id) for ref in refs])
            error = DomainError("observation_withdrawn", "Former VK identity belongs to an older publication; dispatch outcome remains unknown", "review_outcome")
            db.execute("UPDATE attempts SET state='outcome_unknown',stage='finished',observed='unknown',result=?,checkpoint=? WHERE id=?",
                       (canonical(dict(reason=error.message, missing_checks=[error.code], retry_safe=False)),
                        canonical({"core_recovery": hint}), child["id"]))
            db.execute("UPDATE operations SET state='outcome_unknown',complete=1,work_state='done',"
                       "fence=fence+1,lease_owner=NULL,lease_until=0,error=? WHERE id=?",
                       (canonical(error.output()), op["id"]))
            store.event(db, op["id"], "finished", "unknown",
                        "Withdrawn local identity using " + reference + "; prior publication " + prior[0]["publication_id"] + "; no provider call or retry admitted", child["alias"])
            app._key(db, actor, key, identity, op["id"])
    return store.receipt(actor, op["id"])
