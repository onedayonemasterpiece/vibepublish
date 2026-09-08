"""Child-process runner for the SAME RealMaxDriver, loopback, no live factory."""
import asyncio,json,sys,os
from types import SimpleNamespace
from pathlib import Path
from playwright.async_api import async_playwright
from adapters.max.live import RealMaxDriver,Target
from adapters.max.profile import ProfileLane

async def main():
    origin,root,mode=sys.argv[1:];root=Path(root)
    with ProfileLane(root/'profile') as lane:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            try:
                context=await browser.new_context(service_workers='block')
                await context.grant_permissions(['clipboard-read','clipboard-write'],origin=origin)
                async def route(r):
                    if r.request.url.startswith(origin+'/'): await r.continue_()
                    else:
                        (root/'outbound-attempt').touch();await r.abort()
                await context.route('**/*',route)
                page=await context.new_page();calls=0
                async def account():
                    nonlocal calls
                    calls+=1
                    if calls==3 and mode=='crash':
                        (root/'between-reads').touch();await asyncio.Event().wait()
                    return True
                d=RealMaxDriver(page,lane,targets=(Target('-101','Test Group','test_group'),),account_check=account,origin=origin,timeout=30)
                state=json.loads((root/'request.json').read_text())
                if mode=='submit-crash':
                    async def checkpoint(name, raw):
                        with (root/(name+'.json')).open('w') as stream:
                            stream.write(raw);stream.flush();os.fsync(stream.fileno())
                        if name=='MAX_NATIVE_REFERENCE':
                            (root/'after-submit-reference').touch()
                            await asyncio.Event().wait()
                    async def progress(*args): pass
                    async def dispatch(*args):
                        with (root/'dispatched').open('w') as stream:
                            stream.write(json.dumps(args));stream.flush();os.fsync(stream.fileno())
                    result=await d.submit_plain_candidate(target=state['target'],text=state['text'],
                        attempt_id=state['attempt_id'],plan_digest=state['plan_digest'],
                        hooks=SimpleNamespace(checkpoint=checkpoint,emit_progress=progress,before_effect=dispatch))
                else:
                    result=await d.reconcile(state)
                (root/'result.json').write_text(json.dumps(result))
            finally: await browser.close()

if __name__=='__main__':asyncio.run(main())
