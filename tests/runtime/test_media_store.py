import hashlib
import io
import json
from dataclasses import replace

import pytest
from PIL import Image

from adapters.port import (Capability, DownloadedMedia, MediaDownload, Observation,
                           Prepared, ReadPage, RemoteItem)
from social_operations.assets import insert_verified_image, verify_image
from social_operations.domain import canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker


def png():
    out=io.BytesIO();Image.new('RGB',(12,10),'blue').save(out,format='PNG');return out.getvalue()


class Provider:
    def __init__(self):
        self.effects=0;self.reads=0;self.fail_once=None;self.unknown_with_id_once=False;self.items={}
    async def prepare(self,request,hooks):
        if self.fail_once:
            code=self.fail_once;self.fail_once=None
            from social_operations.domain import DomainError
            raise DomainError(code)
        return Prepared(request,Capability('supported','media-store fixture'))
    async def execute(self,prepared,hooks):
        r=prepared.request
        await hooks.checkpoint('prepared',canonical({'ids':[]}))
        await hooks.before_effect(r.attempt_id,r.plan_digest);self.effects+=1
        evidence=tuple(DownloadedMedia(i,hashlib.sha256(a.data).hexdigest(),a.mime,len(a.data))
                       for i,a in enumerate(r.assets))
        item=RemoteItem(str(100+self.effects),'published',json.loads(r.content_json)['text'],'',timestamp(1800000000),
            media_hashes=tuple(a.sha256 for a in r.assets),media_check='provider_binding',native_target=r.native_target,
            provider_media=tuple('document:'+str(i+1) for i,_ in enumerate(r.assets)),member_ids=(str(100+self.effects),),
            observed_media=evidence,reply_to_native_id=r.topic_root_id)
        self.items[item.native_id]=(item,tuple(a.data for a in r.assets))
        await hooks.checkpoint('native_message_saved',canonical({'ids':[item.native_id]}))
        if self.unknown_with_id_once:
            self.unknown_with_id_once=False
            from social_operations.domain import DomainError
            raise DomainError('telegram_rpc_failed')
        return Observation('published',(item,))
    async def reconcile(self,request,checkpoint,hooks):
        state=json.loads(checkpoint); state=state.get('adapter',state)
        ids=state.get('ids',[])
        if ids and ids[0] in self.items:return Observation('published',(self.items[ids[0]][0],))
        return await self.execute(Prepared(request,Capability('supported','fixture')),hooks)
    async def read(self,request,hooks):
        self.reads+=1
        if request.kind!='item' or request.native_item not in self.items:return ReadPage(())
        item,payloads=self.items[request.native_item]
        downloads=tuple(MediaDownload(item.native_id,i,item.provider_media[i],'document',
                                      item.observed_media[i].mime,data)
                        for i,data in enumerate(payloads))
        return ReadPage((item,),downloads=downloads)


def runtime(tmp_path):
    store=Store(tmp_path/'ledger.sqlite');actor=store.authenticate(store.create_principal('t','owner',owner=True))
    store.add_connection(actor,'connection','telegram',account_type='fake');store.bind(actor,'owner','vault','connection','-1004379835477')
    data=png();verified=verify_image(data,'image/png')
    with store.tx() as db:asset=insert_verified_image(store,db,actor,verified)
    provider=Provider();app=Application(store);worker=Worker(store,{'telegram':provider})
    assert actor.owner
    assert 'vibepublish_media_store' in {tool['name'] for tool in app.tools(actor)}
    return store,actor,asset,provider,app,worker


def args(asset,key='vault-1', *, topic='5', text='Луноход — техническая подпись', origin=None):
    command={'kind':'put','to':'vault','thread_ref':f'https://t.me/c/4379835477/{topic}',
        'content':{'text':text},
        'media':[{'source':{'kind':'asset','id':asset},'role':'document'}]}
    if origin is not None:
        command['origin']=origin
    return {'command':command,'request_key':key}


