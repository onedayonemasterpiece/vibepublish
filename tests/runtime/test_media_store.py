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

    retrieved=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'get','entry_ref':item['entry_ref']}})
    await worker.run_once()
    assert store.receipt(actor,retrieved['operation_id'])['media_store_items'][0]['origin']==origin

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


@pytest.mark.asyncio
async def test_origin_metadata_does_not_require_byte_identical_image(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    raw=io.BytesIO();Image.new('RGB',(40,30),'orange').save(raw,format='PNG',compress_level=9)
    data=raw.getvalue();verified=verify_image(data,'image/png');assert verified.data!=data
    with store.tx() as db:derivative=insert_verified_image(store,db,actor,verified)
    origin={'system':'regional_knowledge','ref':'knowledge://illustrations/synthetic','sha256':hashlib.sha256(data).hexdigest()}
    accepted=await app.call(actor,'vibepublish_media_store',args(derivative,'exact-origin-bytes',origin=origin))
    assert 'operation_id' in accepted,accepted;await worker.run_once()
    done=store.receipt(actor,accepted['operation_id']);assert done['state']=='verified'
    assert next(iter(provider.items.values()))[1]==(verified.data,)
    replay=await app.call(actor,'vibepublish_media_store',args(derivative,'exact-origin-bytes',origin=origin));assert replay['operation_id']==accepted['operation_id']
    mismatch=await app.call(actor,'vibepublish_media_store',args(derivative,'different-hash',origin={**origin,'sha256':'a'*64}));assert 'operation_id' in mismatch,mismatch
    no_hash=await app.call(actor,'vibepublish_media_store',args(derivative,'no-image-hash',origin={k:v for k,v in origin.items() if k!='sha256'}));assert 'operation_id' in no_hash,no_hash


@pytest.mark.asyncio
async def test_knowledge_origin_sha_is_independent_but_provider_hash_stays_authoritative(tmp_path):
    store,actor,asset,provider,app,worker=runtime(tmp_path)
    execute=provider.execute
    async def transformed(prepared,hooks):
        observation=await execute(prepared,hooks)
        return replace(observation,items=(replace(observation.items[0],media_hashes=('a'*64,)),))
    provider.execute=transformed
    origin={'system':'regional_knowledge','ref':'knowledge://illustrations/changed-rendition'}
    accepted=await app.call(actor,'vibepublish_media_store',args(asset,'changed-rendition',origin=origin))
    await worker.run_once()
    done=store.receipt(actor,accepted['operation_id'])
    # A saved native message is reconciled by observation, never sent again.
    assert done['state']=='running'
    with store.tx() as db:
        child=db.execute('SELECT * FROM attempts WHERE operation_id=?',(accepted['operation_id'],)).fetchone()
        assert child['state']=='running'
        assert child['stage']=='waiting_connection'
        assert 'media_readback_mismatch' in json.loads(child['result'])['missing_checks']
        db.execute('UPDATE operations SET lease_until=0 WHERE id=?',(accepted['operation_id'],))
    await worker.run_once()
    assert store.receipt(actor,accepted['operation_id'])['state']=='verified'
    assert provider.effects==1


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy_in_flight',[False,True])
async def test_source_document_original_and_clone_purge_preserve_lost_response_replay(tmp_path,legacy_in_flight):
    from social_operations.asset_ingress import upload_image
    store,actor,_,provider,app,worker=runtime(tmp_path)
    data=b'%PDF-1.7\nExact synthetic source bytes.\n'
    ingress=upload_image(app,actor,data,'application/pdf','source-upload')
    with store.tx() as db:
        db.execute("update operations set result=json_remove(result,'$.document_receipt') where action='asset_ingress'")
    command=args(ingress['asset_id'],key='source-put',origin={'system':'regional_knowledge','ref':'knowledge://documents/control/source','sha256':hashlib.sha256(data).hexdigest()})
    accepted=await app.call(actor,'vibepublish_media_store',command)
    if legacy_in_flight:
        with store.tx() as db:
            db.execute("update operations set result=json_remove(result,'$.document_receipt') where action='asset_ingress'")
    await worker.run_once();assert store.receipt(actor,accepted['operation_id'])['state']=='verified'
    with store.connection() as db:
        assert db.execute("select count(*) from assets where mime='application/pdf'").fetchone()[0]==0
    assert upload_image(app,actor,data,'application/pdf','source-upload')==ingress
    assert (await app.call(actor,'vibepublish_media_store',command))['operation_id']==accepted['operation_id']
    assert provider.effects==1
    listed=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'list','to':'vault','thread_ref':'https://t.me/c/4379835477/5'}})
    read=await app.call(actor,'vibepublish_media_store',{'command':{'kind':'get','entry_ref':listed['media_store_items'][0]['entry_ref']}})
    await worker.run_once();assert store.receipt(actor,read['operation_id'])['state']=='verified'

