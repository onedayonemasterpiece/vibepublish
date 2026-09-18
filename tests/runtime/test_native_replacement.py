"""Native identity changes require typed, exact lifecycle evidence before commit."""
import json
from dataclasses import asdict, replace
from types import SimpleNamespace
import pytest
from adapters.port import NativeReplacement, Observation, RemoteItem
from social_operations.domain import OutcomeUnknown
from social_operations.worker import Worker

class CommitReached(Exception): pass
class Store:
    def tx(self): raise CommitReached()

def case():
    old=RemoteItem('old','scheduled','Exact content','fingerprint','2026-09-08T00:00:00Z',
        scheduled_at='2026-09-09T07:30:00Z',native_target='target')
    new=replace(old,native_id='new',scheduled_at='2026-09-09T09:30:00Z')
    plan=dict(existing=asdict(old),provider='max',account_type='max_web',action='reschedule',
        native_target='target',scheduled_at=new.scheduled_at,content_json=json.dumps({'text':old.text}),assets=[])
    proof=NativeReplacement(old.native_id,new.native_id,old.fingerprint,'trusted_ui_native_queue_replacement')
    return plan,Observation('provider_scheduled',(new,),replacement=proof)

def check(plan,observation):
    return Worker.finish_child(SimpleNamespace(store=Store()),{},dict(plan=json.dumps(plan)),None,observation)

def test_exact_native_replacement_reaches_normal_commit():
    plan,observation=case()
    with pytest.raises(CommitReached): check(plan,observation)

@pytest.mark.parametrize('change',[{'provider':'telegram'},{'account_type':'fake'},{'action':'edit'}])
def test_no_widening_to_other_lifecycles(change):
    plan,observation=case();plan.update(change)
    with pytest.raises(OutcomeUnknown) as error: check(plan,observation)
    assert error.value.code=='lifecycle_identity_changed'

@pytest.mark.parametrize('field,value',[('previous_native_id','other'),('native_id','other'),('previous_fingerprint','other'),('evidence','text_match')])
def test_wrong_replacement_binding_rejected(field,value):
    plan,observation=case()
    observation=replace(observation,replacement=replace(observation.replacement,**{field:value}))
    with pytest.raises(OutcomeUnknown) as error: check(plan,observation)
    assert error.value.code=='lifecycle_identity_changed'

def test_untyped_identity_change_rejected():
    plan,observation=case()
    with pytest.raises(OutcomeUnknown):check(plan,replace(observation,replacement=None))

def test_replacement_does_not_skip_content_or_time_checks():
    plan,observation=case()
    for field,value in [('text','Changed'),('scheduled_at','2026-09-10T09:30:00Z')]:
        with pytest.raises(OutcomeUnknown):check(plan,replace(observation,items=(replace(observation.items[0],**{field:value}),)))
