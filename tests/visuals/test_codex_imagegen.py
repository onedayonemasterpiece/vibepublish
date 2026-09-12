from __future__ import annotations
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import pytest

from adapters.codex_imagegen import CodexHost, CodexImagegen, configured_codex
from adapters.imagegen import ImagegenRequest, ImagegenSource
from social_operations.domain import DomainError, OutcomeUnknown
from social_operations.visual_artifacts import verified_artifact
from tests.providers.test_native_adapters import asset
from tests.visuals.test_visual_service import runtime, call, select_command

SCRIPT = Path(__file__).with_name('scripted_codex_cli.py').absolute()


def executor(tmp, case='good', **kwargs):
    host = CodexHost((sys.executable,str(SCRIPT),case,str(tmp/'external')),tmp/'codex-home',
        'scripted-codex 1','image-only',('gpt-5.6-luna',),'a'*64,True,5,True)
    return CodexImagegen(tmp/'results',replace(host,**kwargs))


def request(**kwargs):
    return replace(ImagegenRequest('visual_'+'c'*32,'d'*64,'generate','Scripted fixture, no model.',(),
        'fixture','gpt-5.6-luna',1,time.time()+90),**kwargs)


def count(tmp):
    path=tmp/'external'/'effects'
    return len(path.read_text().splitlines()) if path.exists() else 0


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['good','workspace'])
async def test_exact_reported_artifacts_request_vs_actual_and_restart_no_resubmit(tmp_path,monkeypatch,case):
    monkeypatch.setenv('OPENAI_API_KEY','NEVER_INHERIT')
    monkeypatch.setenv('VIBEPUBLISH_SERVICE_TOKEN','NEVER_INHERIT')
    ex=executor(tmp_path,case)
    probe=await ex.probe()
    assert probe['tool_callable']=='not_probed'
    req=request(candidate_budget=2)
    ref=await ex.submit(req)
    obs=await ex.inspect(ref)
    assert obs.state=='succeeded' and len(obs.artifacts)==2 and obs.fixture
    assert obs.actual_model is None and obs.actual_executor=='scripted-codex-fixture'
    for a in obs.artifacts: verified_artifact(ex.artifact_root/ref,a)
    seen=json.loads((tmp_path/'external'/'seen.json').read_text())
    assert not {'OPENAI_API_KEY','VIBEPUBLISH_SERVICE_TOKEN','PYTHONPATH','NODE_OPTIONS'} & set(seen['env_names'])
    binding=json.loads((ex.control_root/ref/'binding.json').read_text())
    assert binding['requested_route']=='gpt-5.6-luna'
    ev=json.loads((ex.control_root/ref/'events-evidence.json').read_text())
    assert ev['artifact_origin']=='structured_agent_report_not_native_image_tool_attestation'
    again=executor(tmp_path,case)
    assert await again.inspect(ref)==obs
    assert await again.submit(req)==ref and count(tmp_path)==1
    assert await again.cancel(ref)==obs  # Finished output isn't undone.
    with pytest.raises(DomainError,match='imagegen idempotency conflict'):
        await again.submit(replace(req,input_digest='e'*64))


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['tune','compose'])
async def test_exact_verified_sources_only_are_staged(tmp_path,mode):
    art=asset(1)
    sources=(ImagegenSource(art.ref,art.sha256,art.mime,80,100,art.size,art.data),)
    # Derive fixture dimensions independently; the native fixture helper differs.
    import io
    from PIL import Image
    with Image.open(io.BytesIO(art.data)) as image:
        sources=(replace(sources[0],width=image.width,height=image.height),)
    ex=executor(tmp_path)
    req=request(mode=mode,sources=sources)
    assert (await ex.inspect(await ex.submit(req))).state=='succeeded'
    seen=json.loads((tmp_path/'external'/'seen.json').read_text())
    assert len(seen['images'])==1
    assert Path(seen['images'][0]).read_bytes()==art.data


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['foreign_thread','foreign_root','symlink','hardlink','dir_symlink','traversal',
    'duplicate','missing','over_budget','bad_image','wrong_binding','extra_keys','report_mismatch',
    'no_terminal','after_terminal','bad_json','exit','bad_tool','huge'])