@pytest.mark.asyncio
async def test_scoped_machine_archive_put_get_and_denials(tmp_path):
    """RKB can archive exact topics without gaining owner or ordinary publish."""
    from social_operations.asset_ingress import upload_image
    store, owner, _asset, provider, app, worker = runtime(tmp_path)
    token = store.create_principal(
        "t", "regional-knowledge-mirror", scopes={"bootstrap", "status", "media.store"})
    service = store.authenticate(token)
    store.bind(owner, service.principal_id, "rkb-archive", "connection",
               "-1004379835477", rights=("publish",))
    tools = {item["name"] for item in app.tools(service)}
    assert "vibepublish_media_store" in tools
    assert "vibepublish_publication_update" in tools
    update_tool = next(tool for tool in app.tools(service)
                       if tool["name"] == "vibepublish_publication_update")
    allowed_changes = update_tool["inputSchema"]["properties"]["change"]["oneOf"]
    assert [part["properties"]["kind"]["const"] for part in allowed_changes] == ["retry_failed"]
    assert "vibepublish_publish" not in tools
    assert "vibepublish_visual" not in tools
    assert "vibepublish_destinations" not in tools
    assert not service.owner

    pdf = b"%PDF-1.7\nExact KB original synthetic test bytes.\n"
    stored = upload_image(app, service, pdf, "application/pdf", "rkb-original-asset")
    assert stored["sha256"] == hashlib.sha256(pdf).hexdigest()
    def command(topic, key):
        return {
            "command": {
                "kind": "put", "to": "rkb-archive",
                "thread_ref": f"https://t.me/c/4379835477/{topic}",
                "content": {"text": "Synthetic regional source"},
                "origin": {"system": "regional_knowledge",
                           "ref": "knowledge://documents/synthetic/source",
                           "sha256": hashlib.sha256(pdf).hexdigest()},
                "media": [{"source": {"kind": "asset", "id": stored["asset_id"]},
                           "role": "document"}]
            }, "request_key": key
        }

    denied = await app.call(service, "vibepublish_media_store", command("2", "rkb-file-1"))
    assert denied["error"]["code"] == "access_denied"
    assert provider.effects == 0

    granted = store.set_service_media_topic(owner, service.principal_id, "rkb-archive", "2")
    assert granted["enabled"] is True
    assert store.set_service_media_topic(owner, service.principal_id, "rkb-archive", "2") == granted
    invalid = await app.call(service, "vibepublish_media_store", command("4", "rkb-file-2"))
    assert invalid["error"]["code"] == "access_denied"

    admitted = await app.call(service, "vibepublish_media_store", command("2", "rkb-file-1"))
    assert "operation_id" in admitted, admitted
    replay = await app.call(service, "vibepublish_media_store", command("2", "rkb-file-1"))
    assert replay["operation_id"] == admitted["operation_id"]
    await worker.run_once()
    assert store.receipt(service, admitted["operation_id"])["state"] == "verified"
    assert provider.effects == 1

    forbidden = await app.call(service, "vibepublish_media_store", {
        "command": {"kind": "list", "thread_ref": "https://t.me/c/4379835477/4"}})
    assert forbidden["error"]["code"] == "access_denied"
    visible = await app.call(service, "vibepublish_media_store", {
        "command": {"kind": "list", "thread_ref": "https://t.me/c/4379835477/2"}})
    assert visible["state"] == "verified"
    item, = visible["media_store_items"]
    assert item["origin"]["sha256"] == hashlib.sha256(pdf).hexdigest()
    read = await app.call(service, "vibepublish_media_store", {
        "command": {"kind": "get", "entry_ref": item["entry_ref"]},
        "request_key": "scoped-get"})
    assert "operation_id" in read, read
    await worker.run_once()
    receipt = store.receipt(service, read["operation_id"])
    assert receipt["state"] == "verified"
    assets = [media["source"]["id"] for item in receipt.get("items", [])
              for media in item.get("media", [])
              if media.get("source", {}).get("kind") == "asset"]
    assert len(assets) == 1
    exact, mime, sha = app.read_asset(service, assets[0])
    assert exact == pdf
    assert mime == "application/pdf"
    assert sha == hashlib.sha256(pdf).hexdigest()

    revoked = store.set_service_media_topic(owner, service.principal_id, "rkb-archive", "2",
                                            enabled=False)
    assert revoked["enabled"] is False
    current_service = store.authenticate(token)
    after = await app.call(current_service, "vibepublish_media_store", {
        "command": {"kind": "list", "thread_ref": "https://t.me/c/4379835477/2"}})
    assert after["error"]["code"] == "access_denied"
    denied_replay = await app.call(current_service, "vibepublish_media_store", {
        "command": {"kind": "get", "entry_ref": item["entry_ref"]},
        "request_key": "scoped-get"})
    assert denied_replay["error"]["code"] == "access_denied"
    assert provider.reads == 1
    from social_operations.domain import DomainError
    with pytest.raises(DomainError) as exc:
        app.read_asset(current_service, assets[0])
    assert exc.value.code == "access_denied"


