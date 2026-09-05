"""Authenticated HTTP and actual MCP SDK Streamable HTTP over one Application.

Development transport: locally provisioned revocable bearer tokens. Public OAuth
onboarding/TLS deployment is a separate gate. No provider worker runs in requests.
"""
from __future__ import annotations
import asyncio
import json
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, Mount
from .domain import DomainError, canonical
from .service import Application, SKILL
from .asset_ingress import MAX_UPLOAD_BYTES, upload_image


class AuthBoundary:
    def __init__(self, app, store, hosts):
        self.app, self.store, self.hosts = app, store, frozenset(hosts)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        try:
            headers = {k.decode().lower(): v.decode() for k,v in scope.get('headers', [])}
            host = headers.get('host', '').split(':', 1)[0]
            if host not in self.hosts:
                raise DomainError('invalid_host', next_action='contact_owner')
            origin = headers.get('origin')
            if origin:
                parsed = urlsplit(origin)
                if parsed.hostname not in self.hosts or parsed.scheme not in ('http', 'https') or parsed.username:
                    raise DomainError('invalid_origin', next_action='contact_owner')
            authorization = headers.get('authorization', '')
            if not authorization.startswith('Bearer '):
                raise DomainError('unauthorized', 'A service bearer token is required', 'reauthorize')
            scope['vibepublish.actor'] = self.store.authenticate(authorization[7:])
            if scope['method'] in ('POST', 'PUT', 'PATCH'):
                image_upload = scope['method'] == 'POST' and scope['path'] == '/v1/assets'
                body_limit = MAX_UPLOAD_BYTES if image_upload else 512*1024
                body = bytearray()
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        body.extend(message.get('body', b''))
                        if len(body) > body_limit:
                            raise DomainError('request_too_large')
                        if not message.get('more_body', False):
                            break
                # Do not pass malformed/deep JSON into either transport projection.
                try:
                    if not image_upload:
                        json.loads(body)
                except (ValueError, RecursionError):
                    raise DomainError('invalid_json') from None
                original_receive = receive
                consumed = False
                async def receive_body():
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                    return await original_receive()
                receive = receive_body
            return await self.app(scope, receive, send)
        except DomainError as exc:
            status = 401 if exc.code == 'unauthorized' else 413 if exc.code == 'request_too_large' else 403
            return await JSONResponse(exc.output(), status_code=status, headers={'WWW-Authenticate': 'Bearer'})(scope, receive, send)
        except TimeoutError:
            return await JSONResponse(DomainError('request_timeout').output(), status_code=408)(scope, receive, send)


