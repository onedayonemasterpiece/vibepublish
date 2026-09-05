"""Independent loopback provider state. Test controls never used by the driver."""
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

ProfileLane = importlib.import_module('adapters.max.profile').ProfileLane
FixtureDriver = importlib.import_module('adapters.max.driver').FixtureDriver


@pytest.fixture
def server():
    class FixtureState(dict):
        before_effect = None
    state = FixtureState(items=[], effects=0, config={})
    lock = threading.Lock()
    html = Path(__file__).with_name('fixtures').joinpath('index.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, body, content_type):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/state':
                with lock:
                    body = json.dumps(state).encode()
                self.respond(body, 'application/json')
            elif self.path == '/':
                self.respond(html, 'text/html')
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != '/effect':
                self.send_error(404)
                return
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if state.before_effect is not None:
                try:
                    state.before_effect(request)
                except Exception:
                    self.send_error(500, 'fixture dispatch assertion failed')
                    return
            with lock:
                state['effects'] += 1
                if request['action'] == 'publish':
                    item = dict(id=f"native-{state['effects']}", target=request['target'],
                                namespace='scheduled' if request['scheduled_at'] else 'feed',
                                text=request['text'], media=request['media'], scheduled_at=request['scheduled_at'])
                    state['items'].append(item)
                    if state['config'].get('duplicate'):
                        state['items'].append(dict(item, id=item['id']+'-duplicate'))
                else:
                    item = next(x for x in state['items'] if x['id'] == request['existing'] and x['target'] == request['target'])
                    if request['action'] in {'cancel', 'delete'}:
                        state['items'].remove(item)
                    else:
                        item.update(text=request['text'], media=request['media'], scheduled_at=request['scheduled_at'])
            self.respond(b'{}', 'application/json')

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{httpd.server_port}', state
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest_asyncio.fixture
async def browser_driver(server, tmp_path):
    origin, state = server
    with ProfileLane(tmp_path/'profile') as lane:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(str(lane.root/'chromium'), headless=True)
            try:
                # Browser cannot make any external request, including injected assets.
                await context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                page = context.pages[0]
                await page.goto(origin)
                driver = FixtureDriver(page, lane, origin=origin, account='fixture-account',
                                       allowed_targets=frozenset({'channel-a'}))
                yield driver, state, page
            finally:
                await context.close()
