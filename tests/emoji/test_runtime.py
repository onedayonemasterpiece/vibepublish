from __future__ import annotations
import json
from dataclasses import replace
from datetime import datetime, timezone
import pytest
from adapters.telegram import TelegramAdapter
from adapters.vk import VKAdapter
from social_operations.domain import DomainError, OutcomeUnknown, canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import ScriptedTL, VKTransport, tg_message
from tests.providers.test_native_adapters import NOW, TARGETS, Journal, request
from .fixtures import EmojiClient, PAIR, FREE, THUMB


@pytest.fixture
def runtime(tmp_path):
    store = Store(tmp_path/'ledger.sqlite', clock=lambda: NOW)
    token = store.create_principal('tenant','owner',owner=True)
    actor = store.authenticate(token)
    client, vk = EmojiClient(), VKTransport()
    for p, account in [('telegram','mtproto_user'),('vk','vk_user')]:
        store.add_connection(actor,p,p,account_type=account,shared=True)
        store.bind(actor,'owner',p,p,TARGETS[p])
    adapters = {'telegram':TelegramAdapter(client,connection_id='telegram',tl=ScriptedTL(),clock=store.clock),
                'vk':VKAdapter(vk,connection_id='vk',clock=store.clock)}
    return store, actor, Application(store), Worker(store,adapters), client, vk, token


async def call(rt, name, args):
    result = await rt[2].call(rt[1], 'vibepublish_'+name, args)
    assert 'operation_id' in result, result
    return result


async def register(rt, revision=0):
    r = await call(rt,'destinations',{'command':{'kind':'emoji_set_register','destination':'telegram',
        'url':'https://t.me/addemoji/lovekenigofficial','expected_revision':revision}, 'request_key':f'register-{revision}'})
    await rt[3].run_once()
    done = rt[0].receipt(rt[1],r['operation_id'])
    assert done['state']=='verified', done
    return done


async def select(rt, catalog, cells=(2,3), alias='tretyakov', revision=0):
    c = catalog['emoji_catalog']
    return await call(rt,'destinations',{'command':{'kind':'emoji_alias_select','catalog_ref':c['catalog_ref'],
        'catalog_revision':c['revision'],'selection_token':c['selection_token'], 'cells':list(cells),
        'alias':alias,'expected_revision':revision,'fallback':'Третьяковская галерея'}})


async def rule(rt, name='theatre', alias='tretyakov', match='🎭', revision=0):
    return await call(rt,'destinations',{'command':{'kind':'emoji_rule_put','name':name,'match':match,
        'alias':alias,'enabled':True,'expected_revision':revision}})


def rich():
    return {'paragraphs':[[{'kind':'text','text':'Здание ','style':'bold'}, {'kind':'emoji','alias':'tretyakov'},
                           {'kind':'link','label':' Билеты','url':'https://example.org'}]]}


def done(rt,r):
    return rt[0].receipt(rt[1],r['operation_id'])


@pytest.mark.asyncio
async def test_E01_E02_registration_is_read_only_actual_media_numbering_and_replay(runtime):
    rt=runtime; catalog=await register(rt)
    assert rt[4].effects==0 and rt[4].downloads
    c=catalog['emoji_catalog']
    assert [e['cell'] for e in c['entries']]==list(range(1,13))
    assert [e['document_id'] for e in c['entries'][1:3]]==PAIR
    assert c['entries'][0]['document_id']==THUMB
    data,mime,sha=rt[2].read_asset(rt[1],c['sheets'][0]['preview_ref'])
    assert data[:8]==b'\x89PNG\r\n\x1a\n' and mime=='image/png' and sha==c['sheets'][0]['preview_sha256']
    replay=await register(rt)
    assert replay['operation_id']==catalog['operation_id']
    assert len(rt[4].downloads)==12


@pytest.mark.asyncio
@pytest.mark.parametrize('url',['https://t.me/addstickers/name','https://t.me.evil/addemoji/name',
    'https://t.me/addemoji/name?other=1','https://t.me/addemoji/name#foo','https://u@t.me/addemoji/name'])
