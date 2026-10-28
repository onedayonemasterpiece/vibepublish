"""W4: Telegram random_id replay after lost RPC response; all providers are scripted."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from adapters.fake import FakeProvider
from adapters.telegram import TelegramAdapter
from adapters.telegram_resilient import ResilientTelegramAdapter
from social_operations.domain import DomainError, timestamp
from social_operations.provider_diagnostics import diagnostic_scope, provider_call
from social_operations.service import Application
from social_operations.storage import Store
from social_operations.worker import Worker
from tests.providers.scripted import ScriptedTL, TelegramClient, obj
from tests.providers.test_native_adapters import NOW, Journal, asset, request


class DeduplicatingClient(TelegramClient):
    """Emulate Telegram's permanent per-peer random_id deduplication."""
    def __init__(self):
        super().__init__()
        self.sent_ids = {}

    async def __call__(self, req):
        name = type(req).__name__
        if name in {'SendMessageRequest', 'SendMediaRequest', 'SendMultiMediaRequest', 'ForwardMessagesRequest'}:
            random_ids = ([part.random_id for part in req.multi_media] if name == 'SendMultiMediaRequest'
                          else list(req.random_id) if name == 'ForwardMessagesRequest' else [req.random_id])
            if all(random_id in self.sent_ids for random_id in random_ids):
                self.calls.append((name, req))
                return NS(updates=[obj('UpdateMessageID', random_id=i, id=self.sent_ids[i])
                                   for i in random_ids])
            previous = self.next_id
            try:
                return await super().__call__(req)
            finally:
                for offset, random_id in enumerate(random_ids, start=1):
                    if self.next_id >= previous + offset:
                        self.sent_ids[random_id] = previous + offset
        return await super().__call__(req)


@pytest.mark.asyncio
@pytest.mark.parametrize('images', [0, 1, 2])
@pytest.mark.parametrize('scheduled', [False, True])
@pytest.mark.parametrize('adapter_cls', [TelegramAdapter, ResilientTelegramAdapter])
async def test_restart_lost_rpc_response_resolves_original_random_ids_no_duplicate(images, scheduled, adapter_cls):
    client = DeduplicatingClient()
    journal = Journal()
    r = request('telegram', assets=tuple(asset(i+1) for i in range(images)),
                scheduled_at=timestamp(NOW+3600) if scheduled else None)
    original = adapter_cls(client, connection_id='connection', tl=ScriptedTL(), clock=lambda: NOW)
    client.before_mutation = lambda _: len(journal.markers) == 1 or pytest.fail('missing first dispatch marker')
    prepared = await original.prepare(r, journal.hooks)

    def response_lost(_):
        raise OSError('lost response after provider accepted the post')

    client.after_mutation = response_lost
    with pytest.raises(DomainError) as failure:
        await original.execute(prepared, journal.hooks)
    assert failure.value.code == ('telegram_rpc_failed' if adapter_cls is TelegramAdapter
                                  else 'telegram_transport_unhealthy')
    assert client.effects == 1
    checkpoint = journal.checkpoint_json
    assert journal.checkpoints[-1][0] == 'telegram_prepared'
    assert len(journal.checkpoints[-1][1]['random_ids']) == max(1, images)

    client.after_mutation = None
    restarted = adapter_cls(client, connection_id='connection', tl=ScriptedTL(), clock=lambda: NOW)
    observed = await restarted.reconcile(r, checkpoint, journal.hooks)
    assert observed.observed == ('provider_scheduled' if scheduled else 'published')
    remote, = observed.items
    assert remote.member_ids == tuple(str(client.sent_ids[i]) for i in journal.checkpoints[0][1]['random_ids'])
    assert remote.media_hashes == tuple(a.sha256 for a in r.assets)
    assert client.effects == 1
    assert sum(name.startswith('Send') for name, _ in client.calls) == 2
    assert journal.checkpoints[-1][0] == 'telegram_response'


