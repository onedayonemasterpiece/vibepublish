"""No-network tests for the closed upload-telemetry vocabulary and collection."""
import asyncio
import hashlib
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from adapters.vk_upload_diagnostics import upload_endpoint, upload_payload, upload_response
from social_operations.provider_diagnostics import diagnostic_scope, safe_diagnostic


class UploadMetadataTests(unittest.TestCase):
    def test_closed_safe_metadata(self):
        value = dict(upload_host="PU.VK.COM", peer_ip="2001:db8::1",
                     upload_bytes=551753, upload_mime="image/jpeg", asset_sha256="a" * 64,
                     request_body_bytes=551942, request_framing="content_length",
                     response_server="nginx/1.26.2", response_via="1.1 edge.example",
                     response_request_id="01234567-89ab-cdef-0123-456789abcdef",
                     dns_ms=2.1256, headers_wait_ms=4000.25)
        clean = safe_diagnostic(value)
        self.assertEqual(clean["upload_host"], "pu.vk.com")
        self.assertEqual(clean["peer_family"], "ipv6")
        self.assertEqual(clean["upload_bytes"], 551753)
        self.assertEqual(clean["request_body_bytes"], 551942)
        self.assertEqual(clean["dns_ms"], 2.126)
        self.assertEqual(clean["response_server"], "nginx/1.26.2")
        self.assertEqual(clean["asset_sha256"], "a" * 64)

    def test_urls_auth_cookies_and_bodies_never_enter_vocabulary(self):
        value = dict(url="https://pu.vk.com/private?access_token=SECRET", body=b"SECRET",
                     headers={"Authorization": "Bearer SECRET"}, authorization="SECRET",
                     cookie="SECRET", upload_url="https://pu.vk.com?key=SECRET",
                     response_body="SECRET", upload_host="https://pu.vk.com/private",
                     response_server="nginx access_token=SECRET", response_via="1.1 user:SECRET@host",
                     response_request_id="Bearer-SECRET", asset_sha256="SECRET")
        self.assertEqual(safe_diagnostic(value), {})

    def test_host_rejects_non_hostname_and_oversized_values(self):
        for value in ("user@pu.vk.com", "pu.vk.com:443", "pu.vk.com/path",
                      "pu.vk.com?hash=x", "pu.vk.com#x", "pu.vk.com\nSECRET",
                      "secret.pu.vk.com", "a" * 254, None, {}, []):
            with self.subTest(value_type=type(value).__name__):
                self.assertNotIn("upload_host", safe_diagnostic({"upload_host": value}))

    def test_response_header_values_are_bounded_and_not_free_text(self):
        values = ("https://host/private?key=SECRET", "secret", "Bearer abc",
                  "token:abc", "good\r\nAuthorization: abc", "a" * 161, {}, b"abc")
        for key in ("response_server", "response_via", "response_request_id",
                    "response_vk_request_id", "response_correlation_id"):
            for value in values:
                with self.subTest(key=key, value_type=type(value).__name__):
                    self.assertNotIn(key, safe_diagnostic({key: value}))
        self.assertNotIn("response_request_id", safe_diagnostic({"response_request_id": "a.b.c"}))

    def test_sizes_types_and_timing_bounds(self):
        for key in ("upload_bytes", "request_body_bytes"):
            for value in (-1, True, 1.5, "500", 64 * 1024 * 1024 + 1):
                self.assertNotIn(key, safe_diagnostic({key: value}))
        for key in ("dns_ms", "headers_wait_ms"):
            for value in (-1, float("inf"), float("nan"), True, "1"):
                self.assertNotIn(key, safe_diagnostic({key: value}))
        self.assertNotIn("peer_ip", safe_diagnostic({"peer_ip": "fe80::1%SECRET"}))
        self.assertNotIn("peer_ip", safe_diagnostic({"peer_ip": "https://1.2.3.4"}))
        self.assertNotIn("upload_mime", safe_diagnostic({"upload_mime": "text/SECRET"}))
        self.assertNotIn("request_framing", safe_diagnostic({"request_framing": "SECRET"}))

    def test_payload_correlates_original_asset_without_logging_bytes(self):
        events = []
        original = b"original-private-asset"
        derivative = b"private-jpeg-data"
        with diagnostic_scope(events.append):
            upload_payload(derivative, "image/jpeg", "photo",
                           asset_sha256=hashlib.sha256(original).hexdigest())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["asset_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(events[0]["upload_bytes"], len(derivative))
        self.assertEqual(events[0]["phase"], "photo")
        self.assertNotIn("private", json.dumps(events))

    def test_endpoint_extracts_only_hostname_even_before_validation(self):
        details = {}
        upload_endpoint(details, "https://user:SECRET@pu.vk.com/private/path?key=SECRET#SECRET")
        self.assertEqual(safe_diagnostic(details), {"upload_host": "pu.vk.com"})
        upload_endpoint(details, None)
        self.assertNotIn("SECRET", json.dumps(details))

    def test_response_reads_only_allowlisted_headers_and_peer(self):
        read = []
        class Headers(dict):
            def get(self, key, default=None):
                read.append(key)
                return super().get(key, default)
        response = SimpleNamespace(
            headers=Headers({"Server": "nginx", "Via": "1.1 edge.example",
                             "X-Request-Id": "aabbccdd-01234567", "Set-Cookie": "SECRET",
                             "Authorization": "SECRET", "Location": "https://private/SECRET"}),
            request_info=SimpleNamespace(headers={"Content-Length": "551942", "Cookie": "SECRET"}),
            connection=SimpleNamespace(transport=SimpleNamespace(
                get_extra_info=lambda key: ("203.0.113.10", 443))),
        )
        details = {}
        upload_response(details, response)
        clean = safe_diagnostic(details)
        self.assertEqual(clean["request_framing"], "content_length")
        self.assertEqual(clean["request_body_bytes"], 551942)
        self.assertEqual(clean["peer_family"], "ipv4")
        self.assertEqual(set(read), {"Server", "Via", "X-Request-Id", "X-VK-Request-Id", "X-Correlation-Id"})
        self.assertNotIn("SECRET", json.dumps(clean))
        self.assertNotIn("Set-Cookie", read)
        self.assertNotIn("Authorization", read)
        self.assertNotIn("Location", read)

    def test_chunked_and_missing_optional_metadata(self):
        response = SimpleNamespace(headers={}, request_info=SimpleNamespace(
            headers={"Transfer-Encoding": "chunked"}), connection=None)
        details = {}
        upload_response(details, response)
        self.assertEqual(safe_diagnostic(details), {"request_framing": "chunked"})
        details = {}
        upload_response(details, SimpleNamespace(headers={}))
        self.assertEqual(details, {})

    def test_bad_optional_metadata_never_raises(self):
        with patch("adapters.vk_upload_diagnostics.report", side_effect=RuntimeError("SECRET")):
            upload_payload(b"data", "image/jpeg", "photo")
        class BadHeaders:
            def get(self, key):
                raise RuntimeError("SECRET")
        upload_response({}, SimpleNamespace(headers=BadHeaders()))


class Context:
    def __init__(self, value):
        self.value = value
    async def __aenter__(self):
        return self.value
    async def __aexit__(self, *args):
        return False


class UploadTransportTelemetryTests(unittest.TestCase):
    def test_failed_http_upload_metadata_and_request_are_unchanged(self):
        from adapters.vk_transport import VKHTTPTransport
        from social_operations.domain import DomainError
        response = SimpleNamespace(status=504, headers={"Server": "nginx", "Set-Cookie": "SECRET"},
            request_info=SimpleNamespace(headers={"Content-Length": "600100"}), connection=None)
        calls, events, session_options = [], [], []
        data = object()
        def post(url, **kwargs):
            calls.append((url, kwargs))
            return Context(response)
        def session(**kwargs):
            session_options.append(kwargs)
            return Context(SimpleNamespace(post=post))
        fake = SimpleNamespace(TCPConnector=lambda **kwargs: None, ClientSession=session,
            DummyCookieJar=lambda: None, ClientTimeout=lambda **kwargs: None)
        transport = VKHTTPTransport(tokens={})
        url = "https://pu.vk.com/private?hash=SECRET"
        with patch.dict(sys.modules, {"aiohttp": fake}), \
                patch("adapters.vk_transport.public_addresses", new=AsyncMock(return_value=["203.0.113.1"])):
            with diagnostic_scope(events.append), self.assertRaises(DomainError) as raised:
                asyncio.run(transport._post(url, data))
        self.assertEqual(raised.exception.code, "vk_http_failed")
        self.assertEqual(raised.exception.http_status, 504)
        self.assertEqual(calls, [(url, {"data": data, "allow_redirects": False})])
        self.assertFalse(session_options[0]["trust_env"])
        failure = events[-1]
        self.assertEqual(failure["upload_host"], "pu.vk.com")
        self.assertEqual(failure["http_status"], 504)
        self.assertEqual(failure["request_body_bytes"], 600100)
        self.assertEqual(failure["error_type"], "DomainError")
        self.assertGreaterEqual(failure["dns_ms"], 0)
        self.assertGreaterEqual(failure["headers_wait_ms"], 0)
        self.assertNotIn("SECRET", json.dumps(events))
        self.assertNotIn("/private", json.dumps(events))

    def test_invalid_url_has_only_safe_host_and_no_network(self):
        from adapters.vk_transport import VKHTTPTransport
        from social_operations.domain import DomainError
        events = []
        dns = AsyncMock()
        with patch("adapters.vk_transport.public_addresses", dns):
            with diagnostic_scope(events.append), self.assertRaises(DomainError):
                asyncio.run(VKHTTPTransport(tokens={})._post(
                    "https://user:SECRET@pu.vk.com/private?hash=SECRET", {}))
        dns.assert_not_called()
        self.assertEqual(events[-1]["upload_host"], "pu.vk.com")
        self.assertEqual(events[-1]["error_code"], "vk_upload_url_invalid")
        self.assertNotIn("SECRET", json.dumps(events))

    def test_photo_metadata_hashes_source_and_counts_encoded_derivative(self):
        from adapters.vk_transport import VKHTTPTransport
        original, wire = b"source-asset-private", b"jpeg-wire"
        transport = VKHTTPTransport(tokens={})
        transport._post = AsyncMock(return_value={"server": 1, "photo": "receipt", "hash": "receipt-hash"})
        events = []
        with patch("adapters.vk_photo_wire.photo_wire_bytes", return_value=(wire, "image/jpeg")):
            with diagnostic_scope(events.append):
                asyncio.run(transport.upload_photo("https://pu.vk.com/upload", original, "image/png"))
        prepared = next(e for e in events if e.get("operation") == "upload_payload")
        self.assertEqual(prepared["asset_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(prepared["upload_bytes"], len(wire))
        self.assertEqual(prepared["upload_mime"], "image/jpeg")
        self.assertEqual(prepared["status"], "completed")
        self.assertNotIn("source-asset-private", json.dumps(events))


class DiagnosticBudgetTests(unittest.TestCase):
    def test_maximal_metadata_keeps_core_and_parseable_1000_char_message(self):
        from social_operations.provider_diagnostics import budget_diagnostic
        details = dict(provider="vk", operation="media_upload", status="failed",
            error_type="ClientResponseError", error_code="vk_http_failed", http_status=504,
            duration_ms=86400000, upload_host="a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 61,
            peer_ip="2001:db8:abcd:abcd:abcd:abcd:abcd:abcd", upload_bytes=67108864,
            upload_mime="image/jpeg", asset_sha256="a" * 64, request_body_bytes=67108864,
            request_framing="content_length", dns_ms=86400000, headers_wait_ms=86400000,
            response_server="nginx/" + "1" * 32, response_via="1.1 " + "a" * 100,
            response_request_id="a" * 80, response_vk_request_id="b" * 80,
            response_correlation_id="c" * 80)
        record = {**safe_diagnostic(details), "operation_id": "op_" + "a" * 32,
                  "publication_id": "pub_" + "b" * 32, "attempt_id": "attempt_" + "c" * 32,
                  "action": "publication_update", "dispatched": False}
        capped = budget_diagnostic(record)
        encoded = "provider_diagnostic " + json.dumps(capped, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertLessEqual(len(encoded), 1000)
        self.assertEqual(json.loads(encoded[:1000][20:]), capped)
        for key in ("operation_id", "publication_id", "attempt_id", "action", "provider", "dispatched",
                    "operation", "status", "error_code", "error_type", "http_status", "duration_ms"):
            self.assertEqual(capped[key], record[key])
        self.assertGreater(capped["metadata_omitted"], 0)
        self.assertEqual(capped, budget_diagnostic(dict(reversed(list(record.items())))))

    def test_maximum_existing_name_lengths_also_fit(self):
        from social_operations.provider_diagnostics import budget_diagnostic
        record = {k: "x" * 80 for k in ("provider", "operation", "status", "error_code", "error_type")}
        record.update(operation_id="op_" + "a" * 32, publication_id="pub_" + "b" * 32,
                      attempt_id="attempt_" + "c" * 32, action="publication_update", dispatched=True,
                      http_status=599, duration_ms=86400000, upload_host="a" * 250 + ".com")
        result = budget_diagnostic(record)
        self.assertLessEqual(len("provider_diagnostic " + json.dumps(result, sort_keys=True, separators=(",", ":"))), 1000)
        for key in ("operation_id", "publication_id", "attempt_id", "operation", "status", "error_code", "error_type"):
            self.assertEqual(result[key], record[key])
