"""Acceptance integration: durable forum checkpoints recover without redispatch.

All provider calls use an in-memory scripted transport, never Telegram credentials.
"""
import asyncio
import json
from dataclasses import replace

import pytest

from adapters.telegram import TelegramAdapter
from social_operations.assets import import_image
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import ScriptedTL
from tests.providers.test_native_adapters import NOW
from tests.providers.test_telegram_topics import ForumTelegramClient, TARGET
from tests.runtime.test_telegram_topics_runtime import TOPIC_URL, png


class StopAfterResponse(Worker):
    def hooks(self, *args, **kwargs):
        hooks = super().hooks(*args, **kwargs)

        async def checkpoint(transition, state):
            await hooks.checkpoint(transition, state)
            if transition == 'telegram_response':
                raise asyncio.CancelledError()

        return replace(hooks, checkpoint=checkpoint)


@pytest.mark.asyncio
@pytest.mark.parametrize('role', [None, 'image', 'document'])
async def test_topic_durable_response_survives_worker_restart_no_duplicate(tmp_path, role):
    now = [NOW]
    store = Store(tmp_path / 'ledger.sqlite', clock=lambda: now[0])
    token = store.create_principal('tenant', 'owner', owner=True)
    actor = store.authenticate(token)
    store.add_connection(actor, 'conn_tg', 'telegram', account_type='mtproto_user')
    store.bind(actor, 'owner', 'telegram', 'conn_tg', TARGET)
    client = ForumTelegramClient()
    adapter = TelegramAdapter(client, connection_id='conn_tg', tl=ScriptedTL(), clock=lambda: now[0])
    app = Application(store)
    args = {'to': ['telegram'], 'thread_ref': TOPIC_URL,
            'content': {'text': 'Durable topic checkpoint'}, 'request_key': 'restart-once'}
    if role:
        asset = import_image(store, actor, png((20, 40, 60)), 'image/png')
        args['media'] = [{'source': {'kind': 'asset', 'id': asset}, 'role': role}]
    receipt = await app.call(actor, 'vibepublish_publish', args)
    assert receipt['state'] == 'accepted'
    worker = StopAfterResponse(store, {'conn_tg': adapter}, worker_id='before-stop')
    with pytest.raises(asyncio.CancelledError):
        await worker.run_once()
    assert client.effects == 1
    with store.connection() as db:
        before = dict(db.execute('SELECT * FROM attempts WHERE operation_id=?',
                                 (receipt['operation_id'],)).fetchone())
    assert before['dispatched'] == 1
    assert json.loads(before['checkpoint'])['transition'] == 'telegram_response'
    assert json.loads(before['plan'])['topic_root_id'] == '3'
    now[0] += 31
    # Re-open the real SQLite fixture, and replace both worker and adapter.
    reopened = Store(tmp_path / 'ledger.sqlite', clock=lambda: now[0])
    restarted = Worker(reopened, {'conn_tg': TelegramAdapter(
        client, connection_id='conn_tg', tl=ScriptedTL(), clock=lambda: now[0])},
        worker_id='after-stop')
    assert await restarted.run_once()
    result = reopened.receipt(actor, receipt['operation_id'])
    assert result['state'] == 'verified', result
    assert client.effects == 1
    replay = await Application(reopened).call(actor, 'vibepublish_publish', args)
    assert replay['operation_id'] == receipt['operation_id']
    assert not await restarted.run_once()
    assert client.effects == 1
