"""Native cancellation receipts over the real MCP transport, fully offline."""
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import socket
import subprocess
import sys

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import pytest

from adapters.telegram import TelegramAdapter
from social_operations.domain import canonical, timestamp
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import ScriptedTL, TelegramClient
from tests.providers.test_native_adapters import NOW, TARGETS


async def native_cancel(tmp_path):
    store = Store(tmp_path / 'ledger.sqlite', clock=lambda: NOW)
    token = store.create_principal('tenant', 'owner', owner=True)
    actor = store.authenticate(token)
    store.add_connection(actor, 'telegram', 'telegram', account_type='mtproto_user')
    store.bind(actor, actor.principal_id, 'telegram', 'telegram', TARGETS['telegram'])
    transport = TelegramClient()
    adapter = TelegramAdapter(transport, connection_id='telegram', tl=ScriptedTL(), clock=store.clock)
    app, worker = Application(store), Worker(store, {'telegram': adapter})
    scheduled_at = timestamp(NOW + 3600)
    accepted = await app.call(actor, 'vibepublish_publish', {
        'to': ['telegram'], 'content': {'text': 'Offline native cancellation'},
        'delivery': {'kind': 'at', 'at': scheduled_at}, 'request_key': 'schedule'})
    assert await worker.run_once()
    scheduled = (await app.call(actor, 'vibepublish_status', {'ids': [accepted['operation_id']]}))['receipts'][0]
    assert scheduled['state'] == 'scheduled'
    delivery, = scheduled['deliveries']
    assert delivery['requested_at'] == delivery['effective_at'] == scheduled_at
    cancelled = await app.call(actor, 'vibepublish_publication_update', {
        'publication_id': scheduled['resource_id'], 'expected_revision': 1,
        'change': {'kind': 'cancel'}, 'request_key': 'cancel'})
    assert await worker.run_once()
    assert transport.effects == 2 and transport.scheduled == {}
    assert not await worker.run_once()
    with store.connection() as db:
        child = db.execute('SELECT * FROM attempts WHERE operation_id=?', (cancelled['operation_id'],)).fetchone()
        assert json.loads(child['plan'])['scheduled_at'] is None
        assert json.loads(child['checkpoint'])['remote']['scheduled_at'] == scheduled_at
        assert child['state'] == 'cancelled'
    return store, token, actor, app, transport, cancelled['operation_id'], scheduled_at


def business_history(store, operation):
    with store.connection() as db:
        return {
            'operation': tuple(db.execute('SELECT * FROM operations WHERE id=?', (operation,)).fetchone()),
            'attempts': [tuple(row) for row in db.execute('SELECT * FROM attempts WHERE operation_id=?', (operation,))],
            'events': [tuple(row) for row in db.execute('SELECT * FROM events WHERE operation_id=? ORDER BY seq', (operation,))],
        }


async def mcp_status(store, token, operation, tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    process = subprocess.Popen([sys.executable, '-m', 'social_operations.cli', '--db', str(store.path),
                                'serve', '--port', str(port)], cwd=Path(__file__).resolve().parents[2],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with httpx.AsyncClient(trust_env=False) as http:
            for _ in range(150):
                assert process.poll() is None, 'Local fixture MCP server exited'
                try:
                    if (await http.get(base + '/v1/bootstrap')).status_code == 401:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(.03)
            else:
                pytest.fail('Local fixture MCP server did not start')
        async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + token}, trust_env=False) as http:
            async with streamable_http_client(base + '/mcp/', http_client=http) as (read, write, _):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    schema = next(t.outputSchema for t in tools.tools if t.name == 'vibepublish_status')
                    result = await session.call_tool('vibepublish_status', {'ids': [operation]})
                    assert not result.isError
                    # Validate exactly the published MCP status schema, not a hand-written subset.
                    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result.structuredContent)
                    return result.structuredContent
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy_null', [False, True])
async def test_native_cancel_status_schema_and_legacy_projection_without_rewrite(tmp_path, legacy_null):
    store, token, actor, app, transport, operation, scheduled_at = await native_cancel(tmp_path)
    with store.tx() as db:
        row = db.execute('SELECT id,result FROM attempts WHERE operation_id=?', (operation,)).fetchone()
        saved = json.loads(row['result'])
        if legacy_null:
            # Reproduce only the old persisted format in this private test database.
            saved['requested_at'] = None
            db.execute('UPDATE attempts SET result=? WHERE id=?', (canonical(saved), row['id']))
        else:
            assert 'requested_at' not in saved  # The writer itself, not merely projection, is fixed.
    before = business_history(store, operation)
    direct = store.receipt(actor, operation)
    assert direct['state'] == 'cancelled' and direct['operation_complete']
    assert direct['deliveries'][0]['effective_at'] == scheduled_at
    assert 'requested_at' not in direct['deliveries'][0]
    # Application.call performs the canonical output-schema validation too.
    via_application = await app.call(actor, 'vibepublish_status', {'ids': [operation]})
    via_mcp = await mcp_status(store, token, operation, tmp_path)
    for status in (via_application, via_mcp):
        receipt, = status['receipts']
        delivery, = receipt['deliveries']
        assert receipt['state'] == 'cancelled' and delivery['observed'] == 'cancelled'
        assert delivery['effective_at'] == scheduled_at and 'requested_at' not in delivery
    assert business_history(store, operation) == before
    assert transport.effects == 2 and transport.scheduled == {}
