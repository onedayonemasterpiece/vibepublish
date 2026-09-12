from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from adapters.port import ReadRequest
from adapters.telegram import peer_key
from adapters.telegram_direct import DirectTargetTelegramAdapter
from tests.providers.scripted import ScriptedTL, obj
from tests.providers.test_native_adapters import NOW, Journal, request
from tests.providers.test_telegram_topics import (
    ForumTelegramClient,
    TARGET as NUMERIC_TARGET,
    topic_message,
)


TARGETS = ("-1004379835477", "-1000987654321")
PUBLIC = "publicforum"


class DialogHydrationClient:
    def __init__(self):
        self.get_entity_calls = []
        self.dialog_iterations = 0
        self.entities = [
            obj("Channel", id=4_379_835_477, broadcast=False, megagroup=True, forum=True),
            obj("Channel", id=987_654_321, broadcast=False, megagroup=True, forum=True),
        ]

    def is_connected(self):
        return True

    async def get_entity(self, target):
        self.get_entity_calls.append(target)
        raise ValueError("fixture cache miss")

    def iter_dialogs(self):
        async def iterate():
            self.dialog_iterations += 1
            for entity in self.entities:
                yield NS(entity=entity)
        return iterate()


class PublicForumClient(ForumTelegramClient):
    def __init__(self, *, forum=True):
        super().__init__()
        self.entity.username = PUBLIC
        self.entity.forum = forum
        self.messages[(101, 20)] = topic_message(20, "Message inside topic", topic="3")

    async def get_entity(self, target):
        assert target in {PUBLIC, int(NUMERIC_TARGET)}
        return self.entity


@pytest.mark.asyncio
async def test_new_peer_is_hydrated_even_if_not_bound_when_worker_started():
    client = DialogHydrationClient()
    adapter = DirectTargetTelegramAdapter(
        client,
        connection_id="conn",
        tl=ScriptedTL(),
        clock=lambda: NOW,
        bound_targets=(),
    )

    first = await adapter._entity(TARGETS[0])
    second = await adapter._entity(TARGETS[1])

    assert peer_key(first) == TARGETS[0]
    assert peer_key(second) == TARGETS[1]
    assert TARGETS[0] in adapter.bound_targets and TARGETS[1] in adapter.bound_targets
    assert client.dialog_iterations == 2


@pytest.mark.asyncio
async def test_public_username_topic_is_resolved_to_numeric_peer_before_effect():
    client = PublicForumClient(forum=True)
    adapter = DirectTargetTelegramAdapter(
        client, connection_id="connection", tl=ScriptedTL(), clock=lambda: NOW
    )
    journal = Journal()
    client.before_mutation = lambda _: len(journal.markers) == 1 or pytest.fail(
        "effect before durable marker"
    )
    original = replace(request("telegram", topic_root_id="3"), native_target=PUBLIC)

    prepared = await adapter.prepare(original, journal.hooks)
    assert prepared.request == original
    observation = await adapter.execute(prepared, journal.hooks)

    remote, = observation.items
    assert observation.observed == "published"
    assert remote.native_target == PUBLIC
    assert remote.reply_to_native_id == "3"
    mutation = next(req for name, req in client.calls if name == "SendMessageRequest")
    assert mutation.peer is client.entity
    assert mutation.reply_to.top_msg_id == 3
    assert client.effects == 1


@pytest.mark.asyncio
async def test_forum_message_link_resolves_actual_topic_from_provider_message():
    client = PublicForumClient(forum=True)
    adapter = DirectTargetTelegramAdapter(
        client, connection_id="connection", tl=ScriptedTL(), clock=lambda: NOW
    )
    journal = Journal()
    client.before_mutation = lambda _: len(journal.markers) == 1 or pytest.fail(
        "effect before durable marker"
    )
    # Admission passes the final message id, whether the copied URL used
    # /topic/message or ?thread=. The provider object is authoritative.
    original = replace(request("telegram", topic_root_id="20"), native_target=PUBLIC)

    prepared = await adapter.prepare(original, journal.hooks)
    observation = await adapter.execute(prepared, journal.hooks)

    remote, = observation.items
    assert remote.native_target == PUBLIC
    assert remote.reply_to_native_id == "3"
    mutation = next(req for name, req in client.calls if name == "SendMessageRequest")
    assert mutation.reply_to.top_msg_id == 3
    assert client.effects == 1


@pytest.mark.asyncio
async def test_public_permalink_in_regular_chat_means_chat_root_not_fake_topic():
    client = PublicForumClient(forum=False)
    adapter = DirectTargetTelegramAdapter(
        client, connection_id="connection", tl=ScriptedTL(), clock=lambda: NOW
    )
    journal = Journal()
    client.before_mutation = lambda _: len(journal.markers) == 1 or pytest.fail(
        "effect before durable marker"
    )
    original = replace(request("telegram", topic_root_id="3"), native_target=PUBLIC)

    prepared = await adapter.prepare(original, journal.hooks)
    observation = await adapter.execute(prepared, journal.hooks)
    remote, = observation.items

    assert remote.native_target == PUBLIC
    assert remote.reply_to_native_id is None
    mutation = next(req for name, req in client.calls if name == "SendMessageRequest")
    assert mutation.reply_to is None

    page = await adapter.read(
        ReadRequest("connection", PUBLIC, "thread", 10, topic_root_id="3"), journal.hooks
    )
    assert page.items
    assert all(item.native_target == PUBLIC for item in page.items)
    assert any(name == "GetHistoryRequest" for name, _ in client.calls)


@pytest.mark.asyncio
async def test_reconcile_uses_numeric_checkpoint_not_mutable_public_username():
    client = PublicForumClient(forum=True)
    adapter = DirectTargetTelegramAdapter(
        client, connection_id="connection", tl=ScriptedTL(), clock=lambda: NOW
    )
    journal = Journal()
    client.before_mutation = lambda _: len(journal.markers) == 1 or pytest.fail(
        "effect before durable marker"
    )
    original = replace(request("telegram", topic_root_id="3"), native_target=PUBLIC)
    prepared = await adapter.prepare(original, journal.hooks)
    observation = await adapter.execute(prepared, journal.hooks)
    assert observation.items[0].native_target == PUBLIC

    # Simulate username loss after the provider effect. Recovery must use the
    # numeric target already committed in the adapter checkpoint.
    client.entity.username = "renamed_elsewhere"
    recovered = await adapter.reconcile(original, journal.checkpoint_json, journal.hooks)
    assert recovered.observed == "published"
    assert recovered.items[0].native_target == PUBLIC
    assert client.effects == 1