@pytest.mark.asyncio
async def test_worker_reconciles_accepted_lost_response_without_second_post(tmp_path):
    now = [float(NOW)]
    store = Store(tmp_path / 'ledger.sqlite', clock=lambda: now[0])
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    store.add_connection(actor, 'tg', 'telegram', account_type='mtproto_user')
    store.bind(actor, 'owner', 'telegram', 'tg', '-1000000000101')
    receipt = await Application(store).call(actor, 'vibepublish_publish',
                                            {'to': ['telegram'], 'content': {'text': 'Accepted once'}})

    client = DeduplicatingClient()
    def lose_first_response(_):
        raise OSError('response dropped after remote accepted')

    client.after_mutation = lose_first_response
    adapter = ResilientTelegramAdapter(client, connection_id='tg', tl=ScriptedTL(), clock=lambda: now[0])
    assert await Worker(store, {'tg': adapter}).run_once()
    assert client.effects == 1
    client.after_mutation = None

    now[0] += 31
    restarted = ResilientTelegramAdapter(client, connection_id='tg', tl=ScriptedTL(), clock=lambda: now[0])
    assert await Worker(store, {'tg': restarted}).run_once()
    result = store.receipt(actor, receipt['operation_id'])
    assert result['state'] == 'verified', result
    assert client.effects == 1


class FloodWaitError(Exception):
    code = 420
    seconds = 17


class CooldownClient:
    def __init__(self):
        self.calls = 0

    def is_connected(self):
        return True

    async def __call__(self, request):
        self.calls += 1
        if self.calls == 1:
            raise FloodWaitError('secret flood limit')
        return NS(messages=[])


@pytest.mark.asyncio
async def test_resilient_uses_shared_provider_call_to_keep_floodwait_retry_after():
    client = CooldownClient()
    adapter = ResilientTelegramAdapter(client, connection_id='connection', tl=ScriptedTL())
    events = []
    with diagnostic_scope(events.append):
        with pytest.raises(DomainError) as exc:
            await adapter._call('scheduled', peer=object(), hash=0)
        assert exc.value.code == 'telegram_cooldown'
        assert client.calls == 1
        assert events[-1]['provider_code'] == 420
        assert events[-1]['retry_after_s'] == FloodWaitError.seconds
        assert events[-1]['operation'] == 'scheduled'
        # The adapter never retries a started RPC internally; W1 worker controls
        # the next call through its single fixed-deadline transient retry policy.
        assert (await adapter._call('scheduled', peer=object(), hash=0)).messages == []
        assert client.calls == 2
        assert events[-1]['status'] == 'completed'


class FloodOnceProvider(FakeProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.flooded = False

    async def prepare(self, request, hooks):
        if not self.flooded:
            self.flooded = True
            with provider_call('telegram', 'scheduled') as diagnostic:
                diagnostic.update(provider_code=420, retry_after_s=17)
                raise DomainError('telegram_cooldown')
        return await super().prepare(request, hooks)


@pytest.mark.asyncio
async def test_worker_respects_floodwait_before_retrying(tmp_path):
    now = [float(NOW)]
    store = Store(tmp_path / 'ledger.sqlite', clock=lambda: now[0])
    actor = store.authenticate(store.create_principal('tenant', 'owner', owner=True))
    store.add_connection(actor, 'tg', 'telegram', account_type='fake')
    store.bind(actor, 'owner', 'telegram', 'tg', '-1000000000101')
    receipt = await Application(store).call(actor, 'vibepublish_publish',
                                            {'to': ['telegram'], 'content': {'text': 'FloodWait fixture'}})
    provider = FloodOnceProvider(tmp_path / 'remote.sqlite', 'telegram', clock=lambda: now[0])
    worker = lambda: Worker(store, {'tg': provider})

    assert await worker().run_once()
    with store.connection() as db:
        scheduled_at = db.execute('SELECT lease_until FROM operations WHERE id=?',
                                  (receipt['operation_id'],)).fetchone()[0]
    assert scheduled_at >= now[0] + 17
    assert provider.count('execute') == 0

    now[0] += 16
    assert not await worker().run_once()
    assert provider.count('execute') == 0
    # The worker claims a timed-out lease strictly after its deadline.
    now[0] += 2
    assert await worker().run_once()
    assert provider.count('execute') == 1
    assert store.receipt(actor, receipt['operation_id'])['state'] == 'verified'
