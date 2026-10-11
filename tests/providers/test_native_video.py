import copy
import hashlib
from dataclasses import replace

import pytest

from adapters.port import Asset
from adapters.telegram import TelegramAdapter
from adapters.vk import VKAdapter
from adapters.vk_transport import VKHTTPTransport, VKToken
from social_operations.domain import OutcomeUnknown, canonical
from .test_native_adapters import NOW, Journal, request
from .test_max_content_video import video_bytes
from .scripted import ScriptedTL, TelegramClient, VKTransport, obj


def video_asset(data):
    return Asset('asset_video', hashlib.sha256(data).hexdigest(), 'video/mp4', len(data), role='video', data=data)


class VideoVK(VKTransport):
    def __init__(self):
        super().__init__();self.allocations=0;self.pending=False;self.bad_upload=False;self.story_video=False

    async def upload_video(self, url, data, mime):
        assert self.allocations == 1 and mime == 'video/mp4'
        self.uploads.append(data)
        return {'video_id': 501 if self.bad_upload else 500, 'owner_id': -101}

    async def upload_story_video(self, url, data, mime):
        assert mime == 'video/mp4';self.uploads.append(data)
        return 'fixture-story-upload-result'

    async def invoke(self, *, role, method, params):
        if method == 'video.save':
            self.allocations+=1;self.calls.append((method,role,copy.deepcopy(params)))
            assert params == {'group_id':101,'name':'Publication video','wallpost':0}
            return {'owner_id':-101,'video_id':500,'upload_url':'https://pu.vk.com/upload?fixture=1'}
        if method == 'video.get':
            return {'items':[{'owner_id':-101,'id':500,'duration':1,'processing':int(self.pending)}]}
        if method == 'stories.getVideoUploadServer':
            self.story_video=True;method='stories.getPhotoUploadServer'
        original = None
        if method == 'wall.post' and params.get('attachments','').startswith('video'):
            original=params['attachments'];params={**params,'attachments':original.replace('video','photo',1)}
        result=await super().invoke(role=role,method=method,params=params)
        if original:
            for p in self.posts.values():
                p['attachments']=[{'type':'video','video':a['photo']} for a in p['attachments']]
        if method == 'stories.save' and self.story_video:
            for story in self.stories.values():
                story['video']=story.pop('photo');story['type']='video'
            result={'items':copy.deepcopy(list(self.stories.values())),'count':len(self.stories)}
        return result


class VideoTG(TelegramClient):
    async def __call__(self, req):
        if type(req).__name__ == 'UploadMediaRequest':
            assert type(req.media).__name__ == 'InputMediaUploadedDocument'
            self.video_attributes=req.media.attributes
            assert req.media.force_file is False and req.media.mime_type == 'video/mp4'
            return obj('MessageMediaDocument',document=obj('Document',id=500,access_hash=123,file_reference=b'fixture'))
        result=await super().__call__(req)
        if type(req).__name__ == 'SendMediaRequest':
            for m in list(self.messages.values())+list(self.scheduled.values()):
                m.media=obj('MessageMediaDocument',document=obj('Document',id=500,mime_type='video/mp4'))
        return result


@pytest.mark.asyncio
async def test_telegram_native_video_attributes_and_exact_binding(video_bytes):
    client=VideoTG();journal=Journal()
    adapter=TelegramAdapter(client,connection_id='connection',tl=ScriptedTL(),clock=lambda:NOW)
    r=request('telegram',assets=(video_asset(video_bytes),))
    result=await adapter.execute(await adapter.prepare(r,journal.hooks),journal.hooks)
    assert result.items[0].provider_media==('document:500',)
    attr=next(a for a in client.video_attributes if type(a).__name__=='DocumentAttributeVideo')
    assert (attr.w,attr.h)==(32,24) and attr.duration>0 and attr.supports_streaming
    assert len(journal.markers)==1 and client.effects==1


