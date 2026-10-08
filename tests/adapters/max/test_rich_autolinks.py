"""MAX implicit autolink semantics stay strict without misclassifying plain text."""
import pytest

from adapters.max.rich import capture


@pytest.mark.asyncio
async def test_max_native_bare_domain_autolink_is_plain_text():
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            executable_path="/opt/google/chrome/chrome", headless=True
        )
        try:
            page = await browser.new_page()
            await page.set_content(
                '<div id="editor">'
                'Регистрация: <a href="https://vk.cc/d2gEay">vk.cc/d2gEay</a>'
                '</div>'
            )
            result = await capture(page.locator("#editor"))
            assert result == {
                "text": "Регистрация: vk.cc/d2gEay",
                "entities": [],
                "unsupported": False,
            }

            await page.set_content(
                '<div id="editor">'
                '<a href="https://vk.cc/d2gEay">Регистрация</a>'
                '</div>'
            )
            custom = await capture(page.locator("#editor"))
            assert custom["entities"] == [{
                "type": "text_link", "offset": 0,
                "length": len("Регистрация"), "url": "https://vk.cc/d2gEay"
            }]

            await page.set_content(
                '<div id="editor">'
                '<a href="https://wrong.example/path">vk.cc/d2gEay</a>'
                '</div>'
            )
            disguised = await capture(page.locator("#editor"))
            assert disguised["entities"] == [{
                "type": "text_link", "offset": 0,
                "length": len("vk.cc/d2gEay"), "url": "https://wrong.example/path"
            }]

            await page.set_content(
                '<div id="editor">'
                '<a href="http://vk.cc/d2gEay">vk.cc/d2gEay</a>'
                '</div>'
            )
            scheme_changed = await capture(page.locator("#editor"))
            assert scheme_changed["entities"] == [{
                "type": "text_link", "offset": 0,
                "length": len("vk.cc/d2gEay"), "url": "http://vk.cc/d2gEay"
            }]
        finally:
            await browser.close()