async def test_E01_malformed_set_url_no_provider_io(runtime,url):
    r=await runtime[2].call(runtime[1],'vibepublish_destinations',{'command':{'kind':'emoji_set_register',
        'destination':'telegram','url':url,'expected_revision':0}})
    assert 'error' in r and not runtime[4].calls


@pytest.mark.asyncio
async def test_E01_ordinary_sticker_set_rejected(runtime):
    runtime[4].pack_emoji=False
    r=await call(runtime,'destinations',{'command':{'kind':'emoji_set_register','destination':'telegram',
        'url':'https://t.me/addemoji/test','expected_revision':0}})
    await runtime[3].run_once()
    assert done(runtime,r)['state']=='blocked'
    with runtime[0].connection() as db:
        assert not db.execute('SELECT * FROM emoji_catalogs').fetchall()


@pytest.mark.asyncio
async def test_E03_E04_revision_bound_chain_and_CAS(runtime):
    c=await register(runtime)
    chosen=await select(runtime,c,(3,2,3))
    assert [p['document_id'] for p in chosen['emoji_alias']['parts']]==[PAIR[1],PAIR[0],PAIR[1]]
    with pytest.raises(AssertionError,match='emoji_alias_revision_conflict'):
        await select(runtime,c,(1,1))
    await register(runtime,1)
    with pytest.raises(AssertionError,match='emoji_catalog_stale'):
        await select(runtime,c,(2,3),alias='new')
    with pytest.raises(DomainError,match='emoji catalog stale'):
        runtime[2].read_asset(runtime[1],c['emoji_catalog']['entries'][0]['preview_ref'])


@pytest.mark.asyncio
async def test_E08_foreign_palette_tokens_and_revoked_preview_status(runtime):
    c=await register(runtime); await select(runtime,c)
    store,owner,app,worker,*_=runtime
    token=store.create_principal('partner-tenant','partner',scopes={'publish','destinations','status','bootstrap'})
    store.bind(owner,'partner','telegram','telegram',TARGETS['telegram'])
    partner=store.authenticate(token)
    denied=await app.call(partner,'vibepublish_read',{'query':{'kind':'emoji_catalog','catalog_ref':c['emoji_catalog']['catalog_ref']}})
    assert denied['error']['code']=='emoji_catalog_not_available'
    with pytest.raises(DomainError):
        app.read_asset(partner,c['emoji_catalog']['entries'][0]['preview_ref'])
    with store.connection() as db:
        b=store.binding(db,owner,alias='telegram')
    store.revoke_binding(owner,b['id'])
    with pytest.raises(DomainError):
        app.read_asset(owner,c['emoji_catalog']['entries'][0]['preview_ref'])
    denied=await app.call(owner,'vibepublish_status',{'ids':[c['operation_id']]})
    assert 'error' in denied


@pytest.mark.asyncio
@pytest.mark.parametrize('scheduled',[False,True])
async def test_E09_native_rich_now_and_scheduled_no_delayed_editor(runtime,scheduled):
    c=await register(runtime); await select(runtime,c)
    r=await call(runtime,'publish',{'to':['telegram'],'content':rich(),
        **({'delivery':{'kind':'at','at':timestamp(NOW+3600)}} if scheduled else {})})
    assert runtime[4].effects==0
    await runtime[3].run_once()
    finished=done(runtime,r)
    assert finished['state']==('scheduled' if scheduled else 'verified'),finished
    requests=[q for name,q in runtime[4].calls if name=='SendMessageRequest']
    assert len(requests)==1
    assert [str(e.document_id) for e in requests[0].entities if type(e).__name__=='MessageEntityCustomEmoji']==PAIR
    assert not [q for name,q in runtime[4].calls if name=='EditMessageRequest']
    assert runtime[4].effects==1


@pytest.mark.asyncio
async def test_E08_approval_freezes_palette_revision_and_entities(runtime):
    c=await register(runtime); await select(runtime,c); await rule(runtime)
    r=await call(runtime,'publish',{'to':['telegram'],'content':{'text':'🎭'},'mode':'preview'})
    await runtime[3].run_once(); preview=done(runtime,r)
    assert preview['state']=='needs_approval' and runtime[4].effects==0
    assert [e['document_id'] for e in preview['content_previews'][0]['entities']]==PAIR
    await select(runtime,c,(1,1),revision=1)
    approval=await call(runtime,'publication_update',{'publication_id':preview['resource_id'],'expected_revision':1,
        'change':{'kind':'approve','token':preview['review_token']}})
    await runtime[3].run_once()
    assert done(runtime,approval)['state']=='verified',done(runtime,approval)
    sent=next(q for name,q in runtime[4].calls if name=='SendMessageRequest')
    assert [str(e.document_id) for e in sent.entities]==PAIR