@pytest.mark.asyncio
async def test_vk_video_allocation_inside_dispatch_and_exact_wall_binding(video_bytes):
    transport=VideoVK();journal=Journal()
    adapter=VKAdapter(transport,connection_id='connection',clock=lambda:NOW)
    r=request('vk',assets=(video_asset(video_bytes),))
    result=await adapter.execute(await adapter.prepare(r,journal.hooks),journal.hooks)
    assert result.items[0].provider_media==('video-101_500',)
    assert len(journal.markers)==1 and transport.allocations==1 and transport.effects==1
    assert any(stage=='vk_video_allocated' for stage,_ in journal.checkpoints)
    assert (await adapter.reconcile(r,journal.checkpoint_json,journal.hooks)).items[0].native_id==result.items[0].native_id
    assert transport.allocations==1 and transport.effects==1


@pytest.mark.asyncio
async def test_vk_uncertain_video_upload_never_creates_wall_or_reuploads(video_bytes):
    transport=VideoVK();transport.bad_upload=True;journal=Journal()
    adapter=VKAdapter(transport,connection_id='connection',clock=lambda:NOW)
    r=request('vk',assets=(video_asset(video_bytes),))
    with pytest.raises(OutcomeUnknown):
        await adapter.execute(await adapter.prepare(r,journal.hooks),journal.hooks)
    assert len(journal.markers)==1 and transport.allocations==1 and transport.effects==0
    with pytest.raises(OutcomeUnknown):
        await adapter.reconcile(r,journal.checkpoint_json,journal.hooks)
    assert transport.allocations==1 and len(transport.uploads)==1


@pytest.mark.asyncio
async def test_vk_video_story_uses_video_identity_and_readback(video_bytes):
    transport=VideoVK();journal=Journal()
    adapter=VKAdapter(transport,connection_id='connection',clock=lambda:NOW)
    r=request('vk',surface='story',content_json=canonical({'text':''}),assets=(video_asset(video_bytes),))
    result=await adapter.execute(await adapter.prepare(r,journal.hooks),journal.hooks)
    assert result.items[0].namespace=='story' and result.items[0].provider_media[0].startswith('video')
    assert transport.story_video and transport.effects==1 and len(journal.markers)==1
    await adapter.reconcile(r,journal.checkpoint_json,journal.hooks)
    assert transport.effects==1


@pytest.mark.asyncio
async def test_transport_video_multipart_fields_and_response(video_bytes):
    transport=VKHTTPTransport(tokens={})
    async def post(url, form):
        assert form._fields[0][0]['name']=='video_file'
        return {'response':{'upload_result':'opaque'}} if 'story' in url else {'video_id':500}
    transport._post=post
    assert await transport.upload_video('https://pu.vk.com/upload',video_bytes,'video/mp4')=={'video_id':500}
    assert await transport.upload_story_video('https://pu.vk.com/story',video_bytes,'video/mp4')=='opaque'
    group=VKHTTPTransport(tokens={'media':VKToken('fixture',kind='group',group_id=101)})
    assert not group.permits('media','video.save',group_id=101)

