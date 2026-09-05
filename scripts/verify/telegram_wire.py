"""Offline Telethon wire gate, usable before the separate core is delivered.

Default checks the real pinned SDK only. --core additionally checks the actual
VibePublish compiler against those independent constructors; missing core fails.
No TelegramClient, login, RPC, environment credentials or network are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone

SDK_VERSION = "1.44.0"
TEXT = "❤️👩🏽\u200d💻🇷🇺"
ENTITY_SPECS = (
    {"type": "custom_emoji", "offset": 0, "length": 2, "document_id": "5188445640325099838"},
    {"type": "custom_emoji", "offset": 2, "length": 7, "document_id": "5188470637034758005"},
    {"type": "custom_emoji", "offset": 9, "length": 4, "document_id": "5406749623865857008"},
)


def deny_network(event: str, args: tuple) -> None:
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("telegram_wire_gate_network_forbidden")


def cases():
    """Actual SDK constructors and arguments; not an alternate provider port."""
    from telethon import functions as f, types as t
    peer = t.InputPeerChannel(channel_id=1, access_hash=2)
    channel = t.InputChannel(channel_id=1, access_hash=2)
    at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    entities = [t.MessageEntityCustomEmoji(offset=e["offset"], length=e["length"],
                document_id=int(e["document_id"])) for e in ENTITY_SPECS]
    media = t.InputMediaPhoto(id=t.InputPhoto(id=3, access_hash=4, file_reference=b"fixture"))
    album = [t.InputSingleMedia(media=media, random_id=11, message=TEXT, entities=entities),
             t.InputSingleMedia(media=media, random_id=12, message="", entities=[])]
    values = {
        "emoji_set": (f.messages.GetStickerSetRequest, dict(stickerset=t.InputStickerSetShortName(short_name="Fixture"), hash=0)),
        "emoji_documents": (f.messages.GetCustomEmojiDocumentsRequest, dict(document_id=[int(e["document_id"]) for e in ENTITY_SPECS])),
        "app_config": (f.help.GetAppConfigRequest, dict(hash=0)),
        "scheduled": (f.messages.GetScheduledHistoryRequest, dict(peer=peer, hash=0)),
        "history": (f.messages.GetHistoryRequest, dict(peer=peer, offset_id=0, offset_date=None, add_offset=0, limit=10, max_id=0, min_id=0, hash=0)),
        "upload": (f.messages.UploadMediaRequest, dict(peer=peer, media=t.InputMediaUploadedPhoto(file=t.InputFile(id=5, parts=1, name="fixture.png", md5_checksum="0"*32)))),
        "send_text": (f.messages.SendMessageRequest, dict(peer=peer, message=TEXT, random_id=11, entities=entities, schedule_date=at)),
        "send_media": (f.messages.SendMediaRequest, dict(peer=peer, media=media, message=TEXT, random_id=11, entities=entities, schedule_date=at)),
        "send_album": (f.messages.SendMultiMediaRequest, dict(peer=peer, multi_media=album, schedule_date=at)),
        "forward": (f.messages.ForwardMessagesRequest, dict(from_peer=peer, id=[7,8], random_id=[11,12], to_peer=peer, schedule_date=at, drop_author=False)),
        "edit": (f.messages.EditMessageRequest, dict(peer=peer, id=7, message=TEXT, entities=entities, schedule_date=at)),
        "cancel": (f.messages.DeleteScheduledMessagesRequest, dict(peer=peer, id=[7,8])),
        "delete_channel": (f.channels.DeleteMessagesRequest, dict(channel=channel, id=[7,8])),
        "delete_messages": (f.messages.DeleteMessagesRequest, dict(id=[7,8], revoke=True)),
    }
    return entities, values


def roundtrip(value):
    from telethon.extensions.binaryreader import BinaryReader
    data = bytes(value)
    with BinaryReader(data) as reader:
        decoded = reader.tgread_object()
        if reader.read():
            raise AssertionError("unconsumed TL bytes")
    assert type(decoded) is type(value)
    assert bytes(decoded) == data
    return decoded


def verify(*, core: bool = False) -> dict:
    import telethon
    if telethon.__version__ != SDK_VERSION:
        raise RuntimeError(f"Expected Telethon {SDK_VERSION}, got {telethon.__version__}")
    entities, values = cases()
    for entity, spec in zip(entities, ENTITY_SPECS, strict=True):
        result = roundtrip(entity)
        assert (result.offset, result.length, str(result.document_id)) == (spec["offset"], spec["length"], spec["document_id"])
    compiler = None
    if core:
        from adapters.telegram import TelethonTypes, _REQUESTS
        from social_operations.rich_text import from_native, to_native
        compiler = TelethonTypes()
        assert set(_REQUESTS) == set(values), "Add a real wire case for every adapter RPC"
        generated = to_native(TEXT, list(ENTITY_SPECS), compiler)
        assert [bytes(x) for x in generated] == [bytes(x) for x in entities]
        assert from_native(TEXT, generated) == list(ENTITY_SPECS)
    reports = []
    for kind, (constructor, kwargs) in values.items():
        request = constructor(**kwargs)
        result = roundtrip(request)
        if "entities" in kwargs:
            assert [bytes(x) for x in result.entities] == [bytes(x) for x in entities]
        if "schedule_date" in kwargs:
            assert result.schedule_date == kwargs["schedule_date"]
        if compiler:
            assert bytes(compiler.request(kind, **kwargs)) == bytes(request), kind
        reports.append(dict(kind=kind, constructor=constructor.__name__, bytes=len(bytes(request)),
                            sha256=hashlib.sha256(bytes(request)).hexdigest()))
    return dict(sdk=SDK_VERSION, native_entities=len(entities), requests=reports,
                evidence="real_sdk_and_core_compiler" if core else "real_sdk_only_no_core",
                network_calls=0, live_provider_verified=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", action="store_true", help="require actual core/compiler integration")
    args = parser.parse_args()
    sys.addaudithook(deny_network)
    print(json.dumps(verify(core=args.core), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