@pytest.mark.asyncio
async def test_E09_edit_and_reschedule_preserve_exact_native_entities(runtime):
    c=await register(runtime); await select(runtime,c)
    r=await call(runtime,'publish',{'to':['telegram'],'content':rich(),'delivery':{'kind':'at','at':timestamp(NOW+3600)}})
    await runtime[3].run_once(); initial=done(runtime,r)
    change=await call(runtime,'publication_update',{'publication_id':initial['resource_id'],'expected_revision':1,
        'change':{'kind':'reschedule','delivery':{'kind':'at','at':timestamp(NOW+7200)}}})
    await runtime[3].run_once(); assert done(runtime,change)['state']=='scheduled',done(runtime,change)
    change=await call(runtime,'publication_update',{'publication_id':initial['resource_id'],'expected_revision':2,
        'change':{'kind':'edit','content':rich()}})
    await runtime[3].run_once(); assert done(runtime,change)['state']=='scheduled',done(runtime,change)
    edits=[q for name,q in runtime[4].calls if name=='EditMessageRequest']
    assert len(edits)==2
    assert all([str(e.document_id) for e in q.entities if type(e).__name__=='MessageEntityCustomEmoji']==PAIR for q in edits)


@pytest.mark.asyncio
@pytest.mark.parametrize('bad',['dropped','wrong_id','wrong_offset','wrong_link'])
async def test_E10_wrong_or_missing_native_entities_never_verified(runtime,bad):
    c=await register(runtime); await select(runtime,c)
    def corrupt(_):
        m=next(iter(runtime[4].messages.values()))
        if bad=='dropped': m.entities=[]
        elif bad=='wrong_id': next(e for e in m.entities if hasattr(e,'document_id')).document_id=int(THUMB)
        elif bad=='wrong_link': next(e for e in m.entities if hasattr(e,'url')).url='https://wrong.example.org'
        else: next(e for e in m.entities if hasattr(e,'document_id')).offset+=1
    runtime[4].after_mutation=corrupt
    r=await call(runtime,'publish',{'to':['telegram'],'content':rich()})
    await runtime[3].run_once(); assert done(runtime,r)['state']=='outcome_unknown'
    await runtime[3].run_once(); assert runtime[4].effects==1


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['no_response','after_checkpoint'])
async def test_E10_restart_reconciles_without_second_send(runtime,failure):
    c=await register(runtime); await select(runtime,c)
    r=await call(runtime,'publish',{'to':['telegram'],'content':rich()})
    adapter=runtime[3].adapters['telegram']
    op=runtime[0].claim('fixture-worker')
    with runtime[0].connection() as db:
        child=dict(db.execute('SELECT * FROM attempts WHERE operation_id=?',(r['operation_id'],)).fetchone())
    w=Worker(runtime[0],{'telegram':adapter},worker_id='fixture-worker')
    req=w.request(op,child,runtime[1]); hooks=w.hooks(op,child)
    if failure=='no_response':
        def fail(_): raise RuntimeError('response lost')
        runtime[4].after_mutation=fail
    else:
        runtime[4].fail_read=True
    # prepare before introducing a readback-only fault; no existing item on first publish.
    prepared=await adapter.prepare(req,hooks)
    with pytest.raises((DomainError,OSError)):
        await adapter.execute(prepared,hooks)
    runtime[4].after_mutation=None; runtime[4].fail_read=False
    with runtime[0].tx() as db:
        db.execute('UPDATE operations SET lease_until=? WHERE id=?',(NOW-1,op['id']))
    await Worker(runtime[0],{'telegram':adapter}).run_once()
    assert done(runtime,r)['state']==('outcome_unknown' if failure=='no_response' else 'verified'),done(runtime,r)
    assert runtime[4].effects==1


