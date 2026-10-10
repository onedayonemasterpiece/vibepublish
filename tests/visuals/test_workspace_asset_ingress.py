import asyncio
import base64
import hashlib
import io

import pytest
from PIL import Image

from social_operations import workspace_asset_ingress as ingress
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store


def png():
    out = io.BytesIO()
    Image.new('RGB', (12, 12), 'blue').save(out, format='PNG')
    return out.getvalue()


@pytest.fixture
def env(tmp_path):
    now = [1000000000.]
    store = Store(tmp_path / 'db.sqlite', clock=lambda: now[0])
    actor = store.authenticate(store.create_principal('tenant', 'owner', scopes={'publish', 'status'}))
    return store, actor, Application(store), now


async def call(app, actor, kind, key, **fields):
    return await ingress.import_workspace_image(app, actor, {
        'command': {'kind': kind, **fields}, 'request_key': key})


async def begin(app, actor, key='begin', data=None, **extra):
    data = png() if data is None else data
    fields = {'source_sha256': hashlib.sha256(data).hexdigest(), 'mime': 'image/png', 'size_bytes': len(data)}
    fields.update(extra)
    return await call(app, actor, 'import_begin', key, **fields)


async def chunk(app, actor, ident, data, key='chunk', offset=0):
    return await call(app, actor, 'import_chunk', key, upload_id=ident, offset=offset,
                      data_base64=base64.b64encode(data).decode())


async def staged(env, **extra):
    store, actor, app, now = env
    result = await begin(app, actor, **extra)
    ident = result['workspace_upload']['upload_id']
    await chunk(app, actor, ident, png())
    return ident


@pytest.mark.asyncio
async def test_roundtrip_resume_replay_and_private_ledger(env):
    store, actor, app, _ = env
    first = await begin(app, actor)
    ident = first['workspace_upload']['upload_id']
    half = len(png()) // 2
    initial = await chunk(app, actor, ident, png()[:half])
    restart = Application(Store(store.path, clock=store.clock))
    assert (await begin(restart, actor))['operation_id'] == first['operation_id']
    assert (await chunk(restart, actor, ident, png()[:half]))['operation_id'] == initial['operation_id']
    retry = await chunk(restart, actor, ident, png()[:half], 'same-bytes-new-key')
    assert retry['workspace_upload']['received_bytes'] == half
    await chunk(restart, actor, ident, png()[half:], 'second', offset=half)
    result = await call(restart, actor, 'import_finish', 'finish', upload_id=ident)
    assert result['state'] == 'verified' and result['workspace_upload']['state'] == 'completed'
    assert restart.read_asset(actor, result['resource_id'])[1] == 'image/png'
    replay = await call(restart, actor, 'import_finish', 'finish', upload_id=ident)
    assert replay['operation_id'] == result['operation_id']
    recovery = await call(restart, actor, 'import_finish', 'finish-new', upload_id=ident)
    assert recovery['resource_id'] == result['resource_id']
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 2
        assert db.execute('SELECT length(bytes) FROM workspace_uploads').fetchone()[0] == 0
        logs = '\n'.join(str(tuple(r)) for t in ('operations', 'request_keys', 'events')
                         for r in db.execute('SELECT * FROM ' + t))
    assert base64.b64encode(png()[:half]).decode() not in logs
    assert 'data_base64' not in logs



@pytest.mark.asyncio
async def test_additive_migration_reapply_preserves_uploads_assets_and_receipts(env):
    store, actor, app, _ = env
    ident = await staged(env)
    finished = await call(app, actor, 'import_finish', 'finish-migration', upload_id=ident)
    second = (await begin(app, actor, key='second-upload'))['workspace_upload']['upload_id']
    await chunk(app, actor, second, png()[:10], key='second-chunk')
    tables = ('tenants', 'principals', 'assets', 'workspace_uploads', 'operations', 'request_keys', 'events')
    with store.tx() as db:
        before = {name: [tuple(row) for row in db.execute('SELECT * FROM ' + name + ' ORDER BY rowid')]
                  for name in tables}
        # The additive v8 rollback retains all rows and lowers only the marker.
        db.execute('PRAGMA user_version=7')
    restored = Store(store.path, clock=store.clock)
    with restored.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 8
        after = {name: [tuple(row) for row in db.execute('SELECT * FROM ' + name + ' ORDER BY rowid')]
                 for name in tables}
        assert after == before
    resumed = Application(restored)
    replay = await call(resumed, actor, 'import_finish', 'finish-migration', upload_id=ident)
    assert replay['resource_id'] == finished['resource_id']
    await chunk(resumed, actor, second, png()[10:], key='second-rest', offset=10)
    assert (await call(resumed, actor, 'import_finish', 'second-finish', upload_id=second))['state'] == 'verified'

