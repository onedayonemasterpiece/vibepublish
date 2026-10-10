"""Publish authority permits one admission of its own frozen zero-dispatch intent."""
import asyncio
import json
import unittest

from jsonschema import Draft202012Validator
from contracts.social_mcp_v1 import catalog, project_catalog
from social_operations.domain import DomainError
from social_operations.recovery import retry_failed
from tests.runtime import test_safe_retry as fixtures


class PublishRetryContractTests(unittest.TestCase):
    def test_publish_projection_is_closed_and_does_not_grant_management(self):
        canonical = catalog()
        tools = {t["name"]: t for t in project_catalog(
            {"bootstrap", "publish", "status"}, publish_destinations=("max",))}
        schema = tools["vibepublish_publication_update"]["inputSchema"]
        validator = Draft202012Validator(schema)
        args = {"publication_id": "pub_original", "expected_revision": 1,
                "change": {"kind": "retry_failed", "destinations": ["max"]},
                "request_key": "recover-original"}
        validator.validate(args)
        for field in ("publication_id", "expected_revision", "request_key"):
            self.assertFalse(validator.is_valid({k: v for k, v in args.items() if k != field}))
        for kind in ("approve", "edit", "reschedule", "cancel", "delete",
                     "reconcile", "reconcile_removed", "forward"):
            self.assertFalse(validator.is_valid({**args, "change": {"kind": kind}}))
        self.assertFalse(validator.is_valid({**args, "item_ref": "item_native"}))
        self.assertFalse(validator.is_valid({**args, "change": {
            **args["change"], "content": {"text": "Changed"}}}))
        for destinations in (["unbound"], ["max", "max"], []):
            self.assertFalse(validator.is_valid({**args, "change": {
                **args["change"], "destinations": destinations}}))
        for scopes, destinations in (({"status"}, ("max",)), ({"publish"}, ())):
            self.assertNotIn("vibepublish_publication_update", {
                t["name"] for t in project_catalog(scopes, publish_destinations=destinations)})
        self.assertEqual(catalog(), canonical)
        full = next(t for t in project_catalog({"publication.manage"})
                    if t["name"] == "vibepublish_publication_update")
        original = next(t for t in canonical["tools"] if t["name"] == full["name"])
        self.assertEqual(full["inputSchema"], original["inputSchema"])


class PublishRetryRuntimeTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.SafeRetryTests.setUp
    call = fixtures.SafeRetryTests.call
    retry_args = fixtures.SafeRetryTests.retry_args

    def publisher(self, name="events", scopes=None):
        credential = self.store.create_principal(
            self.actor.tenant_id, name, scopes=scopes or {"bootstrap", "publish", "status"})
        self.store.bind(self.actor, name, "max", "max", "target", rights=("publish",))
        self.publisher_credential = credential
        return self.store.authenticate(credential)

    async def blocked_publish(self, actor):
        self.provider.blocked = True
        receipt = await self.call("publish", {
            "to": ["max"], "content": {"text": "Frozen publication"},
            "request_key": "original-publish"}, actor)
        self.assertNotIn("error", receipt, receipt)
        await self.worker.run_once()
        self.assertEqual(self.store.receipt(actor, receipt["operation_id"])["state"], "blocked")
        return receipt

    def snapshot(self, operation_id):
        with self.store.connection() as db:
            return {
                "operation": dict(db.execute("SELECT * FROM operations WHERE id=?",
                                             (operation_id,)).fetchone()),
                "attempts": [dict(r) for r in db.execute(
                    "SELECT * FROM attempts WHERE operation_id=? ORDER BY id", (operation_id,))],
                "events": [dict(r) for r in db.execute(
                    "SELECT * FROM events WHERE operation_id=? ORDER BY seq", (operation_id,))],
                "keys": [dict(r) for r in db.execute(
                    "SELECT * FROM request_keys WHERE operation_id=? ORDER BY key", (operation_id,))],
                "revision": tuple(db.execute(
                    "SELECT p.id,p.revision FROM publications p JOIN operations o "
                    "ON o.publication_id=p.id WHERE o.id=?", (operation_id,)).fetchone()),
            }

    async def test_single_admission_preserves_original_identity_and_has_one_effect(self):
        actor = self.publisher()
        original = await self.blocked_publish(actor)
        before = self.snapshot(original["operation_id"])
        args = self.retry_args(original)
        accepted = await self.call("publication_update", args, actor)
        self.assertEqual(accepted["operation_id"], original["operation_id"])
        self.assertEqual(accepted["revision"], 1)
        admitted = self.snapshot(original["operation_id"])
        for key in ("id", "publication_id", "revision", "action", "request", "request_digest"):
            self.assertEqual(before["operation"][key], admitted["operation"][key])
        for key in ("id", "plan", "plan_digest", "checkpoint", "binding_id", "binding_epoch", "dispatched"):
            self.assertEqual(before["attempts"][0][key], admitted["attempts"][0][key])
        self.assertEqual(before["revision"], admitted["revision"])
        # Simulate a lost admission response and two transport retries.
        replies = await asyncio.gather(*[
            self.call("publication_update", args, actor) for _ in range(2)])
        self.assertTrue(all(r["operation_id"] == original["operation_id"] for r in replies))
        self.assertEqual(self.snapshot(original["operation_id"]), admitted)
        self.provider.blocked = False
        await self.worker.run_once()
        self.assertEqual(self.provider.count("effect"), 1)
        done = self.snapshot(original["operation_id"])
        self.assertEqual((await self.call("publication_update", args, actor))["state"], "verified")
        self.assertEqual(self.snapshot(original["operation_id"]), done)
        self.assertFalse(await self.worker.run_once())

    async def test_authenticated_http_uses_stable_header_and_replays_terminal_receipt(self):
        import httpx
        from social_operations.server import create_app
        actor = self.publisher()
        original = await self.blocked_publish(actor)
        path = "/v1/publications/" + original["resource_id"] + "/commands"
        body = {"expected_revision": 1, "change": {"kind": "retry_failed", "destinations": ["max"]}}
        headers = {"Authorization": "Bearer " + self.publisher_credential,
                   "Idempotency-Key": "http-recovery-once"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.store)),
                                     base_url="http://testserver", headers=headers) as client:
            accepted = await client.post(path, json=body)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            self.assertEqual(accepted.json()["operation_id"], original["operation_id"])
            admitted = self.snapshot(original["operation_id"])
            replay = await client.post(path, json=body)  # Initial reply lost by caller.
            self.assertEqual(replay.status_code, 202)
            self.assertEqual(self.snapshot(original["operation_id"]), admitted)
            await self.worker.run_once()
            terminal = self.snapshot(original["operation_id"])
            self.provider.blocked = False
            replay = await client.post(path, json=body)
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.json()["state"], "blocked")
            self.assertEqual(self.snapshot(original["operation_id"]), terminal)
            overscope = await client.post(path, json={"expected_revision": 1, "change": {"kind": "delete"}})
            self.assertEqual(overscope.status_code, 422)
            self.assertEqual(overscope.json()["error"]["code"], "invalid_input")
        self.assertFalse(await self.worker.run_once())
        self.assertEqual(self.provider.count("effect"), 0)

    async def test_same_key_after_second_terminal_failure_is_permanently_observation_only(self):
        actor = self.publisher()
        original = await self.blocked_publish(actor)
        args = self.retry_args(original)
        await self.call("publication_update", args, actor)
        await self.worker.run_once()  # Still blocked before dispatch.
        terminal = self.snapshot(original["operation_id"])
        self.assertEqual(terminal["attempts"][0]["dispatched"], 0)
        self.provider.blocked = False
        self.now += 1000
        for _ in range(3):
            replay = await self.call("publication_update", args, actor)
            self.assertEqual(replay["state"], "blocked")
            self.assertEqual(self.snapshot(original["operation_id"]), terminal)
            self.assertFalse(await self.worker.run_once())
        self.assertEqual(self.provider.count("effect"), 0)

    async def test_same_key_after_unknown_only_observes_and_fresh_key_cannot_retry(self):
        actor = self.publisher()
        original = await self.blocked_publish(actor)
        args = self.retry_args(original)
        await self.call("publication_update", args, actor)
        self.provider.blocked, self.provider.lose_receipt = False, True
        await self.worker.run_once()
        terminal = self.snapshot(original["operation_id"])
        replay = await self.call("publication_update", args, actor)
        self.assertEqual(replay["state"], "outcome_unknown")
        self.assertEqual(self.snapshot(original["operation_id"]), terminal)
        fresh = await self.call("publication_update", {**args, "request_key": "new-key"}, actor)
        self.assertEqual(fresh["error"]["code"], "retry_not_proven_safe")
        self.assertFalse(await self.worker.run_once())
        self.assertEqual(self.provider.count("effect"), 1)

    async def test_other_principal_and_owner_cannot_recover_private_publication(self):
        actor = self.publisher()
        other = self.publisher("other")
        original = await self.blocked_publish(actor)
        before = self.snapshot(original["operation_id"])
        for caller in (other, self.actor):
            result = await self.call("publication_update", self.retry_args(original), caller)
            self.assertEqual(result["error"]["code"], "not_found")
        self.assertEqual(self.snapshot(original["operation_id"]), before)

    async def test_other_commands_and_unkeyed_retry_fail_at_application_boundary(self):
        actor = self.publisher()
        original = await self.blocked_publish(actor)
        args = self.retry_args(original)
        before = self.snapshot(original["operation_id"])
        for kind in ("edit", "delete", "reschedule", "cancel", "approve",
                     "reconcile", "reconcile_removed", "forward"):
            forbidden = {**args, "change": {"kind": kind}}
            result = await self.call("publication_update", forbidden, actor)
            self.assertEqual(result["error"]["code"], "invalid_input")
            with self.assertRaises(DomainError) as caught:
                self.app.accept(actor, "publication_update", forbidden)
            self.assertEqual(caught.exception.code, "access_denied")
        unkeyed = {k: v for k, v in args.items() if k != "request_key"}
        with self.assertRaises(DomainError) as caught:
            retry_failed(self.app, actor, unkeyed)
        self.assertEqual(caught.exception.code, "access_denied")
        self.assertEqual(self.snapshot(original["operation_id"]), before)

    async def test_existing_lifecycle_revision_cannot_be_recovered_after_scope_narrowing(self):
        edit = await fixtures.SafeRetryTests.blocked_edit(self)
        with self.store.tx() as db:
            db.execute("UPDATE principals SET scopes=? WHERE id=?",
                       (json.dumps(["publish"]), self.actor.principal_id))
        before = self.snapshot(edit["operation_id"])
        with self.assertRaises(DomainError) as caught:
            retry_failed(self.app, self.actor, self.retry_args(edit))
        self.assertEqual(caught.exception.code, "access_denied")
        self.assertEqual(self.snapshot(edit["operation_id"]), before)

    async def test_pending_finalization_and_revision_conflict_do_not_admit(self):
        actor = self.publisher()
        original = await self.blocked_publish(actor)
        args = self.retry_args(original)
        wrong = await self.call("publication_update", {**args, "expected_revision": 2}, actor)
        self.assertEqual(wrong["error"]["code"], "revision_conflict")
        before = self.snapshot(original["operation_id"])
        child = before["attempts"][0]
        with self.store.tx() as db:
            db.execute("INSERT INTO attempt_recovery(attempt_id,plan_digest,original_checkpoint,"
                       "finalize_state,created) VALUES(?,?,?,'pending',?)",
                       (child["id"], child["plan_digest"], child["checkpoint"], self.now))
        rejected = await self.call("publication_update", args, actor)
        self.assertEqual(rejected["error"]["code"], "operation_in_progress")
        self.assertEqual(self.snapshot(original["operation_id"]), before)
        self.assertEqual(self.provider.count("effect"), 0)

    async def test_wrong_original_action_is_rejected_without_schema(self):
        actor = self.publisher()
        original = await self.blocked_publish(actor)
        for action in ("publication_update", "engage", "media_store"):
            with self.store.tx() as db:
                db.execute("UPDATE operations SET action=? WHERE id=?",
                           (action, original["operation_id"]))
            before = self.snapshot(original["operation_id"])
            with self.assertRaises(DomainError) as caught:
                retry_failed(self.app, actor, self.retry_args(original))
            self.assertEqual(caught.exception.code, "access_denied")
            self.assertEqual(self.snapshot(original["operation_id"]), before)

    async def test_current_publish_scope_and_binding_right_are_both_required(self):
        actor = self.publisher()
        original = await self.blocked_publish(actor)
        with self.store.tx() as db:
            db.execute("UPDATE principals SET scopes=? WHERE id=?",
                       (json.dumps(["status"]), actor.principal_id))
        with self.assertRaises(DomainError) as caught:
            retry_failed(self.app, actor, self.retry_args(original))
        self.assertEqual(caught.exception.code, "access_denied")
        with self.store.tx() as db:
            db.execute("UPDATE principals SET scopes=? WHERE id=?",
                       (json.dumps(["publish"]), actor.principal_id))
            db.execute("UPDATE bindings SET rights='[]' WHERE principal_id=?", (actor.principal_id,))
        with self.assertRaises(DomainError) as caught:
            retry_failed(self.app, actor, self.retry_args(original))
        self.assertEqual(caught.exception.code, "access_denied")
        self.assertEqual(self.provider.count("effect"), 0)

    async def test_binding_identity_drift_and_epoch_change_are_rejected(self):
        actor = self.publisher()
        original = await self.blocked_publish(actor)
        args = self.retry_args(original)
        with self.store.tx() as db:
            db.execute("UPDATE destinations SET native_id='changed'")
        result = await self.call("publication_update", args, actor)
        self.assertEqual(result["error"]["code"], "retry_binding_changed")
        with self.store.tx() as db:
            db.execute("UPDATE destinations SET native_id='target'")
            db.execute("UPDATE bindings SET epoch=epoch+1 WHERE principal_id=?", (actor.principal_id,))
        result = await self.call("publication_update", args, actor)
        self.assertEqual(result["error"]["code"], "access_revoked")
        self.assertEqual(self.provider.count("effect"), 0)

    async def test_previously_dispatched_failure_and_unknown_sibling_are_rejected(self):
        actor = self.publisher()
        self.store.bind(self.actor, "events", "other", "max", "other-target", rights=("publish",))
        self.provider.blocked = True
        original = await self.call("publish", {
            "to": ["max", "other"], "content": {"text": "Two destinations"}}, actor)
        await self.worker.run_once()
        args = self.retry_args(original)
        with self.store.tx() as db:
            db.execute("UPDATE attempts SET dispatched=1 WHERE operation_id=? AND alias='max'",
                       (original["operation_id"],))
        result = await self.call("publication_update", args, actor)
        self.assertEqual(result["error"]["code"], "retry_not_proven_safe")
        with self.store.tx() as db:
            db.execute("UPDATE attempts SET dispatched=0 WHERE operation_id=? AND alias='max'",
                       (original["operation_id"],))
            db.execute("UPDATE attempts SET state='outcome_unknown',dispatched=1 "
                       "WHERE operation_id=? AND alias='other'", (original["operation_id"],))
        result = await self.call("publication_update", args, actor)
        self.assertEqual(result["error"]["code"], "retry_not_proven_safe")
        self.assertEqual(self.provider.count("effect"), 0)