def test_service_media_topic_grants_validate_target_scope(tmp_path):
    from social_operations.domain import DomainError
    store, owner, asset, provider, app, worker = runtime(tmp_path)
    service = store.authenticate(store.create_principal(
        "t", "knowledge-service", scopes={"bootstrap", "status", "media.store"}))
    store.bind(owner, service.principal_id, "rkb-archive", "connection",
               "-1004379835477", rights=("publish",))
    for topic in ("0", "02", "invalid", "-1", "9" * 40):
        with pytest.raises(DomainError):
            store.set_service_media_topic(owner, service.principal_id, "rkb-archive", topic)
    other = store.authenticate(store.create_principal(
        "t", "ordinary-service", scopes={"bootstrap", "status"}))
    with pytest.raises(DomainError):
        store.set_service_media_topic(owner, other.principal_id, "rkb-archive", "2")
    with pytest.raises(DomainError):
        store.set_service_media_topic(service, service.principal_id, "rkb-archive", "2")



def get_args(entry_ref, key=None):
    result = {'command': {'kind': 'get', 'entry_ref': entry_ref}}
    if key is not None:
        result['request_key'] = key
    return result


@pytest.mark.asyncio
async def test_get_key_recovers_lost_admission_response_across_restart(tmp_path, monkeypatch):
    import sqlite3
    store, actor, asset, provider, app, worker = runtime(tmp_path)
    put = await app.call(actor, 'vibepublish_media_store', args(asset))
    await worker.run_once()
    command = get_args(put['resource_id'], 'durable-get')
    receipt = store.receipt
    def lost_response(*args, **kwargs):
        raise sqlite3.OperationalError('synthetic lost admission response')
    monkeypatch.setattr(store, 'receipt', lost_response)
    lost = await app.call(actor, 'vibepublish_media_store', command)
    assert lost['error']['code'] == 'store_unavailable'
    with store.connection() as db:
        original = db.execute("select operation_id from request_keys where key='durable-get'").fetchone()[0]
        assert db.execute("select count(*) from operations where action='read'").fetchone()[0] == 1
    monkeypatch.setattr(store, 'receipt', receipt)
    restarted = Store(store.path)
    app = Application(restarted)
    replay = await app.call(actor, 'vibepublish_media_store', command)
    assert replay['operation_id'] == original
    assert replay['operation_complete'] is False
    await Worker(restarted, {'telegram': provider}).run_once()
    replay = await app.call(actor, 'vibepublish_media_store', command)
    assert replay['operation_id'] == original
    assert replay['state'] == 'verified'
    assert provider.reads == 1
    with restarted.connection() as db:
        assert db.execute("select count(*) from operations where action='read'").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_get_key_survives_interrupted_pending_worker(tmp_path):
    import asyncio
    store, actor, asset, provider, app, worker = runtime(tmp_path)
    put = await app.call(actor, 'vibepublish_media_store', args(asset))
    await worker.run_once()
    command = get_args(put['resource_id'], 'pending-get')
    accepted = await app.call(actor, 'vibepublish_media_store', command)
    entered = asyncio.Event()
    original_read = provider.read
    async def interrupted(*args):
        entered.set()
        await asyncio.Event().wait()
    provider.read = interrupted
    task = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(entered.wait(), 2)
    replay = await app.call(actor, 'vibepublish_media_store', command)
    assert replay['operation_id'] == accepted['operation_id']
    assert replay['operation_complete'] is False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    provider.read = original_read
    with store.tx() as db:
        db.execute('update operations set lease_until=0 where id=?', (accepted['operation_id'],))
    restarted = Store(store.path)
    await Worker(restarted, {'telegram': provider}).run_once()
    replay = await Application(restarted).call(actor, 'vibepublish_media_store', command)
    assert replay['operation_id'] == accepted['operation_id']
    assert replay['state'] == 'verified'
    assert provider.reads == 1


