"""Native scheduled UI helpers for RealMaxDriver (not another adapter/driver)."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from playwright.async_api import expect
from . import rich
from .profile import MaxBlocked
from .wire import QueueObserver

MOSCOW=ZoneInfo('Europe/Moscow')


def instant(milliseconds):
    return datetime.fromtimestamp(milliseconds/1000,timezone.utc).isoformat().replace("+00:00","Z")


async def open_queue(driver,target,observer):
    main=await driver._scope(target)
    control=main.get_by_role('button',name='Открыть отложенные сообщения',exact=True)
    await expect(control).to_have_count(1,timeout=driver.timeout*1000)
    await driver.page.bring_to_front()
    await control.click()
    await driver._scope(target,'scheduled')
    return await observer.wait(driver.timeout)


async def item(driver,target,native,main):
    if native['status'] not in (None,'EDITED'):
        raise MaxBlocked('native_schedule_status_unqualified')
    row=driver._rows(main,native['text'])
    await expect(row).to_have_count(1,timeout=driver.timeout*1000)
    await row.scroll_into_view_if_needed()
    styled=await rich.capture(row.locator('.bubbleContent > .text'))
    if styled['text']!=native['text']:raise MaxBlocked('native_queue_content_changed')
    expected=datetime.fromtimestamp(native['time_ms']/1000,MOSCOW).strftime('%H:%M')
    shown=(await row.locator('.meta .text').inner_text()).strip()
    if shown!=expected:raise MaxBlocked('native_queue_time_changed')
    count=native['media_count']
    await expect(row.locator('[aria-label="Прикрепленные фото"] > button')).to_have_count(count,timeout=driver.timeout*1000)
    downloaded=await driver._download_media(row,target,count,namespace='scheduled') if count else []
    await driver._scope(target,'scheduled')
    if (await rich.capture(row.locator('.bubbleContent > .text')))!=styled:
        raise MaxBlocked('native_queue_content_changed')
    return dict(id=native['id'],url=None,target=target,namespace='scheduled',
        text=native['text'],entities=styled['entities'],media=[],observed_media=downloaded,correlation_id=native.get('correlation_id'),
        scheduled_at=instant(native['time_ms']),observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00","Z"))


async def read(driver,target,native_item=None,*,passes=2):
    # Independent page loads and independent queue replies bind the same native
    # object. Positional DOM indexes never supply identity, time or pagination.
    observations=[]
    for _ in range(passes):
        async with QueueObserver(driver.page,target,driver.origin,driver.evidence_pages) as observer:
            await driver._account()
            await driver.page.goto(driver.origin+'/'+target,wait_until='domcontentloaded')
            natives=await open_queue(driver,target,observer)
            if native_item is not None:natives=[x for x in natives if x['id']==native_item]
            if native_item is not None and len(natives)!=1:raise MaxBlocked('native_scheduled_item_not_found')
            main=await driver._scope(target,'scheduled')
            result=[await item(driver,target,n,main) for n in natives]
            await driver._account();await driver._scope(target,'scheduled')
            observations.append(result)
    def evidence(rows):return [{k:v for k,v in r.items() if k!='observed_at'} for r in rows]
    if any(evidence(rows)!=evidence(observations[0]) for rows in observations[1:]):raise MaxBlocked('native_queue_changed')
    return observations[-1]


async def set_time(driver,scheduled_at):
    """Observed calendar/day and accessible spinbuttons; never editor internals."""
    import re
    wanted=datetime.fromisoformat(scheduled_at.replace('Z','+00:00')).astimezone(MOSCOW)
    if wanted.second or wanted.microsecond:raise MaxBlocked('native_schedule_minute_precision')
    dialog=driver.page.get_by_role('dialog')
    await expect(dialog).to_have_count(1)
    months=('январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь')
    desired=f'{months[wanted.month-1]} {wanted.year}'
    title=dialog.locator('.calendar .header .title')
    for _ in range(13):
        current=' '.join((await title.inner_text()).lower().split())
        if current==desired:break
        match=re.fullmatch(r'([^ ]+) ([0-9]{4})',current)
        if not match or match[1] not in months:raise MaxBlocked('native_calendar_unfamiliar')
        old=int(match[2])*12+months.index(match[1]);new=wanted.year*12+wanted.month-1
        await dialog.get_by_role('button',name='Следующий месяц' if new>old else 'Предыдущий месяц',exact=True).click()
    else:raise MaxBlocked('native_calendar_horizon')
    day=dialog.locator('.days > button.day:not(.day--otherMonth)').filter(has_text=re.compile('^'+str(wanted.day)+'$'))
    await expect(day).to_have_count(1);await day.click()
    for label,value,modulus in [('Часы',wanted.hour,24),('Минуты',wanted.minute,60)]:
        spin=dialog.get_by_role('spinbutton',name=label,exact=True)
        current=int(await spin.get_attribute('aria-valuenow'))
        forward=(value-current)%modulus;backward=(current-value)%modulus
        direction=1 if forward<=backward else -1
        for _ in range(min(forward,backward)):
            await spin.press('ArrowUp' if direction==1 else 'ArrowDown')
            current=(current+direction)%modulus
            await expect(spin).to_have_attribute('aria-valuenow',str(current))
        await expect(spin).to_have_attribute('aria-valuenow',str(value))
    await expect(dialog.locator('.days > button.day--selected')).to_have_text(str(wanted.day))
    return dialog,dict(month=desired,day=str(wanted.day),hour=str(wanted.hour),minute=str(wanted.minute))


async def publish(driver,*,target,text,media,entities,scheduled_at,attempt_id,plan_digest,hooks):
    import asyncio,json,hashlib,re
    from .live import COMPOSER
    driver._enter(target);armed=False;guard=None
    try:
        driver.lane.assert_clear()
        async with asyncio.timeout(driver.timeout):
            await driver._account()
            # Read the current native queue before composing. A fresh empty queue
            # surface has no entry control; never treat a missing native ITEM as
            # evidence of deletion or cancellation.
            async with QueueObserver(driver.page,target,driver.origin,driver.evidence_pages) as observer:
                await driver.page.goto(driver.origin+'/'+target,wait_until='domcontentloaded')
                main=await driver._scope(target)
                await expect(main.locator(COMPOSER)).to_have_count(1)
                await main.locator('.messageWrapper').first.wait_for(timeout=driver.timeout*1000)
                if await main.get_by_role('button',name='Открыть отложенные сообщения',exact=True).count():
                    baseline=await open_queue(driver,target,observer)
                    await driver.page.goto(driver.origin+'/'+target,wait_until='domcontentloaded')
                    main=await driver._scope(target)
                else:baseline=[]
            when=int(datetime.fromisoformat(scheduled_at.replace('Z','+00:00')).timestamp()*1000)
            if any(x['text']==text and x['time_ms']==when for x in baseline):raise MaxBlocked('preexisting_scheduled_candidate')
            composer,previews=await driver._compose(main,text,media,entities)
            await main.get_by_role('button',name='Отправить сообщение',exact=True).click(button='right')
            await driver.page.get_by_role('menu').get_by_role('menuitem',name='Отправить позже',exact=True).click()
            dialog,date=await set_time(driver,scheduled_at)
            confirm=dialog.get_by_role('button',name=re.compile(r'^Отправить .+ в '+datetime.fromtimestamp(when/1000,MOSCOW).strftime('%H:%M')+'$'))
            await expect(confirm).to_have_count(1)
            guard=await confirm.evaluate_handle('(button,x)=>{'+rich.SNAPSHOT_JS+r'''
                let clicks=0,blocked=false;
                const ready=()=>{
                    const dialog=button.closest('dialog,[role="dialog"]'),editor=document.querySelector(x.composer);
                    return button.isConnected&&location.href===x.route&&dialog&&editor&&
                        semanticText(editor)===x.text&&JSON.stringify(semanticSnapshot(editor))===x.snapshot&&
                        JSON.stringify([...editor.closest('main').querySelectorAll('.attaches .attach img')].map(e=>({src:e.src,name:e.alt})))===JSON.stringify(x.previews)&&
                        dialog.querySelector('.calendar .header .title')?.textContent.trim().toLowerCase().replace(/\s+/g,' ')===x.date.month&&
                        dialog.querySelector('.days > button.day--selected')?.textContent.trim()===x.date.day&&
                        dialog.querySelector('[role="spinbutton"][aria-label="Часы"]')?.getAttribute('aria-valuenow')===x.date.hour&&
                        dialog.querySelector('[role="spinbutton"][aria-label="Минуты"]')?.getAttribute('aria-valuenow')===x.date.minute&&
                        JSON.stringify([...document.querySelectorAll('main .attaches .attach img')].map(e=>({src:e.src,name:e.alt})))===JSON.stringify(x.previews);
                };
                const check=e=>{if(!button.contains(e.target))return;
                    if(!e.isTrusted||clicks||!ready()){blocked=true;e.preventDefault();e.stopImmediatePropagation();return;}clicks++;};
                document.addEventListener('click',check,true);
                return {ready:()=>ready()&&!clicks&&!blocked,result:()=>({clicks,blocked}),stop:()=>document.removeEventListener('click',check,true)};
            }''',dict(composer=COMPOSER,text=text,snapshot=await composer.evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e));}'),date=date,previews=previews,route=driver.origin+'/'+target))
            state=dict(recipe='max-native-schedule-v1',target=target,text=text,entities=list(entities),kind='scheduled',action='publish',
                media=[None]*len(media),media_slots=len(media),source_hashes=[hashlib.sha256(m['buffer']).hexdigest() for m in media],
                scheduled_at=scheduled_at,existing_id=None,attempt_id=attempt_id,plan_digest=plan_digest,
                baseline_native_ids=[x['id'] for x in baseline],upload_previews=previews)
            if not await guard.evaluate('(g)=>g.ready()'):raise MaxBlocked('native_schedule_form_changed')
            await hooks.checkpoint('MAX_PREPARED',json.dumps(state))
            await hooks.emit_progress('submitting','running','{}')
            await driver._account();await driver._scope(target)
            driver.lane.arm(attempt_id,plan_digest);armed=True
            await hooks.before_effect(attempt_id,plan_digest)
            await driver._account();driver._check_attempt_fuse(attempt_id,plan_digest)
            if not await guard.evaluate('(g)=>g.ready()'):raise MaxBlocked('native_schedule_form_changed')
            await confirm.click()
            transition=await guard.evaluate('(g)=>g.result()')
            if transition!=dict(clicks=1,blocked=False):raise MaxBlocked('native_schedule_click_unverified')
            state['transition']=transition
            await hooks.checkpoint('MAX_SUBMIT_CONFIRMED',json.dumps(state))
            await guard.evaluate('(g)=>g.stop()');await guard.dispose();guard=None
            # A fresh native reply, not a composer/toast, supplies identity/time.
            async with QueueObserver(driver.page,target,driver.origin,driver.evidence_pages) as observer:
                await driver.page.goto(driver.origin+'/'+target,wait_until='domcontentloaded')
                natives=await open_queue(driver,target,observer)
                matches=[x for x in natives if x['id'] not in state['baseline_native_ids'] and x['text']==text and x['time_ms']==when and x['media_count']==len(media)]
                if len(matches)!=1:raise MaxBlocked('native_schedule_identity_ambiguous')
                state['native_id']=matches[0]['id']
                await hooks.checkpoint('MAX_NATIVE_REFERENCE',json.dumps(state))
                result=await item(driver,target,matches[0],await driver._scope(target,'scheduled'))
            state.update(media=result['media'],observed_media=result['observed_media'])
            await hooks.checkpoint('MAX_NATIVE_REFERENCE',json.dumps(state))
            fresh=(await read(driver,target,state['native_id']))[0]
            if any(fresh[k]!=result[k] for k in ('id','text','entities','scheduled_at','observed_media')):raise MaxBlocked('native_schedule_readback_changed')
            driver._check_attempt_fuse(attempt_id,plan_digest)
            await hooks.checkpoint('MAX_CANDIDATE_OBSERVED',json.dumps(dict(state,item=fresh)))
            return [fresh]
    except BaseException as exc:
        if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
        if armed:raise MaxBlocked('outcome_unknown') from None
        if isinstance(exc,MaxBlocked):raise
        raise MaxBlocked('native_schedule_prepare_unavailable') from None
    finally:
        if guard is not None:
            try:await guard.evaluate('(g)=>g.stop()');await guard.dispose()
            except Exception:pass
        driver._busy=False


async def reconcile(driver,state):
    """Read-only original scheduled attempt: never Save/Send or clear quarantine."""
    import asyncio
    target=state['target'];driver._enter(target)
    try:
        async with asyncio.timeout(driver.timeout):
            driver._check_attempt_fuse(state['attempt_id'],state['plan_digest'])
            if state['action']=='cancel':
                result=await cancelled_item(driver,state)
                driver._check_attempt_fuse(state['attempt_id'],state['plan_digest'])
                return dict(item=result,state=state)
            native=state.get('native_id')
            if native is None:
                async with QueueObserver(driver.page,target,driver.origin,driver.evidence_pages) as observer:
                    await driver._account();await driver.page.goto(driver.origin+'/'+target,wait_until='domcontentloaded')
                    rows=await open_queue(driver,target,observer)
                    when=int(datetime.fromisoformat(state['scheduled_at'].replace('Z','+00:00')).timestamp()*1000)
                    matches=[x for x in rows if x['id'] not in state['baseline_native_ids'] and x['text']==state['text'] and x['time_ms']==when and x['media_count']==state['media_slots']]
                    if len(matches)!=1:raise MaxBlocked('native_schedule_identity_ambiguous')
                    native=matches[0]['id']
            if state['action']=='reschedule':
                result=await rescheduled_item(driver,state)
                native=result['id']
            else:result=(await read(driver,target,native))[0]
            if result['text']!=state['text'] or result['scheduled_at']!=state['scheduled_at'] or not rich.same_entities(result['entities'],state.get('entities',[])):
                raise MaxBlocked('native_schedule_intent_changed')
            if state.get('observed_media') and result['observed_media']!=state['observed_media']:
                raise MaxBlocked('native_schedule_media_changed')
            state=dict(state,native_id=native,media=result['media'],observed_media=result['observed_media'])
            driver._check_attempt_fuse(state['attempt_id'],state['plan_digest'])
            return dict(item=result,state=state)
    finally:driver._busy=False


async def legacy_unreachable_guard(driver,state):
    """Forensic v0 migration, NOT an absence-based generic retry/clear operation.

    The sole unversioned scheduled producer required closest('[role=dialog]')
    before any final click. MAX's actual DIALOG has only an implicit role, so that
    predicate was always false. We re-observe that exact control-flow premise on
    two fresh authorized surfaces. A versioned/new/checkpointed-click/native-ID
    attempt is categorically ineligible. Core cancels intent, preserving dispatch
    history; it does not label this a publication or silently retry it.
    """
    import asyncio
    if (state.get('recipe') is not None or state.get('transition') is not None
            or state.get('native_id') is not None or state.get('existing_id') is not None
            or state.get('action')!='publish' or state.get('kind')!='scheduled'
            or 'baseline_native_ids' not in state or 'upload_previews' not in state
            or datetime.fromisoformat(state['scheduled_at'].replace('Z','+00:00'))<=datetime.now(timezone.utc)
            or driver.targets[state['target']].policy!='test_group'):
        return None
    target=state['target'];driver._enter(target)
    try:
        async with asyncio.timeout(driver.timeout):
            for _ in range(2):
                driver._check_attempt_fuse(state['attempt_id'],state['plan_digest'])
                await driver._account();await driver.page.goto(driver.origin+'/'+target,wait_until='domcontentloaded')
                main=await driver._scope(target)
                await main.locator('.messageWrapper').first.wait_for(timeout=driver.timeout*1000)
                if await driver._rows(main,state['text']).count():return None
                if await main.get_by_role('button',name='Открыть отложенные сообщения',exact=True).count():return None
                c=main.locator('[role="textbox"][contenteditable][data-lexical-editor]')
                if await c.evaluate(rich.TEXT_JS) or await main.locator('.attaches .attach').count():return None
                draft='VibePublish read-only guard inspection (not submitted)'
                await driver.page.bring_to_front();await c.fill(draft)
                try:
                    await main.get_by_role('button',name='Отправить сообщение',exact=True).click(button='right')
                    await driver.page.get_by_role('menu').get_by_role('menuitem',name='Отправить позже',exact=True).click()
                    dialog,_=await set_time(driver,state['scheduled_at'])
                    impossible=await dialog.evaluate('e=>e.tagName==="DIALOG"&&!e.hasAttribute("role")&&e.querySelector("button")?.closest("[role=dialog]")===null')
                    if not impossible:return None
                finally:
                    if await driver.page.get_by_role('dialog').count():await driver.page.keyboard.press('Escape')
                    if await c.evaluate(rich.TEXT_JS)==draft:await c.fill('')
                await driver._scope(target);driver._check_attempt_fuse(state['attempt_id'],state['plan_digest'])
            return dict(trusted_clicks=0,input_unreachable=True,absence_only=False,
                proof_method='legacy_unreachable_control_flow',legacy_recipe='max-native-schedule-preclick-v0',
                premise='implicit_native_dialog_cannot_match_explicit_role_guard',fresh_ui_checks=2)
    finally:driver._busy=False


async def reschedule(driver,*,existing,scheduled_at,attempt_id,plan_digest,hooks):
    import asyncio,json,re
    target=existing['target'];driver._enter(target);armed=False;guard=None
    try:
        driver.lane.assert_clear()
        if existing['namespace']!='scheduled' or not scheduled_at:raise MaxBlocked('exact_native_schedule_required')
        async with asyncio.timeout(driver.timeout):
            original=(await read(driver,target,existing['id'],passes=1))[0]
            if any(original[k]!=existing[k] for k in ('text','scheduled_at','observed_media','entities')):
                raise MaxBlocked('native_schedule_existing_changed')
            main=await driver._scope(target,'scheduled');row=driver._rows(main,original['text'])
            await driver._open_message_menu(row)
            await driver.page.get_by_role('menu').get_by_role('menuitem',name='Изменить время',exact=True).click()
            dialog,date=await set_time(driver,scheduled_at)
            clock=datetime.fromisoformat(scheduled_at.replace('Z','+00:00')).astimezone(MOSCOW).strftime('%H:%M')
            confirm=dialog.get_by_role('button',name=re.compile(r'^Отправить .+ в '+clock+'$'))
            await expect(confirm).to_have_count(1)
            guard=await confirm.evaluate_handle('(button,x)=>{'+rich.SNAPSHOT_JS+r'''
                let clicks=0,blocked=false;
                const ready=()=>{
                    const dialog=button.closest('dialog,[role="dialog"]'),row=x.row;
                    return button.isConnected&&row.isConnected&&location.href===x.route&&dialog&&
                        semanticText(row.querySelector('.bubbleContent > .text'))===x.text&&
                        JSON.stringify(semanticSnapshot(row.querySelector('.bubbleContent > .text')))===x.snapshot&&
                        row.querySelectorAll('[aria-label="Прикрепленные фото"] > button').length===x.media_count&&
                        JSON.stringify([...row.querySelectorAll('[aria-label="Прикрепленные фото"] img,[aria-label="Прикрепленные фото"] video source')].map(e=>e.currentSrc||e.src))===x.media&&
                        row.querySelector('.meta .text')?.textContent.trim()===x.old_time&&
                        dialog.querySelector('.calendar .header .title')?.textContent.trim().toLowerCase().replace(/\s+/g,' ')===x.date.month&&
                        dialog.querySelector('.days > button.day--selected')?.textContent.trim()===x.date.day&&
                        dialog.querySelector('[role="spinbutton"][aria-label="Часы"]')?.getAttribute('aria-valuenow')===x.date.hour&&
                        dialog.querySelector('[role="spinbutton"][aria-label="Минуты"]')?.getAttribute('aria-valuenow')===x.date.minute;
                };
                const check=e=>{if(!button.contains(e.target))return;
                    if(!e.isTrusted||clicks||!ready()){blocked=true;e.preventDefault();e.stopImmediatePropagation();return;}clicks++;};
                document.addEventListener('click',check,true);
                return {ready:()=>ready()&&!clicks&&!blocked,result:()=>({clicks,blocked}),stop:()=>document.removeEventListener('click',check,true)};
            }''',dict(row=await row.element_handle(),route=driver.origin+'/'+target,text=original['text'],
                media=await row.locator('[aria-label="Прикрепленные фото"] img,[aria-label="Прикрепленные фото"] video source').evaluate_all('(es)=>JSON.stringify(es.map(e=>e.currentSrc||e.src))'),
                snapshot=await row.locator('.bubbleContent > .text').evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e));}'),
                media_count=len(original['observed_media']),old_time=datetime.fromisoformat(original['scheduled_at'].replace('Z','+00:00')).astimezone(MOSCOW).strftime('%H:%M'),date=date))
            if not await guard.evaluate('(g)=>g.ready()'):raise MaxBlocked('native_reschedule_form_changed')
            state=dict(recipe='max-native-schedule-v1',target=target,text=original['text'],entities=original['entities'],
                kind='scheduled',action='reschedule',scheduled_at=scheduled_at,old_scheduled_at=original['scheduled_at'],
                media=original['media'],observed_media=original['observed_media'],media_slots=len(original['observed_media']),
                existing_id=existing['id'],native_id=existing['id'],old_correlation_id=original.get('correlation_id'),attempt_id=attempt_id,plan_digest=plan_digest)
            await hooks.checkpoint('MAX_RESCHEDULE_PREPARED',json.dumps(state))
            await driver._account();await driver._scope(target,'scheduled')
            driver.lane.arm(attempt_id,plan_digest);armed=True
            await hooks.before_effect(attempt_id,plan_digest)
            await driver._account();driver._check_attempt_fuse(attempt_id,plan_digest)
            if not await guard.evaluate('(g)=>g.ready()'):raise MaxBlocked('native_reschedule_form_changed')
            await confirm.click()
            transition=await guard.evaluate('(g)=>g.result()')
            if transition!=dict(clicks=1,blocked=False):raise MaxBlocked('native_reschedule_click_unverified')
            await hooks.checkpoint('MAX_RESCHEDULE_CONFIRMED',json.dumps(dict(state,transition=transition)))
            await guard.evaluate('(g)=>g.stop()');await guard.dispose();guard=None
            state['transition']=transition
            result=await rescheduled_item(driver,state)
            state['native_id']=result['id']
            if (result['scheduled_at']!=scheduled_at or any(result[k]!=original[k] for k in ('text','entities','observed_media'))):
                raise MaxBlocked('native_reschedule_readback_changed')
            driver._check_attempt_fuse(attempt_id,plan_digest)
            await hooks.checkpoint('MAX_CANDIDATE_OBSERVED',json.dumps(dict(state,transition=transition,item=result)))
            return [result]
    except BaseException as exc:
        if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
        if armed:raise MaxBlocked('outcome_unknown') from None
        if isinstance(exc,MaxBlocked):raise
        raise MaxBlocked('native_reschedule_prepare_unavailable') from None
    finally:
        if guard is not None:
            try:await guard.evaluate('(g)=>g.stop()');await guard.dispose()
            except Exception:pass
        driver._busy=False


async def rescheduled_item(driver,state):
    """MAX assigns a new native ID on reschedule; prove the replacement, not retry.

    A complete correlated native queue must no longer contain the old ID. The
    unique new content/time/media candidate is verified on a second fresh load.
    Proof requires either the persisted trusted Save or the native correlation
    observed before it; a mere text match never grants replacement authority.
    """
    target=state['target'];old=state['existing_id']
    async with QueueObserver(driver.page,target,driver.origin,driver.evidence_pages) as observer:
        await driver._account();await driver.page.goto(driver.origin+'/'+target,wait_until='domcontentloaded')
        natives=await open_queue(driver,target,observer)
        matches=[x for x in natives if x['id']==old]
        if not matches:
            when=int(datetime.fromisoformat(state['scheduled_at'].replace('Z','+00:00')).timestamp()*1000)
            matches=[x for x in natives if x['text']==state['text'] and x['time_ms']==when and x['media_count']==state['media_slots']]
        if len(matches)!=1:raise MaxBlocked('native_reschedule_identity_ambiguous')
        first=await item(driver,target,matches[0],await driver._scope(target,'scheduled'))
    if first['id']!=old:
        correlation=state.get('old_correlation_id')
        correlated=bool(correlation) and correlation==first.get('correlation_id')
        clicked=state.get('transition')==dict(clicks=1,blocked=False)
        if not correlated and not clicked:raise MaxBlocked('native_replacement_proof_missing')
        state['replacement_evidence']='stable_native_correlation' if correlated else 'trusted_ui_native_queue_replacement'
    if (first['text']!=state['text'] or first['scheduled_at']!=state['scheduled_at']
            or first['observed_media']!=state['observed_media'] or not rich.same_entities(first['entities'],state['entities'])):
        raise MaxBlocked('native_reschedule_content_or_media_changed')
    fresh=(await read(driver,target,first['id'],passes=1))[0]
    if any(first[k]!=fresh[k] for k in ('id','text','entities','scheduled_at','observed_media','correlation_id')):
        raise MaxBlocked('native_replacement_changed')
    return fresh


async def cancelled_item(driver,state):
    """A persisted trusted removal plus fresh native absence, never absence alone."""
    if state.get('transition')!=dict(clicks=1,removed=True,blocked=False):
        raise MaxBlocked('native_cancel_removal_proof_missing')
    original=state.get('item',{})
    if (original.get('id')!=state['existing_id'] or original.get('target')!=state['target']
            or original.get('scheduled_at')!=state['old_scheduled_at']):
        raise MaxBlocked('native_cancel_binding_changed')
    for _ in range(2):
        async with QueueObserver(driver.page,state['target'],driver.origin,driver.evidence_pages) as observer:
            await driver._account()
            await driver.page.goto(driver.origin+'/'+state['target'],wait_until='domcontentloaded')
            main=await driver._scope(state['target'])
            entry=main.get_by_role('button',name='Открыть отложенные сообщения',exact=True)
            if await entry.count():
                natives=await open_queue(driver,state['target'],observer)
                if any(n['id']==state['existing_id'] for n in natives):raise MaxBlocked('native_cancel_item_still_present')
            # A last-item deletion removes the queue entry. The persisted causal
            # removal, not this empty UI alone, proves cancellation vs publication.
            await driver._account()
    return dict(original,observed_at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'))


async def cancel(driver,*,existing,attempt_id,plan_digest,hooks):
    import asyncio,json
    target=existing['target'];driver._enter(target);guard=None;armed=False
    try:
        driver.lane.assert_clear()
        if driver.targets[target].policy!='test_group' or existing['namespace']!='scheduled':
            raise MaxBlocked('native_cancel_scope_unqualified')
        async with asyncio.timeout(driver.timeout):
            original=(await read(driver,target,existing['id'],passes=1))[0]
            if (any(original[k]!=existing[k] for k in ('text','scheduled_at','observed_media'))
                    or not rich.same_entities(original['entities'],existing['entities'])):
                raise MaxBlocked('native_cancel_existing_changed')
            main=await driver._scope(target,'scheduled');row=driver._rows(main,original['text'])
            await driver._open_message_menu(row)
            # The observed delayed-item menu opens a native confirmation dialog;
            # the only provider deletion is its guarded primary button below.
            await driver.page.get_by_role('menu').get_by_role('menuitem',name='Удалить',exact=True).click()
            dialog=driver.page.get_by_role('dialog')
            await expect(dialog.get_by_text('Удалить сообщение',exact=True)).to_have_count(1)
            await expect(dialog.get_by_role('checkbox')).to_have_count(0)
            button=dialog.get_by_role('button',name='Удалить',exact=True)
            await expect(button).to_have_count(1)
            guard=await button.evaluate_handle('(button,x)=>{'+rich.SNAPSHOT_JS+r'''
                let clicks=0,removed=false,blocked=false;const row=x.row,main=row.closest('main');
                const ready=()=>button.isConnected&&row.isConnected&&location.href===x.route&&
                    semanticText(row.querySelector('.bubbleContent > .text'))===x.text&&
                    JSON.stringify(semanticSnapshot(row.querySelector('.bubbleContent > .text')))===x.snapshot&&
                    row.querySelector('.meta .text')?.textContent.trim()===x.time&&
                    row.querySelectorAll('[aria-label="Прикрепленные фото"] > button').length===x.media_count&&
                        JSON.stringify([...row.querySelectorAll('[aria-label="Прикрепленные фото"] img,[aria-label="Прикрепленные фото"] video source')].map(e=>e.currentSrc||e.src))===x.media&&Date.now()<x.at;
                const watcher=new MutationObserver(()=>{if(clicks===1&&!row.isConnected)removed=true;});
                watcher.observe(main,{childList:true,subtree:true});
                const check=e=>{if(!button.contains(e.target))return;
                    if(!e.isTrusted||clicks||!ready()){blocked=true;e.preventDefault();e.stopImmediatePropagation();return;}clicks++;};
                document.addEventListener('click',check,true);
                return {ready,result:()=>({clicks,removed,blocked}),stop:()=>{watcher.disconnect();document.removeEventListener('click',check,true);}};
            }''',dict(row=await row.element_handle(),route=driver.origin+'/'+target,text=original['text'],
                media=await row.locator('[aria-label="Прикрепленные фото"] img,[aria-label="Прикрепленные фото"] video source').evaluate_all('(es)=>JSON.stringify(es.map(e=>e.currentSrc||e.src))'),
                snapshot=await row.locator('.bubbleContent > .text').evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e));}'),
                time=datetime.fromisoformat(original['scheduled_at'].replace('Z','+00:00')).astimezone(MOSCOW).strftime('%H:%M'),
                at=int(datetime.fromisoformat(original['scheduled_at'].replace('Z','+00:00')).timestamp()*1000),media_count=len(original['observed_media'])))
            if not await guard.evaluate('(g)=>g.ready()'):raise MaxBlocked('native_cancel_guard_changed')
            state=dict(recipe='max-native-schedule-v1',target=target,text=original['text'],entities=original['entities'],
                kind='scheduled',action='cancel',scheduled_at=None,old_scheduled_at=original['scheduled_at'],
                media=original['media'],observed_media=original['observed_media'],media_slots=len(original['observed_media']),
                existing_id=original['id'],native_id=original['id'],item=original,attempt_id=attempt_id,plan_digest=plan_digest)
            await hooks.checkpoint('MAX_CANCEL_PREPARED',json.dumps(state))
            await driver._account();await driver._scope(target,'scheduled')
            driver.lane.arm(attempt_id,plan_digest);armed=True
            await hooks.before_effect(attempt_id,plan_digest)
            await driver._account();driver._check_attempt_fuse(attempt_id,plan_digest)
            if not await guard.evaluate('(g)=>g.ready()'):raise MaxBlocked('native_cancel_guard_changed')
            await button.click();await expect(dialog).to_have_count(0);await expect(row).to_have_count(0)
            transition=await guard.evaluate('(g)=>g.result()')
            if transition!=dict(clicks=1,removed=True,blocked=False):raise MaxBlocked('native_cancel_transition_unverified')
            state['transition']=transition
            await hooks.checkpoint('MAX_CANCEL_CONFIRMED',json.dumps(state))
            await guard.evaluate('(g)=>g.stop()');await guard.dispose();guard=None
            result=await cancelled_item(driver,state)
            await hooks.checkpoint('MAX_CANCEL_OBSERVED',json.dumps(dict(state,item=result)))
            return [result]
    except BaseException as exc:
        if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
        if armed:raise MaxBlocked('outcome_unknown') from None
        if isinstance(exc,MaxBlocked):raise
        raise MaxBlocked('native_cancel_prepare_unavailable') from None
    finally:
        if guard is not None:
            try:await guard.evaluate('(g)=>g.stop()');await guard.dispose()
            except Exception:pass
        driver._busy=False


async def edit(driver,*,existing,text,entities,attempt_id,plan_digest,hooks):
    """Observed queued-message editor; retain native time and all media."""
    import asyncio,json,re
    from .live import COMPOSER
    target=existing['target'];driver._enter(target);armed=False;guard=None
    try:
        driver.lane.assert_clear()
        if driver.targets[target].policy!='test_group' or existing['namespace']!='scheduled':
            raise MaxBlocked('native_edit_scope_unqualified')
        async with asyncio.timeout(driver.timeout):
            original=(await read(driver,target,existing['id'],passes=1))[0]
            if (any(original[k]!=existing[k] for k in ('text','scheduled_at','observed_media'))
                    or not rich.same_entities(original['entities'],existing['entities'])):
                raise MaxBlocked('native_edit_existing_changed')
            main=await driver._scope(target,'scheduled');row=driver._rows(main,original['text'])
            await driver._open_message_menu(row)
            await driver.page.get_by_role('menu').get_by_role('menuitem',name='Редактировать',exact=True).click()
            heading=main.get_by_text('Редактирование сообщения',exact=True)
            await expect(heading).to_have_count(1)
            composer=main.locator(COMPOSER)
            if await composer.evaluate(rich.TEXT_JS)!=original['text']:raise MaxBlocked('native_edit_draft_changed')
            attached=main.locator('.attaches .attach img')
            await expect(main.locator('.attaches .attach')).to_have_count(len(original['observed_media']))
            await expect(attached).to_have_count(len(original['observed_media']))
            for image in await attached.element_handles():
                await driver.page.wait_for_function('(e)=>e.isConnected&&e.complete&&e.naturalWidth>0',arg=image,timeout=driver.timeout*1000)
            previews=await attached.evaluate_all('(es)=>es.map(e=>({src:e.src,name:e.alt}))')
            await rich.fill(driver.page,composer,text,entities)
            button=main.get_by_role('button',name='Отправить сообщение',exact=True)
            guard=await button.evaluate_handle('(button,x)=>{'+rich.SNAPSHOT_JS+r'''
                let clicks=0,blocked=false;const row=x.row,main=row.closest('main');
                const checks=()=>({
                    connected:button.isConnected&&row.isConnected,route:location.href===x.route,
                    mode:[...main.querySelectorAll('*')].some(e=>!e.children.length&&e.textContent==='Редактирование сообщения'),
                    text:semanticText(main.querySelector(x.composer))===x.text,
                    rich:JSON.stringify(semanticSnapshot(main.querySelector(x.composer)))===x.snapshot,
                    old_text:semanticText(row.querySelector('.bubbleContent > .text'))===x.old,
                    old_rich:JSON.stringify(semanticSnapshot(row.querySelector('.bubbleContent > .text')))===x.old_snapshot,
                    time:row.querySelector('.meta .text')?.textContent.trim()===x.time,
                    media:JSON.stringify([...row.querySelectorAll('[aria-label="Прикрепленные фото"] img,[aria-label="Прикрепленные фото"] video source')].map(e=>e.currentSrc||e.src))===x.media,
                    previews:JSON.stringify([...main.querySelectorAll('.attaches .attach img')].map(e=>({src:e.src,name:e.alt})))===JSON.stringify(x.previews)
                });
                const ready=()=>Object.values(checks()).every(Boolean);
                const check=e=>{if(!button.contains(e.target))return;
                    if(!e.isTrusted||clicks||!ready()){blocked=true;e.preventDefault();e.stopImmediatePropagation();return;}clicks++;};
                document.addEventListener('click',check,true);
                return {ready,checks,result:()=>({clicks,blocked}),stop:()=>document.removeEventListener('click',check,true)};
            }''',dict(row=await row.element_handle(),route=driver.origin+'/'+target,composer=COMPOSER,text=text,old=original['text'],previews=previews,
                media=await row.locator('[aria-label="Прикрепленные фото"] img,[aria-label="Прикрепленные фото"] video source').evaluate_all('(es)=>JSON.stringify(es.map(e=>e.currentSrc||e.src))'),
                snapshot=await composer.evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e));}'),
                old_snapshot=await row.locator('.bubbleContent > .text').evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e));}'),
                time=datetime.fromisoformat(original['scheduled_at'].replace('Z','+00:00')).astimezone(MOSCOW).strftime('%H:%M')))
            if not await guard.evaluate('(g)=>g.ready()'):
                await hooks.emit_progress('validating','failed',__import__('json').dumps(await guard.evaluate('(g)=>g.checks()')))
                raise MaxBlocked('native_edit_guard_changed')
            state=dict(recipe='max-native-schedule-v1',target=target,text=text,entities=list(entities),kind='scheduled',action='edit',
                scheduled_at=original['scheduled_at'],media=original['media'],observed_media=original['observed_media'],
                media_slots=len(original['observed_media']),existing_id=original['id'],native_id=original['id'],attempt_id=attempt_id,plan_digest=plan_digest)
            await hooks.checkpoint('MAX_NATIVE_EDIT_PREPARED',json.dumps(state))
            await driver._account();await driver._scope(target,'scheduled')
            driver.lane.arm(attempt_id,plan_digest);armed=True
            await hooks.before_effect(attempt_id,plan_digest)
            await driver._account();driver._check_attempt_fuse(attempt_id,plan_digest)
            if not await guard.evaluate('(g)=>g.ready()'):
                await hooks.emit_progress('validating','failed',__import__('json').dumps(await guard.evaluate('(g)=>g.checks()')))
                raise MaxBlocked('native_edit_guard_changed')
            await button.click();state['transition']=await guard.evaluate('(g)=>g.result()')
            if state['transition']!=dict(clicks=1,blocked=False):raise MaxBlocked('native_edit_click_unverified')
            await hooks.checkpoint('MAX_NATIVE_EDIT_CONFIRMED',json.dumps(state))
            await expect(heading).to_have_count(0)
            await guard.evaluate('(g)=>g.stop()');await guard.dispose();guard=None
            result=(await read(driver,target,original['id']))[0]
            if (result['text']!=text or not rich.same_entities(result['entities'],entities)
                    or result['scheduled_at']!=original['scheduled_at'] or result['observed_media']!=original['observed_media']):
                raise MaxBlocked('native_edit_readback_changed')
            await hooks.checkpoint('MAX_NATIVE_EDIT_OBSERVED',json.dumps(dict(state,item=result)))
            return [result]
    except BaseException as exc:
        if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
        if armed:raise MaxBlocked('outcome_unknown') from None
        if isinstance(exc,MaxBlocked):raise
        raise MaxBlocked('native_edit_prepare_unavailable') from None
    finally:
        if guard is not None:
            try:await guard.evaluate('(g)=>g.stop()');await guard.dispose()
            except Exception:pass
        driver._busy=False
