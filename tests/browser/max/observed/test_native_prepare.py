"""Observed MAX menu absence and complete pre-arm calendar regression."""
import json
from types import SimpleNamespace
import pytest
from adapters.max import queue
from adapters.max.profile import MaxBlocked
from adapters.max.live import Target
from tests.browser.max.observed.test_submit import writer, effects

pytestmark = pytest.mark.asyncio

MENU = """(element, options) => {
 window.opens=0;window.confirmClicks=0;
 element.oncontextmenu=e=>{
  e.preventDefault();e.stopImmediatePropagation();window.opens++;
  if(options.drift && window.opens===1) {
   if(options.drift==='detach') element.replaceWith(element.cloneNode(true));
   if(options.drift==='text') element.closest('main').querySelector('[contenteditable]').textContent+=' changed';
   if(options.drift==='metadata') element.closest('.messageWrapper').querySelector('.volatile').textContent='UI metadata changed';
   if(options.drift==='route') history.pushState({},'', '/foreign');
   if(options.drift==='media') element.closest('main').querySelector('img').src='data:image/png;base64,changed';
  }
  if(window.opens<options.after)return;
  const menu=document.createElement('div');menu.role='menu';
  const item=document.createElement('button');item.role='menuitem';item.textContent=options.label;
  item.onclick=()=>{menu.remove();window.selectedMenu=options.label;if(window.calendar)window.calendar();};
  menu.append(item);document.body.append(menu);
 };
}"""

CALENDAR = """() => {
 window.calendar=()=>{
  const dialog=document.createElement('dialog');
  dialog.innerHTML='<div class="calendar"><div class="header"><span class="title">октябрь 2030</span><button aria-label="Следующий месяц">next</button></div><div class="days"><button class="day">12</button></div></div><div role="spinbutton" tabindex="0" aria-label="Часы" aria-valuenow="18"></div><div role="spinbutton" tabindex="0" aria-label="Минуты" aria-valuenow="44"></div><button id="confirm">Отправить 12 ноября в 19:45</button>';
  dialog.querySelector('[aria-label="Следующий месяц"]').onclick=()=>dialog.querySelector('.title').textContent='ноябрь 2030';
  dialog.querySelector('.day').onclick=e=>e.target.classList.add('day--selected');
  for(const spin of dialog.querySelectorAll('[role=spinbutton]'))spin.onkeydown=e=>{
   const modulo=spin.getAttribute('aria-label')==='Часы'?24:60;
   spin.setAttribute('aria-valuenow',String((+spin.getAttribute('aria-valuenow')+(e.key==='ArrowUp'?1:-1)+modulo)%modulo));
  };
  dialog.querySelector('#confirm').onclick=()=>window.confirmClicks++;
  document.body.append(dialog);dialog.showModal();
 };
}"""

async def setup_menu(writer, surface, after, drift=None):
    d,page,state,h=writer
    state['messages']=[dict(id='old',text='Bound caption',outgoing=True)]
    await d.open('-101')
    main=await d._scope('-101')
    await main.evaluate("m=>{const i=document.createElement('img');i.src='data:image/png;base64,AAAA';const a=document.createElement('div');a.className='attach';a.append(i);m.querySelector('.attaches').append(a);}")
    control=(d._rows(main,'Bound caption').locator('.bubbleContent > .text') if surface=='row'
             else main.get_by_role('button',name='Отправить сообщение',exact=True))
    label='Изменить время' if surface=='row' else 'Отправить позже'
    await control.evaluate(MENU,dict(after=after,label=label,drift=drift))
    return d,page,state,control,label

@pytest.mark.parametrize('surface',['row','send'])
@pytest.mark.parametrize('after',[1,2,3])
async def test_menu_absence_has_one_bounded_pre_effect_retry(writer,surface,after):
    d,page,state,control,label=await setup_menu(writer,surface,after)
    d.timeout=2
    if after==3:
        with pytest.raises(MaxBlocked,match='native_context_menu_not_open'):
            await d._open_context_menu(control)
    else:
        menu=await d._open_context_menu(control)
        assert await menu.get_by_role('menuitem',name=label,exact=True).count()==1
    assert await page.evaluate('window.opens')==min(after,2)
    assert await page.evaluate('window.confirmClicks')==0
    assert not effects(state) and not d.lane.marker.exists()

@pytest.mark.parametrize('drift',['detach','text','route','media'])
async def test_menu_retry_requires_same_connected_subject(writer,drift):
    d,page,state,control,_=await setup_menu(writer,'send',2,drift)
    d.timeout=2
    with pytest.raises(MaxBlocked,match='context_menu_subject_changed|native_context_menu_not_open'):
        await d._open_context_menu(control)
    assert await page.evaluate('window.opens')==1
    assert not effects(state) and not d.lane.marker.exists()

async def test_wrong_visible_menu_does_not_reopen_or_select(writer):
    d,page,state,control,_=await setup_menu(writer,'send',1)
    await control.evaluate(MENU,dict(after=1,label='Unrelated action'))
    await d._open_context_menu(control)
    assert await page.evaluate('window.opens')==1
    assert await page.evaluate('window.selectedMenu || null') is None
    with pytest.raises(MaxBlocked,match='context_menu_already_open'):
        await d._open_context_menu(control)
    assert await page.evaluate('window.opens')==1
    assert not effects(state)