@pytest.mark.asyncio
async def test_get_provider_timeout_replays_original_terminal_failure(tmp_path):
    store, actor, asset, provider, app, worker = runtime(tmp_path)
    put = await app.call(actor, 'vibepublish_media_store', args(asset))
    await worker.run_once()
    async def timeout(*args):
        provider.reads += 1
        raise TimeoutError
    provider.read = timeout
    command = get_args(put['resource_id'], 'timeout-get')
    accepted = await app.call(actor, 'vibepublish_media_store', command)
    await worker.run_once()
    restarted = Store(store.path)
    replay = await Application(restarted).call(actor, 'vibepublish_media_store', command)
    assert replay['operation_id'] == accepted['operation_id']
    assert replay['operation_complete'] is True
    assert replay['state'] == 'blocked'
    assert replay['error']['code'] == 'provider_read_deadline'
    assert provider.reads == 1
    assert await Worker(restarted, {'telegram': provider}).run_once() is False


@pytest.mark.asyncio
async def test_get_key_is_atomic_under_concurrent_admission_and_quota(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store, actor, asset, provider, app, worker = runtime(tmp_path)
    put = await app.call(actor, 'vibepublish_media_store', args(asset))
    await worker.run_once()
    with store.tx() as db:
        db.execute('update tenants set command_limit=1 where id=?', (actor.tenant_id,))
    command = get_args(put['resource_id'], 'concurrent-get')
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: app.media_store(actor, command), range(8)))
    assert len({r['operation_id'] for r in receipts}) == 1
    with store.connection() as db:
        assert db.execute("select count(*) from operations where action='read'").fetchone()[0] == 1
        assert db.execute("select count(*) from request_keys where key='concurrent-get'").fetchone()[0] == 1
    assert provider.reads == 0


