"""Native MAX social helpers. UI effects only; no auth, ledger, or dispatch owner."""
from __future__ import annotations
import asyncio
import json
from playwright.async_api import expect
from .profile import MaxBlocked
from .wire import HistoryObserver,published_wire_id


async def observe(driver,target,native_id):
    """Exact copied reference plus correlated native relationship/own reaction."""
    await driver.open(target)
    async with HistoryObserver(driver.page,target,driver.origin,pages=driver.evidence_pages) as history:
        item=(await driver.read(target,'feed',native_item=native_id))[0]
        rows=await history.wait(min(driver.timeout,25))
        exact=[row for row in rows if row['id']==published_wire_id(item['id'])]
        if len(exact)!=1 or exact[0]['text']!=item['text']:
            raise MaxBlocked('native_social_identity_unverified')
        if 'own_reactions' not in exact[0]:raise MaxBlocked('native_own_reactions_unobserved')
        return dict(item,own_reactions=exact[0]['own_reactions'],own_reactions_observed=True,
            native_link=exact[0]['link'])


def same_content(actual,expected):
    return all(actual.get(k)==expected.get(k) for k in ('id','target','text','entities','observed_media','scheduled_at'))


def desired(item,reaction,mode):
    return item.get('own_reactions_observed') is True and ((reaction in item['own_reactions'])==(mode=='add'))


async def react(driver,*,existing,reaction,reaction_mode,attempt_id,plan_digest,hooks):
    if reaction_mode not in {'add','remove'} or not isinstance(reaction,str) or not 0<len(reaction)<=100:
        raise MaxBlocked('invalid_reaction_intent')
    if driver.visual_palette is None:raise MaxBlocked('native_canvas_palette_classifier_required')
    target=existing['target'];driver.lane.assert_clear()
    before=await observe(driver,target,existing['id'])
    if not same_content(before,existing):raise MaxBlocked('reaction_source_changed')
    if desired(before,reaction,reaction_mode):raise MaxBlocked('reaction_already_in_requested_state')
    driver._enter(target);guard=None;armed=False
    try:
        async with asyncio.timeout(driver.timeout):
            await driver._account();main=await driver._scope(target)
            row=driver._rows(main,before['text'],outgoing=True)
            if await driver._copy_native_reference(row,target)!=(before['url'],before['id']):
                raise MaxBlocked('reaction_native_reference_changed')
            await driver._open_message_menu(row)
            palette=driver.page.get_by_role('menu').locator('..').locator('.reactionsSlot .reactions')
            buttons=palette.locator('button.reaction')
            await buttons.first.wait_for()
            # The observed compact palette has unlabeled canvas cells, not emoji
            # aria labels. Classify only that cropped palette, never the message.
            handles=await buttons.element_handles()
            # The container can be stable while Svelte's staggered cell
            # animations are still running. Wait on every actual input cell.
            for handle in handles:
                await handle.wait_for_element_state('visible')
                await handle.wait_for_element_state('stable')
            png=await palette.screenshot(type='png',animations='disabled')
            cells=await palette.evaluate('''e=>{const r=e.getBoundingClientRect();return [...e.querySelectorAll('button.reaction')].map(b=>{const q=b.getBoundingClientRect();return {x:q.x-r.x,y:q.y-r.y,width:q.width,height:q.height};});}''')
            proposal=await driver.visual_palette.identify(png,reaction=reaction,cells=cells)
            if len(handles)!=len(cells):raise MaxBlocked('reaction_palette_changed')
            if not await palette.evaluate('(p,old)=>{const now=[...p.querySelectorAll("button.reaction")];return now.length===old.length && now.every((b,i)=>b===old[i]);}',handles):
                raise MaxBlocked('reaction_palette_changed')
            button=handles[proposal['index']];source=await row.element_handle();panel=await palette.element_handle()
            guard=await driver.page.evaluate_handle('''([button,row,palette,route,text,header])=>{
                const state={clicks:0,blocked:false};
                const children=[...palette.querySelectorAll('button.reaction')];
                const guard=e=>{if(!button.contains(e.target))return;
                    const current=[...palette.querySelectorAll('button.reaction')];
                    if(!e.isTrusted || !button.isConnected || !row.isConnected || !palette.isConnected ||
                        location.href!==route || row.querySelector('.bubbleContent > .text')?.textContent!==text ||
                        !document.querySelector('main button[aria-label="'+header+'"]') ||
                        current.length!==children.length || current.some((b,i)=>b!==children[i]) || state.clicks){
                        state.blocked=true;e.preventDefault();e.stopImmediatePropagation();return;
                    }state.clicks++;
                };document.addEventListener('click',guard,true);
                return {state,stop:()=>document.removeEventListener('click',guard,true)};
            }''',[button,source,panel,driver.origin+'/'+target,before['text'],'Открыть профиль '+driver.targets[target].alias])
            state=dict(target=target,text=before['text'],entities=before.get('entities',[]),kind='feed',action='react',
                scheduled_at=None,existing_id=before['id'],native_id=before['id'],recovery_reference=before['url'],
                media=before['media'],media_slots=len(before.get('observed_media',[])) or len(before['media']),
                observed_media=before.get('observed_media',[]),attempt_id=attempt_id,plan_digest=plan_digest,
                reaction=reaction,reaction_mode=reaction_mode,baseline=before,palette_proposal=proposal)
            await hooks.checkpoint('MAX_REACTION_PREPARED',json.dumps(state))
            driver.lane.arm(attempt_id,plan_digest);armed=True
            await hooks.before_effect(attempt_id,plan_digest)
            await driver._account()
            driver._check_attempt_fuse(attempt_id,plan_digest);await driver._scope(target)
            await button.click()
            transition=await guard.evaluate('g=>g.state')
            if transition!=dict(clicks=1,blocked=False):raise MaxBlocked('reaction_input_unverified')
            state['transition']=transition
            await hooks.checkpoint('MAX_REACTION_CLICKED',json.dumps(state))
            await guard.evaluate('g=>g.stop()');await guard.dispose();guard=None
            driver._busy=False
            fresh=await observe(driver,target,before['id'])
            if not same_content(fresh,before) or not desired(fresh,reaction,reaction_mode):
                raise MaxBlocked('native_reaction_readback_mismatch')
            driver._check_attempt_fuse(attempt_id,plan_digest)
            state['item']=fresh
            await hooks.checkpoint('MAX_REACTION_OBSERVED',json.dumps(state))
            return [fresh]
    except BaseException as exc:
        if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
        if armed:raise MaxBlocked('outcome_unknown') from None
        raise
    finally:
        if guard is not None:
            try:await guard.evaluate('g=>g.stop()');await guard.dispose()
            except Exception:pass
        driver._busy=False


async def reconcile_reaction(driver,state):
    driver._check_attempt_fuse(state['attempt_id'],state['plan_digest'])
    before=state.get('baseline')
    if not isinstance(before,dict) or desired(before,state['reaction'],state['reaction_mode']):
        raise MaxBlocked('reaction_baseline_unverified')
    fresh=await observe(driver,state['target'],state['existing_id'])
    if not same_content(fresh,before) or not desired(fresh,state['reaction'],state['reaction_mode']):
        raise MaxBlocked('native_reaction_readback_mismatch')
    driver._check_attempt_fuse(state['attempt_id'],state['plan_digest'])
    return dict(item=fresh,quarantine_released=False)
