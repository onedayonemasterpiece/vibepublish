"""Durable sanitized diagnostics use the existing public progress cursor."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from adapters.fake import FakeProvider
from social_operations.domain import DomainError
from social_operations.provider_diagnostics import diagnostic_scope, provider_call, safe_diagnostic
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


def test_closed_metadata_vocabulary_and_bounds():
    clean = safe_diagnostic(dict(provider="vk", operation="wall.post", status="failed",
        http_status=503, provider_code=6, retry_after_s=12, duration_ms=1.5,
        url="https://private/token", body="SECRET", headers={"Authorization":"SECRET"},
        error_type="bad SECRET!", error_code="https://private/SECRET"))
    assert clean == dict(provider="vk", operation="wall.post", status="failed",
                         http_status=503, provider_code=6, retry_after_s=12, duration_ms=1.5)
    assert safe_diagnostic(dict(http_status=999, retry_after_s=float("inf"),
                                duration_ms=-1, provider_code=True)) == {}


def test_original_exception_and_observer_failure_never_change_effect():
    events = []
    with diagnostic_scope(events.append):
        with pytest.raises(TimeoutError):
            with provider_call("vk", "media_upload"):
                raise TimeoutError("SECRET signed URL")
    assert [e["status"] for e in events] == ["started", "failed"]
    assert events[-1]["error_type"] == "TimeoutError"
    assert events[-1]["duration_ms"] >= 0
    assert "SECRET" not in json.dumps(events)
    def broken(_):
        raise RuntimeError("unavailable diagnostic sink")
    with diagnostic_scope(broken):
        with provider_call("vk", "wall.post"):
            pass


@pytest.mark.asyncio
async def test_task_local_correlation():
    left, right = [], []
    async def run(sink, operation):
        with diagnostic_scope(sink.append):
            with provider_call("telegram", operation):
                await asyncio.sleep(0)
    await asyncio.gather(run(left,"left"),run(right,"right"))
    assert {e["operation"] for e in left} == {"left"}
    assert {e["operation"] for e in right} == {"right"}


class FailedProvider(FakeProvider):
    armed = False
    calls = 0
    async def execute(self, prepared, hooks):
        self.calls += 1
        await hooks.emit_progress("uploading", "started", "Uploading fixture")
        if self.armed:
            await hooks.before_effect(prepared.request.attempt_id, prepared.request.plan_digest)
        with provider_call("telegram", "upload_file") as diagnostic:
            diagnostic.update(http_status=503, retry_after_s=7, body="SECRET",
                              url="https://private/SECRET")
            raise DomainError("fixture_upload_failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("armed", [False, True])
async def test_failure_survives_restart_and_public_cursor_without_retry(tmp_path, armed):
    now = 1800000000.0
    store = Store(tmp_path/"ledger.sqlite", clock=lambda: now)
    actor = store.authenticate(store.create_principal("tenant", "owner", owner=True))
    store.add_connection(actor, "tg", "telegram", account_type="fake")
    store.bind(actor, "owner", "tg", "tg", "target")
    provider = FailedProvider(tmp_path/"remote.sqlite", "telegram", clock=lambda: now)
    provider.armed = armed
    receipt = await Application(store).call(actor, "vibepublish_publish",
        {"to":["tg"], "content":{"text":"Fixture"}})
    worker = Worker(store, {"telegram":provider})
    assert await worker.run_once()
    reopened = Store(tmp_path/"ledger.sqlite", clock=lambda: now)
    result = reopened.receipt(actor, receipt["operation_id"], event_limit=1)
    events = result["progress"]["events"]
    while result["progress"]["has_more"]:
        result = reopened.receipt(actor, receipt["operation_id"],
                                  after=result["progress"]["cursor"], event_limit=1)
        events += result["progress"]["events"]
    diagnostics = [json.loads(e["message"].split(" ",1)[1]) for e in events
                   if e["message"].startswith("provider_diagnostic ")]
    failure = next(e for e in diagnostics if e["operation"]=="upload_file" and e["status"]=="failed")
    assert failure["operation_id"] == receipt["operation_id"]
    assert failure["publication_id"] == receipt["resource_id"]
    assert failure["attempt_id"] == result["deliveries"][0]["attempt_id"]
    assert failure["http_status"] == 503 and failure["retry_after_s"] == 7
    assert failure["dispatched"] is armed
    assert result["state"] == ("outcome_unknown" if armed else "blocked")
    assert result["retry_safe"] is False
    assert "SECRET" not in json.dumps(events)
    assert not await Worker(reopened, {"telegram":provider}).run_once()
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_telegram_retains_safe_rpc_code_and_flood_seconds():
    from adapters.telegram import TelegramAdapter
    class FloodWaitError(Exception):
        code = 420
        seconds = 17
    async def client(_):
        raise FloodWaitError("SECRET account and request")
    adapter = object.__new__(TelegramAdapter)
    adapter.client = client
    adapter.tl = SimpleNamespace(request=lambda kind, **kwargs: object())
    events = []
    with diagnostic_scope(events.append), pytest.raises(DomainError) as raised:
        await adapter._call("GetHistoryRequest", private="SECRET")
    assert raised.value.code == "telegram_cooldown"
    assert events[-1]["provider_code"] == 420
    assert events[-1]["retry_after_s"] == 17
    assert events[-1]["error_type"] == "FloodWaitError"
    assert "SECRET" not in json.dumps(events)


@pytest.mark.asyncio
async def test_vk_retains_safe_api_code_without_response_body():
    from adapters.vk_transport import VKHTTPTransport, VKToken
    class Transport(VKHTTPTransport):
        async def _post(self, *args, **kwargs):
            return {"error":{"error_code":15, "error_msg":"SECRET",
                             "request_params":[{"key":"access_token","value":"SECRET"}]}}
    transport = Transport(tokens={"reader":VKToken("fixture-not-a-live-token")})
    events = []
    with diagnostic_scope(events.append), pytest.raises(DomainError) as raised:
        await transport.invoke(role="reader",method="wall.getById",params={"posts":"-1_2"})
    assert raised.value.code == "vk_api_failed"
    assert events[-1]["operation"] == "wall.getById"
    assert events[-1]["provider_code"] == 15
    assert "SECRET" not in json.dumps(events)
