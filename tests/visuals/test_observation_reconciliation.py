"""Offline worker/command regressions; no native generation or publication."""
import json
from dataclasses import replace
import pytest,pytest_asyncio

from adapters.imagegen import FakeImagegen
from social_operations.domain import DomainError,digest
from social_operations.assets import import_image
from tests.visuals.test_visual_service import runtime,call
from tests.providers.test_native_adapters import asset

class LateObservation(FakeImagegen):
 def __init__(self,root):super().__init__(root);self.ready=False;self.reads=[];self.before_read=None;self.read_state='succeeded'
 async def find(self,key):raise AssertionError('must inspect the saved execution_ref, never find')
 async def inspect(self,ref):
  self.reads.append(ref)
  if self.before_read:self.before_read()
  result=await FakeImagegen.find(self,ref)
  return replace(result,state=self.read_state if self.ready else 'unknown',artifacts=result.artifacts if self.ready else ())

@pytest_asyncio.fixture
async def terminal(runtime):
 store,actor,app,worker,_,provider,clock,binding,token=runtime
 executor=LateObservation(store.path.parent/'late-art');worker.imagegen=executor
 original=await call(app,actor,'visual',{'command':{'kind':'generate','brief':'Offline saved-task recovery','candidates':1,'selection':'automatic'},'request_key':'original'})
 assert await worker.run_once()
 result=store.receipt(actor,original['operation_id']);assert result['state']=='outcome_unknown' and result['operation_complete']
 with store.connection() as db:
  op=dict(db.execute('SELECT * FROM operations WHERE id=?',(original['operation_id'],)).fetchone());job=dict(db.execute('SELECT * FROM visual_jobs WHERE operation_id=?',(op['id'],)).fetchone())
 command={'kind':'reconcile_observation','operation_id':op['id'],'job_id':job['id'],'expected_revision':op['revision'],'expected_visual_revision':job['revision']}
 executor.ready=True
 clock[0]+=31 # Terminal worker lease must have expired before explicit recovery.
 return store,actor,app,worker,executor,provider,clock,binding,token,op,job,command

async def recover(f,**changes):
 return await f[2].call(f[1],'vibepublish_visual',{'command':{**f[-1],**changes},'request_key':'observe-existing'})

@pytest.mark.asyncio
async def test_same_terminal_operation_recovers_completed_art_without_submit_after_deadline(terminal):
 store,actor,app,worker,executor,provider,clock,_,_,old,job,_=terminal
 clock[0]=job['deadline']+30
 queued=await recover(terminal)
 assert queued['operation_id']==old['id'] and queued['state']=='accepted' and queued['revision']==old['revision']+1
 assert queued['visual_revision']==job['revision']+1 and not queued['retry_safe']
 with store.tx() as db:
  current=db.execute('SELECT * FROM operations WHERE id=?',(old['id'],)).fetchone()
  assert current['deadline']==old['deadline'] and current['fence']==old['fence']+1
  assert current['lease_owner'] is None
  with pytest.raises(DomainError,match='stale worker'):store.fence(db,old['id'],old['lease_owner'],old['fence'])
 assert await worker.run_once()
 done=store.receipt(actor,old['id']);assert done['state']=='needs_selection' and done['operation_complete']
 assert len(done['candidates'])==1 and len(executor.calls)==1 and executor.reads==[job['id'],job['id']]
 assert executor.calls[0].deadline==job['deadline'] and provider.count('effect')==0
 assert not done.get('selected_asset_ref') # Even automatic fixture mode cannot publish/select in observation recovery.
 with store.connection() as db:
  current=db.execute('SELECT * FROM visual_jobs WHERE id=?',(job['id'],)).fetchone()
  assert current['dispatched']==1 and current['execution_ref']==job['execution_ref']
  assert current['input_digest']==job['input_digest'] and current['deadline']==job['deadline']
  assert db.execute('SELECT count(*) FROM operations').fetchone()[0]==1
  assert db.execute('SELECT count(*) FROM visual_jobs').fetchone()[0]==1
  assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
 replay=await recover(terminal);assert replay['revision']==done['revision'] and replay['candidates']==done['candidates']
 assert not await worker.run_once() and len(executor.calls)==1

@pytest.mark.asyncio
@pytest.mark.parametrize('field,value',[('expected_revision',99),('expected_visual_revision',99)])
async def test_stale_revision_does_not_requeue_or_send(terminal,field,value):
 result=await recover(terminal,**{field:value});assert result['error']['code']=='visual_revision_conflict'
 assert not await terminal[3].run_once() and len(terminal[4].calls)==1

@pytest.mark.asyncio
@pytest.mark.parametrize('column,value',[('lease_until','active'),('complete',0),('work_state','working')])
async def test_nonterminal_or_live_lease_cannot_recover(terminal,column,value):
 store,_,_,worker,executor,_,clock,*_=terminal;old=terminal[9]
 with store.tx() as db:db.execute(f'UPDATE operations SET {column}=? WHERE id=?',(clock[0]+60 if value=='active' else value,old['id']))
 result=await recover(terminal);assert result['error']['code']=='imagegen_observation_reconciliation_conflict'
 assert len(executor.calls)==1

