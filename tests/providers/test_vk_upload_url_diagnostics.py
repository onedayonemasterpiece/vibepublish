"""No-network validation evidence and fail-closed provider error redaction."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from adapters.vk_transport import validated_url
from social_operations.domain import DomainError
from social_operations.provider_diagnostics import (
    budget_diagnostic, diagnostic_scope, provider_error_metadata, safe_diagnostic,
)


class UploadURLDiagnosticsTests(unittest.TestCase):
    def test_direct_adapter_validation_reports_before_any_transport(self):
        cases = (
            (None, False, "invalid_type", None),
            ([], False, "invalid_type", None),
            ("", False, "invalid_length", None),
            ("x" * 4097, False, "invalid_length", None),
            ("https://pu.vk.com/private path", False, "invalid_characters", "pu.vk.com"),
            ("https://pu.vk.com/\\private", False, "invalid_characters", "pu.vk.com"),
            ("https://[private", False, "malformed_url", None),
            ("http://pu.vk.com/private?key=PRIVATE", False, "scheme_not_https", "pu.vk.com"),
            ("https://user:PRIVATE@pu.vk.com/private?key=PRIVATE", False, "credentials_present", "pu.vk.com"),
            ("https://pu.vk.com/private#PRIVATE", False, "fragment_present", "pu.vk.com"),
            ("https://pu.vk.com:444/private", False, "port_not_allowed", "pu.vk.com"),
            ("https://pu.vk.com:PRIVATE/private", False, "port_not_allowed", "pu.vk.com"),
            ("https://pu.vk.com:65536/private", False, "port_not_allowed", "pu.vk.com"),
            ("https://video.example.org/private?key=PRIVATE", False, "host_not_allowed", "video.example.org"),
            ("https://vk.com.evil.example/private", False, "host_not_allowed", "vk.com.evil.example"),
            ("https://pu.vk.com/method/wall.getById", True, "api_host_not_allowed", "pu.vk.com"),
            ("https://api.vk.com/private", True, "api_path_not_allowed", "api.vk.com"),
            ("https://api.vk.com/method/wall.getById?key=PRIVATE", True, "api_query_present", "api.vk.com"),
        )
        for url, api, reason, host in cases:
            with self.subTest(reason=reason, api=api):
                events = []
                with patch("adapters.vk_transport.public_addresses", new_callable=AsyncMock) as dns:
                    with diagnostic_scope(events.append), self.assertRaises(DomainError) as raised:
                        validated_url(url, api=api)
                    dns.assert_not_called()
                self.assertEqual(raised.exception.code, "vk_upload_url_invalid")
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["operation"], "upload_url_validation")
                self.assertEqual(events[0]["status"], "failed")
                self.assertEqual(events[0]["url_rejection_reason"], reason)
                self.assertEqual(events[0].get("upload_host"), host)
                serialized = json.dumps(events)
                for value in ("PRIVATE", "/private", "key=", "user:"):
                    self.assertNotIn(value, serialized)

    def test_existing_allowlist_and_signed_upload_queries_are_unchanged(self):
        accepted = ["https://" + host + "/private?key=PRIVATE" for host in
                    ("vk.com", "pu.vk.com", "userapi.com", "pu.userapi.com",
                     "vkuser.net", "pu.vkuser.net", "vk.me", "pu.vk.me", "ovu.mycdn.me")]
        accepted.append("https://PU.VK.COM:443/private?key=PRIVATE")
        events = []
        with diagnostic_scope(events.append):
            for url in accepted:
                self.assertTrue(validated_url(url))
            self.assertEqual(validated_url("https://api.vk.com/method/wall.getById", api=True), "api.vk.com")
        self.assertEqual(events, [])

    def test_invalid_url_still_rejected_when_diagnostic_sink_throws(self):
        with patch("adapters.vk_upload_diagnostics.report", side_effect=RuntimeError("PRIVATE")):
            with self.assertRaises(DomainError) as raised:
                validated_url("http://pu.vk.com/private?key=PRIVATE")
        self.assertEqual(raised.exception.code, "vk_upload_url_invalid")

    def test_rejection_reason_is_closed_and_host_is_not_a_url(self):
        for value in ("PRIVATE", "host_not_allowed PRIVATE", {}, [], True):
            self.assertEqual(safe_diagnostic({"url_rejection_reason": value}), {})
        clean = safe_diagnostic({"url_rejection_reason": "host_not_allowed",
                                 "upload_host": "user:PRIVATE@pu.vk.com/private?key=PRIVATE",
                                 "upload_url": "PRIVATE", "port": "PRIVATE"})
        self.assertEqual(clean, {"url_rejection_reason": "host_not_allowed"})


class ProviderErrorRedactionTests(unittest.TestCase):
    def test_known_error_is_fixed_template_not_a_scrubbed_substring(self):
        cases = (
            ("Access denied: owner PRIVATE; https://user:PRIVATE@host/private?access_token=PRIVATE", "access_denied", "Access denied"),
            ("Permission to perform this action is denied: PRIVATE", "access_denied", "Access denied"),
            ("User authorization failed: access_token=PRIVATE", "authorization_failed", "Authorization failed"),
            ("Too many requests per second. PRIVATE", "rate_limited", "Rate limit exceeded"),
            ("Flood control: PRIVATE", "rate_limited", "Rate limit exceeded"),
            ("Captcha needed: https://host/private?key=PRIVATE", "captcha_required", "Captcha required"),
            ("One of the parameters specified was missing or invalid: message=PRIVATE", "invalid_parameters", "Invalid or missing parameters"),
            ("Internal server error\r\nAuthorization: Bearer PRIVATE", "provider_error", "Provider internal error"),
            ("Unknown error occurred; Cookie: PRIVATE", "provider_error", "Provider internal error"),
        )
        for message, category, safe_text in cases:
            with self.subTest(category=category):
                value = provider_error_metadata(message)
                self.assertEqual(value, {"provider_error_class": category, "provider_error_text": safe_text})
                self.assertEqual(safe_diagnostic(value), value)
                self.assertNotIn("PRIVATE", json.dumps(value))

    def test_unknown_and_oversized_messages_are_omitted_not_echoed(self):
        unknown = ("PRIVATE", "Access deniedPRIVATE", "https://host/private?token=PRIVATE",
                   "Bearer PRIVATE", "email=user@example.org", "0xdeadbeef", "PRIVATE\nmessage",
                   "Access denied: " + "PRIVATE" * 400, None, {}, [], 123, b"PRIVATE")
        for message in unknown:
            with self.subTest(message_type=type(message).__name__):
                self.assertEqual(provider_error_metadata(message), {
                    "provider_error_class": "unclassified", "provider_error_text": "Provider error; message omitted"})

    def test_caller_cannot_inject_arbitrary_text_via_allowed_fields(self):
        value = safe_diagnostic({"provider_error_class": "access_denied", "provider_error_text": "PRIVATE",
                                 "error_msg": "PRIVATE", "message": "PRIVATE", "request_params": {"token": "PRIVATE"}})
        self.assertEqual(value, {"provider_error_class": "access_denied", "provider_error_text": "Access denied"})
        for category in ("PRIVATE", {}, [], None):
            self.assertEqual(safe_diagnostic({"provider_error_class": category, "provider_error_text": "PRIVATE"}), {})

    def test_budget_prioritizes_rejection_and_api_error_evidence(self):
        record = {"operation_id": "op_" + "a" * 32, "publication_id": "pub_" + "b" * 32,
                  "attempt_id": "attempt_" + "c" * 32, "action": "edit", "dispatched": False,
                  **safe_diagnostic({"provider": "vk", "operation": "upload_url_validation", "status": "failed",
                      "error_code": "vk_upload_url_invalid", "url_rejection_reason": "host_not_allowed",
                      "provider_code": 15, "provider_error_class": "access_denied",
                      "upload_host": ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 61)),
                      "response_request_id": "a" * 80, "asset_sha256": "b" * 64})}
        result = budget_diagnostic(record)
        for key in ("operation_id", "publication_id", "attempt_id", "url_rejection_reason",
                    "provider_code", "provider_error_class", "provider_error_text", "upload_host"):
            self.assertEqual(result[key], record[key])
        self.assertLessEqual(len("provider_diagnostic " + json.dumps(result, separators=(",", ":"))), 1000)


class APIErrorTransportIntegrationTests(unittest.TestCase):
    def test_error_metadata_does_not_change_exception_or_add_requests(self):
        from adapters.vk_transport import VKHTTPTransport, VKToken
        transport = VKHTTPTransport(tokens={"reader": VKToken("fixture-private", kind="user")})
        transport._post = AsyncMock(return_value={"error": {"error_code": 15,
            "error_msg": "Access denied: https://user:PRIVATE@host/private?access_token=PRIVATE",
            "request_params": [{"key": "access_token", "value": "PRIVATE"}]}})
        events = []
        with diagnostic_scope(events.append), self.assertRaises(DomainError) as raised:
            asyncio.run(transport.invoke(role="reader", method="wall.getById", params={"posts": "-101_77"}))
        self.assertEqual(raised.exception.code, "vk_api_failed")
        transport._post.assert_awaited_once()
        self.assertEqual(events[-1]["provider_code"], 15)
        self.assertEqual(events[-1]["provider_error_class"], "access_denied")
        self.assertEqual(events[-1]["provider_error_text"], "Access denied")
        self.assertNotIn("PRIVATE", json.dumps(events))
        self.assertNotIn("fixture-private", json.dumps(events))
