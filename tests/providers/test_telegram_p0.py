from __future__ import annotations

from dataclasses import replace

import pytest

from adapters.port import ReadRequest
from adapters.telegram_resilient import ResilientTelegramAdapter
from tests.providers.scripted import ScriptedTL
from tests.providers.test_native_adapters import Journal, asset, request
from tests.providers.test_telegram_topics import (
    ForumTelegramClient,
    TARGET,
    topic_message,
)


class HealthyForumClient(ForumTelegramClient):
    def __init__(self):
        super().__init__()
        self.connected = True
        self.connects = 0

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connects += 1
        self.connected = True

    async def is_user_authorized(self):
        return True

    async def iter_dialogs(self):
        yield type("Dialog", (), {"entity": self.entity})()


@pytest.mark.asyncio
async def test_topic_5_document_publish_confirmation_and_private_readback_bytes():
    client = HealthyForumClient()
    client.messages[(101, 5)] = topic_message(5, "P0 topic root")
    adapter = ResilientTelegramAdapter(
        client,
        connection_id="connection",
        tl=ScriptedTL(),
        clock=lambda: 1_800_000_000,
        bound_targets=(TARGET,),
    )
    journal = Journal()
    client.before_mutation = lambda _: (
        len(journal.markers) == 1
        or pytest.fail("effect before durable marker")
    )

    media = replace(asset(55), role="document")
    provider_request = request(
        "telegram",
        assets=(media,),
        topic_root_id="5",
    )
    observed = await adapter.execute(
        await adapter.prepare(provider_request, journal.hooks),
        journal.hooks,
    )
    remote, = observed.items
    assert observed.observed == "published"
    assert remote.reply_to_native_id == "5"
    assert remote.provider_media[0].startswith("document:")
    assert remote.media_hashes == (media.sha256,)

    page = await adapter.read(
        ReadRequest(
            "connection",
            TARGET,
            "thread",
            10,
            topic_root_id="5",
        ),
        journal.hooks,
    )
    item, = page.items
    download, = page.downloads
    assert item.native_id == remote.native_id
    assert item.reply_to_native_id == "5"
    assert download.media_kind == "document"
    assert download.data == media.data
    assert item.observed_media[0].sha256 == media.sha256
