"""Only run by the local synthetic crash test; never a runtime entrypoint."""
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ProfileLane = importlib.import_module('adapters.max.profile').ProfileLane
FixtureDriver = importlib.import_module('adapters.max.driver').FixtureDriver


async def main():
    origin, root = sys.argv[1:]
    root = Path(root)
    class Hooks:
        async def emit_progress(self, stage, status, evidence):
            if stage == 'reading_back':
                # Parent waits for independent server effect THEN kills process
                # group. No fake exception in place of actual process death.
                (root/'post-submit').touch()
                await asyncio.Event().wait()

        async def checkpoint(self, transition, state):
            if transition == 'MAX_PREPARED':
                with (root/'checkpoint.json').open('w') as stream:
                    stream.write(state)
                    stream.flush()
                    os.fsync(stream.fileno())

        async def before_effect(self, attempt, digest):
            with (root/'test-dispatch-marker').open('w') as stream:
                stream.write(attempt)
                stream.flush()
                os.fsync(stream.fileno())

    with ProfileLane(root/'profile') as lane:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(str(lane.root/'chromium'), headless=True)
            await context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
            page = context.pages[0]
            await page.goto(origin)
            driver = FixtureDriver(page, lane, origin=origin, account='fixture-account', allowed_targets=frozenset({'channel-a'}))
            await driver.mutate(target='channel-a', text='crash fixture',
                                media=({'name':'fixture.png','mimeType':'image/png','buffer':b'fixture-bytes'},),
                                scheduled_at=None, action='publish', attempt_id='one', plan_digest='one', hooks=Hooks())


if __name__ == '__main__':
    asyncio.run(main())
