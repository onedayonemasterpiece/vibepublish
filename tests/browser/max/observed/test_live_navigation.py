import itertools
import json
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from adapters.max.live import RealMaxDriver, Target
from adapters.max.profile import ProfileLane, MaxBlocked

pytestmark=pytest.mark.asyncio
HTML=Path(__file__).with_name('replay.html').read_text()

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
    # The sole non-loopback literal is copied text, never a request URL.
    assert HTML.count('https://') == 1
    assert "const ref='https://max.ru/c/'" in HTML

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
    with pytest.raises(MaxBlocked, match='recovery_evidence_required'):
        await d.reconcile({'text':'Safe example','native_receipt':None})
    assert d.lane.marker.read_bytes()==before
    with pytest.raises(MaxBlocked, match='outcome_unknown'):
        await d.mutation_preflight('-101','publish')
    assert await page.evaluate('provider.visits')==['-101']

RECOVERY_TEXT='Task-owned probe 0123456789abcdef0123456789abcdef'

def recovery_state():
    return dict(target='-101',text=RECOVERY_TEXT,kind='feed',action='publish',
        media=[],scheduled_at=None,recovery_reference='https://max.ru/c/-101/new-item',
        task_marker=RECOVERY_TEXT.split()[-1],attempt_id='original-attempt',plan_digest='original-plan')

async def recovery_setup(replay, *, messages=None, extra=''):
    d,page,_=replay
    # Two fresh navigations + four clipboard confirmations, not one navigation.
    d.timeout=10
    await page.context.grant_permissions(['clipboard-read','clipboard-write'],origin=d.origin)
    await page.context.add_init_script('window.REPLAY_MESSAGES='+json.dumps(messages if messages is not None else [dict(id='new-item',text=RECOVERY_TEXT,outgoing=True)])+';'+extra)
    d.lane.arm('original-attempt','original-plan')
    return d,page

@pytest.mark.parametrize('order',list(itertools.permutations(['-101','-202','-303'])))
async def test_exact_recovery_two_fresh_reads_preserve_original_fuse(replay,order):
    d,page=await recovery_setup(replay,extra='window.REPLAY_ORDER='+json.dumps(order))
    fuse=d.lane.marker.read_bytes()
    # Reorder the chat list from EACH awaited account callback as well as
    # starting in every permutation. Native item selection must be unaffected.
    async def account():
        await page.evaluate('provider.order.reverse();sidebar()')
        return True
    d.account_check=account
    result=await d.reconcile(recovery_state())
    assert result['item']['id']=='new-item' and result['item']['text']==RECOVERY_TEXT
    assert len(result['observations'])==2
    assert result['observation_only'] and not result['quarantine_released']
    assert result['attribution']=='requires_core_historical_evidence_validation'
    assert result['history_complete'] is False
    assert d.lane.marker.read_bytes()==fuse
    assert await page.evaluate('provider.order')==list(reversed(order))

@pytest.mark.parametrize('fault', ['old_ref','same_text_wrong_id','duplicate','foreign','changed_text','media','wrong_target','stale_clipboard'])
async def test_recovery_rejects_nonexact_candidates(replay,fault):
    message=dict(id='new-item',text=RECOVERY_TEXT,outgoing=True)
    extra='';messages=[message]
    if fault in {'old_ref','same_text_wrong_id'}: message['id']='old-item'
    elif fault=='duplicate': messages.append(dict(message,id='other-item'))
    elif fault=='foreign': message['outgoing']=False
    elif fault=='changed_text': message['text']+=' changed'
    elif fault=='media': message['media']=True
    elif fault=='wrong_target': extra="window.REPLAY_COPY_TARGET='-202'"
    elif fault=='stale_clipboard': extra='window.REPLAY_SILENT_COPY=true'
    d,page=await recovery_setup(replay,messages=messages,extra=extra)
    await page.evaluate('(s)=>navigator.clipboard.writeText(s)',recovery_state()['recovery_reference'])
    fuse=d.lane.marker.read_bytes()
    with pytest.raises(MaxBlocked): await d.reconcile(recovery_state())
    assert d.lane.marker.read_bytes()==fuse

@pytest.mark.parametrize('fault',['account','attempt','digest','reference_target'])
async def test_recovery_binding_rejection(replay,fault):
    d,page=await recovery_setup(replay)
    state=recovery_state()
    if fault=='account': replay[2]['ok']=False
    elif fault=='attempt': state['attempt_id']='different'
    elif fault=='digest': state['plan_digest']='different'
    else: state['recovery_reference']='https://max.ru/c/-202/new-item'
    fuse=d.lane.marker.read_bytes()
    with pytest.raises(MaxBlocked): await d.reconcile(state)
    assert d.lane.marker.read_bytes()==fuse

