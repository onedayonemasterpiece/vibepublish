"""Native MAX social helpers. UI effects only; no auth, ledger, or dispatch owner."""
from __future__ import annotations
import asyncio
import json
from playwright.async_api import expect
from .profile import MaxBlocked
from . import rich
from .wire import HistoryObserver,published_wire_id


async def observe(driver,target,native_id):
    """Exact copied reference plus correlated native relationship/own reaction."""
    if driver.page.url!=driver.origin+'/'+target:await driver.open(target)
    async with HistoryObserver(driver.page,target,driver.origin,pages=driver.evidence_pages) as history:
        item=(await driver.read(target,'feed',native_item=native_id))[0]
        rows=await history.wait(min(driver.timeout,25))
        exact=[row for row in rows if row['id']==published_wire_id(item['id'])]
        if len(exact)!=1 or exact[0]['text']!=item['text']:
            raise MaxBlocked('native_social_identity_unverified')
        if 'own_reactions' not in exact[0]:raise MaxBlocked('native_own_reactions_unobserved')
        return dict(item,own_reactions=exact[0]['own_reactions'],own_reactions_observed=True,
            native_link=exact[0]['link'],history_ids=[row['id'] for row in rows])


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
            if await row.count()!=1:row=await driver._find_native_row(main,before['text'],before['id'])
            source=await row.element_handle()
            if await driver._copy_native_reference(source,target)!=(before['url'],before['id']):
                raise MaxBlocked('reaction_native_reference_changed')
            source_snapshot=await source.evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e.querySelector(".bubbleContent > .text")));}')
            source_media=await source.evaluate('e=>JSON.stringify([...e.querySelectorAll(".media img,.media video source")].map(e=>e.currentSrc||e.src))')
            await driver._open_message_menu(source)
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
            button=handles[proposal['index']];panel=await palette.element_handle()
            guard=await driver.page.evaluate_handle('''([button,row,palette,route,text,header,snapshot,media])=>{''' + rich.SNAPSHOT_JS + '''
                const state={clicks:0,blocked:false};
                const children=[...palette.querySelectorAll('button.reaction')];
                const guard=e=>{if(!button.contains(e.target))return;
                    const current=[...palette.querySelectorAll('button.reaction')];
                    if(!e.isTrusted || !button.isConnected || !row.isConnected || !palette.isConnected ||
                        location.href!==route || semanticText(row.querySelector('.bubbleContent > .text'))!==text ||
                        JSON.stringify(semanticSnapshot(row.querySelector('.bubbleContent > .text')))!==snapshot ||
                        JSON.stringify([...row.querySelectorAll('.media img,.media video source')].map(e=>e.currentSrc||e.src))!==media ||
                        ![...document.querySelectorAll('main button')].some(b=>b.getAttribute('aria-label')===header) ||
                        current.length!==children.length || current.some((b,i)=>b!==children[i]) || state.clicks){
                        state.blocked=true;e.preventDefault();e.stopImmediatePropagation();return;
                    }state.clicks++;
                };document.addEventListener('click',guard,true);
                return {state,stop:()=>document.removeEventListener('click',guard,true)};
            }''',[button,source,panel,driver.origin+'/'+target,before['text'],'Открыть профиль '+driver.targets[target].alias,source_snapshot,source_media])
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


async def verify_reply(driver,item,subject):
    fresh=await observe(driver,item['target'],item['id'])
    link=fresh.get('native_link') or {}
    message=link.get('message') or {}
    if (link.get('type')!='REPLY' or not isinstance(message,dict)
            or str(message.get('id'))!=published_wire_id(subject['id'])
            or fresh['id']==subject['id'] or not same_content(fresh,item)):
        raise MaxBlocked('native_reply_relationship_unverified')
    return dict(fresh,reply_to_native_id=subject['id'])


def forward_link_matches(link,subject):
    if not isinstance(link,dict) or link.get('type')!='FORWARD':return False
    message=link.get('message')
    return (isinstance(message,dict) and str(message.get('id'))==published_wire_id(subject['id'])
        and (link.get('chatId') is None or str(link['chatId'])==subject['target']))


async def forward_candidate(driver,state):
    target=state['target'];subject=state['subject']
    await driver.open(target)
    async with HistoryObserver(driver.page,target,driver.origin,pages=driver.evidence_pages) as history:
        await driver.page.reload();main=await driver._scope(target)
        await driver._rows(main,subject['text'],outgoing=True).last.wait_for()
        rows=await history.wait(min(driver.timeout,25))
        candidates=[r for r in rows if r['id'] not in state['baseline_ids'] and r['text']==subject['text']
            and forward_link_matches(r['link'],subject)]
        if len(candidates)!=1:raise MaxBlocked('native_forward_candidate_unverified')
        native=candidates[0]['id']
        possible=driver._rows(main,subject['text'],outgoing=True)
        handles=await possible.element_handles()
        if not 1<=len(handles)<=100:raise MaxBlocked('bounded_forward_candidates')
        for handle in handles:
            reference,copied=await driver._copy_native_reference(handle,target)
            if published_wire_id(copied)!=native:continue
            # Binding comes from native identity, never position/text alone.
            index=await possible.evaluate_all('(es,h)=>es.indexOf(h)',handle)
            if index<0:raise MaxBlocked('native_row_detached')
            row=possible.nth(index)
            if not await row.evaluate('(e,h)=>e===h',handle):raise MaxBlocked('native_row_reordered')
            item=await driver._plain_candidate(target,subject['text'],row,
                media_count=len(subject.get('observed_media',[])) or len(subject['media']))
            if item['url']!=reference or item['id']!=copied:raise MaxBlocked('native_forward_changed')
            if any(item.get(k)!=subject.get(k) for k in ('text','entities','observed_media')):
                raise MaxBlocked('native_forward_content_changed')
            return dict(item,origin=subject['url'],forward_origin_matched=True)
    raise MaxBlocked('native_forward_reference_unobserved')