@pytest.mark.asyncio
@pytest.mark.parametrize('problem',['premium','limit','deleted','changed_alt','bot'])
async def test_eligibility_checked_before_effect(runtime,problem):
    c=await register(runtime); await select(runtime,c)
    if problem=='premium': runtime[4].premium=False
    if problem=='limit': runtime[4].maximum=1
    if problem=='deleted': runtime[4].docs=runtime[4].docs[:1]
    if problem=='changed_alt': runtime[4].docs[1].attributes[0].alt='😀'
    if problem=='bot':
        runtime[4].bot=True
        runtime[3].adapters['telegram'].account_type='mtproto_bot'
    r=await call(runtime,'publish',{'to':['telegram'],'content':rich()})
    await runtime[3].run_once()
    assert done(runtime,r)['state']=='blocked' and runtime[4].effects==0


@pytest.mark.asyncio
async def test_nonpremium_free_documents_allowed(runtime):
    c=await register(runtime); await select(runtime,c)
    runtime[4].premium=False
    for d in runtime[4].docs: d.attributes[0].free=True
    r=await call(runtime,'publish',{'to':['telegram'],'content':rich()})
    await runtime[3].run_once(); assert done(runtime,r)['state']=='verified'


@pytest.mark.asyncio
async def test_E11_vk_explicit_fallback_and_native_forward_untouched(runtime):
    c=await register(runtime); await select(runtime,c); await rule(runtime)
    content={'paragraphs':[[{'kind':'emoji','alias':'tretyakov'}]]}
    r=await call(runtime,'publish',{'to':['telegram','vk'],'content':content,'emoji_fallback':'approved_text'})
    await runtime[3].run_once(); assert done(runtime,r)['state']=='verified',done(runtime,r)
    post=next(iter(runtime[5].posts.values())); assert post['text']=='Третьяковская галерея'
    # Forward one exact provider source; ordinary trigger and existing custom IDs stay intact.
    message=tg_message(77,202,'🎭🖼🖼')
    message.entities=[runtime[3].adapters['telegram'].tl.type('MessageEntityCustomEmoji',offset=2+i*2,length=2,document_id=int(id)) for i,id in enumerate(PAIR)]
    runtime[4].messages[(202,77)]=message
    r=await call(runtime,'engage',{'command':{'kind':'forward','item_ref':'https://t.me/source/77','to':['telegram']}})
    await runtime[3].run_once(); assert done(runtime,r)['state']=='verified',done(runtime,r)
    forwarded=runtime[4].messages[(101,runtime[4].next_id)]
    assert forwarded.message=='🎭🖼🖼' and [str(e.document_id) for e in forwarded.entities]==PAIR


@pytest.mark.asyncio
async def test_E11_unsupported_vk_target_does_not_discard_telegram_success(runtime):
    c=await register(runtime); await select(runtime,c)
    r=await call(runtime,'publish',{'to':['telegram','vk'],'content':{'paragraphs':[[{'kind':'emoji','alias':'tretyakov'}]]}})
    await runtime[3].run_once(); receipt=done(runtime,r)
    assert receipt['state']=='partial',receipt
    assert runtime[4].effects==1 and runtime[5].effects==0
    assert [d['state'] for d in receipt['deliveries']]==['verified','blocked']


@pytest.mark.asyncio
async def test_preview_render_is_private_and_uses_exact_sanitized_bytes(runtime):
    import httpx
    from social_operations.server import create_app
    c=await register(runtime)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime[0])),base_url='http://testserver') as client:
        path='/v1/emoji/catalogs/'+c['emoji_catalog']['catalog_ref']
        assert (await client.get(path)).status_code==401
        r=await client.get(path,headers={'Authorization':'Bearer '+runtime[6]})
        assert r.status_code==200 and r.headers['cache-control']=='no-store'
        assert r.text.count('class="cell"')==12
        assert 'data:image/png;base64,' in r.text
        assert 'default-src' in r.headers['content-security-policy']
        assert 'frame-ancestors \'none\'' in r.headers['content-security-policy']