@pytest.mark.asyncio
async def test_offset_conflicts_and_immutable_key(env):
    _, actor, app, _ = env
    ident = (await begin(app, actor))['workspace_upload']['upload_id']
    await chunk(app, actor, ident, png()[:10])
    for data, key, offset, code in [
        (b'bad', 'chunk', 0, 'idempotency_conflict'),
        (b'bad', 'different', 0, 'workspace_upload_offset_conflict'),
        (b'x', 'gap', 11, 'workspace_upload_offset_conflict'),
        (png(), 'overflow', 10, 'workspace_upload_offset_conflict')]:
        with pytest.raises(DomainError) as exc:
            await chunk(app, actor, ident, data, key, offset)
        assert exc.value.code == code
    with pytest.raises(DomainError, match='workspace upload incomplete'):
        await call(app, actor, 'import_finish', 'early', upload_id=ident)


@pytest.mark.asyncio
async def test_abort_expiry_and_retention_cleanup(env):
    store, actor, app, now = env
    ident = await staged(env)
    result = await call(app, actor, 'import_abort', 'abort', upload_id=ident)
    assert result['workspace_upload']['state'] == 'aborted'
    assert (await call(app, actor, 'import_abort', 'abort-again', upload_id=ident))['workspace_upload']['state'] == 'aborted'
    with pytest.raises(DomainError, match='workspace upload closed'):
        await call(app, actor, 'import_finish', 'finish', upload_id=ident)
    exp = (await begin(app, actor, 'expiring'))['workspace_upload']['upload_id']
    await chunk(app, actor, exp, png(), 'expiring-chunk')
    now[0] += ingress.UPLOAD_TTL + 1
    with pytest.raises(DomainError, match='workspace upload expired'):
        await call(app, actor, 'import_finish', 'expired-finish', upload_id=exp)
    status = await call(app, actor, 'import_status', 'status', upload_id=exp)
    assert status['workspace_upload']['state'] == 'expired'
    with store.connection() as db:
        assert db.execute('SELECT SUM(length(bytes)) FROM workspace_uploads').fetchone()[0] == 0
    now[0] += ingress.TERMINAL_TTL
    await begin(app, actor, 'trigger-cleanup')
    with store.connection() as db:
        assert not db.execute('SELECT 1 FROM workspace_uploads WHERE id=?', (exp,)).fetchone()


@pytest.mark.asyncio
async def test_hash_mime_and_invalid_image_destroy_staged_bytes(env):
    store, actor, app, _ = env
    for i, data, extra in [(1, png(), {'source_sha256': '0' * 64}),
                           (2, png(), {'mime': 'image/jpeg'}),
                           (3, b'not an image', {})]:
        ident = (await begin(app, actor, str(i), data, **extra))['workspace_upload']['upload_id']
        await chunk(app, actor, ident, data, 'chunk-' + str(i))
        with pytest.raises(DomainError):
            await call(app, actor, 'import_finish', 'finish-' + str(i), upload_id=ident)
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 0
        assert db.execute('SELECT SUM(length(bytes)) FROM workspace_uploads').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_scope_principal_tenant_epoch_and_revocation(env, monkeypatch):
    store, actor, app, _ = env
    ident = await staged(env)
    others = [store.authenticate(store.create_principal(t, p, scopes={'publish'}))
              for t, p in [('tenant', 'other'), ('other-tenant', 'outsider')]]
    for other in others:
        for kind in ('import_status', 'import_abort', 'import_finish'):
            with pytest.raises(DomainError, match='workspace upload not found'):
                await call(app, other, kind, kind, upload_id=ident)
    with store.tx() as db:
        db.execute("UPDATE principals SET scopes='[\"status\"]' WHERE id='owner'")
    with pytest.raises(DomainError, match='access denied'):
        await call(app, actor, 'import_status', 'status', upload_id=ident)
    with store.tx() as db:
        db.execute("UPDATE principals SET scopes='[\"publish\"]',epoch=epoch+1 WHERE id='owner'")
    with pytest.raises(DomainError, match='Current authorization is required'):
        await call(app, actor, 'import_status', 'status', upload_id=ident)
    from dataclasses import replace
    current = replace(actor, epoch=actor.epoch + 1)
    with pytest.raises(DomainError, match='workspace upload not found'):
        await call(app, current, 'import_status', 'status', upload_id=ident)


