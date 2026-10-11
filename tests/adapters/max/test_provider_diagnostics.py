"""MAX diagnostics observe original failures without retrying native effects."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from adapters.max import live
from adapters.max.diagnostics import observe, observed
from adapters.max.live import OpenBlocked, RealMaxDriver, Target
from adapters.max.profile import MaxBlocked, ProfileLane
from adapters.port import Hooks
from social_operations.provider_diagnostics import diagnostic_scope

pytestmark = pytest.mark.asyncio
PRIVATE = "PRIVATE_CONTENT_URL_ACCOUNT_SENTINEL"


async def test_observe_preserves_result_and_emits_before_await():
    records = []
    value = object()

    async def effect():
        assert records == [{"provider": "max", "operation": "submit", "status": "started"}]
        return value

    call = AsyncMock(side_effect=effect)
    with diagnostic_scope(records.append):
        assert await observe("submit", call()) is value
    call.assert_awaited_once()
    assert records[-1]["status"] == "completed"
    assert records[-1]["duration_ms"] >= 0


@pytest.mark.parametrize("kind", [TimeoutError, asyncio.CancelledError, MaxBlocked])
async def test_observe_keeps_original_exception_and_never_exports_message(kind):
    error = kind(PRIVATE)
    call = AsyncMock(side_effect=error)
    records = []
    with diagnostic_scope(records.append):
        with pytest.raises(kind) as caught:
            await observe("media_download", call())
    assert caught.value is error
    call.assert_awaited_once()
    assert records[-1]["status"] == "failed"
    assert records[-1]["error_type"] == kind.__name__
    assert records[-1]["duration_ms"] >= 0
    assert PRIVATE not in json.dumps(records)


async def test_decorator_preserves_method_result_and_metadata():
    class Driver:
        @observed("calendar")
        async def set_time(self, value):
            """Original method."""
            return value

    records = []
    with diagnostic_scope(records.append):
        assert await Driver().set_time(42) == 42
    assert Driver.set_time.__name__ == "set_time"
    assert Driver.set_time.__doc__ == "Original method."
    assert [r["status"] for r in records] == ["started", "completed"]


@pytest.fixture
def driver(tmp_path):
    with ProfileLane(tmp_path / "profile") as lane:
        value = RealMaxDriver(
            SimpleNamespace(goto=AsyncMock()), lane,
            targets=(Target("-3", "Synthetic channel", "publish_channel"),),
            account_check=AsyncMock(return_value=True), live_writes=True)
        value._scope = AsyncMock()
        yield value


async def test_navigation_failure_recorded_before_open_sanitization(driver):
    driver.page.goto.side_effect = TimeoutError(PRIVATE)
    records = []
    with diagnostic_scope(records.append):
        with pytest.raises(OpenBlocked) as caught:
            await driver.open("-3")
    assert caught.value.phase == "navigation"
    assert caught.value.category == "timeout"
    failed = [r for r in records if r["status"] == "failed"]
    assert failed[-1]["operation"] == "navigation"
    assert failed[-1]["error_type"] == "TimeoutError"
    assert PRIVATE not in json.dumps(records)
    assert not driver.lane.marker.exists()
    driver.page.goto.assert_awaited_once()


@pytest.mark.parametrize("failure_phase", ["submit", "candidate_wait"])
async def test_post_arm_failure_keeps_original_diagnostic_and_unknown_outcome(driver, failure_phase):
    error = TimeoutError(PRIVATE)
    button = SimpleNamespace(click=AsyncMock(side_effect=error if failure_phase == "submit" else None))
    composer = SimpleNamespace(evaluate=AsyncMock(side_effect=["[]", "text"]))
    observer = SimpleNamespace(evaluate=AsyncMock(return_value=True), dispose=AsyncMock())
    rows = SimpleNamespace(count=AsyncMock(return_value=0))
    main = SimpleNamespace(
        evaluate_handle=AsyncMock(return_value=observer),
        get_by_role=Mock(return_value=button), locator=Mock(return_value=composer))
    driver._scope.return_value = main
    driver._rows = Mock(return_value=rows)
    driver._compose = AsyncMock(return_value=(composer, []))
    hooks = Hooks(AsyncMock(), AsyncMock(), AsyncMock())
    expectation = SimpleNamespace(to_have_count=AsyncMock(side_effect=error))
    records = []
    with diagnostic_scope(records.append), patch.object(live, "expect", return_value=expectation):
        with pytest.raises(MaxBlocked, match="^outcome_unknown$"):
            await driver.submit_plain_candidate(
                target="-3", text="text", attempt_id="attempt", plan_digest="plan", hooks=hooks)
    failed = [r for r in records if r["status"] == "failed"]
    assert failed[-1]["operation"] == failure_phase
    assert failed[-1]["error_type"] == "TimeoutError"
    assert PRIVATE not in json.dumps(records)
    button.click.assert_awaited_once()
    hooks.before_effect.assert_awaited_once_with("attempt", "plan")
    assert driver.lane.marker.exists()
    assert driver._busy is False


@pytest.mark.parametrize("reason", [
    "existing_draft", "native_calendar_unfamiliar", "rich_selection_changed",
])
async def test_known_leaf_guard_reason_is_retained(reason):
    records = []
    error = MaxBlocked(reason)
    with diagnostic_scope(records.append):
        with pytest.raises(MaxBlocked) as caught:
            await observe("compose", AsyncMock(side_effect=error)())
    assert caught.value is error
    assert records[-1]["error_code"] == reason
    assert records[-1]["error_type"] == "MaxBlocked"


@pytest.mark.parametrize("reason", [PRIVATE, "private_token_without_spaces",
                                    "https://private.example/account"])
async def test_unknown_guard_reason_is_never_exported(reason):
    records = []
    error = MaxBlocked(reason)
    with diagnostic_scope(records.append):
        with pytest.raises(MaxBlocked) as caught:
            await observe("compose", AsyncMock(side_effect=error)())
    assert caught.value is error
    assert "error_code" not in records[-1]
    assert reason not in json.dumps(records)
