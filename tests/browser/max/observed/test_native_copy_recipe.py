"""Standalone synthetic coverage for native Copy geometry, labels and references."""
import json

import pytest

from adapters.max.live import RealMaxDriver, Target
from adapters.max.profile import MaxBlocked
from tests.browser.max.observed.test_submit import writer, effects

pytestmark = pytest.mark.asyncio

TARGET = '-202'
PUBLIC = 'https://max.ru/channel_fixture'
POST = PUBLIC + '/AaEmK_9-x'
LINK_TEXT = 'this long named hyperlink occupies the caption center'
LINK_URL = 'https://example.test/source'
MENU_FIXTURE = r"""
window.REPLAY_LINK_MENUS=0;
window.REPLAY_SHORT_COPY_CLICKS=0;
window.REPLAY_CONTEXT_EVENTS=0;
document.addEventListener('contextmenu', event => {
    if (!event.target.closest('.bubbleContent > .text')) return;
    window.REPLAY_CONTEXT_EVENTS++;
    if (!event.target.closest('a')) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    window.REPLAY_LINK_MENUS++;
    document.querySelector('[role=menu]')?.remove();
    const menu=document.createElement('div');menu.role='menu';
    const copy=document.createElement('button');copy.role='menuitem';
    copy.textContent='Скопировать ссылку';
    copy.onclick=()=>{window.REPLAY_SHORT_COPY_CLICKS++;menu.remove();};
    menu.append(copy);document.body.append(menu);
}, true);
document.addEventListener('DOMContentLoaded',()=>{
    for(const row of document.querySelectorAll('.messageWrapper')){
        const original=row.oncontextmenu;
        row.oncontextmenu=function(event){
            original.call(this,event);
            const menu=document.querySelector('[role=menu]');
            const item=menu?.querySelector('[role=menuitem]');
            if(!item)return;
            const mode=window.REPLAY_NATIVE_LABEL_MODE;
            if(mode==='post'||mode==='disabled')item.textContent='Скопировать ссылку на пост';
            if(mode==='disabled')item.disabled=true;
            if(mode==='short')item.textContent='Скопировать ссылку';
            if(window.REPLAY_PUBLIC_REFERENCE){
                item.onclick=async()=>{
                    await navigator.clipboard.writeText(window.REPLAY_PUBLIC_REFERENCE);
                    await fetch('/replay-event',{method:'POST',body:JSON.stringify({
                        kind:'copy',target:provider.target,id:'provider-item'})});
                    menu.remove();
                };
            }
            if(mode==='both'||mode==='duplicate'){
                const duplicate=item.cloneNode(true);
                if(mode==='both')duplicate.textContent='Скопировать ссылку на пост';
                duplicate.onclick=item.onclick;
                menu.append(duplicate);
            }
            if(mode==='menus')document.body.append(menu.cloneNode(true));
            if(mode==='mutate'){
                this.querySelector('.bubbleContent > .text').firstChild.textContent=
                    'Changed after menu opened ';
            }
        };
    }
});
"""


def rich_text(layout='middle'):
    prefix = '' if layout == 'begin' else 'Start '
    suffix = '' if layout == 'end' else ' end'
    return prefix + LINK_TEXT + suffix, prefix + '<a href="' + LINK_URL + '">' + LINK_TEXT + '</a>' + suffix


async def exact_row(writer, *, layout='middle', media=False, mode=None,
                    public_reference=None, plain=False, all_link=False):
    driver, page, state, _ = writer
    assert isinstance(driver, RealMaxDriver)
    driver.targets[TARGET] = Target(TARGET, 'Channel A', 'publish_channel')
    text, html = rich_text(layout)
    if plain:
        text = html = 'Plain native message'
    if all_link:
        text, html = LINK_TEXT, '<a href="' + LINK_URL + '">' + LINK_TEXT + '</a>'
    message = dict(id='provider-item', target=TARGET, text=text, html=html, outgoing=False)
    if media:
        message['media'] = ['https://i.oneme.ru/replay/0.png']
    state['messages'] = [message]
    await page.add_init_script(
        'window.REPLAY_NATIVE_LABEL_MODE=' + json.dumps(mode) + ';' +
        'window.REPLAY_PUBLIC_REFERENCE=' + json.dumps(public_reference) + ';' + MENU_FIXTURE)
    await page.goto(driver.origin + '/' + TARGET, wait_until='domcontentloaded')
    main = await driver._scope(TARGET)
    row = driver._rows(main, text)
    await row.first.wait_for(state='visible', timeout=driver.timeout * 1000)
    assert await row.count() == 1
    return row


def bind_public(driver, public_url=PUBLIC):
    driver.binding_snapshot = {'targets': {TARGET: {
        'alias': 'Channel A', 'policy': 'publish_channel', 'public_url': public_url}}}


async def assert_observation_only(writer, *, copies):
    driver, page, state, _ = writer
    assert not effects(state)
    assert not state['checkpoints'] and 'dispatched' not in state
    assert not driver.lane.marker.exists()
    assert state['checks'] == 0
    assert len([event for event in state['events'] if event['kind'] == 'copy']) == copies
    assert await page.evaluate('window.REPLAY_SHORT_COPY_CLICKS') == 0
    assert await page.evaluate('window.REPLAY_LINK_MENUS') == 0


