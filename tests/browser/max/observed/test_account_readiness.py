"""Real-browser replay of the existing Settings/phone account recipe only."""
import json
import time

import pytest
from playwright.async_api import async_playwright, Error as PlaywrightError

from adapters.max.account import VisibleAccountCheck

pytestmark = pytest.mark.asyncio
ACCOUNT = 'synthetic-bound-account'


def html(*, settings_delay=0, phone_delay=0, observed=ACCOUNT, logged_out=False, duplicate=False):
    if logged_out:
        return '<!doctype html><meta charset="utf-8"><h1>Sign in with phone number</h1>'
    button = '<button id="settings" style="display:none">Настройки</button>'
    if duplicate:
        button += '<button>Настройки</button>'
    return ('<!doctype html><meta charset="utf-8">' + button
        + '<aside><span class="phone" style="display:none"></span></aside><script>'
        + 'const settings=document.querySelector("#settings"), phone=document.querySelector(".phone");'
        + 'phone.textContent=' + json.dumps(observed) + ';'
        + 'setTimeout(()=>settings.style.display="block",' + str(settings_delay) + ');'
        + 'settings.onclick=()=>setTimeout(()=>phone.style.display="block",' + str(phone_delay) + ');'
        + '</script>')


@pytest.mark.parametrize('delayed', ['settings', 'phone'])
async def test_authenticated_cold_readiness_over_ten_seconds_then_fresh_warm_check(delayed):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        visits = []
        async def route(request):
            visits.append(request.request.url)
            assert request.request.url == 'https://web.max.ru/'
            cold = len(visits) == 1
            document = html(settings_delay=10100 if cold and delayed == 'settings' else 0,
                            phone_delay=10100 if cold and delayed == 'phone' else 0)
            await request.fulfill(status=200, content_type='text/html', body=document)
        await page.route('**/*', route)
        try:
            check = VisibleAccountCheck(page, ACCOUNT, timeout=20)
            start = time.monotonic()
            assert await check() is True
            assert time.monotonic()-start >= 10
            assert await check() is True
            assert visits == ['https://web.max.ru/', 'https://web.max.ru/']
            assert check.phase == 'phone'
        finally:
            await browser.close()


@pytest.mark.parametrize('state', ['logged_out', 'wrong_account', 'duplicate'])
async def test_unverified_identity_never_passes_visible_account_gate(state):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        requests = []
        async def route(request):
            requests.append(request.request.url)
            assert request.request.url == 'https://web.max.ru/'
            await request.fulfill(status=200, content_type='text/html',
                body=html(logged_out=state == 'logged_out', duplicate=state == 'duplicate',
                          observed='another-synthetic-account'))
        await page.route('**/*', route)
        try:
            check = VisibleAccountCheck(page, ACCOUNT, timeout=1)
            if state == 'wrong_account':
                assert await check() is False
                assert check.phase == 'phone'
            else:
                with pytest.raises((TimeoutError, PlaywrightError)):
                    await check()
            assert requests == ['https://web.max.ru/']
        finally:
            await browser.close()
