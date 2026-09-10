import asyncio
import json
import socket

import pytest
from jsonschema import Draft202012Validator
from mcp.types import Tool
from social_operations import chat_file_ingress as ingress
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.domain import DomainError
from contracts.social_mcp_v1 import catalog
from tests.visuals.test_asset_ingress import png


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = Store(tmp_path/'db.sqlite')
    token = store.create_principal('tenant','owner')
    app = Application(store)
    calls = []
    async def download(url):
        calls.append(url)
        return png()
    monkeypatch.setattr(ingress,'download_file',download)
    return store, store.authenticate(token), app, calls


def args(**extra):
    return {'command':{'kind':'import'}, 'file':{'file_id':'attachment-1',
            'download_url':'https://files.example/photo?secret=never-store', 'file_name':'private-name.png'},
            'request_key':'file-1', **extra}


@pytest.mark.asyncio
async def test_import_replay_scope_and_private_receipt(env):
    store, actor, app, calls = env
    result = await app.call(actor,'vibepublish_visual',args())
    assert result['state'] == 'verified', result
    assert app.read_asset(actor,result['resource_id'])[1] == 'image/png'
    # Expired / replaced signed URL is not fetched on same immutable file identity replay.
    replay = args(); replay['file']['download_url'] = 'https://files.example/expired'
    replayed = await Application(Store(store.path)).call(actor,'vibepublish_visual',replay)
    assert replayed['operation_id'] == result['operation_id'] and replayed['resource_id'] == result['resource_id']
    assert len(calls) == 1
    conflict = args(); conflict['file']['file_id'] = 'another-file'
    assert (await app.call(actor,'vibepublish_visual',conflict))['error']['code'] == 'idempotency_conflict'
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 2
        text = '\n'.join(str(tuple(row)) for table in ['operations','request_keys','events'] for row in db.execute('SELECT * FROM '+table))
        assert 'never-store' not in text and 'private-name' not in text and 'attachment-1' not in text
    other = store.authenticate(store.create_principal('tenant','other',scopes={'publish'}))
    tool = next(t for t in app.tools(other) if t['name']=='vibepublish_visual')
    assert tool['_meta']['openai/fileParams']==['file']
    assert Tool(**tool).meta == tool['_meta']
    assert tool['inputSchema']['properties']['command']['properties']['kind']['const']=='import'
    assert (await app.call(other,'vibepublish_visual',{'command':{'kind':'generate','prompt':'sea'}}))['error']['code']=='invalid_input'
    with pytest.raises(DomainError): app.read_asset(other,result['resource_id'])
    assert (await app.call(other,'vibepublish_visual',args()))['state']=='verified'


@pytest.mark.parametrize('change', ['missing_file','missing_key','extra_path','file_on_generate'])
@pytest.mark.asyncio
async def test_contract_rejects_invalid_file_shapes(env, change):
    _, actor, app, calls = env
    payload=args()
    if change=='missing_file': payload.pop('file')
    if change=='missing_key': payload.pop('request_key')
    if change=='extra_path': payload['file']['path']='/etc/passwd'
    if change=='file_on_generate': payload['command']={'kind':'generate','prompt':'sea'}
    assert (await app.call(actor,'vibepublish_visual',payload))['error']['code']=='invalid_input'
    assert not calls


@pytest.mark.asyncio
async def test_mime_and_revocation_prevent_admission(env, monkeypatch):
    store, actor, app, _ = env
    payload=args(); payload['file']['mime_type']='image/jpeg'
    assert (await app.call(actor,'vibepublish_visual',payload))['error']['code']=='asset_format_or_dimensions'
    async def revoked(url):
        with store.tx() as db: db.execute("UPDATE principals SET epoch=epoch+1 WHERE id='owner'")
        return png()
    monkeypatch.setattr(ingress,'download_file',revoked)
    assert (await app.call(actor,'vibepublish_visual',args()))['error']['code']=='access_revoked'
    with store.connection() as db: assert db.execute('SELECT count(*) FROM assets').fetchone()[0]==0


@pytest.mark.parametrize('url', ['http://files.example/a','https://u:p@files.example/a','https://files.example:444/a',
    'https://127.0.0.1/a','https://[::1]/a','file:///etc/passwd','https://files.example/a#frag',
    'https://files.example/a\r\nx:x','https://files.example\\@private/a','https://bad..example/a'])
def test_invalid_url(url):
    with pytest.raises(DomainError,match='file url invalid'): ingress.validated_host(url)


@pytest.mark.asyncio
@pytest.mark.parametrize('address',['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:8.8.8.8','64:ff9b::808:808','2002:0808:0808::'])
async def test_nonpublic_and_translation_dns_rejected(monkeypatch,address):
    async def dns(*a,**k): return [(socket.AF_INET,socket.SOCK_STREAM,0,'',(address,443))]
    monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',dns)
    with pytest.raises(DomainError,match='file nonpublic address'): await ingress.pinned_addresses('files.example')


@pytest.mark.asyncio
async def test_pinning_dns_all_addresses_checked(monkeypatch):
    async def dns(*a,**k): return [(socket.AF_INET,socket.SOCK_STREAM,0,'',(ip,443)) for ip in ['8.8.8.8','10.0.0.1']]
    monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',dns)
    with pytest.raises(DomainError): await ingress.pinned_addresses('files.example')


