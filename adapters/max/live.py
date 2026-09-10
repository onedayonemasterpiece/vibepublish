"""Observed MAX Web read/navigation recipe, not a publishing-capability claim.

Read/recovery code runs unchanged against MAX and sanitized loopback replay.
The same class supports explicitly wired text/image/video Test Group effects and
observed replay. Scheduling capabilities remain refused until implemented.
No API, storage-state reads, account-wide message search or synthetic selectors.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from playwright.async_api import ElementHandle, Error as PlaywrightError, expect, TimeoutError as PlaywrightTimeoutError

from .profile import MaxBlocked, ProfileLane
from . import rich

RECIPE = 'max-web-observed-20260905-v1'
MAIN = 'main[aria-labelledby="main-header-title"]'
COMPOSER = '[contenteditable][role="textbox"][data-lexical-editor="true"]'
TITLE = '.name > .text'
QUEUE_TITLE = 'Запланированные посты'
QUEUE_HEADING = re.compile(r'^(?:Запланированные посты|Отложенные сообщения)$')


@dataclass(frozen=True)
class Target:
    native_id: str
    alias: str
    policy: str

    def __post_init__(self):
        if not re.fullmatch(r'-[1-9][0-9]{0,19}', self.native_id):
            raise MaxBlocked('invalid_native_target')
        if not self.alias or self.policy not in {'test_group', 'scheduled_only'}:
            raise MaxBlocked('invalid_target_binding')


@dataclass(frozen=True)
class VisibleSnapshot:
    """A bounded screen projection, NEVER an authoritative full provider queue.

    No fabricated native IDs, timestamps, media hashes or pagination cursors.
    Provider item identity is a separate gate, not a text/time fingerprint.
    """
    target: str
    namespace: str
    observed_at: str
    rows: tuple[dict, ...]
    complete: bool = False
    missing_checks: tuple[str, ...] = ('native_item_identity', 'pagination_completeness')


class RealMaxDriver:
    def __init__(self, page, lane: ProfileLane, *, targets: tuple[Target, ...],
                 account_check, origin='https://web.max.ru', timeout=10, visual_recovery=None, visual_palette=None, live_writes=False, semantic_selectors=False, evidence_pages=()):
        parsed = urlsplit(origin)
        if not (origin == 'https://web.max.ru' or
                parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
                and parsed.port and parsed.path == '' and not parsed.query
                and not parsed.fragment and not parsed.username and not parsed.password):
            raise MaxBlocked('max_origin_denied')
        if len({t.native_id for t in targets}) != len(targets):
            raise MaxBlocked('duplicate_target_binding')
        self.page, self.lane, self.account_check = page, lane, account_check
        self.targets = {t.native_id: t for t in targets}
        self.origin, self.timeout, self._busy = origin, timeout, False
        self.evidence_pages = tuple(evidence_pages) or (page,)
        self.semantic_selectors = semantic_selectors
        self.visual_recovery = visual_recovery
        self.visual_palette = visual_palette
        self.live_writes = live_writes is True
        self.min_lead = 60

    def _rows(self, main, text, *, outgoing=False):
        if self.semantic_selectors:
            import json
            return main.locator('maxrow='+json.dumps(dict(text=text,outgoing=outgoing)))
        return main.locator('.messageWrapper--isOut' if outgoing else '.messageWrapper').filter(
            has=self.page.locator('.bubbleContent > .text').filter(has_text=re.compile('^'+re.escape(text)+'$')))

    def _enter(self, target):
        self.lane.owned()
        if self._busy:
            raise MaxBlocked('profile_busy')
        if target not in self.targets:
            raise MaxBlocked('target_denied')
        self._busy = True

    def _route(self, target):
        if self.page.url != self.origin + '/' + target:
            raise MaxBlocked('wrong_target_or_origin')

    async def _account(self):
        # Trusted explicit binding, not a boolean supplied by a model/request.
        # Live factory reads the existing account's settings in its OWN page.
        if await self.account_check() is not True:
            raise MaxBlocked('needs_auth_or_wrong_account')

    async def _scope(self, target, namespace='feed'):
        self._route(target)
        main = self.page.locator(MAIN)
        await expect(main).to_have_count(1, timeout=self.timeout*1000)
        if namespace == 'feed':
            # Fail closed on a rename pending read-only binding reconfirmation.
            # Never replace the ID with another chat carrying the previous name.
            header = main.get_by_role('button', name='Открыть профиль ' + self.targets[target].alias, exact=True)
            await expect(header).to_be_visible(timeout=self.timeout*1000)
            if await main.get_by_text(QUEUE_HEADING, exact=True).count():
                raise MaxBlocked('wrong_namespace')
        elif namespace == 'scheduled':
            await expect(main.get_by_text(QUEUE_HEADING, exact=True)).to_be_visible(timeout=self.timeout*1000)
        else:
            raise MaxBlocked('unsupported_namespace')
        self._route(target)
        return main

    async def open(self, target):
        self._enter(target)
        try:
            async with asyncio.timeout(self.timeout):
                await self._account()
                # Reordering/pinning/unread/search cannot affect this binding.
                # This route was obtained from actual owner-authorized UI.
                await self.page.goto(self.origin + '/' + target, wait_until='domcontentloaded')
                await self._scope(target)
                await self._account()
                await self._scope(target)
        except MaxBlocked:
            raise
        except Exception:
            raise MaxBlocked('unfamiliar_or_unavailable_ui') from None
        finally:
            self._busy = False

    async def visible(self, target, namespace='feed'):
        """Explicit incomplete read; unsuitable for deletion/absence assertions."""
        await self.open(target)
        self._enter(target)
        try:
            async with asyncio.timeout(self.timeout):
                main = await self._scope(target)
                if namespace == 'scheduled':
                    control = main.get_by_role('button', name='Открыть отложенные сообщения', exact=True)
                    if await control.count() != 1:
                        raise MaxBlocked('queue_entry_not_observed')
                    await control.click()
                    main = await self._scope(target, namespace)
                elif namespace != 'feed':
                    raise MaxBlocked('unsupported_namespace')
                # Read only this bound main pane, not sidebar snippets, app state,
                # cookies, local storage or unrelated search matches.
                rows = await main.locator('.messageWrapper').evaluate_all('''els => els.map(e => ({
                    text: e.querySelector('.bubbleContent > .text')?.textContent ?? '',
                    media: [...e.querySelectorAll('.media img')].map(i => i.getAttribute('src')),
                    displayed_time: e.querySelector('.meta .text')?.textContent ?? null,
                    outgoing: e.classList.contains('messageWrapper--isOut')
                }))''')
                if len(rows) > 100:
                    raise MaxBlocked('visible_read_bound_exceeded')
                await self._account()
                await self._scope(target, namespace)
                return VisibleSnapshot(target, namespace, datetime.now(timezone.utc).isoformat(), tuple(rows))
        except MaxBlocked:
            raise
        except Exception:
            raise MaxBlocked('unfamiliar_or_unavailable_ui') from None
        finally:
            self._busy = False

    async def discovery_titles(self):
        """Only visible CHAT titles. Never issue account-wide message search.

        Names remain untrusted discovery hints. This method neither clicks a row
        nor creates an allowlist binding, even if a title has exactly one match.
        """
        self.lane.owned()
        if self._busy:
            raise MaxBlocked('profile_busy')
        self._busy = True
        try:
            async with asyncio.timeout(self.timeout):
                await self._account()
                parsed = urlsplit(self.page.url)
                if f'{parsed.scheme}://{parsed.netloc}' != self.origin:
                    raise MaxBlocked('max_origin_denied')
                # h3 limits normal list; search has a separate observed title
                # wrapper. A highlighted name in a message excerpt is not one.
                names = await self.page.locator('h3 ' + TITLE + ', .searchResultsList > button[aria-haspopup="dialog"] .title ' + TITLE).all_text_contents()
                if len(names) > 100:
                    raise MaxBlocked('discovery_bound_exceeded')
                await self._account()
                return tuple(" ".join(name.split()) for name in names)
        except MaxBlocked:
            raise
        except Exception:
            raise MaxBlocked('discovery_unavailable') from None
        finally:
            self._busy = False

    async def mutation_preflight(self, target, action, *, media=(), scheduled_at=None):
        self.lane.assert_clear()
        if not self.live_writes:
            raise MaxBlocked('causal_receipt_recipe_unverified')
        if target not in self.targets:
            raise MaxBlocked('immediate_publication_denied')
        # Cancel is not immediate publication. The queued native snapshot and
        # exact bound object are mandatory in queue.cancel before any input.
        if action=='cancel':return
        if self.targets[target].policy != 'test_group' and scheduled_at is None:
            raise MaxBlocked('immediate_publication_denied')
        if scheduled_at is not None and action in {'publish','reschedule','edit'}:
            wanted=datetime.fromisoformat(scheduled_at.replace('Z','+00:00'))
            if wanted.second or wanted.microsecond:raise MaxBlocked('native_schedule_minute_precision')
            return
        if action not in {'publish', 'edit', 'delete', 'react','reply','forward'} or scheduled_at is not None:
            raise MaxBlocked('live_surface_not_implemented')

    async def mutate(self, *, target, text, media, scheduled_at, action,
                     attempt_id, plan_digest, hooks, existing=None, entities=(), reaction=None, reaction_mode=None, subject=None):
        await self.mutation_preflight(target, action, media=media, scheduled_at=scheduled_at)
        if action=='forward':
            from .engagement import forward
            return await forward(self,subject=subject,target=target,attempt_id=attempt_id,plan_digest=plan_digest,hooks=hooks)
        if action=='react':
            from . import engagement
            return await engagement.react(self,existing=existing,reaction=reaction,reaction_mode=reaction_mode,attempt_id=attempt_id,plan_digest=plan_digest,hooks=hooks)
        if action=='cancel':
            from . import queue
            return await queue.cancel(self,existing=existing,attempt_id=attempt_id,plan_digest=plan_digest,hooks=hooks)
        if action=='reschedule':
            from . import queue
            return await queue.reschedule(self,existing=existing,scheduled_at=scheduled_at,attempt_id=attempt_id,plan_digest=plan_digest,hooks=hooks)
        if action=='edit' and scheduled_at is not None:
            from . import queue
            return await queue.edit(self,existing=existing,text=text,entities=entities,attempt_id=attempt_id,plan_digest=plan_digest,hooks=hooks)
        if action == 'publish' and scheduled_at is not None:
            from . import queue
            return await queue.publish(self,target=target,text=text,media=media,entities=entities,scheduled_at=scheduled_at,attempt_id=attempt_id,plan_digest=plan_digest,hooks=hooks)
        if action in {'publish','reply'}:
            result = await self.submit_plain_candidate(target=target,text=text,
                attempt_id=attempt_id,plan_digest=plan_digest,hooks=hooks,media=media,entities=entities,reply_to=subject if action=='reply' else None)
        elif action == 'delete':
            result = await self.delete_plain(existing=existing,attempt_id=attempt_id,plan_digest=plan_digest,hooks=hooks)
        else:
            result = await self.edit_plain_candidate(existing=existing,text=text,
                attempt_id=attempt_id,plan_digest=plan_digest,hooks=hooks,entities=entities)
        return [result['item']]

    async def _compose(self, main, text, media, entities):
        composer=main.locator(COMPOSER)
        await expect(composer).to_have_count(1)
        if await composer.evaluate(rich.TEXT_JS):raise MaxBlocked('existing_draft')
        if len(media)>10 or any(m['mimeType'] not in {'image/png','image/jpeg','video/mp4'} for m in media):
            raise MaxBlocked('unsupported_media')
        if await main.locator('.attaches .attach').count():raise MaxBlocked('existing_attachments')
        previews=[]
        if media:
            await main.get_by_role('button',name='Загрузить файл',exact=True).click()
            async with self.page.expect_file_chooser() as chooser:
                await self.page.get_by_role('menu').get_by_role('menuitem',name='Фото или видео',exact=True).click()
            await (await chooser.value).set_files(list(media))
            attached=main.locator('.attaches .attach img')
            await expect(attached).to_have_count(len(media))
            if any(m['mimeType']=='video/mp4' for m in media):
                await expect(main.locator('.attaches').get_by_role('button',name='Отменить загрузку',exact=True)).to_have_count(0,timeout=self.timeout*1000)
            previews=await attached.evaluate_all('(es)=>es.map(e=>({src:e.src,name:e.alt}))')
            if [p['name'] for p in previews]!=[m['name'] for m in media] or any(not p['src'].startswith('data:image/png;base64,' if m['mimeType']=='video/mp4' else 'blob:') for p,m in zip(previews,media)):
                raise MaxBlocked('upload_preview_mismatch')
        await rich.fill(self.page,composer,text,entities)
        return composer,previews

    async def submit_plain_candidate(self, *, target, text, attempt_id, plan_digest, hooks, media=(), entities=(), reply_to=None):
        """Single trusted plain Send with durable native receipt, no effect retry.

        Runs observed composer/Send/native-copy selectors. Captures
        the UI transition before Send and persists an exact reference before a
        fresh read. Evidence is a candidate, not core-authorized attribution or
        release. No required marker is appended to ordinary user text.
        """
        import json
        if not self.live_writes and not re.fullmatch(r'http://127\.0\.0\.1:[0-9]+', self.origin):
            raise MaxBlocked('writer_live_qualification_pending')
        if reply_to is not None:
            from .engagement import same_content
            if reply_to['target']!=target or reply_to['namespace']!='feed':raise MaxBlocked('reply_subject_scope')
            source=(await self.read(target,'feed',native_item=reply_to['id']))[0]
            if not same_content(source,reply_to):raise MaxBlocked('reply_source_changed')
        self._enter(target)
        armed = False
        observer = None
        try:
            self.lane.assert_clear()
            if self.targets[target].policy != 'test_group':
                raise MaxBlocked('immediate_publication_denied')
            if (not isinstance(text, str) or not text.strip() or len(text) > 4000
                    or not attempt_id or not plan_digest or hooks is None):
                raise MaxBlocked('invalid_publish_intent')
            async with asyncio.timeout(self.timeout):
                await self._account()
                await self.page.goto(self.origin + '/' + target, wait_until='domcontentloaded')
                main = await self._scope(target)
                if await self._rows(main,text).count():
                    raise MaxBlocked('preexisting_content_candidate')
                reply_node=None
                if reply_to is not None:
                    source_row=self._rows(main,reply_to['text'],outgoing=True)
                    if await self._copy_native_reference(source_row,target)!=(reply_to['url'],reply_to['id']):
                        raise MaxBlocked('reply_native_reference_changed')
                    reply_node=await source_row.element_handle()
                    await self._open_message_menu(source_row)
                    await self.page.get_by_role('menu').get_by_role('menuitem',name='Ответить',exact=True).click()
                    await expect(main.locator('.composer .action > .text.title')).to_contain_text('Ответ для')
                    if (await main.locator('.composer .action > .text.content').text_content()).strip()!=reply_to['text']:
                        raise MaxBlocked('reply_preview_unverified')
                composer,previews=await self._compose(main,text,media,entities)
                observer = await main.evaluate_handle("(main, intent) => {" + rich.SNAPSHOT_JS + """
                    const content = '.bubbleContent > .text';
                    const state = {clicks:0, changed:false, blocked:false};
                    const candidates = () => [...main.querySelectorAll('.messageWrapper')]
                        .filter(r=>semanticText(r.querySelector(content))===intent.text);
                    const watch = new MutationObserver(() => {
                        if(state.clicks===1 && candidates().length) state.changed=true;
                    });
                    watch.observe(main,{subtree:true,childList:true,characterData:true});
                    const guard = e => {
                        const send=e.target.closest('button[aria-label="Отправить сообщение"]');
                        if(!send) return;
                        const editors=main.querySelectorAll(intent.composer);
                        let shell=editors[0]?.parentElement;
                        while(shell && shell!==main && !shell.querySelector('button[aria-label="Отправить сообщение"]')) shell=shell.parentElement;
                        while(shell?.parentElement?.classList.contains('composer')) shell=shell.parentElement;
                        const previews=[...(shell?.querySelectorAll('.attaches .attach img')||[])].map(e=>({src:e.src,name:e.alt}));
                        const header=[...main.querySelectorAll('button')]
                            .some(b=>b.getAttribute('aria-label')===intent.header);
                        if(!main.isConnected || !main.contains(send) || !e.isTrusted ||
                           location.href!==intent.route || !header ||
                           editors.length!==1 || semanticText(editors[0])!==intent.text || JSON.stringify(semanticSnapshot(editors[0]))!==intent.snapshot ||
                           (intent.reply && (!intent.replyNode?.isConnected ||
                             semanticText(intent.replyNode.querySelector(content))!==intent.reply.text ||
                             !shell?.querySelector('.action > .text.title')?.textContent.includes('Ответ для') ||
                             shell?.querySelector('.action > .text.content')?.textContent.trim()!==intent.reply.text)) ||
                           (!intent.reply && shell?.querySelector('.action')) ||
                           !shell || shell===main || shell.querySelector('.messageWrapper,video,audio') ||
                           JSON.stringify(previews)!==JSON.stringify(intent.previews) ||
                           shell.querySelectorAll('.attaches img').length!==intent.previews.length ||
                           candidates().length || state.clicks) {
                            state.blocked=true;e.preventDefault();e.stopImmediatePropagation();return;
                        }
                        state.clicks++;
                    };
                    document.addEventListener('click',guard,true);
                    return {state, ready:()=>main.isConnected && location.href===intent.route && !state.clicks && !state.blocked,
                        stop:()=>{watch.disconnect();document.removeEventListener('click',guard,true);}};
                }""", dict(text=text, reply=reply_to,replyNode=reply_node, snapshot=await composer.evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e));}'), previews=previews, composer=COMPOSER, route=self.origin+'/'+target,
                            header='Открыть профиль '+self.targets[target].alias))
                state = dict(target=target, text=text, entities=list(entities), kind='feed', action='reply' if reply_to is not None else 'publish',reply_to=reply_to,
                             media=[None]*len(media), source_hashes=[__import__('hashlib').sha256(m['buffer']).hexdigest() for m in media], media_slots=len(media), upload_previews=previews, scheduled_at=None, existing_id=None,
                             attempt_id=attempt_id, plan_digest=plan_digest,
                             observer_installed=True, baseline_scope='loaded_target_rows_only')
                await hooks.checkpoint('MAX_PREPARED', json.dumps(state))
                await hooks.emit_progress('submitting', 'running', '{}')
                await self._account()
                await self._scope(target)
                self.lane.arm(attempt_id, plan_digest)
                armed = True
                await hooks.before_effect(attempt_id, plan_digest)
                await self._account()
                self._check_attempt_fuse(attempt_id, plan_digest)
                main = await self._scope(target)
                if await main.locator(COMPOSER).evaluate(rich.TEXT_JS) != text:
                    raise MaxBlocked('composer_changed')
                if not await observer.evaluate('(o)=>o.ready()'):
                    raise MaxBlocked('submit_observer_lost')
                # No retry loop: after this boundary any failure is unknown.
                await main.get_by_role('button', name='Отправить сообщение', exact=True).click()
                await hooks.emit_progress('reading_back', 'running', '{}')
                rows = self._rows(main,text)
                await expect(rows).to_have_count(1, timeout=self.timeout*1000)
                transition = await observer.evaluate('(o)=>o.state')
                if transition != dict(clicks=1, changed=True, blocked=False):
                    raise MaxBlocked('submit_transition_unverified')
                if reply_to is not None or entities or any(m['mimeType']=='video/mp4' for m in media):
                    # Preserve the actual native reference before media inspection;
                    # a lost download/readback must never require another Send.
                    if 'messageWrapper--isOut' not in (await rows.get_attribute('class') or '').split():
                        raise MaxBlocked('nonexact_outgoing_candidate')
                    reference,native_id=await self._copy_native_reference(rows,target)
                    state.update(recovery_reference=reference,native_id=native_id,transition=transition)
                    await hooks.checkpoint('MAX_NATIVE_REFERENCE',json.dumps(state))
                item = await self._plain_candidate(target, text, rows, media_count=len(media))
                state.update(recovery_reference=item['url'],native_id=item['id'],transition=transition,media=item['media'],observed_media=item.get('observed_media',[]))
                await hooks.checkpoint('MAX_NATIVE_REFERENCE', json.dumps(state))
                # The checkpoint is awaited BEFORE navigation destroys the observer.
                await self._account()
                await self._scope(target)
                await observer.evaluate('(o)=>o.stop()')
                await observer.dispose()
                observer = None
                await self.page.goto(self.origin+'/'+target, wait_until='domcontentloaded')
                main = await self._scope(target)
                rows = self._rows(main,text)
                await expect(rows).to_have_count(1, timeout=self.timeout*1000)
                fresh = await self._plain_candidate(target, text, rows, media_count=len(media))
                if fresh['url'] != item['url'] or fresh.get('observed_media',[]) != item.get('observed_media',[]):
                    raise MaxBlocked('native_reference_changed')
                await self._account()
                await self._scope(target)
                # Account callback may rerender the list: do not return old data.
                final = await self._plain_candidate(target, text, rows, media_count=len(media))
                if final['url'] != item['url'] or final.get('observed_media',[]) != item.get('observed_media',[]):
                    raise MaxBlocked('native_reference_changed')
                if reply_to is not None:
                    from .engagement import verify_reply
                    self._busy=False
                    final=await verify_reply(self,final,reply_to)
                self._check_attempt_fuse(attempt_id, plan_digest)
                await hooks.checkpoint('MAX_CANDIDATE_OBSERVED', json.dumps(dict(state, item=final)))
                return dict(item=final, transition=transition, quarantine_released=False,
                            attribution='requires_core_historical_evidence_validation',
                            history_complete=False)
        except BaseException as exc:
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            if armed:
                raise MaxBlocked('outcome_unknown') from None
            if isinstance(exc, MaxBlocked):
                raise
            raise MaxBlocked('prepare_unavailable') from None
        finally:
            if observer is not None:
                try:
                    await observer.evaluate('(o)=>o.stop()')
                    await observer.dispose()
                except Exception:
                    pass  # Closed page/context; never convert uncertainty to retry.
            self._busy = False

    async def edit_plain_candidate(self, *, existing, text, attempt_id, plan_digest, hooks, entities=()):
        """Exact plain-text edit; post-commit release belongs to the core hook.

        Requires the observed edit-mode heading as well as a copied native
        reference. Unknown/closed edit mode must never turn Save into new Send.
        Media/rich/scheduled objects are refused, never silently stripped.
        """
        import json
        if not self.live_writes and not re.fullmatch(r'http://127\.0\.0\.1:[0-9]+', self.origin):
            raise MaxBlocked('writer_live_qualification_pending')
        try:
            target, old, reference = existing['target'], existing['text'], existing['url']
            match = re.fullmatch(r'https://max\.ru/c/(-[1-9][0-9]*)/([A-Za-z0-9_-]+)', reference)
            if (not match or match[1] != target or match[2] != existing['id']
                    or existing['namespace'] != 'feed'
                    or existing['scheduled_at'] is not None or not old
                    or not isinstance(text, str) or not text.strip() or len(text) > 4000
                    or old == text or not attempt_id or not plan_digest or hooks is None):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise MaxBlocked('exact_plain_existing_required') from None
        self._enter(target)
        armed = False
        guard = None
        try:
            self.lane.assert_clear()
            if self.targets[target].policy != 'test_group':
                raise MaxBlocked('published_channel_edit_denied')
            async with asyncio.timeout(self.timeout):
                await self._account()
                await self.page.goto(self.origin+'/'+target, wait_until='domcontentloaded')
                main = await self._scope(target)
                composer = main.locator(COMPOSER)
                if await composer.evaluate(rich.TEXT_JS):
                    raise MaxBlocked('existing_draft')
                rows = self._rows(main,old)
                if await rows.count()!=1:rows=await self._find_native_row(main,old,existing['id'])
                source_handle=await rows.element_handle()
                observed = await self._plain_candidate(target, old, rows,media_count=len(existing.get('observed_media',[])) or len(existing['media']))
                if observed['url'] != reference or not rich.same_entities(observed.get('entities',[]),existing.get('entities',[])) or observed.get('observed_media',[]) != existing.get('observed_media',[]):
                    raise MaxBlocked('existing_reference_changed')
                if await self._copy_native_reference(source_handle,target)!=(reference,existing['id']):raise MaxBlocked('existing_reference_changed')
                await self._open_message_menu(source_handle)
                menu=self.page.get_by_role('menu')
                await expect(menu).to_be_visible()
                if await menu.get_by_role('menuitem',name='Редактировать',exact=True).count()!=1:
                    raise MaxBlocked('native_edit_not_available')
                await menu.get_by_role('menuitem',name='Редактировать',exact=True).click()
                await expect(main.get_by_text(re.compile(r'^Редактирование (?:поста|сообщения)$'))).to_have_count(1)
                if await composer.evaluate(rich.TEXT_JS) != old:
                    raise MaxBlocked('edit_draft_mismatch')
                await rich.fill(self.page,composer,text,entities)
                # Guard the actual trusted Save click, including a mode closure
                # during pointerdown. No synthetic ID or provider state access.
                guard = await main.evaluate_handle("(main, x)=>{" + rich.SNAPSHOT_JS + r"""
                    let clicks=0, blocked=false;
                    const ready=()=>{
                        const rows=x.row?.isConnected && main.contains(x.row) ? [x.row] : [];
                        return main.isConnected && location.href===x.route &&
                            [...main.querySelectorAll('button')].some(e=>e.getAttribute('aria-label')===x.header) &&
                            [...main.querySelectorAll('*')].some(e=>e.children.length===0 && ['Редактирование поста','Редактирование сообщения'].includes(e.textContent)) &&
                            semanticText(main.querySelector(x.composer))===x.text && JSON.stringify(semanticSnapshot(main.querySelector(x.composer)))===x.snapshot && rows.length===1 &&
                            rows[0].classList.contains('messageWrapper--isOut') &&
                            !rows[0].querySelector('audio') &&
                            JSON.stringify([...rows[0].querySelectorAll('.media video source')].map(e=>e.src))===JSON.stringify(x.videos) &&
                            rows[0].querySelectorAll('.media').length===x.mediaContainers &&
                            JSON.stringify(semanticSnapshot(rows[0].querySelector('.bubbleContent > .text')))===x.oldSnapshot &&
                            JSON.stringify([...rows[0].querySelectorAll('.media img')].map(e=>e.currentSrc||e.src))===JSON.stringify(x.media);
                    };
                    const check=e=>{
                        if(!e.target.closest('button[aria-label="Отправить сообщение"]'))return;
                        if(!e.isTrusted || !ready() || clicks){blocked=true;e.preventDefault();e.stopImmediatePropagation();return;}
                        clicks++;
                    };
                    document.addEventListener('click',check,true);
                    return {ready, result:()=>({clicks,blocked}),stop:()=>document.removeEventListener('click',check,true)};
                }""", dict(row=source_handle,route=self.origin+'/'+target, composer=COMPOSER,text=text,old=old,snapshot=await composer.evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e));}'),oldSnapshot=await rows.locator('.bubbleContent > .text').evaluate('(e)=>{'+rich.SNAPSHOT_JS+'return JSON.stringify(semanticSnapshot(e));}'),mediaContainers=await rows.locator('.media').count(),videos=await rows.locator('.media video source').evaluate_all('(es)=>es.map(e=>e.src)'),media=await rows.locator('.media img').evaluate_all('(es)=>es.map(e=>e.currentSrc||e.src)'),
                            header='Открыть профиль '+self.targets[target].alias))
                state = dict(target=target,text=text,entities=list(entities),old_text=old,old_entities=existing.get('entities',[]),kind='feed',action='edit',
                    media=list(existing['media']),observed_media=list(existing.get('observed_media',[])),media_slots=len(existing.get('observed_media',[])) or len(existing['media']),scheduled_at=None,existing_id=existing['id'],
                    recovery_reference=reference,attempt_id=attempt_id,plan_digest=plan_digest)
                await hooks.checkpoint('MAX_EDIT_PREPARED', json.dumps(state))
                await hooks.emit_progress('submitting','running','{}')
                await self._account()
                await self._scope(target)
                self.lane.arm(attempt_id,plan_digest)
                armed = True
                await hooks.before_effect(attempt_id,plan_digest)
                await self._account()
                self._check_attempt_fuse(attempt_id,plan_digest)
                main = await self._scope(target)
                current = await self._plain_candidate(target,old,rows,media_count=len(existing.get('observed_media',[])) or len(existing['media']))
                if current['url'] != reference or current.get('observed_media',[]) != existing.get('observed_media',[]) or not await guard.evaluate('(g)=>g.ready()'):
                    raise MaxBlocked('edit_binding_or_mode_changed')
                await main.get_by_role('button',name='Отправить сообщение',exact=True).click()
                transition = await guard.evaluate('(g)=>g.result()')
                if transition != dict(clicks=1,blocked=False):
                    raise MaxBlocked('edit_transition_unverified')
                state['transition'] = transition
                await hooks.emit_progress('reading_back','running','{}')
                await expect(main.get_by_text(re.compile(r'^Редактирование (?:поста|сообщения)$'))).to_have_count(0)
                updated = self._rows(main,text)
                await expect(updated).to_have_count(1,timeout=self.timeout*1000)
                item = await self._plain_candidate(target,text,updated,media_count=len(existing.get('observed_media',[])) or len(existing['media']))
                if item['url'] != reference or not rich.same_entities(item.get('entities',[]),entities) or item.get('observed_media',[]) != existing.get('observed_media',[]):
                    raise MaxBlocked('edit_created_other_object')
                await hooks.checkpoint('MAX_EDIT_REFERENCE',json.dumps(dict(state,item=item)))
                await guard.evaluate('(g)=>g.stop()');await guard.dispose();guard=None
                await self._account()
                await self.page.goto(self.origin+'/'+target,wait_until='domcontentloaded')
                main = await self._scope(target)
                updated = self._rows(main,text)
                item = await self._plain_candidate(target,text,updated,media_count=len(existing.get('observed_media',[])) or len(existing['media']))
                await self._account()
                self._check_attempt_fuse(attempt_id,plan_digest)
                final = await self._plain_candidate(target,text,updated,media_count=len(existing.get('observed_media',[])) or len(existing['media']))
                if item['url'] != reference or final['url'] != reference or item.get('observed_media',[]) != existing.get('observed_media',[]) or final.get('observed_media',[]) != existing.get('observed_media',[]):
                    raise MaxBlocked('edit_created_other_object')
                await hooks.checkpoint('MAX_EDIT_OBSERVED',json.dumps(dict(state,item=final)))
                return dict(item=final,quarantine_released=False,history_complete=False,
                    attribution='requires_core_historical_evidence_validation')
        except BaseException as exc:
            if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):
                raise
            if armed:
                raise MaxBlocked('outcome_unknown') from None
            if isinstance(exc,MaxBlocked):
                raise
            raise MaxBlocked('edit_prepare_unavailable') from None
        finally:
            if guard is not None:
                try:
                    await guard.evaluate('(g)=>g.stop()');await guard.dispose()
                except Exception:
                    pass
            self._busy=False

    async def read(self, target, namespace='feed', *, native_item=None):
        """Bounded own text/image/video objects with native identity; no fabricated IDs."""
        if namespace == 'scheduled':
            from . import queue
            self._enter(target)
            try:
                async with asyncio.timeout(self.timeout):
                    return await queue.read(self,target,native_item)
            finally:
                self._busy=False
        if namespace != 'feed':
            raise MaxBlocked('unsupported_namespace')
        self._enter(target)
        try:
            async with asyncio.timeout(self.timeout):
                await self._account()
                await self.page.goto(self.origin+'/'+target,wait_until='domcontentloaded')
                main=await self._scope(target)
                rows=main.locator('.messageWrapper--isOut')
                # Header readiness is not history readiness: MAX loads message rows
                # asynchronously after navigation. This is a readiness wait only,
                # never positional item identity or authoritative empty history.
                await rows.locator('.bubbleContent > .text').first.wait_for(timeout=self.timeout*1000)
                texts=await rows.locator('.bubbleContent > .text').evaluate_all('(es)=>{'+rich.DOM_HELPERS+'return es.map(semanticText);}')
                if len(texts)>100:raise MaxBlocked('bounded_read_limit')
                items=[];incomplete=False
                # Snapshot candidate content, then rebind semantically: row indexes
                # are not stable across scrolling/rerenders (Playwright locator contract).
                for text in dict.fromkeys(reversed(texts)):
                    if not text:continue
                    row=self._rows(main,text,outgoing=True)
                    try:
                        if await row.count()!=1:
                            if not native_item:raise MaxBlocked('ambiguous_read_candidate')
                            row=await self._find_native_row(main,text,native_item)
                        if native_item:
                            # Establish exact identity before downloading media from
                            # any candidate. Unrelated rows are not evidence for this read.
                            _url,copied=await self._copy_native_reference(row,target)
                            if copied!=native_item:continue
                        if await row.locator('audio').count():
                            incomplete=True;continue
                        await self.page.bring_to_front()
                        await row.scroll_into_view_if_needed()
                        count=await row.locator('[aria-label="Прикрепленные фото"] > button').count()
                        item=await self._plain_candidate(target,text,row,media_count=count)
                    except MaxBlocked as exc:
                        if not native_item or str(exc) not in {'ambiguous_read_candidate','native_candidate_not_matching','nonexact_plain_candidate','rich_link_not_verified','native_copy_menu_unavailable'}:raise
                        incomplete=True
                        if await self.page.get_by_role('menu').count():await self.page.keyboard.press('Escape')
                        await self._scope(target)
                        continue
                    if native_item:
                        if item['id']==native_item:
                            await self._account();await self._scope(target)
                            fresh=await self._plain_candidate(target,text,row,media_count=len(item.get('observed_media',[])) or len(item['media']))
                            if fresh['url']!=item['url'] or fresh.get('observed_media',[])!=item.get('observed_media',[]):raise MaxBlocked('native_reference_changed')
                            return [fresh]
                    else:items.append(item)
                await self._account();await self._scope(target)
                if native_item or incomplete:raise MaxBlocked('exact_read_not_observed')
                return items
        finally:
            self._busy=False

    async def delete_plain(self, *, existing, attempt_id, plan_digest, hooks, _preparation_retry=False):
        """Delete the copied own native object for everyone, never a text-only match."""
        import json
        if not self.live_writes:
            raise MaxBlocked('writer_live_qualification_pending')
        try:
            target, text, reference = existing['target'], existing['text'], existing['url']
            if existing['namespace'] != 'feed' or not text:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise MaxBlocked('exact_plain_existing_required') from None
        self._enter(target)
        armed, guard = False, None
        phase="scope"
        try:
            self.lane.assert_clear()
            if self.targets[target].policy != 'test_group':
                raise MaxBlocked('published_channel_delete_denied')
            async with asyncio.timeout(self.timeout):
                await self._account()
                await self.page.goto(self.origin+'/'+target, wait_until='domcontentloaded')
                main = await self._scope(target)
                phase='native_read'
                row = self._rows(main,text)
                if await row.count()!=1:row=await self._find_native_row(main,text,existing['id'])
                handle=await row.element_handle()
                observed = await self._plain_candidate(target,text,row,media_count=len(existing.get('observed_media',[])) or len(existing['media']))
                if observed['url'] != reference or observed['id'] != existing['id'] or observed.get('observed_media',[]) != existing.get('observed_media',[]):
                    raise MaxBlocked('existing_reference_changed')
                phase='native_handle_recheck'
                if await self._copy_native_reference(handle,target)!=(reference,existing['id']):raise MaxBlocked('existing_reference_changed')
                phase='open_menu'
                await self._open_message_menu(handle)
                phase='delete_choice'
                await self.page.get_by_role('menu').get_by_role('menuitem',name='Удалить',exact=True).click()
                phase='dialog'
                dialog = self.page.get_by_role('dialog')
                await expect(dialog.get_by_text('Удалить сообщение',exact=True)).to_have_count(1)
                phase='everyone_checkbox'
                checkbox = dialog.get_by_role('checkbox',name='Удалить для всех?',exact=True)
                await checkbox.check()
                # Bind the actual connected row, not whichever row later matches text.
                phase='guard_capture'
                guard = await dialog.evaluate_handle("(dialog,x)=>{" + rich.SNAPSHOT_JS + """
                    const row=x.row, main=row.closest('main');
                    let clicks=0,removed=false,blocked=false;
                    const ready=()=>dialog.isConnected && main.isConnected && row.isConnected &&
                        location.href===x.route && [...main.querySelectorAll('button')].some(b=>b.getAttribute('aria-label')===x.header) && semanticText(row.querySelector('.bubbleContent > .text'))===x.text &&
                        row.classList.contains('messageWrapper--isOut') &&
                        JSON.stringify([...row.querySelectorAll('.media video source')].map(e=>e.src))===JSON.stringify(x.videos) &&
                        JSON.stringify([...row.querySelectorAll('.media img')].map(e=>e.currentSrc||e.src))===JSON.stringify(x.media) &&
                        dialog.querySelector('input[type=checkbox]')?.checked &&
                        [...dialog.querySelectorAll('*')].some(e=>!e.children.length&&e.textContent==='Удалить сообщение');
                    const watch=new MutationObserver(()=>{if(clicks===1&&!row.isConnected)removed=true;});
                    watch.observe(main,{childList:true,subtree:true});
                    const check=e=>{
                        const b=e.target.closest('button');if(!b||!dialog.contains(b)||b.textContent.trim()!=='Удалить')return;
                        if(!e.isTrusted||!ready()||clicks){blocked=true;e.preventDefault();e.stopImmediatePropagation();return;}clicks++;
                    };
                    document.addEventListener('click',check,true);
                    return {ready,result:()=>({clicks,removed,blocked}),stop:()=>{watch.disconnect();document.removeEventListener('click',check,true);}};
                }""", dict(row=handle,videos=await row.locator('.media video source').evaluate_all('(es)=>es.map(e=>e.src)'),route=self.origin+'/'+target,text=text,media=await row.locator('.media img').evaluate_all('(es)=>es.map(e=>e.currentSrc||e.src)'),header='Открыть профиль '+self.targets[target].alias))
                state=dict(target=target,text=text,entities=existing.get('entities',[]),kind='feed',action='delete',media=list(existing['media']),observed_media=list(existing.get('observed_media',[])),media_slots=len(existing.get('observed_media',[])) or len(existing['media']),scheduled_at=None,
                    existing_id=existing['id'],recovery_reference=reference,attempt_id=attempt_id,plan_digest=plan_digest)
                await hooks.checkpoint('MAX_DELETE_PREPARED',json.dumps(state))
                await self._account();await self._scope(target)
                self.lane.arm(attempt_id,plan_digest);armed=True
                await hooks.before_effect(attempt_id,plan_digest)
                await self._account();await self._scope(target)
                await self.page.bring_to_front()
                self._check_attempt_fuse(attempt_id,plan_digest)
                if not await guard.evaluate('(g)=>g.ready()'):raise MaxBlocked('delete_binding_changed')
                await dialog.get_by_role('button',name='Удалить',exact=True).click()
                await expect(dialog).to_have_count(0)
                await handle.wait_for_element_state('hidden')
                transition=await guard.evaluate('(g)=>g.result()')
                if transition!=dict(clicks=1,removed=True,blocked=False):raise MaxBlocked('delete_transition_unverified')
                state.update(transition=transition,item=observed)
                await hooks.checkpoint('MAX_DELETE_CONFIRMED',json.dumps(state))
                await guard.evaluate('(g)=>g.stop()');await guard.dispose();guard=None
                await self._account()
                await self.page.goto(self.origin+'/'+target,wait_until='domcontentloaded')
                main=await self._scope(target)
                await self._remaining_rows_exclude(main,text,existing['id'])
                self._check_attempt_fuse(attempt_id,plan_digest)
                observed['observed_at']=datetime.now(timezone.utc).isoformat()
                await hooks.checkpoint('MAX_DELETE_OBSERVED',json.dumps(dict(state,item=observed)))
                return dict(item=observed,quarantine_released=False)
        except BaseException as exc:
            if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
            if armed:raise MaxBlocked('outcome_unknown') from None
            if isinstance(exc,MaxBlocked):raise
            if (isinstance(exc,PlaywrightError) and not _preparation_retry
                    and phase in {'native_read','native_handle_recheck','open_menu'}):
                # Read-only preparation can lose a native row during rerender.
                # Reacquire once by copied ID, never retry a Delete confirmation.
                self._busy=False
                return await self.delete_plain(existing=existing,attempt_id=attempt_id,
                    plan_digest=plan_digest,hooks=hooks,_preparation_retry=True)
            raise MaxBlocked('delete_prepare_unavailable_'+phase+'_'+type(exc).__name__.lower()) from None
        finally:
            if guard is not None:
                try:await guard.evaluate('(g)=>g.stop()');await guard.dispose()
                except Exception:pass
            self._busy=False

    async def _download_media(self, row, target, count, *, namespace='feed'):
        """Actual UI downloads, not rotating CDN URLs or invented native IDs."""
        import hashlib
        import io
        from pathlib import Path
        from PIL import Image
        result=[]
        for slot in range(count):
            await self._scope(target,namespace);await self.page.bring_to_front()
            tiles=row.locator('[aria-label="Прикрепленные фото"] > button')
            await expect(tiles).to_have_count(count)
            tile=tiles.nth(slot)
            video=await tile.locator('video').count()==1
            if video:
                # Observed nested player controls intercept centre clicks. Native
                # keyboard activation opens this exact outer media tile once.
                await tile.press('Enter')
            else:await tile.click()
            dialog=self.page.get_by_role('dialog')
            await expect(dialog).to_have_count(1)
            download=None
            try:
                async with self.page.expect_download(timeout=self.timeout*1000) as pending:
                    await dialog.get_by_role('button',name='Скачать видео' if video else 'Скачать',exact=True).click()
                download=await pending.value
                if await download.failure():raise MaxBlocked('media_download_failed')
                path=await download.path()
                with Path(path).open('rb') as stream:data=stream.read(20*1024*1024+1)
                if not data or len(data)>20*1024*1024:raise MaxBlocked('media_download_size')
                if video:
                    from social_operations.video_assets import verify_video
                    await asyncio.to_thread(verify_video,data,'video/mp4',artifact_root=Path(path).parent)
                    mime='video/mp4'
                else:
                    with Image.open(io.BytesIO(data)) as image:
                        mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}.get(image.format)
                        if not mime or image.width*image.height>25_000_000:raise MaxBlocked('media_download_format')
                        image.verify()
                result.append(dict(kind='download_sha256',slot=slot,sha256=hashlib.sha256(data).hexdigest(),mime=mime,size=len(data)))
            finally:
                if download is not None:await download.delete()
                await dialog.get_by_role('button',name='Закрыть',exact=True).click()
            await self._scope(target,namespace)
        return result

    async def _plain_candidate(self, target, text, row, *, media_count=0):
        await self._scope(target)
        await expect(row).to_have_count(1)
        await self.page.bring_to_front()
        await row.scroll_into_view_if_needed()
        async def content():
            if ('messageWrapper--isOut' not in (await row.get_attribute('class') or '').split()
                    or await row.locator('.bubbleContent > .text').evaluate(rich.TEXT_JS)!=text
                    or await row.locator('audio').count()
                    or (not media_count and await row.locator('.media').count())):
                raise MaxBlocked('nonexact_plain_candidate')
            styled=await rich.capture(row.locator('.bubbleContent > .text'))
            await expect(row.locator('.media img,.media video')).to_have_count(media_count,timeout=self.timeout*1000)
            video_count=await row.locator('.media video').count()
            for index in range(media_count-video_count):
                await expect(row.locator('.media img').nth(index)).to_have_attribute('src',re.compile(r'^https://i\.oneme\.ru/'),timeout=self.timeout*1000)
            images=await row.locator('.media img').evaluate_all('(es)=>es.map(e=>e.currentSrc||e.src)')
            videos=await row.locator('.media video source').evaluate_all('(es)=>es.map(e=>e.src)')
            if len(images)+video_count!=media_count or len(videos)!=video_count:
                raise MaxBlocked('nonexact_plain_candidate')
            # Observed rendered media origin. Blob previews are never provider IDs.
            if any(not re.fullmatch(r'https://i\.oneme\.ru/[^\s]+',value) for value in images):
                raise MaxBlocked('media_identity_unavailable')
            if any(not re.fullmatch(r'https://[^/]+\.okcdn\.ru/[^\s]*',value) for value in videos):
                raise MaxBlocked('video_source_unavailable')
            return dict(images=images,videos=videos,entities=styled['entities'])
        media=await content()
        reference,native_id=await self._copy_native_reference(row,target)
        if await content()!=media:raise MaxBlocked('candidate_changed_during_copy')
        downloaded=await self._download_media(row,target,media_count) if media_count else []
        await self._scope(target)
        if media_count:
            await content()
            repeated,_=await self._copy_native_reference(row,target)
            if repeated!=reference:raise MaxBlocked('media_post_reference_changed')
        return dict(id=native_id,url=reference,target=target,namespace='feed',text=text,
            media=[],observed_media=downloaded,entities=media['entities'],scheduled_at=None,observed_at=datetime.now(timezone.utc).isoformat())

    async def _open_message_menu(self, row):
        # A media row's centre is the image viewer, not the message menu.
        # Use the verified caption surface; never infer identity from coordinates.
        if isinstance(row,ElementHandle):
            captions=await row.query_selector_all('.bubbleContent > .text')
            if len(captions)!=1 or not await row.evaluate('e=>e.isConnected'):raise MaxBlocked('native_row_detached')
            caption=captions[0]
        else:
            caption=row.locator('.bubbleContent > .text')
            await expect(caption).to_have_count(1)
        await caption.click(button='right',timeout=self.timeout*1000)

    async def _remaining_rows_exclude(self,main,text,native_id):
        """After durable trusted removal only; not standalone absence proof."""
        rows=self._rows(main,text)
        handles=await rows.element_handles()
        if len(handles)>100:raise MaxBlocked('bounded_native_candidates')
        for handle in handles:
            _url,copied=await self._copy_native_reference(handle,self.page.url.rsplit('/',1)[-1])
            if copied==native_id:raise MaxBlocked('deleted_native_item_still_present')

    async def _connected_row(self,row):
        if isinstance(row,ElementHandle):
            if not await row.evaluate('e=>e.isConnected'):raise MaxBlocked('native_row_detached')
        else:await expect(row).to_have_count(1)

    async def _find_native_row(self,main,text,native_id):
        """Enumerate candidates read-only; only copied native IDs select a row.

        Indexes are temporary locator mechanics, never object identities. A
        retained DOM handle is rechecked after each copy and before return.
        """
        rows=self._rows(main,text,outgoing=True)
        handles=await rows.element_handles()
        if not 1<=len(handles)<=100:raise MaxBlocked('bounded_native_candidates')
        for handle in handles:
            _url,copied=await self._copy_native_reference(handle,self.page.url.rsplit('/',1)[-1])
            if copied!=native_id:continue
            index=await rows.evaluate_all('(es,h)=>es.indexOf(h)',handle)
            if index<0:raise MaxBlocked('native_row_detached')
            candidate=rows.nth(index)
            if not await candidate.evaluate('(e,h)=>e===h',handle):raise MaxBlocked('native_row_reordered')
            return candidate
        raise MaxBlocked('native_candidate_not_matching')

    async def _copy_native_reference(self, row, target):
        """Observed message-menu recipe; never infer an ID from row position."""
        import uuid
        await self._scope(target)
        await self._connected_row(row)
        # Identity validation uses another page; activate our own message page
        # before clipboard and pointer interactions (never a recovered user tab).
        await self.page.bring_to_front()
        await self._scope(target)
        # A failed copy must not accidentally reuse a previous clipboard receipt.
        sentinel = 'vibepublish-copy-' + uuid.uuid4().hex
        await self.page.evaluate('(value)=>navigator.clipboard.writeText(value)', sentinel)
        # MAX can detach its transient menu during a feed rerender. Retrying
        # this read-only menu is safe; never reuse this loop around Send/Save.
        for opening in range(2):
            await self._scope(target)
            await self._connected_row(row)
            await self._open_message_menu(row)
            menu = self.page.get_by_role('menu')
            try:
                await menu.get_by_role('menuitem', name='Скопировать ссылку на сообщение', exact=True).click(
                    timeout=min(self.timeout*1000, 2000))
                break
            except PlaywrightTimeoutError:
                await self._scope(target)
                if opening or await menu.count():
                    # Only a disappeared menu is reopened. Existing but disabled,
                    # unfamiliar or ambiguous controls are not force-clicked.
                    raise MaxBlocked('native_copy_menu_unavailable') from None
                # This is still an observation, not a second social effect.
                await self.page.evaluate('(value)=>navigator.clipboard.writeText(value)', sentinel)
        value = await self.page.evaluate('navigator.clipboard.readText()')
        match = re.fullmatch(r'https://max\.ru/c/(-[1-9][0-9]*)/([A-Za-z0-9_-]+)', value)
        if not match or match[1] != target:
            raise MaxBlocked('native_reference_scope_mismatch')
        await self._scope(target)
        return value, match[2]

    def _check_attempt_fuse(self, attempt, plan):
        import json
        import os
        try:
            fd = os.open(self.lane.marker, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError()
            saved = json.loads(raw)
        except (OSError, ValueError):
            raise MaxBlocked('recovery_quarantine_required') from None
        if saved != {'attempt_id': attempt, 'plan_digest': plan}:
            raise MaxBlocked('recovery_attempt_mismatch')

    async def reconcile(self, state):
        """DOM first; optional scoped visual corroboration, then ONE fresh DOM read.

        Neither the model nor its screenshot replaces native-reference checks.
        Identity/content/quarantine failures never enter model-assisted recovery.
        """
        if state.get('action')=='forward':
            from .engagement import forward_candidate
            self._check_attempt_fuse(state['attempt_id'],state['plan_digest'])
            item=await forward_candidate(self,state)
            return dict(item=item,quarantine_released=False)
        if state.get('action')=='reply':
            from .engagement import verify_reply
            result=await self._reconcile_dom(state)
            return dict(result,item=await verify_reply(self,result['item'],state['reply_to']))
        if state.get('action')=='react':
            from .engagement import reconcile_reaction
            return await reconcile_reaction(self,state)
        if state.get('kind')=='scheduled':
            from . import queue
            return await queue.reconcile(self,state)
        if state.get('action') == 'delete':
            return await self._reconcile_delete(state)
        try:
            return await self._reconcile_dom(state)
        except MaxBlocked as exc:
            if self.visual_recovery is None or str(exc) not in {
                    'native_copy_menu_unavailable', 'recovery_observation_unavailable',
                    'recovery_observation_deadline'}:
                raise
        self._enter(state['target'])
        try:
            try:
                evidence = await self.visual_recovery.observe(self, state)
            except MaxBlocked:
                raise
            except Exception:
                # No provider error payload, screenshot text or secrets in core errors.
                raise MaxBlocked('visual_observation_unavailable') from None
        finally:
            self._busy = False
        if not evidence['exact_text_match']:
            raise MaxBlocked('visual_text_unconfirmed')
        # No recursion, Send/Save, or manual release. Original native checks run again.
        result = await self._reconcile_dom(state)
        return dict(result, visual_evidence=evidence)

    async def _reconcile_delete(self, state):
        # Absence alone is never a tombstone. Require the persisted trusted click
        # and removal of the exact previously native-bound connected row.
        item=state.get('item',{})
        if (state.get('transition') != dict(clicks=1,removed=True,blocked=False)
                or item.get('url') != state.get('recovery_reference')
                or item.get('id') != state.get('existing_id')
                or item.get('text') != state.get('text')
                or item.get('target') != state.get('target') or item.get('observed_media',[]) != state.get('observed_media',[])):
            raise MaxBlocked('delete_confirmation_evidence_required')
        target=state['target'];self._enter(target)
        try:
            async with asyncio.timeout(self.timeout):
                for _ in range(2):
                    self._check_attempt_fuse(state['attempt_id'],state['plan_digest'])
                    await self._account()
                    await self.page.goto(self.origin+'/'+target,wait_until='domcontentloaded')
                    main=await self._scope(target)
                    await self._remaining_rows_exclude(main,state['text'],state['existing_id'])
                return dict(item=dict(item,observed_at=datetime.now(timezone.utc).isoformat()),quarantine_released=False)
        finally:self._busy=False

    async def _reconcile_dom(self, state):
        """Observation only: no execute, checkpoint write, or fuse release.

        Accept an exact reference supplied by the trusted recovery caller, not
        text discovery as an attribution certificate. Core must independently
        validate the historical chain and persist its resolution before release.
        Missing historical receipt/evidence is NOT repaired by this method.
        A saved native reference also permits exact ordinary-text observation;
        task markers are optional locator hints, never appended to user content.
        """
        try:
            target, text = state['target'], state['text']
            reference = state['recovery_reference']
            marker = state.get('task_marker', text)
            attempt, plan = state['attempt_id'], state['plan_digest']
            if (state['kind'] != 'feed' or state['action'] not in {'publish', 'edit','reply'}
                    or not isinstance(state['media'],list) or len(state['media'])>10 or state['scheduled_at'] is not None
                    or not isinstance(text, str) or not text or len(text) > 4000
                    or not isinstance(marker, str) or not marker
                    or ('task_marker' in state and len(marker) < 16)
                    or text.count(marker) != 1 or not attempt or not plan):
                raise ValueError()
            match = re.fullmatch(r'https://max\.ru/c/(-[1-9][0-9]*)/([A-Za-z0-9_-]+)', reference)
            if not match or match[1] != target:
                raise ValueError()
            if state['action'] == 'edit' and (state.get('existing_id') != match[2]
                    or not isinstance(state.get('old_text'), str) or not state['old_text']
                    or state['old_text'] == text):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise MaxBlocked('recovery_evidence_required') from None
        self._enter(target)
        try:
            # Match, but NEVER clear, the original durable quarantine.
            def check_fuse():
                self._check_attempt_fuse(attempt, plan)
            check_fuse()
            observations = []
            async with asyncio.timeout(self.timeout):
                for _ in range(2):
                    await self._account()
                    await self.page.goto(self.origin + '/' + target, wait_until='domcontentloaded')
                    main = await self._scope(target)
                    # Search ONLY the intended pane, not account-wide snippets.
                    candidates = self._rows(main,text)
                    await expect(candidates).to_have_count(1, timeout=self.timeout*1000)
                    row = candidates
                    if 'messageWrapper--isOut' not in (await row.get_attribute('class') or '').split():
                        raise MaxBlocked('recovery_not_outgoing')
                    content = row.locator('.bubbleContent > .text')
                    await expect(content).to_have_count(1)
                    if await content.evaluate(rich.TEXT_JS) != text:
                        raise MaxBlocked('recovery_content_changed')
                    first=await self._plain_candidate(target,text,row,media_count=state.get('media_slots',len(state['media'])))
                    if state.get('observed_media') and first.get('observed_media',[])!=state['observed_media']:
                        raise MaxBlocked('recovery_media_not_verified')
                    value,native_id=first['url'],first['id']
                    if value != reference:
                        raise MaxBlocked('recovery_native_reference_mismatch')
                    await self._account()
                    await self._scope(target)
                    # Re-acquire after the awaited account callback/re-render.
                    await expect(candidates).to_have_count(1)
                    if await candidates.locator('.bubbleContent > .text').evaluate(rich.TEXT_JS) != text:
                        raise MaxBlocked('recovery_content_changed')
                    if 'messageWrapper--isOut' not in (await candidates.get_attribute('class') or '').split():
                        raise MaxBlocked('recovery_not_outgoing')
                    fresh=await self._plain_candidate(target,text,candidates,media_count=state.get('media_slots',len(state['media'])))
                    if fresh.get('observed_media',[])!=first.get('observed_media',[]) or (observations and fresh.get('observed_media',[])!=observations[-1].get('observed_media',[])):
                        raise MaxBlocked('recovery_media_not_verified')
                    second=fresh['url']
                    if second != reference:
                        raise MaxBlocked('recovery_native_reference_mismatch')
                    check_fuse()
                    observations.append(dict(id=native_id, url=reference, target=target,
                        namespace='feed',text=text,entities=fresh.get('entities',[]),media=[],observed_media=fresh.get('observed_media',[]),scheduled_at=None,
                        observed_at=datetime.now(timezone.utc).isoformat()))
                return dict(item=observations[-1], observations=observations,
                    attempt_id=attempt, plan_digest=plan, observation_only=True,
                    attribution='requires_core_historical_evidence_validation',
                    candidate_scope='loaded_target_rows_only', history_complete=False,
                    quarantine_released=False)
        except MaxBlocked:
            raise
        except TimeoutError:
            raise MaxBlocked('recovery_observation_deadline') from None
        except Exception:
            raise MaxBlocked('recovery_observation_unavailable') from None
        finally:
            self._busy = False
