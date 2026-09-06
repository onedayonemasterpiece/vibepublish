"""OAuth protocol/consent/persistence/security, offline and without social effects."""
import base64
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from social_operations.oauth import CALLBACK, COOKIE, SCOPE, create_oauth_app
from social_operations.storage import Store

ISSUER = 'https://mcp.example.test'
RESOURCE = ISSUER+'/mcp/'


@pytest.fixture
def setup(tmp_path):
    tmp_path.chmod(0o700)
    store = Store(tmp_path/'ledger.sqlite')
    token = store.create_principal('tenant','owner',owner=True)
    app = create_oauth_app(store,auth_db=tmp_path/'oauth.sqlite',issuer=ISSUER)
    with TestClient(app,base_url=ISSUER,follow_redirects=False) as client:
        yield store,token,app,client


def register(client, **overrides):
    return client.post('/register',json={'redirect_uris':[CALLBACK],'token_endpoint_auth_method':'none',
        'grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':SCOPE,**overrides})


def begin(client, cid, **overrides):
    verifier = 'a'*43
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    response = client.get('/authorize',params={'client_id':cid,'response_type':'code','redirect_uri':CALLBACK,
        'scope':SCOPE,'state':'safe-state','resource':RESOURCE,'code_challenge':challenge,'code_challenge_method':'S256',**overrides})
    return response,verifier


def consent(client, token, response):
    page = client.get(response.headers['location'])
    assert page.status_code == 200, page.text
    fields = dict(re.findall(r'name="(request|csrf)" value="([^"]+)"',page.text))
    response = client.post('/oauth/login',data={**fields,'service_token':token,'consent':'yes'},headers={'Origin':ISSUER})
    assert response.status_code == 303,response.text
    values = parse_qs(urlsplit(response.headers['location']).query)
    assert values['iss']==[ISSUER] and values['state']==['safe-state']
    assert token not in response.headers['location'] and token not in page.text
    return values['code'][0]


def exchange(client,cid,code,verifier,**overrides):
    return client.post('/token',data={'client_id':cid,'grant_type':'authorization_code','code':code,
        'code_verifier':verifier,'redirect_uri':CALLBACK,'resource':RESOURCE,**overrides})


def grant(setup):
    store,token,app,client = setup
    registered = register(client)
    assert registered.status_code == 201, registered.text
    cid=registered.json()['client_id']
    response,verifier = begin(client,cid)
    assert response.status_code == 302,response.text
    code=consent(client,token,response)
    tokens=exchange(client,cid,code,verifier)
    assert tokens.status_code==200,tokens.text
    return cid,tokens.json(),code,verifier


def test_discovery_challenge(setup):
    _,_,_,client=setup
    r=client.get('/mcp/')
    assert r.status_code==401
    assert 'resource_metadata="'+ISSUER+'/.well-known/oauth-protected-resource/mcp/"' in r.headers['www-authenticate']
    meta=client.get('/.well-known/oauth-authorization-server').json()
    assert meta['issuer']==ISSUER and meta['token_endpoint_auth_methods_supported']==['none']
    assert meta['authorization_response_iss_parameter_supported'] is True
    for path in ('/.well-known/oauth-protected-resource/mcp/','/.well-known/oauth-protected-resource/mcp','/.well-known/oauth-protected-resource'):
        assert client.get(path).json()['resource']==RESOURCE
        assert client.get(path).json()['authorization_servers']==[ISSUER]


def test_complete_flow_restart_single_use_no_token_storage(setup):
    store,owner,app,client=setup
    cid,tokens,code,verifier=grant(setup)
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==200
    assert exchange(client,cid,code,verifier).status_code==400
    app2=create_oauth_app(store,auth_db=app.provider.path,issuer=ISSUER)
    with TestClient(app2,base_url=ISSUER) as c2:
        assert c2.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==200
    data=app.provider.path.read_bytes()
    for secret in (owner,code,tokens['access_token'],tokens['refresh_token']):
        assert secret.encode() not in data
    assert app.provider.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('overrides',[
    {'redirect_uris':['https://evil.test/callback']},
    {'redirect_uris':[CALLBACK+'?x=y']},
    {'redirect_uris':[CALLBACK,'https://evil.test/callback']},
    {'token_endpoint_auth_method':'client_secret_post'},
    {'scope':'admin'},
])
def test_dcr_rejects_unapproved_clients(setup,overrides):
    assert register(setup[3],**overrides).status_code==400


