import hashlib
import io

import pytest
from PIL import Image
from starlette.testclient import TestClient
from social_operations.server import create_app
from social_operations.storage import Store
from social_operations.service import Application


def png(color='blue'):
    out = io.BytesIO()
    Image.new('RGB', (32, 40), color).save(out, format='PNG')
    return out.getvalue()


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path/'db.sqlite')
    token = store.create_principal('tenant', 'owner', scopes={'publish', 'status'})
    with TestClient(create_app(store)) as client:
        client.headers['authorization'] = 'Bearer '+token
        yield store, token, client


def upload(client, data=None, key='image-1', mime='image/png'):
    return client.post('/v1/assets', content=png() if data is None else data,
                       headers={'idempotency-key': key, 'content-type': mime})


def test_upload_read_replay_restart_and_status(env):
    store, token, client = env
    result = upload(client)
    assert result.status_code == 200, result.text
    result = result.json()
    assert result['source_sha256'] == hashlib.sha256(png()).hexdigest()
    assert result['mime'] == 'image/png' and (result['width'], result['height']) == (32, 40)
    read = client.get('/v1/assets/'+result['asset_id'])
    assert hashlib.sha256(read.content).hexdigest() == result['sha256']
    assert upload(client).json() == result
    with TestClient(create_app(Store(store.path))) as restarted:
        restarted.headers['authorization'] = 'Bearer '+token
        assert upload(restarted).json() == result
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0] == 1
        op = db.execute('SELECT id FROM operations').fetchone()[0]
    status = client.get('/v1/operations/'+op)
    assert status.status_code == 200 and status.json()['receipts'][0]['state'] == 'verified', status.text
    assert upload(client, png('red')).status_code == 409


def test_authority_isolation_and_quota(env):
    store, token, client = env
    result = upload(client).json()
    for scopes in [{'visual'}, {'publish'}]:
        other = store.create_principal('tenant', 'other-'+next(iter(scopes)), scopes=scopes)
        client.headers['authorization'] = 'Bearer '+other
        assert client.get('/v1/assets/'+result['asset_id']).status_code == 404
        assert upload(client).status_code == 200
    denied = store.create_principal('tenant', 'denied', scopes={'status'})
    client.headers['authorization'] = 'Bearer '+denied
    assert upload(client).status_code == 403
    client.headers['authorization'] = 'Bearer '+token
    with store.tx() as db:
        db.execute('UPDATE tenants SET storage_limit=1')
    assert upload(client, key='quota').status_code == 422
    assert upload(client).json() == result
    with store.tx() as db:
        db.execute("UPDATE principals SET active=0 WHERE id='owner'")
    assert upload(client).status_code == 401
    client.headers.pop('authorization')
    assert upload(client).status_code == 401


@pytest.mark.parametrize('data,mime', [(b'', 'image/png'), (b'bad', 'image/png'), (png(), 'image/jpeg'), (png(), 'text/plain')])
def test_invalid_images(env, data, mime):
    store, _, client = env
    assert upload(client, data, mime=mime).status_code == 422
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 0


def test_route_specific_limits_and_key(env):
    _, _, client = env
    assert upload(client, b'x'*(20*1024*1024+1)).status_code == 413
    # Valid PNG with trailing padding exceeds JSON limit but remains bounded image.
    assert upload(client, png()+b'\0'*(600*1024)).status_code == 200
    assert client.post('/v1/reads', content=b' '*(513*1024)).status_code == 413
    assert client.post('/mcp/', content=b' '*(513*1024)).status_code == 413
    assert client.post('/v1/assets', content=png(), headers={'content-type':'image/png'}).status_code == 422


def test_revocation_between_decode_and_commit(env, monkeypatch):
    from social_operations import asset_ingress
    store, _, client = env
    original = asset_ingress.verify_image
    def revoke(data, mime):
        verified = original(data, mime)
        with store.tx() as db:
            db.execute("UPDATE principals SET epoch=epoch+1 WHERE id='owner'")
        return verified
    monkeypatch.setattr(asset_ingress, 'verify_image', revoke)
    assert upload(client).status_code == 403
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM request_keys').fetchone()[0] == 0


@pytest.mark.parametrize('fmt,mime', [('JPEG','image/jpeg'), ('WEBP','image/webp')])
def test_supported_original_formats(env, fmt, mime):
    store, _, client = env
    out = io.BytesIO()
    Image.new('RGB',(25,30),'green').save(out,format=fmt)
    data = out.getvalue()
    result = upload(client, data, mime=mime).json()
    assert result['source_sha256'] == hashlib.sha256(data).hexdigest()
    with store.connection() as db:
        originals = db.execute('SELECT bytes FROM assets WHERE mime=?',(mime,)).fetchall()
        assert len(originals) == 1 and originals[0][0] == data
    assert client.get('/v1/assets/'+result['asset_id']).headers['content-type'] == 'image/png'


@pytest.mark.asyncio
async def test_total_read_deadline(env, monkeypatch):
    from social_operations import server
    store, token, _ = env
    real_timeout = server.asyncio.timeout
    monkeypatch.setattr(server.asyncio, 'timeout', lambda seconds: real_timeout(0.001))
    messages = []
    async def receive():
        await server.asyncio.sleep(0.03)
        return {'type':'http.request','body':png()}
    async def send(message):
        messages.append(message)
    await create_app(store)({'type':'http','method':'POST','path':'/v1/assets',
        'headers':[(b'host',b'testserver'),(b'authorization',('Bearer '+token).encode())]}, receive, send)
    assert messages[0]['status'] == 408