@pytest.mark.parametrize('media', [False, True])
@pytest.mark.parametrize('layout', ['begin', 'middle', 'end'])
async def test_named_link_positions_use_verified_plain_text(writer, media, layout):
    driver, page, _, _ = writer
    row = await exact_row(writer, layout=layout, media=media)
    assert await page.evaluate("""()=>{
        const rect=document.querySelector('.bubbleContent > .text').getBoundingClientRect();
        return Boolean(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2)?.closest('a'));
    }""")
    assert await driver._copy_native_reference(row, TARGET) == (
        'https://max.ru/c/-202/provider-item', 'provider-item')
    assert await page.evaluate('window.REPLAY_CONTEXT_EVENTS') == 1
    await assert_observation_only(writer, copies=1)


async def test_plain_caption_still_copies_native_reference(writer):
    driver, _, _, _ = writer
    row = await exact_row(writer, plain=True)
    assert await driver._copy_native_reference(row, TARGET) == (
        'https://max.ru/c/-202/provider-item', 'provider-item')
    await assert_observation_only(writer, copies=1)


async def test_all_link_caption_fails_before_opening_menu(writer):
    driver, page, _, _ = writer
    row = await exact_row(writer, all_link=True)
    with pytest.raises(MaxBlocked, match='^native_non_link_text_surface_unavailable$'):
        await driver._copy_native_reference(row, TARGET)
    assert await page.evaluate('window.REPLAY_CONTEXT_EVENTS') == 0
    await assert_observation_only(writer, copies=0)


@pytest.mark.parametrize('mode,reason', [
    ('menus', 'native_copy_menu_unavailable'),
    ('mutate', 'context_menu_subject_changed'),
])
async def test_menu_ambiguity_or_subject_change_fails_before_copy(writer, mode, reason):
    driver, page, _, _ = writer
    row = await exact_row(writer, mode=mode)
    with pytest.raises(MaxBlocked, match='^' + reason + '$'):
        await driver._copy_native_reference(row, TARGET)
    assert await page.get_by_role('menu').count() == (2 if mode == 'menus' else 1)
    assert await page.evaluate('window.REPLAY_CONTEXT_EVENTS') == 1
    await assert_observation_only(writer, copies=0)


@pytest.mark.parametrize('mode', ['post', 'both', 'duplicate', 'disabled', 'short'])
async def test_only_one_enabled_full_native_copy_label_is_accepted(writer, mode):
    driver, page, _, _ = writer
    row = await exact_row(writer, mode=mode)
    if mode == 'post':
        assert await driver._copy_native_reference(row, TARGET) == (
            'https://max.ru/c/-202/provider-item', 'provider-item')
    else:
        with pytest.raises(MaxBlocked, match='^native_copy_menu_unavailable$'):
            await driver._copy_native_reference(row, TARGET)
        assert await page.get_by_role('menu').count() == 1
        assert await page.get_by_role('menuitem').count() == (2 if mode in {'both', 'duplicate'} else 1)
    assert await page.evaluate('window.REPLAY_CONTEXT_EVENTS') == 1
    await assert_observation_only(writer, copies=int(mode == 'post'))


async def test_nonlink_geometry_keeps_exact_native_target_check(writer):
    driver, page, _, _ = writer
    await page.add_init_script("window.REPLAY_COPY_TARGET='-303'")
    row = await exact_row(writer)
    with pytest.raises(MaxBlocked, match='^native_reference_scope_mismatch$'):
        await driver._copy_native_reference(row, TARGET)
    await assert_observation_only(writer, copies=1)


async def test_public_reference_requires_exact_verified_binding(writer):
    driver, _, _, _ = writer
    bind_public(driver)
    row = await exact_row(writer, mode='post', public_reference=POST)
    assert await driver._copy_native_reference(row, TARGET) == (POST, 'AaEmK_9-x')
    await assert_observation_only(writer, copies=1)


@pytest.mark.parametrize('fault', ['missing', 'handle', 'alias', 'policy'])
async def test_public_copy_does_not_create_or_repair_binding(writer, fault):
    driver, _, _, _ = writer
    bind_public(driver)
    entry = driver.binding_snapshot['targets'][TARGET]
    if fault == 'missing':
        driver.binding_snapshot = {}
    elif fault == 'handle':
        entry['public_url'] = 'https://max.ru/other_channel'
    elif fault == 'alias':
        entry['alias'] = 'Different channel'
    else:
        entry['policy'] = 'scheduled_only'
    before = json.dumps(driver.binding_snapshot, sort_keys=True)
    row = await exact_row(writer, mode='post', public_reference=POST)
    with pytest.raises(MaxBlocked, match='^native_reference_scope_mismatch$'):
        await driver._copy_native_reference(row, TARGET)
    assert json.dumps(driver.binding_snapshot, sort_keys=True) == before
    await assert_observation_only(writer, copies=int(fault in {'missing', 'handle'}))


async def test_public_binding_change_during_copy_fails_closed(writer):
    driver, page, _, _ = writer
    bind_public(driver)
    row = await exact_row(writer, mode='post', public_reference=POST)
    def drift(request):
        if request.url == driver.origin + '/replay-event' and request.method == 'POST':
            if request.post_data_json.get('kind') == 'copy':
                driver.binding_snapshot['targets'][TARGET]['public_url'] = 'https://max.ru/other_channel'
    page.on('request', drift)
    with pytest.raises(MaxBlocked, match='^native_reference_scope_mismatch$'):
        await driver._copy_native_reference(row, TARGET)
    assert driver.binding_snapshot['targets'][TARGET]['public_url'] == 'https://max.ru/other_channel'
    await assert_observation_only(writer, copies=1)