@pytest.mark.parametrize('overrides',[
    {'resource':ISSUER+'/other'}, {'code_challenge_method':'plain'}, {'code_challenge':'x'},
    {'state':''}, {'redirect_uri':'https://evil.test/'}, {'scope':'admin'},
])
def test_authorization_rejects_invalid_binding(setup,overrides):
    client=setup[3]
    cid=register(client).json()['client_id']
    response,_=begin(client,cid,**overrides)
    assert response.status_code in (302,400)
    if response.status_code==302:
        assert 'error=' in response.headers['location']
        assert response.headers['location'].startswith(CALLBACK)


@pytest.mark.parametrize('overrides',[
    {'resource':ISSUER+'/other'},{'resource':''},{'code_verifier':'b'*43},
    {'redirect_uri':CALLBACK+'?wrong=1'}, {'client_id':'wrong'},
])
def test_token_wrong_binding_no_consumption(setup,overrides):
    _,token,_,client=setup
    cid=register(client).json()['client_id']
    response,verifier=begin(client,cid)
    code=consent(client,token,response)
    assert exchange(client,cid,code,verifier,**overrides).status_code in (400,401)
    assert exchange(client,cid,code,verifier).status_code==200


def test_refresh_rotation_reuse_revokes_family(setup):
    _,_,_,client=setup
    cid,tokens,_,_=grant(setup)
    body={'client_id':cid,'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'resource':RESOURCE}
    new=client.post('/token',data=body)
    assert new.status_code==200,new.text
    new=new.json()
    assert new['refresh_token'] != tokens['refresh_token']
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+new['access_token']}).status_code==200
    assert client.post('/token',data=body).status_code==400
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+new['access_token']}).status_code==401
    assert client.post('/token',data={**body,'refresh_token':new['refresh_token']}).status_code==400


@pytest.mark.parametrize('sql',[
    'UPDATE principals SET epoch=epoch+1', 'UPDATE principals SET active=0','UPDATE tenants SET active=0',
    'UPDATE principals SET owner=0', "UPDATE principals SET scopes='[]'",
])
def test_authority_revocation_each_request_and_refresh(setup,sql):
    store,_,_,client=setup
    cid,tokens,_,_=grant(setup)
    with store.tx() as db:
        db.execute(sql)
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401
    assert client.post('/token',data={'client_id':cid,'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'resource':RESOURCE}).status_code==400


def test_consent_csrf_origin_and_owner(setup):
    store,token,_,client=setup
    cid=register(client).json()['client_id']
    response,_=begin(client,cid)
    page=client.get(response.headers['location'])
    fields=dict(re.findall(r'name="(request|csrf)" value="([^"]+)"',page.text))
    body={**fields,'service_token':token,'consent':'yes'}
    assert client.post('/oauth/login',data=body).status_code==403
    assert client.post('/oauth/login',data=body,headers={'Origin':'https://evil.test'}).status_code==403
    assert client.post('/oauth/login',data={**body,'csrf':'wrong'},headers={'Origin':ISSUER}).status_code==403
    partner=store.create_principal('tenant','partner',owner=False)
    assert client.post('/oauth/login',data={**body,'service_token':partner},headers={'Origin':ISSUER}).status_code==403
    assert client.post('/oauth/login',data=body,headers={'Origin':ISSUER}).status_code==303
    assert client.post('/oauth/login',data=body,headers={'Origin':ISSUER}).status_code==403


def test_scope_snapshot_no_escalation(setup):
    store,_,_,client=setup
    with store.tx() as db:
        db.execute('UPDATE principals SET scopes=?',(json.dumps(['bootstrap']),))
    _,tokens,_,_=grant(setup)
    with store.tx() as db:
        db.execute('UPDATE principals SET scopes=?',(json.dumps(['bootstrap','publish']),))
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401
    assert client.post('/mcp/',json={'jsonrpc':'2.0','id':1,'method':'tools/list'},headers={'Authorization':'Bearer '+tokens['access_token'],'Accept':'application/json, text/event-stream'}).status_code==401
    assert client.post('/v1/publications',json={'to':['forbidden'],'content':{'text':'must not dispatch'}},headers={'Authorization':'Bearer '+tokens['access_token'],'Idempotency-Key':'no-escalation'}).status_code==401
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0]==0


def test_expiry_revocation_and_wrong_token_kind(setup):
    _,_,app,client=setup
    cid,tokens,_,_=grant(setup)
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['refresh_token']}).status_code==401
    response=client.post('/revoke',data={'client_id':cid,'token':tokens['refresh_token'],'token_type_hint':'refresh_token'})
    assert response.status_code==200,response.text
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401


