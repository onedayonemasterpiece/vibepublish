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
                  "deliveries": [{"destination": "pka_max", "provider": "max", "state": "outcome_unknown",
                    "observed": "unknown", "revision": 1, "media_check": "incomplete", "retry_safe": False}]}
        for name in ("publish", "publication_update", "visual", "engage", "destinations"):
            validator("vibepublish_" + name, "outputSchema").validate(result)
        result["next_action"] = "retry_everything"
        self.assertTrue(list(validator("vibepublish_publish", "outputSchema").iter_errors(result)))

    def test_read_success_outputs(self):
        validator("vibepublish_status", "outputSchema").validate({"receipts": []})
        validator("vibepublish_read", "outputSchema").validate({"items": [], "truncated": False})
        validator("vibepublish_get_started", "outputSchema").validate({
            "version": "1", "schema_version": "1", "skill_sha256": "a" * 64, "skill": "Read first",
            "estimated_tokens": 20, "server_time": "2026-09-04T18:00:00Z", "policy_epoch": 1,
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
        self.assertEqual(len(project_catalog({t["required_scope"] for t in CATALOG["tools"]})), 8)

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
        "input_schema_bytes": {n: len(json.dumps(t["inputSchema"], ensure_ascii=False,
                                separators=(",", ":")).encode()) for n, t in TOOLS.items()}}), flush=True)
    unittest.main(verbosity=2)
