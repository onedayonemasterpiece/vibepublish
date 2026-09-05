import itertools
import json
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from adapters.max.live import RealMaxDriver, Target
from adapters.max.profile import ProfileLane, MaxBlocked

pytestmark=pytest.mark.asyncio
HTML=Path(__file__).with_name('replay.html').read_text()

@pytest.fixture
async def replay(tmp_path):
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        context=await browser.new_context(service_workers='block')
        outbound=[]
        events=[]
        async def route(r):
            if r.request.url=='http://127.0.0.1:18765/replay-event':
                events.append(json.loads(r.request.post_data)); await r.fulfill(body='{}',content_type='application/json')
            elif r.request.url.startswith('http://127.0.0.1:18765/'):
                await r.fulfill(body=HTML,content_type='text/html')
            else:
                outbound.append(r.request.url); await r.abort()
        await context.route('**/*',route)
        page=await context.new_page()
        account={'ok':True}
        async def check(): return account['ok']
        with ProfileLane(tmp_path/'profile') as lane:
            d=RealMaxDriver(page,lane,origin='http://127.0.0.1:18765',account_check=check,
                targets=tuple(Target(i,a,p) for i,a,p in [('-101','Test Group','test_group'),('-202','Channel A','scheduled_only'),('-303','Channel B','scheduled_only')]),timeout=2)
            await page.goto(d.origin+'/-101')
            yield d,page,account
            assert await page.evaluate('provider.effects')==0
            assert not outbound
            assert not [e for e in events if e["kind"]=="effect"]
        await browser.close()

@pytest.mark.parametrize('order',list(itertools.permutations(['-101','-202','-303'])))
async def test_all_orders_use_exact_native_route(replay,order):
    d,page,_=replay
    await page.context.add_init_script('window.REPLAY_ORDER='+json.dumps(order))
    await page.evaluate('(order)=>{provider.order=order;sidebar()}',order)
    for target in order:
        await d.open(target)
        assert page.url==d.origin+'/'+target
        assert await page.evaluate('provider.target')==target
        assert await page.evaluate('provider.order')==list(order)

async def test_message_search_hit_not_a_chat_title(replay):
    d,page,_=replay
    names=await d.discovery_titles()
    assert names==('Test Group','Channel A','Channel B','Channel A')
    # highlighted text in another message is deliberately not discovered/clicked
    assert names.count('Test Group')==1
    assert await page.evaluate('provider.visits')==['-101']

async def test_disappearing_reordered_duplicate_rows_do_not_redirect(replay):
    d,page,_=replay
    await page.locator('aside').evaluate('(e)=>{e.innerHTML="<h3><span class=name><span class=text>Test Group</span></span></h3>"+e.innerHTML}')
    await page.evaluate('provider.order=[];sidebar()')
    await d.open('-303')
    assert await page.evaluate('provider.target')=='-303'

async def test_wrong_account_no_navigation(replay):
    d,page,account=replay
    account['ok']=False
    with pytest.raises(MaxBlocked,match='wrong_account'): await d.open('-303')
    assert await page.evaluate('provider.visits')==['-101']

async def test_revoke_after_navigation_stops_read(replay):
    d,page,_=replay
    calls=0
    async def check():
        nonlocal calls
        calls+=1
        return calls<2
    d.account_check=check
    with pytest.raises(MaxBlocked,match='wrong_account'): await d.visible('-101')

async def test_exact_target_allowlist_and_origin(replay):
    d,page,_=replay
    with pytest.raises(MaxBlocked,match='target_denied'): await d.open('-999')
    await page.evaluate('history.pushState({},"","/-999")')
    with pytest.raises(MaxBlocked,match='wrong_target'): await d._scope('-101')

async def test_unknown_renamed_header_fail_closed_not_alias_rebind(replay):
    d,page,_=replay
    await page.evaluate("provider.rename['-101']='Renamed';render()")
    with pytest.raises(AssertionError): await d._scope('-101')
    assert d.targets['-101'].alias=='Test Group'

@pytest.mark.parametrize('namespace',['feed','scheduled'])
async def test_visible_projection_never_claims_ids_or_complete_queue(replay,namespace):
    d,page,_=replay
    result=await d.visible('-101',namespace)
    assert result.namespace==namespace and result.target=='-101'
    assert result.complete is False and 'native_item_identity' in result.missing_checks
    assert result.rows[0]['text']=='Safe example'
    assert 'id' not in result.rows[0] and 'scheduled_at' not in result.rows[0]

async def test_rerender_reacquires_scoped_locator(replay):
    d,page,_=replay
    await d.open('-202')
    await page.evaluate('render();sidebar();render()')
    await d._scope('-202')
    assert await page.locator('main [contenteditable]').count()==1

async def test_target_drift_during_awaited_account_check(replay):
    d,page,_=replay
    calls=0
    async def check():
        nonlocal calls
        calls+=1
        if calls==2:
            await page.evaluate("go('-303')")
        return True
    d.account_check=check
    with pytest.raises(MaxBlocked,match='wrong_target'): await d.open('-101')

async def test_wrong_namespace_not_inferred_from_route(replay):
    d,page,_=replay
    await page.evaluate("provider.mode='scheduled';render()")
    with pytest.raises(AssertionError): await d._scope('-101','feed')

async def test_recipe_manifest_and_fixture_are_mandatory():
    from adapters.max.live import RECIPE
    manifest=json.loads(Path(__file__).with_name('manifest.json').read_text())
    assert manifest['recipe']==RECIPE
    assert manifest['not_covered']
    assert 'data-target=' not in HTML and 'data-account=' not in HTML
    assert 'https://' not in HTML

async def test_observed_title_whitespace_not_an_identity_change(replay):
    d,page,_=replay
    await page.locator('h3 .name > .text').evaluate_all('(els)=>els.forEach(e=>e.textContent=" "+e.textContent+" ")')
    names=await d.discovery_titles()
    assert names[:3]==('Test Group','Channel A','Channel B')
    await d.open('-303')
    assert await page.evaluate('provider.target')=='-303'

@pytest.mark.parametrize('action', ['publish', 'edit', 'delete', 'reschedule', 'cancel'])
async def test_missing_causal_receipt_blocks_before_any_effect(replay, action):
    d,page,_=replay
    # A mutable ad-hoc connection flag must not enable an unfinished writer.
    d.publishing_binding='example-connection'
    await page.locator('[contenteditable]').fill('Pre-existing draft')
    with pytest.raises(MaxBlocked, match='causal_receipt_recipe_unverified'):
        await d.mutate(target='-101',text='Own marked probe',media=(),
            scheduled_at=None,action=action,attempt_id='attempt',
            plan_digest='plan',hooks=None)
    assert await page.locator('[contenteditable]').inner_text()=='Pre-existing draft'
    assert not d.lane.marker.exists()
    assert await page.evaluate('provider.visits')==['-101']

async def test_unknown_attempt_survives_read_only_reconcile(replay):
    d,page,_=replay
    d.lane.arm('unresolved-attempt','unresolved-plan')
    before=d.lane.marker.read_bytes()
    with pytest.raises(MaxBlocked, match='causal_receipt_recipe_unverified'):
        await d.reconcile({'text':'Safe example','native_receipt':None})
    assert d.lane.marker.read_bytes()==before
    with pytest.raises(MaxBlocked, match='outcome_unknown'):
        await d.mutation_preflight('-101','publish')
    assert await page.evaluate('provider.visits')==['-101']
