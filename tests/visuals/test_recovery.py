from __future__ import annotations
import asyncio
import concurrent.futures
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from adapters.imagegen import FakeImagegen
from social_operations.assets import import_image
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from .test_visual_service import runtime, call, select_command
from tests.providers.test_native_adapters import asset


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,code,state,submits', [('before_marker',91,'needs_selection',1),
    ('after_marker',92,'outcome_unknown',0), ('after_submit',93,'needs_selection',0)])
async def test_independent_process_crashes_recover_without_second_executor_submit(runtime, stage, code, state, submits):
    store, actor, app, worker, executor, provider, clock, *_ = runtime
    first = await call(app,actor,'visual',{'command':{'kind':'generate','brief':'Crash fixture'}})
    result = await asyncio.to_thread(subprocess.run, [sys.executable,'-m','tests.visuals.crash_worker',str(store.path),str(executor.artifact_root),stage],capture_output=True,timeout=15)
    assert result.returncode==code,result.stderr.decode()
    clock[0]+=31  # Actual dead process + elapsed lease; not a mocked provider exception.
    await Worker(Store(store.path,clock=store.clock),imagegen=executor).run_once()
    observed=store.receipt(actor,first['operation_id'])
    assert observed['state']==state,observed
    assert len(executor.calls)==submits
    assert not await worker.run_once()
    assert provider.count('effect')==0
    if stage=='after_submit':
        assert len((executor.artifact_root/'submit.log').read_text().splitlines())==1


def test_v1_to_v3_migration_preserves_existing_rows_and_is_concurrent_idempotent(tmp_path):
    path=tmp_path/'ledger.sqlite'
    old_schema=Path(__file__).resolve().parents[2]/'social_operations/schema.sql'
    db=sqlite3.connect(path)
    db.executescript(old_schema.read_text())
    db.execute("INSERT INTO tenants(id,timezone,storage_limit) VALUES('old-tenant','Europe/Kaliningrad',123456)")
    db.commit();db.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _:Store(path), range(8)))
    store=Store(path)
    with store.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==3
        assert tuple(db.execute('SELECT id,storage_limit FROM tenants').fetchone())==('old-tenant',123456)
        assert db.execute('SELECT count(*) FROM visual_jobs').fetchone()[0]==0
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


@pytest.mark.asyncio
async def test_concurrent_same_selection_creates_one_attempt_and_one_resume(runtime):
    store, actor, app, worker, executor, provider, *_=runtime
    first=await call(app,actor,'publish',{'to':['announcements'],'visual':{'kind':'generate','brief':'Fixture'}})
    await worker.run_once();ready=store.receipt(actor,first['operation_id'])
    command=select_command(ready)
    def choose(n):
        return asyncio.run(Application(Store(store.path,clock=store.clock)).call(actor,'vibepublish_visual',{'command':command,'request_key':'choice-'+str(n)}))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(choose,range(8)))
    assert all(row.get('operation_id')==first['operation_id'] for row in rows),rows
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM publications').fetchone()[0]==1
        assert db.execute('SELECT revision FROM visual_jobs').fetchone()[0]==2
    await worker.run_once();assert provider.count('effect')==1
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_selected_fixture_cannot_be_republished_through_native_connection(runtime):
    store, actor, app, worker, executor, provider, *_=runtime
    first=await call(app,actor,'visual',{'command':{'kind':'generate','brief':'Fixture','selection':'automatic'}})
    await worker.run_once();selected=store.receipt(actor,first['operation_id'])
    store.add_connection(actor,'native','telegram',account_type='mtproto_user')
    store.bind(actor,actor.principal_id,'native','native','-1000000000101')
    result=await app.call(actor,'vibepublish_publish',{'to':['native'],'media':[{'source':{'kind':'asset','id':selected['selected_asset_ref']}}]})
    assert result['error']['code']=='fixture_asset_native_publish_forbidden'
    assert provider.count('effect')==0


@pytest.mark.asyncio
async def test_revocation_invalidates_visual_asset_reads_and_reuse(runtime):
    store, actor, app, worker, executor, provider, clock, binding, token=runtime
    first=await call(app,actor,'publish',{'to':['announcements'],'visual':{'kind':'generate','brief':'Fixture'}})
    await worker.run_once();ready=store.receipt(actor,first['operation_id'])
    ref=ready['candidates'][0]['asset_ref']
    store.revoke_binding(actor,binding);actor=store.authenticate(token)
    with pytest.raises(DomainError,match='authorization|revoked'):
        app.read_asset(actor,ref)
    reuse=await app.call(actor,'vibepublish_visual',{'command':{'kind':'tune','brief':'Reuse denied','source':{'source':{'kind':'asset','id':ref}}}})
    assert reuse['error']['code']=='access_revoked'


@pytest.mark.asyncio
async def test_artifact_from_other_job_is_not_resolved_in_shared_executor_root(runtime):
    from dataclasses import replace
    store, actor, app, worker, executor, provider, *_=runtime
    first=await call(app,actor,'visual',{'command':{'kind':'generate','brief':'First'}})
    await worker.run_once()
    original=await executor.inspect(first['visual_job_id'])
    second=await call(app,actor,'visual',{'command':{'kind':'generate','brief':'Second'},'request_key':'second'})
    original_inspect=executor.inspect
    async def malicious(ref):
        result=await original_inspect(ref)
        return replace(result,artifacts=original.artifacts)
    executor.inspect=malicious
    await worker.run_once()
    result=store.receipt(actor,second['operation_id'])
    assert result['state']=='blocked' and result['error']['code']=='imagegen_artifact_hash_mismatch'
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM visual_candidates WHERE job_id=?',(second['visual_job_id'],)).fetchone()[0]==0
