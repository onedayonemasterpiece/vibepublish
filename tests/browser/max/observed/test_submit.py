"""Same RealMaxDriver writer qualification, not a live/MCP publication claim."""
import itertools
import json
import os
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from adapters.max.live import RealMaxDriver, Target
from adapters.max.profile import MaxBlocked, ProfileLane
from pathlib import Path

HTML = Path(__file__).with_name('replay.html').read_text()

pytestmark = pytest.mark.asyncio
TEXT = 'Plain publication without an injected task marker'


@pytest.fixture
async def writer(tmp_path):
    state = dict(messages=[], events=[], checkpoints=[], outbound=[], fault=None,
                 orders=['-101', '-202', '-303'], checks=0)
    origin = 'http://127.0.0.1:18766'
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(service_workers='block')
        await context.grant_permissions(['clipboard-read', 'clipboard-write'])
        async def route(r):
            if r.request.url == origin+'/replay-event':
                event = json.loads(r.request.post_data)
                state['events'].append(event)
                if event['kind'] == 'effect':
                    # Independent provider: the driver cannot allocate IDs or read
                    # this state. Dispatch must already have been durably awaited.
                    assert state.get('dispatched') == state.get('expected_dispatch', ('attempt', 'plan'))
                    assert driver.lane.marker.exists()
                    if event.get('action') == 'delete':
                        state['messages'][:]=[m for m in state['messages'] if not(m['id']==event['existing'] and m.get('target')==event['target'])]
                    elif event.get('action') == 'edit':
                        matches=[m for m in state['messages'] if m['id']==event['existing'] and m.get('target')==event['target']]
                        assert len(matches)==1
                        matches[0]['text']=event['text']
                        if state['fault']=='replace_edit': matches[0]['id']='replacement'
                    else:
                        message = dict(id='provider-item', target=event['target'], text=event['text'], outgoing=True)
                        if event.get('media'):message['media']=[('https://maxvd.example.okcdn.ru/replay/'+str(i)+'.mp4') if name.endswith('.mp4') else ('https://i.oneme.ru/replay/'+str(i)+'.png') for i,name in enumerate(event['media'])]
                        if state['fault'] == 'foreign': message['outgoing'] = False
                        state['messages'].append(message)
                        if state['fault'] == 'duplicate':
                            state['messages'].append(dict(message, id='other-item'))
                    if state['fault'] == 'lost_response':
                        await r.abort(); return
                await r.fulfill(body=json.dumps(dict(messages=state['messages'])), content_type='application/json')
            elif r.request.url.startswith('https://maxvd.example.okcdn.ru/replay/'):
                await r.fulfill(body=Path(__file__).with_name('sample.mp4').read_bytes(),content_type='video/mp4',headers={'Content-Disposition':'attachment; filename=video.mp4'} if 'download=1' in r.request.url else {})
            elif r.request.url.startswith('https://i.oneme.ru/replay/'):
                import base64
                await r.fulfill(body=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg=='),content_type='image/png',headers={'Content-Disposition':'attachment; filename=photo.png'} if 'download=1' in r.request.url else {})
            elif r.request.url.startswith(origin+'/'):
                body = '<script>window.REPLAY_MESSAGES='+json.dumps(state['messages'])+';window.REPLAY_ORDER='+json.dumps(state['orders'])+'</script>'+HTML
                await r.fulfill(body=body, content_type='text/html')
            else:
                state['outbound'].append(r.request.url)
                await r.abort()
        await context.route('**/*', route)
        page = await context.new_page()
        async def account():
            state['checks'] += 1
            if state.get('reorder') and page.url.startswith(origin+'/'):
                await page.evaluate('provider.order.reverse();sidebar()')
            return not state.get('revoked')
        with ProfileLane(tmp_path/'profile') as lane:
            driver = RealMaxDriver(page, lane, origin=origin, account_check=account,
                targets=(Target('-101','Test Group','test_group'),
                         Target('-202','Channel A','scheduled_only'),
                         Target('-303','Channel B','scheduled_only')), timeout=10)
            async def checkpoint(name, raw):
                if state.get('fail_checkpoint') == name: raise RuntimeError('fixture DB refusal')
                data = json.loads(raw)
                # Persisted hook record outside browser; retained across navigation.
                state['checkpoints'].append((name, data))
                with (tmp_path/(name+'.json')).open('w') as stream:
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
                if state.get('after_checkpoint'): await state['after_checkpoint'](name)
            async def progress(*args): pass
            async def dispatch(attempt, plan):
                if state.get('refuse_dispatch'): raise RuntimeError('fixture revoked')
                state['dispatched'] = (attempt, plan)
                if state.get('drift') == 'target': await page.evaluate("go('-303')")
                if state.get('drift') == 'composer': await page.locator('[contenteditable]').fill('External edit')
                if state.get('drift') == 'account': state['revoked'] = True
                if state.get('drift') == 'rerender':
                    await page.evaluate('render()')
            hooks = SimpleNamespace(checkpoint=checkpoint, emit_progress=progress, before_effect=dispatch)
            yield driver, page, state, hooks
            assert not state['outbound']
        await browser.close()


async def submit(writer, target='-101'):
    d, _, _, hooks = writer
    return await d.submit_plain_candidate(target=target,text=TEXT,
        attempt_id='attempt',plan_digest='plan',hooks=hooks)


def effects(state): return [e for e in state['events'] if e['kind']=='effect']


@pytest.mark.parametrize('order',list(itertools.permutations(['-101','-202','-303'])))
async def test_submit_once_durable_reference_fresh_read_all_orders(writer, order):
    d,page,state,_ = writer
    state.update(orders=order,reorder=True)
    result = await submit(writer)
    assert result['item']['id']=='provider-item'
    assert result['item']['text']==TEXT
    assert result['quarantine_released'] is False
    assert result['history_complete'] is False
    assert result['transition']==dict(clicks=1,changed=True,blocked=False)
    assert [c[0] for c in state['checkpoints']]==['MAX_PREPARED','MAX_NATIVE_REFERENCE','MAX_CANDIDATE_OBSERVED']
    assert len(effects(state))==1 and effects(state)[0]['target']=='-101'
    assert len([e for e in state['events'] if e['kind']=='copy'])==3
    assert len([e for e in state['events'] if e['kind']=='visit'])==2
    assert json.loads(d.lane.marker.read_text())==dict(attempt_id='attempt',plan_digest='plan')
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await submit(writer)
    assert len(effects(state))==1


@pytest.mark.parametrize('drift',['target','composer','account','rerender'])
async def test_submit_callback_drift_zero_send(writer,drift):
    d,page,state,_=writer
    state['drift']=drift
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await submit(writer)
    assert effects(state)==[] and d.lane.marker.exists()


@pytest.mark.parametrize('name',['MAX_PREPARED','MAX_NATIVE_REFERENCE','MAX_CANDIDATE_OBSERVED'])
async def test_submit_checkpoint_failure_never_retries(writer,name):
    d,page,state,_=writer
    state['fail_checkpoint']=name
    with pytest.raises(MaxBlocked): await submit(writer)
    expected = 0 if name=='MAX_PREPARED' else 1
    assert len(effects(state))==expected
    assert d.lane.marker.exists()==bool(expected)
    if expected:
        with pytest.raises(MaxBlocked,match='outcome_unknown'): await submit(writer)
        assert len(effects(state))==1


@pytest.mark.parametrize('fault',['foreign','duplicate','lost_response'])
async def test_submit_ambiguous_or_lost_response_stays_unknown(writer,fault):
    d,page,state,_=writer
    d.timeout=3
    state['fault']=fault
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await submit(writer)
    assert len(effects(state))==1 and d.lane.marker.exists()
    assert not [c for c in state['checkpoints'] if c[0]=='MAX_NATIVE_REFERENCE']
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await submit(writer)
    assert len(effects(state))==1


async def test_submit_refused_dispatch_zero_send(writer):
    d,page,state,_=writer
    state['refuse_dispatch']=True
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await submit(writer)
    assert not effects(state) and d.lane.marker.exists()


async def test_submit_same_old_text_not_attributed(writer):
    d,page,state,_=writer
    state['messages']=[dict(id='old',text=TEXT,outgoing=True)]
    with pytest.raises(MaxBlocked,match='preexisting_content'): await submit(writer)
    assert not effects(state) and not d.lane.marker.exists()


async def test_submit_channel_policy_denied(writer):
    d,page,state,_=writer
    with pytest.raises(MaxBlocked,match='immediate_publication_denied'): await submit(writer,'-202')
    assert not state['events'] and not d.lane.marker.exists()


async def test_submit_live_origin_remains_disabled_without_a_flag(writer):
    d,page,state,_=writer
    d.origin='https://web.max.ru'
    with pytest.raises(MaxBlocked,match='writer_live_qualification_pending'): await submit(writer)
    assert not state['events'] and not d.lane.marker.exists()

async def test_submit_other_quarantine_during_dispatch_zero_send(writer):
    d,page,state,hooks=writer
    async def dispatch(*_):
        d.lane.marker.write_text(json.dumps(dict(attempt_id='other',plan_digest='other')))
    hooks.before_effect=dispatch
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await submit(writer)
    assert not effects(state)
    assert json.loads(d.lane.marker.read_text())['attempt_id']=='other'

async def test_submit_native_reference_change_after_checkpoint_is_unknown(writer):
    d,page,state,_=writer
    async def changed(name):
        if name=='MAX_NATIVE_REFERENCE': state['messages'][0]['id']='replacement'
    state['after_checkpoint']=changed
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await submit(writer)
    assert len(effects(state))==1 and d.lane.marker.exists()
    assert state['checkpoints'][-1][0]=='MAX_NATIVE_REFERENCE'

async def test_submit_process_kill_after_reference_restart_reads_never_resends(recovery_server,tmp_path):
    import asyncio
    import os
    import signal
    import subprocess
    import sys
    from pathlib import Path
    origin,state=recovery_server
    state['messages']=[]
    request=dict(target='-101',text='Own probe 0123456789abcdef0123456789abcdef',
        kind='feed',action='publish',media=[],scheduled_at=None,
        attempt_id='original-attempt',plan_digest='original-plan',
        recovery_reference='https://max.ru/c/-101/new-item',task_marker='0123456789abcdef0123456789abcdef')
    (tmp_path/'request.json').write_text(json.dumps(request))
    state['before_effect']=lambda: json.loads((tmp_path/'dispatched').read_text())==['original-attempt','original-plan']
    runner=Path(__file__).with_name('recovery_reader.py')
    processes=[]
    with (tmp_path/'child.log').open('w') as log:
        def launch(mode):
            proc=subprocess.Popen([sys.executable,str(runner),origin,str(tmp_path),mode],
                start_new_session=True,stdout=log,stderr=log,env=dict(os.environ,PYTHONPATH=os.getcwd()))
            processes.append(proc);return proc
        try:
            first=launch('submit-crash')
            async with asyncio.timeout(25):
                while not (tmp_path/'after-submit-reference').exists():
                    assert first.poll() is None
                    await asyncio.sleep(.05)
            reference=json.loads((tmp_path/'MAX_NATIVE_REFERENCE.json').read_text())
            assert reference['recovery_reference']==request['recovery_reference']
            fuse=(tmp_path/'profile/.vibepublish-uncertain').read_bytes()
            os.killpg(first.pid,signal.SIGKILL)
            await asyncio.to_thread(first.wait,10)
            restarted=launch('restart')
            assert await asyncio.to_thread(restarted.wait,35)==0
            observed=json.loads((tmp_path/'result.json').read_text())
            assert observed['item']['url']==reference['recovery_reference']
            assert observed['observation_only'] and not observed['quarantine_released']
            assert (tmp_path/'profile/.vibepublish-uncertain').read_bytes()==fuse
            assert len([e for e in state['events'] if e['kind']=='effect'])==1
            assert len(state['messages'])==1
            assert not (tmp_path/'outbound-attempt').exists()
        finally:
            for proc in processes:
                if proc.poll() is None: os.killpg(proc.pid,signal.SIGKILL)
                await asyncio.to_thread(proc.wait,10)

async def test_submit_saved_candidate_reconcile_without_invented_marker(writer):
    d,page,state,_=writer
    await submit(writer)
    saved=next(value for name,value in state['checkpoints'] if name=='MAX_NATIVE_REFERENCE')
    assert 'task_marker' not in saved
    result=await d.reconcile(saved)
    assert result['item']['text']==TEXT and result['item']['id']=='provider-item'
    assert result['observation_only'] and not result['quarantine_released']
    assert len(effects(state))==1

@pytest.mark.parametrize('drift',['reload','pointerdown'])
async def test_submit_observer_loss_or_last_input_route_drift_never_sends(writer,drift):
    d,page,state,hooks=writer
    async def dispatch(*_):
        state['dispatched']=('attempt','plan')
        if drift=='reload':
            await page.reload()
            await page.locator('[contenteditable]').fill(TEXT)
        else:
            await page.get_by_role('button',name='Отправить сообщение',exact=True).evaluate(
                "e=>e.addEventListener('pointerdown',()=>history.pushState({},'', '/-303'),{once:true})")
    hooks.before_effect=dispatch
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await submit(writer)
    assert not effects(state) and d.lane.marker.exists()


def edit_seed(writer):
    _,_,state,_=writer
    state['messages']=[dict(id='existing-item',target='-101',text='Original plain text',outgoing=True)]
    return dict(id='existing-item',target='-101',text='Original plain text',url='https://max.ru/c/-101/existing-item',
                namespace='feed',media=[],scheduled_at=None)


async def edit(writer, existing):
    d,_,_,hooks=writer
    return await d.edit_plain_candidate(existing=existing,text='Edited plain text',
        attempt_id='attempt',plan_digest='plan',hooks=hooks)


@pytest.mark.parametrize('order',list(itertools.permutations(['-101','-202','-303'])))
async def test_exact_edit_preserves_identity_all_orders(writer,order):
    d,page,state,_=writer
    existing=edit_seed(writer)
    state.update(orders=order,reorder=True)
    result=await edit(writer,existing)
    assert result['item']['id']==existing['id'] and result['item']['text']=='Edited plain text'
    assert result['item']['url']==existing['url']
    assert len(state['messages'])==1 and len(effects(state))==1
    assert effects(state)[0]['action']=='edit' and effects(state)[0]['existing']==existing['id']
    assert not result['quarantine_released'] and d.lane.marker.exists()
    assert [n for n,_ in state['checkpoints']]==['MAX_EDIT_PREPARED','MAX_EDIT_REFERENCE','MAX_EDIT_OBSERVED']
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await edit(writer,existing)
    assert len(effects(state))==1


@pytest.mark.parametrize('fault',['reference','text','media','mode','account','target'])
async def test_edit_dispatch_drift_zero_effect(writer,fault):
    d,page,state,hooks=writer
    existing=edit_seed(writer)
    async def dispatch(*args):
        state['dispatched']=tuple(args)
        if fault=='reference': await page.evaluate("messages[0].id='other'")
        elif fault=='text': await page.locator('.bubbleContent > .text').evaluate("e=>e.textContent='External edit'")
        elif fault=='media': await page.locator('.messageWrapper').evaluate("e=>e.insertAdjacentHTML('beforeend','<span class=media></span>')")
        elif fault=='mode': await page.evaluate("document.querySelector('.edit-heading').remove();provider.editing=null")
        elif fault=='account': state['revoked']=True
        elif fault=='target': await page.evaluate("go('-303')")
    hooks.before_effect=dispatch
    d.timeout=3
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await edit(writer,existing)
    assert not effects(state) and d.lane.marker.exists()


@pytest.mark.parametrize('fault',['replace_edit','lost_response'])
async def test_edit_post_effect_uncertainty_never_repeats(writer,fault):
    d,page,state,_=writer
    existing=edit_seed(writer);state['fault']=fault;d.timeout=3
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await edit(writer,existing)
    assert len(effects(state))==1 and len(state['messages'])==1
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await edit(writer,existing)
    assert len(effects(state))==1


async def test_edit_live_origin_still_denied(writer):
    d,_,state,_=writer;existing=edit_seed(writer);d.origin='https://web.max.ru'
    with pytest.raises(MaxBlocked,match='writer_live_qualification_pending'): await edit(writer,existing)
    assert not state['events']


async def test_edit_lost_response_reconcile_same_object_without_resave(writer):
    d,page,state,_=writer
    existing=edit_seed(writer);state['fault']='lost_response'
    # Keep the normal preflight budget: inject failure at the provider response,
    # not a machine-load-dependent timeout before the trusted Save.
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await edit(writer,existing)
    assert len(effects(state))==1
    saved=state['checkpoints'][0][1]
    assert saved['action']=='edit'
    d.timeout=10
    recovered=await d.reconcile(saved)
    assert recovered['item']['id']==existing['id']
    assert recovered['item']['text']=='Edited plain text' and recovered['observation_only']
    assert len(effects(state))==1 and d.lane.marker.exists()


async def test_edit_recovery_cannot_switch_saved_native_id(writer):
    d,page,state,_=writer
    existing=edit_seed(writer)
    await edit(writer,existing)
    saved=dict(state['checkpoints'][0][1],existing_id='another-object')
    with pytest.raises(MaxBlocked,match='recovery_evidence_required'): await d.reconcile(saved)
    assert len(effects(state))==1


@pytest.mark.parametrize('fault',['mode','media','header'])
async def test_edit_final_pointerdown_drift_cannot_turn_save_into_publish(writer,fault):
    d,page,state,hooks=writer
    existing=edit_seed(writer)
    async def dispatch(*args):
        state['dispatched']=tuple(args)
        await page.get_by_role('button',name='Отправить сообщение',exact=True).evaluate(
            """(e,fault)=>e.addEventListener('pointerdown',()=>{
                if(fault==='mode'){document.querySelector('.edit-heading').remove();provider.editing=null;}
                if(fault==='media')document.querySelector('.messageWrapper').insertAdjacentHTML('beforeend','<span class=media></span>');
                if(fault==='header')document.querySelector('main button').setAttribute('aria-label','Wrong header');
            },{once:true})""",fault)
    hooks.before_effect=dispatch
    with pytest.raises(MaxBlocked,match='outcome_unknown'): await edit(writer,existing)
    assert not effects(state) and d.lane.marker.exists()


async def test_plain_send_ignores_unrelated_history_media(writer):
    d,page,state,h=writer
    state['messages']=[dict(id='unrelated',target='-101',text='Old photo',outgoing=True,media=True)]
    result=await submit(writer)
    assert result['item']['text']==TEXT and len(effects(state))==1


async def test_observed_delete_all_requires_durable_dispatch_and_exact_reference(writer):
    d,page,state,h=writer
    d.live_writes=True
    state['messages']=[dict(id='owned',target='-101',text=TEXT,outgoing=True)]
    existing=dict(id='owned',target='-101',text=TEXT,url='https://max.ru/c/-101/owned',namespace='feed',media=[],scheduled_at=None)
    result=await d.delete_plain(existing=existing,attempt_id='attempt',plan_digest='plan',hooks=h)
    assert result['item']['id']=='owned' and not state['messages']
    assert len(effects(state))==1 and effects(state)[0]['action']=='delete'
    assert state['checkpoints'][-1][1]['transition']==dict(clicks=1,removed=True,blocked=False)
    assert d.lane.marker.exists()

async def test_exact_native_read_does_not_use_chat_or_message_order(writer):
    d,page,state,h=writer
    state.update(reorder=True,messages=[
        dict(id='old-photo',target='-101',text='Old photo',outgoing=True,media=True),
        dict(id='owned',target='-101',text=TEXT,outgoing=True)])
    result=await d.read('-101',native_item='owned')
    assert len(result)==1 and result[0]['id']=='owned' and result[0]['text']==TEXT
    assert not effects(state) and not d.lane.marker.exists()


async def test_observed_group_edit_heading(writer):
    d,page,state,h=writer
    await page.add_init_script('window.REPLAY_GROUP_EDIT=true')
    state['messages']=[dict(id='owned',target='-101',text=TEXT,outgoing=True)]
    existing=dict(id='owned',target='-101',text=TEXT,url='https://max.ru/c/-101/owned',namespace='feed',media=[],scheduled_at=None)
    result=await d.edit_plain_candidate(existing=existing,text=TEXT+' edited',attempt_id='attempt',plan_digest='plan',hooks=h)
    assert result['item']['id']=='owned' and len(effects(state))==1


async def test_observed_image_chooser_bound_before_one_send(writer):
    d,page,state,h=writer
    import base64
    data=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==')
    result=await d.submit_plain_candidate(target='-101',text=TEXT,attempt_id='attempt',plan_digest='plan',hooks=h,
        media=(dict(name='0.png',mimeType='image/png',buffer=data),))
    assert result['item']['media']==[] and len(result['item']['observed_media'])==1 and len(effects(state))==1
    assert state['checkpoints'][0][1]['upload_previews'][0]['name']=='0.png'
    assert state['checkpoints'][-1][1]['observed_media']==result['item']['observed_media']


async def test_exact_read_waits_for_history_not_only_header(writer):
    d,page,state,h=writer
    state['messages']=[dict(id='owned',target='-101',text=TEXT,outgoing=True)]
    await page.add_init_script('window.REPLAY_HISTORY_DELAY=500')
    result=await d.read('-101',native_item='owned')
    assert result[0]['id']=='owned' and not effects(state)


async def test_exact_image_read_waits_for_lazy_tile_image(writer):
    d,page,state,h=writer
    state['messages']=[dict(id='owned',target='-101',text=TEXT,outgoing=True,
        media=['https://i.oneme.ru/replay/0.png'])]
    await page.add_init_script('window.REPLAY_LAZY_MEDIA=600;window.REPLAY_ESCAPE_LEAVES_CHAT=true')
    result=await d.read('-101',native_item='owned')
    assert result[0]['id']=='owned' and len(result[0]['observed_media'])==1
    assert page.url.endswith('/-101') and not effects(state)


async def test_read_skips_unsupported_candidate_without_leaving_chat(writer):
    d,page,state,h=writer
    state['messages']=[dict(id='owned',target='-101',text=TEXT,outgoing=True),
        dict(id='unsupported',target='-101',text='Unsupported attachment',outgoing=True,media=True)]
    await page.add_init_script('window.REPLAY_ESCAPE_LEAVES_CHAT=true')
    result=await d.read('-101',native_item='owned')
    assert result[0]['id']=='owned' and page.url.endswith('/-101')
    assert not effects(state)
