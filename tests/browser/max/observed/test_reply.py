"""The existing writer's reply-mode guard, not another Send implementation."""
import pytest
from adapters.max import engagement
from adapters.max.profile import MaxBlocked
from tests.browser.max.observed.test_submit import writer
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('drift',[None,'mode','source'])
async def test_reply_binds_subject_preview_and_preserves_single_send(writer,monkeypatch,drift):
    d,page,state,h=writer;d.live_writes=True
    state['messages']=[dict(id='source',target='-101',text='Owned reply source',outgoing=True)]
    await d.open('-101')
    source=(await d.read('-101',native_item='source'))[0]
    original=d._open_message_menu
    async def menu(row):
        await original(row)
        await page.get_by_role('menu').evaluate('''menu=>{const reply=document.createElement('button');reply.role='menuitem';reply.textContent='Ответить';
          reply.onclick=()=>{menu.remove();const composer=document.querySelector('[data-testid=composer]');composer.classList.add('composer');
            const preview=document.createElement('div');preview.className='action';preview.innerHTML='<span class="text title">Ответ для Test</span><span class="text content">Owned reply source</span>';composer.prepend(preview);};menu.append(reply);}''')
    monkeypatch.setattr(d,'_open_message_menu',menu)
    async def verified(driver,item,subject):
        assert subject['id']=='source';return dict(item,reply_to_native_id='source')
    monkeypatch.setattr(engagement,'verify_reply',verified)
    before=h.before_effect
    async def dispatch(*args):
        await before(*args)
        if drift=='mode':await page.locator('.action').evaluate('e=>e.remove()')
        if drift=='source':await page.locator('.action > .content').evaluate('e=>e.textContent="Other subject"')
    h.before_effect=dispatch
    if drift:
        with pytest.raises(MaxBlocked):await d.submit_plain_candidate(target='-101',text='Owned reply',attempt_id='attempt',plan_digest='plan',hooks=h,reply_to=source)
        assert not [e for e in state['events'] if e['kind']=='effect']
    else:
        result=await d.submit_plain_candidate(target='-101',text='Owned reply',attempt_id='attempt',plan_digest='plan',hooks=h,reply_to=source)
        assert result['item']['reply_to_native_id']=='source'
        assert len([e for e in state['events'] if e['kind']=='effect'])==1
        assert state['checkpoints'][0][1]['reply_to']['id']=='source'
        assert state['checkpoints'][0][1]['action']=='reply'


async def test_duplicate_text_is_read_by_copied_native_identity_not_order(writer):
    d,page,state,h=writer
    state['messages']=[dict(id='first',target='-101',text='Same forwarded body',outgoing=True),
                       dict(id='second',target='-101',text='Same forwarded body',outgoing=True)]
    for native in ('second','first'):
        result=await d.read('-101',native_item=native)
        assert result[0]['id']==native
    assert not [e for e in state['events'] if e['kind']=='effect']


@pytest.mark.parametrize('action',['edit','delete'])
async def test_duplicate_body_lifecycle_keeps_the_other_native_object(writer,action):
    d,page,state,h=writer;d.live_writes=True
    state['messages']=[dict(id='first',target='-101',text='Same native body',outgoing=True),
                       dict(id='second',target='-101',text='Same native body',outgoing=True)]
    existing=(await d.read('-101',native_item='second'))[0]
    if action=='edit':
        result=await d.edit_plain_candidate(existing=existing,text='Edited second only',attempt_id='attempt',plan_digest='plan',hooks=h)
        assert result['item']['id']=='second'
        assert [m['text'] for m in state['messages'] if m['id']=='second']==['Edited second only']
    else:
        result=await d.delete_plain(existing=existing,attempt_id='attempt',plan_digest='plan',hooks=h)
        assert result['item']['id']=='second'
        recovered=await d.reconcile(state['checkpoints'][-1][1])
        assert recovered['item']['id']=='second'
        assert not [m for m in state['messages'] if m['id']=='second']
    assert [m['text'] for m in state['messages'] if m['id']=='first']==['Same native body']
    assert len([e for e in state['events'] if e['kind']=='effect'])==1


async def test_detached_readonly_delete_preparation_rebinds_before_single_effect(writer,monkeypatch):
    from playwright.async_api import Error
    d,page,state,h=writer;d.live_writes=True
    state['messages']=[dict(id='own',target='-101',text='Owned',outgoing=True)]
    existing=(await d.read('-101',native_item='own'))[0]
    original=d._plain_candidate;calls=0
    async def read(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==1:raise Error('Element is not attached to the DOM')
        return await original(*args,**kwargs)
    monkeypatch.setattr(d,'_plain_candidate',read)
    result=await d.delete_plain(existing=existing,attempt_id='attempt',plan_digest='plan',hooks=h)
    assert result['item']['id']=='own' and calls==2
    assert len([e for e in state['events'] if e['kind']=='effect'])==1


async def test_exact_read_never_downloads_or_projects_an_unrelated_candidate(writer,monkeypatch):
    d,page,state,h=writer
    state['messages']=[dict(id='wanted',target='-101',text='Exact wanted',outgoing=True),
                       dict(id='unrelated',target='-101',text='Unrelated candidate',outgoing=True)]
    original=d._plain_candidate;projected=[]
    async def candidate(target,text,row,**kwargs):
        projected.append(text)
        assert text=='Exact wanted'
        return await original(target,text,row,**kwargs)
    monkeypatch.setattr(d,'_plain_candidate',candidate)
    assert (await d.read('-101',native_item='wanted'))[0]['id']=='wanted'
    assert projected==['Exact wanted','Exact wanted']
    assert not [e for e in state['events'] if e['kind']=='effect']
