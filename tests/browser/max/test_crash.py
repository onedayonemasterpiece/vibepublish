import asyncio
import importlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

ProfileLane = importlib.import_module('adapters.max.profile').ProfileLane
MaxBlocked = importlib.import_module('adapters.max.profile').MaxBlocked
FixtureDriver = importlib.import_module('adapters.max.driver').FixtureDriver


async def test_M09_actual_process_death_observe_not_resubmit(server, tmp_path):
    origin, state = server
    root = Path(__file__).resolve().parents[3]
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('crash_worker.py')), origin, str(tmp_path)],
                               cwd=root, env=dict(os.environ, PYTHONPATH=str(root)),
                               start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        async with asyncio.timeout(20):
            while state['effects'] != 1 or not (tmp_path/'post-submit').exists():
                if process.poll() is not None:
                    raise AssertionError(process.stderr.read().decode())
                await asyncio.sleep(.05)
        assert (tmp_path/'test-dispatch-marker').exists()
        os.killpg(process.pid, signal.SIGKILL)
        await asyncio.to_thread(process.wait, 5)
        assert process.returncode == -signal.SIGKILL
        checkpoint = json.loads((tmp_path/'checkpoint.json').read_text())
        # Independent provider is alive after every worker/browser process died.
        assert state['effects'] == 1 and len(state['items']) == 1
        with ProfileLane(tmp_path/'profile') as lane:
            with pytest.raises(MaxBlocked, match='outcome_unknown'):
                lane.arm('fresh-operation', 'fresh-plan')
            async with async_playwright() as pw:
                browser = await pw.chromium.launch_persistent_context(str(lane.root/'chromium'), headless=True)
                try:
                    page = browser.pages[0]
                    await browser.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                    await page.goto(origin)
                    driver = FixtureDriver(page, lane, origin=origin, account='fixture-account', allowed_targets=frozenset({'channel-a'}))
                    result = await driver.reconcile(checkpoint)
                    assert result[0]['id'] == state['items'][0]['id']
                    assert lane.marker.exists()  # Core must durably accept observation.
                finally:
                    await browser.close()
        assert state['effects'] == 1
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            await asyncio.to_thread(process.wait, 5)
        process.stderr.close()
