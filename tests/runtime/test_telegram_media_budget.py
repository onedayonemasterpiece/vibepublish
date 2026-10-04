"""Actual ledger/worker admission, mixed workloads, restart and rolling windows."""
import asyncio
import json
import pytest
from tests.runtime.test_media_store import Provider, png, args
from social_operations.storage import Store
from social_operations.service import Application
from social_operations.worker import Worker
from social_operations.assets import verify_image, insert_verified_image
from social_operations.media_budget import wait_until, media_files


@pytest.mark.asyncio
async def test_27_files_shared_budget_durable_defer_restart_and_independent_connection(tmp_path):
    clock=[1800000000.0]
    store=Store(tmp_path/'ledger.sqlite',clock=lambda:clock[0])
    actor=store.authenticate(store.create_principal('t','owner',owner=True))
    for connection,alias in [('connection','vault'),('connection','ordinary'),('other_connection','other')]:
        if alias!='ordinary':store.add_connection(actor,connection,'telegram',account_type='fake')
        store.bind(actor,'owner',alias,connection,{'vault':'-1004379835477','ordinary':'-1004379835499','other':'-1004379835478'}[alias])
    with store.tx() as db:asset=insert_verified_image(store,db,actor,verify_image(png(),'image/png'))
    provider=Provider();app=Application(store);workers=[Worker(store,{'telegram':provider}),Worker(Store(store.path,clock=lambda:clock[0]),{'telegram':provider})]
    accepted=[]
    for i in range(25):
        r=await app.call(actor,'vibepublish_media_store',args(asset,'budget-'+str(i),text='Budget synthetic file '+str(i)));assert 'operation_id' in r,r;accepted.append(r)
    album=await app.call(actor,'vibepublish_publish',{'to':['ordinary'],'content':{'text':'Ordinary album shares the same connection'},'media':[{'source':{'kind':'asset','id':asset},'role':'document'}]*2,'request_key':'ordinary-album'});assert 'operation_id' in album,album;accepted.append(album)
    text=await app.call(actor,'vibepublish_publish',{'to':['ordinary'],'content':{'text':'Text only unaffected'},'request_key':'text-only'})
    other=await app.call(actor,'vibepublish_publish',{'to':['other'],'content':{'text':'Independent connection'},'media':[{'source':{'kind':'asset','id':asset},'role':'document'}]*3,'request_key':'other-connection'})
    for _ in range(16):await asyncio.gather(*(w.run_once() for w in workers))
    def events():
        with store.connection() as db:
            return [(r['dispatch_at'],media_files(json.loads(r['plan'])),json.loads(r['plan'])['connection_id']) for r in db.execute("select plan,dispatch_at from attempts where dispatched=1 order by dispatch_at,id")]
    first=events();assert sum(n for _,n,c in first if c=='connection')==20
    assert sum(n for _,n,c in first if c=='other_connection')==3
    assert store.receipt(actor,text['operation_id'])['state']=='verified'
    assert store.receipt(actor,other['operation_id'])['state']=='verified'
    with store.connection() as db:
        waiting=list(db.execute("select a.* from attempts a where a.state='accepted' and a.stage='waiting_connection'"));assert waiting
        assert all(r['dispatched']==0 for r in waiting)
        assert all(db.execute('select complete,lease_owner from operations where id=?',(r['operation_id'],)).fetchone()['complete']==0 for r in waiting)
    # New process objects see the same durable dispatch window and due times.
    store=Store(store.path,clock=lambda:clock[0]);worker=Worker(store,{'telegram':provider});clock[0]+=59.999
    assert not await worker.run_once();assert events()==first
    clock[0]=1800000060.002
    for _ in range(30):
        if not await worker.run_once():break
    assert all(store.receipt(actor,r['operation_id'])['state']=='verified' for r in accepted)
    dispatch=events();assert sum(n for _,n,c in dispatch if c=='connection')==27
    for at,_,connection in dispatch:
        assert sum(n for t,n,c in dispatch if c==connection and at-60<=t<=at)<=20
    # The real ledger timestamps are inspectable deterministic acceptance evidence.
    (tmp_path/'dispatch-evidence.json').write_text(json.dumps(dispatch))
    before=provider.effects
    for i in range(25):await app.call(actor,'vibepublish_media_store',args(asset,'budget-'+str(i),text='Budget synthetic file '+str(i)))
    assert not await worker.run_once();assert provider.effects==before


def test_media_upload_count_includes_changed_edits_and_excludes_native_forwards():
    assert media_files({'action':'forward','assets':[{'sha256':'a'}]})==0
    assert media_files({'action':'edit','assets':[{'sha256':'a'}],'existing':{'media_hashes':['a']}})==0
    assert media_files({'action':'edit','assets':[{'sha256':'b'}],'existing':{'media_hashes':['a']}})==1
