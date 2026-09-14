"""Observed recipient dialog: semantic selection, one Send, no source re-upload."""
import pytest
from adapters.max import engagement
from adapters.max.profile import MaxBlocked
from tests.browser.max.observed.test_submit import writer
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('drift',[None,'order','recipient','source','media'])
async def test_native_forward_dialog_identity_is_not_chat_position(writer,monkeypatch,drift):
    d,page,state,h=writer;d.live_writes=True
    state['messages']=[dict(id='AAAAAAAAACo',target='-101',text='Owned forward source',outgoing=True)]
    await d.open('-101');source=(await d.read('-101',native_item='AAAAAAAAACo'))[0];effects=[]
    async def observe(*a,**kw):return dict(source,own_reactions=[],own_reactions_observed=True,history_ids=['42'])
    monkeypatch.setattr(engagement,'observe',observe)
    class History:
        def __init__(self,*a,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def wait(self,*a):return [{'id':'42'}]
    monkeypatch.setattr(engagement,'HistoryObserver',History)
    async def candidate(*a):return dict(source,id='forwarded',url='https://max.ru/c/-101/forwarded',origin=source['url'],forward_origin_matched=True)
    monkeypatch.setattr(engagement,'forward_candidate',candidate)
    original=d._open_message_menu
    async def menu(row):
        await original(row)
        await page.get_by_role('menu').evaluate('''menu=>{const forward=document.createElement('button');forward.role='menuitem';forward.textContent='Переслать';
          forward.onclick=()=>{menu.remove();const d=document.createElement('dialog');d.innerHTML=`
            <input placeholder="Найти чат или канал"><div class="options">
            <button role="option" aria-selected="false"><span class="name"><span class="text">Channel B</span></span></button>
            <button role="option" aria-selected="false"><span class="name"><span class="text">Test Group</span></span></button></div>
            <button aria-label="Отправить сообщение"></button>`;
            d.querySelectorAll('[role=option]').forEach(b=>b.onclick=()=>b.setAttribute('aria-selected','true'));
            d.querySelector('[aria-label="Отправить сообщение"]').onclick=async()=>{await fetch('/forward-event',{method:'POST'});
                const source=document.querySelector('.messageWrapper');source.parentElement.append(source.cloneNode(true));d.remove();};
            document.body.append(d);d.showModal();};menu.append(forward);}''')
    monkeypatch.setattr(d,'_open_message_menu',menu)
    async def effect(route):
        assert state['dispatched']==('attempt','plan') and d.lane.marker.exists()
        assert state['checkpoints'][0][0]=='MAX_FORWARD_PREPARED'
        effects.append(1);await route.fulfill(body='ok')
    await page.route('**/forward-event',effect)
    before=h.before_effect
    async def dispatch(*args):
        await before(*args)
        if drift=='order':await page.locator('.options').evaluate('e=>e.append(e.firstElementChild)')
        if drift=='recipient':await page.locator('[aria-selected=true] .text').evaluate('e=>e.textContent="Other"')
        if drift=='media':await page.locator('.messageWrapper').evaluate('e=>e.insertAdjacentHTML("beforeend","<div class=media><img src=\"data:image/png;base64,AAAA\"></div>")')
        if drift=='source':await page.locator('.bubbleContent > .text').evaluate('e=>e.textContent="Other"')
    h.before_effect=dispatch
    if drift in {'recipient','source','media'}:
        with pytest.raises(MaxBlocked):await engagement.forward(d,subject=source,target='-101',attempt_id='attempt',plan_digest='plan',hooks=h)
        assert effects==[]
    else:
        result=await engagement.forward(d,subject=source,target='-101',attempt_id='attempt',plan_digest='plan',hooks=h)
        assert effects==[1] and result[0]['forward_origin_matched']
