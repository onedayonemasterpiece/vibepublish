"""Preflight diagnostics retain enums only and never retry a provider effect."""
import asyncio
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from adapters.max.bridge import MaxAdapter, _preflight_reason
from adapters.max.live import OpenBlocked, RealMaxDriver, Target
from adapters.max.profile import MaxBlocked, ProfileLane
from adapters.port import Hooks, ProviderRequest
from social_operations.domain import DomainError


SENTINEL = 'PRIVATE_CONTENT_URL_ACCOUNT_SENTINEL'
pytestmark = pytest.mark.asyncio


def request(**values):
    base = ProviderRequest('op', 'attempt', 'digest', 'max', 'max_web',
        'VIBEPUBLISH_MAX_PROFILE', 'destination', '-3', 'publish', 'post',
        json.dumps({'text': SENTINEL}), (), None, time.time() + 300)
    return replace(base, **values)


@pytest.fixture
def driver(tmp_path):
    with ProfileLane(tmp_path / 'profile') as lane:
        value = RealMaxDriver(
            SimpleNamespace(goto=AsyncMock()), lane,
            targets=(Target('-3', 'Synthetic channel', 'publish_channel'),),
            account_check=AsyncMock(return_value=True), live_writes=True)
        value._scope = AsyncMock()
        value.mutate = AsyncMock()
        yield value


def hooks():
    return Hooks(AsyncMock(), AsyncMock(), AsyncMock())


async def test_policy_blocker_is_precise_and_does_not_open_or_dispatch(driver):
    driver.lane.arm('older-attempt', 'older-plan')
    adapter = MaxAdapter(driver, connection_id='max')
    capability = await adapter.inspect(request())
    assert capability.status == 'needs_review'
    assert capability.evidence == 'max_web_dom'
    assert capability.reason == (
        'MAX preflight not verified: stage=mutation_preflight; reason=outcome_unknown')
    h = hooks()
    with pytest.raises(DomainError) as caught:
        await adapter.prepare(request(), h)
    assert caught.value.code == 'max_preflight_needs_review'
    assert caught.value.message == capability.reason
    assert caught.value.output()['retry_safe'] is False
    driver.page.goto.assert_not_awaited()
    driver.mutate.assert_not_awaited()
    h.before_effect.assert_not_awaited()
    h.checkpoint.assert_not_awaited()
    assert driver.lane.marker.exists()


@pytest.mark.parametrize('changes,reason', [
    ({'native_target': '-9'}, 'max_connection_or_target_denied'),
    ({'surface': 'story'}, 'max_surface_unsupported'),
    ({'account_type': 'fake'}, 'max_live_binding_mismatch'),
    ({'deadline': 0}, 'command_expired'),
])
async def test_validate_reason_stays_bounded(driver, changes, reason):
    adapter = MaxAdapter(driver, connection_id='max')
    capability = await adapter.inspect(request(**changes))
    assert capability.reason == f'MAX preflight not verified: stage=validate; reason={reason}'
    assert capability.evidence == 'max_web_dom'
    # Existing initial validation still raises its original typed error.
    with pytest.raises(DomainError) as caught:
        await adapter.prepare(request(**changes), hooks())
    assert caught.value.code == reason
    driver.page.goto.assert_not_awaited()
    driver.mutate.assert_not_awaited()


