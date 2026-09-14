import hashlib
import io
import json

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


def args(asset,key='vault-1', *, topic='5', text='Луноход — техническая подпись'):
    return {'command':{'kind':'put','to':'vault','thread_ref':f'https://t.me/c/4379835477/{topic}',
        'content':{'text':text},
        'media':[{'source':{'kind':'asset','id':asset},'role':'document'}]},'request_key':key}


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
async def test_media_store_transient_failure_retries_without_connection_quarantine(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path);provider.fail_once='telegram_rpc_failed'
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
