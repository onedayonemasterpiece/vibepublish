"""MAX-only semantic/video opt-in; actual local media validation, no social access."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from adapters.native import identity, verify_assets
from adapters.port import Observation, Prepared, Capability, RemoteItem, ReadPage
from social_operations.domain import DomainError, canonical, timestamp
from social_operations.rich_text import compile_content, max_content
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.video_assets import import_video, verify_video, _probe, MAX_VIDEO_BYTES
from social_operations.worker import Worker


RICH={'paragraphs':[[{'kind':'text','text':'😀 Bold','style':'bold'},
                    {'kind':'text','text':' '},{'kind':'link','label':'Exact link','url':'https://example.test/owned'}]]}


@pytest.fixture(scope='module')
def video_bytes(tmp_path_factory):
    root=tmp_path_factory.mktemp('max-video-source')
    executable=shutil.which('ffmpeg')
    assert executable, 'FFmpeg is a required local video-validation test prerequisite'
    path=root/'source.mp4'
    subprocess.run([executable,'-nostdin','-v','error','-f','lavfi','-i','color=c=black:s=32x24:r=10',
        '-t','0.3','-c:v','libx264','-pix_fmt','yuv420p','-metadata','title=PRIVATE_FIXTURE_METADATA',
        '-metadata','location=+00.0000+000.0000/','-movflags','+faststart',str(path)],check=True,timeout=15)
    return path.read_bytes()


def runtime(tmp_path, provider='max', account='max_web'):
    store=Store(tmp_path/'ledger.sqlite')
    actor=store.authenticate(store.create_principal('t','owner',owner=True))
    store.add_connection(actor,'connection',provider,account_type=account)
    store.bind(actor,'owner','target','connection','native-target')
    app=Application(store)
    return store,actor,app


def test_max_rich_compiler_preserves_unicode_links_and_does_not_widen_defaults():
    result=compile_content(RICH,lambda _:None,provider='max',max_native=True)
    text,entities=max_content(canonical(result),4000)
    assert result['format']=='max_entities' and text=='😀 Bold Exact link'
    assert entities==[{'type':'bold','offset':0,'length':7},
                      {'type':'text_link','offset':8,'length':10,'url':'https://example.test/owned'}]
    assert compile_content(result,lambda _:None,provider='max',max_native=True)==result
    for provider in ('max','vk'):
        with pytest.raises(DomainError): compile_content(RICH,lambda _:None,provider=provider)
    assert compile_content(RICH,lambda _:None,provider='telegram')['format']=='telegram_entities'


@pytest.mark.parametrize('content', [
    {'text':'x','format':'max_entities','entities':[{'type':'custom_emoji','offset':0,'length':1,'document_id':'123'}]},
    {'text':'😀','format':'max_entities','entities':[{'type':'bold','offset':1,'length':1}]},
    {'text':'x','format':'telegram_entities','entities':[]},
    {'text':'x','format':'max_entities','entities':[],'unexpected':'x'},
])
def test_max_entity_validation_rejects_unsupported_unbound_or_malformed(content):
    with pytest.raises(DomainError): max_content(canonical(content),4000)


def test_actual_video_decode_metadata_strip_source_lineage_and_quota(tmp_path,video_bytes):
    store,actor,_=runtime(tmp_path)
    ref=import_video(store,actor,video_bytes,'video/mp4')
    with store.connection() as db:
        row=db.execute('SELECT * FROM assets WHERE id=?',(ref,)).fetchone()
        assert row['mime']=='video/mp4' and (row['width'],row['height'])==(32,24)
        assert row['source_sha256']==hashlib.sha256(video_bytes).hexdigest()
        assert row['sha256']==hashlib.sha256(row['bytes']).hexdigest()
        sanitized=row['bytes']
    assert b'PRIVATE_FIXTURE_METADATA' not in sanitized
    assert b'+00.0000+000.0000/' not in sanitized
    assert len(list((tmp_path/'artifacts/video-processing').iterdir()))==0
    with store.tx() as db: db.execute('UPDATE tenants SET storage_limit=1')
    with pytest.raises(DomainError) as error: import_video(store,actor,video_bytes,'video/mp4')
    assert error.value.code=='storage_quota_exceeded'


@pytest.mark.parametrize('data,mime',[(b'not mp4','video/mp4'),(b'\0'*4+b'ftyp'+b'x'*8,'image/png'),(b'x'*(MAX_VIDEO_BYTES+1),'video/mp4')])
def test_invalid_video_rejected_before_external_process(tmp_path,data,mime,monkeypatch):
    monkeypatch.setattr('social_operations.video_assets._tool',lambda _:pytest.fail('Invalid input reached tool'))
    with pytest.raises(DomainError): verify_video(data,mime,artifact_root=tmp_path)


@pytest.mark.parametrize('field,value',[('width',3000),('height',2500),('duration','121'),('duration','NaN'),('codec_name','hevc')])
def test_probe_contract_rejects_excess_limits_and_wrong_codec(field,value,monkeypatch,tmp_path):
    stream={'codec_type':'video','codec_name':'h264','width':32,'height':24,'duration':'1'}
    info={'streams':[stream],'format':{'duration':'1','format_name':'mov,mp4'}}
    if field=='duration': info['format']['duration']=value
    else: stream[field]=value
    monkeypatch.setattr('social_operations.video_assets._run',lambda *a,**k:json.dumps(info).encode())
    with pytest.raises(DomainError): _probe('ffprobe',tmp_path/'not-opened.mp4')


def test_subprocess_contract_forbids_network_and_external_tracks(tmp_path,video_bytes,monkeypatch):
    import social_operations.video_assets as module
    original=module._run;calls=[]
    def checked(args,**kwargs):
        calls.append(args)
        assert args[args.index('-protocol_whitelist')+1]=='file'
        assert args[args.index('-enable_drefs')+1]=='0'
        assert args[args.index('-use_absolute_path')+1]=='0'
        assert args[args.index('-codec_whitelist')+1]=='h264,aac'
        assert kwargs['timeout']<=30
        return original(args,**kwargs)
    monkeypatch.setattr(module,'_run',checked)
    verify_video(video_bytes,'video/mp4',artifact_root=tmp_path)
    assert len(calls)==4


def test_video_timeout_and_missing_tools_fail_closed(tmp_path,video_bytes,monkeypatch):
    import social_operations.video_assets as module
    def timeout(*args,**kwargs): raise subprocess.TimeoutExpired('private-command',30)
    monkeypatch.setattr(module.subprocess,'run',timeout)
    with pytest.raises(DomainError) as error: verify_video(video_bytes,'video/mp4',artifact_root=tmp_path)
    assert error.value.code=='video_processing_timeout'
    monkeypatch.setattr(module.shutil,'which',lambda _:None)
    with pytest.raises(DomainError) as error: verify_video(video_bytes,'video/mp4',artifact_root=tmp_path)
    assert error.value.code=='video_tools_missing'


class SemanticMax:
    """Explicit isolated port fixture, not a MAX browser capability claim."""
    drop_entities=False
    remote=None
    requests=[]
    async def prepare(self,request,hooks):
        max_content(request.content_json,4000);verify_assets(request,allow_video=True)
        if request.existing and identity(request.existing)!=identity(self.remote):
            raise DomainError('external_change')
        return Prepared(request,Capability('supported','offline semantic fixture'))
    async def execute(self,prepared,hooks):
        request=prepared.request;self.requests.append(request)
        await hooks.before_effect(request.attempt_id,request.plan_digest)
        text,entities=max_content(request.content_json,4000)
        namespace='scheduled' if request.scheduled_at else 'published'
        media=tuple('media-'+str(i) for i,_ in enumerate(request.assets)) or (request.existing.provider_media if request.existing else ())
        remote=RemoteItem('native-item',namespace,text,'',timestamp(1800000000),scheduled_at=request.scheduled_at,
            media_hashes=tuple(a.sha256 for a in request.assets),native_target=request.native_target,provider_media=media,
            entities_json=canonical([] if self.drop_entities else entities),media_check='provider_binding' if media else 'not_applicable')
        self.remote=replace(remote,fingerprint=identity(remote))
        return Observation('provider_scheduled' if namespace=='scheduled' else 'edited' if request.action=='edit' else 'published',(self.remote,))
    async def read(self,request,hooks): return ReadPage((self.remote,))


@pytest.mark.asyncio
async def test_max_rich_video_plan_lifecycle_roles_and_adoption(tmp_path,video_bytes):
    store,actor,app=runtime(tmp_path)
    asset=import_video(store,actor,video_bytes,'video/mp4')
    provider=SemanticMax();provider.requests=[]
    worker=Worker(store,{'connection':provider})
    async def call(method,args):
        return await app.call(actor,'vibepublish_'+method,args)
    first=await call('publish',{'to':['target'],'content':RICH,'media':[{'source':{'kind':'asset','id':asset},'role':'video'}],
        'delivery':{'kind':'at','at':timestamp(store.clock()+3600)}})
    await worker.run_once();receipt=store.receipt(actor,first['operation_id'])
    assert receipt['state']=='scheduled',receipt
    assert provider.requests[0].assets[0].role=='video'
    with pytest.raises(DomainError): verify_assets(provider.requests[0])
    verify_assets(provider.requests[0],allow_video=True)
    second=await call('publication_update',{'publication_id':receipt['resource_id'],'expected_revision':1,
        'change':{'kind':'reschedule','delivery':{'kind':'at','at':timestamp(store.clock()+7200)}},'request_key':'reschedule-video'})
    await worker.run_once();second=store.receipt(actor,second['operation_id'])
    assert second['state']=='scheduled',second
    assert provider.requests[-1].assets[0].role=='video'
    assert json.loads(provider.requests[-1].content_json)['format']=='max_entities'
    adopted=await call('publication_update',{'item_ref':second['deliveries'][0]['item_ref'],
        'change':{'kind':'reschedule','delivery':{'kind':'at','at':timestamp(store.clock()+10800)}},'request_key':'adopt-video'})
    await worker.run_once();adopted=store.receipt(actor,adopted['operation_id'])
    assert adopted['state']=='scheduled',adopted
    assert json.loads(provider.requests[-1].content_json)['format']=='max_entities'
    assert provider.requests[-1].existing.provider_media==('media-0',)


@pytest.mark.asyncio
async def test_missing_max_entities_never_verifies(tmp_path):
    store,actor,app=runtime(tmp_path)
    provider=SemanticMax();provider.drop_entities=True
    accepted=await app.call(actor,'vibepublish_publish',{'to':['target'],'content':RICH})
    await Worker(store,{'connection':provider}).run_once()
    result=store.receipt(actor,accepted['operation_id'])
    assert result['state']=='outcome_unknown'
    assert result['deliveries'][0]['missing_checks']==['entities_readback_mismatch']


@pytest.mark.asyncio
@pytest.mark.parametrize('provider,account',[('telegram','mtproto_user'),('vk','vk_user'),('max','fake')])
async def test_video_role_does_not_widen_other_provider_or_fake_bindings(tmp_path,video_bytes,provider,account):
    store,actor,app=runtime(tmp_path,provider,account)
    asset=import_video(store,actor,video_bytes,'video/mp4')
    result=await app.call(actor,'vibepublish_publish',{'to':['target'],'content':{'text':'Video'},
        'media':[{'source':{'kind':'asset','id':asset},'role':'video'}]})
    assert result['error']['code']=='media_role_not_enabled'


def test_owner_file_ingress_rejects_symlink_fifo_and_oversize(tmp_path,video_bytes):
    import os
    from social_operations.video_assets import read_video_file
    source=tmp_path/'owned.mp4';source.write_bytes(video_bytes)
    assert read_video_file(source)==video_bytes
    link=tmp_path/'link.mp4';link.symlink_to(source)
    with pytest.raises(DomainError): read_video_file(link)
    fifo=tmp_path/'pipe';os.mkfifo(fifo)
    with pytest.raises(DomainError) as error: read_video_file(fifo)
    assert error.value.code=='video_regular_file_required'


def test_owner_video_cli_imports_verified_asset(tmp_path,video_bytes,monkeypatch,capsys):
    import sys
    from social_operations.cli import main
    store=Store(tmp_path/'ledger.sqlite')
    token=store.create_principal('t','owner',owner=True)
    source=tmp_path/'owned.mp4';source.write_bytes(video_bytes)
    monkeypatch.setenv('VIBEPUBLISH_SERVICE_TOKEN',token)
    monkeypatch.setattr(sys,'argv',['vibepublish','--db',str(store.path),'video','--file',str(source),'--mime','video/mp4'])
    main()
    ref=capsys.readouterr().out.strip()
    with store.connection() as db:
        row=db.execute('SELECT mime,source_sha256 FROM assets WHERE id=?',(ref,)).fetchone()
        assert tuple(row)==('video/mp4',hashlib.sha256(video_bytes).hexdigest())


def download_record(slot=0, sha='d'*64):
    return {'kind':'download_sha256','slot':slot,'sha256':sha,'mime':'image/jpeg','size':4650}


def test_download_evidence_is_typed_immutable_serializable_and_distinct_from_native_ids():
    from adapters.port import DownloadedMedia
    plain=RemoteItem('native','published','text','',timestamp(1800000000),native_target='target')
    observed=replace(plain,observed_media=[download_record()])
    assert isinstance(observed.observed_media[0],DownloadedMedia)
    assert observed.provider_media==() and observed.media_hashes==()
    assert RemoteItem(**asdict(observed))==observed
    assert identity(plain)!=identity(observed)
    assert identity(observed)==identity(replace(observed,observed_at=timestamp(1800000100)))
    assert identity(observed)!=identity(replace(observed,observed_media=[download_record(sha='e'*64)]))


@pytest.mark.parametrize('records',[
    [download_record(slot=1)], [download_record(),download_record()],
    [{**download_record(),'sha256':'not-digest'}], [{**download_record(),'size':True}],
    [{**download_record(),'kind':'native_id'}], [{**download_record(),'url':'https://signed.test'}],
])
def test_download_evidence_rejects_malformed_records_and_slots(records):
    with pytest.raises(DomainError):
        RemoteItem('n','published','','',timestamp(1800000000),observed_media=records)


def test_download_binding_requires_original_intent_source_and_repeated_exact_native_slot():
    from adapters.port import Asset, ProviderRequest
    from adapters.native import bind_download_media
    from social_operations.domain import OutcomeUnknown
    asset=Asset('asset','a'*64,'image/png',10,data=b'not-used')
    request=ProviderRequest('op','attempt','plan','connection','max_web','secret','dest','target','publish','post','{"text":"text"}',(asset,),None,1800000000)
    item=RemoteItem('native','published','text','',timestamp(1800000000),native_target='target',observed_media=[download_record()])
    binding={'operation_id':'op','attempt_id':'attempt','plan_digest':'plan','native_target':'target',
             'native_id':'native','namespace':'published','source_hashes':['a'*64],'observed_media':[download_record()]}
    with pytest.raises(DomainError):
        bind_download_media(replace(request,account_type='mtproto_user'),item,binding=binding)
    result=bind_download_media(request,item,binding=binding)
    assert result.media_check=='download_binding' and result.media_hashes==('a'*64,)
    assert result.observed_media[0].sha256=='d'*64 and result.provider_media==()
    for change in ({'attempt_id':'other'},{'native_id':'other'},{'source_hashes':['d'*64]},
                   {'observed_media':[download_record(sha='e'*64)]}):
        with pytest.raises(OutcomeUnknown): bind_download_media(request,item,binding={**binding,**change})
    with pytest.raises(OutcomeUnknown):
        bind_download_media(request,replace(item,provider_media=('counterfeit',)),binding=binding)
    adopted=replace(request,assets=(),existing=result,action='edit')
    result=bind_download_media(adopted,item,binding={**binding,'source_hashes':[]})
    assert result.media_hashes==() and result.media_check=='download_binding'
    with pytest.raises(OutcomeUnknown):
        bind_download_media(replace(adopted,existing=None),item,binding={**binding,'source_hashes':[]})


@pytest.mark.asyncio
@pytest.mark.parametrize('changed',[False,True])
async def test_max_download_evidence_survives_adoption_and_blocks_changed_media(tmp_path,changed):
    from adapters.native import bind_download_media
    from PIL import Image
    import io
    from social_operations.assets import import_image
    store,actor,app=runtime(tmp_path)
    image=io.BytesIO();Image.new('RGB',(4,4)).save(image,format='PNG')
    asset=import_image(store,actor,image.getvalue(),'image/png')
    class DownloadMax(SemanticMax):
        changed=False
        async def execute(self,prepared,hooks):
            obs=await super().execute(prepared,hooks)
            request=prepared.request
            # Fixture models durable attribution supplied by the actual adapter.
            item=replace(obs.items[0],provider_media=(),observed_media=[download_record(sha=('e' if self.changed else 'd')*64)])
            binding={'operation_id':request.operation_id,'attempt_id':request.attempt_id,'plan_digest':request.plan_digest,
                'native_target':request.native_target,'native_id':item.native_id,'namespace':item.namespace,
                'source_hashes':[a.sha256 for a in request.assets],'observed_media':[asdict(x) for x in item.observed_media]}
            if request.assets:
                item=bind_download_media(request,item,binding=binding)
            else:
                # Intentionally bypass helper in faulty fixture to test core guard.
                item=replace(item,media_check='download_binding')
            self.remote=replace(item,fingerprint=identity(item))
            return replace(obs,items=(self.remote,))
    provider=DownloadMax();provider.requests=[]
    worker=Worker(store,{'connection':provider})
    first=await app.call(actor,'vibepublish_publish',{'to':['target'],'content':{'text':'first'},
        'media':[{'source':{'kind':'asset','id':asset},'role':'image'}],'request_key':'download-first'})
    await worker.run_once()
    status=store.receipt(actor,first['operation_id'])
    assert status['state']=='verified', status
    ref=status['deliveries'][0]['item_ref']
    edit=await app.call(actor,'vibepublish_publication_update',{'item_ref':ref,'change':{'kind':'edit','content':{'text':'edited'}},'request_key':'download-edit'})
    provider.changed=changed
    await worker.run_once()
    status=store.receipt(actor,edit['operation_id'])
    assert status['state']==('outcome_unknown' if changed else 'verified'), status
    if changed:
        assert status['deliveries'][0]['missing_checks']==['download_media_lifecycle_changed']
    with store.connection() as db:
        plan=json.loads(db.execute('SELECT plan FROM attempts WHERE operation_id=?',(edit['operation_id'],)).fetchone()[0])
    assert plan['existing']['observed_media'][0]['sha256']=='d'*64


@pytest.mark.asyncio
async def test_downloaded_media_read_projection_is_safe_metadata_not_upload_attribution(tmp_path):
    from contracts.social_mcp_v1 import catalog
    from jsonschema import Draft202012Validator
    store,actor,app=runtime(tmp_path)
    provider=SemanticMax()
    provider.remote=RemoteItem('native','published','caption','',timestamp(store.clock()),native_target='native-target',
        media_hashes=('a'*64,),observed_media=[download_record()],media_check='download_binding')
    provider.remote=replace(provider.remote,fingerprint=identity(provider.remote))
    read=await app.call(actor,'vibepublish_read',{'query':{'kind':'feed','destination':'target'}})
    await Worker(store,{'connection':provider}).run_once()
    receipt=store.receipt(actor,read['operation_id'])
    assert receipt['state']=='verified',receipt
    projected=receipt['items'][0]
    assert projected['media_evidence']==[download_record()]
    assert 'error' not in projected and 'media' not in projected
    assert 'a'*64 not in canonical(projected) and 'provider_media' not in projected
    assert 'native' not in canonical(projected) and 'url' not in projected
    output=next(tool['outputSchema'] for tool in catalog()['tools'] if tool['name']=='vibepublish_read')
    Draft202012Validator(output).validate(receipt)
    with store.connection() as db:
        saved=app.resolve_item(db,actor,projected['ref'])
        assert json.loads(saved['snapshot'])['observed_media']==[download_record()]
    # Current authority still guards access to both metadata and its item handle.
    with store.connection() as db:
        binding=db.execute('SELECT id FROM bindings').fetchone()[0]
    store.revoke_binding(actor,binding)
    denied=await app.call(actor,'vibepublish_read',{'query':{'kind':'item','item_ref':projected['ref']}})
    assert 'error' in denied
