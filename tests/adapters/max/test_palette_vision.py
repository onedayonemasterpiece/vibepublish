"""Palette proposals use the actual quota gateway contract, never mutation proof."""
import json
from unittest.mock import AsyncMock
import pytest
from adapters.max.visual import VisualReactionPalette,visual_gateway,MODEL
from adapters.max.profile import MaxBlocked

PNG=b'\x89PNG\r\n\x1a\nminimal-mocked-capture'
CELLS=[dict(x=0,y=0,width=40,height=40)]

def setup(monkeypatch,answer):
    client=visual_gateway(supabase_client=object())
    generate=AsyncMock(return_value=(json.dumps(answer),None))
    monkeypatch.setattr(client,'generate_content_async',generate)
    record=AsyncMock();return VisualReactionPalette(client,record=record),generate,record

@pytest.mark.asyncio
async def test_palette_capture_and_proposal_are_durable_supplementary_only(monkeypatch):
    v,g,r=setup(monkeypatch,{'certain':True,'index':0})
    result=await v.identify(PNG,reaction='👍',cells=CELLS)
    assert result['index']==0 and result['supplementary_only']
    assert r.await_count==2 and r.call_args_list[0].args[1]['phase']=='captured'
    assert g.call_args.kwargs['model']==MODEL
    assert g.call_args.kwargs['prompt'][1]['inline_data']['data']==PNG

@pytest.mark.asyncio
@pytest.mark.parametrize('answer',[{'certain':True,'index':True},{'certain':True,'index':1},
    {'certain':False,'index':0},{'certain':'yes','index':0},{'certain':True,'index':0,'click':True}])
async def test_palette_rejects_unbounded_or_instruction_shaped_proposals(monkeypatch,answer):
    v,g,r=setup(monkeypatch,answer)
    with pytest.raises(MaxBlocked,match='invalid_response'):await v.identify(PNG,reaction='👍',cells=CELLS)
    assert r.await_count==1

@pytest.mark.asyncio
async def test_palette_ambiguity_never_authorizes_click(monkeypatch):
    v,g,r=setup(monkeypatch,{'certain':False,'index':None})
    with pytest.raises(MaxBlocked,match='unconfirmed'):await v.identify(PNG,reaction='👍',cells=CELLS)
    assert r.await_count==2

@pytest.mark.asyncio
async def test_capture_disk_failure_prevents_paid_call(monkeypatch):
    v,g,r=setup(monkeypatch,{'certain':True,'index':0});r.side_effect=OSError('disk')
    with pytest.raises(OSError):await v.identify(PNG,reaction='👍',cells=CELLS)
    g.assert_not_awaited()

@pytest.mark.asyncio
async def test_palette_rejects_limiter_bypass(monkeypatch):
    v,g,r=setup(monkeypatch,{'certain':True,'index':0});v.client.allow_local_limiter_fallback=True
    with pytest.raises(MaxBlocked,match='shared_limiter'):await v.identify(PNG,reaction='👍',cells=CELLS)
    g.assert_not_awaited();r.assert_not_awaited()