async def test_unproven_outputs_remain_unknown_and_never_retry(tmp_path,case):
    ex=executor(tmp_path,case)
    req=request()
    ref=await ex.submit(req)
    assert (await ex.inspect(ref)).state=='unknown'
    assert not (ex.artifact_root/ref).exists()
    # An unrelated recent image is not a valid substitute.
    latest=tmp_path/'codex-home'/'generated_images'/'unrelated'
    latest.mkdir(parents=True,exist_ok=True);(latest/'newest.png').write_bytes(asset(1).data)
    other=executor(tmp_path,case)
    assert (await other.find(req.job_key)).state=='unknown'
    await other.submit(req)
    assert count(tmp_path)==1


@pytest.mark.asyncio
async def test_timeout_terminates_owned_local_process_but_not_upstream_claim(tmp_path):
    ex=executor(tmp_path,'hang',timeout_seconds=5)
    ref=await ex.submit(request())
    assert (await ex.cancel(ref)).state=='unknown'
    pid=int((tmp_path/'external'/'pid').read_text())
    with pytest.raises(ProcessLookupError): os.kill(pid,0)
    await ex.submit(request())
    assert count(tmp_path)==1


@pytest.mark.asyncio
async def test_cancellation_during_submit_keeps_uncertainty_and_single_effect(tmp_path):
    ex=executor(tmp_path,'hang')
    req=request()
    task=asyncio.create_task(ex.submit(req))
    try:
        for _ in range(1000):
            if count(tmp_path): break
            await asyncio.sleep(.02)
        assert count(tmp_path)==1
        assert (await executor(tmp_path,'hang').find(req.job_key)).state=='running'
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert (await ex.find(req.job_key)).state=='unknown'
        assert await ex.submit(req)==req.job_key
        assert count(tmp_path)==1
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_version_and_validation_gates_before_generation(tmp_path):
    ex=executor(tmp_path,expected_version='different version')
    with pytest.raises(DomainError,match='codex cli version changed'): await ex.submit(request())
    assert count(tmp_path)==0
    ex=executor(tmp_path)
    for change in [dict(candidate_budget=5),dict(requested_route='made-up-model'),dict(deadline=0),dict(mode='tune')]:
        with pytest.raises(DomainError): await ex.submit(request(**change))
    bad=asset(1)
    source=ImagegenSource(bad.ref,'0'*64,bad.mime,1,1,bad.size,bad.data)
    with pytest.raises(DomainError,match='imagegen source integrity'):
        await ex.submit(request(mode='tune',sources=(source,)))
    assert count(tmp_path)==0
    with pytest.raises(DomainError,match='codex host contract not verified'):
        executor(tmp_path,image_only_isolation_verified=False)


@pytest.mark.asyncio
async def test_reserved_directory_without_receipt_is_not_resubmitted(tmp_path):
    ex=executor(tmp_path);req=request()
    (ex.control_root/req.job_key).mkdir(mode=0o700)
    with pytest.raises(OutcomeUnknown): await ex.submit(req)
    assert count(tmp_path)==0


@pytest.mark.asyncio
async def test_concurrent_submissions_do_not_duplicate_generation(tmp_path):
    ex=executor(tmp_path);other=executor(tmp_path);req=request()
    results=await asyncio.gather(ex.submit(req),other.submit(req),return_exceptions=True)
    assert any(r==req.job_key for r in results),results
    assert (await ex.find(req.job_key)).state=='succeeded' and count(tmp_path)==1


