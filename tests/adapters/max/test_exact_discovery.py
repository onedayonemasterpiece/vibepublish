"""Offline visible-surface replay; no browser, account, or real channel access."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from adapters.max import discovery
from adapters.max.live import RealMaxDriver, MAIN, COMPOSER
from adapters.max.profile import ProfileLane, MaxBlocked
from social_operations.domain import DomainError

URL = "https://max.ru/channel_exact"
WEB = "https://web.max.ru/-3"
TITLE = "Exact public channel"


class Element:
    def __init__(self, text="", href=None, visible=True, editable=False):
        self.text, self.href, self.visible, self.editable = text, href, visible, editable

    async def is_visible(self):
        return self.visible

    async def inner_text(self):
        return self.text

    async def get_attribute(self, attribute):
        assert attribute == "href"
        return self.href

    async def is_editable(self):
        return self.editable


class Collection:
    def __init__(self, elements):
        self.elements = elements

    async def all(self):
        return self.elements

    async def count(self):
        return len(self.elements)

    async def is_visible(self):
        return len(self.elements) == 1 and await self.elements[0].is_visible()

    async def is_editable(self):
        return len(self.elements) == 1 and await self.elements[0].is_editable()


class Main(Collection):
    def __init__(self, page):
        super().__init__([Element()])
        self.page = page

    def get_by_role(self, role, *, name, exact):
        assert role == "button" and exact
        return Collection([Element(visible=name == "Открыть профиль " + self.page.title)])

    def locator(self, selector):
        assert selector == COMPOSER
        return Collection([Element(editable=self.page.editable)]) if self.page.has_composer else Collection([])


class Page:
    def __init__(self, *, links=None, public_redirect=None, native_redirect=None,
                 marker=True, hidden_marker=False, editable=True, title=TITLE):
        self.url = "https://web.max.ru/"
        self.links = links if links is not None else [Element(href=WEB)]
        self.headings = [Element(text=TITLE)]
        self.public_redirect = public_redirect
        self.native_redirect = native_redirect
        self.marker = marker
        self.hidden_marker = hidden_marker
        self.editable = editable
        self.has_composer = True
        self.title = title
        self.visits = []

    async def goto(self, url, **kwargs):
        self.visits.append(url)
        self.url = (self.public_redirect or url) if url == URL else (self.native_redirect or url)

    async def wait_for_url(self, pattern, **kwargs):
        if not pattern.fullmatch(self.url):
            raise MaxBlocked("native_channel_route_unverified")

    def get_by_role(self, role):
        assert role in {"heading", "link"}
        return Collection(self.headings if role == "heading" else self.links)

    def get_by_text(self, pattern):
        assert pattern is discovery.SUBSCRIBERS
        return Collection([Element(visible=not self.hidden_marker)] if self.marker else [])

    def locator(self, selector):
        assert selector == MAIN
        return Main(self)


class Expected:
    def __init__(self, locator):
        self.locator = locator

    async def to_have_count(self, count, **kwargs):
        if await self.locator.count() != count:
            raise MaxBlocked("unexpected_count")

    async def to_be_visible(self, **kwargs):
        if not await self.locator.is_visible():
            raise MaxBlocked("exact_title_unverified")


@pytest.fixture(autouse=True)
def expected(monkeypatch):
    monkeypatch.setattr(discovery, "expect", Expected)


async def probe(tmp_path, page):
    with ProfileLane(tmp_path / "profile") as lane:
        account = AsyncMock(return_value=True)
        driver = RealMaxDriver(page, lane, targets=(), account_check=account, live_writes=True)
        value = await discovery.probe(driver, URL)
        assert driver.targets == {}
        assert driver._busy is False
        assert account.await_count == 2
        return value


@pytest.mark.asyncio
async def test_exact_public_channel_and_composer_are_read_only(tmp_path):
    page = Page()
    evidence = await probe(tmp_path, page)
    assert evidence == dict(url=URL, native_id="-3", label=TITLE,
        kind="channel", publish_verified=True, source="max_web_visible_channel")
    assert page.visits == [URL, WEB]


@pytest.mark.asyncio
async def test_hidden_link_does_not_create_ambiguity_and_duplicates_deduplicate(tmp_path):
    page = Page(links=[Element(href=WEB), Element(href=WEB), Element(href="https://web.max.ru/-4", visible=False)])
    assert (await probe(tmp_path, page))["native_id"] == "-3"


@pytest.mark.asyncio
@pytest.mark.parametrize("link", [
    "http://web.max.ru/-3", "https://web.max.ru:443/-3",
    "https://web.max.ru.evil/-3", "https://user@web.max.ru/-3",
    "https://evil.example/-3",
])
async def test_untrusted_web_link_is_not_followed(tmp_path, link):
    page = Page(links=[Element(href=link)])
    with pytest.raises(DomainError, match="MAX exact resolution blocked"):
        await probe(tmp_path, page)
    assert page.visits == [URL]


@pytest.mark.asyncio
async def test_hidden_only_link_is_not_followed(tmp_path):
    page = Page(links=[Element(href=WEB, visible=False)])
    with pytest.raises(DomainError):
        await probe(tmp_path, page)
    assert page.visits == [URL]


@pytest.mark.asyncio
async def test_two_unique_visible_links_are_ambiguous(tmp_path):
    page = Page(links=[Element(href=WEB), Element(href="https://web.max.ru/-4")])
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, page)
    assert error.value.code == "max_exact_channel_navigation_unverified"
    assert page.visits == [URL]


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect", [
    "https://evil.example/", "https://max.ru/channel_different",
    "https://max.ru:443/channel_exact", "https://user@max.ru/channel_exact",
])
async def test_public_redirect_never_becomes_authority(tmp_path, redirect):
    page = Page(public_redirect=redirect)
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, page)
    assert error.value.code == "max_exact_public_landing_unverified"
    assert page.visits == [URL]


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect", ["https://evil.example/", "https://web.max.ru/-99"])
async def test_native_target_substitution_is_refused(tmp_path, redirect):
    page = Page(native_redirect=redirect)
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, page)
    assert error.value.code == "max_native_channel_route_unverified"


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"marker": False}, {"hidden_marker": True}])
async def test_channel_kind_must_be_visible(tmp_path, kwargs):
    page = Page(**kwargs)
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, page)
    assert error.value.code == "max_destination_not_channel"
    assert page.visits == [URL]


@pytest.mark.asyncio
async def test_composer_must_prove_current_publication_rights(tmp_path):
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, Page(editable=False))
    assert error.value.code == "max_channel_publish_permission_required"


@pytest.mark.asyncio
async def test_exact_public_title_must_match_native_visible_header(tmp_path):
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, Page(title="Different channel"))
    assert error.value.code == "max_exact_title_unverified"


@pytest.mark.asyncio
async def test_diagnostics_strip_web_query_fragment_and_private_exception(tmp_path):
    page = Page(links=[Element(href="https://web.max.ru/?secret=PRIVATE_SENTINEL#private")])
    page.native_redirect = "https://web.max.ru/"
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, page)
    assert "PRIVATE_SENTINEL" not in str(error.value)
    assert "secret" not in str(error.value)
    assert "#private" not in str(error.value)
    page = Page()
    page.goto = AsyncMock(side_effect=RuntimeError("PRIVATE_SENTINEL"))
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, page)
    assert "PRIVATE_SENTINEL" not in str(error.value)
    assert "RuntimeError" in str(error.value)


@pytest.mark.asyncio
async def test_generic_web_home_cannot_reopen_unrelated_chat(tmp_path):
    page = Page(links=[Element(href="https://web.max.ru/?utm_source=public")], native_redirect=WEB)
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, page)
    assert error.value.code == "max_exact_channel_navigation_unverified"
    assert page.visits == [URL]


@pytest.mark.asyncio
async def test_observed_exact_public_reference_can_navigate_to_native_route(tmp_path):
    page = Page(links=[Element(href="https://web.max.ru/?url=" + URL)], native_redirect=WEB)
    assert (await probe(tmp_path, page))["native_id"] == "-3"


@pytest.mark.asyncio
async def test_truncated_landing_never_hides_ambiguity(tmp_path):
    page = Page(links=[Element(href=WEB)] * 64 + [Element(href="https://web.max.ru/-9")])
    with pytest.raises(DomainError) as error:
        await probe(tmp_path, page)
    assert error.value.code == "max_public_landing_bound_exceeded"
    assert page.visits == [URL]


@pytest.mark.parametrize("text", ["1 подписчик", "2 подписчика", "10 подписчиков", "Подписчики"])
def test_observed_russian_channel_markers(text):
    assert discovery.SUBSCRIBERS.search(text)