@pytest.mark.asyncio
async def test_bounded_sessions_and_global_reservations(env, monkeypatch):
    store, actor, app, _ = env
    await begin(app, actor, 'one')
    await begin(app, actor, 'two')
    with pytest.raises(DomainError, match='workspace upload quota exceeded'):
        await begin(app, actor, 'three')
    other = store.authenticate(store.create_principal('tenant', 'other', scopes={'visual'}))
    monkeypatch.setattr(ingress, 'GLOBAL_STAGED_BYTES', len(png()) * 2)
    with pytest.raises(DomainError, match='workspace upload quota exceeded'):
        await begin(app, other, 'four')


@pytest.mark.asyncio
async def test_finish_race_is_atomic_and_decode_off_loop(env, monkeypatch):
    store, actor, app, _ = env
    ident = await staged(env)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = ingress.verify_image
    async def decode(fn, *args):
        entered.set()
        await release.wait()
        return original(*args)
    monkeypatch.setattr(ingress, 'run_in_threadpool', decode)
    tasks = [asyncio.create_task(call(app, actor, 'import_finish', key, upload_id=ident))
             for key in ('finish-one', 'finish-two')]
    await entered.wait()
    await asyncio.sleep(0)
    with pytest.raises(DomainError, match='asset ingress busy'):
        await call(app, actor, 'import_finish', 'third', upload_id=ident)
    release.set()
    results = await asyncio.gather(*tasks)
    assert results[0]['resource_id'] == results[1]['resource_id']
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 2


@pytest.mark.asyncio
async def test_revocation_during_decode_prevents_asset_admission(env, monkeypatch):
    store, actor, app, _ = env
    ident = await staged(env)
    original = ingress.verify_image
    async def decode(fn, *args):
        with store.tx() as db:
            db.execute("UPDATE principals SET epoch=epoch+1 WHERE id='owner'")
        return original(*args)
    monkeypatch.setattr(ingress, 'run_in_threadpool', decode)
    with pytest.raises(DomainError, match='Current authorization is required'):
        await call(app, actor, 'import_finish', 'finish', upload_id=ident)
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('encoded', ['!!!!', '', 'eA===', 'A' * (262144 + 4)])
async def test_invalid_and_oversized_base64(env, encoded):
    _, actor, app, _ = env
    ident = (await begin(app, actor))['workspace_upload']['upload_id']
    with pytest.raises(DomainError, match='invalid input'):
        await call(app, actor, 'import_chunk', 'bad', upload_id=ident, offset=0, data_base64=encoded)


@pytest.mark.asyncio
async def test_verification_runs_off_event_loop(env, monkeypatch):
    import threading
    _, actor, app, _ = env
    ident = await staged(env)
    event_loop_thread = threading.get_ident()
    original = ingress.verify_image
    seen = []
    def verify(*args):
        seen.append(threading.get_ident())
        return original(*args)
    monkeypatch.setattr(ingress, 'verify_image', verify)
    await call(app, actor, 'import_finish', 'finish', upload_id=ident)
    assert seen and seen[0] != event_loop_thread


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['abort', 'expire'])
async def test_finish_rechecks_terminal_state_after_decode(env, monkeypatch, change):
    store, actor, app, now = env
    ident = await staged(env)
    original = ingress.verify_image
    async def decode(fn, *args):
        if change == 'abort':
            await call(app, actor, 'import_abort', 'abort', upload_id=ident)
        else:
            now[0] += ingress.UPLOAD_TTL + 1
        return original(*args)
    monkeypatch.setattr(ingress, 'run_in_threadpool', decode)
    with pytest.raises(DomainError):
        await call(app, actor, 'import_finish', 'finish', upload_id=ident)
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM assets').fetchone()[0] == 0
        assert db.execute('SELECT SUM(length(bytes)) FROM workspace_uploads').fetchone()[0] == 0