@pytest.mark.asyncio
async def test_real_SIGKILL_of_submitter_is_unknown_on_restart_no_second_effect(tmp_path):
    driver=Path(__file__).with_name('codex_crash_submit.py')
    log=(tmp_path/'driver.log').open('wb')
    process=subprocess.Popen([sys.executable,str(driver),str(tmp_path)],stdout=log,stderr=log)
    child_pid=None
    try:
        for _ in range(1500):
            if (tmp_path/'external'/'pid').exists():
                child_pid=int((tmp_path/'external'/'pid').read_text());break
            assert process.poll() is None,(tmp_path/'driver.log').read_text()
            await asyncio.sleep(.02)
        assert child_pid and count(tmp_path)==1
        process.kill();process.wait(timeout=5)
        assert process.returncode==-signal.SIGKILL
        ex=executor(tmp_path,'hang')
        observed=await ex.find(request().job_key)
        assert observed.state=='unknown'
        await ex.submit(request());assert count(tmp_path)==1
        assert (await ex.cancel(request().job_key)).state=='unknown'
        os.kill(child_pid,0)  # A new executor did NOT signal a persisted/reused PID.
    finally:
        if process.poll() is None: process.kill();process.wait(timeout=5)
        if child_pid:
            try: os.killpg(child_pid,signal.SIGKILL)
            except ProcessLookupError: pass
        log.close()


@pytest.mark.asyncio
async def test_existing_visual_service_importer_selection_and_parent_resume(runtime,tmp_path):
    store,actor,app,worker,_old,provider,*_=runtime
    ex=executor(tmp_path/'codex')
    ex.clock=store.clock
    worker.imagegen=ex
    first=await call(app,actor,'publish',{'to':['announcements'],'content':{'text':'Caption'},
        'visual':{'kind':'generate','brief':'Fixture art','candidates':1},'request_key':'codex-parent'})
    await worker.run_once()
    ready=store.receipt(actor,first['operation_id'])
    assert ready['state']=='needs_selection',ready
    assert ready['executor']['actual_model'] is None
    assert provider.count('effect')==0
    assert count(tmp_path/'codex')==1
    await call(app,actor,'visual',{'command':select_command(ready),'request_key':'codex-choose'})
    await worker.run_once()
    assert provider.count('effect')==1
    assert not await worker.run_once()
    assert count(tmp_path/'codex')==1


def test_closed_private_operator_config_and_disabled_default(tmp_path):
    config=tmp_path/'host.json'
    values={'command':[sys.executable], 'codex_home':str(tmp_path/'host'),
        'expected_version':'version requires observation on DevCoveer','profile':'image-only',
        'allowed_routes':['gpt-5.6-luna'],'attestation_ref':'a'*64,'image_only_isolation_verified':False}
    config.write_text(json.dumps(values));config.chmod(0o600)
    with pytest.raises(DomainError,match='codex host contract not verified'):
        configured_codex(tmp_path/'outputs',config)
    values['image_only_isolation_verified']='false'
    config.write_text(json.dumps(values))
    with pytest.raises(DomainError,match='codex host contract not verified'):
        configured_codex(tmp_path/'outputs',config)
    values['image_only_isolation_verified']=True
    config.write_text(json.dumps(values));config.chmod(0o644)
    with pytest.raises(DomainError,match='codex config not private'):
        configured_codex(tmp_path/'outputs',config)
    config.chmod(0o600);values['fixture']=True;config.write_text(json.dumps(values))
    with pytest.raises(DomainError,match='codex host config invalid'):
        configured_codex(tmp_path/'outputs',config)
    values.pop('fixture');config.write_text(json.dumps(values))
    loaded=configured_codex(tmp_path/'outputs',config)
    assert loaded.host.fixture is False  # Configuration alone has made no call.
    assert count(tmp_path)==0
    from social_operations.cli import parser
    args=parser().parse_args(['--db',str(tmp_path/'db'),'worker'])
    assert args.codex_imagegen_config is None and args.fake_imagegen is None