@pytest.mark.asyncio
async def test_get_key_conflicts_with_other_entry_or_put_intent(tmp_path):
    store, actor, asset, provider, app, worker = runtime(tmp_path)
    first = await app.call(actor, 'vibepublish_media_store', args(asset, 'first-put'))
    await worker.run_once()
    second = await app.call(actor, 'vibepublish_media_store', args(asset, 'second-put', text='Another source'))
    await worker.run_once()
    accepted = await app.call(actor, 'vibepublish_media_store', get_args(first['resource_id'], 'bound-get'))
    assert accepted['operation_complete'] is False
    for entry, key in ((second['resource_id'], 'bound-get'), (first['resource_id'], 'first-put')):
        conflict = await app.call(actor, 'vibepublish_media_store', get_args(entry, key))
        assert conflict['error']['code'] == 'idempotency_conflict'
    with store.connection() as db:
        assert db.execute("select count(*) from operations where action='read'").fetchone()[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('other_tenant', [False, True])
async def test_get_key_does_not_share_entry_or_operation_across_owners(tmp_path, other_tenant):
    store, actor, asset, provider, app, worker = runtime(tmp_path)
    first = await app.call(actor, 'vibepublish_media_store', args(asset))
    await worker.run_once()
    accepted = await app.call(actor, 'vibepublish_media_store', get_args(first['resource_id'], 'same-key'))
    other = store.authenticate(store.create_principal('other-t' if other_tenant else 't', 'other-owner', owner=True))
    store.add_connection(other, 'other-connection', 'telegram', account_type='fake')
    store.bind(other, other.principal_id, 'vault', 'other-connection', '-1004379835477')
    denied = await app.call(other, 'vibepublish_media_store', get_args(first['resource_id'], 'same-key'))
    assert denied['error']['code'] == 'media_store_entry_not_found'
    with store.tx() as db:
        other_asset = insert_verified_image(store, db, other, verify_image(png(), 'image/png'))
    second = await app.call(other, 'vibepublish_media_store', args(other_asset, 'other-put'))
    await worker.run_once()
    await worker.run_once()
    own = await app.call(other, 'vibepublish_media_store', get_args(second['resource_id'], 'same-key'))
    assert own['operation_id'] != accepted['operation_id']
    with store.connection() as db:
        assert db.execute("select count(*) from request_keys where key='same-key'").fetchone()[0] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('revocation', ['actor', 'binding'])
async def test_get_key_does_not_reauthorize_old_receipt_after_epoch_change(tmp_path, revocation):
    store, actor, asset, provider, app, worker = runtime(tmp_path)
    put = await app.call(actor, 'vibepublish_media_store', args(asset))
    await worker.run_once()
    command = get_args(put['resource_id'], 'epoch-get')
    accepted = await app.call(actor, 'vibepublish_media_store', command)
    await worker.run_once()
    with store.tx() as db:
        if revocation == 'actor':
            db.execute('update principals set epoch=epoch+1 where id=?', (actor.principal_id,))
            actor = replace(actor, epoch=actor.epoch + 1)
        else:
            db.execute('update bindings set epoch=epoch+1,alias=? where principal_id=?', ('renamed-vault', actor.principal_id))
    replay = await app.call(actor, 'vibepublish_media_store', command)
    assert replay['error']['code'] == 'access_revoked'
    assert provider.reads == 1


@pytest.mark.asyncio
async def test_get_replay_preserves_expired_asset_receipt_without_redownload(tmp_path):
    from social_operations.domain import DomainError
    store, actor, asset, provider, app, worker = runtime(tmp_path)
    put = await app.call(actor, 'vibepublish_media_store', args(asset))
    await worker.run_once()
    command = get_args(put['resource_id'], 'cache-get')
    accepted = await app.call(actor, 'vibepublish_media_store', command)
    await worker.run_once()
    done = store.receipt(actor, accepted['operation_id'])
    asset_id = done['items'][0]['media'][0]['source']['id']
    with store.connection() as db:
        expiry = db.execute('select expires from media_store_assets where asset_id=?', (asset_id,)).fetchone()[0]
    store.clock = lambda: expiry + 1
    replay = await app.call(actor, 'vibepublish_media_store', command)
    assert replay['operation_id'] == accepted['operation_id']
    assert replay['items'] == done['items']
    with pytest.raises(DomainError) as exc:
        app.read_asset(actor, asset_id)
    assert exc.value.code == 'asset_not_available'
    assert provider.reads == 1
    fresh = await app.call(actor, 'vibepublish_media_store', get_args(put['resource_id'], 'fresh-cache-get'))
    assert fresh['operation_id'] != accepted['operation_id']
    await worker.run_once()
    fresh_done = store.receipt(actor, fresh['operation_id'])
    assert fresh_done['state'] == 'verified'
    fresh_id = fresh_done['items'][0]['media'][0]['source']['id']
    assert fresh_id != asset_id
    assert app.read_asset(actor, fresh_id)[0]
    assert provider.reads == 2


@pytest.mark.asyncio
async def test_get_without_key_keeps_fresh_read_semantics(tmp_path):
    store, actor, asset, provider, app, worker = runtime(tmp_path)
    put = await app.call(actor, 'vibepublish_media_store', args(asset))
    await worker.run_once()
    first = await app.call(actor, 'vibepublish_media_store', get_args(put['resource_id']))
    second = await app.call(actor, 'vibepublish_media_store', get_args(put['resource_id']))
    assert first['operation_id'] != second['operation_id']
    await worker.run_once()
    await worker.run_once()
    assert provider.reads == 2
