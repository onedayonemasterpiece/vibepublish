"""Bounded exact-link navigation. Never search, join, type, or submit."""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import expect

from adapters.max_discovery import parse_destination_url
from social_operations.domain import DomainError
from .profile import MaxBlocked

NATIVE = re.compile(r"^https://web\.max\.ru/(-[1-9][0-9]{0,19})$")
SUBSCRIBERS = re.compile(r"\bподписчик(?:ов|а|и)?\b", re.IGNORECASE)


def navigation_link(value):
    """Only an observed exact native route can prove the landing-to-chat link."""
    if not isinstance(value, str):
        return None
    match = NATIVE.fullmatch(value)
    return match.group(1) if match else None


async def probe(driver, url):
    from .live import MAIN, COMPOSER
    url = parse_destination_url(url)
    driver.lane.owned()
    if driver._busy:
        raise MaxBlocked("profile_busy")
    driver._busy = True
    diagnostic = {"stage": "account", "heading_count": 0, "native_links": [], "web_link_paths": [],
                  "channel_marker": False, "main_count": 0, "composer_count": 0}
    try:
        async with asyncio.timeout(driver.timeout):
            await driver._account()
            diagnostic["stage"] = "public_landing"
            await driver.page.goto(url, wait_until="domcontentloaded")
            current = urlsplit(driver.page.url)
            if current.scheme != "https" or current.netloc != "max.ru" or driver.page.url.rstrip("/") != url:
                raise MaxBlocked("exact_public_landing_unverified")
            # Public channel landing only; no account sidebar/message content.
            headings = driver.page.get_by_role("heading")
            if await headings.count() > 12:
                raise MaxBlocked("public_landing_bound_exceeded")
            visible = []
            for heading in (await headings.all())[:12]:
                if await heading.is_visible():
                    value = (await heading.inner_text()).strip()
                    if value and len(value) <= 200:
                        visible.append(value)
            diagnostic["heading_count"] = len(visible)
            links = driver.page.get_by_role("link")
            if await links.count() > 64:
                raise MaxBlocked("public_landing_bound_exceeded")
            native = set()
            web_links = set()
            for link in (await links.all())[:64]:
                if await link.is_visible():
                    href = await link.get_attribute("href")
                    identity = navigation_link(href)
                    parsed = urlsplit(href or "")
                    if (parsed.scheme == "https" and parsed.netloc == "web.max.ru"
                            and len(href) <= 1024 and not any(c.isspace() for c in href)):
                        # A generic Web home link can reopen the previous chat.
                        # Require a native route or this exact public reference.
                        handle = url.rsplit("/", 1)[1]
                        values = [v for group in parse_qs(parsed.query).values() for v in group]
                        if (identity or parsed.path.rstrip("/") == "/" + handle
                                or any(v in {url, handle} for v in values)):
                            web_links.add(href)
                    if identity:
                        native.add(identity)
            diagnostic["native_links"] = sorted(native)[:8]
            diagnostic["web_link_paths"] = sorted({urlsplit(link).path[:160] for link in web_links})[:8]
            marker = driver.page.get_by_text(SUBSCRIBERS)
            diagnostic["channel_marker"] = any([
                await item.is_visible() for item in (await marker.all())[:16]
            ])
            if len(visible) != 1 or len(web_links) != 1:
                raise MaxBlocked("exact_channel_navigation_unverified")
            if not diagnostic["channel_marker"]:
                raise MaxBlocked("destination_not_channel")
            label = visible[0]
            diagnostic["stage"] = "native_channel"
            # Follow only the link observed on this exact public landing page.
            if driver.origin != "https://web.max.ru":
                raise MaxBlocked("max_origin_denied")
            await driver.page.goto(next(iter(web_links)), wait_until="domcontentloaded")
            await driver.page.wait_for_url(NATIVE, timeout=driver.timeout * 1000)
            target = navigation_link(driver.page.url)
            if target is None or (native and native != {target}):
                raise MaxBlocked("native_channel_route_unverified")
            main = driver.page.locator(MAIN)
            await expect(main).to_have_count(1)
            diagnostic["main_count"] = await main.count()
            header = main.get_by_role("button", name="Открыть профиль " + label, exact=True)
            await expect(header).to_be_visible()
            driver._route(target)
            composer = main.locator(COMPOSER)
            diagnostic["composer_count"] = await composer.count()
            if await composer.count() != 1 or not await composer.is_visible() or not await composer.is_editable():
                raise MaxBlocked("channel_publish_permission_required")
            # An existing draft may be observed but is never edited by resolve.
            await driver._account()
            driver._route(target)
            await expect(header).to_be_visible()
            if not await composer.is_editable():
                raise MaxBlocked("channel_publish_permission_required")
            return {"url": url, "native_id": target, "label": label, "kind": "channel",
                    "publish_verified": True, "source": "max_web_visible_channel"}
    except (MaxBlocked, DomainError) as exc:
        if isinstance(exc, DomainError):
            raise
        raise DomainError("max_" + str(exc),
            "MAX exact resolution blocked: " + json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":")),
            next_action="contact_owner") from None
    except Exception as exc:
        diagnostic["error_type"] = type(exc).__name__
        raise DomainError("max_exact_channel_ui_unavailable",
            "MAX exact resolution blocked: " + json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":")),
            next_action="refresh") from None
    finally:
        driver._busy = False
