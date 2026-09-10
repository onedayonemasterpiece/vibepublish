"""Observed queued editor mode/Save guard; independent offline provider effects."""
from datetime import datetime,timezone,timedelta
import pytest
from adapters.max import queue
from adapters.max.profile import MaxBlocked
from tests.browser.max.observed.test_submit import writer
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('drift',[None,'mode','media','lazy_preview'])
async def test_scheduled_edit_retains_time_and_blocks_last_input_drift(writer,monkeypatch,drift):
    d,page,state,h=writer;d.live_writes=True
    state['messages']=[dict(id='scheduled-own',target='-101',text='Old caption',outgoing=True)]
    await d.open('-101')
    at=(datetime.now(timezone.utc)+timedelta(days=1)).replace(hour=9,minute=30,second=0,microsecond=0).isoformat()
    old=dict(id='scheduled-own',target='-101',text='Old caption',entities=[],namespace='scheduled',
        scheduled_at=at,media=[],observed_media=[],url=None,observed_at=at)
    await page.locator('main').evaluate('''main=>{main.innerHTML=`<span>Отложенные сообщения</span>
      <div class="messageWrapper"><div class="bubbleContent"><span class="text">Old caption</span><span class="meta"><span class="text">12:30</span></span></div></div>
      <div class="composer"><div class="attaches"></div><div role="textbox" contenteditable data-lexical-editor="true"></div><button aria-label="Отправить сообщение"></button></div>`;
      const row=main.querySelector('.messageWrapper'),editor=main.querySelector('[contenteditable]');
      row.oncontextmenu=e=>{e.preventDefault();const menu=document.createElement('div');menu.role='menu';
        menu.innerHTML='<button role="menuitem">Редактировать</button>';menu.firstChild.onclick=()=>{menu.remove();
          const title=document.createElement('span');title.className='edit-title';title.textContent='Редактирование сообщения';main.append(title);editor.textContent='Old caption';};document.body.append(menu);};
      main.querySelector('[aria-label="Отправить сообщение"]').onclick=async()=>{
        await fetch('/replay-event',{method:'POST',body:JSON.stringify({kind:'effect',action:'edit',target:'-101',existing:'scheduled-own',text:editor.textContent})});
        row.querySelector('.bubbleContent > .text').textContent=editor.textContent;editor.textContent='';main.querySelector('.edit-title')?.remove();};}''')
    if drift=='lazy_preview':
        old['observed_media']=[{'slot':0,'kind':'photo','sha256':'d'*64,'mime':'image/png','size':79}]
        await page.evaluate('''()=>{
            const open=document.querySelector('.messageWrapper').oncontextmenu;
            document.querySelector('.messageWrapper').oncontextmenu=e=>{open(e);
                const button=document.querySelector('[role=menuitem]'),edit=button.onclick;
                button.onclick=()=>{edit();setTimeout(()=>{
                    const attach=document.createElement('div');attach.className='attach';const image=document.createElement('img');
                    image.src='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==';
                    attach.append(image);document.querySelector('.attaches').append(attach);
                },1500);};};}''')
    reads=[]
    async def read(*args,**kwargs):
        reads.append(kwargs)
        return [dict(old,text='New caption') if len(reads)>1 else old]
    monkeypatch.setattr(queue,'read',read)
    dispatch=h.before_effect
    async def before(*args):
        await dispatch(*args)
        if drift=='mode':await page.locator('.edit-title').evaluate('e=>e.remove()')
        if drift=='media':await page.locator('.attaches').evaluate('e=>e.innerHTML="<div class=attach><img alt=changed></div>"')
    h.before_effect=before
    if drift in {'mode','media'}:
        with pytest.raises(MaxBlocked):await queue.edit(d,existing=old,text='New caption',entities=[],attempt_id='attempt',plan_digest='plan',hooks=h)
        assert not [e for e in state['events'] if e['kind']=='effect']
    else:
        result=await queue.edit(d,existing=old,text='New caption',entities=[],attempt_id='attempt',plan_digest='plan',hooks=h)
        assert result[0]['id']==old['id'] and result[0]['scheduled_at']==at
        assert len([e for e in state['events'] if e['kind']=='effect'])==1
        assert state['checkpoints'][-1][1]['transition']==dict(clicks=1,blocked=False)
        assert d.lane.marker.exists()