@pytest.mark.asyncio
async def test_download_deadline_includes_dns(monkeypatch):
    async def dns(host): await asyncio.sleep(.02)
    monkeypatch.setattr(ingress,'pinned_addresses',dns)
    monkeypatch.setattr(ingress,'DOWNLOAD_SECONDS',.001)
    with pytest.raises(DomainError,match='file download timeout'): await ingress.download_file('https://files.example/a')


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario,code', [('ok',None),('redirect','file_download_failed'),
    ('encoded','file_encoding_unsupported'),('declared_large','asset_size_limit'),
    ('stream_large','asset_size_limit'),('exception','file_download_failed')])
async def test_download_transport_policy(monkeypatch, scenario, code):
    captured = {}
    class Context:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    class Content:
        async def iter_chunked(self,n):
            yield b'x'*101 if scenario=='stream_large' else png()
    class Response(Context):
        status = 302 if scenario=='redirect' else 200
        headers = {'Content-Encoding':'gzip'} if scenario=='encoded' else {}
        content_length = 101 if scenario=='declared_large' else None
        content = Content()
    class Session(Context):
        def __init__(self,**kwargs): captured['session']=kwargs
        def get(self,url,**kwargs):
            captured['get'] = kwargs
            if scenario=='exception': raise OSError('secret URL must not leak')
            return Response()
    async def dns(host): return ('8.8.8.8',)
    def connector(**kwargs): captured['connector']=kwargs; return object()
    monkeypatch.setattr(ingress,'pinned_addresses',dns)
    monkeypatch.setattr(ingress.aiohttp,'ClientSession',Session)
    monkeypatch.setattr(ingress.aiohttp,'TCPConnector',connector)
    if scenario in {'stream_large','declared_large'}: monkeypatch.setattr(ingress,'MAX_UPLOAD_BYTES',100)
    if code:
        with pytest.raises(DomainError) as exc: await ingress.download_file('https://files.example/a?secret=yes')
        assert exc.value.code==code and 'secret' not in str(exc.value)
    else:
        assert await ingress.download_file('https://files.example/a?secret=yes')==png()
    assert captured['get']['allow_redirects'] is False
    assert captured['session']['trust_env'] is False and captured['session']['auto_decompress'] is False
    assert captured['session']['headers']=={'Accept-Encoding':'identity'}
    assert captured['connector']['resolver'].addresses==('8.8.8.8',)
    assert captured['connector']['use_dns_cache'] is False
    assert 'ssl' not in captured['connector']  # Default certificate/hostname validation retained.


@pytest.mark.asyncio
async def test_bounded_import_admission(env, monkeypatch):
    _, actor, app, _ = env
    entered=asyncio.Event(); finish=asyncio.Event()
    async def download(url):
        entered.set()
        await finish.wait()
        return png()
    monkeypatch.setattr(ingress,'download_file',download)
    pending=[asyncio.create_task(app.call(actor,'vibepublish_visual',args(request_key='key'+str(i)))) for i in range(2)]
    await entered.wait()
    await asyncio.sleep(0)
    assert (await app.call(actor,'vibepublish_visual',args(request_key='overflow')))['error']['code']=='asset_ingress_busy'
    finish.set()
    assert all(r['state']=='verified' for r in await asyncio.gather(*pending))


def test_real_mcp_projection_and_import(env):
    from starlette.testclient import TestClient
    from social_operations.server import create_app
    store, _, _, calls = env
    token=store.create_principal('tenant','mcp-owner',owner=True)
    with TestClient(create_app(store)) as client:
        client.headers.update({'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'})
        def rpc(method,params):
            response=client.post('/mcp/',json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
            assert response.status_code==200,response.text
            return response.json()['result']
        rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'fixture','version':'1'}})
        listed=rpc('tools/list',{})['tools']
        assert len(listed)==8
        visual=next(t for t in listed if t['name']=='vibepublish_visual')
        assert visual['_meta']['openai/fileParams']==['file']
        result=rpc('tools/call',{'name':'vibepublish_visual','arguments':args()})
        assert not result.get('isError') and result['structuredContent']['state']=='verified'
        assert len(calls)==1


@pytest.mark.asyncio
async def test_concurrent_same_key_atomic_asset_admission(env):
    store, actor, app, _ = env
    first, second = await asyncio.gather(*(app.call(actor,'vibepublish_visual',args()) for _ in range(2)))
    assert first['resource_id']==second['resource_id'] and first['operation_id']==second['operation_id']
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM request_keys').fetchone()[0]==1


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['quota','malformed','denied'])
async def test_import_fail_closed(env, monkeypatch, mode):
    store, actor, app, calls = env
    if mode=='quota':
        with store.tx() as db: db.execute('UPDATE tenants SET storage_limit=1')
    elif mode=='malformed':
        async def download(url): return b'not an image'
        monkeypatch.setattr(ingress,'download_file',download)
    else:
        actor=store.authenticate(store.create_principal('tenant','denied',scopes={'status'}))
    result=await app.call(actor,'vibepublish_visual',args())
    assert result['error']['code']=={'quota':'storage_quota_exceeded','malformed':'invalid_image','denied':'access_denied'}[mode]
    with store.connection() as db: assert db.execute('SELECT count(*) FROM assets').fetchone()[0]==0
    if mode=='denied': assert not calls