async def test_row_ui_metadata_change_does_not_replace_authored_binding(writer):
    d,page,state,control,label=await setup_menu(writer,'row',2)
    await control.evaluate("e=>{const n=document.createElement('span');n.className='volatile';n.textContent='Initial UI metadata';e.closest('.messageWrapper').append(n)}")
    await control.evaluate(MENU,dict(after=2,label=label,drift='metadata'))
    await d._open_context_menu(control)
    assert await page.evaluate('window.opens')==2
    assert await control.text_content()=='Bound caption'
    assert not effects(state) and not d.lane.marker.exists()

class PreparedOnly(SystemExit): pass

@pytest.mark.parametrize('action',['publish','reschedule'])
@pytest.mark.parametrize('after_arm',[False,True,'after_marker'])
async def test_full_native_prepare_and_no_retry_after_arm(writer,monkeypatch,action,after_arm):
    d,page,state,h=writer
    d.evidence_pages=(page,)
    d.targets['-101']=Target('-101','Test Group','scheduled_only')
    state['messages']=[dict(id='old',text='Bound caption',outgoing=True)]
    original=dict(id='native-1',target='-101',namespace='scheduled',text='Bound caption',
        entities=[],media=[],observed_media=[],scheduled_at='2030-11-12T15:00:00Z')
    async def install_menu(main, row=False):
        await page.evaluate(CALENDAR)
        control=(main.locator('.bubbleContent > .text') if row else
                 main.get_by_role('button',name='Отправить сообщение',exact=True))
        await control.evaluate(MENU,dict(after=2,label='Изменить время' if row else 'Запланировать пост'))
    if action=='reschedule':
        async def read(*a,**kw):
            await page.goto(d.origin+'/-101')
            main=await d._scope('-101')
            await main.evaluate("""m=>{m.innerHTML='<span>Отложенные сообщения</span><div class="messageWrapper"><div class="bubbleContent"><span class="text">Bound caption</span><span class="meta"><span class="text">18:00</span></span></div></div>';}""")
            await install_menu(main,True)
            return [dict(original)]
        monkeypatch.setattr(queue,'read',read)
    else:
        class Observer:
            def __init__(self,*a):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
            async def wait(self,*a):return []
        monkeypatch.setattr(queue,'QueueObserver',Observer)
        compose=d._compose
        async def composed(main,*a):
            result=await compose(main,*a)
            await install_menu(main)
            return result
        monkeypatch.setattr(d,'_compose',composed)
    checkpoints=[]
    async def checkpoint(name,raw):
        checkpoints.append((name,json.loads(raw)))
        if not after_arm:raise PreparedOnly()
    import asyncio
    from contextlib import asynccontextmanager
    original_timeout=asyncio.timeout;resets=[];marked=False
    @asynccontextmanager
    async def tracked_timeout(seconds):
        async with original_timeout(seconds) as budget:
            def reset(deadline):
                resets.append(deadline-asyncio.get_running_loop().time())
                budget.reschedule(deadline)
            yield SimpleNamespace(reschedule=reset)
    monkeypatch.setattr(asyncio,'timeout',tracked_timeout)
    account=d._account
    async def checked_account():
        if marked and after_arm=='after_marker':raise RuntimeError('stop after committed marker, before click')
        return await account()
    monkeypatch.setattr(d,'_account',checked_account)
    async def dispatch(*a):
        nonlocal marked
        if after_arm!='after_marker':raise RuntimeError('dispatch refuses before click')
        marked=True
    h.checkpoint=checkpoint;h.before_effect=dispatch
    args=dict(scheduled_at='2030-11-12T16:45:00Z',attempt_id='attempt',plan_digest='plan',hooks=h)
    expected=MaxBlocked if after_arm else PreparedOnly
    import base64,hashlib
    photo=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==')
    media=({'name':'lecture.png','mimeType':'image/png','buffer':photo},)
    entities=({'type':'text_link','offset':8,'length':7,'url':'https://example.com/registration'},)
    with pytest.raises(expected,match='outcome_unknown' if after_arm else None):
        if action=='reschedule':await queue.reschedule(d,existing=original,**args)
        else:await queue.publish(d,target='-101',text='Lecture caption',entities=entities,media=media,**args)
    assert checkpoints[0][0]==('MAX_RESCHEDULE_PREPARED' if action=='reschedule' else 'MAX_PREPARED')
    assert checkpoints[0][1]['scheduled_at']=='2030-11-12T16:45:00Z'
    if action=='publish':
        assert checkpoints[0][1]['source_hashes']==[hashlib.sha256(photo).hexdigest()]
        assert checkpoints[0][1]['entities']==list(entities)
        assert await page.locator('[contenteditable] a').get_attribute('href')==entities[0]['url']
        assert await page.locator('.attaches .attach').count()==1
    assert await page.evaluate('window.opens')==2
    assert await page.evaluate('window.confirmClicks')==0
    assert not effects(state)
    assert d.lane.marker.exists()==bool(after_arm)
    assert len(resets)==(1 if after_arm=='after_marker' else 0)
    if resets:assert resets[0]==pytest.approx(d.timeout,abs=.02)

@pytest.mark.parametrize('primary',[False,True])
async def test_observer_cleanup_preserves_primary_exception(primary):
    from adapters.max.wire import QueueObserver
    calls=[]
    class BrokenSession:
        async def detach(self):
            calls.append('detach')
            raise RuntimeError('cleanup only')
    observer=QueueObserver(None,'-101','https://example.com')
    observer.sessions=[BrokenSession(),BrokenSession()]
    if primary:
        await observer.__aexit__(ValueError,ValueError('original'),None)
    else:
        with pytest.raises(RuntimeError,match='cleanup only'):
            await observer.__aexit__(None,None,None)
    assert calls==['detach','detach']