async def test_actual_reader_process_crash_restart_never_sends(tmp_path,recovery_server):
    import os,sys,signal,subprocess,asyncio
    origin,state=recovery_server
    with ProfileLane(tmp_path/'profile') as lane:
        lane.arm('original-attempt','original-plan')
        fuse=lane.marker.read_bytes()
    (tmp_path/'request.json').write_text(json.dumps(recovery_state()))
    processes=[];logs=[]
    def launch(mode):
        log=(tmp_path/(mode+'.log')).open('wb');logs.append(log)
        proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('recovery_reader.py')),origin,str(tmp_path),mode],
            env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LD_LIBRARY_PATH','PLAYWRIGHT_BROWSERS_PATH'}}|{'PYTHONPATH':str(Path(__file__).resolve().parents[4])},
            start_new_session=True,stdout=log,stderr=log)
        processes.append(proc);return proc
    try:
        first=launch('crash')
        async with asyncio.timeout(20):
            while not (tmp_path/'between-reads').exists():
                assert first.poll() is None
                await asyncio.sleep(.05)
        os.killpg(first.pid,signal.SIGKILL)
        await asyncio.to_thread(first.wait,10)
        assert (tmp_path/'profile/.vibepublish-uncertain').read_bytes()==fuse
        restarted=launch('restart')
        assert await asyncio.to_thread(restarted.wait,35)==0
        result=json.loads((tmp_path/'result.json').read_text())
        assert result['item']['id']=='new-item' and result['observation_only']
        assert (tmp_path/'profile/.vibepublish-uncertain').read_bytes()==fuse
        assert not (tmp_path/'outbound-attempt').exists()
        assert len([e for e in state['events'] if e['kind']=='copy'])==6
        assert not [e for e in state['events'] if e['kind']=='effect']
        assert len(state['messages'])==1
    finally:
        for proc in processes:
            if proc.poll() is None: os.killpg(proc.pid,signal.SIGKILL)
            await asyncio.to_thread(proc.wait,10)
        for log in logs: log.close()

@pytest.mark.parametrize('fault',['account','target','text','media','native_ref','quarantine'])
async def test_recovery_rechecks_after_awaited_callback(replay,fault):
    d,page=await recovery_setup(replay)
    calls=0
    async def account():
        nonlocal calls
        calls+=1
        if calls==2:
            if fault=='account': return False
            if fault=='target': await page.evaluate("go('-202')")
            if fault=='text': await page.evaluate("messages[0].text+=' changed';render()")
            if fault=='media': await page.evaluate("messages[0].media=true;render()")
            if fault=='native_ref': await page.evaluate("messages[0].id='other';render()")
            if fault=='quarantine': d.lane.marker.write_text(json.dumps({'attempt_id':'other','plan_digest':'other'}))
        return True
    d.account_check=account
    with pytest.raises(MaxBlocked): await d.reconcile(recovery_state())
    assert d.lane.marker.exists()
    if fault=='quarantine': assert json.loads(d.lane.marker.read_text())['attempt_id']=='other'

async def test_recovery_deadline_is_unknown_and_keeps_original_fuse(replay):
    import asyncio
    d,page=await recovery_setup(replay)
    d.timeout=.02
    async def delayed_account():
        await asyncio.sleep(1)
        return True
    d.account_check=delayed_account
    before=d.lane.marker.read_bytes()
    with pytest.raises(MaxBlocked,match='recovery_observation_deadline'):
        await d.reconcile(recovery_state())
    assert d.lane.marker.read_bytes()==before

async def test_two_readers_share_one_serial_profile_lane(replay):
    import asyncio
    d,page=await recovery_setup(replay)
    entered=asyncio.Event();release=asyncio.Event();calls=0
    async def account():
        nonlocal calls
        calls+=1
        if calls==1: entered.set();await release.wait()
        return True
    d.account_check=account
    before=d.lane.marker.read_bytes()
    first=asyncio.create_task(d.reconcile(recovery_state()))
    try:
        await asyncio.wait_for(entered.wait(),5)
        with pytest.raises(MaxBlocked,match='profile_busy'):
            await d.reconcile(recovery_state())
    finally:
        release.set()
    result=await first
    assert result['item']['id']=='new-item' and d.lane.marker.read_bytes()==before