@pytest.mark.parametrize('phase', [
    'account_before', 'navigation', 'scope_before', 'account_after', 'scope_after',
])
@pytest.mark.parametrize('failure,category', [
    (TimeoutError, 'timeout'), (PlaywrightTimeoutError, 'timeout'),
    (AssertionError, 'ui_assertion_failed'), (RuntimeError, 'unavailable_ui'),
])
async def test_open_phase_and_category_never_export_exception_payload(driver, phase, failure, category):
    error = failure(SENTINEL)
    driver._account = AsyncMock(side_effect=[error] if phase == 'account_before'
                                else [None, error] if phase == 'account_after'
                                else None)
    if phase == 'navigation':
        driver.page.goto.side_effect = error
    if phase == 'scope_before':
        driver._scope.side_effect = error
    elif phase == 'scope_after':
        driver._scope.side_effect = [None, error]
    adapter = MaxAdapter(driver, connection_id='max')
    h = hooks()
    with pytest.raises(DomainError) as caught:
        await adapter.prepare(request(), h)
    assert caught.value.code == 'max_preflight_needs_review'
    assert caught.value.message == (
        f'MAX preflight not verified: stage=open_{phase}; reason={category}')
    assert SENTINEL not in json.dumps(caught.value.output())
    assert driver._busy is False
    assert not driver.lane.marker.exists()
    driver.mutate.assert_not_awaited()
    h.before_effect.assert_not_awaited()
    h.checkpoint.assert_not_awaited()
    assert driver.page.goto.await_count <= 1


async def test_known_open_blocker_preserves_original_code(driver):
    driver._scope.side_effect = MaxBlocked('wrong_target_or_origin')
    with pytest.raises(OpenBlocked) as caught:
        await driver.open('-3')
    assert str(caught.value) == 'wrong_target_or_origin'
    assert caught.value.phase == 'scope_before'
    assert caught.value.category == 'blocked'
    assert _preflight_reason('open', caught.value).endswith(
        'stage=open_scope_before; reason=wrong_target_or_origin')


@pytest.mark.parametrize('error', [
    MaxBlocked(SENTINEL), DomainError(SENTINEL, SENTINEL),
    OpenBlocked(SENTINEL, SENTINEL, SENTINEL),
])
async def test_unknown_diagnostic_fields_are_not_exported(error):
    result = _preflight_reason('open', error)
    assert result == 'MAX preflight not verified: stage=open; reason=unrecognized_blocker'
    assert _preflight_reason(SENTINEL, error) == (
        'MAX preflight not verified: stage=unknown; reason=unrecognized_blocker')


async def test_account_denial_has_fixed_reason_and_no_navigation(driver):
    driver.account_check.return_value = False
    capability = await MaxAdapter(driver, connection_id='max').inspect(request())
    assert capability.reason.endswith(
        'stage=open_account_before; reason=needs_auth_or_wrong_account')
    driver.page.goto.assert_not_awaited()


async def test_total_open_timeout_is_unchanged_and_labeled(driver):
    driver.timeout = 0.01
    async def slow_account():
        await asyncio.sleep(10)
    driver._account = slow_account
    with pytest.raises(OpenBlocked) as caught:
        await driver.open('-3')
    assert str(caught.value) == 'unfamiliar_or_unavailable_ui'
    assert caught.value.phase == 'account_before'
    assert caught.value.category == 'timeout'
    assert driver._busy is False
    driver.page.goto.assert_not_awaited()


async def test_cancellation_is_not_converted_to_capability_or_retried(driver):
    driver._account = AsyncMock(side_effect=asyncio.CancelledError(SENTINEL))
    with pytest.raises(asyncio.CancelledError):
        await MaxAdapter(driver, connection_id='max').inspect(request())
    assert driver._busy is False
    driver.page.goto.assert_not_awaited()
    driver.mutate.assert_not_awaited()


async def test_supported_preflight_keeps_original_request_and_no_effect(driver):
    adapter = MaxAdapter(driver, connection_id='max')
    r, h = request(), hooks()
    prepared = await adapter.prepare(r, h)
    assert prepared.request is r
    assert prepared.capability.status == 'supported'
    assert prepared.capability.evidence == 'max_web_dom'
    assert driver.account_check.await_count == 2
    assert driver._scope.await_count == 2
    driver.page.goto.assert_awaited_once_with('https://web.max.ru/-3', wait_until='domcontentloaded')
    driver.mutate.assert_not_awaited()
    h.before_effect.assert_not_awaited()
    assert not driver.lane.marker.exists()
