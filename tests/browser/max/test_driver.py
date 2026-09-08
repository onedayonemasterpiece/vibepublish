import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import pytest

MaxBlocked = importlib.import_module('adapters.max.profile').MaxBlocked


class Hooks:
    def __init__(self, fail=None, callback=None):
        self.fail, self.callback = fail, callback
        self.states = {}
        self.events = []

    async def emit_progress(self, stage, status, evidence):
        if self.fail == stage:
            raise RuntimeError('private exception must not escape')
        self.events.append(stage)

    async def checkpoint(self, transition, state):
        if self.fail == transition:
            raise RuntimeError('DB unavailable')
        self.states[transition] = state

    async def before_effect(self, attempt, digest):
        if self.fail == 'before_effect':
            raise RuntimeError('DB unavailable')
        if self.callback:
            await self.callback()


def future():
    return (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()


def args(**kwargs):
    values = dict(target='channel-a', text='fixture text', media=(), scheduled_at=None,
                  action='publish', attempt_id='attempt-1', plan_digest='digest-1', hooks=Hooks())
    values.update(kwargs)
    return values


def images():
    # Actual tiny PNG payload, not a path into private assets.
    import base64
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9l8AAAAASUVORK5CYII=')
    return tuple(dict(name=f'{i}.png', mimeType='image/png', buffer=png) for i in range(2))


@pytest.mark.parametrize('account', ['wrong-account', 'QR'])
async def test_M01_M07_wrong_account_zero_effect(browser_driver, account):
    driver, state, page = browser_driver
    await page.get_by_test_id('session').evaluate('(el, value)=>el.dataset.account=value', account)
    with pytest.raises(MaxBlocked, match='needs_auth_or_wrong_account'):
        await driver.mutate(**args())
    assert state['effects'] == 0


async def test_M02_M03_queue_virtualization_external_editors_scope(browser_driver):
    driver, state, page = browser_driver
    for i in range(7):
        state['items'].append(dict(id=str(i),target='channel-a',namespace='scheduled',
                                   text='external editor',media=[],scheduled_at=future()))
    state['items'].append(dict(id='private',target='channel-b',namespace='scheduled',text='private',media=[],scheduled_at=future()))
    result = await driver.read('channel-a')
    assert len(result) == 7 and all(x['target'] == 'channel-a' for x in result)
    with pytest.raises(MaxBlocked, match='target_denied'):
        await driver.read('channel-b')
    assert await page.get_by_test_id('channel').get_attribute('data-target') == 'channel-a'


@pytest.mark.parametrize('config', [{'drop_upload': True}, {'reverse_upload': True}])
async def test_M05_incomplete_or_reordered_upload_zero_submit(browser_driver, config):
    driver, state, _ = browser_driver
    state['config'].update(config)
    with pytest.raises(MaxBlocked, match='upload_order_or_count'):
        await driver.mutate(**args(media=images()))
    assert state['effects'] == 0


async def test_M04_M06_delayed_upload_and_rerender(browser_driver):
    driver, state, page = browser_driver
    state['config']['upload_delay'] = 150
    async def rerender():
        await page.get_by_role('dialog').evaluate('(el)=>el.replaceWith(el.cloneNode(true))')
    hooks = Hooks(callback=rerender)
    result = await driver.mutate(**args(media=images(), scheduled_at=future(), hooks=hooks))
    assert state['effects'] == 1
    assert len(result[0]['media']) == 2 and result[0]['namespace'] == 'scheduled'
    assert result[0]['media_check'] == 'provider_identity_order'
    assert 'uploading' in hooks.events and 'MAX_OBSERVED' in hooks.states
    assert not driver.lane.marker.exists()


@pytest.mark.parametrize('stage', ['waiting_connection', 'uploading', 'MAX_PREPARED', 'submitting', 'before_effect'])
async def test_M08_callback_failure_zero_mutation(browser_driver, stage):
    driver, state, _ = browser_driver
    with pytest.raises(MaxBlocked):
        await driver.mutate(**args(media=images(), hooks=Hooks(fail=stage)))
    assert state['effects'] == 0


@pytest.mark.parametrize('which', ['rights', 'account', 'target', 'text', 'time', 'media', 'action', 'existing'])
async def test_changed_after_callback_never_submits(browser_driver, which):
    driver, state, page = browser_driver
    async def revoke():
        if which == 'rights':
            await page.get_by_test_id('channel').evaluate("el=>el.dataset.writable='false'")
        elif which == 'account':
            await page.get_by_test_id('session').evaluate("el=>el.dataset.account='other'")
        elif which == 'target':
            await page.get_by_test_id('channel').evaluate("el=>el.dataset.target='channel-b'")
        elif which == 'text':
            await page.get_by_label('Text', exact=True).fill('tampered')
        elif which == 'time':
            await page.get_by_label('Native time').fill('')
        elif which == 'action':
            await page.get_by_label('Action').select_option('delete')
        elif which == 'existing':
            await page.get_by_label('Existing item', exact=True).fill('another-item')
        else:
            await page.get_by_test_id('uploads').evaluate("el=>el.dataset.media='[]'")
    # Keep the normal bounded preparation budget; short global timeouts can
    # expire before this test reaches its intended post-marker injection.
    with pytest.raises(MaxBlocked, match='outcome_unknown'):
        await driver.mutate(**args(media=images(), scheduled_at=future(), hooks=Hooks(callback=revoke)))
    assert state['effects'] == 0 and driver.lane.marker.exists()


@pytest.mark.parametrize('value', ['2000-01-01T00:00:00Z', '2026-09-06', 'invalid'])
async def test_invalid_native_time_never_now(browser_driver, value):
    driver, state, _ = browser_driver
    with pytest.raises(MaxBlocked, match='native_time'):
        await driver.mutate(**args(scheduled_at=value))
    assert state['effects'] == 0


async def test_time_window_closes_during_callback(browser_driver):
    driver, state, _ = browser_driver
    async def delay_clock_margin():
        driver.min_lead = 7200
    with pytest.raises(MaxBlocked, match='outcome_unknown'):
        await driver.mutate(**args(scheduled_at=future(), hooks=Hooks(callback=delay_clock_margin)))
    assert state['effects'] == 0


async def test_M10_old_same_text_and_new_text_never_proves_authorship(browser_driver):
    driver, state, _ = browser_driver
    state['items'].append(dict(id='old',target='channel-a',namespace='feed',text='fixture text',media=[],scheduled_at=None))
    with pytest.raises(MaxBlocked, match='outcome_unknown'):
        await driver.mutate(**args())
    assert state['effects'] == 1 and len(state['items']) == 2
    with pytest.raises(MaxBlocked, match='outcome_unknown'):
        await driver.mutate(**args(attempt_id='NEW-OPERATION'))
    assert state['effects'] == 1


async def test_M10_multiple_candidates_remain_unknown(browser_driver):
    driver, state, _ = browser_driver
    state['config']['duplicate'] = True
    with pytest.raises(MaxBlocked, match='outcome_unknown'):
        await driver.mutate(**args(media=images()))
    assert state['effects'] == 1


async def test_M12_in_place_lifecycle_and_absence_not_cancellation(browser_driver):
    driver, state, _ = browser_driver
    item = dict(id='other-editor', target='channel-a', namespace='scheduled', text='old', media=[], scheduled_at=future())
    state['items'].append(item)
    existing = (await driver.read('channel-a'))[0]
    result = await driver.mutate(**args(action='edit', existing=existing, scheduled_at=item['scheduled_at']))
    assert result[0]['id'] == 'other-editor' and len(state['items']) == 1
    result = await driver.mutate(**args(action='reschedule', existing=result[0], scheduled_at=future()))
    assert result[0]['id'] == 'other-editor' and len(state['items']) == 1
    with pytest.raises(MaxBlocked, match='outcome_unknown'):
        await driver.mutate(**args(action='cancel', existing=result[0], scheduled_at=result[0]['scheduled_at']))
    assert state['items'] == [] and state['effects'] == 3


async def test_external_change_CAS_zero_mutation(browser_driver):
    driver, state, _ = browser_driver
    item = dict(id='external',target='channel-a',namespace='scheduled',text='old',media=[],scheduled_at=future())
    state['items'].append(item)
    existing = (await driver.read('channel-a'))[0]
    item['text'] = 'changed externally'
    with pytest.raises(MaxBlocked, match='external_change'):
        await driver.mutate(**args(action='edit', existing=existing, scheduled_at=item['scheduled_at']))
    assert state['effects'] == 0


async def test_post_effect_checkpoint_failure_preserves_quarantine(browser_driver):
    driver, state, _ = browser_driver
    with pytest.raises(MaxBlocked, match='outcome_unknown'):
        await driver.mutate(**args(media=images(), hooks=Hooks(fail='MAX_OBSERVED')))
    assert state['effects'] == 1 and driver.lane.marker.exists()


async def test_unsupported_video_and_no_asset_path_access(browser_driver):
    driver, state, _ = browser_driver
    for media in [({'name':'x','mimeType':'video/mp4','buffer':b'x'},), ({'path':'/private/asset'},)]:
        with pytest.raises(MaxBlocked, match='unsupported_media'):
            await driver.mutate(**args(media=media))
    assert state['effects'] == 0


async def test_M11_same_process_lane_and_other_async_work(browser_driver):
    driver, state, _ = browser_driver
    waiting, release = asyncio.Event(), asyncio.Event()
    class WaitingHooks(Hooks):
        async def emit_progress(self, stage, status, evidence):
            if stage == 'uploading':
                waiting.set()
                await release.wait()
            await super().emit_progress(stage, status, evidence)
    task = asyncio.create_task(driver.mutate(**args(media=images(), hooks=WaitingHooks())))
    try:
        await asyncio.wait_for(waiting.wait(), 3)
        # This proves event-loop/lane independence only, NOT real core MCP status.
        assert not task.done()
        with pytest.raises(MaxBlocked, match='profile_busy'):
            await driver.read('channel-a')
        release.set()
        await task
        assert state['effects'] == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_empty_time_cannot_be_reschedule(browser_driver):
    driver, state, _ = browser_driver
    with pytest.raises(MaxBlocked, match='native_time_required'):
        await driver.mutate(**args(action='reschedule'))
    assert state['effects'] == 0


async def test_live_origin_not_accepted(browser_driver):
    driver, _, page = browser_driver
    with pytest.raises(MaxBlocked, match='fixture_origin_required'):
        type(driver)(page, driver.lane, origin='https://web.max.ru', account='fixture-account', allowed_targets=frozenset({'channel-a'}))


async def test_reschedule_cannot_drop_media_or_change_text(browser_driver):
    driver, state, _ = browser_driver
    state['items'].append(dict(id='media-post',target='channel-a',namespace='scheduled',text='old',media=['native-image'],scheduled_at=future()))
    existing = (await driver.read('channel-a'))[0]
    with pytest.raises(MaxBlocked, match='preservation_unverified'):
        await driver.mutate(**args(action='reschedule', existing=existing, text='old', scheduled_at=future()))
    assert state['effects'] == 0 and state['items'][0]['media'] == ['native-image']
