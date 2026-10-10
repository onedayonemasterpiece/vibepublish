"""Named-link edits preserve the existing Telegram photo and native identity."""
import pytest

from adapters.telegram_direct import DirectTargetTelegramAdapter
from social_operations.rich_text import from_native, utf16
from social_operations.worker import Worker
from tests.providers.scripted import ScriptedTL, tg_message
from tests.providers.test_core_integration import runtime, call, result

REGISTRATION = "https://app.myatom.ru/event/7873af3a-b103-44c9-89cb-164b273b03fc"
VK = "https://vk.com/club231828790"
MAX = "https://max.ru/channel_kenigevents"


@pytest.mark.asyncio
async def test_named_registration_link_edit_preserves_photo_footer_identity_and_replay(runtime):
    store, actor, transports, app, _worker = runtime
    transport = transports["telegram"]
    transport.messages[(101, 77)] = tg_message(77, text="Original caption", photo=900)
    adapter = DirectTargetTelegramAdapter(
        transport, connection_id="telegram", tl=ScriptedTL(), clock=store.clock
    )
    worker = Worker(store, {"telegram": adapter})
    read = await call(app, actor, "read", {"query": {"kind": "feed", "destination": "telegram"}})
    await worker.run_once()
    item, = result(store, actor, read)["items"]
    content = {"paragraphs": [
        [{"kind": "text", "text": "🌍 Как звучит Земля?"}],
        [{"kind": "link", "label": "Зарегистрироваться", "url": REGISTRATION}],
        [{"kind": "link", "label": "ВКонтакте", "url": VK},
         {"kind": "text", "text": "  ·  "},
         {"kind": "link", "label": "MAX", "url": MAX}],
    ]}
    args = {"item_ref": item["ref"], "change": {"kind": "edit", "content": content},
            "request_key": "native-named-link-fixture"}
    accepted = await call(app, actor, "publication_update", args)
    await worker.run_once()
    edited = result(store, actor, accepted)
    assert edited["state"] == "verified", edited
    remote = transport.messages[(101, 77)]
    assert remote.id == 77 and remote.media.photo.id == 900
    assert len(transport.messages) == 1 and not transport.scheduled
    assert not transport.uploads and transport.effects == 1
    assert remote.message == "🌍 Как звучит Земля?\n\nЗарегистрироваться\n\nВКонтакте  ·  MAX"
    entities = from_native(remote.message, remote.entities)
    assert [entity["url"] for entity in entities] == [REGISTRATION, VK, MAX]
    assert entities[0]["offset"] == utf16("🌍 Как звучит Земля?\n\n")
    assert entities[0]["length"] == utf16("Зарегистрироваться")
    mutations = [name for name, _ in transport.calls if name in transport.MUTATIONS]
    assert mutations == ["EditMessageRequest"]
    replay = await call(app, actor, "publication_update", args)
    assert replay["operation_id"] == accepted["operation_id"]
    assert not await worker.run_once()
    assert transport.effects == 1
