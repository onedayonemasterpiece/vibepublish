"""Shared authenticated admission/worker proof contracts, not live MAX evidence."""
import json
from dataclasses import replace
import pytest
from adapters.native import identity
from adapters.port import Capability,Observation,Prepared,RemoteItem,ReadPage
from social_operations.domain import DomainError
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker

class Provider:
    def __init__(self):self.items={};self.effects=0;self.wrong=False;self.missing=False
    async def prepare(self,request,hooks):return Prepared(request,Capability('supported','isolated core test'))
    async def execute(self,prepared,hooks):
        r=prepared.request
        await hooks.checkpoint('PREPARED',json.dumps({'attempt':r.attempt_id}))
        await hooks.before_effect(r.attempt_id,r.plan_digest)
        self.effects+=1
        if r.action=='react':
            values=set(r.subject.own_reactions)
            (values.add if r.reaction_mode=='add' else values.discard)(r.reaction)
            item=replace(r.subject,own_reactions_observed=not self.missing,own_reactions=tuple(sorted(values)) if not self.wrong else ())
        else:
            item=RemoteItem(str(self.effects),'published',json.loads(r.content_json)['text'],'',
                '2026-09-08T00:00:00Z',native_target=r.native_target,url=f'https://max.ru/c/{r.native_target}/{self.effects}',
                reply_to_native_id=('wrong' if self.wrong else r.subject.native_id) if r.action=='reply' else None)
        item=replace(item,fingerprint=identity(item));self.items[item.native_id]=item
        return Observation('reacted' if r.action=='react' else 'published',(item,))
    async def read(self,request,hooks):return ReadPage(tuple(self.items.values()))

@pytest.fixture
def runtime(tmp_path):
    store=Store(tmp_path/'core.sqlite');token=store.create_principal('tenant','owner',owner=True)
    actor=store.authenticate(token);store.add_connection(actor,'connection','max',account_type='fake')
    binding=store.bind(actor,'owner','max','connection','-101')
    provider=Provider();app=Application(store);worker=Worker(store,{'max':provider})
    return store,actor,binding,provider,app,worker

async def publish(runtime):
    store,actor,binding,provider,app,worker=runtime
    result=await app.call(actor,'vibepublish_publish',{'to':['max'],'content':{'text':'Source'}})
    await worker.run_once();result=store.receipt(actor,result['operation_id'])
    assert result['state']=='verified';return result['deliveries'][0]['item_ref']

@pytest.mark.asyncio
async def test_reply_and_reaction_use_same_worker_and_explicit_additive_rights(runtime):
    store,actor,binding,p,app,worker=runtime;source=await publish(runtime)
    reply={'command':{'kind':'reply','item_ref':source,'content':{'text':'Reply'}}}
    denied=await app.call(actor,'vibepublish_engage',reply)
    assert denied['error']['code']=='access_denied' and p.effects==1
    store.grant_binding_rights(actor,binding,['reply','react'])
    accepted=await app.call(actor,'vibepublish_engage',reply)
    await worker.run_once();done=store.receipt(actor,accepted['operation_id'])
    assert done['state']=='verified' and done['deliveries'][0]['reply_to_ref']==source
    for mode in ('add','remove'):
        accepted=await app.call(actor,'vibepublish_engage',{'command':{'kind':'react','item_ref':source,'reaction':'👍','mode':mode}})
        await worker.run_once();done=store.receipt(actor,accepted['operation_id'])
        assert done['state']=='verified',done
        assert done['deliveries'][0]['observed']=='reacted' and done['deliveries'][0]['reaction_mode']==mode
        source=done['deliveries'][0]['item_ref']
    assert p.effects==4

@pytest.mark.asyncio
@pytest.mark.parametrize('kind,code',[('reply','reply_subject_mismatch'),('react','reaction_subject_or_state_mismatch')])
async def test_wrong_native_social_evidence_does_not_become_success(runtime,kind,code):
    store,actor,binding,p,app,worker=runtime;source=await publish(runtime)
    store.grant_binding_rights(actor,binding,['reply','react']);p.wrong=True
    command={'kind':kind,'item_ref':source,**({'content':{'text':'Reply'}} if kind=='reply' else {'reaction':'👍','mode':'add'})}
    admitted=await app.call(actor,'vibepublish_engage',{'command':command})
    await worker.run_once();result=store.receipt(actor,admitted['operation_id'])
    assert result['state']=='outcome_unknown' and result['error']['code']==code
    assert p.effects==2


def test_additive_grant_preserves_binding_epoch_and_never_changes_attempts(runtime):
    store,actor,binding,p,app,worker=runtime
    with store.connection() as db:before=dict(db.execute('SELECT * FROM bindings WHERE id=?',(binding,)).fetchone())
    rights=store.grant_binding_rights(actor,binding,['reply'])
    assert set(json.loads(before['rights']))<=set(rights)
    with store.connection() as db:
        after=dict(db.execute('SELECT * FROM bindings WHERE id=?',(binding,)).fetchone())
        assert after['epoch']==before['epoch'] and db.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
    with pytest.raises(DomainError):store.grant_binding_rights(actor,binding,['made_up'])
    with pytest.raises(DomainError):store.grant_binding_rights(replace(actor,owner=False),binding,['react'])


@pytest.mark.asyncio
async def test_missing_reaction_observation_is_not_proof_of_removal(runtime):
    store,actor,binding,p,app,worker=runtime;source=await publish(runtime)
    store.grant_binding_rights(actor,binding,['react']);p.missing=True
    admitted=await app.call(actor,'vibepublish_engage',{'command':{'kind':'react','item_ref':source,'reaction':'👍','mode':'remove'}})
    await worker.run_once();result=store.receipt(actor,admitted['operation_id'])
    assert result['state']=='outcome_unknown' and result['error']['code']=='reaction_subject_or_state_mismatch'


@pytest.mark.asyncio
async def test_exact_own_reaction_reads_preserve_empty_vs_missing_evidence(runtime):
    store,actor,binding,p,app,worker=runtime;ref=await publish(runtime)
    store.grant_binding_rights(actor,binding,['react'])
    for mode,expected in [('add',['👍']),('remove',[])]:
        admitted=await app.call(actor,'vibepublish_engage',{'command':{'kind':'react','item_ref':ref,'reaction':'👍','mode':mode}})
        await worker.run_once();done=store.receipt(actor,admitted['operation_id']);ref=done['deliveries'][0]['item_ref']
        read=await app.call(actor,'vibepublish_read',{'query':{'kind':'reactions','item_ref':ref}})
        await worker.run_once();result=store.receipt(actor,read['operation_id'])
        assert result['state']=='verified' and result['items'][0]['own_reactions']==expected
    p.items={k:replace(v,own_reactions_observed=False) for k,v in p.items.items()}
    read=await app.call(actor,'vibepublish_read',{'query':{'kind':'reactions','item_ref':ref}})
    await worker.run_once();result=store.receipt(actor,read['operation_id'])
    assert result['state']=='blocked' and result['error']['code']=='reaction_read_unverified'
    assert p.effects==3
