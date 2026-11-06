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


@pytest.mark.parametrize('native',['wanted','absent'])
async def test_exact_read_returns_only_requested_native_object_without_download(writer,native):
    d,page,state,h=writer
    state['messages']=[dict(id='wanted',target='-101',text='Exact wanted',outgoing=True),
                       dict(id='unrelated',target='-101',text='Unrelated candidate',outgoing=True,
                            media=['https://i.oneme.ru/replay/unrelated.png'])]
    downloads=[]
    page.on('download',lambda download: downloads.append(download))
    if native=='absent':
        with pytest.raises(MaxBlocked,match='^exact_read_not_observed$'):
            await d.read('-101',native_item=native)
    else:
        result=await d.read('-101',native_item=native)
        assert len(result)==1 and result[0]['id']=='wanted' and result[0]['text']=='Exact wanted'
        assert result[0]['media']==[] and result[0]['observed_media']==[]
    assert not downloads and not [e for e in state['events'] if e['kind']=='effect']


async def test_tall_album_reveals_native_media_before_readiness(writer):
    """A visible long caption does not put its lazy photo grid in view."""
    from adapters.max.wire import link_id_from_wire_id
    d,page,state,_=writer
    text='Album caption'
    media=[f'https://i.oneme.ru/replay/album-{i}.png' for i in range(6)]
    state['messages']=[dict(id='album',target='-101',text=text,
                           html='<strong>Album</strong> caption',outgoing=True,media=media)]
    await d.open('-101')
    await page.evaluate("""()=>{
        const main=document.querySelector('main');
        main.style.cssText='height:500px;width:700px;overflow:auto';
        const row=main.querySelector('.messageWrapper');
        row.style.cssText='display:flex;flex-direction:column;height:1234px';
        const media=row.querySelector('.media');
        media.style.cssText='display:block;height:505px;flex-shrink:0;order:-1';
        const grid=media.firstElementChild;
        grid.style.cssText='display:grid;grid-template-columns:repeat(3,1fr);height:100%';
        const caption=row.querySelector('.bubbleContent');
        caption.style.cssText='height:729px;flex-shrink:0';
        const lazy=new IntersectionObserver(entries=>{
            for(const entry of entries)if(entry.isIntersecting){
                const tile=entry.target;
                const image=document.createElement('img');image.src=tile.dataset.source;
                tile.replaceChildren(image);lazy.unobserve(tile);
            }
        },{root:main});
        for(const tile of grid.children){
            tile.dataset.source=tile.querySelector('img').src;
            const placeholder=document.createElement('div');placeholder.className='image-placeholder';
            tile.replaceChildren(placeholder);lazy.observe(tile);
        }
        main.scrollTop=main.scrollHeight;
    }""")
    row=d._rows(page.locator('main'),text,outgoing=True)
    assert await row.locator('[aria-label="Прикрепленные фото"] > button').count()==6
    assert await row.locator('.media img').count()<6
    d.timeout=2
    item=await d._plain_candidate('-101',text,row,media_count=6,native_history_id='123456789')
    assert item['id']==link_id_from_wire_id('123456789')
    assert item['media']==media and item['text']==text
    assert item['entities']==[dict(type='bold',offset=0,length=5)]
    assert item['observed_media']==[]
    assert not [e for e in state['events'] if e['kind'] in {'effect','copy'}]
