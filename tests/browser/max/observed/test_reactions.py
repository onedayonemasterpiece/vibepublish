"""Observed canvas palette structure, trusted input and restart (offline)."""
import json
from types import SimpleNamespace
import pytest
from adapters.max import engagement
from adapters.max.profile import MaxBlocked
from tests.browser.max.observed.test_submit import writer
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('drift',[None,'row','palette','account','crash'])
async def test_one_native_reaction_click_or_guarded_zero_then_read_only_reconcile(writer,monkeypatch,drift):
    d,page,state,h=writer;d.live_writes=True
    state['messages']=[dict(id='own',target='-101',text='Owned source',outgoing=True)]
    await d.open('-101');effects=[]
    old=dict(id='own',target='-101',namespace='feed',url='https://max.ru/c/-101/own',text='Owned source',
        entities=[],media=[],observed_media=[],scheduled_at=None,own_reactions=[],own_reactions_observed=True)
    async def native_observe(*a,**kw):return dict(old,own_reactions=['👍'] if effects else [])
    monkeypatch.setattr(engagement,'observe',native_observe)
    async def copy(*a):return old['url'],old['id']
    monkeypatch.setattr(d,'_copy_native_reference',copy)
    async def native_effect(route):
        assert d.lane.marker.exists() and state['dispatched']==('attempt','plan')
        assert state['checkpoints'][0][0]=='MAX_REACTION_PREPARED'
        effects.append('👍');await route.fulfill(body='ok')
    await page.route('**/reaction-event',native_effect)
    async def menu(*a):
        await page.evaluate('''()=>{const panel=document.createElement('div');panel.innerHTML=`
            <div class="reactionsSlot"><div class="reactions" style="display:flex;width:84px;height:40px">
            <button class="reaction" style="width:40px;height:40px"><canvas width="24" height="24"></canvas></button>
            <button class="reaction" style="width:40px;height:40px"><canvas width="24" height="24"></canvas></button>
            </div></div><div role="menu"></div>`;
            panel.querySelector('button').onclick=()=>fetch('/reaction-event',{method:'POST'});
            document.body.append(panel);}''')
    monkeypatch.setattr(d,'_open_message_menu',menu)
    async def identify(*a,**kw):
        if drift=='palette':await page.locator('.reactions').evaluate('e=>e.append(e.firstElementChild)')
        return dict(index=0,certain=True,supplementary_only=True)
    d.visual_palette=SimpleNamespace(identify=identify)
    dispatch=h.before_effect
    async def before(*args):
        await dispatch(*args)
        if drift=='row':await page.locator('.bubbleContent > .text').evaluate('e=>e.textContent="Foreign"')
        if drift=='account':state['revoked']=True
    h.before_effect=before
    if drift=='crash':state['fail_checkpoint']='MAX_REACTION_CLICKED'
    if drift:
        with pytest.raises((MaxBlocked,RuntimeError)):
            await engagement.react(d,existing=old,reaction='👍',reaction_mode='add',attempt_id='attempt',plan_digest='plan',hooks=h)
        if drift!='crash':assert effects==[];return
    else:
        result=await engagement.react(d,existing=old,reaction='👍',reaction_mode='add',attempt_id='attempt',plan_digest='plan',hooks=h)
        assert result[0]['own_reactions']==['👍']
    saved=state['checkpoints'][0][1]
    result=await engagement.reconcile_reaction(d,saved)
    assert result['item']['own_reactions']==['👍'] and effects==['👍'] and d.lane.marker.exists()
