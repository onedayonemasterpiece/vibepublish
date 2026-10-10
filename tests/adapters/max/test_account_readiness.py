"""Shared visible-account readiness budgets; no browser or live profile access."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from adapters.max import account
from adapters.max.account import VisibleAccountCheck
from adapters.max.bridge import MaxAdapter
from adapters.max.live import RealMaxDriver, Target
from adapters.max.profile import MaxBlocked, ProfileLane
from adapters.port import ProviderRequest

pytestmark = pytest.mark.asyncio
PRIVATE = 'SYNTHETIC_PRIVATE_ACCOUNT_SENTINEL'


def surface():
    settings = SimpleNamespace(wait_for=AsyncMock(), click=AsyncMock())
    phone = SimpleNamespace(wait_for=AsyncMock(), inner_text=AsyncMock(return_value=PRIVATE))
    page = SimpleNamespace(goto=AsyncMock(), get_by_role=Mock(return_value=settings),
                           locator=Mock(return_value=phone))
    return page, settings, phone


def make_driver(tmp_path, check, lane, timeout=90):
    driver = RealMaxDriver(SimpleNamespace(goto=AsyncMock()), lane,
        targets=(Target('-3', 'Synthetic channel', 'publish_channel'),),
        account_check=check, timeout=timeout, live_writes=True)
    driver._scope = AsyncMock()
    driver.mutate = AsyncMock()
    return driver


def request(deadline):
    return ProviderRequest('op', 'attempt', 'plan', 'max', 'max_web',
        'VIBEPUBLISH_MAX_PROFILE', 'destination', '-3', 'publish', 'post',
        json.dumps({'text': 'Synthetic post'}), (), None, deadline)


async def test_every_step_consumes_one_decreasing_budget(monkeypatch):
    page, settings, phone = surface()
    monkeypatch.setattr(account, 'time', SimpleNamespace(
        monotonic=Mock(side_effect=[100, 100, 115, 120, 145, 150])))
    check = VisibleAccountCheck(page, PRIVATE, timeout=90)
    assert await check() is True
    page.goto.assert_awaited_once_with('https://web.max.ru/', wait_until='domcontentloaded', timeout=90000)
    page.get_by_role.assert_called_once_with('button', name='Настройки', exact=True)
    page.locator.assert_called_once_with('aside .phone')
    settings.wait_for.assert_awaited_once_with(state='visible', timeout=75000)
    settings.click.assert_awaited_once_with(timeout=70000)
    phone.wait_for.assert_awaited_once_with(state='visible', timeout=45000)
    phone.inner_text.assert_awaited_once_with(timeout=40000)
    assert check.phase == 'phone'


async def test_exhausted_remainder_never_passes_timeout_zero(monkeypatch):
    page, settings, phone = surface()
    monkeypatch.setattr(account, 'time', SimpleNamespace(
        monotonic=Mock(side_effect=[0, 0, 91])))
    check = VisibleAccountCheck(page, PRIVATE, timeout=90)
    with pytest.raises(TimeoutError):
        await check()
    assert check.phase == 'settings'
    settings.wait_for.assert_not_awaited()
    settings.click.assert_not_awaited()
    phone.inner_text.assert_not_awaited()


async def test_total_checker_deadline_does_not_reset_per_step():
    page, settings, phone = surface()
    async def slow(**_):
        await asyncio.sleep(0.025)
    page.goto.side_effect = lambda *args, **kwargs: None
    settings.wait_for.side_effect = slow
    settings.click.side_effect = slow
    phone.wait_for.side_effect = slow
    check = VisibleAccountCheck(page, PRIVATE, timeout=0.06)
    with pytest.raises(TimeoutError):
        await check()
    assert check.phase == 'phone'
    phone.inner_text.assert_not_awaited()


@pytest.mark.parametrize('phase', ['navigation', 'settings', 'phone'])
@pytest.mark.parametrize('error', [PlaywrightTimeoutError, RuntimeError])
async def test_account_subphase_is_bounded_in_preflight(tmp_path, phase, error):
    page, settings, phone = surface()
    step = {'navigation': page.goto, 'settings': settings.wait_for,
            'phone': phone.wait_for}[phase]
    step.side_effect = error(PRIVATE)
    check = VisibleAccountCheck(page, PRIVATE, timeout=90)
    with ProfileLane(tmp_path / 'profile') as lane:
        driver = make_driver(tmp_path, check, lane)
        capability = await MaxAdapter(driver, connection_id='max').inspect(request(time.time()+300))
        category = 'timeout' if error is PlaywrightTimeoutError else 'unavailable_ui'
        assert capability.reason == (
            f'MAX preflight not verified: stage=open_account_before_{phase}; reason={category}')
        assert PRIVATE not in capability.reason
        driver.page.goto.assert_not_awaited()
        driver.mutate.assert_not_awaited()
        assert not lane.marker.exists()


async def test_operation_deadline_caps_account_readiness_and_retains_phase(tmp_path):
    page, settings, phone = surface()
    started = asyncio.Event()
    async def never_ready(**_):
        started.set()
        await asyncio.Event().wait()
    settings.wait_for.side_effect = never_ready
    check = VisibleAccountCheck(page, PRIVATE, timeout=90)
    with ProfileLane(tmp_path / 'profile') as lane:
        driver = make_driver(tmp_path, check, lane)
        start = time.monotonic()
        capability = await MaxAdapter(driver, connection_id='max').inspect(request(time.time()+0.1))
        assert started.is_set()
        assert time.monotonic()-start < 1
        assert capability.reason.endswith('stage=open_account_before_settings; reason=timeout')
        settings.click.assert_not_awaited()
        driver.page.goto.assert_not_awaited()
        driver.mutate.assert_not_awaited()
        assert not driver._busy


async def test_outer_budget_covers_both_account_checks_without_reset(tmp_path):
    page, settings, phone = surface()
    async def slow(**_):
        await asyncio.sleep(0.04)
    settings.wait_for.side_effect = slow
    check = VisibleAccountCheck(page, PRIVATE, timeout=90)
    with ProfileLane(tmp_path / 'profile') as lane:
        driver = make_driver(tmp_path, check, lane, timeout=0.06)
        capability = await MaxAdapter(driver, connection_id='max').inspect(request(time.time()+300))
        assert capability.reason.endswith('stage=open_account_after_settings; reason=timeout')
        assert page.goto.await_count == 2
        assert settings.click.await_count == 1
        driver.page.goto.assert_awaited_once()
        driver.mutate.assert_not_awaited()


async def test_expired_deadline_has_no_account_or_target_navigation(tmp_path):
    page, settings, phone = surface()
    check = VisibleAccountCheck(page, PRIVATE, timeout=90)
    check.phase = 'phone'  # Previous warm observation must not label this failure.
    with ProfileLane(tmp_path / 'profile') as lane:
        driver = make_driver(tmp_path, check, lane)
        with pytest.raises(MaxBlocked, match='command_expired'):
            await driver.open('-3', deadline=time.time()-1)
        page.goto.assert_not_awaited()
        driver.page.goto.assert_not_awaited()
        assert not driver._busy


@pytest.mark.parametrize('observed', ['other-synthetic-account', ' '+PRIVATE, PRIVATE+' '])
async def test_wrong_or_normalized_account_never_passes_exact_gate(tmp_path, observed):
    page, settings, phone = surface()
    phone.inner_text.return_value = observed
    check = VisibleAccountCheck(page, PRIVATE, timeout=90)
    with ProfileLane(tmp_path / 'profile') as lane:
        driver = make_driver(tmp_path, check, lane)
        capability = await MaxAdapter(driver, connection_id='max').inspect(request(time.time()+300))
        assert capability.reason.endswith(
            'stage=open_account_before_phone; reason=needs_auth_or_wrong_account')
        assert observed not in capability.reason
        driver.page.goto.assert_not_awaited()
        driver.mutate.assert_not_awaited()


async def test_warm_recheck_reads_identity_again():
    page, settings, phone = surface()
    check = VisibleAccountCheck(page, PRIVATE, timeout=90)
    assert await check() is True
    phone.inner_text.return_value = 'different-synthetic-account'
    assert await check() is False
    assert page.goto.await_count == 2
    assert phone.inner_text.await_count == 2


async def test_external_cancellation_is_never_converted(tmp_path):
    page, settings, phone = surface()
    settings.wait_for.side_effect = asyncio.CancelledError(PRIVATE)
    check = VisibleAccountCheck(page, PRIVATE, timeout=90)
    with ProfileLane(tmp_path / 'profile') as lane:
        driver = make_driver(tmp_path, check, lane)
        with pytest.raises(asyncio.CancelledError):
            await MaxAdapter(driver, connection_id='max').inspect(request(time.time()+300))
        assert check.phase == 'settings'
        assert not driver._busy
        settings.click.assert_not_awaited()
        driver.page.goto.assert_not_awaited()
