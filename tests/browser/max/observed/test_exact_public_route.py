"""Observed public SSR link recipe replayed in an isolated intercepted browser."""
import html
import json

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from adapters.max.discovery import probe
from adapters.max.live import RealMaxDriver
from adapters.max.profile import ProfileLane
from social_operations.domain import DomainError

URL = "https://max.ru/channel_exact"
WEB = "https://web.max.ru/channel_exact"
LABEL = "Exact public channel"

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def landing(tmp_path):
    state = dict(delay=0, status=200, native="-3", label=LABEL, editable=True,
                 channel_href="max://max.ru/channel_exact", web_href=WEB,
                 visits=[], external=[], checks=0)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(service_workers="block")
        async def route(request):
            url = request.request.url
            state["visits"].append(url)
            if url == URL:
                if state["status"] >= 400:
                    await request.fulfill(status=state["status"], content_type="text/html",
                                          body="<h1>Forbidden</h1>")
                    return
                # Exact roles/labels/hrefs were observed publicly on 2026-10-10.
                body = (
                    '<meta charset="utf-8"><h1>' + html.escape(LABEL) + "</h1><span>@channel_exact</span>"
                    + '<a aria-label="Перейти в канал" href="' + html.escape(state["channel_href"], quote=True)
                    + '">Перейти в канал</a>'
                    + '<a aria-label="Открыть в браузере" id="open" hidden href="'
                    + html.escape(state["web_href"], quote=True) + '">Открыть в браузере</a>'
                    + "<script>setTimeout(()=>document.getElementById('open').hidden=false,"
                    + str(state["delay"]) + ");</script>")
                await request.fulfill(content_type="text/html", body=body)
            elif url.startswith("https://web.max.ru/"):
                body = ('<meta charset="utf-8"><main aria-labelledby="main-header-title"><h2 id="main-header-title">'
                    + html.escape(state["label"]) + '</h2><button aria-label="Открыть профиль '
                    + html.escape(state["label"], quote=True) + '"></button>'
                    + '<div role="textbox" contenteditable="' + ("true" if state["editable"] else "false")
                    + '" data-lexical-editor="true"></div></main>')
                if url == WEB:
                    body += "<script>history.replaceState({},'',"+json.dumps("/"+state["native"])+");</script>"
                await request.fulfill(content_type="text/html", body=body)
            else:
                state["external"].append(url)
                await request.abort()
        await context.route("**/*", route)
        page = await context.new_page()
        async def account():
            state["checks"] += 1
            return True
        with ProfileLane(tmp_path / "profile") as lane:
            driver = RealMaxDriver(page, lane, targets=(), account_check=account, timeout=3,
                                   live_writes=True)
            yield driver, page, state
            assert driver.targets == {}
            assert not state["external"]
        await browser.close()


@pytest.mark.parametrize("delay", [0, 350])
async def test_exact_ssr_controls_support_channel_without_subscriber_text(landing, delay):
    driver, page, state = landing
    state["delay"] = delay
    evidence = await probe(driver, URL)
    assert evidence["native_id"] == "-3"
    assert evidence["label"] == LABEL and evidence["kind"] == "channel"
    assert evidence["publish_verified"] is True
    assert state["visits"] == [URL, WEB]
    assert state["checks"] == 2
    assert driver._busy is False


async def test_unrelated_prior_chat_does_not_select_destination_by_title(landing):
    driver, page, state = landing
    # Even a duplicated display title cannot authorize reuse of an unrelated ID.
    await page.goto("https://web.max.ru/-99")
    state["native"] = "-99"
    with pytest.raises(DomainError) as error:
        await probe(driver, URL)
    assert error.value.code == "max_native_channel_route_reused_unverified"
    assert driver._busy is False


async def test_prior_other_chat_can_navigate_to_a_fresh_exact_native_route(landing):
    driver, page, state = landing
    await page.goto("https://web.max.ru/-99")
    assert (await probe(driver, URL))["native_id"] == "-3"


async def test_existing_exact_public_url_binding_can_be_reverified(landing):
    driver, page, state = landing
    await page.goto("https://web.max.ru/-3")
    driver.binding_snapshot = {"targets": {"-3": {"public_url": URL}}}
    assert (await probe(driver, URL))["native_id"] == "-3"


@pytest.mark.parametrize("key,value", [
    ("channel_href", "max://max.ru/other_channel"),
    ("web_href", "https://web.max.ru/"),
    ("web_href", "https://web.max.ru/channel_other"),
    ("editable", False),
])
async def test_public_reference_kind_and_publishing_rights_still_fail_closed(landing, key, value):
    driver, page, state = landing
    state[key] = value
    with pytest.raises(DomainError) as error:
        await probe(driver, URL)
    expected = {"channel_href": "max_destination_not_channel",
                "web_href": "max_exact_channel_navigation_unverified",
                "editable": "max_channel_publish_permission_required"}
    assert error.value.code == expected[key]
    assert driver._busy is False


async def test_http_failure_is_explicit_bounded_and_never_follows_links(landing):
    driver, page, state = landing
    state["status"] = 403
    with pytest.raises(DomainError) as error:
        await probe(driver, URL)
    assert error.value.code == "max_public_landing_http_error"
    assert '"http_status":403' in str(error.value)
    assert state["visits"] == [URL]