@pytest.mark.asyncio
@pytest.mark.parametrize('column,value',[('dispatched',0),('execution_ref',None),('execution_ref','visual_'+'f'*32),('selected_candidate','candidate_'+'a'*32)])
async def test_dispatch_identity_or_choice_conflict_cannot_recover(terminal,column,value):
 with terminal[0].tx() as db:db.execute(f'UPDATE visual_jobs SET {column}=? WHERE id=?',(value,terminal[10]['id']))
 result=await recover(terminal);assert result['error']['code']=='imagegen_observation_reconciliation_conflict'
 assert not await terminal[3].run_once() and len(terminal[4].calls)==1

@pytest.mark.asyncio
async def test_candidate_or_provider_attempt_cannot_recover(terminal):
 store,actor,_,_,executor,_,_,binding,_,old,job,_=terminal
 with store.tx() as db:
  b=db.execute('SELECT epoch FROM bindings WHERE id=?',(binding,)).fetchone()
  db.execute('INSERT INTO attempts(id,operation_id,binding_id,binding_epoch,alias,provider,plan,plan_digest) VALUES(?,?,?,?,?,?,?,?)',('attempt_existing',old['id'],binding,b['epoch'],'announcements','telegram',json.dumps({'content_json':'{}'}),digest({'content_json':'{}'})))
 assert (await recover(terminal))['error']['code']=='imagegen_observation_reconciliation_conflict'
 with store.tx() as db:db.execute('DELETE FROM attempts WHERE operation_id=?',(old['id'],))
 ref=import_image(store,actor,asset(1).data,'image/png')
 with store.tx() as db:
  a=db.execute('SELECT sha256,width,height FROM assets WHERE id=?',(ref,)).fetchone()
  db.execute('INSERT INTO visual_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('candidate_existing',job['id'],0,ref,a['sha256'],ref,a['sha256'],a['width'],a['height'],'post_4_5','{}','{}','none',1,1))
 assert (await recover(terminal))['error']['code']=='imagegen_observation_reconciliation_conflict'
 assert len(executor.calls)==1

@pytest.mark.asyncio
async def test_actor_scope_epoch_routing_and_key_are_fenced(terminal):
 store,actor,app,_,executor,_,_,_,token,old,job,command=terminal
 no_key=await app.call(actor,'vibepublish_visual',{'command':command});assert no_key['error']['code']=='reconciliation_requires_request_key'
 other=store.authenticate(store.create_principal('tenant','other'))
 denied=await app.call(other,'vibepublish_visual',{'command':command,'request_key':'other'});assert denied['error']['code'] in {'visual_not_available','access_denied'}
 with store.tx() as db:db.execute('UPDATE principals SET routing_revision=routing_revision+1 WHERE id=?',(actor.principal_id,))
 assert (await recover(terminal))['error']['code']=='imagegen_observation_reconciliation_conflict'
 with store.tx() as db:db.execute('UPDATE principals SET epoch=epoch+1 WHERE id=?',(actor.principal_id,))
 assert (await recover(terminal))['error']['code']=='access_revoked'
 assert len(executor.calls)==1

@pytest.mark.asyncio
@pytest.mark.parametrize('state',['unknown','running','queued'])
async def test_unknown_or_unfinished_read_is_terminal_without_resend_or_poll_loop(terminal,state):
 executor=terminal[4];executor.read_state=state
 assert (await recover(terminal))['state']=='accepted'
 assert await terminal[3].run_once()
 result=terminal[0].receipt(terminal[1],terminal[9]['id']);assert result['state']=='outcome_unknown' and result['operation_complete']
 assert len(executor.reads)==2 and len(executor.calls)==1
 assert not await terminal[3].run_once()
 assert (await recover(terminal))['state']=='outcome_unknown' # same key only observes, never requeues.

@pytest.mark.asyncio
async def test_expired_read_window_never_reads_or_submits(terminal):
 queued=await recover(terminal);terminal[6][0]=queued['observation_recovery']['read_deadline']+1
 assert await terminal[3].run_once()
 result=terminal[0].receipt(terminal[1],terminal[9]['id']);assert result['state']=='outcome_unknown'
 assert result['error']['code']=='imagegen_observation_recovery_expired'
 assert len(terminal[4].calls)==1 and len(terminal[4].reads)==1

@pytest.mark.asyncio
async def test_current_routing_rechecked_during_import(terminal):
 # Standalone routing must still be current even if it changes DURING inspect.
 store,actor,_,worker,executor,*_=terminal
 await recover(terminal)
 def change_route():
  with store.tx() as db:db.execute('UPDATE principals SET routing_revision=routing_revision+1 WHERE id=?',(actor.principal_id,))
 executor.before_read=change_route
 await worker.run_once()
 result=store.receipt(store.authenticate(terminal[8]),terminal[9]['id']);assert result['state']=='blocked'
 assert result['error']['code']=='access_revoked' and not result.get('candidates') and len(executor.calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['command','import'])
async def test_parent_revision_is_checked_before_queue_and_at_import(runtime,stage):
 store,actor,app,worker,_,provider,clock,_,_=runtime
 executor=LateObservation(store.path.parent/'parent-art');worker.imagegen=executor
 original=await call(app,actor,'publish',{'to':['announcements'],'mode':'execute',
  'content':{'text':'Frozen parent caption'},'visual':{'kind':'generate','brief':'Offline parent','selection':'automatic'},'request_key':'parent'})
 assert await worker.run_once();clock[0]+=31;executor.ready=True
 with store.connection() as db:
  op=dict(db.execute('SELECT * FROM operations WHERE id=?',(original['operation_id'],)).fetchone());job=dict(db.execute('SELECT * FROM visual_jobs WHERE operation_id=?',(op['id'],)).fetchone())
 command={'kind':'reconcile_observation','operation_id':op['id'],'job_id':job['id'],'expected_revision':op['revision'],'expected_visual_revision':job['revision']}
 def change_parent():
  with store.tx() as db:db.execute('UPDATE publications SET revision=revision+1 WHERE id=?',(job['parent_publication'],))
 if stage=='command':change_parent()
 result=await app.call(actor,'vibepublish_visual',{'command':command,'request_key':'parent-observe'})
 if stage=='command':assert result['error']['code']=='visual_parent_revision_conflict'
 else:
  assert result['state']=='accepted';executor.before_read=change_parent
  assert await worker.run_once();result=store.receipt(actor,op['id'])
  assert result['state']=='blocked' and result['error']['code']=='visual_parent_revision_conflict'
 assert len(executor.calls)==1 and provider.count('effect')==0
 with store.connection() as db:assert db.execute('SELECT count(*) FROM visual_candidates').fetchone()[0]==0

@pytest.mark.asyncio
async def test_source_bytes_rechecked_at_import_without_creating_candidates(runtime):
 store,actor,app,worker,_,provider,clock,_,_=runtime
 source=import_image(store,actor,asset(1).data,'image/png')
 executor=LateObservation(store.path.parent/'source-art');worker.imagegen=executor
 first=await call(app,actor,'visual',{'command':{'kind':'tune','source':{'source':{'kind':'asset','id':source}},'brief':'Frozen source'},'request_key':'source'})
 assert await worker.run_once();clock[0]+=31;executor.ready=True
 with store.connection() as db:
  op=dict(db.execute('SELECT * FROM operations WHERE id=?',(first['operation_id'],)).fetchone());job=dict(db.execute('SELECT * FROM visual_jobs WHERE operation_id=?',(op['id'],)).fetchone())
 command={'kind':'reconcile_observation','operation_id':op['id'],'job_id':job['id'],'expected_revision':op['revision'],'expected_visual_revision':job['revision']}
 assert (await app.call(actor,'vibepublish_visual',{'command':command,'request_key':'source-observe'}))['state']=='accepted'
 def corrupt_source():
  # Offline corruption injection only; production immutable-asset trigger remains unchanged.
  with store.tx() as db:
   names=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='assets'")]
   for name in names:db.execute('DROP TRIGGER '+name)
   db.execute("UPDATE assets SET bytes=X'00' WHERE id=?",(source,))
 executor.before_read=corrupt_source
 assert await worker.run_once();result=store.receipt(actor,op['id'])
 assert result['state']=='blocked' and result['error']['code']=='asset_integrity'
 assert len(executor.calls)==1 and provider.count('effect')==0
 with store.connection() as db:assert db.execute('SELECT count(*) FROM visual_candidates').fetchone()[0]==0

@pytest.mark.asyncio
async def test_late_worker_fence_cannot_commit_or_downgrade_current_owner(terminal):
 store,actor,_,worker,executor,*_=terminal
 assert (await recover(terminal))['state']=='accepted'
 def change_fence():
  with store.tx() as db:db.execute('UPDATE operations SET fence=fence+1 WHERE id=?',(terminal[9]['id'],))
 executor.before_read=change_fence
 await worker.run_once()
 with store.connection() as db:
  assert db.execute('SELECT count(*) FROM visual_candidates').fetchone()[0]==0
  assert db.execute('SELECT state FROM operations WHERE id=?',(terminal[9]['id'],)).fetchone()[0]=='running'
 assert len(executor.calls)==1

@pytest.mark.asyncio
async def test_current_visual_scope_revocation_cannot_requeue(terminal):
 store,actor,*_=terminal
 with store.tx() as db:db.execute('UPDATE principals SET scopes=? WHERE id=?',(json.dumps(['status','publish']),actor.principal_id))
 result=await recover(terminal)
 assert result['error']['code'] in {'invalid_input','access_denied','imagegen_observation_reconciliation_conflict'}
 assert len(terminal[4].calls)==1 and not await terminal[3].run_once()
