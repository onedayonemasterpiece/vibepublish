"""Compose failures retain location, never content or hidden effect retries."""
import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from adapters.max.live import RealMaxDriver, COMPOSER
from adapters.max import live

class ComposeDiagnosticsTest(IsolatedAsyncioTestCase):
    def surface(self):
        composer=SimpleNamespace(evaluate=AsyncMock(return_value=''))
        attached=SimpleNamespace(count=AsyncMock(return_value=0))
        button=SimpleNamespace(click=AsyncMock())
        main=SimpleNamespace(
            locator=Mock(side_effect=lambda selector:composer if selector==COMPOSER else attached),
            get_by_role=Mock(return_value=button))
        driver=SimpleNamespace(page=object(),timeout=90)
        return driver,main,composer,button

    async def test_upload_menu_timeout_is_precise_private_and_not_retried(self):
        driver,main,composer,button=self.surface()
        original=TimeoutError('PRIVATE_SENTINEL_POST_AND_URL')
        button.click.side_effect=original
        expected=SimpleNamespace(to_have_count=AsyncMock())
        with patch.object(live,'expect',return_value=expected), self.assertLogs('adapters.max.live',level='WARNING') as logs:
            with self.assertRaises(TimeoutError) as caught:
                await RealMaxDriver._compose(driver,main,'PRIVATE_SENTINEL_POST_AND_URL',
                    ({'mimeType':'image/jpeg','name':'0.jpg','buffer':b'x'},),())
        self.assertIs(caught.exception,original)
        button.click.assert_awaited_once()
        output=' '.join(logs.output)
        self.assertIn('step=upload_menu',output)
        self.assertIn('error_type=TimeoutError',output)
        self.assertIn('live.py:',output)
        self.assertNotIn('PRIVATE_SENTINEL',output)

    async def test_rich_text_timeout_and_cancellation_keep_original(self):
        for kind in (TimeoutError,asyncio.CancelledError):
            with self.subTest(kind=kind.__name__):
                driver,main,composer,button=self.surface()
                original=kind('PRIVATE_SENTINEL')
                expected=SimpleNamespace(to_have_count=AsyncMock())
                with patch.object(live,'expect',return_value=expected), patch.object(live.rich,'fill',AsyncMock(side_effect=original)) as fill, self.assertLogs('adapters.max.live',level='WARNING') as logs:
                    with self.assertRaises(kind) as caught:
                        await RealMaxDriver._compose(driver,main,'PRIVATE_SENTINEL',(),())
                self.assertIs(caught.exception,original)
                fill.assert_awaited_once()
                button.click.assert_not_awaited()
                self.assertIn('step=rich_text',' '.join(logs.output))
                self.assertNotIn('PRIVATE_SENTINEL',' '.join(logs.output))

    async def test_success_is_unchanged(self):
        driver,main,composer,button=self.surface()
        expected=SimpleNamespace(to_have_count=AsyncMock())
        with patch.object(live,'expect',return_value=expected), patch.object(live.rich,'fill',AsyncMock()) as fill:
            result=await RealMaxDriver._compose(driver,main,'text',(),())
        self.assertEqual(result,(composer,[]))
        fill.assert_awaited_once_with(driver.page,composer,'text',())
        button.click.assert_not_awaited()
