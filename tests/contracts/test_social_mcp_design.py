"""Offline design checks only. No model, database, browser or provider execution."""
from pathlib import Path
import json
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jsonschema import Draft202012Validator, FormatChecker
from contracts.social_mcp_v1 import catalog, project_catalog
from contracts.task_corpus_v1 import JOBS, INVALID

CATALOG = catalog()
TOOLS = {tool["name"]: tool for tool in CATALOG["tools"]}


def validator(tool, field="inputSchema"):
    return Draft202012Validator(TOOLS[tool][field], format_checker=FormatChecker())


class ContractDesignTests(unittest.TestCase):
    def test_all_schemas_and_closed_objects(self):
        def visit(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False)
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)
        self.assertEqual(len(TOOLS), 8)
        for tool in TOOLS.values():
            for field in ("inputSchema", "outputSchema"):
                with self.subTest(tool=tool["name"], schema=field):
                    Draft202012Validator.check_schema(tool[field])
                    self.assertEqual(tool[field]["type"], "object")
                    visit(tool[field])

    def test_all_golden_calls_validate(self):
        self.assertGreaterEqual(len(JOBS), 40)
        self.assertEqual({j["tool"] for j in JOBS}, set(TOOLS))
        self.assertEqual(len({j["id"] for j in JOBS}), len(JOBS))
        for job in JOBS:
            with self.subTest(job=job["id"]):
                validator(job["tool"]).validate(job["arguments"])

    def test_negative_calls_are_rejected(self):
        for tool, arguments, reason in INVALID:
            with self.subTest(reason=reason):
                self.assertTrue(list(validator("vibepublish_" + tool).iter_errors(arguments)))

    def test_failure_outputs_do_not_fabricate_receipts(self):
        result = {"error": {"code": "invalid_input", "message": "Fix the selected field"},
                  "message": "No operation accepted", "next_action": "fix_input", "retry_safe": False}
        for name in TOOLS:
            with self.subTest(tool=name):
                validator(name, "outputSchema").validate(result)

    def test_mutation_receipt_and_uncertain_result(self):
        result = {"operation_id": "op_1", "resource_id": "pub_1", "revision": 1,
                  "action": "publish", "state": "outcome_unknown", "message": "MAX needs observation",
                  "next_action": "review_outcome", "retry_safe": False, "receipt_ref": "receipt_1",
                  "operation_complete": False,
                  "progress": {"events": [], "cursor": "event_cursor_0", "has_more": False},
                  "deliveries": [{"destination": "pka_max", "provider": "max", "state": "outcome_unknown",
                    "stage": "outcome_unknown", "observed": "unknown", "revision": 1, "media_check": "incomplete", "retry_safe": False}]}
        for name in ("publish", "publication_update", "visual", "engage", "destinations"):
            validator("vibepublish_" + name, "outputSchema").validate(result)
        result["next_action"] = "retry_everything"
        self.assertTrue(list(validator("vibepublish_publish", "outputSchema").iter_errors(result)))

    def test_read_success_outputs(self):
        validator("vibepublish_status", "outputSchema").validate({"receipts": []})
        validator("vibepublish_read", "outputSchema").validate({
            "operation_id": "op_read", "action": "read", "state": "verified", "message": "Read complete",
            "operation_complete": True, "progress": {"events": [], "cursor": "event_1", "has_more": False},
            "next_action": "none", "retry_safe": False, "receipt_ref": "receipt_read",
            "deliveries": [], "items": [], "truncated": False})
        validator("vibepublish_get_started", "outputSchema").validate({
            "version": "1", "schema_version": "1", "skill_sha256": "a" * 64, "skill": "Read first",
            "estimated_tokens": 20, "server_time": "2026-09-04T18:00:00Z", "policy_epoch": 1,
            "scheduling": "provider_native_only", "read_policy": "bound_publish_destinations",
            "destinations": [], "capabilities": []})

    def test_scoped_projection_and_determinism(self):
        scopes = {"bootstrap", "publish", "publication.manage", "visual", "status"}
        tools = project_catalog(scopes)
        self.assertEqual(len(tools), 5)
        self.assertTrue(all("required_scope" not in t for t in tools))
        self.assertNotIn("vibepublish_read", {t["name"] for t in tools})
        self.assertEqual(project_catalog(set()), [])
        self.assertEqual(catalog(), CATALOG)
        self.assertEqual(project_catalog(scopes), tools)
        self.assertEqual(len(project_catalog({t["required_scope"] for t in CATALOG["tools"]}, owner=True)), 8)

    def test_native_queue_only(self):
        schema = TOOLS["vibepublish_publish"]["inputSchema"]["$defs"]["delivery"]
        self.assertEqual(set(schema["oneOf"][1]["properties"]), {"kind", "at"})
        output = json.dumps(TOOLS["vibepublish_publish"]["outputSchema"])
        self.assertNotIn("service_queued", output)
        self.assertNotIn('"backend"', output)

    def test_publisher_inherits_scoped_read_catalog(self):
        scopes = {"bootstrap", "publish", "publication.manage", "visual", "status"}
        projected = project_catalog(scopes, publish_destinations=("own_channel",))
        self.assertEqual(len(projected), 6)
        read = next(t for t in projected if t["name"] == "vibepublish_read")
        v = Draft202012Validator(read["inputSchema"], format_checker=FormatChecker())
        for kind in ("feed", "scheduled", "stories"):
            v.validate({"query": {"kind": kind, "destination": "own_channel"}})
        self.assertTrue(list(v.iter_errors({"query": {"kind": "dialogs", "provider": "telegram"}})))
        owner_read = next(t for t in project_catalog(scopes, owner=True) if t["name"] == "vibepublish_read")
        Draft202012Validator(owner_read["inputSchema"]).validate({"query": {"kind": "dialogs", "provider": "telegram"}})
        self.assertEqual(catalog(), CATALOG)  # Projection never mutates the canonical schema.

    def test_incremental_receipt_does_not_require_all_children_finished(self):
        event = {"seq": 3, "operation_id": "op_1", "destination": "pka_tg",
            "at": "2026-09-04T20:00:00Z", "stage": "verifying", "status": "completed",
            "message": "Observed in Telegram native queue"}
        children = []
        for dest, provider, state, stage, observed in [
            ("pka_tg", "telegram", "scheduled", "finished", "provider_scheduled"),
            ("pka_vk", "vk", "running", "uploading", "not_attempted"),
            ("pka_max", "max", "running", "waiting_connection", "not_attempted")]:
            children.append({"destination": dest, "provider": provider, "state": state, "stage": stage,
                "observed": observed, "revision": 1, "media_check": "not_applicable", "retry_safe": False})
        receipt = {"operation_id": "op_1", "action": "schedule", "state": "running",
            "message": "Telegram confirmed; others still running", "operation_complete": False,
            "next_action": "check_status", "retry_safe": False, "receipt_ref": "receipt_1",
            "progress": {"events": [event], "cursor": "event_cursor_3", "has_more": False},
            "deliveries": children}
        validator("vibepublish_publish", "outputSchema").validate(receipt)
        validator("vibepublish_status", "outputSchema").validate({"receipts": [receipt]})
        # Invalid stage is rejected, not silently treated as successful provider work.
        event["stage"] = "wait_until_publish_time"
        self.assertTrue(list(validator("vibepublish_publish", "outputSchema").iter_errors(receipt)))

    def test_schedule_finished_is_not_published(self):
        receipt = {"operation_id": "op_1", "action": "schedule", "state": "scheduled",
            "message": "Confirmed in provider queue", "operation_complete": True,
            "next_action": "none", "retry_safe": False, "receipt_ref": "receipt_1",
            "progress": {"events": [], "cursor": "event_cursor_9", "has_more": False},
            "deliveries": [{"destination": "pka_tg", "provider": "telegram", "state": "scheduled",
                "stage": "finished", "observed": "provider_scheduled", "revision": 1,
                "scheduling_owner": "provider", "queue_ref": "queue_1", "media_check": "provider_binding",
                "retry_safe": False}]}
        validator("vibepublish_publish", "outputSchema").validate(receipt)

    def test_history_metrics_and_remote_queue_examples(self):
        for args in [
            {"query": {"kind": "history", "author": "mine", "text": "сезон"}},
            {"query": {"kind": "analytics", "publication_ids": ["pub_1"], "freshness": "refresh"}},
            {"query": {"kind": "scheduled", "destination": "own_channel"}}]:
            validator("vibepublish_read").validate(args)
        self.assertIn("allow_all_bound_queue_items_not_only_own", {j["runtime_oracle"] for j in JOBS})
        self.assertIn("return_first_new_event_from_any_child", {j["runtime_oracle"] for j in JOBS})

    def test_progress_required_for_accepted_operation(self):
        payload = {"operation_id": "op_1", "action": "publish", "state": "accepted",
            "message": "Accepted", "operation_complete": False, "next_action": "check_status",
            "retry_safe": False, "receipt_ref": "receipt_1", "deliveries": []}
        self.assertTrue(list(validator("vibepublish_publish", "outputSchema").iter_errors(payload)))
        payload["progress"] = {"events": [], "cursor": "event_cursor_0", "has_more": False}
        validator("vibepublish_publish", "outputSchema").validate(payload)

    def test_sensitive_runtime_cases_remain_explicit_oracles(self):
        # This checks only that the corpus specifies those gates, not that a server enforces them.
        oracles = {j["runtime_oracle"] for j in JOBS}
        self.assertIn("deny_before_provider_read", oracles)
        self.assertIn("reject_uncertain_retry_keep_existing_receipt", oracles)
        self.assertIn("idempotency_conflict_before_dispatch", oracles)
        self.assertIn("deny_before_parent_resume", oracles)


if __name__ == "__main__":
    print(json.dumps({"scope": "offline_schema_design_only", "tools": len(TOOLS),
        "schemas": 2 * len(TOOLS), "golden_calls": len(JOBS), "invalid_calls": len(INVALID),
        "version": CATALOG["version"], "input_schema_bytes": {n: len(json.dumps(t["inputSchema"], ensure_ascii=False,
                                separators=(",", ":")).encode()) for n, t in TOOLS.items()}}), flush=True)
    unittest.main(verbosity=2)
