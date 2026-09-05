"""Test launcher for the UNMODIFIED archived Worker, with failure/gate hooks.

No replacement server/ledger/dispatch. FakeProvider is the archived TG/VK
fixture; MAX uses the existing FixtureDriver through its actual port bridge.
"""
import asyncio
import importlib
import json
import sys
from pathlib import Path

from adapters.fake import FakeProvider
from adapters.port import Hooks
from social_operations.storage import Store
from social_operations.worker import Worker
from playwright.async_api import async_playwright

MaxAdapter = importlib.import_module('adapters.max.bridge').MaxAdapter
FixtureDriver = importlib.import_module('adapters.max.driver').FixtureDriver
ProfileLane = importlib.import_module('adapters.max.profile').ProfileLane


async def main():
    root, origin, mode = sys.argv[1:]
    root = Path(root)
    store = Store(root/'ledger.sqlite')

    class ObservedWorker(Worker):
        def hooks(self, op, child=None, min_lead=60):
            real = super().hooks(op, child, min_lead)
            if not child or child['provider'] != 'max':
                return real

            async def emit(stage, status, evidence):
                await real.emit_progress(stage, status, evidence)
                if stage == 'uploading' and mode in {'gate', 'crash', 'revoke'}:
                    (root/'max-waiting').touch()
                    while not (root/'release-max').exists():
                        await asyncio.sleep(.025)
                if stage == 'reading_back' and mode == 'crash':
                    (root/'post-submit').touch()
                    await asyncio.Event().wait()

            async def before(attempt, plan):
                (root/'before-effect-entered').touch()
                if mode == 'callback_failure':
                    raise RuntimeError('Injected loss before core dispatch transaction')
                await real.before_effect(attempt, plan)
                # Separate connection reads the real committed SQLite marker.
                with store.connection() as db:
                    row = db.execute('SELECT dispatched,checkpoint FROM attempts WHERE id=?', (attempt,)).fetchone()
                    assert row['dispatched'] == 1
                    assert json.loads(row['checkpoint'])['adapter']['attempt'] == attempt
                (root/'core-marker-observed').touch()
                if mode == 'marker_crash':
                    (root/'post-marker').touch()
                    await asyncio.Event().wait()
            return Hooks(emit, real.checkpoint, before)

    with ProfileLane(root/'profile') as lane:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(str(lane.root/'chromium'), headless=True)
            try:
                await context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                page = context.pages[0]
                await page.goto(origin)
                driver = FixtureDriver(page, lane, origin=origin, account='fixture-account', allowed_targets=frozenset({'channel-a'}), timeout=60)
                adapters = {p: FakeProvider(root/'remote.sqlite', p) for p in ('telegram','vk')}
                adapters['max'] = MaxAdapter(driver, connection_id='max')
                await ObservedWorker(store, adapters).run_once()
            finally:
                await context.close()


if __name__ == '__main__':
    asyncio.run(main())