async def forward(driver,*,subject,target,attempt_id,plan_digest,hooks):
    if subject['target']!=target or driver.targets[target].policy!='test_group':
        raise MaxBlocked('native_forward_target_recipe_unqualified')
    driver.lane.assert_clear()
    before=await observe(driver,target,subject['id'])
    if not same_content(before,subject):raise MaxBlocked('forward_source_changed')
    # Reuse that same fresh, exact source read's native set, not a redundant
    # second full read. This is still not a complete-history assertion.
    baseline=before.get('history_ids')
    if not isinstance(baseline,list) or published_wire_id(subject['id']) not in baseline:
        raise MaxBlocked('native_forward_baseline_unverified')
    driver._enter(target);guard=None;armed=False
    try:
        async with asyncio.timeout(driver.timeout):
            await driver._account();main=await driver._scope(target)
            row=await driver._find_native_row(main,subject['text'],subject['id'])
            handle=await row.element_handle()
            if await driver._copy_native_reference(handle,target)!=(subject['url'],subject['id']):
                raise MaxBlocked('forward_source_reference_changed')
            baseline_count=await driver._rows(main,subject['text'],outgoing=True).count()
            await driver._open_message_menu(handle)
            await driver.page.get_by_role('menu').get_by_role('menuitem',name='Переслать',exact=True).click()
            dialog=driver.page.get_by_role('dialog')
            await expect(dialog).to_have_count(1)
            option=dialog.get_by_role('option').filter(has=driver.page.get_by_text(driver.targets[target].alias,exact=True))
            await expect(option).to_have_count(1)
            await option.click();await expect(option).to_have_attribute('aria-selected','true')
            selected=dialog.locator('[role=option][aria-selected=true]')
            await expect(selected).to_have_count(1)
            recipient=await option.element_handle()
            guard=await dialog.evaluate_handle('''(dialog,x)=>{''' + rich.SNAPSHOT_JS + '''
                const state={clicks:0,blocked:false};
                const guard=e=>{const send=e.target.closest('button[aria-label="Отправить сообщение"]');if(!send)return;
                    const selected=[...dialog.querySelectorAll('[role=option][aria-selected=true]')];
                    if(!e.isTrusted || !dialog.contains(send) || !dialog.isConnected || !x.source.isConnected ||
                       location.href!==x.route || selected.length!==1 || selected[0]!==x.recipient ||
                       x.recipient.querySelector('.name .text')?.textContent!==x.alias ||
                       semanticText(x.source.querySelector('.bubbleContent > .text'))!==x.text ||
                       JSON.stringify(semanticSnapshot(x.source.querySelector('.bubbleContent > .text')))!==x.snapshot ||
                       JSON.stringify([...x.source.querySelectorAll('.media img,.media video source')].map(e=>e.currentSrc||e.src))!==x.media || state.clicks){
                        state.blocked=true;e.preventDefault();e.stopImmediatePropagation();return;
                    }state.clicks++;
                };document.addEventListener('click',guard,true);
                return {state,stop:()=>document.removeEventListener('click',guard,true)};
            }''',dict(source=handle,recipient=recipient,route=driver.origin+'/'+target,alias=driver.targets[target].alias,text=subject['text'],
                snapshot=await handle.evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e.querySelector(".bubbleContent > .text")));}'),
                media=await handle.evaluate('e=>JSON.stringify([...e.querySelectorAll(".media img,.media video source")].map(e=>e.currentSrc||e.src))')))
            state=dict(target=target,text=subject['text'],entities=subject.get('entities',[]),kind='feed',action='forward',
                scheduled_at=None,existing_id=None,media=subject['media'],media_slots=len(subject.get('observed_media',[])) or len(subject['media']),
                subject=subject,baseline_ids=baseline,attempt_id=attempt_id,plan_digest=plan_digest)
            await hooks.checkpoint('MAX_FORWARD_PREPARED',json.dumps(state))
            driver.lane.arm(attempt_id,plan_digest);armed=True
            await hooks.before_effect(attempt_id,plan_digest)
            await driver._account();driver._check_attempt_fuse(attempt_id,plan_digest);await driver._scope(target)
            await dialog.get_by_role('button',name='Отправить сообщение',exact=True).click()
            transition=await guard.evaluate('g=>g.state')
            if transition!=dict(clicks=1,blocked=False):raise MaxBlocked('forward_input_unverified')
            state['transition']=transition
            await expect(driver._rows(main,subject['text'],outgoing=True)).to_have_count(baseline_count+1,timeout=driver.timeout*1000)
            await hooks.checkpoint('MAX_FORWARD_CLICKED',json.dumps(state))
            await guard.evaluate('g=>g.stop()');await guard.dispose();guard=None;driver._busy=False
            first=await forward_candidate(driver,state)
            state.update(native_id=first['id'],recovery_reference=first['url'],observed_media=first.get('observed_media',[]))
            await hooks.checkpoint('MAX_FORWARD_REFERENCE',json.dumps(state))
            final=await forward_candidate(driver,state)
            if not same_content(first,final):raise MaxBlocked('native_forward_changed')
            state['item']=final
            await hooks.checkpoint('MAX_FORWARD_OBSERVED',json.dumps(state))
            return [final]
    except BaseException as exc:
        if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
        if armed:raise MaxBlocked('outcome_unknown') from None
        raise
    finally:
        if guard is not None:
            try:await guard.evaluate('g=>g.stop()');await guard.dispose()
            except Exception:pass
        driver._busy=False