@pytest.mark.asyncio
async def test_palette_lists_current_disabled_rules_and_cas_can_turn_them_off(runtime):
    rt=runtime; c=await register(rt);await select(rt,c);await rule(rt)
    result=await call(rt,'read',{'query':{'kind':'emoji_palette'}})
    assert result['emoji_rules'][0]['revision']==1 and result['emoji_rules'][0]['enabled']
    changed=await call(rt,'destinations',{'command':{'kind':'emoji_rule_put','name':'theatre',
        'match':'🎭','alias':'tretyakov','enabled':False,'expected_revision':result['emoji_rules'][0]['revision']}})
    assert changed['emoji_rule']['revision']==2
    palette=await call(rt,'read',{'query':{'kind':'emoji_palette'}})
    assert len(palette['emoji_rules'])==1 and palette['emoji_rules'][0]['enabled'] is False
    post=await call(rt,'publish',{'to':['telegram'],'content':{'text':'🎭'}})
    await rt[3].run_once()
    assert done(rt,post)['state']=='verified'
    sent=[req for name,req in rt[4].calls if name=='SendMessageRequest'][-1]
    assert sent.entities==[]


@pytest.mark.asyncio
async def test_catalog_read_token_budget_is_bounded_without_invalidating_prior_choices(runtime):
    rt=runtime; c=await register(rt); page=c['emoji_catalog']
    with rt[0].tx() as db:
        for n in range(1999):
            db.execute('INSERT INTO emoji_choices VALUES(?,?,?,?,?,?)',
                (str(n),page['catalog_ref'],rt[1].tenant_id,rt[1].principal_id,rt[1].epoch,rt[0].clock()+900))
    error=await rt[2].call(rt[1],'vibepublish_read',{'query':{'kind':'emoji_catalog','catalog_ref':page['catalog_ref']}})
    assert error['error']['code']=='emoji_preview_rate_limit'
    chosen=await select(rt,c)
    assert chosen['emoji_alias']['parts'][0]['document_id']==PAIR[0]


@pytest.mark.asyncio
async def test_multi_page_catalog_has_authenticated_cursor_link_and_absolute_cell_numbers(runtime):
    from copy import copy
    from social_operations.emoji_preview import render_catalog
    rt=runtime
    for n in range(40):
        doc=copy(rt[4].docs[0]);doc.id=1000+n;rt[4].docs.append(doc)
    c=await register(rt);page=c['emoji_catalog']
    assert len(page['entries'])==50 and page['total']==52
    markup,_=render_catalog(rt[2],rt[1],c)
    assert 'Следующая страница каталога' in markup and '?cursor=' in markup
    second=await call(rt,'read',{'query':{'kind':'emoji_catalog','catalog_ref':page['catalog_ref']},'cursor':c['next_cursor']})
    assert [e['cell'] for e in second['emoji_catalog']['entries']]==[51,52]
    chosen=await select(rt,second,cells=(52,2,51))
    assert chosen['emoji_alias']['cells']==[52,2,51]


@pytest.mark.asyncio
async def test_nonfinite_provider_limit_is_a_typed_pre_effect_gate(runtime):
    rt=runtime;c=await register(rt);await select(rt,c)
    rt[4].maximum=float('nan')
    result=await call(rt,'publish',{'to':['telegram'],'content':rich()})
    await rt[3].run_once()
    assert done(rt,result)['state']=='blocked'
    assert rt[4].effects==0


@pytest.mark.asyncio
async def test_palette_storage_snapshots_are_immutable_and_emoji_bootstrap_is_bounded(runtime):
    import sqlite3
    rt=runtime;c=await register(rt);await select(rt,c);await rule(rt)
    with rt[0].tx() as db:
        for table in ('emoji_aliases','emoji_rules','emoji_catalogs'):
            with pytest.raises(sqlite3.IntegrityError,match='immutable emoji'):
                db.execute(f"UPDATE {table} SET snapshot='{{}}'")
    brief=rt[2].bootstrap(rt[1],{'section':'emoji'})
    full=rt[2].bootstrap(rt[1],{})
    assert len(brief['skill'])<len(full['skill'])
    assert 'emoji_alias_select' in brief['skill'] and 'unknown outcome' in brief['skill']