@pytest.mark.asyncio
async def test_media_database_tool_is_owner_only(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    partner=store.authenticate(store.create_principal('t','partner'))
    assert 'vibepublish_media_store' not in {tool['name'] for tool in app.tools(partner)}
    denied=await app.call(partner,'vibepublish_media_store',{'command':{'kind':'search','text':'архив'}})
    assert denied['error']['code']=='access_denied'


@pytest.mark.asyncio
async def test_put_is_separate_idempotent_and_purges_verified_staging(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    with store.connection() as db: baseline_assets=db.execute('select count(*) from assets').fetchone()[0]
    accepted=await app.call(actor,'vibepublish_media_store',args(asset));assert accepted.get('action')=='media_store', accepted
    replay=await app.call(actor,'vibepublish_media_store',args(asset));assert replay['operation_id']==accepted['operation_id']
    with store.connection() as db:
        assert db.execute("select count(*) from media_store_assets where purpose='staging'").fetchone()[0]==1
        assert db.execute('select count(*) from assets').fetchone()[0]==baseline_assets+1
    await worker.run_once();done=store.receipt(actor,accepted['operation_id'])
    assert done['state']=='verified' and provider.effects==1
    with store.connection() as db:
        assert db.execute("select count(*) from publications where kind='media_store'").fetchone()[0]==1
        assert db.execute("select count(*) from media_store_assets where purpose='staging'").fetchone()[0]==0
        assert db.execute('select count(*) from assets').fetchone()[0]==baseline_assets

    listed=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'list','to':'vault',
        'thread_ref':'https://t.me/c/4379835477/5','text':'луноход'}})
    assert listed['state']=='verified' and provider.reads==0
    item,=listed['media_store_items'];assert item['native_id']=='101'
    assert item['destination']=='vault'
    assert item['thread_ref']=='https://t.me/c/4379835477/5'
    assert item['telegram_url']=='https://t.me/c/4379835477/101'
    assert item['sha256']==[hashlib.sha256(verify_image(png(),'image/png').data).hexdigest()]

    listed_without_alias=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'list',
        'thread_ref':'https://t.me/c/4379835477/5','text':'луноход'}})
    assert listed_without_alias['state']=='verified'
    assert [row['native_id'] for row in listed_without_alias['media_store_items']]==['101']

    mismatch=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'list','to':'other',
        'thread_ref':'https://t.me/c/4379835477/5'}})
    assert mismatch['error']['code']=='media_store_destination_mismatch'
    assert mismatch['next_action']=='fix_input'


@pytest.mark.asyncio
async def test_media_store_preserves_cross_service_origin_without_changing_binary_identity(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    source_hash=hashlib.sha256(png()).hexdigest()
    origin={'system':'regional_knowledge',
            'ref':'knowledge://illustrations/ill_0001',
            'sha256':source_hash}
    accepted=await app.call(actor,'vibepublish_media_store',
                            args(asset,'knowledge-origin',text='Иллюстрация из региональной базы',origin=origin))
    assert 'operation_id' in accepted, accepted
    await worker.run_once()
    assert store.receipt(actor,accepted['operation_id'])['state']=='verified'

    listed=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'list',
        'thread_ref':'https://t.me/c/4379835477/5','text':'региональной'}})
    item,=listed['media_store_items']
    assert item['origin']==origin
    assert item['sha256']==[hashlib.sha256(verify_image(png(),'image/png').data).hexdigest()]

    searched=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'search','text':'иллюстрация'}})
    assert searched['media_store_items'][0]['origin']==origin

    fetched=await app.call(actor,'vibepublish_media_store',
                           {'command':{'kind':'get','entry_ref':accepted['resource_id']}})
    await worker.run_once()
    fetched_done=store.receipt(actor,fetched['operation_id'])
    assert fetched_done['state']=='verified'
    assert fetched_done['media_store_items'][0]['origin']==origin

    replay=await app.call(actor,'vibepublish_media_store',
                          args(asset,'knowledge-origin',text='Иллюстрация из региональной базы',origin=origin))
    assert replay['operation_id']==accepted['operation_id']
    conflict=await app.call(actor,'vibepublish_media_store',
                            args(asset,'knowledge-origin',text='Иллюстрация из региональной базы',
                                 origin={**origin,'ref':'knowledge://illustrations/ill_0002'}))
    assert conflict['error']['code']=='idempotency_conflict'


@pytest.mark.asyncio
async def test_metadata_only_reread_preserves_exact_media_evidence(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    accepted=await app.call(actor,'vibepublish_media_store',args(asset))
    await worker.run_once(); assert store.receipt(actor,accepted['operation_id'])['state']=='verified'
    remote=provider.items['101'][0]
    metadata_only=replace(remote,observed_media=(),media_hashes=(),media_check='not_applicable')
    with store.tx() as db:
        destination=db.execute("SELECT destination_id FROM facts WHERE native_id='101'").fetchone()[0]
        worker.save_fact(db,destination,metadata_only)
    listed=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'list',
        'thread_ref':'https://t.me/c/4379835477/5'}})
    item,=listed['media_store_items']
    assert item['sha256']==[hashlib.sha256(verify_image(png(),'image/png').data).hexdigest()]


