import json
from pathlib import Path
import pytest
from adapters.max.evidence import structure_only
from adapters.max.live import Target
from adapters.max.live_session import existing_session, private_json
from adapters.max.profile import MaxBlocked

@pytest.mark.parametrize('identifier',['0','-0','-01','1','../-1','-1?target=-2','-1/evil','-1#queue'])
def test_native_id_not_an_arbitrary_route(identifier):
    with pytest.raises(MaxBlocked): Target(identifier,'alias','test_group')

@pytest.mark.asyncio
async def test_ordinary_call_cannot_enable_live(tmp_path):
    with pytest.raises(MaxBlocked,match='explicit_live_required'):
        async with existing_session(profile=tmp_path,executable='not-executed',allowlist=tmp_path/'missing'):
            pytest.fail('must not launch')

@pytest.mark.asyncio
async def test_live_factory_is_not_onboarding(tmp_path):
    with pytest.raises(MaxBlocked,match='existing_profile_required'):
        async with existing_session(profile=tmp_path,executable='not-executed',allowlist=tmp_path/'missing',explicit_live=True):
            pytest.fail('must not launch')

@pytest.mark.parametrize('mode',[0o644,0o640,0o666])
def test_binding_must_be_private(tmp_path,mode):
    p=tmp_path/'binding';p.write_text('{}');p.chmod(mode)
    with pytest.raises(MaxBlocked,match='permissions'): private_json(p)

def test_symlink_binding_not_followed(tmp_path):
    p=tmp_path/'original';p.write_text('{}');p.chmod(0o600)
    link=tmp_path/'link';link.symlink_to(p)
    with pytest.raises(MaxBlocked,match='path'): private_json(link)

@pytest.mark.asyncio
async def test_busy_bridge_owner_not_overridden(tmp_path):
    profile=tmp_path/'profile';profile.mkdir(mode=0o700);(profile/'Default').mkdir()
    lock=profile/'.my-browser-bridge.lock';lock.write_text('foreign-owner')
    binding=tmp_path/'binding';binding.write_text(json.dumps({'account_phone':'synthetic-account','targets':{}}));binding.chmod(0o600)
    with pytest.raises(MaxBlocked,match='browser_owner_busy'):
        async with existing_session(profile=profile,executable='never-run',allowlist=binding,explicit_live=True):
            pytest.fail('must not launch')
    assert lock.read_text()=='foreign-owner'

@pytest.mark.parametrize('where',[
 '<span>{s}</span>','<img src="https://private/{s}">','<div class="{s}" data-id="{s}">{s}</div>',
 '<script>localStorage.token="{s}"</script>','<style>/* {s} */</style>',
 '<input value="{s}" placeholder="{s}" aria-label="{s}">','<!-- {s} -->',
 '<button onclick="send(\'{s}\')" style="background:url({s})">{s}</button>'
])
def test_export_drops_artificial_secrets(where):
    sentinel='SECRET_SENTINEL_94721'
    out=structure_only(where.format(s=sentinel))
    assert sentinel not in out
    assert all(x not in out for x in ('localStorage','onclick','https://','src=','value=','data-id='))

def test_export_preserves_only_observed_selector_semantics():
    out=structure_only('<main aria-labelledby="main-header-title"><button aria-label="Открыть отложенные сообщения">PRIVATE NAME</button><span class="name secret">PRIVATE PHONE</span></main>')
    assert out=='<main aria-labelledby="main-header-title"><button aria-label="Открыть отложенные сообщения"></button><span class="name"></span></main>'

@pytest.mark.asyncio
async def test_symlink_default_profile_is_not_reused(tmp_path):
    (tmp_path/'other').mkdir();(tmp_path/'Default').symlink_to(tmp_path/'other')
    with pytest.raises(MaxBlocked,match='existing_profile_required'):
        async with existing_session(profile=tmp_path,executable='never-run',allowlist=tmp_path/'missing',explicit_live=True):
            pytest.fail('must not launch')
