"""Real queue recovery algorithm: native replacement, never a repeated Save."""
import importlib
import os
from types import SimpleNamespace
import pytest
if os.environ.get('VIBEPUBLISH_MAX_CORE_REQUIRED')=='1':
    importlib.import_module('social_operations.worker')
else:
    pytest.importorskip('social_operations.worker',exc_type=ModuleNotFoundError)
from adapters.max import queue
from adapters.max.profile import MaxBlocked
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('proof',['click','correlation','none','ambiguous','changed'])
async def test_reschedule_recovery_exact_native_replacement(monkeypatch,proof):
    state=dict(target='target',existing_id='old',text='Exact',scheduled_at='2026-09-09T09:30:00Z',
        media_slots=0,observed_media=[],entities=[])
    if proof=='click':state['transition']=dict(clicks=1,blocked=False)
    if proof=='correlation':state['old_correlation_id']='correlation'
    if proof=='changed':state['transition']=dict(clicks=1,blocked=False)
    row=dict(id='new',text='Exact',time_ms=1788946200000,media_count=0)
    # timestamp is derived from the immutable request, never a positional DOM ID.
    from datetime import datetime
    row['time_ms']=int(datetime.fromisoformat(state['scheduled_at'].replace('Z','+00:00')).timestamp()*1000)
    current=dict(id='new',text='Exact',scheduled_at=state['scheduled_at'],observed_media=[],entities=[],correlation_id='correlation')
    async def noop(*a,**kw):pass
    driver=SimpleNamespace(page=SimpleNamespace(goto=noop),origin='https://invalid.test',evidence_pages=(),_account=noop,_scope=noop)
    class Observer:
        def __init__(self,*a):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
    async def rows(*a):return [row,row] if proof=='ambiguous' else [row]
    async def item(*a):return dict(current)
    calls=[]
    async def read(*a,**kw):
        calls.append((a[2],kw))
        return [dict(current,text='other') if proof=='changed' else dict(current)]
    monkeypatch.setattr(queue,'QueueObserver',Observer);monkeypatch.setattr(queue,'open_queue',rows)
    monkeypatch.setattr(queue,'item',item);monkeypatch.setattr(queue,'read',read)
    if proof in {'none','ambiguous','changed'}:
        with pytest.raises(MaxBlocked):await queue.rescheduled_item(driver,state)
    else:
        result=await queue.rescheduled_item(driver,state)
        assert result['id']=='new' and calls==[('new',{'passes':1})]
        assert state['replacement_evidence']==('stable_native_correlation' if proof=='correlation' else 'trusted_ui_native_queue_replacement')