def create_app(store, *, allowed_hosts=('127.0.0.1', 'localhost', 'testserver')):
    service = Application(store)
    mcp = Server('VibePublish', version='0.1.0')

    def actor():
        request = mcp.request_context.request
        if request is None:
            raise DomainError('unauthorized', next_action='reauthorize')
        return request.scope['vibepublish.actor']

    @mcp.list_tools()
    async def list_tools():
        return [types.Tool(**tool) for tool in service.tools(actor())]

    @mcp.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        result = await service.call(actor(), name, arguments)
        return types.CallToolResult(content=[types.TextContent(type='text', text=canonical(result))],
                                    structuredContent=result, isError='error' in result and 'operation_id' not in result)

    def authorize_skill():
        if not any(t['name'] == 'vibepublish_get_started' for t in service.tools(actor())):
            raise DomainError('access_denied', next_action='contact_owner')

    @mcp.list_resources()
    async def list_resources():
        authorize_skill()
        return [types.Resource(uri='vibepublish://skill', name='VibePublish skill', mimeType='text/markdown')]

    @mcp.list_resource_templates()
    async def list_resource_templates():
        current = actor()
        with store.connection() as db:
            current = store.current(db, current)
        if not current.scopes.intersection({'visual', 'publish'}):
            return []
        return [types.ResourceTemplate(uriTemplate='vibepublish://assets/{asset_id}', name='Private verified visual', mimeType='image/png')]

    @mcp.read_resource()
    async def read_resource(uri):
        if str(uri).startswith('vibepublish://assets/'):
            data, mime, _sha = service.read_asset(actor(), str(uri).removeprefix('vibepublish://assets/'))
            return [ReadResourceContents(content=data, mime_type=mime)]
        authorize_skill()
        if str(uri) != 'vibepublish://skill':
            raise DomainError('resource_not_found')
        return [ReadResourceContents(content=SKILL.read_text(), mime_type='text/markdown')]

    @mcp.list_prompts()
    async def list_prompts():
        authorize_skill()
        return [types.Prompt(name='vibepublish', description='Canonical VibePublish task instructions')]

    @mcp.get_prompt()
    async def get_prompt(name, arguments=None):
        authorize_skill()
        if name != 'vibepublish' or arguments:
            raise DomainError('invalid_prompt')
        return types.GetPromptResult(messages=[types.PromptMessage(role='user', content=types.TextContent(type='text', text=SKILL.read_text()))])

    manager = StreamableHTTPSessionManager(mcp, json_response=True, stateless=True, max_request_body_size=512*1024,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[h+':*' for h in allowed_hosts]+list(allowed_hosts),
            allowed_origins=[scheme+'://'+h+':*' for h in allowed_hosts for scheme in ('http','https')]))

    @asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    async def mcp_endpoint(scope, receive, send):
        await manager.handle_request(scope, receive, send)

    def endpoint(tool, *, mutation=False, target_field="publication_id"):
        async def run(request: Request):
            try:
                if request.method == 'GET':
                    args = dict(request.query_params)
                    for key in ('limit','wait_seconds'):
                        if key in args:
                            args[key] = int(args[key])
                    if tool == 'status':
                        args['ids'] = [request.path_params['id']]
                else:
                    args = await request.json()
                    if not isinstance(args, dict):
                        raise DomainError('invalid_input')
                    if mutation:
                        key = request.headers.get('idempotency-key')
                        if not key:
                            raise DomainError('idempotency_key_required')
                        if args.get('request_key', key) != key:
                            raise DomainError('idempotency_key_conflict')
                        args['request_key'] = key
                    if tool == 'publication_update':
                        if args.get(target_field, request.path_params['id']) != request.path_params['id']:
                            raise DomainError('publication_id_conflict')
                        args[target_field] = request.path_params['id']
                result = await service.call(request.scope['vibepublish.actor'], 'vibepublish_'+tool, args)
                failed = 'error' in result and 'operation_id' not in result
                status = 422 if failed else 202 if result.get('state') == 'accepted' else 200
                return JSONResponse(result, status_code=status)
            except (ValueError, TypeError, RecursionError):
                return JSONResponse(DomainError('invalid_input').output(), status_code=422)
            except DomainError as exc:
                return JSONResponse(exc.output(), status_code=422)
        return run

    upload_slots = asyncio.Semaphore(2)

    async def upload_endpoint(request):
        try:
            if upload_slots.locked():
                return JSONResponse(DomainError('asset_ingress_busy').output(), status_code=429)
            async with upload_slots:
                # Bound parallel decode memory and keep MCP/status responsive.
                from starlette.concurrency import run_in_threadpool
                result = await run_in_threadpool(upload_image, service, request.scope['vibepublish.actor'],
                                                 await request.body(), request.headers.get('content-type', ''),
                                                 request.headers.get('idempotency-key'))
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
        except DomainError as exc:
            status = 409 if exc.code == 'idempotency_conflict' else 403 if exc.code in {'access_denied', 'access_revoked'} else 422
            return JSONResponse(exc.output(), status_code=status, headers={'Cache-Control': 'no-store'})

    async def asset_endpoint(request):
        try:
            data, mime, sha = service.read_asset(request.scope['vibepublish.actor'], request.path_params['id'])
            return Response(data, media_type=mime, headers={'Cache-Control': 'no-store', 'X-Content-SHA256': sha,
                              'X-Content-Type-Options': 'nosniff'})
        except DomainError as exc:
            return JSONResponse(exc.output(), status_code=404, headers={'Cache-Control': 'no-store'})

    async def emoji_preview_endpoint(request):
        try:
            from .emoji_preview import render_catalog
            current = request.scope['vibepublish.actor']
            with store.tx() as db:
                current = store.current(db, current)
                cursor = request.query_params.get('cursor')
                offset = store.cursor_position(db, current, cursor, 'emoji_catalog', request.path_params['id']) if cursor else 0
                page = service.emojis.page(db, current, request.path_params['id'], offset)
            markup, headers = render_catalog(service, current, page)
            return Response(markup, media_type='text/html', headers=headers)
        except DomainError as exc:
            return JSONResponse(exc.output(), status_code=404, headers={'Cache-Control':'no-store'})

    routes = [Route('/v1/assets', upload_endpoint, methods=['POST']), Route('/v1/emoji/catalogs/{id}', emoji_preview_endpoint, methods=['GET']), Route('/v1/assets/{id}', asset_endpoint, methods=['GET']), Route('/v1/bootstrap', endpoint('get_started'), methods=['GET']),
              Route('/v1/operations/{id}', endpoint('status'), methods=['GET']),
              Route('/v1/publications/{id}/commands', endpoint('publication_update', mutation=True), methods=['POST']),
              Route('/v1/items/{id}/commands', endpoint('publication_update', mutation=True, target_field='item_ref'), methods=['POST'])]
    for path, name, mutation in [('/v1/publications','publish',True), ('/v1/reads','read',False),
        ('/v1/engagement/commands','engage',True), ('/v1/visuals/commands','visual',True), ('/v1/destinations/commands','destinations',True)]:
        routes.append(Route(path, endpoint(name, mutation=mutation), methods=['POST']))
    routes.append(Mount('/mcp', app=mcp_endpoint))
    return AuthBoundary(Starlette(routes=routes, lifespan=lifespan), store, allowed_hosts)