@pytest.mark.asyncio
async def test_changed_provider_media_invalidates_old_hash_without_breaking_list(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    accepted=await app.call(actor,'vibepublish_media_store',args(asset))
    await worker.run_once(); assert store.receipt(actor,accepted['operation_id'])['state']=='verified'
    changed=replace(provider.items['101'][0],provider_media=('document:replacement',),
                    observed_media=(),media_hashes=(),media_check='not_applicable')
    with store.tx() as db:
        destination=db.execute("SELECT destination_id FROM facts WHERE native_id='101'").fetchone()[0]
        worker.save_fact(db,destination,changed)
    listed=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'list',
        'thread_ref':'https://t.me/c/4379835477/5'}})
    assert listed['state']=='verified'
    assert listed['media_store_items'][0]['sha256']==[]


@pytest.mark.asyncio
async def test_global_search_finds_entries_across_topics_without_provider_io(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    first=await app.call(actor,'vibepublish_media_store',args(asset,'topic-5',topic='5',text='Луноход архив'))
    await worker.run_once(); assert store.receipt(actor,first['operation_id'])['state']=='verified'
    second=await app.call(actor,'vibepublish_media_store',args(asset,'topic-9',topic='9',text='Автобус архив'))
    await worker.run_once(); assert store.receipt(actor,second['operation_id'])['state']=='verified'

    found=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'search','text':'архив'}})
    assert found['action']=='media_store_search' and provider.reads==0
    assert {item['thread_ref'] for item in found['media_store_items']} == {
        'https://t.me/c/4379835477/5', 'https://t.me/c/4379835477/9'}
    only_bus=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'search','text':'автобус'}})
    assert [item['text'] for item in only_bus['media_store_items']]==['Автобус архив']


@pytest.mark.asyncio
async def test_get_downloads_exact_telegram_bytes_into_expiring_cache(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    put=await app.call(actor,'vibepublish_media_store',args(asset))
    await worker.run_once(); assert store.receipt(actor,put['operation_id'])['state']=='verified'
    with store.connection() as db: baseline=db.execute('select count(*) from assets').fetchone()[0]
    fetched=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'get','entry_ref':put['resource_id']}})
    assert fetched['action']=='read' and fetched['operation_complete'] is False
    await worker.run_once(); done=store.receipt(actor,fetched['operation_id'])
    assert done['state']=='verified' and provider.reads==1
    downloaded=done['items'][0]['media'][0]['source']['id']
    payload,mime,sha=app.read_asset(actor,downloaded)
    assert hashlib.sha256(payload).hexdigest()==sha and mime=='image/png'
    with store.connection() as db:
        expiry=db.execute("select expires from media_store_assets where asset_id=? and purpose='download_cache'",
                          (downloaded,)).fetchone()['expires']
        assert db.execute('select count(*) from assets').fetchone()[0]==baseline+1
    store.clock=lambda: expiry+1
    with pytest.raises(Exception) as error: app.read_asset(actor,downloaded)
    assert getattr(error.value,'code',None)=='asset_not_available'
    with store.connection() as db: assert db.execute('select count(*) from assets').fetchone()[0]==baseline


@pytest.mark.asyncio
@pytest.mark.parametrize('failure_code',['telegram_rpc_failed','telegram_cooldown'])
async def test_media_store_transient_failure_retries_without_connection_quarantine(tmp_path,failure_code):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    provider.fail_once=failure_code
    first=await app.call(actor,'vibepublish_media_store',args(asset)); assert 'operation_id' in first, first
    await worker.run_once();receipt=store.receipt(actor,first['operation_id'])
    assert receipt['state']=='running' and receipt['operation_complete'] is False
    second=await app.call(actor,'vibepublish_media_store',args(
        asset,'vault-2',text='Независимая запись во время повтора'))
    assert second['operation_id']!=first['operation_id']
    with store.connection() as db:
        db.execute("update operations set lease_until=0 where id=?",(first['operation_id'],))
    await worker.run_once();assert store.receipt(actor,first['operation_id'])['state']=='verified'


@pytest.mark.asyncio
async def test_known_native_id_recovers_after_worker_restart_without_second_effect(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path);provider.unknown_with_id_once=True
    accepted=await app.call(actor,'vibepublish_media_store',args(asset,'restart-recovery'))
    await worker.run_once()
    waiting=store.receipt(actor,accepted['operation_id'])
    assert waiting['state']=='running' and provider.effects==1
    with store.tx() as db:
        db.execute('update operations set lease_until=0 where id=?',(accepted['operation_id'],))
    restarted=Worker(store,{'telegram':provider})
    await restarted.run_once()
    assert store.receipt(actor,accepted['operation_id'])['state']=='verified'
    assert provider.effects==1