@pytest.mark.asyncio
async def test_mp4_workspace_ingress_is_atomic_replayable_and_catalog_valid(tmp_path,video_bytes):
    import base64
    from social_operations.service import Application
    from social_operations.storage import Store
    store=Store(tmp_path/'db.sqlite')
    actor=store.authenticate(store.create_principal('t','owner',owner=True))
    app=Application(store)
    async def call(kind,key,**fields):
        result=await app.call(actor,'vibepublish_visual',{'command':{'kind':kind,**fields},'request_key':key})
        assert 'error' not in result,result
        return result
    start=await call('import_begin','begin-video',source_sha256=hashlib.sha256(video_bytes).hexdigest(),mime='video/mp4',size_bytes=len(video_bytes))
    ident=start['workspace_upload']['upload_id']
    await call('import_chunk','video-chunk',upload_id=ident,offset=0,data_base64=base64.b64encode(video_bytes).decode())
    result=await call('import_finish','video-finish',upload_id=ident)
    assert result['workspace_upload']['state']=='completed' and result['workspace_upload']['mime']=='video/mp4'
    assert (await call('import_finish','video-finish',upload_id=ident))['resource_id']==result['resource_id']
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0]==2
        assert db.execute('SELECT length(bytes) FROM workspace_uploads WHERE id=?',(ident,)).fetchone()[0]==0
    for provider,account,target in [('vk','vk_user','-101'),('telegram','mtproto_user','-1000000000101')]:
        store.add_connection(actor,provider,provider,account_type=account)
        store.bind(actor,'owner',provider,provider,target)
        preview=await app.call(actor,'vibepublish_publish',{'to':[provider],'content':{'text':'Approved video'},'mode':'preview','media':[{'source':{'kind':'asset','id':result['resource_id']},'role':'video'}]})
        assert 'error' not in preview,preview


def test_portrait_rotation_metadata_uses_display_dimensions(monkeypatch,tmp_path):
    import json
    from social_operations.video_assets import _probe
    raw={'streams':[{'codec_type':'video','codec_name':'h264','width':1280,'height':720,'nb_read_packets':'10','side_data_list':[{'rotation':-90}]}],'format':{'duration':'33.513'}}
    monkeypatch.setattr('social_operations.video_assets._run',lambda *a,**k:json.dumps(raw).encode())
    assert _probe('ffprobe',tmp_path/'unused')[:3]==(720,1280,33.513)

@pytest.mark.asyncio
async def test_video_allocation_requires_dispatch_authority(video_bytes):
    from social_operations.domain import DomainError
    transport=VideoVK();journal=Journal();journal.fail_before=True
    adapter=VKAdapter(transport,connection_id='connection',clock=lambda:NOW)
    r=request('vk',assets=(video_asset(video_bytes),))
    with pytest.raises(DomainError):
        await adapter.execute(await adapter.prepare(r,journal.hooks),journal.hooks)
    assert transport.allocations==0 and transport.effects==0


@pytest.mark.asyncio
@pytest.mark.parametrize('fault',['processing','duration'])
async def test_video_processing_or_changed_duration_cannot_publish_wall(video_bytes,monkeypatch,fault):
    transport=VideoVK();journal=Journal()
    original=transport.invoke
    async def invoke(**kw):
        result=await original(**kw)
        if kw['method']=='video.get':
            result['items'][0].update(processing=int(fault=='processing'),duration=100 if fault=='duration' else 1)
        return result
    async def no_wait(_):pass
    monkeypatch.setattr('adapters.vk.asyncio.sleep',no_wait)
    transport.invoke=invoke
    adapter=VKAdapter(transport,connection_id='connection',clock=lambda:NOW)
    r=request('vk',assets=(video_asset(video_bytes),))
    with pytest.raises(OutcomeUnknown):
        await adapter.execute(await adapter.prepare(r,journal.hooks),journal.hooks)
    assert transport.allocations==1 and transport.effects==0 and len(journal.markers)==1


@pytest.mark.asyncio
async def test_story_without_native_video_identity_is_not_verified(video_bytes):
    transport=VideoVK();journal=Journal();original=transport.invoke
    async def invoke(**kw):
        result=await original(**kw)
        if kw['method'] in {'stories.save','stories.getById'}:
            for row in result['items']:row.pop('video',None)
        return result
    transport.invoke=invoke
    adapter=VKAdapter(transport,connection_id='connection',clock=lambda:NOW)
    r=request('vk',surface='story',content_json=canonical({'text':''}),assets=(video_asset(video_bytes),))
    with pytest.raises(OutcomeUnknown):
        await adapter.execute(await adapter.prepare(r,journal.hooks),journal.hooks)
    assert transport.effects==1
