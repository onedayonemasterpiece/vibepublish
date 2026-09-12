from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from adapters.telegram import peer_key
from adapters.telegram_direct import DirectTargetTelegramAdapter
from tests.providers.scripted import ScriptedTL, obj


TARGETS = ("-1004379835477", "-1000987654321")


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


@pytest.mark.asyncio
async def test_new_peer_is_hydrated_even_if_not_bound_when_worker_started():
    client = DialogHydrationClient()
    adapter = DirectTargetTelegramAdapter(
        client,
        connection_id="conn",
        tl=ScriptedTL(),
        clock=lambda: 1_800_000_000,
        bound_targets=(),
    )

    first = await adapter._entity(TARGETS[0])
    second = await adapter._entity(TARGETS[1])

    assert peer_key(first) == TARGETS[0]
    assert peer_key(second) == TARGETS[1]
    assert TARGETS[0] in adapter.bound_targets and TARGETS[1] in adapter.bound_targets
    assert client.dialog_iterations == 2