@pytest.mark.asyncio
async def test_abandoned_staging_expires_and_worker_purges_bytes(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    with store.connection() as db: baseline=db.execute('select count(*) from assets').fetchone()[0]
    accepted=await app.call(actor,'vibepublish_media_store',args(asset,'abandoned'))
    with store.connection() as db:
        staging=db.execute("select asset_id,expires from media_store_assets where purpose='staging'").fetchone()
        assert db.execute('select count(*) from assets').fetchone()[0]==baseline+1
    store.clock=lambda: staging['expires']+1
    await worker.run_once()
    with store.connection() as db:
        assert db.execute('select 1 from assets where id=?',(staging['asset_id'],)).fetchone() is None
        assert db.execute("select 1 from media_store_assets where purpose='staging'").fetchone() is None
    assert store.receipt(actor,accepted['operation_id'])['state']=='blocked'


@pytest.mark.asyncio
async def test_media_store_and_publication_unknowns_do_not_quarantine_each_other(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    public=await app.call(actor,'vibepublish_publish',{'to':['vault'],'content':{'text':'public unknown'},
        'media':[{'source':{'kind':'asset','id':asset},'role':'document'}]})
    with store.tx() as db:
        db.execute("update attempts set dispatched=1,state='outcome_unknown',stage='outcome_unknown' where operation_id=?",
                   (public['operation_id'],))
        db.execute("update operations set state='outcome_unknown',complete=1,work_state='done' where id=?",
                   (public['operation_id'],))
    private=await app.call(actor,'vibepublish_media_store',args(asset,'private-after-public-unknown'))
    await worker.run_once(); assert store.receipt(actor,private['operation_id'])['state']=='verified'

    store,actor,asset,provider,app,worker=runtime(tmp_path/'reverse')
    private_unknown=await app.call(actor,'vibepublish_media_store',args(asset,'private-unknown'))
    with store.tx() as db:
        db.execute("update attempts set dispatched=1,state='outcome_unknown',stage='outcome_unknown' where operation_id=?",
                   (private_unknown['operation_id'],))
        db.execute("update operations set state='outcome_unknown',complete=1,work_state='done' where id=?",
                   (private_unknown['operation_id'],))
    public_after=await app.call(actor,'vibepublish_publish',{'to':['vault'],
        'content':{'text':'public after private unknown'}})
    await worker.run_once(); assert store.receipt(actor,public_after['operation_id'])['state']=='verified'


class MutableClock:
    def __init__(self, value=1_800_000_000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def budget_runtime(tmp_path):
    clock=MutableClock()
    store=Store(tmp_path/'budget.sqlite',clock=clock)
    actor=store.authenticate(store.create_principal('t','owner',owner=True))
    store.add_connection(actor,'connection','telegram',account_type='fake')
    store.bind(actor,'owner','vault','connection','-1004379835477')
    data=png();verified=verify_image(data,'image/png')
    with store.tx() as db:asset=insert_verified_image(store,db,actor,verified)
    provider=Provider();app=Application(store);worker=Worker(store,{'telegram':provider})
    return clock,store,actor,asset,provider,app,worker


def media_put(asset,key,*,alias='vault',channel='4379835477',count=1,text=None):
    return {
        'command':{
            'kind':'put',
            'to':alias,
            'thread_ref':f'https://t.me/c/{channel}/5',
            'content':{'text':text or key},
            'media':[
                {'source':{'kind':'asset','id':asset},'role':'document'}
                for _ in range(count)
            ],
        },
        'request_key':key,
    }


async def run_count(worker,count):
    for _ in range(count):
        assert await worker.run_once()


def media_admissions(store,connection=None):
    with store.connection() as db:
        if connection is None:
            rows=db.execute(
                'SELECT connection_id,media_count,admitted_at '
                'FROM telegram_media_admissions ORDER BY admitted_at,id'
            ).fetchall()
        else:
            rows=db.execute(
                'SELECT connection_id,media_count,admitted_at '
                'FROM telegram_media_admissions WHERE connection_id=? '
                'ORDER BY admitted_at,id',(connection,)
            ).fetchall()
    return [dict(row) for row in rows]


@pytest.mark.asyncio
async def test_telegram_media_budget_25_files_survives_restart_and_respects_rolling_window(tmp_path):
    clock,store,actor,asset,provider,app,worker=budget_runtime(tmp_path)
    accepted=[
        await app.call(actor,'vibepublish_media_store',
                       media_put(asset,f'budget-{i}',text=f'Budget item {i}'))
        for i in range(25)
    ]
    assert len({item['operation_id'] for item in accepted})==25

    await run_count(worker,12)
    assert sum(row['media_count'] for row in media_admissions(store,'connection'))==12

    restarted=Worker(Store(store.path,clock=clock),{'telegram':provider})
    await run_count(restarted,13)
    rows=media_admissions(store,'connection')
    assert sum(row['media_count'] for row in rows)==20
    assert provider.effects==20
    with store.connection() as db:
        waiting=db.execute(
            "SELECT count(*) FROM attempts "
            "WHERE stage='waiting_connection' AND dispatched=0"
        ).fetchone()[0]
    assert waiting==5

    clock.advance(60.01)
    restarted_again=Worker(Store(store.path,clock=clock),{'telegram':provider})
    await run_count(restarted_again,5)
    rows=media_admissions(store,'connection')
    assert sum(row['media_count'] for row in rows)==25
    assert provider.effects==25

    dispatches=[
        row['admitted_at']
        for row in rows
        for _ in range(row['media_count'])
    ]
    for right_edge in dispatches:
        assert sum(
            right_edge-60.0 < observed <= right_edge
            for observed in dispatches
        ) <= 20


@pytest.mark.asyncio
async def test_telegram_media_budget_is_shared_with_publication_but_ignores_text(tmp_path):
    clock,store,actor,asset,provider,app,worker=budget_runtime(tmp_path)
    for i in range(20):
        await app.call(actor,'vibepublish_media_store',
                       media_put(asset,f'fill-{i}',text=f'Fill {i}'))
    await run_count(worker,20)
    assert sum(row['media_count'] for row in media_admissions(store,'connection'))==20

    media_publication=await app.call(actor,'vibepublish_publish',{
        'to':['vault'],'content':{'text':'ordinary media'},
        'media':[{'source':{'kind':'asset','id':asset},'role':'document'}],
        'request_key':'ordinary-media',
    })
    await worker.run_once()
    assert store.receipt(actor,media_publication['operation_id'])['state']=='running'
    assert provider.effects==20

    text_publication=await app.call(actor,'vibepublish_publish',{
        'to':['vault'],'content':{'text':'text only'},
        'request_key':'text-only',
    })
    await worker.run_once()
    assert store.receipt(actor,text_publication['operation_id'])['state']=='verified'
    assert provider.effects==21
    assert sum(row['media_count'] for row in media_admissions(store,'connection'))==20

    clock.advance(60.01)
    await Worker(Store(store.path,clock=clock),{'telegram':provider}).run_once()
    assert store.receipt(actor,media_publication['operation_id'])['state']=='verified'
    assert sum(row['media_count'] for row in media_admissions(store,'connection'))==21


@pytest.mark.asyncio
async def test_telegram_media_budget_is_per_connection_and_counts_album_members(tmp_path):
    clock,store,actor,asset,provider,app,worker=budget_runtime(tmp_path)
    store.add_connection(actor,'connection-2','telegram',account_type='fake')
    store.bind(actor,'owner','vault2','connection-2','-1004368830579')

    first=await app.call(actor,'vibepublish_media_store',
                         media_put(asset,'album-1',count=10,text='Album one'))
    second=await app.call(actor,'vibepublish_media_store',
                          media_put(asset,'album-2',count=10,text='Album two'))
    await run_count(worker,2)
    assert store.receipt(actor,first['operation_id'])['state']=='verified'
    assert store.receipt(actor,second['operation_id'])['state']=='verified'
    assert [row['media_count'] for row in media_admissions(store,'connection')]==[10,10]

    blocked=await app.call(actor,'vibepublish_media_store',
                           media_put(asset,'connection-1-full',text='Connection one full'))
    await worker.run_once()
    assert store.receipt(actor,blocked['operation_id'])['state']=='running'

    independent=await app.call(actor,'vibepublish_media_store',
        media_put(asset,'connection-2-free',alias='vault2',channel='4368830579',
                  text='Independent connection'))
    await worker.run_once()
    assert store.receipt(actor,independent['operation_id'])['state']=='verified'
    assert sum(row['media_count'] for row in media_admissions(store,'connection-2'))==1
    assert sum(row['media_count'] for row in media_admissions(store,'connection'))==20
