"""Explicit local baseline refresh for one never-dispatched VK edit conflict.

A private immutable read ref is evidence, not authorization to send. This creates
a new local revision only; the subsequent explicit edit still performs native CAS.
"""
import json
import re

from .domain import DomainError, canonical, digest, new_id, normalize_intent, parse_time


def rebase(app, actor, args):
    store = app.store
    change = args["change"]
    key = args.get("request_key")
    reference = change.get("native_reference", "")
    if (args.get("item_ref") or not key or not change.get("attempt_id")
            or not re.fullmatch(r"item_[0-9a-f]{32}", reference)):
        raise DomainError("rebase_exact_reference_required")
    intent = normalize_intent("publication_update", args)
    identity = digest(["rebase", intent])
    with store.tx() as db:
        actor = store.current(db, actor)
        if not actor.owner or "publication.manage" not in actor.scopes:
            raise DomainError("access_denied", next_action="contact_owner")
        replay = db.execute(
            "SELECT * FROM request_keys WHERE tenant_id=? AND principal_id=? AND key=?",
            (actor.tenant_id, actor.principal_id, key)).fetchone()
        if replay:
            if replay["digest"] != identity:
                raise DomainError("idempotency_conflict")
            operation = store.private_operation(db, actor, replay["operation_id"])["id"]
        else:
            previous = store.private_operation(db, actor, args["publication_id"])
            if (previous["id"] != change["operation_id"]
                    or previous["revision"] != args["expected_revision"]):
                raise DomainError("revision_conflict", next_action="refresh")
            publication = db.execute("SELECT * FROM publications WHERE id=?",
                                     (previous["publication_id"],)).fetchone()
            if publication["revision"] != args["expected_revision"]:
                raise DomainError("revision_conflict", next_action="refresh")
            children = list(db.execute("SELECT * FROM attempts WHERE operation_id=?",
                                       (previous["id"],)))
            if previous["work_state"] != "done" or len(children) != 1:
                raise DomainError("rebase_not_available")
            child = children[0]
            old = json.loads(child["plan"])
            missing = json.loads(child["result"]).get("missing_checks", [])
            failure = json.loads(previous["error"] or "{}").get("error", {})
            upload_failed = ("vk_http_failed" in missing
                and failure.get("code") == "vk_http_failed"
                and failure.get("message") in {
                    "VK media_upload HTTP status 502",
                    "VK media_upload HTTP status 503",
                    "VK media_upload HTTP status 504"})
            if (child["id"] != change["attempt_id"] or child["dispatched"]
                    or child["state"] not in {"blocked", "failed"}
                    or old["provider"] != "vk" or old["action"] != "edit"
                    or not ("remote_revision_conflict" in missing or upload_failed)
                    or not old.get("existing") or old["existing"]["namespace"] != "published"):
                raise DomainError("rebase_not_available")
            if db.execute("SELECT 1 FROM attempt_recovery WHERE attempt_id=? AND finalize_state='pending'",
                          (child["id"],)).fetchone():
                raise DomainError("rebase_not_available")
            binding = store.binding(db, actor, binding_id=child["binding_id"])
            if (binding["epoch"] != child["binding_epoch"]
                    or "edit" not in json.loads(binding["rights"])
                    or any(binding[k] != old[k] for k in
                           ("connection_id", "destination_id", "account_type", "secret_ref"))
                    or binding["native_id"] != old["native_target"]):
                raise DomainError("access_revoked", next_action="reauthorize")
            item = app.resolve_item(db, actor, reference)
            remote = json.loads(item["snapshot"])
            if (item["binding_id"] != child["binding_id"]
                    or item["binding_epoch"] != child["binding_epoch"]
                    or item["native_id"] != old["existing"]["native_id"]
                    or item["namespace"] != "published"
                    or remote["native_id"] != old["existing"]["native_id"]
                    or remote["native_target"] != old["native_target"]
                    or remote["namespace"] != "published" or remote.get("origin")):
                raise DomainError("rebase_reference_mismatch")
            age = store.clock() - parse_time(remote["observed_at"])
            if not 0 <= age <= 300:
                raise DomainError("rebase_reference_stale", next_action="refresh")
            # New immutable revision; never alter the failed request/plan/checkpoint.
            plan = {**old, "existing": remote}
            revision = publication["revision"] + 1
            db.execute("UPDATE publications SET revision=? WHERE id=? AND revision=?",
                       (revision, publication["id"], publication["revision"]))
            db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?)",
                (actor.tenant_id, actor.principal_id, publication["id"], revision,
                 canonical(intent), canonical([plan]), digest([plan])))
            operation = app._new_operation(db, actor, "publication_update", intent,
                publication=publication["id"], revision=revision, complete=True,
                result={"message":"Baseline refreshed locally; no provider write. Submit a separate explicit edit."})
            result = {"item_ref":reference, "observed_at":remote["observed_at"],
                      "media_check":remote.get("media_check", "incomplete")}
            db.execute(
                "INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,plan,plan_digest,"
                "state,stage,observed,result,checkpoint) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("attempt"), operation, child["binding_id"], child["binding_epoch"],
                 child["alias"], child["provider"], canonical(plan), digest(plan),
                 "verified", "finished", "published", canonical(result), canonical({"remote":remote})))
            store.event(db, operation, "finished", "completed",
                "Explicit baseline refresh from " + reference + "; original conflict " +
                previous["id"] + " retained. No provider effect.", child["alias"])
            app._key(db, actor, key, identity, operation)
    return store.receipt(actor, operation)
