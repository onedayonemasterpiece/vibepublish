"""Native scheduled confirmation and durable removal regression (offline replay)."""
from datetime import datetime, timezone, timedelta
import pytest
from adapters.max import queue
from adapters.max.profile import MaxBlocked
from tests.browser.max.observed.test_submit import writer
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('policy',['test_group','scheduled_only'])
@pytest.mark.parametrize('changed',[False,'text','media'])
async def test_cancel_exact_native_row_guard_and_recovery(writer,monkeypatch,changed,policy):
    d,page,state,h=writer
    d.live_writes=True
    from adapters.max.live import Target
    d.targets['-101']=Target('-101','Test Group',policy)
    await d.mutation_preflight('-101','cancel')
    if policy=='scheduled_only':
        with pytest.raises(MaxBlocked,match='immediate_publication_denied'):
            await d.mutation_preflight('-101','publish')
    await d.open('-101')
    at=(datetime.now(timezone.utc)+timedelta(days=1)).replace(hour=9,minute=30,second=0,microsecond=0).isoformat().replace('+00:00','Z')
    item=dict(id='scheduled-own',target='-101',namespace='scheduled',text='Owned scheduled',entities=[],
        media=[],observed_media=[],scheduled_at=at,observed_at='2026-09-08T00:00:00Z',url=None)
    await page.locator('main').evaluate('''(main,title)=>{main.innerHTML=`<span>Отложенные сообщения</span>
      <div class="messageWrapper"><div class="bubbleContent"><span class="text">Owned scheduled</span><span class="meta"><span class="text">12:30</span></span></div></div>`;
      const row=main.querySelector('.messageWrapper');row.oncontextmenu=e=>{e.preventDefault();
        const menu=document.createElement('div');menu.role='menu';
        menu.innerHTML='<button role="menuitem">Удалить</button>';
        menu.firstChild.onclick=()=>{menu.remove();const dialog=document.createElement('dialog');
          dialog.innerHTML='<h2>'+title+'</h2><button>Удалить</button><button>Отмена</button>';
          dialog.querySelector('button').onclick=async()=>{await fetch('/replay-event',{method:'POST',body:JSON.stringify({kind:'effect',action:'delete',target:'-101',existing:'scheduled-own'})});row.remove();dialog.remove();};
          document.body.append(dialog);dialog.showModal();};document.body.append(menu);};}''','Удалить пост' if policy=='scheduled_only' else 'Удалить сообщение')
    async def read(*a,**kw):return [dict(item)]
    monkeypatch.setattr(queue,'read',read)
    checks=[]
    async def absent(driver,saved):
        assert saved['transition']==dict(clicks=1,removed=True,blocked=False)
        assert await page.locator('.messageWrapper').count()==0
        checks.append(saved);return dict(item)
    monkeypatch.setattr(queue,'cancelled_item',absent)
    original_dispatch=h.before_effect
    async def dispatch_changed(*args):
        await original_dispatch(*args)
        if changed=='text':await page.locator('.bubbleContent > .text').evaluate('e=>e.textContent="Foreign replacement"')
        if changed=='media':await page.locator('.messageWrapper').evaluate('e=>{const image=document.createElement("img");image.src="data:image/png;base64,AAAA";const grid=document.createElement("div");grid.setAttribute("aria-label","Прикрепленные фото");grid.append(image);e.append(grid);}')
    h.before_effect=dispatch_changed
    if changed:
        with pytest.raises(MaxBlocked):await queue.cancel(d,existing=item,attempt_id='attempt',plan_digest='plan',hooks=h)
        assert not [e for e in state['events'] if e['kind']=='effect']
        return
    result=await queue.cancel(d,existing=item,attempt_id='attempt',plan_digest='plan',hooks=h)
    assert result[0]['id']==item['id'] and len(checks)==1 and d.lane.marker.exists()
    raw=state['checkpoints'][-1][1]
    recovered=await queue.reconcile(d,raw)
    assert recovered['item']['id']==item['id']
    assert len([e for e in state['events'] if e['kind']=='effect'])==1
    assert d.lane.marker.exists() # Only core post-commit finalization releases it.


@pytest.mark.parametrize('policy,label',[('test_group','Отправить позже'),('scheduled_only','Запланировать пост')])
async def test_native_schedule_context_menu_is_target_surface_specific(writer,policy,label):
    from adapters.max.live import Target
    d,page,state,h=writer
    d.targets['-101']=Target('-101','Test Group',policy)
    await d.open('-101');main=await d._scope('-101')
    await main.get_by_role('button',name='Отправить сообщение',exact=True).evaluate("""button=>{
      button.oncontextmenu=e=>{e.preventDefault();e.stopImmediatePropagation();
        const menu=document.createElement('div');menu.role='menu';
        for(const name of ['Запланировать пост','Отправить позже']){const item=document.createElement('button');
          item.role='menuitem';item.textContent=name;item.onclick=()=>{window.selectedScheduleLabel=name;menu.remove();};menu.append(item);}
        document.body.append(menu);};} """)
    await queue.open_schedule_dialog(d,'-101',main)
    assert await page.evaluate('window.selectedScheduleLabel')==label
    assert not [e for e in state['events'] if e['kind']=='effect']