def test_request_security_and_limits(setup):
    _,_,_,client=setup
    assert client.get('/.well-known/oauth-authorization-server',headers={'Host':'evil.test'}).status_code==403
    assert client.get('/.well-known/oauth-authorization-server',headers={'Origin':ISSUER+':444'}).status_code==403
    assert client.get('/authorize?state=1&state=2').status_code==400
    assert client.get('/oauth/login?service_token=never-put-tokens-in-urls').status_code==400
    assert client.post('/register',content=b'x'*16385).status_code==413
    assert client.post('/register',json=[]).status_code==400
    assert client.post('/token',content='client_id=a&client_id=b',headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==400
    for _ in range(20):
        client.get('/.well-known/oauth-authorization-server')
    assert client.get('/.well-known/oauth-authorization-server').status_code==429


def test_public_clients_never_accept_secrets(setup):
    _,_,_,client=setup
    cid,tokens,_,_=grant(setup)
    body={'client_id':cid,'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'resource':RESOURCE}
    assert client.post('/token',data={**body,'client_secret':'wrong'}).status_code==401
    assert client.post('/revoke',data={'client_id':cid,'token':tokens['refresh_token'],'client_secret':'wrong'}).status_code==401
    assert client.post('/token',data=body,headers={'Authorization':'Basic abc'}).status_code==401
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==200


def test_expired_access_code_and_refresh_rejected(setup):
    _,token,app,client=setup
    cid,tokens,_,_=grant(setup)
    with app.provider.db() as db:
        db.execute('UPDATE credentials SET expires=0 WHERE kind="access"')
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401
    response,verifier=begin(client,cid)
    code=consent(client,token,response)
    with app.provider.db() as db:
        db.execute('UPDATE credentials SET expires=0 WHERE kind="code"')
    assert exchange(client,cid,code,verifier).status_code==400
    with app.provider.db() as db:
        db.execute('UPDATE credentials SET expires=0 WHERE kind="refresh"')
    assert client.post('/token',data={'client_id':cid,'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'resource':RESOURCE}).status_code==400


def test_cross_client_code_and_refresh_rejected(setup):
    _,token,_,client=setup
    cid,tokens,_,_=grant(setup)
    other=register(client).json()['client_id']
    assert client.post('/token',data={'client_id':other,'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'resource':RESOURCE}).status_code==400
    # Wrong client's probing cannot revoke the actual grant.
    assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==200
    response,verifier=begin(client,cid)
    code=consent(client,token,response)
    assert exchange(client,other,code,verifier).status_code==400
    assert exchange(client,cid,code,verifier).status_code==200


def test_concurrent_code_exchange_one_winner(setup):
    import asyncio
    _,token,app,client=setup
    cid=register(client).json()['client_id']
    response,verifier=begin(client,cid)
    code=consent(client,token,response)
    async def race():
        oauth_client=await app.provider.get_client(cid)
        loaded=await app.provider.load_authorization_code(oauth_client,code)
        return await asyncio.gather(*(app.provider.exchange_authorization_code(oauth_client,loaded) for _ in range(2)),return_exceptions=True)
    from mcp.shared.auth import OAuthToken
    assert sum(isinstance(result,OAuthToken) for result in asyncio.run(race()))==1


def test_grant_bound_to_static_resource_after_restart(setup):
    store,_,app,_=setup
    _,tokens,_,_=grant(setup)
    replacement=create_oauth_app(store,auth_db=app.provider.path,issuer='https://other.example.test')
    with TestClient(replacement,base_url='https://other.example.test') as client:
        assert client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401


def test_actual_mcp_tools_oauth_descriptor(setup):
    _,_,_,client=setup
    _,tokens,_,_=grant(setup)
    headers={'Authorization':'Bearer '+tokens['access_token'],'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'}
    response=client.post('/mcp/',json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'oauth-offline-test','version':'1'}}},headers=headers)
    assert response.status_code==200,response.text
    response=client.post('/mcp/',json={'jsonrpc':'2.0','id':2,'method':'tools/list'},headers=headers)
    assert response.status_code==200,response.text
    tools=response.json()['result']['tools']
    assert len(tools)==8
    for tool in tools:
        assert tool['securitySchemes']==[{'type':'oauth2','scopes':[SCOPE]}]
        assert tool['_meta']['securitySchemes']==tool['securitySchemes']
    response=client.post('/mcp/',json={'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'vibepublish_get_started','arguments':{'section':'all'}}},headers=headers)
    assert response.status_code==200 and 'skill_sha256' in response.json()['result']['structuredContent']
